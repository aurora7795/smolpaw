"""
Measure what Ollama and LM Studio re-read when something earlier in an agent's prompt changes (#69, #73).

#29 showed a stable prompt start is nearly free to re-read and a changed first line is not. This asks the
follow-up that tool routing and result snipping depend on: if the *tool block* shrinks, or an *old tool
result* is shortened, how much of the prompt is read again?

The requests are the real ones: SmolPaw's system prompt and tool schemas for the model, as the agent would
send them (isolated notes and skills, as in first_call_tokens.py), then a short history of one tool call with
a large result, then one more small tool exchange, so every request ends on a tool result as an agent step
does. One output token is requested, so time is dominated by reading the prompt. Each repeat starts with a
fresh `Session N` first line so nothing is cached. Conditions, in the order they are sent:
  cold          all tools, history H, first call (nothing cached)
  warm, warm2   the same prefix, a different last exchange (what a stable prompt allows)
  subset        only the file tools, same history (what a routed category would send)
  subset_again, subset_third  the same subset again (how many calls until it is cached?)
  all_again     all tools again (what widening after the first tool call would send)
  snipped       all tools, but the old large result cut to its first half plus last quarter (#73)
  snipped_again, snipped_third  the snipped history again (a snipped history is then the new prefix)

Read-only. Never touches the real notes, memory or skills; the tool result is random words.

  .venv/bin/python tests/prefix_cache_tools.py --backend ollama --model qwen3.5:9b
  .venv/bin/python tests/prefix_cache_tools.py --model qwen3.5-9b-mlx
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
from smolagents.agents import SystemPromptStep, TaskStep

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import agent as agent_mod  # noqa: E402
from eval import BACKENDS, ensure_model, safe_name, unload_all  # noqa: E402
from first_call_tokens import isolate  # noqa: E402
from prefill_timing import random_text  # noqa: E402

ROOT = Path(__file__).parent.parent
TOKENS_PER_WORD = 1.9
FILE_TOOLS = {"run_shell", "read_file", "list_dir", "write_file", "ask_user", "final_answer"}
CONDITIONS = ["cold", "warm", "warm2", "subset", "subset_again", "subset_third", "all_again",
              "snipped", "snipped_again", "snipped_third"]


def request_parts(agent) -> tuple[str, list[dict]]:
    """The system prompt text and the OpenAI-format tool list the agent sends for a first request."""
    agent.memory.reset()
    agent.memory.system_prompt = SystemPromptStep(system_prompt=agent.initialize_system_prompt())
    agent.memory.steps.append(TaskStep(task="hello"))
    kwargs = agent.model._prepare_completion_kwargs(
        agent.write_memory_to_messages(), tools_to_call_from=list(agent.tools.values()), max_tokens=1)
    content = kwargs["messages"][0]["content"]
    text = content if isinstance(content, str) else "".join(p.get("text", "") for p in content)
    return text, kwargs["tools"]


def snip(text: str) -> str:
    """First half plus last quarter, the rule #73 proposes."""
    return text[: len(text) // 2] + "\n[...]\n" + text[-(len(text) // 4):]


def exchange(n: int, result: str) -> list[dict]:
    """One tool call and its result."""
    call = {"id": f"call_{n}", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": f"part{n}.txt"})}}
    return [{"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": f"call_{n}", "content": result}]


def send(url: str, model: str, system: str, tools: list[dict], history: list[dict]) -> dict:
    body = {"model": model, "max_tokens": 1, "temperature": 0, "tools": tools,
            "messages": [{"role": "system", "content": system}, *history]}
    t0 = time.time()
    r = requests.post(url, json=body, timeout=1800)
    secs = time.time() - t0
    r.raise_for_status()
    u = r.json()["usage"]
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    return {"seconds": round(secs, 2), "prompt_tokens": u["prompt_tokens"], "cached_tokens": cached}


def one_repeat(url: str, model: str, system: str, tools: list[dict], rep: int, result_tokens: int,
               rng: random.Random) -> list[dict]:
    names = lambda ts: {t["function"]["name"] for t in ts}  # noqa: E731
    subset = [t for t in tools if t["function"]["name"] in FILE_TOOLS]
    assert names(subset) < names(tools) and len(subset) >= 4, "the file tools were not found in the tool list"
    big = random_text(int(result_tokens / TOKENS_PER_WORD), rng)
    sys_text = f"Session {rep}\n{system}"
    base = [{"role": "user", "content": "Read part0.txt and tell me what is in it."}]
    plan = [("cold", tools, big), ("warm", tools, big), ("warm2", tools, big),
            ("subset", subset, big), ("subset_again", subset, big), ("subset_third", subset, big),
            ("all_again", tools, big), ("snipped", tools, snip(big)), ("snipped_again", tools, snip(big)),
            ("snipped_third", tools, snip(big))]
    rows = []
    for i, (cond, tool_list, result) in enumerate(plan, 1):
        history = base + exchange(0, result) + exchange(i, random_text(40, rng))
        row = {"rep": rep, "condition": cond, "tools_sent": len(tool_list),
               **send(url, model, sys_text, tool_list, history)}
        rows.append(row)
        print(f"  rep {rep} {cond:<13} {row['tools_sent']:>2} tools {row['prompt_tokens']:>6} tok "
              f"{row['seconds']:>6.1f}s cached {row['cached_tokens']}")
    return rows


def summarise(rows: list[dict]) -> list[str]:
    lines = ["| condition | tools | prompt tokens | seconds (median) | cached tokens (median) | read again |",
             "|---|---|---|---|---|---|"]
    for cond in CONDITIONS:
        sel = [r for r in rows if r["condition"] == cond]
        tok = statistics.median(r["prompt_tokens"] for r in sel)
        sec = statistics.median(r["seconds"] for r in sel)
        cached = [r["cached_tokens"] for r in sel if r["cached_tokens"] is not None]
        if cached:
            c = statistics.median(cached)
            again = f"{statistics.median(r['prompt_tokens'] - r['cached_tokens'] for r in sel if r['cached_tokens'] is not None):.0f}"
            lines.append(f"| {cond} | {sel[0]['tools_sent']} | {tok:.0f} | {sec:.1f} | {c:.0f} | {again} |")
        else:
            lines.append(f"| {cond} | {sel[0]['tools_sent']} | {tok:.0f} | {sec:.1f} | not reported | n/a |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--result-tokens", type=int, default=3000, help="size of the old tool result")
    ap.add_argument("--no-load", action="store_true")
    args = ap.parse_args()

    agent_mod.load_env()
    isolate(Path(tempfile.mkdtemp()), "# notes\n")
    system, tools = request_parts(agent_mod.build_agent(args.model, backend=args.backend))
    url = BACKENDS[args.backend]["url"] + "/chat/completions"
    ctx = None if args.no_load else ensure_model(args.model, args.ctx, args.backend)
    rng = random.Random(11)
    print(f"prefix cache, tool block and history edits, {args.backend}: {args.model} | loaded context {ctx} | "
          f"{len(tools)} tools")
    send(url, args.model, "warm up", [], [{"role": "user", "content": random_text(30, rng)}])  # start-up cost
    rows = []
    for rep in range(args.reps):
        rows += one_repeat(url, args.model, system, tools, rep, args.result_tokens, rng)
    print("\n".join(["", *summarise(rows)]))
    out = ROOT / "logs" / f"prefix-cache-tools-{args.backend}-{safe_name(args.model)}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"backend": args.backend, "model": args.model, "loaded_context": ctx,
                               "result_tokens": args.result_tokens, "rows": rows}, indent=2))
    print(f"saved {out.name}")
    unload_all(force_lms=args.backend == "lmstudio")


if __name__ == "__main__":
    main()
