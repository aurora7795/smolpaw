"""
Generic tools for the Smolpaw agent, with a Python-side confirmation layer.

The model gets a shell, HTTP, files, skills and a way to ask the user. Every
safety rule lives here, not in the prompt, so the model cannot talk its way past it:

  - read-only commands inside workspace/ and skills/ run freely; HTTP GET runs freely
  - anything else asks the user [y/N] first (writes, other HTTP methods, other commands)
  - API keys are added by the harness for hosts listed in notes.md; the model never sees them
  - .env files can never be read or written
"""

import json
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from smolagents import tool

ROOT = Path(__file__).parent
WORKSPACE = ROOT / "workspace"
SKILLS = ROOT / "skills"
NOTES = ROOT / "notes.md"
LOG_DIR = ROOT / "logs"

READ_ONLY_CMDS = {"ls", "cat", "head", "grep", "find", "wc", "stat", "file"}
FIND_UNSAFE = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf"}
SHELL_META = re.compile(r"[;&|<>`$()\\\n]")
MAX_OUT = 4000
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
        m = re.match(r"^- (\w+): (\S+)((?: \| \w+=\S+)*)\s*$", line)
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
    _log_file = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{model}.jsonl"
    _log("start", model=model, prompt=prompt)
    return _log_file


def log_final(answer: object) -> None:
    _log("final", answer=str(answer), actions=list(ACTIONS))


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


@tool
def run_shell(command: str) -> str:
    """Run a shell command in the workspace folder. Read-only commands (ls, cat, head, grep, find, wc, stat, file) on workspace files run immediately; anything else asks the user first.

    Args:
        command: The command line to run, e.g. "ls -la" or "grep -r error logs".
    """
    WORKSPACE.mkdir(exist_ok=True)
    argv = _read_only_argv(command)
    if argv:
        proc = lambda: subprocess.run(argv, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)  # noqa: E731
    else:
        if not _approved(f"Run shell command in workspace/:\n  {command}"):
            return DECLINED
        proc = lambda: subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=60)  # noqa: E731
    try:
        r = proc()
    except subprocess.TimeoutExpired:
        if not argv:
            ACTIONS.append(f"shell timed out, outcome unknown: {command}")
        return "ERROR: command timed out after 60s. If it changes anything, its outcome is unknown."
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


@tool
def http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request. GET runs immediately; any other method asks the user first. API keys for services listed in the notes are added automatically.

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
        r = requests.request(method, url, json=data, headers=_auth_headers(url), timeout=30)
    except requests.RequestException as exc:
        if method != "GET":
            ACTIONS.append(f"{method} {url} -> outcome unknown ({type(exc).__name__})")
        return _clip(_redact(f"ERROR: {exc}. For a write, the outcome is unknown, not failed."))
    if method != "GET":
        ACTIONS.append(f"{method} {url} -> HTTP {r.status_code}")
    _log("http", method=method, url=url, status=r.status_code)
    return _clip(_redact(f"HTTP {r.status_code}\n{r.text}"))


# --- files ------------------------------------------------------------------------

@tool
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
    answer = ASK(question)
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
    run_shell, http_request, read_file, write_file, ask_user,
    list_skills, read_skill, write_skill,
]

GUIDANCE = """\
You are Smolpaw, an agent on the user's Mac. Work out how to meet the user's goal with your tools.
- Call list_skills first and read any relevant skill.
- The services below are reachable with http_request. API keys are added automatically; never ask for them.
- Before changing anything, use read-only calls (GET, ls, cat) to learn how the service works.
- Changes ask the user to confirm. If declined, do not repeat it: try another way or call ask_user.
- Report exactly what the tools returned. Never claim success unless a tool result says SUCCESS or shows it.
- When a task teaches you something reusable, save a short skill with write_skill. No secrets in skills.
- Call final_answer when done."""


def build_instructions() -> str:
    notes = NOTES.read_text() if NOTES.exists() else "(no notes.md found)"
    return f"{GUIDANCE}\n\n--- notes.md ---\n{notes}"
