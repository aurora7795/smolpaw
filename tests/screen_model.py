"""
A staged screen for a new model (#126): cheap checks first, the expensive matrix only for survivors.

Runs the stages in order, prints one pass or fail line per stage with its time, and stops at the first failure.
Thresholds are fixed here, before any model was screened:

  1. loads    The runtime loads it, the chat template accepts `tools`, and a plain reply is real text (not empty,
              not a repeated token). Also records the loaded context and the size of that call in tokens.
  2. tools    Three single-call tasks (read a file, finish with final_answer, answer with no tool needed), n=3
              each, against a small set of offered tools. Pass: at least 7 of 9 correct and no call to a tool
              that was not offered ("invents tools", #7) and no call whose arguments are not a JSON object.
  3. tidepool Tidepool `easy` and `hint` (tests/eval.py), n=3 each. Pass: at least 2 of 3 on each.
  4. matrix   Not run here: a model that passes 1 to 3 is worth the full matrix of tests/eval.py cells (n>=5).

  .venv/bin/python tests/screen_model.py --backend ollama --model <id> [--ctx 32768] [--stages loads,tools]

Read-only. It unloads whatever is loaded first (only one model fits on 16GB). Logs go to logs/screen-*.json.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests import eval as ev  # noqa: E402  (model loading and the backend table)

ROOT = Path(__file__).parent.parent
TOOLS_MIN_PASS = 7  # of 9
TIDEPOOL_MIN_PASS = 2  # of 3, per variant
RUNS_PER_TASK = 3

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file in the workspace.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "file name"}},
                    "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_dir", "description": "List the entries of a folder.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "folder name"}},
                    "required": ["path"]}}},
    {"type": "function", "function": {"name": "final_answer", "description": "Give the final answer to the user and stop.",
     "parameters": {"type": "object", "properties": {"answer": {"type": "string", "description": "the answer"}},
                    "required": ["answer"]}}},
]
OFFERED = {t["function"]["name"] for t in TOOLS}
SYSTEM = "You are a helpful assistant with tools. Call a tool when you need one; call final_answer to finish."

# (name, prompt, grader over the list of (tool name, parsed arguments) and the reply text)
TASKS = [
    ("read_a_file", "Read notes.txt and tell me what it says.",
     lambda calls, text: any(n == "read_file" and "notes.txt" in str(a.get("path", "")) for n, a in calls)),
    ("final_answer", "The sum of 2 and 2 is 4. Give that to the user now.",
     lambda calls, text: any(n == "final_answer" and "4" in str(a.get("answer", "")) for n, a in calls)),
    ("no_tool_needed", "Say hello in one short sentence.",
     lambda calls, text: (not calls and bool(text.strip())) or any(n == "final_answer" and a.get("answer") for n, a in calls)),
]


def looks_like_junk(text: str) -> bool:
    """A reply that is empty, or a few words repeated over and over."""
    words = re.findall(r"\w+", text.lower())
    if len(words) < 3:
        return True
    return len(set(words)) / len(words) < 0.3 and len(words) > 12


def parse_calls(message: dict) -> tuple[list[tuple[str, dict]], list[str]]:
    """The (name, arguments) of each native tool call, plus a list of problems (invented tool, bad arguments)."""
    calls, problems = [], []
    for c in message.get("tool_calls") or []:
        fn = c.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            problems.append(f"{name}: arguments are not a JSON object")
            args = {}
        if name not in OFFERED:
            problems.append(f"invented tool {name!r}")
        calls.append((name, args))
    return calls, problems


def chat(backend: str, model: str, prompt: str, tools: bool = True, max_tokens: int = 2000) -> dict:
    b = ev.BACKENDS[backend]
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "max_tokens": max_tokens}
    if tools:
        body["tools"] = TOOLS
    r = requests.post(f"{b['url']}/chat/completions", json=body, headers={"Authorization": f"Bearer {b['key']}"}, timeout=300)
    r.raise_for_status()
    return r.json()


def reply_text(message: dict) -> str:
    """The reply as text: the content, or the answer of a final_answer call (models told to finish that way give no content)."""
    text = message.get("content") or ""
    if not text.strip():
        calls, _ = parse_calls(message)
        text = next((str(a.get("answer", "")) for n, a in calls if n == "final_answer"), "")
    return text


def stage_loads(args) -> tuple[bool, str, dict]:
    ctx = ev.ensure_model(args.model, args.ctx, args.backend)
    reply = chat(args.backend, args.model, "Reply with one short sentence about cats.")
    text = reply_text(reply["choices"][0]["message"])
    toks = reply.get("usage", {}).get("prompt_tokens")
    ok = not looks_like_junk(text)
    return ok, f"context {ctx}, {toks} prompt tokens with 3 tools, reply: {text.strip()[:80]!r}", {"context": ctx, "prompt_tokens": toks, "reply": text}


def stage_tools(args) -> tuple[bool, str, dict]:
    passed, problems, per_task = 0, [], {}
    for name, prompt, grade in TASKS:
        ok_n = 0
        for _ in range(RUNS_PER_TASK):
            try:
                msg = chat(args.backend, args.model, prompt)["choices"][0]["message"]
            except requests.RequestException as e:
                problems.append(f"{name}: request failed: {e}")
                continue
            calls, probs = parse_calls(msg)
            problems += [f"{name}: {p}" for p in probs]
            if not probs and grade(calls, msg.get("content") or ""):
                ok_n += 1
        per_task[name] = ok_n
        passed += ok_n
    total = RUNS_PER_TASK * len(TASKS)
    ok = passed >= TOOLS_MIN_PASS and not problems
    return ok, f"{passed}/{total} correct {per_task}; problems: {problems[:3] or 'none'}", {"passed": passed, "per_task": per_task, "problems": problems}


def stage_tidepool(args) -> tuple[bool, str, dict]:
    results, ok = {}, True
    for variant in ("easy", "hint"):
        cmd = [sys.executable, str(ROOT / "tests" / "eval.py"), "--backend", args.backend, "--model", args.model,
               "--ctx", str(args.ctx), "--tidepool", variant, "--n", "3", "--run-timeout", "400", "--label", f"screen-{variant}"]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        m = re.search(r"=> (\d+)/(\d+) passed", out)
        results[variant] = int(m.group(1)) if m else 0
        ok &= results[variant] >= TIDEPOOL_MIN_PASS
    return ok, f"easy {results['easy']}/3, hint {results['hint']}/3", results


STAGES = {"loads": stage_loads, "tools": stage_tools, "tidepool": stage_tidepool}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["lmstudio", "ollama"], default="ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=32768)
    ap.add_argument("--stages", default=",".join(STAGES), help="comma list, in order (default: all three)")
    args = ap.parse_args()
    log = {"backend": args.backend, "model": args.model, "ctx": args.ctx, "stages": []}
    survived = True
    for name in args.stages.split(","):
        t0 = time.time()
        try:
            ok, detail, data = STAGES[name](args)
        except Exception as e:  # a model that will not load, or a server error, is a failed stage
            ok, detail, data = False, f"{type(e).__name__}: {str(e)[:200]}", {}
        secs = time.time() - t0
        print(f"{'PASS' if ok else 'FAIL'}  {name:9} {secs:5.0f}s  {detail}")
        log["stages"].append({"stage": name, "passed": ok, "seconds": round(secs), "detail": detail, **data})
        if not ok:
            survived = False
            break
    print("survives the screen: run the full matrix (stage 4)" if survived else "stopped at the first failure")
    out = ROOT / "logs" / f"screen-{datetime.now():%Y%m%d-%H%M%S}-{args.backend}-{ev.safe_name(args.model)}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(log, indent=2))
    print(f"saved {out.relative_to(ROOT)}")
    sys.exit(0 if survived else 1)


if __name__ == "__main__":
    main()
