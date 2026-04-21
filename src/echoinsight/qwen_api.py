"""Small OpenAI-compatible API client used by EchoInsight.

The API configuration is read from an info.md file containing:

apikey = ...
model = qwen-4.7
base_url = https://open.bigmodel.cn/api/paas/v4

This module intentionally keeps API calling separate from the agentic pipeline so
OpenAI-compatible model connectivity can be tested independently.
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
class ModelSettings:
    api_key: str
    model: str
    base_url: str

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def load_qwen_settings(info_path: str | Path) -> ModelSettings:
    path = Path(info_path)
    if not path.exists():
        raise FileNotFoundError(f"Qwen info file not found: {path}")

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    missing = [key for key in ("apikey", "model", "base_url") if not values.get(key)]
    if missing:
        raise ValueError(f"Missing Qwen settings in {path}: {', '.join(missing)}")

    return ModelSettings(
        api_key=values["apikey"],
        model=values["model"],
        base_url=values["base_url"],
    )


class QwenClient:
    def __init__(
        self,
        info_path: str | Path,
        timeout: float = 45.0,
        request_delay: float = 0.2,
        rpm: float = 60.0,
        disable_thinking: bool = True,
        sglang_disable_thinking: bool = False,
        enable_thinking: bool | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        self.settings = load_qwen_settings(info_path)
        self.timeout = timeout
        self.request_delay = request_delay
        self.rpm = rpm
        self.disable_thinking = disable_thinking
        self.sglang_disable_thinking = sglang_disable_thinking
        self.enable_thinking = enable_thinking
        self.extra_body = extra_body or {}
        self._last_request_at = 0.0

    def chat(self, prompt: str, temperature: float = 0.1, max_retries: int = 2) -> str:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if self.extra_body:
            payload.update(self.extra_body)
        # Qwen-4.7 / Qwen-5 BigModel/Z.AI API: disable thinking for lower latency.
        # Official docs: {"thinking": {"type": "disabled"}}.
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        # ModelScope / some OpenAI-compatible providers accept enable_thinking
        # in the request body. Let explicit enable_thinking override defaults.
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking
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
            except requests.HTTPError as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                status_code = exc.response.status_code if exc.response is not None else None
                retry_after = self._retry_after_seconds(exc.response)
                is_429 = status_code == 429
                # longer backoff on provider rate limits
                if retry_after is not None:
                    backoff = retry_after
                elif is_429:
                    backoff = min(60.0, 10.0 * (attempt + 1))
                else:
                    backoff = min(8.0, 1.5 * (attempt + 1))
                time.sleep(backoff)
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(min(8.0, 1.5 * (attempt + 1)))

        raise RuntimeError(f"Qwen chat request failed after {max_retries + 1} attempts: {last_error}")

    def chat_json(self, prompt: str, temperature: float = 0.1, max_retries: int = 2) -> Any:
        last_content = ""
        for attempt in range(max_retries + 1):
            last_content = self.chat(prompt, temperature=temperature, max_retries=max_retries)
            parsed = parse_json_from_text(last_content)
            if parsed is not None:
                return parsed
            repaired = self._repair_json_response(prompt, last_content)
            if repaired is not None:
                return repaired
            if attempt < max_retries:
                time.sleep(0.5 + attempt)
        raise RuntimeError(f"Qwen did not return parseable JSON. Last content: {last_content[:500]}")

    def quick_check(self) -> dict[str, Any]:
        prompt = 'Return JSON only: {"ok": true, "message": "qwen api reachable", "thinking_disabled": true}'
        parsed = self.chat_json(prompt, temperature=0.0, max_retries=1)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected Qwen quick-check response: {parsed}")
        return parsed

    def _respect_delay(self) -> None:
        elapsed = time.time() - self._last_request_at
        rpm_delay = 60.0 / self.rpm if self.rpm and self.rpm > 0 else 0.0
        min_delay = max(self.request_delay, rpm_delay)
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self._last_request_at = time.time()

    def _repair_json_response(self, original_prompt: str, invalid_content: str) -> Any | None:
        prompt_tail = original_prompt[-1800:]
        content_tail = invalid_content[-1800:]
        repair_prompt = f"""Your previous answer was not valid JSON.
Rewrite it as valid JSON only.

Rules:
- Output JSON only.
- Do not include analysis, explanations, markdown, or code fences.
- Preserve the intended structure requested in the original prompt.

Original prompt tail:
{prompt_tail}

Previous response tail:
{content_tail}
"""
        try:
            repaired = self.chat(repair_prompt, temperature=0.0, max_retries=1)
        except Exception:
            return None
        return parse_json_from_text(repaired)

    @staticmethod
    def _retry_after_seconds(response: requests.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            parsed = float(value)
        except ValueError:
            return None
        return max(parsed, 0.0)


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
