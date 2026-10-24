"""
Time how long a local model takes to read prompts of increasing size (prefill), through LM Studio's
OpenAI-compatible API. Each request asks for one token, so wall time is dominated by reading the prompt.
Prompts are random words so a prompt cache cannot help. Nothing here touches any agent config.

  .venv/bin/python tests/prefill_timing.py --model qwen3.5-9b-mlx --ctx 32768
"""

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from eval import ensure_model  # noqa: E402

URL = "http://127.0.0.1:1234/v1/chat/completions"
SYLLABLES = ["ka", "to", "mi", "re", "su", "lo", "ve", "na", "pi", "du", "xo", "ba", "len", "mar", "tin", "sor"]


def random_text(words: int, rng: random.Random) -> str:
    return " ".join("".join(rng.choices(SYLLABLES, k=rng.randint(1, 3))) for _ in range(words))


def timed_request(model: str, words: int, rng: random.Random) -> tuple[int, float]:
    body = {"model": model, "max_tokens": 1, "temperature": 0,
            "messages": [{"role": "user", "content": random_text(words, rng) + "\n\nSay OK."}]}
    t0 = time.time()
    r = requests.post(URL, json=body, timeout=1800)
    elapsed = time.time() - t0
    r.raise_for_status()
    return r.json()["usage"]["prompt_tokens"], elapsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=32768)
    ap.add_argument("--sizes", default="2000,6000,12000,24000", help="approximate prompt tokens")
    ap.add_argument("--no-lms", action="store_true")
    args = ap.parse_args()

    ctx = None if args.no_lms else ensure_model(args.model, args.ctx)
    rng = random.Random(7)
    print(f"prefill {args.model} | loaded context {ctx}")
    timed_request(args.model, 50, rng)  # warm up (first call can include model start-up)
    rows = []
    for target in [int(s) for s in args.sizes.split(",")]:
        # about 1.9 tokens per generated word for this vocabulary; the real count comes from usage
        try:
            tokens, secs = timed_request(args.model, int(target / 1.9), rng)
        except requests.RequestException as exc:
            print(f"  target {target}: failed ({exc})")
            continue
        rows.append({"prompt_tokens": tokens, "seconds": round(secs, 1), "tokens_per_s": round(tokens / secs)})
        print(f"  {tokens:>6} tokens: {secs:6.1f}s  ({tokens / secs:.0f} tok/s)")
    out = Path(__file__).parent.parent / "logs" / f"prefill-{args.model.replace('/', '_')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "loaded_context": ctx, "rows": rows}, indent=2))
    print(f"  saved {out.name}")
    subprocess.run([str(Path.home() / ".lmstudio/bin/lms"), "unload", "--all"], capture_output=True)


if __name__ == "__main__":
    main()
