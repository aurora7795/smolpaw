"""
Measure how many prompt tokens one tool's schema costs, on an Ollama model.

Sends the tool's JSON schema (as smolagents sends it) to /api/generate with raw=true and one output token,
and subtracts the count for an empty prompt. Read-only; touches no workspace or notes.

  .venv/bin/python tests/tool_schema_tokens.py --model qwen3.5:9b --tool web_search
"""

import argparse
import json
import sys
from pathlib import Path

import requests
from smolagents.models import get_tool_json_schema

sys.path.insert(0, str(Path(__file__).parent.parent))
import generic_tools as g  # noqa: E402


def prompt_tokens(url: str, model: str, prompt: str) -> int:
    r = requests.post(f"{url}/api/generate", timeout=300, json={
        "model": model, "prompt": prompt, "raw": True, "stream": False,
        "options": {"num_predict": 1},
    })
    r.raise_for_status()
    return r.json()["prompt_eval_count"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--tool", default="web_search")
    ap.add_argument("--url", default="http://localhost:11434")
    args = ap.parse_args()
    tool = getattr(g, args.tool)
    schema = json.dumps(get_tool_json_schema(tool))
    base = prompt_tokens(args.url, args.model, " ")
    full = prompt_tokens(args.url, args.model, schema)
    print(f"{args.model} {args.tool}: {full - base} tokens ({full} with schema, {base} baseline)")


if __name__ == "__main__":
    main()
