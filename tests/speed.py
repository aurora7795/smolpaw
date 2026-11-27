"""
Speed as a user feels it, per model, through the OpenAI-compatible API of Ollama or LM Studio (#148).

Four measurements, all by wall clock on a streamed request, so they include whatever the server does:

  load      seconds from "nothing loaded" to a model that can answer (Ollama only: the model is unloaded first)
  first     time to first token (TTFT) for SmolPaw's real first call (system prompt plus tool schemas, as in
            tests/first_call_tokens.py): `cold` with a fresh prompt start, `warm` with the same prompt again
  sweep     at each context size (random words, so no cache can help): TTFT, prefill tok/s and decode tok/s
            while the model writes a fixed 256 tokens
  long      seconds to write about 1,500 tokens (the size of a small web page written in one tool call)

Reasoning ("thinking") tokens count as tokens, since a user waits for them too. The first token is whichever
arrives first, thinking or answer. Prints a verdict per figure using the thresholds in JUDGE below, which are
judgement calls, not measurements. Nothing here touches any agent config, notes or workspace; it only reads.

  .venv/bin/python tests/speed.py --model qwen3.5:9b
  .venv/bin/python tests/speed.py --backend lmstudio --model qwen3.5-9b-mlx --ctx 16384
  .venv/bin/python tests/speed.py --report            # one table from every logs/speed-*.json
"""

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from eval import BACKENDS, OLLAMA, ensure_model, ensure_ollama, safe_name, unload_all  # noqa: E402

ROOT = Path(__file__).parent.parent
SYLLABLES = ["ka", "to", "mi", "re", "su", "lo", "ve", "na", "pi", "du", "xo", "ba", "len", "mar", "tin", "sor"]
TOKENS_PER_WORD = 1.9  # for the vocabulary above; the real count comes from the server's usage
SWEEP_OUT = 256
LONG_OUT = 1500

# (good if at least / at most this, usable up to this); anything past the second figure is slow.
JUDGE = {
    "decode_tok_s": (20, 10, "higher"),    # text streams faster than most people read
    "first_cold_s": (5, 15, "lower"),      # wait after pressing Run before anything appears
    "load_s": (15, 45, "lower"),           # first request after the model was not loaded
    "long_s": (60, 150, "lower"),          # writing a small page in one tool call
}


def random_text(words: int, rng: random.Random) -> str:
    return " ".join("".join(rng.choices(SYLLABLES, k=rng.randint(1, 3))) for _ in range(words))


def timing_from_events(t0: float, events: list[tuple[float, dict]]) -> dict:
    """Timing of one streamed reply from (arrival time, parsed chunk) pairs.

    ttft is the arrival of the first chunk carrying any text, thinking or tool call. decode_tok_s is the tokens
    after the first one over the time from the first to the last such chunk; usage in the last chunk gives the token counts.
    """
    first = last = None
    usage: dict = {}
    for t, chunk in events:
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if any(delta.get(k) for k in ("content", "reasoning", "reasoning_content", "tool_calls")):
                first = t if first is None else first
                last = t
    if first is None:
        return {"error": "no tokens came back"}
    out = usage.get("completion_tokens")
    row = {"ttft_s": round(first - t0, 2), "total_s": round((last or first) - t0, 2),
           "prompt_tokens": usage.get("prompt_tokens"), "output_tokens": out}
    if out and out > 1 and last > first:
        row["decode_tok_s"] = round((out - 1) / (last - first), 1)
    pt = usage.get("prompt_tokens")
    if pt and first > t0:
        row["prefill_tok_s"] = round(pt / (first - t0))
    return row


def stream_request(url: str, body: dict) -> dict:
    """POST a streaming chat request and time it."""
    body = {**body, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0}
    t0 = time.time()
    events: list[tuple[float, dict]] = []
    with requests.post(url, json=body, stream=True, timeout=900) as r:
        if not r.ok:
            return {"error": f"{r.status_code}: {r.text[:200]}"}
        for line in r.iter_lines():
            if line.startswith(b"data: ") and line[6:] != b"[DONE]":
                try:
                    events.append((time.time(), json.loads(line[6:])))
                except ValueError:
                    continue
    return timing_from_events(t0, events)


def median(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 2) if vals else None


def verdict(metric: str, value: float | None) -> str:
    """good / usable / slow for a figure, by the thresholds in JUDGE; n/a when it was not measured."""
    if value is None:
        return "n/a"
    good, usable, direction = JUDGE[metric]
    if direction == "higher":
        return "good" if value >= good else "usable" if value >= usable else "slow"
    return "good" if value <= good else "usable" if value <= usable else "slow"


def first_call_body(model: str, backend: str) -> dict:
    """The request SmolPaw's first model call would send for "hello" (empty notes, only git-tracked skills)."""
    import os  # noqa: PLC0415

    from first_call_tokens import PROMPT, isolate  # noqa: PLC0415
    from smolagents.agents import SystemPromptStep, TaskStep  # noqa: PLC0415

    sys.path.insert(0, str(ROOT))
    import agent as agent_mod  # noqa: PLC0415

    agent_mod.load_env()
    os.environ["SMOLPAW_SEARCH_PROVIDER"] = "ddgs"
    isolate(Path(tempfile.mkdtemp()), "# notes\n")
    agent = agent_mod.build_agent(model, backend=backend)
    agent.memory.reset()
    agent.memory.system_prompt = SystemPromptStep(system_prompt=agent.initialize_system_prompt())
    agent.memory.steps.append(TaskStep(task=PROMPT))
    kwargs = agent.model._prepare_completion_kwargs(
        agent.write_memory_to_messages(), tools_to_call_from=list(agent.tools.values()), max_tokens=8)
    kwargs["model"] = model
    return kwargs


def with_fresh_start(body: dict, tag: str) -> dict:
    """The same request with a unique first line, so no prompt cache can match it."""
    msgs = [dict(m) for m in body["messages"]]
    first = msgs[0]
    if isinstance(first.get("content"), list):
        # edit the first part's text rather than adding a part: some chat templates reject a system message of several parts
        first["content"] = [{**first["content"][0], "text": f"[{tag}]\n{first['content'][0]['text']}"}] + first["content"][1:]
    else:
        first["content"] = f"[{tag}]\n{first['content']}"
    return {**body, "messages": msgs}


def measure_model(args) -> dict:
    url = BACKENDS[args.backend]["url"] + "/chat/completions"
    rng = random.Random(11)
    result: dict = {"backend": args.backend, "model": args.model, "repeats": args.repeats}

    if args.backend == "ollama":
        unload_all()
        time.sleep(3)
        t0 = time.time()
        result["loaded_context"] = ensure_ollama(args.model, args.ctx)
        result["load_s"] = round(time.time() - t0, 1)
    else:
        t0 = time.time()
        result["loaded_context"] = ensure_model(args.model, args.ctx, "lmstudio")
        result["load_s"] = round(time.time() - t0 - 3, 1)  # ensure_model sleeps 3s after unloading
    print(f"{args.model}: loaded in {result['load_s']}s, context {result['loaded_context']}")
    stream_request(url, {"model": args.model, "max_tokens": 4, "messages": [{"role": "user", "content": "Say OK."}]})  # warm up

    body = first_call_body(args.model, args.backend)
    cold = [stream_request(url, with_fresh_start(body, f"{rng.random():.9f}")) for _ in range(args.repeats)]
    warm = [stream_request(url, with_fresh_start(body, "fixed")) for _ in range(args.repeats + 1)][1:]  # first call fills the cache
    result["first"] = {"cold": cold, "warm": warm,
                       "cold_ttft_s": median(cold, "ttft_s"), "warm_ttft_s": median(warm, "ttft_s"),
                       "prompt_tokens": median(cold, "prompt_tokens")}
    print(f"  first call ({result['first']['prompt_tokens']} tokens): cold {result['first']['cold_ttft_s']}s, warm {result['first']['warm_ttft_s']}s")

    result["sweep"] = []
    for size in [int(s) for s in args.sizes.split(",")]:
        rows = []
        for _ in range(args.repeats):
            text = random_text(int(size / TOKENS_PER_WORD), rng) if size else ""
            prompt = (text + "\n\nIgnore the text above. " if text else "") + "Write a long story about a cat who learns to cook."
            rows.append(stream_request(url, {"model": args.model, "max_tokens": SWEEP_OUT,
                                             "messages": [{"role": "user", "content": prompt}]}))
        summary = {"target_tokens": size, "prompt_tokens": median(rows, "prompt_tokens"), "ttft_s": median(rows, "ttft_s"),
                   "prefill_tok_s": median(rows, "prefill_tok_s"), "decode_tok_s": median(rows, "decode_tok_s"), "runs": rows}
        result["sweep"].append(summary)
        print(f"  context {summary['prompt_tokens']}: ttft {summary['ttft_s']}s, prefill {summary['prefill_tok_s']} tok/s, "
              f"decode {summary['decode_tok_s']} tok/s")

    if not args.no_long:
        long_rows = [stream_request(url, {"model": args.model, "max_tokens": LONG_OUT, "messages": [{"role": "user", "content":
                     "Write a complete single-file HTML tic-tac-toe game with CSS and JavaScript. Output only the code."}]})
                     for _ in range(args.repeats)]
        result["long"] = {"total_s": median(long_rows, "total_s"), "output_tokens": median(long_rows, "output_tokens"),
                          "decode_tok_s": median(long_rows, "decode_tok_s"), "runs": long_rows}
        print(f"  long write: {result['long']['output_tokens']} tokens in {result['long']['total_s']}s")
    return result


def judged(result: dict) -> dict:
    """The four headline figures with their verdicts, from one model's result."""
    small = next((s for s in result.get("sweep", []) if s["target_tokens"] <= 500), None) or (result.get("sweep") or [{}])[0]
    figures = {"load_s": result.get("load_s"), "first_cold_s": result.get("first", {}).get("cold_ttft_s"),
               "decode_tok_s": small.get("decode_tok_s"), "long_s": (result.get("long") or {}).get("total_s")}
    return {k: {"value": v, "verdict": verdict(k, v)} for k, v in figures.items()}


def report() -> None:
    """One markdown table from every saved result, newest run of each model."""
    rows = []
    for f in sorted((ROOT / "logs").glob("speed-*.json")):
        d = json.loads(f.read_text())
        j = judged(d)
        sweep = {s["target_tokens"]: s for s in d.get("sweep", [])}
        big = sweep[max(sweep)] if sweep else {}
        cell = lambda k: f"{j[k]['value']} ({j[k]['verdict']})"  # noqa: E731
        rows.append(f"| {d['model']} ({d['backend']}) | {cell('load_s')} | {cell('first_cold_s')} | "
                    f"{d.get('first', {}).get('warm_ttft_s')} | {cell('decode_tok_s')} | {big.get('decode_tok_s')} | "
                    f"{big.get('prefill_tok_s')} | {cell('long_s')} |")
    print("| Model | Load s | First call, cold s | First call, warm s | Decode tok/s (small prompt) | Decode tok/s (largest) "
          "| Prefill tok/s (largest) | Write 1,500 tokens s |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="ollama")
    ap.add_argument("--model")
    ap.add_argument("--ctx", type=int, default=32768, help="context to load with (LM Studio; on Ollama it is set on the server)")
    ap.add_argument("--sizes", default="0,4000,12000", help="approximate prompt tokens for the sweep (0 is a one-line prompt)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--no-long", action="store_true", help="skip the 1,500-token write")
    ap.add_argument("--report", action="store_true", help="print a table from logs/speed-*.json and exit")
    args = ap.parse_args()
    if args.report:
        report()
        return
    if not args.model:
        ap.error("--model is required")
    result = measure_model(args)
    result["judged"] = judged(result)
    out = ROOT / "logs" / f"speed-{args.backend}-{safe_name(args.model)}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    for k, v in result["judged"].items():
        print(f"  {k}: {v['value']} -> {v['verdict']}")
    print(f"  saved {out.name}")
    unload_all(force_lms=args.backend == "lmstudio")


if __name__ == "__main__":
    main()
