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
import json
import os
import platform
import re
import shlex
import subprocess
import warnings
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from smolagents import tool

# _remember wraps tools; smolagents only warns about this for its remote executor, which we do not use.
warnings.filterwarnings("ignore", message=".*has decorators other than @tool.*")

ROOT = Path(__file__).parent
WORKSPACE = ROOT / "workspace"
SKILLS = ROOT / "skills"
NOTES = ROOT / "notes.md"
LOG_DIR = ROOT / "logs"

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


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUT else text[:MAX_OUT] + f"\n... [truncated, {len(text)} chars total]"


def _log(kind: str, **fields) -> None:
    if _log_file:
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "kind": kind, **fields}
        with _log_file.open("a") as f:
            f.write(_redact(json.dumps(entry, default=str)) + "\n")


def start_log(model: str, prompt: str) -> Path:
    global _log_file
    LOG_DIR.mkdir(exist_ok=True)
    _log_file = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{model.replace('/', '_')}.jsonl"
    _log("start", model=model, prompt=prompt)
    return _log_file


def log_final(answer: object) -> None:
    _log("final", answer=str(answer), actions=list(ACTIONS))


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
    return (WORKSPACE / path).resolve()


def _in_scope(path: str) -> bool:
    p = _resolve(path)
    return any(p.is_relative_to(base.resolve()) for base in (WORKSPACE, SKILLS))


def _is_secret_file(path: Path) -> bool:
    return path.name.startswith(".env") or ".ssh" in path.parts


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
    return argv


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
    _log("shell", command=command, read_only=bool(argv), exit=r.returncode)
    return _clip(_redact(out))


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
def read_file(path: str) -> str:
    """Read a text file. Files in workspace/ and skills/ are read immediately; other paths ask the user first. Paths are relative to workspace/.

    Args:
        path: File path, e.g. "notes.txt" or "../skills/radarr.md".
    """
    p = _resolve(path)
    if _is_secret_file(p):
        return "BLOCKED: this file holds secrets and cannot be read."
    if not _in_scope(path) and not _approved(f"Read file outside workspace/:\n  {p}"):
        return DECLINED
    try:
        return _clip(_redact(p.read_text()))
    except (OSError, UnicodeDecodeError) as exc:
        return f"ERROR: {exc}"


@tool
def write_file(path: str, text: str) -> str:
    """Write a text file, replacing any existing one. Always asks the user first. Paths are relative to workspace/.

    Args:
        path: File path, e.g. "summary.md".
        text: The full file contents.
    """
    p = _resolve(path)
    if _is_secret_file(p):
        return "BLOCKED: secrets files cannot be written."
    where = "" if _in_scope(path) else "  (OUTSIDE workspace/)"
    if not _approved(f"Write {len(text)} chars to {p}{where}:\n{text[:500]}"):
        return DECLINED
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    except OSError as exc:
        ACTIONS.append(f"write failed: {p}")
        return f"ERROR: {exc}"
    ACTIONS.append(f"wrote {p} ({len(text)} chars)")
    return f"SUCCESS: wrote {len(text)} chars to {p}."


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
        return "No such skill. Call list_skills."
    return _clip(_redact(p.read_text()))


@tool
def write_skill(name: str, text: str) -> str:
    """Save or update a skill: a short how-to note for future tasks (what worked, what failed, exact values). The first line should be a one-line summary. Asks the user first. Never put secrets in a skill.

    Args:
        name: Short lowercase name using letters, digits, - or _.
        text: The skill contents in markdown.
    """
    p = _skill_path(name)
    if not p:
        return "ERROR: invalid skill name."
    verb = "Update" if p.exists() else "Create"
    if not _approved(f"{verb} skill '{p.stem}':\n{text[:1500]}"):
        return DECLINED
    SKILLS.mkdir(exist_ok=True)
    p.write_text(_redact(text))
    ACTIONS.append(f"saved skill {p.stem}")
    return f"SUCCESS: saved skill '{p.stem}'."


GENERIC_TOOLS = [
    run_shell, http_request, fetch_page, openapi_search, read_file, write_file, ask_user,
    list_skills, read_skill, write_skill,
]

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
    parts = [GUIDANCE, f"--- notes.md ---\n{notes}"]
    parts += [f"--- skill: {name} ---\n{text}" for name, text in inline]
    if listed:
        parts.append("Longer skills (read with read_skill): " + ", ".join(name for name, _ in listed))
    return "\n\n".join(parts)
