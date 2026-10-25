"""
Measure whether LM Studio and Ollama reuse the start of a prompt between calls (prompt-prefix caching).

Part 1, controlled: random-word prompts of a fixed size, one output token requested, so time is dominated
by reading the prompt. For each size and repeat, with a fresh random prefix:
  cold          the first call with that prefix (nothing cached)
  warm, warm2   the same prefix, a different ending each time (what a stable prompt prefix allows)
  changed_start the same prefix body with a different first line (what a timestamp at the top would do)
Then a 5-step series that grows an append-only prompt by ~300 tokens a step, as an agent's history does,
once with a stable start ("cached") and once with the first line changed every step ("broken").

Part 2, --real-agent: the actual SmolPaw agent on the Tidepool task, recording each step's seconds and
prompt tokens, to compare against the cold reading speed measured in part 1. Uses its own notes and
memory, never the real ones. Confirmation prompts are declined (the task is read-only).

  .venv/bin/python tests/prefix_cache.py --model qwen3.5-9b-mlx --ctx 16384 --real-agent
  .venv/bin/python tests/prefix_cache.py --backend ollama --model qwen3.5:9b --ctx 16384 --real-agent
"""

import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import eval as ev  # noqa: E402
from eval import BACKENDS, ensure_model, safe_name, unload_all  # noqa: E402
from prefill_timing import random_text  # noqa: E402

ROOT = Path(__file__).parent.parent
TOKENS_PER_WORD = 1.9  # for prefill_timing's vocabulary; the real count comes from usage
SERIES_STEPS, SERIES_GROWTH = 5, 300


def call(url: str, model: str, system: str, user: str) -> dict:
    """One chat call asking for a single token; returns seconds, prompt tokens and any cached-token count."""
    body = {"model": model, "max_tokens": 1, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user + "\n\nSay OK."}]}
    t0 = time.time()
    r = requests.post(url, json=body, timeout=1800)
    secs = time.time() - t0
    r.raise_for_status()
    u = r.json()["usage"]
    return {"seconds": round(secs, 2), "prompt_tokens": u["prompt_tokens"],
            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens")}


def words(n_tokens: int, rng: random.Random) -> str:
    return random_text(int(n_tokens / TOKENS_PER_WORD), rng)


def controlled(url: str, model: str, size: int, reps: int, rng: random.Random) -> list[dict]:
    rows = []
    for rep in range(reps):
        body = words(size, rng)
        end_a, end_b, end_c = words(40, rng), words(40, rng), words(40, rng)
        for cond, system, user in [
            ("cold", f"Session 0\n{body}", end_a),
            ("warm", f"Session 0\n{body}", end_b),
            ("warm2", f"Session 0\n{body}", end_c),
            ("changed_start", f"Session {rep + 1}\n{body}", end_a),
        ]:
            rows.append({"size": size, "rep": rep, "condition": cond, **call(url, model, system, user)})
            print(f"  {size:>6} rep {rep} {cond:<13} {rows[-1]['prompt_tokens']:>6} tok {rows[-1]['seconds']:>6.1f}s")
    return rows


def series(url: str, model: str, size: int, mode: str, rng: random.Random) -> list[dict]:
    """Append-only growth. 'broken' changes the first line each step, which defeats prefix reuse."""
    body, rows = words(size, rng), []
    for step in range(SERIES_STEPS):
        head = f"Session {step}" if mode == "broken" else "Session 0"
        rows.append({"size": size, "mode": mode, "step": step + 1, **call(url, model, f"{head}\n{body}", "go")})
        print(f"  {size:>6} series {mode:<6} step {step + 1} {rows[-1]['prompt_tokens']:>6} tok {rows[-1]['seconds']:>6.1f}s")
        body += " " + words(SERIES_GROWTH, rng)
    return rows


def summarise(rows: list[dict]) -> list[str]:
    lines = ["| prompt tokens | cold | warm | warm2 | changed start | warm2 / cold |", "|---|---|---|---|---|---|"]
    for size in sorted({r["size"] for r in rows}):
        med = {c: statistics.median(r["seconds"] for r in rows if r["size"] == size and r["condition"] == c)
               for c in ("cold", "warm", "warm2", "changed_start")}
        tok = statistics.median(r["prompt_tokens"] for r in rows if r["size"] == size and r["condition"] == "cold")
        lines.append(f"| {tok:.0f} | {med['cold']:.1f}s | {med['warm']:.1f}s | {med['warm2']:.1f}s | "
                     f"{med['changed_start']:.1f}s | {med['warm2'] / med['cold']:.2f} |")
    return lines


def real_agent(model: str, backend: str, n: int, cold_rate: float) -> list[dict]:
    """Run the Tidepool task n times; each step's seconds against reading its whole prompt uncached."""
    g = ev.g
    port = ev.free_port()
    server = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_api.py"), str(port), "hint"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    out = []
    try:
        with tempfile.TemporaryDirectory() as d:
            url = f"http://127.0.0.1:{port}"
            (Path(d) / "notes.md").write_text(f"# notes\n\n- tidepool: {url}\n  Harbour logbook service. No API key needed.\n")
            g.NOTES, g.MEMORY = Path(d) / "notes.md", Path(d) / "memory.md"
            g.CONFIRM = lambda desc: False
            g.ASK = lambda q: "(no answer: nobody is at the keyboard.)"
            for i in range(n):
                r = ev.run_once(model, ev.TIDEPOOL_PROMPT.format(url=url), ["kestrel", "340"], 12, backend)
                for k, s in enumerate(r["step_stats"], 1):
                    uncached = s["input_tokens"] / cold_rate
                    out.append({"run": i + 1, "step": k, "passed": r["passed"], **s,
                                "uncached_prefill_s": round(uncached, 1)})
                    print(f"  run {i + 1} step {k}: {s['input_tokens']:>6} tok in, {s['seconds']:>5.1f}s "
                          f"(reading it all cold would take ~{uncached:.1f}s)")
    finally:
        server.terminate()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--sizes", default="3000,12000", help="approximate prompt tokens")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--real-agent", action="store_true", help="also run the Tidepool task and record per-step times")
    ap.add_argument("--agent-runs", type=int, default=3)
    ap.add_argument("--no-load", action="store_true")
    args = ap.parse_args()

    url = BACKENDS[args.backend]["url"] + "/chat/completions"
    ctx = None if args.no_load else ensure_model(args.model, args.ctx, args.backend)
    rng = random.Random(11)
    print(f"prefix cache {args.backend}: {args.model} | loaded context {ctx}")
    call(url, args.model, "warm up", words(50, rng))  # first call can include model start-up
    rows, ser = [], []
    sizes = [int(s) for s in args.sizes.split(",")]
    for size in sizes:
        rows += controlled(url, args.model, size, args.reps, rng)
    for size in sizes:
        for mode in ("cached", "broken"):
            ser += series(url, args.model, size, mode, rng)
    print("\n".join(["", *summarise(rows)]))
    agent = []
    if args.real_agent:
        cold = [r["prompt_tokens"] / r["seconds"] for r in rows if r["condition"] == "cold" and r["size"] == min(sizes)]
        agent = real_agent(args.model, args.backend, args.agent_runs, statistics.median(cold))
    out = ROOT / "logs" / f"prefix-cache-{args.backend}-{safe_name(args.model)}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"backend": args.backend, "model": args.model, "loaded_context": ctx,
                               "controlled": rows, "series": ser, "agent_steps": agent}, indent=2))
    print(f"saved {out.name}")
    unload_all(force_lms=args.backend == "lmstudio")


if __name__ == "__main__":
    main()
