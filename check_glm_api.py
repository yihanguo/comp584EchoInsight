"""Check GLM API connectivity for EchoInsight."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echoinsight.glm_api import GLMClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check GLM API connectivity.")
    parser.add_argument("--info-path", default=str(ROOT / "results_airpods_500" / "info.md"))
    parser.add_argument("--timeout", type=float, default=100.0)
    parser.add_argument("--enable-thinking", action="store_true", help="Do not send thinking disabled flag")
    parser.add_argument("--sglang-disable-thinking", action="store_true", help="Also send chat_template_kwargs enable_thinking=false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = GLMClient(
        info_path=args.info_path,
        timeout=args.timeout,
        disable_thinking=not args.enable_thinking,
        sglang_disable_thinking=args.sglang_disable_thinking,
    )
    result = client.quick_check()
    print("GLM API check succeeded")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
