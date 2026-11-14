"""
Edit skills and memory.md from the web page (#97). notes.md is not editable here (#98).

Every change copies the old file to .undo/ first (the same net write_file uses), is written atomically so a run
never reads half a file, and goes through the same masking as the agent's own writes. The view of a file shows
secret-redacted text, so text carrying the redaction marker is refused: saving it back would overwrite a real value.
Each function returns an error message (never the text) or None. No network or model access.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile
import threading

import generic_tools as g

MAX_TEXT = 20_000
SKILL_NAME = re.compile(r"[a-z0-9_-]{1,64}")
MARK = "[REDACTED"
_LOCK = threading.RLock()


def _path(kind: object, name: object) -> Path | None:
    """The file a (kind, name) pair means: memory.md, or a skill whose name is already clean."""
    if kind == "memory":
        return g.MEMORY
    if kind == "skill" and isinstance(name, str) and SKILL_NAME.fullmatch(name):
        return g.SKILLS / f"{name}.md"
    return None


def _write(p: Path, text: str) -> None:
    """Replace p atomically, keeping its permissions (0644 for a new file)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _snapshot(p: Path) -> str | None:
    """Copy p to .undo/ if it exists; a reason if the copy could not be made (the edit is then refused)."""
    _, why = g._save_undo(p)
    return None if why is None else f"could not make a safety copy first ({why})"


def latest_undo(p: Path) -> Path | None:
    """The newest copy of p in .undo/, if there is one."""
    suffix = f"__{g._undo_tag(p)}"
    copies = sorted(f for f in g.UNDO_DIR.glob("*") if f.is_file() and f.name.endswith(suffix)) if g.UNDO_DIR.exists() else []
    return copies[-1] if copies else None


def can_restore(kind: object, name: object = None) -> bool:
    p = _path(kind, name)
    return p is not None and latest_undo(p) is not None


def read(kind: object, name: object = None) -> tuple[str | None, str | None]:
    """The full text to edit, secret-redacted, as (text, error). Not clipped: editing a clipped copy would cut the file."""
    p = _path(kind, name)
    if p is None:
        return None, "unknown file"
    try:
        if not p.exists():
            return ("", None) if kind == "memory" else (None, "no such skill")
        if p.stat().st_size > MAX_TEXT * 4:
            return None, "too large to edit here"
        text = p.read_text()
    except OSError:
        return None, "could not read it"
    if len(text) > MAX_TEXT + 1:  # +1: a saved text at the limit gains a final newline
        return None, "too large to edit here"
    return g._redact(text), None


def save(kind: object, name: object, text: object) -> tuple[str | None, bool]:
    """Save text as the file's new content: (error or None, whether masking changed the text)."""
    p = _path(kind, name)
    if p is None:
        return "unknown file", False
    if not isinstance(text, str):
        return "text must be a string", False
    if len(text) > MAX_TEXT:
        return f"too long (over {MAX_TEXT:,} characters)", False
    if MARK in text:
        return "the text contains [REDACTED: that marks a hidden secret, and saving it would overwrite the real value. Remove it first", False
    if kind == "skill" and not text.strip():
        return "a skill cannot be empty (delete it instead)", False
    tidy = (lambda t: t.rstrip("\n") + "\n" if t.strip() else "")
    clean = g._redact(text)
    if kind == "memory":
        clean = g.redact_pasted_secrets(clean)
    clean, wanted = tidy(clean), tidy(text)
    with _LOCK:
        err = _snapshot(p)
        if err:
            return err, False
        try:
            _write(p, clean)
        except OSError:
            return "could not write it", False
    return None, clean != wanted


def delete_skill(name: object) -> str | None:
    """Remove a skill, keeping a copy in .undo/ so it can be restored."""
    p = _path("skill", name)
    if p is None:
        return "unknown skill"
    with _LOCK:
        if not p.exists():
            return "no such skill"
        err = _snapshot(p)
        if err:
            return err
        try:
            p.unlink()
        except OSError:
            return "could not delete it"
    return None


def restore(kind: object, name: object = None) -> str | None:
    """Put back the newest copy from .undo/. The file it replaces is copied first, so a restore can itself be undone."""
    p = _path(kind, name)
    if p is None:
        return "unknown file"
    with _LOCK:
        copy = latest_undo(p)
        if copy is None:
            return "nothing to restore"
        try:
            text = copy.read_text()
        except OSError:
            return "could not read the saved copy"
        err = _snapshot(p)
        if err:
            return err
        try:
            _write(p, text)
        except OSError:
            return "could not write it"
    return None
