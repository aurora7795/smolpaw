"""
Repeatable eval runs for the generic harness.

Runs one prompt N times on a model and records pass/fail, steps, wall time, token counts,
tool calls and the final answer. Confirmation prompts are answered "no" (and recorded), so
use it for read-only tasks. The real notes.md is never touched: the run uses its own notes.

Examples:
  .venv/bin/python tests/eval.py --model google/gemma-4-e4b --tidepool hint --n 3
  .venv/bin/python tests/eval.py --model qwen3.5-9b-mlx --notes-file notes.md \\
      --prompt "What is in my Radarr download queue? Just look, don't change anything." \\
      --expect Gattaca
"""

import argparse
import contextlib
import io
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from agent import build_agent, load_env  # noqa: E402
from smolagents.memory import ActionStep  # noqa: E402
from smolagents.utils import AgentMaxStepsError, AgentParsingError  # noqa: E402

LMS = Path.home() / ".lmstudio/bin/lms"
ROOT = Path(__file__).parent.parent
TIDEPOOL_PROMPT = ("Using the Tidepool service at {url}, which vessel has the biggest cargo "
                   "capacity, and what is that capacity?")


def lms(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(LMS), *args], capture_output=True, text=True)


def ensure_model(model: str, ctx: int) -> int | None:
    """Unload everything, load `model` with the given context and one slot; return the loaded context."""
    lms("unload", "--all")
    time.sleep(3)
    for attempt in range(3):
        r = lms("load", model, "--context-length", str(ctx), "--parallel", "1", "-y")
        if r.returncode == 0:
            break
        time.sleep(8)
    else:
        raise RuntimeError(f"could not load {model}: {(r.stdout + r.stderr).strip()[-300:]}")
    loaded = json.loads(lms("ps", "--json").stdout or "[]")
    for m in loaded:
        if model in (m.get("identifier"), m.get("modelKey"), m.get("path")):
            return m.get("contextLength")
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def usage(agent) -> tuple[int, int]:
    t = agent.monitor.get_total_token_counts()
    return getattr(t, "input_tokens", 0), getattr(t, "output_tokens", 0)


def run_once(model: str, prompt: str, expects: list[str], max_steps: int) -> dict:
    g.ACTIONS.clear()
    g.LAST_RESULT = ""
    agent = build_agent(model, "tool", max_steps, "generic")
    t0 = time.time()
    buf = io.StringIO()
    error = ""
    try:
        with contextlib.redirect_stdout(buf):
            answer = str(agent.run(prompt))
    except Exception as exc:  # noqa: BLE001
        answer, error = "", f"{type(exc).__name__}: {exc}"
    wall = time.time() - t0
    steps = [s for s in agent.memory.steps if isinstance(s, ActionStep)]
    tokens_in, tokens_out = usage(agent)
    return {
        "passed": bool(answer) and all(re.search(e, answer, re.I) for e in expects),
        "wall_s": round(wall, 1),
        "steps": len(steps),
        "hit_cap": any(isinstance(s.error, AgentMaxStepsError) for s in steps),
        "parse_errors": sum(isinstance(s.error, AgentParsingError) for s in steps),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "tools": [tc.name for s in steps for tc in (s.tool_calls or [])],
        "declined": [a for a in g.ACTIONS if a.startswith("declined")],
        "answer": answer.strip()[:400],
        "error": error,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", help="task prompt (default for --tidepool: the vessel question)")
    ap.add_argument("--expect", action="append", default=[], help="regex the answer must match (repeatable)")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--ctx", type=int, default=16384, help="context length to load the model with")
    ap.add_argument("--no-lms", action="store_true", help="do not unload/load models; use what is loaded")
    ap.add_argument("--notes-file", help="notes to use instead of the real notes.md")
    ap.add_argument("--tidepool", metavar="VARIANT", help="serve the fake Tidepool API (easy|hint|detail|paged)")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    load_env()
    tmp = Path(tempfile.mkdtemp())
    server = None
    prompt, expects = args.prompt, args.expect
    if args.tidepool:
        port = free_port()
        server = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_api.py"), str(port), args.tidepool],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        url = f"http://127.0.0.1:{port}"
        (tmp / "notes.md").write_text(f"# notes\n\n- tidepool: {url}\n  Harbour logbook service. No API key needed.\n")
        prompt = prompt or TIDEPOOL_PROMPT.format(url=url)
        expects = expects or ["kestrel", "340"]
    elif args.notes_file:
        (tmp / "notes.md").write_text(Path(args.notes_file).read_text())
    else:
        (tmp / "notes.md").write_text("# notes\n")
    if not prompt:
        ap.error("--prompt is required unless --tidepool is used")
    g.NOTES = tmp / "notes.md"
    g.CONFIRM = lambda desc: False
    g.ASK = lambda q: "(no answer: nobody is at the keyboard. Do not ask again; make your best attempt.)"

    ctx = None
    try:
        if not args.no_lms:
            ctx = ensure_model(args.model, args.ctx)
        label = args.label or (f"tidepool-{args.tidepool}" if args.tidepool else "custom")
        print(f"eval {label} | {args.model} | loaded context {ctx} | n={args.n}")
        results = []
        for i in range(1, args.n + 1):
            r = run_once(args.model, prompt, expects, args.max_steps)
            results.append(r)
            flag = "PASS" if r["passed"] else "FAIL"
            cap = " CAP" if r["hit_cap"] else ""
            print(f"  run {i}: {flag}{cap} {r['wall_s']}s steps={r['steps']} parse_err={r['parse_errors']} "
                  f"tokens_in={r['input_tokens']} tools={'>'.join(r['tools'])}")
            print(f"         {r['answer'][:160]!r}{' ERROR ' + r['error'] if r['error'] else ''}")
        n = len(results)
        print(f"  => {sum(r['passed'] for r in results)}/{n} passed | "
              f"mean {sum(r['wall_s'] for r in results) / n:.0f}s, "
              f"{sum(r['steps'] for r in results) / n:.1f} steps, "
              f"{sum(r['input_tokens'] for r in results) / n:.0f} input tokens")
        out = ROOT / "logs" / f"eval-{datetime.now():%Y%m%d-%H%M%S}-{args.model.replace('/', '_')}-{label}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"model": args.model, "label": label, "loaded_context": ctx,
                                   "prompt": prompt, "expect": expects, "runs": results}, indent=2))
        print(f"  saved {out.relative_to(ROOT)}")
    finally:
        if server:
            server.terminate()


if __name__ == "__main__":
    main()
