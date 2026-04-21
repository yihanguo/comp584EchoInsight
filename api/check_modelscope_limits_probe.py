"""Probe whether ModelScope rate limiting is model-specific or account-wide.

This script does not modify existing project code. It sends a tiny text-only
request to one or more OpenAI-compatible ModelScope models and prints the HTTP
result for each model.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


DEFAULT_MODELS = [
    "Qwen/Qwen3.5-35B-A3B",
    "deepseek-ai/DeepSeek-V3.2",
]


def parse_info_md(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe ModelScope model availability and rate limits.")
    parser.add_argument(
        "--info",
        default=Path(__file__).with_name("info.md"),
        help="Path to info.md containing apikey/model/base_url.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override OpenAI-compatible ModelScope base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MODELSCOPE_API_KEY"),
        help="Override ModelScope API key.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help="Models to probe.",
    )
    parser.add_argument(
        "--text",
        default="9.9和9.11谁大？只回答结果。",
        help="Tiny text-only prompt.",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Send enable_thinking=True in extra_body.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        help="Pause between model probes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("The openai package is not installed. Run `pip install openai` first.", file=sys.stderr)
        return 3

    info = parse_info_md(args.info)
    api_key = args.api_key or info.get("apikey")
    base_url = args.base_url or info.get("base_url") or "https://api-inference.modelscope.cn/v1"

    if not api_key:
        print("Missing API key. Pass --api-key, set MODELSCOPE_API_KEY, or add apikey to info.md.", file=sys.stderr)
        return 2

    client = OpenAI(base_url=base_url, api_key=api_key)
    any_success = False

    print(f"Base URL: {base_url}")
    print(f"Models to probe: {', '.join(args.models)}")
    print(f"Enable thinking: {args.enable_thinking}")
    print("---")

    for idx, model in enumerate(args.models):
        print(f"[probe] model={model}")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": args.text}],
                stream=False,
                extra_body={"enable_thinking": args.enable_thinking},
            )
            content = response.choices[0].message.content
            print("status=OK")
            print(f"answer={content!r}")
            any_success = True
        except Exception as exc:
            status_code = getattr(getattr(exc, "status_code", None), "__int__", lambda: None)()
            if status_code is None:
                status_code = getattr(exc, "status_code", None)
            print(f"status=ERROR type={type(exc).__name__} status_code={status_code}")
            print(f"message={exc}")
        print("---")
        if idx < len(args.models) - 1 and args.pause_seconds > 0:
            time.sleep(args.pause_seconds)

    return 0 if any_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
