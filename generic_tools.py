"""
Generic tools for the SmolPaw agent, with a Python-side confirmation layer.

The model gets a shell, HTTP, files, skills and a way to ask the user. Every
safety rule lives here, not in the prompt, so the model cannot talk its way past it:

  - read-only commands inside workspace/ and skills/ run freely; HTTP GET runs freely
  - anything else asks the user [y/N] first (writes, other HTTP methods, other commands)
  - API keys are added by the harness for hosts listed in notes.md; the model never sees them
  - .env files can never be read or written
"""

import functools
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time
import warnings
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse

import requests
from smolagents import tool

# _remember wraps tools; smolagents only warns about this for its remote executor, which we do not use.
warnings.filterwarnings("ignore", message=".*has decorators other than @tool.*")

ROOT = Path(__file__).parent
WORKSPACE = ROOT / "workspace"
SKILLS = ROOT / "skills"
NOTES = ROOT / "notes.md"
MEMORY = ROOT / "memory.md"
LOG_DIR = ROOT / "logs"
UNDO_DIR = ROOT / ".undo"
UNDO_MAX_BYTES = 1_000_000
UNDO_KEEP = 10

READ_ONLY_CMDS = {"ls", "cat", "head", "grep", "find", "wc", "stat", "file"}
FIND_UNSAFE = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf"}
SHELL_META = re.compile(r"[;&|<>`$()\\\n]")
MAX_OUT = 4000
USER_AGENT = "SmolPaw/0.1 (local agent; https://github.com/aurora7795/smolpaw)"
DECLINED = "DECLINED: the user said no. Nothing was done. Try another approach or call ask_user."


def _ask(prompt: str) -> bool:
    return input(f"\n{prompt} [y/N] ").strip().lower() == "y"


# The eval harness replaces these to script answers.
CONFIRM = _ask


def _ask_user(question: str) -> str:
    try:
        return input(f"\n[agent asks] {question}\n> ")
    except EOFError:
        return "(no answer: the user is not at the keyboard. Do not ask again; make your best attempt.)"


ASK = _ask_user

_SEARCH_COUNT = 0
_SEARCH_LOCK = threading.Lock()  # tools can run in parallel threads: check and count together
MAX_SEARCHES = 3


def reset_search_count() -> None:
    """Start a new per-request search allowance (start_log() calls this once per request)."""
    global _SEARCH_COUNT
    with _SEARCH_LOCK:
        _SEARCH_COUNT = 0


ACTIONS: list[str] = []  # outcomes of side-effecting calls; the harness prints these as ground truth
_log_file: Path | None = None


# --- logging, secrets -------------------------------------------------------------

def services() -> dict[str, dict]:
    """Parse notes.md lines like `- radarr: http://host:7878 | key_env=RADARR_API_KEY | header=X-Api-Key`."""
    found = {}
    if not NOTES.exists():
        return found
    for line in NOTES.read_text().splitlines():
        m = re.match(r"^- (\w+): (https?://\S+)((?: \| \w+=\S+)*)\s*$", line)
        if not m:
            continue
        opts = dict(kv.split("=", 1) for kv in m.group(3).split(" | ") if kv)
        found[m.group(1)] = {"url": m.group(2).rstrip("/"), **opts}
    return found


def _secrets() -> list[str]:
    values = [os.environ.get(s.get("key_env", ""), "") for s in services().values()]
    return [v for v in values if len(v) >= 8]


def _redact(text: str) -> str:
    for secret in _secrets():
        text = text.replace(secret, "[REDACTED]")
    return text


# Common credential shapes, for a backstop over ask_user (#32): unlike _redact() above, this does
# not need the secret to be pre-registered in notes.md/.env. A human can paste any credential into
# an answer; this catches the common ones regardless of which service they are for.
_CRED_PATTERNS = [re.compile(p) for p in [
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",              # GitHub PAT / OAuth / user-to-server / refresh token
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",            # GitHub fine-grained PAT
    r"\bAKIA[0-9A-Z]{16}\b",                        # AWS access key id
    r"\bASIA[0-9A-Z]{16}\b",                        # AWS temporary access key id
    r"\bsk-[A-Za-z0-9]{20,}\b",                     # OpenAI/Anthropic-style secret key
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",            # Slack token
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWT
]]
_CRED_CATCHALL = re.compile(r"(?<![A-Za-z0-9_/+=])[A-Za-z0-9_/+=]{28,}(?![A-Za-z0-9_/+=])")


def _looks_like_a_token(s: str) -> bool:
    """Conservative check for the generic catch-all: mixed letters and digits, no spaces, no obvious word."""
    return any(c.isdigit() for c in s) and any(c.isalpha() for c in s)


def redact_pasted_secrets(text: str) -> str:
    """Mask anything in text that looks like a pasted credential, whoever it is for (#32).

    _redact() above only knows about secrets the harness itself injected for a service listed in
    notes.md. A human can paste a real credential straight into an ask_user answer; this is the
    backstop for that case, so it never reaches the model's context, the run log, or anything the
    model echoes back.
    """
    for pat in _CRED_PATTERNS:
        text = pat.sub("[REDACTED: looks like a credential]", text)
    return _CRED_CATCHALL.sub(
        lambda m: "[REDACTED: looks like a credential]" if _looks_like_a_token(m.group(0)) else m.group(0), text)


LOG_OUT = 500  # chars of shell output kept in the run log, so a run can be audited afterwards


def _page(text: str, offset: int = 0) -> str:
    """One MAX_OUT page of text from offset; a long file gets a footer naming the characters shown and the next offset."""
    total = len(text)
    if total <= MAX_OUT and offset <= 0:
        return text
    offset = max(offset, 0)
    if offset >= total:
        return f"[offset {offset} is past the end of the file ({total} characters)]"
    end = min(offset + MAX_OUT, total)
    more = f"call read_file again with offset={end} to continue" if end < total else "end of file"
    return f"{text[offset:end]}\n[characters {offset}-{end} of {total}; {more}]"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUT else text[:MAX_OUT] + f"\n... [truncated, {len(text)} chars total]"


def _show(label: str, text: str) -> None:
    """Remember a result the user should be able to read, since the agent may not repeat it in its answer."""
    global SHOWN_OUTPUT
    SHOWN_OUTPUT = (_redact(label), text)


def _log(kind: str, **fields) -> None:
    if _log_file:
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "kind": kind, **fields}
        with _log_file.open("a") as f:
            f.write(_redact(json.dumps(entry, default=str)) + "\n")


def start_log(model: str, prompt: str, thread: str | None = None, schedule: str | None = None) -> Path:
    global _log_file, SHOWN_OUTPUT
    SHOWN_OUTPUT = None
    reset_search_count()
    LOG_DIR.mkdir(exist_ok=True)
    _log_file = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{model.replace('/', '_')}.jsonl"
    _log("start", model=model, prompt=prompt, **({"thread": thread} if thread else {}),
         **({"schedule": schedule} if schedule else {}))
    return _log_file


def log_final(answer: object, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
    """Close the run log; token totals (when the caller has them) feed the web page's run summary."""
    extra = {} if input_tokens is None else {"input_tokens": input_tokens, "output_tokens": output_tokens or 0}
    _log("final", answer=str(answer), actions=list(ACTIONS), **extra)


SHOWN_OUTPUT: tuple[str, str] | None = None  # (label, text) of the latest shell or list_dir result, for the web page
LAST_RESULT = ""  # most recent tool output, shown by the harness if the agent hits the step cap


def _remember(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global LAST_RESULT
        result = fn(*args, **kwargs)
        LAST_RESULT = f"{fn.__name__}: {result}"[:1500]
        return result
    return wrapper


def _approved(desc: str) -> bool:
    ok = CONFIRM(desc)
    _log("confirm", desc=desc, approved=ok)
    if not ok:
        ACTIONS.append(f"declined: {desc.splitlines()[0]}")
    return ok


# --- paths ------------------------------------------------------------------------

def _resolve(path: str) -> Path:
    return (WORKSPACE / os.path.expanduser(path)).resolve()


def _in_scope(path: str) -> bool:
    p = _resolve(path)
    return any(p.is_relative_to(base.resolve()) for base in (WORKSPACE, SKILLS))


def _is_secret_file(path: Path) -> bool:
    return path.name.startswith(".env") or ".ssh" in path.parts


# --- undo / reversible writes -----------------------------------------------------

def _undo_tag(target: Path | str) -> str:
    """Readable, separator-free name for a path, plus a short hash so paths that sanitise or truncate
    to the same text (long paths, `a..b` against `ab`) keep separate copies and separate retention."""
    full = str(target).replace("\\", "/").strip()
    raw = re.sub(r"\.\.+", "", full)
    clean = re.sub(r"[/]+", "__", raw).strip("_")
    if len(clean) > 100:
        clean = clean[-100:].lstrip("_")
    digest = hashlib.sha1(full.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{clean or 'file'}__{digest}"


def _undo_name(target: Path | str, now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S-%f")
    tag = _undo_tag(target)
    return f"{ts}__{tag}"


def _prune_undo(target: Path | str) -> None:
    if not UNDO_DIR.exists():
        return
    tag = _undo_tag(target)
    suffix = f"__{tag}"
    undo_dir_resolved = UNDO_DIR.resolve()
    copies = []
    for f in UNDO_DIR.iterdir():
        if f.is_file() and f.name.endswith(suffix):
            try:
                if f.resolve().parent == undo_dir_resolved:
                    copies.append(f)
            except OSError:
                pass
    copies.sort(key=lambda x: x.name)
    if len(copies) > UNDO_KEEP:
        for f in copies[:len(copies) - UNDO_KEEP]:
            try:
                if f.resolve().parent == undo_dir_resolved:
                    f.unlink(missing_ok=True)
            except OSError:
                pass


def _save_undo(p: Path) -> tuple[Path | None, str | None]:
    """Copy pre-edit regular file to UNDO_DIR. Returns (saved_path, None) or (None, reason)."""
    if _is_secret_file(p):
        return None, "not saved: could not copy"
    try:
        st = os.lstat(p)
    except OSError:
        return None, None
    if not stat.S_ISREG(st.st_mode):
        return None, "not saved: could not copy"
    if st.st_size > UNDO_MAX_BYTES:
        return None, "not saved: too large"
    try:
        data = p.read_bytes()
    except (OSError, PermissionError):
        return None, "not saved: could not copy"
    try:
        UNDO_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)  # copies may hold private files
        name = _undo_name(p)
        dest = UNDO_DIR / name
        while dest.exists():
            time.sleep(0.0005)
            name = _undo_name(p)
            dest = UNDO_DIR / name
        with os.fdopen(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as fh:
            fh.write(data)
        _prune_undo(p)
        return dest, None
    except Exception:
        return None, "not saved: could not copy"


# --- shell ------------------------------------------------------------------------

def _read_only_argv(cmd: str) -> list[str] | None:
    """Return argv if cmd is a single read-only command touching only in-scope paths."""
    if SHELL_META.search(cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if not argv or argv[0] not in READ_ONLY_CMDS:
        return None
    if argv[0] == "find" and FIND_UNSAFE & set(argv):
        return None
    if not all(_in_scope(a) for a in argv[1:] if not a.startswith("-")):
        return None
    if any(_is_secret_file(_resolve(a)) for a in argv[1:] if not a.startswith("-")):
        return None
    # Expand ~ ourselves: argv runs without a shell, so a literal "~" would otherwise reach the command.
    return argv[:1] + [os.path.expanduser(a) for a in argv[1:]]


WINDOWS = platform.system() == "Windows"


def _ps_quote(arg: str) -> str:
    """Quote one argument for PowerShell's single-quoted string syntax (double an embedded quote)."""
    return "'" + arg.replace("'", "''") + "'"


def _run_argv(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a pre-validated read-only argv. PowerShell on Windows, since ls/cat are its own aliases
    (#33); there is no ls.exe/cat.exe on PATH by default, so a bare exec crashes with WinError 2."""
    if WINDOWS:
        # argv[0] is always a bare name from READ_ONLY_CMDS: quoting it would make PowerShell treat
        # it as a string literal instead of invoking it. shlex.join's POSIX quoting ('"'"') is also
        # not how PowerShell escapes an embedded quote, so arguments are quoted PowerShell-style.
        command = argv[0] + "".join(" " + _ps_quote(a) for a in argv[1:])
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                              cwd=WORKSPACE, capture_output=True, text=True, timeout=60)
    return subprocess.run(argv, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)


def _run_shell_string(command: str) -> subprocess.CompletedProcess:
    """Run an already-approved command line. PowerShell on Windows: shell=True there means cmd.exe,
    which does not understand ls/cat either (those are PowerShell aliases, not cmd.exe built-ins)."""
    if WINDOWS:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                              cwd=WORKSPACE, capture_output=True, text=True, timeout=60)
    # pipefail so a failing first stage of a pipe is not hidden by the last stage's exit 0 (#49)
    bash = shutil.which("bash")
    if bash:
        return subprocess.run([bash, "-c", "set -o pipefail; " + command], cwd=WORKSPACE,
                              capture_output=True, text=True, timeout=60)
    return subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)


@tool
@_remember
def run_shell(command: str) -> str:
    """Run a shell command in the workspace folder. Read-only commands (ls, cat, head, grep, find, wc, stat, file) on workspace files run immediately; anything else asks the user first.

    Args:
        command: The command line to run, e.g. "ls -la" or "grep -r error logs".
    """
    WORKSPACE.mkdir(exist_ok=True)
    argv = _read_only_argv(command)
    if argv:
        proc = lambda: _run_argv(argv)  # noqa: E731
    else:
        if not _approved(f"Run shell command in workspace/:\n  {command}"):
            return DECLINED
        proc = lambda: _run_shell_string(command)  # noqa: E731
    try:
        r = proc()
    except subprocess.TimeoutExpired:
        if not argv:
            ACTIONS.append(f"shell timed out, outcome unknown: {command}")
        return "ERROR: command timed out after 60s. If it changes anything, its outcome is unknown."
    except OSError as exc:
        # e.g. the command does not exist on this platform (#33): report cleanly, do not crash the tool call.
        if not argv:
            ACTIONS.append(f"shell could not run, outcome unknown: {command}")
        return f"ERROR: could not run that command ({exc}). It may not exist on this platform."
    if not argv:
        ACTIONS.append(f"shell exit {r.returncode}: {command}")
    out = f"exit code {r.returncode}\n{r.stdout}{('[stderr] ' + r.stderr) if r.stderr else ''}"
    _log("shell", command=command, read_only=bool(argv), exit=r.returncode, output=out[:LOG_OUT])
    result = _clip(_redact(out))
    _show(f"$ {command}", result)
    return result


# --- http -------------------------------------------------------------------------

def _auth_headers(url: str) -> dict[str, str]:
    u = urlparse(url)
    for svc in services().values():
        s = urlparse(svc["url"])
        if (u.scheme, u.netloc) == (s.scheme, s.netloc) and svc.get("key_env"):
            key = os.environ.get(svc["key_env"], "")
            if key:
                return {svc.get("header", "X-Api-Key"): key}
    return {}


def _looks_like_html(r: requests.Response) -> bool:
    head = r.text[:200].lstrip().lower()
    return "text/html" in r.headers.get("content-type", "") or head.startswith(("<!doctype html", "<html"))


def _is_service(url: str) -> bool:
    u = urlparse(url)
    return any((u.scheme, u.netloc) == urlparse(s["url"])[:2] for s in services().values())


class _TextExtractor(HTMLParser):
    """Collect a page's visible text, one line per block element, keeping <main> apart."""

    SKIP = {"script", "style", "noscript", "svg", "template", "head", "nav", "aside", "footer", "form"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "table", "ul", "ol", "pre", "blockquote", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_main = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP:
            self._skip += 1
        elif tag == "main":
            self._in_main += 1
        if tag in self.BLOCK:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "main" and self._in_main:
            self._in_main -= 1
        if tag in self.BLOCK:
            self._add("\n")

    def _add(self, text: str) -> None:
        self.parts.append(text)
        if self._in_main:
            self.main.append(text)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._add(re.sub(r"\s+", " ", data))  # line breaks come from block tags only


def html_to_text(html: str) -> str:
    """Reduce an HTML page to its title and visible text (only <main> when it has text)."""
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.main) if "".join(p.main).strip() else "".join(p.parts)
    lines = (" ".join(line.split()) for line in text.splitlines())
    body = "\n".join(line for line in lines if line)
    title = " ".join(p.title.split())
    return f"Title: {title}\n{body}" if title else body


def _diff_fields(sent: dict, got: dict) -> list[str]:
    """Fields present in both dicts whose values differ, as 'key: sent X, got Y' strings."""
    return [f"{k}: sent {v!r}, got {got[k]!r}" for k, v in sent.items() if k in got and got[k] != v]


def _verify_write(method: str, url: str, data, r: requests.Response) -> str:
    """Best-effort check of what a write actually did (#19), beyond the status code it returned.

    A follow-up GET only; never asks for approval (GET already runs freely) and never reaches the
    model, only the human-readable [Harness says] report, so it has no prompt cost. Best-effort:
    any failure here is reported, never raised, since the original write's own result still stands.
    """
    if r.status_code // 100 != 2:
        return ""
    headers = _auth_headers(url)
    try:
        if method == "DELETE":
            check = requests.get(url, headers=headers, timeout=10)
            if check.status_code == 404:
                return " (verified: now returns 404)"
            return f" (WARNING: a follow-up GET still returns HTTP {check.status_code} — may not actually be deleted)"

        if method == "POST":
            target = r.headers.get("Location")
            if not target:
                try:
                    body = r.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and "id" in body:
                    target = f"{url.rstrip('/')}/{body['id']}"
            if not target:
                return " (not verified: no Location header or id in the response)"
            check = requests.get(target, headers=headers, timeout=10)
            if check.status_code // 100 != 2:
                return f" (WARNING: created but a follow-up GET to {target} returned HTTP {check.status_code})"
            note = " (verified: now exists"
            if isinstance(data, dict):
                try:
                    got = check.json()
                except ValueError:
                    got = None
                if isinstance(got, dict):
                    diffs = _diff_fields(data, got)
                    note += f", but mismatched: {'; '.join(diffs)}" if diffs else ", fields match"
            return note + ")"

        if method in ("PUT", "PATCH"):
            check = requests.get(url, headers=headers, timeout=10)
            if check.status_code // 100 != 2:
                return f" (WARNING: a follow-up GET returned HTTP {check.status_code} — may not have taken effect)"
            if isinstance(data, dict):
                try:
                    got = check.json()
                except ValueError:
                    got = None
                if isinstance(got, dict):
                    diffs = _diff_fields(data, got)
                    return f" (mismatched: {'; '.join(diffs)})" if diffs else " (verified: fields match)"
            return " (verified: still exists)"
    except requests.RequestException as exc:
        return f" (could not verify: {type(exc).__name__})"
    return ""


_REQUIRED_QUERY_PARAMS = {"term", "query", "q"}

_ACTION_PATH_KEYWORDS = {
    "action", "actions",
    "cancel",
    "execute",
    "refresh",
    "reload",
    "rescan",
    "reset",
    "restart",
    "run",
    "scan",
    "start",
    "stop",
    "sync",
    "trigger", "triggers",
    "webhook", "webhooks",
}


def _is_action_endpoint(url: str) -> bool:
    """Return True if the URL path suggests an action/trigger endpoint that may take no body."""
    path = urlparse(url).path.lower()
    segments = [s for s in path.split("/") if s]
    return any(seg in _ACTION_PATH_KEYWORDS for seg in segments)


def _preflight_problem(method: str, url: str, body: str) -> str | None:
    """Return why a request is obviously wrong and not worth sending, or None."""
    for key, val in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if key.lower() in _REQUIRED_QUERY_PARAMS and not val.strip():
            return f"query parameter '{key}' is empty; please provide a value for '{key}'."
    if method in ("POST", "PUT", "PATCH") and not (body or "").strip() and (method != "POST" or not _is_action_endpoint(url)):
        return (
            f"{method} {url} requires a request body. "
            "Look up the endpoint's required body first (see the api-discovery skill and openapi_search)."
        )
    return None


@tool
@_remember
def http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request. GET runs immediately; any other method asks the user first. Web pages come back as plain text. API keys for services listed in the notes are added automatically.

    Args:
        method: HTTP method such as GET, POST, PUT or DELETE.
        url: Full URL including any query string.
        body: Optional JSON text to send as the request body.
    """
    method = method.upper()
    problem = _preflight_problem(method, url, body)
    if problem:
        _log("preflight", method=method, url=url, reason=problem)
        return _redact(f"ERROR: {problem}")
    try:
        data = json.loads(body) if body else None
    except ValueError:
        return "ERROR: body must be valid JSON text."
    if method != "GET":
        preview = f"\n  body: {body[:500]}" if body else ""
        if not _approved(f"{method} {url}{preview}"):
            return DECLINED
    try:
        headers = {"User-Agent": USER_AGENT, **_auth_headers(url)}  # some sites refuse requests without one
        r = requests.request(method, url, json=data, headers=headers, timeout=30)
    except requests.RequestException as exc:
        if method != "GET":
            ACTIONS.append(f"{method} {url} -> outcome unknown ({type(exc).__name__})")
        return _clip(_redact(f"ERROR: {exc}. For a write, the outcome is unknown, not failed."))
    if method != "GET":
        ACTIONS.append(_redact(f"{method} {url} -> HTTP {r.status_code}{_verify_write(method, url, data, r)}"))
    _log("http", method=method, url=url, status=r.status_code)
    if _looks_like_html(r) and not _is_service(url):
        # An ordinary web page: give the model its text, not the markup.
        return _clip(_redact(f"HTTP {r.status_code} (web page converted to text)\n{html_to_text(r.text)}"))
    if _looks_like_html(r):
        # A service from the notes answering with HTML means a wrong API path (its web UI).
        return (
            f"HTTP {r.status_code} but the body is an HTML web page, not API data. "
            "The path is probably wrong, so this is NOT an answer. Do not read anything into the page. "
            "Find the real endpoint (see the api-discovery skill)."
        )
    return _clip(_redact(f"HTTP {r.status_code}\n{r.text}"))


def _trim_to_query(text: str, query: str, max_chars: int = 2500) -> tuple[str, int]:
    """Trim page text to excerpts matching query, with surrounding line context. Returns (result_text, hit_count)."""
    query = query.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "(empty page)", 0
    title = lines[0] if lines[0].startswith("Title: ") else ""

    if not query:
        content = "\n".join(lines)
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n... [trimmed to {max_chars} chars]"
        return content, 0

    q_lower = query.lower()
    q_words = [w for w in re.findall(r"\w+", q_lower) if len(w) > 1]

    def line_matches(l: str) -> bool:
        low = l.lower()
        if q_lower in low:
            return True
        if len(q_words) > 1 and all(w in low for w in q_words):
            return True
        return False

    matching_indices = [i for i, line in enumerate(lines) if line_matches(line)]
    if not matching_indices and len(q_words) > 1:
        matching_indices = [i for i, line in enumerate(lines) if any(w in line.lower() for w in q_words)]

    if not matching_indices:
        snippet = "\n".join(lines[:6])
        msg = f"No content matching {query!r} found on page ({len(text)} chars)."
        if title:
            msg += f" {title}."
        msg += f"\nTop of page content:\n{snippet}"
        return msg, 0

    included_indices = set()
    for idx in matching_indices:
        for offset in range(-1, 2):
            target = idx + offset
            if 0 <= target < len(lines):
                included_indices.add(target)
    if title:
        included_indices.add(0)

    sorted_indices = sorted(included_indices)
    blocks = []
    current_block = [sorted_indices[0]]
    for idx in sorted_indices[1:]:
        if idx == current_block[-1] + 1:
            current_block.append(idx)
        else:
            blocks.append(current_block)
            current_block = [idx]
    blocks.append(current_block)

    formatted_blocks = ["\n".join(lines[i] for i in b) for b in blocks]
    result = "\n\n...\n\n".join(formatted_blocks)
    if len(result) > max_chars:
        result = result[:max_chars] + f"\n... [trimmed to {max_chars} chars]"
    return result, len(matching_indices)


@tool
@_remember
def fetch_page(url: str, query: str = "") -> str:
    """Fetch a web page and return the text matching a query, so large pages do not flood memory. Use this instead of reading an entire page when looking for specific information.

    Args:
        url: Web page URL (http:// or https://).
        query: Words or phrase to search for on the page. If omitted, returns the page title and top text.
    """
    if not url.startswith(("http://", "https://")):
        return "ERROR: URL must start with http:// or https://"
    try:
        headers = {"User-Agent": USER_AGENT, **_auth_headers(url)}
        r = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        _log("fetch_page", url=url, query=query, status="error", hits=0, result=f"error ({type(exc).__name__})")
        return _clip(_redact(f"ERROR: {exc}"))
    if not r.ok:
        _log("fetch_page", url=url, query=query, status=r.status_code, hits=0, result=f"HTTP {r.status_code}")
        return _clip(_redact(f"HTTP {r.status_code}\n{r.text[:500]}"))

    if _looks_like_html(r) and _is_service(url):
        # A service from the notes answering with HTML means a wrong API path (its web UI), same as http_request.
        _log("fetch_page", url=url, query=query, status=r.status_code, hits=0, result="wrong path (service HTML)")
        return (
            f"HTTP {r.status_code} but the body is an HTML web page, not API data. "
            "The path is probably wrong, so this is NOT an answer. Do not read anything into the page. "
            "Find the real endpoint (see the api-discovery skill)."
        )
    text = html_to_text(r.text) if _looks_like_html(r) else r.text
    result, hits = _trim_to_query(text, query)
    _log("fetch_page", url=url, query=query, status=r.status_code, hits=hits,
         result=f"{hits} hits" if query.strip() else f"{len(result)} chars")
    return _clip(_redact(result))


def _search_ddgs(query: str, limit: int) -> list[dict]:
    try:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
    except ImportError:
        raise RuntimeError("The 'ddgs' package is not installed. Re-run ./setup.sh to install it.")
    try:
        results = DDGS().text(query, max_results=limit)
    except RatelimitException as exc:
        raise RuntimeError(f"DuckDuckGo rate limit exceeded: {exc}. Do not retry the same query.")
    except TimeoutException as exc:
        raise RuntimeError(f"DuckDuckGo search timed out: {exc}. Do not retry the same query.")
    except DDGSException as exc:
        if "no results found" in str(exc).lower():
            return []
        raise RuntimeError(f"DuckDuckGo search error: {exc}. Do not retry the same query.")
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo search failed: {exc}. Do not retry the same query.")

    out = []
    for r in results or []:
        url = r.get("href") or r.get("url") or ""
        snippet = r.get("body") or r.get("snippet") or ""
        title = r.get("title") or ""
        out.append({"title": str(title), "url": str(url), "snippet": str(snippet)})
    return out


def _search_searxng(query: str, limit: int) -> list[dict]:
    url = os.environ.get("SMOLPAW_SEARCH_URL", "").strip()
    if not url:
        raise RuntimeError("SMOLPAW_SEARCH_URL is not set. Set it in .env to your SearXNG URL.")
    try:
        r = requests.get(
            f"{url.rstrip('/')}/search",
            params={"q": query, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"SearXNG connection error: {exc}. Do not retry the same query.")
    if r.status_code == 403:
        raise RuntimeError(
            "SearXNG returned 403 (JSON format not enabled). "
            "Add 'json' under 'search: formats:' in settings.yml."
        )
    if not r.ok:
        raise RuntimeError(f"SearXNG returned HTTP {r.status_code}. Do not retry the same query.")
    try:
        data = r.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"SearXNG returned malformed JSON: {exc}. Do not retry the same query.")
    if not isinstance(data, dict) or "results" not in data:
        raise RuntimeError("SearXNG response missing 'results' field. Do not retry the same query.")
    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        raise RuntimeError("SearXNG 'results' field is not a list. Do not retry the same query.")
    out = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        out.append({
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "snippet": str(item.get("content", "") or item.get("snippet", "")),
        })
    return out


SEARCH_PROVIDERS: dict[str, Callable[[str, int], list[dict]]] = {
    "ddgs": _search_ddgs,
    "searxng": _search_searxng,
}


@tool
@_remember
def web_search(query: str) -> str:
    """Search the web and return up to 5 results with title, URL and snippet. Use when you need current information or to find URLs to fetch.

    Args:
        query: Words or phrase to search the web for.
    """
    query = query.strip()
    if not query:
        return "ERROR: query cannot be empty."

    provider_name = os.environ.get("SMOLPAW_SEARCH_PROVIDER", "").strip().lower() or "ddgs"
    provider_fn = SEARCH_PROVIDERS.get(provider_name)
    if not provider_fn:
        return f"ERROR: unknown search provider '{provider_name}'. Valid choices: {', '.join(sorted(SEARCH_PROVIDERS.keys()))}."

    global _SEARCH_COUNT
    with _SEARCH_LOCK:
        allowed = _SEARCH_COUNT < MAX_SEARCHES
        if allowed:
            _SEARCH_COUNT += 1
    if not allowed:
        _log("web_search", provider=provider_name, query=query, status="limit", hits=0, result="limit reached")
        return "Search limit reached (maximum 3 searches per request). Please answer using the information you already have."

    try:
        raw_results = provider_fn(query, 5)
    except Exception as exc:
        _log("web_search", provider=provider_name, query=query, status="error", hits=0,
             result=f"error ({type(exc).__name__})")
        msg = str(exc)
        err = msg if msg.startswith("ERROR:") else f"ERROR: {msg}"
        return _clip(_redact(err))

    if not raw_results:
        _log("web_search", provider=provider_name, query=query, status="ok", hits=0, result="0 hits")
        return f"No results found for {query!r}. Try different search terms, but do not repeat the same query."

    results = raw_results[:5]
    formatted = []
    for i, item in enumerate(results, 1):
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = " ".join(str(item.get("snippet", "")).split())[:300]
        formatted.append(f"{i}. {title}\n   {url}\n   {snippet}")

    out = "\n\n".join(formatted)
    _log("web_search", provider=provider_name, query=query, status="ok", hits=len(results),
         result=f"{len(results)} hits")
    return _clip(_redact(out))


_SPECS: dict[str, dict] = {}


@tool
@_remember
def openapi_search(spec_url: str, keyword: str = "") -> str:
    """Search a service's OpenAPI spec (a JSON file listing every endpoint) and list matching endpoints. Use this to find the real endpoint names instead of guessing. With no keyword, lists the spec's tags.

    Args:
        spec_url: URL of the OpenAPI JSON file.
        keyword: Word to look for in endpoint paths, summaries and tags, e.g. "queue".
    """
    if spec_url not in _SPECS:
        try:
            r = requests.get(spec_url, timeout=30)
            _SPECS[spec_url] = r.json()
        except (requests.RequestException, ValueError) as exc:
            _log("openapi_search", spec_url=spec_url, keyword=keyword, result=f"error: not a spec ({type(exc).__name__})")
            return (
                f"ERROR: {spec_url} is not an OpenAPI spec ({type(exc).__name__}). "
                "Do not guess spec URLs. Call the API itself with http_request instead."
            )
    spec = _SPECS[spec_url]
    if not isinstance(spec, dict) or "paths" not in spec:
        _SPECS.pop(spec_url, None)
        _log("openapi_search", spec_url=spec_url, keyword=keyword, result="error: no 'paths' key")
        return (
            f"ERROR: {spec_url} returns JSON but it is not an OpenAPI spec (it has no 'paths'). "
            "That JSON is probably the API's own data or index: read it with http_request instead."
        )
    paths = spec["paths"]
    if not keyword:
        tags = sorted({t for ops in paths.values() for op in ops.values() if isinstance(op, dict) for t in op.get("tags", [])})
        _log("openapi_search", spec_url=spec_url, keyword=keyword, result=f"{len(paths)} endpoints, no keyword")
        return f"{len(paths)} endpoints. Tags: {', '.join(tags)}"
    kw = keyword.lower()
    hits = []
    for path, ops in paths.items():
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            text = " ".join([path, op.get("summary", ""), " ".join(op.get("tags", []))]).lower()
            if kw in text:
                hits.append(f"{method.upper()} {path}  {op.get('summary', '')}".rstrip())
    _log("openapi_search", spec_url=spec_url, keyword=keyword, result=f"{len(hits)} hits")
    return "\n".join(hits[:20]) + (f"\n... {len(hits) - 20} more" if len(hits) > 20 else "") or "No matching endpoints."


# --- files ------------------------------------------------------------------------

@tool
@_remember
def read_file(path: str, offset: int = 0) -> str:
    """Read a text file, up to 4000 characters at a time. Files in workspace/ and skills/ are read immediately; other paths ask the user first. Paths are relative to workspace/.

    Args:
        path: File path, e.g. "notes.txt" or "../skills/radarr.md".
        offset: Character to start from. A long file ends with a note giving the next offset.
    """
    p = _resolve(path)
    if _is_secret_file(p):
        _log("read_file", path=path, result="blocked (secrets file)")
        return "BLOCKED: this file holds secrets and cannot be read."
    if not _in_scope(path) and not _approved(f"Read file outside workspace/:\n  {p}"):
        _log("read_file", path=path, result="declined")
        return DECLINED
    try:
        content = p.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        _log("read_file", path=path, result=f"error ({type(exc).__name__})")
        return f"ERROR: {exc}"
    _log("read_file", path=path, result="ok")
    return _page(_redact(content), offset)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


LIST_DIR_MAX = 200


@tool
@_remember
def list_dir(path: str = ".") -> str:
    """List a folder: exact names, sizes and entry count. Folders in workspace/ and skills/ are listed immediately; other paths ask the user first. Paths are relative to workspace/.

    Args:
        path: Folder path, e.g. "." or "../skills".
    """
    p = _resolve(path)
    if ".ssh" in p.parts:
        _log("list_dir", path=path, result="blocked (secrets folder)")
        return "BLOCKED: this folder holds secrets and cannot be listed."
    if not _in_scope(path) and not _approved(f"List folder outside workspace/:\n  {p}"):
        _log("list_dir", path=path, result="declined")
        return DECLINED
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        lines = []
        for e in entries[:LIST_DIR_MAX]:
            if e.is_dir():
                lines.append(f"{e.name}/  folder, {sum(1 for _ in e.iterdir())} items")
            else:
                lines.append(f"{e.name}  {_size(e.stat().st_size)}")
    except OSError as exc:
        _log("list_dir", path=path, result=f"error ({type(exc).__name__})")
        return f"ERROR: {exc}"
    folders = sum(e.is_dir() for e in entries)
    head = f"{p}: {len(entries)} entries ({folders} folders, {len(entries) - folders} files)"
    if len(entries) > LIST_DIR_MAX:
        head += f"; showing the first {LIST_DIR_MAX}"
    _log("list_dir", path=path, entries=len(entries), result="ok")
    result = _clip(_redact("\n".join([head, *lines])))
    _show(f"list_dir {path}", result)
    return result


@tool
def write_file(path: str, text: str) -> str:
    """Write a text file, replacing any existing one. Always asks the user first. Paths are relative to workspace/.

    Args:
        path: File path, e.g. "summary.md".
        text: The full file contents.
    """
    p = _resolve(path)
    if _is_secret_file(p):
        _log("write_file", path=path, chars=len(text), result="blocked (secrets file)")
        return "BLOCKED: secrets files cannot be written."
    where = "" if _in_scope(path) else "  (OUTSIDE workspace/)"
    if not _approved(f"Write {len(text)} chars to {p}{where}:\n{text[:500]}"):
        _log("write_file", path=path, chars=len(text), result="declined")
        return DECLINED
    saved_undo, undo_reason = _save_undo(p)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    except OSError as exc:
        _log("write_file", path=path, chars=len(text), result=f"error ({type(exc).__name__})")
        ACTIONS.append(f"write failed: {p}")
        return f"ERROR: {exc}"
    undo_note = ""
    extra_log = {}
    if saved_undo:
        undo_note = f" (previous content saved at {saved_undo})"
        extra_log["undo"] = str(saved_undo)
    elif undo_reason:
        undo_note = f" ({undo_reason})"
        extra_log["undo"] = undo_reason
    ACTIONS.append(f"wrote {p} ({len(text)} chars){undo_note}")
    _log("write_file", path=path, chars=len(text), result="ok", **extra_log)
    return f"SUCCESS: wrote {len(text)} chars to {p}."


@tool
def edit_file(path: str, old: str, new: str) -> str:
    """Replace one passage in an existing text file and keep the rest as it is. Prefer this to write_file for a change to part of a file. Always asks the user first. Only files in workspace/ and skills/.

    Args:
        path: File path, e.g. "notes.txt".
        old: The exact text to replace, copied from the file. It must appear once; add surrounding words if it does not.
        new: The text to put in its place.
    """
    p = _resolve(path)
    if _is_secret_file(p):
        _log("edit_file", path=path, result="blocked (secrets file)")
        return "BLOCKED: secrets files cannot be written."
    if not _in_scope(path):
        _log("edit_file", path=path, result="refused (outside workspace/)")
        return "ERROR: edit_file only works on files in workspace/ and skills/. Use write_file for other paths."
    if not old:
        return "ERROR: old must be the exact text to replace."
    try:
        before = p.read_bytes().decode()
    except (OSError, UnicodeDecodeError) as exc:
        _log("edit_file", path=path, result=f"error ({type(exc).__name__})")
        return f"ERROR: {exc}"
    hits = before.count(old)
    if hits != 1:
        _log("edit_file", path=path, result=f"no unique match ({hits})")
        if hits == 0:
            return f"ERROR: old was not found in {path}; the file is unchanged. Use read_file and copy the passage exactly."
        return f"ERROR: old appears {hits} times in {path}; the file is unchanged. Include more surrounding text so it matches once."
    after = before.replace(old, new)
    if not _approved(f"Edit {p}: replace {len(old)} chars with {len(new)}\n- {old[:300]}\n+ {new[:300]}"):
        _log("edit_file", path=path, result="declined")
        return DECLINED
    saved_undo, undo_reason = _save_undo(p)
    try:
        p.write_bytes(after.encode())
    except OSError as exc:
        _log("edit_file", path=path, result=f"error ({type(exc).__name__})")
        ACTIONS.append(f"edit failed: {p}")
        return f"ERROR: {exc}"
    undo_note = f" (previous content saved at {saved_undo})" if saved_undo else f" ({undo_reason})" if undo_reason else ""
    ACTIONS.append(f"edited {p} ({len(before)} -> {len(after)} chars){undo_note}")
    _log("edit_file", path=path, chars=len(after), result="ok", **({"undo": str(saved_undo or undo_reason)} if saved_undo or undo_reason else {}))
    return f"SUCCESS: replaced 1 passage in {p} ({len(before)} -> {len(after)} chars)."


@tool
def ask_user(question: str) -> str:
    """Ask the user a question and wait for the answer. Use this when you are unsure instead of guessing.

    Args:
        question: The question to show the user.
    """
    answer = redact_pasted_secrets(ASK(question))
    _log("ask", question=question, answer=answer)
    return answer


# --- skills -----------------------------------------------------------------------

def _skill_path(name: str) -> Path | None:
    clean = re.sub(r"[^a-z0-9_-]", "", name.lower().removesuffix(".md"))
    return SKILLS / f"{clean}.md" if clean else None


@tool
def list_skills() -> str:
    """List saved skills (short how-to notes written from earlier tasks). Check these before starting a task."""
    files = sorted(SKILLS.glob("*.md")) if SKILLS.exists() else []
    _log("list_skills", result=f"{len(files)} skills")
    if not files:
        return "No skills saved yet."
    return "\n".join(f"{f.stem}: {(f.read_text().splitlines() or [''])[0].lstrip('# ')}" for f in files)


@tool
def read_skill(name: str) -> str:
    """Read a saved skill.

    Args:
        name: Skill name as shown by list_skills.
    """
    p = _skill_path(name)
    if not p or not p.exists():
        _log("read_skill", name=name, result="not found")
        return "No such skill. Call list_skills."
    try:
        content = p.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        _log("read_skill", name=name, result=f"error ({type(exc).__name__})")
        raise
    _log("read_skill", name=name, result="ok")
    return _clip(_redact(content))


@tool
def write_skill(name: str, text: str) -> str:
    """Save or update a skill: a short how-to note for future tasks (what worked, what failed, exact values). The first line should be a one-line summary. Asks the user first. Never put secrets in a skill.

    Args:
        name: Short lowercase name using letters, digits, - or _.
        text: The skill contents in markdown.
    """
    p = _skill_path(name)
    if not p:
        _log("write_skill", name=name, chars=len(text), result="error (invalid skill name)")
        return "ERROR: invalid skill name."
    verb = "Update" if p.exists() else "Create"
    if not _approved(f"{verb} skill '{p.stem}':\n{text[:1500]}"):
        _log("write_skill", name=name, chars=len(text), result="declined")
        return DECLINED
    saved_undo, undo_reason = _save_undo(p)
    try:
        SKILLS.mkdir(exist_ok=True)
        p.write_text(_redact(text))
    except OSError as exc:
        _log("write_skill", name=name, chars=len(text), result=f"error ({type(exc).__name__})")
        raise
    undo_note = ""
    extra_log = {}
    if saved_undo:
        undo_note = f" (previous content saved at {saved_undo})"
        extra_log["undo"] = str(saved_undo)
    elif undo_reason:
        undo_note = f" ({undo_reason})"
        extra_log["undo"] = undo_reason
    ACTIONS.append(f"saved skill {p.stem}{undo_note}")
    _log("write_skill", name=name, chars=len(text), result="ok", **extra_log)
    return f"SUCCESS: saved skill '{p.stem}'."


# --- memory -----------------------------------------------------------------------

@tool
def remember(fact: str) -> str:
    """Save a fact or user preference to long-term memory. Asks the user first. Never save secrets.

    Args:
        fact: Fact to remember, e.g. "User prefers dark mode" or "Movie files go to /Volumes/Media".
    """
    fact = fact.strip()
    if not fact:
        return "ERROR: fact cannot be empty."
    clean_fact = redact_pasted_secrets(_redact(fact))
    if not _approved(f"Remember fact in memory:\n  {clean_fact}"):
        return DECLINED
    entry = clean_fact if clean_fact.startswith("- ") else f"- {clean_fact}"
    try:
        if MEMORY.exists():
            text = MEMORY.read_text()
            if text and not text.endswith("\n"):
                text += "\n"
            text += entry + "\n"
        else:
            text = f"# Memory\n\n{entry}\n"
        MEMORY.parent.mkdir(parents=True, exist_ok=True)
        MEMORY.write_text(text)
    except OSError as exc:
        ACTIONS.append(f"remember failed: {clean_fact}")
        return f"ERROR: could not save memory ({exc})"
    ACTIONS.append(f"remembered: {clean_fact}")
    _log("remember", fact=clean_fact)
    return f"SUCCESS: remembered: {clean_fact}"


@tool
@_remember
def recall(query: str = "") -> str:
    """Search long-term memory for previously remembered facts or preferences.

    Args:
        query: Word or phrase to search for. If empty, lists all remembered facts.
    """
    if not MEMORY.exists():
        _log("recall", query=query, hits=0, result="no memory file")
        return "No memories saved yet."
    try:
        raw = MEMORY.read_text().strip()
    except OSError as exc:
        _log("recall", query=query, hits=0, result=f"error ({type(exc).__name__})")
        return f"ERROR: {exc}"
    if not raw:
        _log("recall", query=query, hits=0, result="empty memory file")
        return "No memories saved yet."

    lines = [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        _log("recall", query=query, hits=0, result="no facts")
        return "No memories saved yet."

    query = query.strip()
    if not query:
        _log("recall", query="", hits=len(lines), result=f"{len(lines)} facts")
        return _clip(_redact("\n".join(lines)))

    q_lower = query.lower()
    q_words = [w for w in re.findall(r"\w+", q_lower) if len(w) > 1]

    def line_matches(l: str) -> bool:
        low = l.lower()
        if q_lower in low:
            return True
        if len(q_words) > 1 and all(w in low for w in q_words):
            return True
        return False

    hits = [line for line in lines if line_matches(line)]
    if not hits and len(q_words) > 1:
        hits = [line for line in lines if any(w in line.lower() for w in q_words)]

    if not hits:
        _log("recall", query=query, hits=0, result="no match")
        return f"No memories matching {query!r}."

    _log("recall", query=query, hits=len(hits), result=f"{len(hits)} hits")
    return _clip(_redact("\n".join(hits)))


def _configure_search_provider(provider: str | None = None) -> str:
    """Validate and configure search provider selection, updating GENERIC_TOOLS."""
    if provider is None:
        provider = os.environ.get("SMOLPAW_SEARCH_PROVIDER", "").strip().lower() or "ddgs"
    else:
        provider = provider.strip().lower()
    valid = list(SEARCH_PROVIDERS.keys()) + ["none"]
    if provider not in valid:
        raise ValueError(
            f"Invalid SMOLPAW_SEARCH_PROVIDER '{provider}'. Valid choices: {', '.join(sorted(SEARCH_PROVIDERS.keys()))}, none."
        )
    if provider == "none":
        if web_search in GENERIC_TOOLS:
            GENERIC_TOOLS.remove(web_search)
    else:
        if web_search not in GENERIC_TOOLS:
            GENERIC_TOOLS.append(web_search)
    return provider


GENERIC_TOOLS = [
    run_shell, http_request, fetch_page, openapi_search, read_file, list_dir, write_file, edit_file, ask_user,
    list_skills, read_skill, write_skill, remember, recall,
]
def apply_search_provider() -> str:
    """Apply SMOLPAW_SEARCH_PROVIDER to GENERIC_TOOLS; a bad value warns and falls back to ddgs."""
    try:
        return _configure_search_provider()
    except ValueError as exc:
        print(f"WARNING: {exc} Falling back to ddgs.", file=sys.stderr)
        return _configure_search_provider("ddgs")


apply_search_provider()  # build_agent() applies it again once .env is loaded

GUIDANCE = """\
You are SmolPaw, an agent on the user's Mac. Work out how to meet the user's goal with your tools.
- Skills below are already loaded. Follow the relevant one before acting.
- The contents of notes.md are included below (services, key user preferences). Do not look for it as a file.
- The services below are reachable with http_request. API keys are added automatically; never ask for them.
- Never ask the user to type a password, token or API key into chat, even if they offer. Tell them to add it to notes.md/.env instead.
- Before changing anything, use read-only calls (GET, ls, cat) to learn how the service works.
- Changes ask the user to confirm. If declined, do not repeat it: try another way or call ask_user.
- Report exactly what the tools returned. Never claim success unless a tool result says SUCCESS or shows it.
- When a task teaches you something reusable, save a short skill with write_skill. No secrets in skills.
- Call final_answer when done."""


INLINE_SKILL_MAX = 1500  # chars; longer skills are listed by name and read on demand


def build_instructions() -> str:
    notes = NOTES.read_text() if NOTES.exists() else "(no notes.md found)"
    inline, listed = [], []
    for f in sorted(SKILLS.glob("*.md")) if SKILLS.exists() else []:
        text = f.read_text()
        (inline if len(text) <= INLINE_SKILL_MAX else listed).append((f.stem, text))
    parts = [GUIDANCE, f"Home folder: {Path.home()}. Shell commands start in workspace/.", f"--- notes.md ---\n{notes}"]
    parts += [f"--- skill: {name} ---\n{text}" for name, text in inline]
    if listed:
        parts.append("Longer skills (read with read_skill): " + ", ".join(name for name, _ in listed))
    return "\n\n".join(parts)
