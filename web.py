"""
SmolPaw web harness: run the agent and answer its [y/N] prompts and questions from a browser.

  .venv/bin/python web.py --backend ollama --host 0.0.0.0

Open the printed URL; it carries the access token, and every request must present it. The
confirmation rules are unchanged: this only replaces where the prompts are answered.
"""

import argparse
import hmac
import itertools
import json
import os
import secrets
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import generic_tools as g
from agent import BACKENDS, MAX_STEPS, build_agent, load_env, run_request

PORT = 8770
MAX_BODY = 64_000
MAX_PROMPT = 4_000
FEED_LINES = 40
NO_ANSWER = "(no answer from the user in time. Do not ask again; make your best attempt.)"


class Approvals:
    """Prompts waiting for an answer from the browser. The agent blocks until answered, as with input()."""

    def __init__(self, timeout: float = 0):
        self.timeout = timeout  # seconds; 0 waits forever. Unanswered confirms count as "no".
        self._serial = threading.Lock()  # tools can run in parallel threads: one prompt at a time
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._ids = itertools.count(int(time.time() * 1000))  # unique across restarts, so the page never reuses an id
        self._answer: object = None
        self.pending: dict | None = None

    def _wait(self, kind: str, text: str, default: object) -> object:
        with self._serial:
            with self._lock:
                self.pending = {"id": next(self._ids), "kind": kind, "text": g._redact(text)}
                self._answer = None
                self._done.clear()
            answered = self._done.wait(self.timeout or None)
            with self._lock:
                self.pending = None
                return self._answer if answered else default

    def confirm(self, desc: str) -> bool:
        return self._wait("confirm", desc, False) is True

    def ask(self, question: str) -> str:
        answer = self._wait("ask", question, NO_ANSWER)
        return answer if isinstance(answer, str) and answer.strip() else NO_ANSWER

    def answer(self, prompt_id: int, value: object) -> bool:
        """Answer the pending prompt if `prompt_id` is still current; stale answers are refused."""
        with self._lock:
            if not self.pending or self.pending["id"] != prompt_id:
                return False
            kind = self.pending["kind"]
            if kind == "confirm" and not isinstance(value, bool):
                return False
            if kind == "ask" and not isinstance(value, str):
                return False
            self._answer = value[:MAX_PROMPT] if isinstance(value, str) else value
            self._done.set()
            return True

    def cancel(self) -> None:
        """Decline whatever is pending (used by Stop)."""
        with self._lock:
            if self.pending:
                self._answer = False if self.pending["kind"] == "confirm" else NO_ANSWER
                self._done.set()

    def install(self) -> None:
        g.CONFIRM = self.confirm
        g.ASK = self.ask


class Session:
    """Runs one agent request at a time in a background thread."""

    def __init__(self, agent, model: str, approvals: Approvals, backend: str = "lmstudio",
                 max_steps: int = MAX_STEPS):
        self.agent, self.model, self.approvals = agent, model, approvals
        self.backend, self.max_steps = backend, max_steps
        self._lock = threading.Lock()
        self.status, self.prompt, self.answer, self.outcome, self.error = "idle", "", "", "", ""
        self.started_at = 0.0

    def start(self, prompt: str) -> bool:
        with self._lock:
            if self.status == "running":
                return False
            self.status, self.prompt, self.answer, self.outcome, self.error = "running", prompt, "", "", ""
            self.started_at = time.time()
        threading.Thread(target=self._run, args=(prompt,), daemon=True).start()
        return True

    def _run(self, prompt: str) -> None:
        try:
            self.answer, self.outcome = run_request(self.agent, self.model, "generic", prompt)
        except Exception as exc:  # noqa: BLE001 - shown on the page, as the CLI prints it
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.status = "idle"

    def stop(self) -> None:
        self.agent.interrupt()
        self.approvals.cancel()

    def configure(self, backend: str, model: str, max_steps: int, timeout: float) -> bool:
        """Switch backend, model, step limit and prompt timeout between requests; refused while one runs."""
        with self._lock:
            if self.status == "running":
                return False
            if (backend, model, max_steps) != (self.backend, self.model, self.max_steps):
                self.agent = build_agent(model, "tool", max_steps, "generic", backend)
                self.backend, self.model, self.max_steps = backend, model, max_steps
            self.approvals.timeout = timeout
            return True


def list_models(backend: str) -> list[str]:
    """Model ids the backend's server lists (both expose the OpenAI-style /models); empty if unreachable."""
    try:
        req = urllib.request.Request(BACKENDS[backend]["url"] + "/models",
                                     headers={"Authorization": f"Bearer {BACKENDS[backend]['key']}"})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read(1_000_000))
        return sorted(str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and "id" in m)
    except (OSError, ValueError, KeyError, AttributeError):
        return []


TOOL_KINDS = {
    "shell", "http", "fetch_page", "openapi_search",
    "read_file", "write_file", "list_skills", "read_skill", "write_skill",
    "remember", "recall", "ask",
}


def feed(log_path: Path | None = None) -> list[str]:
    """Short lines from a run log (default: current run, already redacted by generic_tools)."""
    target = log_path if log_path is not None else g._log_file
    if not target or not target.exists():
        return []
    try:
        raw_lines = target.read_text().splitlines()
    except OSError:
        return []
    lines = []
    for raw in raw_lines[-FEED_LINES:]:
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = e.get("t", "")[11:]
        kind = e.get("kind")
        if kind == "shell":
            lines.append(f"{t} $ {e.get('command')} (exit {e.get('exit')})")
        elif kind == "http":
            lines.append(f"{t} {e.get('method')} {e.get('url')} -> {e.get('status')}")
        elif kind == "preflight":
            lines.append(f"{t} refused before sending: {e.get('method')} {e.get('url')} ({e.get('reason')})")
        elif kind == "confirm":
            first = (str(e.get("desc", "")).splitlines() or [""])[0]
            lines.append(f"{t} asked: {first} -> {'yes' if e.get('approved') else 'no'}")
        elif kind == "ask":
            lines.append(f"{t} question: {e.get('question')}")
        elif kind == "read_file":
            lines.append(f"{t} read_file {e.get('path')} -> {e.get('result')}")
        elif kind == "write_file":
            lines.append(f"{t} write_file {e.get('path')} ({e.get('chars')} chars) -> {e.get('result')}")
        elif kind == "list_skills":
            lines.append(f"{t} list_skills -> {e.get('result')}")
        elif kind == "read_skill":
            lines.append(f"{t} read_skill {e.get('name')} -> {e.get('result')}")
        elif kind == "write_skill":
            lines.append(f"{t} write_skill {e.get('name')} ({e.get('chars')} chars) -> {e.get('result')}")
        elif kind == "openapi_search":
            lines.append(f"{t} openapi_search {e.get('spec_url')} {e.get('keyword') or '(no keyword)'} -> {e.get('result')}")
        elif kind == "fetch_page":
            lines.append(f"{t} fetch_page {e.get('url')} {e.get('query') or '(no query)'} -> {e.get('result')}")
        elif kind == "remember":
            lines.append(f"{t} remember {e.get('fact')}")
        elif kind == "recall":
            lines.append(f"{t} recall {e.get('query') or '(all)'} -> {e.get('result')}")
        elif kind in ("start", "final"):
            lines.append(f"{t} {kind}")
    return [g._redact(line) for line in lines]


def _run_summary(path: Path | None) -> str | None:
    """One-line summary for a run log derived from existing log fields."""
    if not path or not path.exists():
        return None
    try:
        raw_lines = path.read_text().splitlines()
    except OSError:
        return None
    entries = []
    for raw in raw_lines:
        try:
            entries.append(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    if not entries:
        return None
    start = next((e for e in entries if e.get("kind") == "start"), None)
    if not start:
        return None
    start_t = start.get("t", "")
    model = start.get("model", "")
    has_final = any(e.get("kind") == "final" for e in entries)
    if has_final:
        last_t = entries[-1].get("t", "")
        try:
            d = max(0.0, (datetime.fromisoformat(last_t) - datetime.fromisoformat(start_t)).total_seconds())
            dur = f"{int(round(d))}s"
        except (ValueError, TypeError):
            dur = "unfinished"
    else:
        dur = "unfinished"
    tool_calls = sum(1 for e in entries if e.get("kind") in TOOL_KINDS)
    tool_str = f"{tool_calls} tool call" if tool_calls == 1 else f"{tool_calls} tool calls"
    final = next((e for e in entries if e.get("kind") == "final"), {})
    tokens = ""
    if isinstance(final.get("input_tokens"), int):
        tokens = f" · {final['input_tokens']:,} in / {final.get('output_tokens', 0):,} out tokens"
    return g._redact(f"{start_t} · {model} · {dur} · {tool_str}{tokens}")


def _list_runs() -> list[dict]:
    """List recent runs from g.LOG_DIR, newest first, capped at 20."""
    if not g.LOG_DIR.exists() or not g.LOG_DIR.is_dir():
        return []
    try:
        files = sorted(g.LOG_DIR.glob("*.jsonl"), key=lambda f: f.name, reverse=True)
    except OSError:
        return []
    runs = []
    for f in files:
        if not f.is_file():
            continue
        summary = _run_summary(f)
        if summary is None:
            continue
        runs.append({"id": f.name, "summary": summary})
        if len(runs) >= 20:
            break
    return runs


def _files_payload() -> dict:
    """Read-only view of notes.md, skills/*.md and memory.md, secret-redacted and clipped."""
    def read_safe(p: Path) -> str:
        try:
            if p.exists() and p.is_file():
                return g._clip(g._redact(p.read_text()))
        except OSError:
            pass
        return ""

    skills = []
    try:
        if g.SKILLS.exists() and g.SKILLS.is_dir():
            for f in sorted(g.SKILLS.glob("*.md")):
                if f.is_file():
                    try:
                        skills.append({"name": f.stem, "text": g._clip(g._redact(f.read_text()))})
                    except OSError:
                        continue
    except OSError:
        pass
    return {
        "notes": read_safe(g.NOTES),
        "skills": skills,
        "memory": read_safe(g.MEMORY),
    }


def make_handler(token: str, approvals: Approvals, session: Session | None, info: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass  # keep the terminal for the agent's own output

        def _authed(self) -> bool:
            given = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("t", [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")  # the token is in the page URL
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._authed():
                return self._send(403, {"error": "missing or wrong token"})
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/state":
                s = session
                curr_summary = _run_summary(g._log_file) if g._log_file else ""
                return self._send(200, {
                    **info, "can_run": s is not None,
                    **({"backends": sorted(BACKENDS), "backend": s.backend, "model": s.model,
                        "max_steps": s.max_steps, "timeout": approvals.timeout} if s else {}),
                    "status": s.status if s else info.get("status", "running"),
                    "started_at": s.started_at if s and s.status == "running" else None,
                    "prompt": s.prompt if s else "", "answer": s.answer if s else "",
                    "outcome": s.outcome if s else "", "error": s.error if s else "",
                    "pending": approvals.pending, "feed": feed(),
                    "summary": curr_summary or "", "run_id": g._log_file.name if g._log_file else ""})
            if path == "/api/models":
                backend = parse_qs(urlparse(self.path).query).get("backend", [""])[0]
                if backend not in BACKENDS:
                    return self._send(404, {"error": "unknown backend"})
                return self._send(200, list_models(backend))
            if path == "/api/files":
                return self._send(200, _files_payload())
            if path == "/api/runs":
                return self._send(200, _list_runs())
            if path == "/api/run_feed":
                run_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                if not run_id or "/" in run_id or "\\" in run_id:
                    return self._send(404, {"error": "not found"})
                if not g.LOG_DIR.exists() or not g.LOG_DIR.is_dir():
                    return self._send(404, {"error": "not found"})
                try:
                    files = list(g.LOG_DIR.glob("*.jsonl"))
                except OSError:
                    return self._send(404, {"error": "not found"})
                matched = next((f for f in files if f.name == run_id), None)
                if not matched:
                    return self._send(404, {"error": "not found"})
                return self._send(200, feed(matched))
            return self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authed():
                return self._send(403, {"error": "missing or wrong token"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad JSON"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "expected a JSON object"})
            path = urlparse(self.path).path
            if path == "/api/answer":
                ok = approvals.answer(body.get("id"), body.get("value"))
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/run" and session:
                prompt = str(body.get("prompt", "")).strip()
                if not prompt or len(prompt) > MAX_PROMPT:
                    return self._send(400, {"error": "empty or too long"})
                ok = session.start(prompt)
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/settings" and session:
                backend, model = body.get("backend"), body.get("model")
                steps, timeout = body.get("max_steps"), body.get("timeout")
                if (backend not in BACKENDS or not isinstance(model, str) or not model.strip()
                        or len(model) > 200 or isinstance(steps, bool) or not isinstance(steps, int)
                        or not 1 <= steps <= 50 or isinstance(timeout, bool)
                        or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 3600):
                    return self._send(400, {"error": "invalid settings"})
                ok = session.configure(backend, model.strip(), steps, float(timeout))
                return self._send(200 if ok else 409, {"ok": ok})
            if path == "/api/stop" and session:
                session.stop()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return Handler


def serve(host: str, port: int, token: str, approvals: Approvals, session: Session | None = None,
          info: dict | None = None) -> ThreadingHTTPServer:
    """Start the web server in a background thread. `info` is shown on the page (eval uses it for progress)."""
    server = ThreadingHTTPServer((host, port), make_handler(token, approvals, session, info or {}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def url(host: str, port: int, token: str) -> str:
    shown = "<this-machine>" if host in ("0.0.0.0", "::") else host
    return f"http://{shown}:{port}/?t={token}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run SmolPaw and answer its prompts from a browser.")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio")
    ap.add_argument("--model", default=None, help="default depends on --backend")
    ap.add_argument("--max-steps", type=int, default=None, help="default: MAX_STEPS env var, else 12")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for all interfaces, e.g. to reach it over Tailscale)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--timeout", type=float, default=0, help="seconds before an unanswered prompt counts as no "
                                                              "(default: wait forever)")
    args = ap.parse_args()

    load_env()
    model = args.model or BACKENDS[args.backend]["model"]
    max_steps = args.max_steps or int(os.environ.get("MAX_STEPS", MAX_STEPS))
    token = os.environ.get("SMOLPAW_WEB_TOKEN") or secrets.token_urlsafe(18)
    approvals = Approvals(args.timeout)
    approvals.install()
    session = Session(build_agent(model, "tool", max_steps, "generic", args.backend), model, approvals,
                      args.backend, max_steps)
    server = serve(args.host, args.port, token, approvals, session,
                   {"mode": "agent", "backend": args.backend, "model": model})
    print(f"SmolPaw web [{args.backend}: {model}] at {url(args.host, args.port, token)}  (Ctrl-C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nBye.")
        server.shutdown()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SmolPaw</title>
<style>
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#dcdad5; --accent:#2f6fde;
        --yes:#1f8a4c; --no:#c23b3b; --warn:#fff4d6; }
@media (prefers-color-scheme: dark) { :root { --bg:#151517; --card:#1f1f22; --ink:#ececee; --muted:#9a9aa1;
        --line:#333338; --accent:#6b9cff; --yes:#3fbf73; --no:#ff6b6b; --warn:#3a3220; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 -apple-system, system-ui, sans-serif; }
main { max-width:720px; margin:0 auto; padding:16px; overflow-wrap:anywhere; }
h1 { font-size:20px; margin:0 0 4px; }
.meta { color:var(--muted); font-size:14px; margin-bottom:16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
.card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 8px; }
.pending { border:2px solid var(--accent); background:var(--warn); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:0; font:14px/1.4 ui-monospace, Menlo, monospace; }
textarea { width:100%; min-height:84px; font:inherit; padding:10px; border-radius:8px; border:1px solid var(--line);
           background:var(--bg); color:var(--ink); }
.row { display:flex; gap:10px; margin-top:10px; }
button { flex:1; font:inherit; font-weight:600; padding:12px; border-radius:10px; border:0; color:#fff;
         background:var(--accent); }
button.yes { background:var(--yes); } button.no { background:var(--no); }
button.ghost { background:transparent; color:var(--muted); border:1px solid var(--line); }
button:disabled { opacity:.45; }
.cardhead { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.cardhead h2 { margin:0; }
.copybtn { font:12px inherit; font-weight:600; padding:4px 10px; border-radius:6px; border:1px solid var(--line);
           background:transparent; color:var(--muted); }
.feed pre { font-size:12px; color:var(--muted); }
summary { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; cursor:pointer; }
summary:focus { outline:none; }
.filesec { margin-top:12px; }
.filesec h3 { font-size:12px; font-weight:600; color:var(--muted); margin:8px 0 2px; }
.runitem { padding:6px 8px; border-radius:6px; cursor:pointer; font-size:12px; font-family:ui-monospace, Menlo, monospace; color:var(--muted); margin-bottom:4px; }
.runitem:hover { background:var(--bg); color:var(--ink); }
select, input { width:100%; font:inherit; padding:8px; border-radius:8px; border:1px solid var(--line);
                background:var(--bg); color:var(--ink); }
[hidden] { display:none !important; }
.nav { display:none; }
aside { padding:16px 16px 0; }
main { display:flex; flex-direction:column; }
#content, .col { display:contents; }
#recentcard { order:1; }
@media (min-width:900px) {
  body { display:grid; grid-template-columns:220px minmax(0,1fr); min-height:100vh; }
  aside { position:sticky; top:0; height:100vh; padding:20px 14px; border-right:1px solid var(--line);
          background:var(--card); display:flex; flex-direction:column; gap:6px; overflow-y:auto; }
  aside h1 { font-size:22px; margin:0 0 12px 8px; }
  aside .meta { margin:auto 8px 0; font-size:12px; }
  .nav { display:block; text-align:left; background:transparent; color:var(--muted); font-weight:600;
         padding:10px 12px; border-radius:8px; flex:none; }
  .nav:hover { background:var(--bg); color:var(--ink); }
  .nav.on { background:var(--bg); color:var(--accent); }
  main { display:block; max-width:none; width:100%; padding:24px 32px; }
  #content { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:0 24px; align-items:start; }
  .col { display:block; }
  .side { position:sticky; top:24px; }
  [data-views] { display:none; }
  body[data-view=chat] [data-views~=chat], body[data-view=runs] [data-views~=runs],
  body[data-view=files] [data-views~=files], body[data-view=settings] [data-views~=settings] { display:block; }
  body[data-view=files] #content, body[data-view=settings] #content { grid-template-columns:minmax(0,760px); }
  #setcard > summary, #filescard > summary { display:none; }
  #prompt { min-height:120px; }
  .feed pre, #recentcard .runitem { font-size:13px; }
}
</style></head><body data-view="chat">
<aside><h1>SmolPaw</h1>
  <button class="nav on" data-view="chat">Chat</button><button class="nav" data-view="runs">Runs</button>
  <button class="nav" data-view="files">Files</button><button class="nav" data-view="settings">Settings</button>
  <div class="meta" id="meta">connecting...</div></aside>
<main><div id="content"><div class="col">
<div class="card pending" id="pending" data-views="chat runs files settings" hidden><h2 id="pkind">Approval needed</h2><pre id="ptext"></pre>
  <div class="row" id="yesno"><button class="yes" id="yes">Yes</button><button class="no" id="no">No</button></div>
  <div id="askbox" hidden><textarea id="reply" placeholder="Your answer"></textarea>
    <div class="row"><button id="send">Send answer</button></div></div></div>
<div class="card" id="runcard" data-views="chat" hidden><h2>Request</h2><textarea id="prompt" placeholder="What should the agent do?"></textarea>
  <div class="row"><button id="run">Run</button><button class="ghost" id="stop">Stop</button></div>
  <div class="meta" id="working" hidden></div></div>
<details class="card" id="setcard" data-views="settings" hidden><summary>Settings</summary>
  <div class="filesec">
    <h3>Backend</h3><select id="sbackend"></select>
    <h3>Model</h3><input id="smodel" list="smodels" autocomplete="off"><datalist id="smodels"></datalist>
    <h3>Step limit</h3><input id="ssteps" type="number" min="1" max="50">
    <h3>Prompt timeout (seconds, 0 waits forever)</h3><input id="stimeout" type="number" min="0" max="3600">
    <div class="row"><button id="sapply">Apply</button></div>
    <div class="meta" id="smsg"></div>
  </div></details>
<div class="card" id="result" data-views="chat" hidden><div class="cardhead"><h2>Answer</h2><button class="copybtn" id="copy">Copy</button></div>
  <pre id="answer"></pre><pre id="outcome" style="margin-top:10px"></pre></div>
<details class="card" id="filescard" data-views="files"><summary>Files</summary>
  <div class="filesec">
    <h2>Notes (notes.md)</h2>
    <pre id="fnotes">(empty)</pre>
    <h2 style="margin-top:12px">Skills (skills/)</h2>
    <div id="fskills"><pre>(none)</pre></div>
    <h2 style="margin-top:12px">Memory (memory.md)</h2>
    <pre id="fmemory">(empty)</pre>
  </div></details>
<div class="card" id="recentcard" data-views="runs"><h2>Recent runs</h2><div id="runslist"><pre>(no runs yet)</pre></div></div>
</div><div class="col side">
<div class="card feed" data-views="chat runs"><div class="cardhead"><h2>Activity</h2><button class="copybtn" id="livebtn" hidden>Current run</button></div>
  <div class="meta" id="actsummary" style="margin-bottom:8px"></div>
  <pre id="feed">(nothing yet)</pre></div>
</div></div></div></main><script>
const token = new URLSearchParams(location.search).get("t") || "";
const $ = id => document.getElementById(id);
let pendingId = null;
let startedAt = null;
const VERBS = ["Pawing", "Sniffing", "Fetching", "Digging", "Trotting", "Scouting",
               "Rummaging", "Burrowing", "Tinkering", "Nosing around"];
function tick() {
  if (!startedAt) return;
  const secs = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  const verb = VERBS[Math.floor(secs / 3) % VERBS.length];
  $("working").textContent = verb + "... (" + secs + "s)";
}
setInterval(tick, 1000);
async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", cache: "no-store",
    headers: {"X-Token": token, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
async function answer(value) { if (pendingId !== null) { await api("/api/answer", {id: pendingId, value}); refresh(); } }
$("yes").onclick = () => answer(true);
$("no").onclick = () => answer(false);
$("send").onclick = () => { answer($("reply").value); $("reply").value = ""; };
$("run").onclick = async () => { const p = $("prompt").value.trim(); if (p) { await api("/api/run", {prompt: p}); refresh(); } };
$("stop").onclick = () => api("/api/stop", {});
$("copy").onclick = async () => {
  const text = $("answer").textContent;
  const flash = msg => { $("copy").textContent = msg; setTimeout(() => { $("copy").textContent = "Copy"; }, 1500); };
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      document.execCommand("copy"); document.body.removeChild(ta);
    }
    flash("Copied!");
  } catch (e) { flash("Copy failed"); }
};
async function loadFiles() {
  try {
    const data = await api("/api/files");
    $("fnotes").textContent = data.notes || "(empty)";
    $("fmemory").textContent = data.memory || "(empty)";
    const skillsDiv = $("fskills");
    while (skillsDiv.firstChild) skillsDiv.removeChild(skillsDiv.firstChild);
    if (!data.skills || !data.skills.length) {
      const p = document.createElement("pre");
      p.textContent = "(none)";
      skillsDiv.appendChild(p);
    } else {
      for (const s of data.skills) {
        const title = document.createElement("h3");
        title.textContent = s.name;
        const pre = document.createElement("pre");
        pre.textContent = s.text || "(empty)";
        skillsDiv.appendChild(title);
        skillsDiv.appendChild(pre);
      }
    }
  } catch (e) {}
}
let setLoaded = false;
async function loadModels() {
  try {
    const models = await api("/api/models?backend=" + encodeURIComponent($("sbackend").value));
    const dl = $("smodels");
    while (dl.firstChild) dl.removeChild(dl.firstChild);
    for (const m of models) { const o = document.createElement("option"); o.value = m; dl.appendChild(o); }
    $("smsg").textContent = models.length ? "" : "Could not list models from this server; type an id.";
  } catch (e) {}
}
function fillSettings(s) {
  if (setLoaded) return;
  setLoaded = true;
  const sel = $("sbackend");
  for (const b of s.backends || [s.backend]) {
    const o = document.createElement("option"); o.value = o.textContent = b; sel.appendChild(o);
  }
  sel.value = s.backend; $("smodel").value = s.model;
  $("ssteps").value = s.max_steps; $("stimeout").value = s.timeout;
}
$("sbackend").onchange = () => { $("smodel").value = ""; loadModels(); };
$("setcard").ontoggle = () => { if ($("setcard").open) loadModels(); };
$("sapply").onclick = async () => {
  const r = await fetch("/api/settings", {method: "POST", cache: "no-store",
    headers: {"X-Token": token, "Content-Type": "application/json"},
    body: JSON.stringify({backend: $("sbackend").value, model: $("smodel").value,
      max_steps: parseInt($("ssteps").value, 10), timeout: Number($("stimeout").value)})});
  $("smsg").textContent = r.ok ? "Applied." : r.status === 409 ? "A request is running; try again when it finishes." : "Invalid settings.";
  refresh();
};
$("filescard").ontoggle = () => { if ($("filescard").open) loadFiles(); };
let selectedRunId = null, lastRunId = null, runsKey = null;
async function loadRuns() {
  try {
    const runs = await api("/api/runs");
    const container = $("runslist");
    while (container.firstChild) container.removeChild(container.firstChild);
    if (!runs || !runs.length) {
      const p = document.createElement("pre");
      p.textContent = "(no runs yet)";
      container.appendChild(p);
      return;
    }
    for (const r of runs) {
      const row = document.createElement("div");
      row.className = "runitem";
      row.textContent = r.summary;
      row.onclick = async () => {
        selectedRunId = r.id;
        try {
          const lines = await api("/api/run_feed?id=" + encodeURIComponent(r.id));
          $("feed").textContent = (lines || []).join("\\n") || "(empty run log)";
          $("actsummary").textContent = r.summary;
          $("livebtn").hidden = false;
        } catch (e) {}
      };
      container.appendChild(row);
    }
  } catch (e) {}
}
$("livebtn").onclick = () => {
  selectedRunId = null;
  $("livebtn").hidden = true;
  refresh();
};
async function refresh() {
  let s; try { s = await api("/api/state"); } catch (e) { $("meta").textContent = "cannot reach SmolPaw"; return; }
  $("meta").textContent = [s.mode, s.backend, s.model, s.status, s.progress].filter(Boolean).join(" · ");
  const p = s.pending;
  $("pending").hidden = !p;
  if (p && p.id !== pendingId) {
    pendingId = p.id; $("ptext").textContent = p.text;
    $("pkind").textContent = p.kind === "confirm" ? "Approval needed" : "The agent asks";
    $("yesno").hidden = p.kind !== "confirm"; $("askbox").hidden = p.kind !== "ask";
    if (navigator.vibrate) navigator.vibrate(200);
  }
  if (!p) pendingId = null;
  $("runcard").hidden = !s.can_run;
  $("setcard").hidden = !s.can_run;
  if (s.can_run) fillSettings(s);
  $("sapply").disabled = s.status === "running";
  $("run").disabled = s.status === "running"; $("stop").disabled = s.status !== "running";
  $("working").hidden = s.status !== "running";
  if (s.status === "running") { startedAt = s.started_at ? s.started_at * 1000 : (startedAt || Date.now()); tick(); }
  else { startedAt = null; }
  const done = s.answer || s.error;
  $("result").hidden = !done && !s.prompt;
  $("answer").textContent = s.error ? "[Error] " + s.error : (s.answer || (s.prompt ? "working on: " + s.prompt : ""));
  $("outcome").textContent = s.outcome || "";
  if (lastRunId !== null && s.run_id !== lastRunId) selectedRunId = null;
  lastRunId = s.run_id;
  if (!selectedRunId) {
    $("livebtn").hidden = true;
    $("actsummary").textContent = s.summary || "";
    $("feed").textContent = (s.feed || []).join("\\n") || "(nothing yet)";
  }
  if ($("filescard").open) loadFiles();
  const key = [s.run_id, s.status, s.summary].join("|");
  if (key !== runsKey) { runsKey = key; loadRuns(); }
}
const wide = window.matchMedia("(min-width:900px)");
function openPanels() { if (wide.matches) { $("setcard").open = true; $("filescard").open = true; } }
function setView(v) {
  document.body.dataset.view = v;
  for (const b of document.querySelectorAll(".nav")) b.classList.toggle("on", b.dataset.view === v);
  try { localStorage.setItem("smolpawView", v); } catch (e) {}
}
for (const b of document.querySelectorAll(".nav")) b.onclick = () => setView(b.dataset.view);
try { const v = localStorage.getItem("smolpawView"); if (["chat", "runs", "files", "settings"].includes(v)) setView(v); } catch (e) {}
wide.onchange = openPanels; openPanels();
refresh(); setInterval(refresh, 1500);
</script></body></html>
"""


if __name__ == "__main__":
    main()
