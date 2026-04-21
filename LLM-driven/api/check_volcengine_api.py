"""Smoke test for the Volcengine Ark OpenAI-compatible chat API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echoinsight.qwen_api import QwenClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Volcengine Ark chat connectivity.")
    parser.add_argument(
        "--info-path",
        default=str(Path(__file__).with_name("info_volcengine.md")),
        help="Path to info file containing apikey/model/base_url.",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Do not send thinking disabled flag.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = QwenClient(
        info_path=args.info_path,
        timeout=args.timeout,
        disable_thinking=not args.enable_thinking,
    )
    result = client.quick_check()
    print("Volcengine API check succeeded")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
