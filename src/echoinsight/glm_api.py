"""Small GLM API client used by EchoInsight.

The API configuration is read from an info.md file containing:

apikey = ...
model = glm-4.7
base_url = https://open.bigmodel.cn/api/paas/v4

This module intentionally keeps API calling separate from the agentic pipeline so
GLM connectivity can be tested independently.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class GLMSettings:
    api_key: str
    model: str
    base_url: str

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def load_glm_settings(info_path: str | Path) -> GLMSettings:
    path = Path(info_path)
    if not path.exists():
        raise FileNotFoundError(f"GLM info file not found: {path}")

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    missing = [key for key in ("apikey", "model", "base_url") if not values.get(key)]
    if missing:
        raise ValueError(f"Missing GLM settings in {path}: {', '.join(missing)}")

    return GLMSettings(
        api_key=values["apikey"],
        model=values["model"],
        base_url=values["base_url"],
    )


class GLMClient:
    def __init__(
        self,
        info_path: str | Path,
        timeout: float = 45.0,
        request_delay: float = 0.2,
        rpm: float = 60.0,
        disable_thinking: bool = True,
        sglang_disable_thinking: bool = False,
    ):
        self.settings = load_glm_settings(info_path)
        self.timeout = timeout
        self.request_delay = request_delay
        self.rpm = rpm
        self.disable_thinking = disable_thinking
        self.sglang_disable_thinking = sglang_disable_thinking
        self._last_request_at = 0.0

    def chat(self, prompt: str, temperature: float = 0.1, max_retries: int = 2) -> str:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        # GLM-4.7 / GLM-5 BigModel/Z.AI API: disable thinking for lower latency.
        # Official docs: {"thinking": {"type": "disabled"}}.
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        # SGLang/vLLM-compatible serving can use chat_template_kwargs. Keep this
        # opt-in because some hosted OpenAI-compatible APIs reject unknown fields.
        if self.sglang_disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            self._respect_delay()
            try:
                response = requests.post(
                    self.settings.chat_completions_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(min(8.0, 1.5 * (attempt + 1)))

        raise RuntimeError(f"GLM chat request failed after {max_retries + 1} attempts: {last_error}")

    def chat_json(self, prompt: str, temperature: float = 0.1, max_retries: int = 2) -> Any:
        last_content = ""
        for attempt in range(max_retries + 1):
            last_content = self.chat(prompt, temperature=temperature, max_retries=max_retries)
            parsed = parse_json_from_text(last_content)
            if parsed is not None:
                return parsed
            if attempt < max_retries:
                time.sleep(0.5 + attempt)
        raise RuntimeError(f"GLM did not return parseable JSON. Last content: {last_content[:500]}")

    def quick_check(self) -> dict[str, Any]:
        prompt = 'Return JSON only: {"ok": true, "message": "glm api reachable", "thinking_disabled": true}'
        parsed = self.chat_json(prompt, temperature=0.0, max_retries=1)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected GLM quick-check response: {parsed}")
        return parsed

    def _respect_delay(self) -> None:
        elapsed = time.time() - self._last_request_at
        rpm_delay = 60.0 / self.rpm if self.rpm and self.rpm > 0 else 0.0
        min_delay = max(self.request_delay, rpm_delay)
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self._last_request_at = time.time()


def parse_json_from_text(content: str) -> Any | None:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    match = re.search(r"(\{.*\}|\[.*\])", content, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None
