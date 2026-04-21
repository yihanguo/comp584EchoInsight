"""Smoke test for the ModelScope OpenAI-compatible Qwen API."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_MODELSCOPE_API_KEY = "ms-74b8eedd-5f76-419a-a513-f421399093da"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a small multimodal chat request to the ModelScope OpenAI-compatible API."
    )
    parser.add_argument(
        "--base-url",
        default="https://api-inference.modelscope.cn/v1",
        help="OpenAI-compatible ModelScope base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MODELSCOPE_API_KEY", DEFAULT_MODELSCOPE_API_KEY),
        help="ModelScope API token. Defaults to MODELSCOPE_API_KEY or the in-file default token.",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3.5-35B-A3B",
        help="ModelScope model id.",
    )
    parser.add_argument(
        "--text",
        default="描述这幅图",
        help="User text prompt.",
    )
    parser.add_argument(
        "--image-url",
        default="https://modelscope.oss-cn-beijing.aliyuncs.com/demo/images/audrey_hepburn.jpg",
        help="Image URL to send in the multimodal request.",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Send a pure text request without image input.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use streaming responses.",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Also print reasoning_content when the server returns it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.api_key:
        print(
            "Missing API key. Pass --api-key or set MODELSCOPE_API_KEY.",
            file=sys.stderr,
        )
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "The openai package is not installed. Run `pip install openai` first.",
            file=sys.stderr,
        )
        return 3

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    if args.text_only:
        messages = [{"role": "user", "content": args.text}]
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": args.text},
                    {"type": "image_url", "image_url": {"url": args.image_url}},
                ],
            }
        ]

    print(f"Sending request to {args.base_url}")
    print(f"Model: {args.model}")
    if args.text_only:
        print("Mode: text-only")
    else:
        print(f"Image URL: {args.image_url}")
    print(f"Stream: {args.stream}")
    print("---")

    if args.stream:
        response = client.chat.completions.create(
            model=args.model,
            messages=messages,
            stream=True,
        )
        saw_text = False
        saw_reasoning = False
        printed_answer_header = False
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            answer = getattr(delta, "content", None)

            if reasoning and args.show_reasoning:
                if not saw_reasoning:
                    print("=== Reasoning ===")
                    saw_reasoning = True
                print(reasoning, end="", flush=True)

            if answer:
                if args.show_reasoning and not printed_answer_header:
                    if saw_reasoning:
                        print("\n\n=== Final Answer ===")
                    else:
                        print("=== Final Answer ===")
                    printed_answer_header = True
                print(answer, end="", flush=True)
                saw_text = True
        if saw_text:
            print()
        else:
            print("No text chunks returned.")
        return 0

    response = client.chat.completions.create(
        model=args.model,
        messages=messages,
        stream=False,
    )
    reasoning = getattr(response.choices[0].message, "reasoning_content", None)
    if reasoning and args.show_reasoning:
        print("=== Reasoning ===")
        print(reasoning)
        print("\n=== Final Answer ===")
    print(response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
