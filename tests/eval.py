"""
Repeatable eval runs for the generic harness.

Runs one prompt N times on a model and records pass/fail, steps, wall time, token counts,
tool calls and the final answer. Confirmation prompts are answered "no" (and recorded), so
use it for read-only tasks, unless --confirm web sends them to the web page (see web.py).
The real notes.md is never touched: the run uses its own notes.

Examples:
  .venv/bin/python tests/eval.py --model google/gemma-4-e4b --tidepool hint --n 3
  .venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --tidepool hint --n 3
  .venv/bin/python tests/eval.py --model google/gemma-4-e4b --notes-file notes.md --confirm web \\
      --web-host 0.0.0.0 --prompt "Add Gattaca to Radarr" --expect "added"
  .venv/bin/python tests/eval.py --model qwen3.5-9b-mlx --notes-file notes.md \\
      --prompt "What is in my Radarr download queue? Just look, don't change anything." \\
      --expect Gattaca
"""

import argparse
import contextlib
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from agent import BACKENDS, build_agent, load_env  # noqa: E402
from smolagents.memory import ActionStep  # noqa: E402
from smolagents.utils import AgentMaxStepsError, AgentParsingError  # noqa: E402

LMS = Path.home() / ".lmstudio/bin/lms"
OLLAMA = BACKENDS["ollama"]["url"].removesuffix("/v1")
ROOT = Path(__file__).parent.parent
TIDEPOOL_PROMPT = ("Using the Tidepool service at {url}, which vessel has the biggest cargo "
                   "capacity, and what is that capacity?")


LISTING_PROMPT = "What files and folders are in the folder downloads/? Give the exact total count and the name of every folder."
LISTING_FOLDERS = ["apps", "docs", "fonts", "photos"]


def make_listing_fixture(workspace: Path) -> list[str]:
    """Create downloads/ with 55 entries (4 folders, 51 files) and return regexes the answer must match (#46)."""
    d = workspace / "downloads"
    d.mkdir(parents=True)
    for i, name in enumerate(LISTING_FOLDERS):
        (d / name).mkdir()
        for j in range(i + 1):
            (d / name / f"item{j}.txt").write_text("x")
    for i in range(51):
        (d / f"file{i:02}.{('pdf', 'png', 'zip')[i % 3]}").write_bytes(b"0" * (i * 100 + 10))
    return [r"\b55\b", *LISTING_FOLDERS]


def lms(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(LMS), *args], capture_output=True, text=True)


def server_up(url: str) -> bool:
    try:
        return requests.get(url, timeout=3).ok
    except requests.RequestException:
        return False


def ollama_loaded() -> list[dict]:
    """Models Ollama has in memory, or [] if its server is not running."""
    try:
        return requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", [])
    except requests.RequestException:
        return []


def unload_all(force_lms: bool = False) -> None:
    """Free memory on both servers: only one model fits on 16GB."""
    # Without force_lms, call lms only when LM Studio's server is up, so an Ollama run does not start it.
    if LMS.exists() and (force_lms or server_up(BACKENDS["lmstudio"]["url"] + "/models")):
        lms("unload", "--all")
    for m in ollama_loaded():
        requests.post(f"{OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def ensure_ollama(model: str, ctx: int) -> int | None:
    """Load `model` in Ollama and return its context. Ollama sets the context on the server, so only check it."""
    r = requests.post(f"{OLLAMA}/api/generate", json={"model": model}, timeout=600)  # no prompt: load only
    if not r.ok:
        raise RuntimeError(f"could not load {model}: {r.text.strip()[-300:]}")
    names = {model, f"{model}:latest"}
    loaded = next((m.get("context_length") for m in ollama_loaded() if m.get("name") in names), None)
    if loaded != ctx:
        print(f"warning: Ollama loaded {model} with context {loaded}, not {ctx}. "
              f"Set OLLAMA_CONTEXT_LENGTH={ctx} on the Ollama server to change it.")
    return loaded


def ensure_model(model: str, ctx: int, backend: str = "lmstudio") -> int | None:
    """Unload everything, load `model` with the given context and one slot; return the loaded context."""
    unload_all(force_lms=backend == "lmstudio")
    time.sleep(3)
    if backend == "ollama":
        return ensure_ollama(model, ctx)
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


def safe_name(model: str) -> str:
    """Model id as a filename part: Ollama ids contain ':', LM Studio ids may contain '/'."""
    return re.sub(r"[/:]", "_", model)


def run_once(model: str, prompt: str, expects: list[str], max_steps: int, backend: str = "lmstudio",
             native_history: bool = True) -> dict:
    g.ACTIONS.clear()
    g.LAST_RESULT = ""
    prompts: list[str] = []
    confirm = g.CONFIRM
    g.CONFIRM = lambda desc: (prompts.append(desc.splitlines()[0]), confirm(desc))[1]
    agent = build_agent(model, "tool", max_steps, "generic", backend, native_history)
    t0 = time.time()
    buf = io.StringIO()
    error = ""
    try:
        with contextlib.redirect_stdout(buf):
            answer = str(agent.run(prompt))
    except Exception as exc:  # noqa: BLE001
        answer, error = "", f"{type(exc).__name__}: {exc}"
    wall = time.time() - t0
    g.CONFIRM = confirm
    steps = [s for s in agent.memory.steps if isinstance(s, ActionStep)]
    tokens_in, tokens_out = usage(agent)
    hit_cap = any(isinstance(s.error, AgentMaxStepsError) for s in steps)
    return {
        # A capped run did not finish, even if its forced last answer happens to match.
        "passed": bool(answer) and not hit_cap and all(re.search(e, answer, re.I) for e in expects),
        "wall_s": round(wall, 1),
        "steps": len(steps),
        "hit_cap": hit_cap,
        "parse_errors": sum(isinstance(s.error, AgentParsingError) for s in steps),
        # text of each parse error, to see which failure mode recurs (#14) instead of only a count
        "parse_error_detail": [str(s.error)[:300] for s in steps if isinstance(s.error, AgentParsingError)],
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "tools": [tc.name for s in steps for tc in (s.tool_calls or [])],
        # per model call: seconds, prompt tokens read and tokens written, to see where time goes (#29)
        "step_stats": [{"seconds": round(s.timing.duration or 0, 1),
                        "input_tokens": getattr(s.token_usage, "input_tokens", 0),
                        "output_tokens": getattr(s.token_usage, "output_tokens", 0)} for s in steps],
        "declined": [a for a in g.ACTIONS if a.startswith("declined")],
        "confirm_prompts": prompts,
        "actions": list(g.ACTIONS),  # what [Harness says] would report, to check the answer against
        "answer": answer.strip()[:400],
        "error": error,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio")
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", help="task prompt (default for --tidepool: the vessel question)")
    ap.add_argument("--expect", action="append", default=[], help="regex the answer must match (repeatable)")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--ctx", type=int, default=16384,
                    help="context to load with (LM Studio); on Ollama, the context to expect from the server")
    ap.add_argument("--no-load", "--no-lms", dest="no_load", action="store_true",
                    help="do not unload/load models; use what is loaded")
    ap.add_argument("--notes-file", help="notes to use instead of the real notes.md")
    ap.add_argument("--tidepool", metavar="VARIANT", help="serve the fake Tidepool API (easy|hint|detail|paged)")
    ap.add_argument("--listing", action="store_true",
                    help="folder-listing task on a generated 55-entry downloads/ in an isolated workspace (#46)")
    ap.add_argument("--without-tool", action="append", default=[],
                    help="drop a generic tool by name for this run, to compare (for example list_dir)")
    ap.add_argument("--label", default="")
    ap.add_argument("--confirm", choices=["no", "web"], default="no",
                    help="no = answer every prompt no; web = answer prompts in the browser (web.py)")
    ap.add_argument("--web-host", default="127.0.0.1")
    ap.add_argument("--web-port", type=int, default=8770)
    ap.add_argument("--text-history", action="store_true",
                    help="send earlier tool calls as smolagents' text, not native tool_calls "
                         "(for comparison, #14)")
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
    if args.listing:
        g.WORKSPACE = tmp / "workspace"
        fixture_expects = make_listing_fixture(g.WORKSPACE)
        expects = expects or fixture_expects
        prompt = prompt or LISTING_PROMPT
        if not args.tidepool and not args.notes_file:
            (tmp / "notes.md").write_text("# notes\n")
    for name in args.without_tool:
        g.GENERIC_TOOLS[:] = [t for t in g.GENERIC_TOOLS if t.name != name]
    if not prompt:
        ap.error("--prompt is required unless --tidepool or --listing is used")
    g.NOTES = tmp / "notes.md"
    g.MEMORY = tmp / "memory.md"
    web_server, web_info = None, {}
    if args.confirm == "web":
        import web  # noqa: PLC0415 - only needed for this mode
        approvals = web.Approvals()
        approvals.install()
        token = os.environ.get("SMOLPAW_WEB_TOKEN") or secrets.token_urlsafe(18)
        web_info = {"mode": "eval", "backend": args.backend, "model": args.model, "status": "loading model"}
        web_server = web.serve(args.web_host, args.web_port, token, approvals, info=web_info)
        print(f"answer prompts at {web.url(args.web_host, args.web_port, token)}")
    else:
        g.CONFIRM = lambda desc: False
        g.ASK = lambda q: "(no answer: nobody is at the keyboard. Do not ask again; make your best attempt.)"

    ctx = None
    try:
        if not args.no_load:
            ctx = ensure_model(args.model, args.ctx, args.backend)
        label = args.label or (f"tidepool-{args.tidepool}" if args.tidepool else "listing" if args.listing else "custom")
        print(f"eval {label} | {args.backend}: {args.model} | loaded context {ctx} | n={args.n}")
        results = []
        for i in range(1, args.n + 1):
            web_info.update(status="running", progress=f"{label}: run {i} of {args.n}")
            r = run_once(args.model, prompt, expects, args.max_steps, args.backend, not args.text_history)
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
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        out = ROOT / "logs" / f"eval-{stamp}-{args.backend}-{safe_name(args.model)}-{label}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"backend": args.backend, "model": args.model, "label": label,
                                   "history": "text" if args.text_history else "native",
                                   "loaded_context": ctx, "prompt": prompt, "expect": expects,
                                   "runs": results}, indent=2))
        print(f"  saved {out.relative_to(ROOT)}")
    finally:
        if server:
            server.terminate()
        if web_server:
            web_server.shutdown()


if __name__ == "__main__":
    main()
