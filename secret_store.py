"""
Secrets entered on the web page (Settings > Secrets).

Each secret is a NAME=value line in a marked block of .env, so it survives restarts and loads like any other
key there (agent.load_env). The value is also put in os.environ, so http services (notes.md key_env=) and
shell commands ($NAME) can use it by name while the model only ever sees the name. generic_tools masks the
values in all tool output and run logs. Nothing here returns a value to the page: it lists names only.
Pure Python, no network or model access.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import threading

PATH: Path = Path(__file__).resolve().parent / ".env"
BEGIN = "# --- secrets entered on the web page (SmolPaw edits this block) ---"
END = "# --- end of web page secrets ---"
NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
MAX_VALUE = 4_096
MAX_SECRETS = 50
MIN_MASK = 4  # shorter values are not masked in output: they would mangle ordinary text
# Names that change how a program starts, so a secret must never be saved under them even if unset.
RESERVED_PREFIXES = ("DYLD_", "LD_", "PYTHON", "SMOLPAW_", "BASH", "SHELL", "PATH", "HOME", "IFS")
_LOCK = threading.RLock()


def _split(text: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Return the lines before the block, the block's NAME=value pairs, and the lines after it."""
    lines = text.splitlines()
    if BEGIN not in lines:
        return lines, {}, []
    start = lines.index(BEGIN)
    end = lines.index(END, start) if END in lines[start:] else len(lines)
    pairs = {}
    for line in lines[start + 1:end]:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            pairs[k.strip()] = v
    return lines[:start], pairs, lines[end + 1:]


def _read() -> tuple[list[str], dict[str, str], list[str]]:
    try:
        return _split(PATH.read_text())
    except FileNotFoundError:
        return [], {}, []


def _write(before: list[str], pairs: dict[str, str], after: list[str]) -> None:
    """Rewrite .env atomically, readable by the owner only."""
    block = [BEGIN, *(f"{k}={v}" for k, v in sorted(pairs.items())), END] if pairs else []
    while before and not before[-1].strip():
        before = before[:-1]
    parts = (before + [""] if before and block else before) + block + (([""] if block and after else []) + after)
    fd, tmp = tempfile.mkstemp(dir=PATH.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(parts) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def names() -> list[str]:
    """The names saved from the web page, sorted. Never values."""
    with _LOCK:
        return sorted(_read()[1])


def values() -> list[str]:
    """Saved values long enough to mask in output, longest first so one never hides inside another."""
    with _LOCK:
        pairs = _read()[1]
    found = {os.environ.get(k) or v for k, v in pairs.items()}
    return sorted((v for v in found if len(v) >= MIN_MASK), key=len, reverse=True)


def set_secret(name: object, value: object) -> str | None:
    """Save a secret; return None on success or a short reason it was refused (never containing the value)."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return "name must be 2 to 64 characters: capital letters, digits and underscores, starting with a letter"
    if name.startswith(RESERVED_PREFIXES):
        return "that name is reserved"
    if not isinstance(value, str) or not value:
        return "value is empty"
    if len(value) > MAX_VALUE:
        return "value is too long"
    if value != value.strip() or any(c in value for c in "\r\n\0"):
        return "value must be one line with no spaces at either end"
    with _LOCK:
        before, pairs, after = _read()
        if name not in pairs and name in os.environ:
            return "that name is already set outside this page"
        if name not in pairs and len(pairs) >= MAX_SECRETS:
            return "too many secrets"
        pairs[name] = value
        _write(before, pairs, after)
        os.environ[name] = value
    return None


def delete_secret(name: object) -> bool:
    """Remove a saved secret; False if there was none by that name."""
    with _LOCK:
        before, pairs, after = _read()
        if not isinstance(name, str) or name not in pairs:
            return False
        del pairs[name]
        _write(before, pairs, after)
        os.environ.pop(name, None)
    return True
