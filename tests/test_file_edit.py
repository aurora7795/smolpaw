"""
Tests for editing skills and memory.md from the web page (file_edit.py and the /api/file_* routes, #97).
Run with: .venv/bin/python tests/test_file_edit.py

Uses a temporary skills folder, memory file, .undo folder, notes, workspace and logs; never touches the real ones.
"""

import json
import os
import socket
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import file_edit  # noqa: E402
import generic_tools as g  # noqa: E402
import secret_store  # noqa: E402
import web  # noqa: E402

tmp = Path(tempfile.mkdtemp())
g.SKILLS = tmp / "skills"
g.MEMORY = tmp / "memory.md"
g.NOTES = tmp / "notes.md"
g.UNDO_DIR = tmp / ".undo"
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.WORKSPACE.mkdir()
secret_store.PATH = tmp / ".env"
for var in ("EDIT_TEST_KEY",):
    os.environ.pop(var, None)


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0

skill = g.SKILLS / "movies.md"
undo = lambda: sorted(g.UNDO_DIR.glob("*")) if g.UNDO_DIR.exists() else []  # noqa: E731

# --- reading ---------------------------------------------------------------------------

check("a missing memory.md reads as empty", file_edit.read("memory") == ("", None))
check("a missing skill is an error", file_edit.read("skill", "movies")[1] == "no such skill")
for kind, name, why in [("notes", "", "notes.md is not editable"), ("skill", "../x", "a path"), ("skill", "a/b", "a slash"),
                        ("skill", "A", "uppercase"), ("skill", "x.md", "an extension"), ("skill", "", "empty"),
                        ("skill", "x" * 65, "too long"), ("skill", None, "none"), ("skill", 7, "not a string"),
                        ("secrets", "x", "unknown kind")]:
    check(f"refused everywhere: {why}",
          file_edit.read(kind, name)[1] and file_edit.save(kind, name, "x")[0] and file_edit.restore(kind, name)
          and (kind != "skill" or file_edit.delete_skill(name)))
check("nothing was created by the refused names", not g.SKILLS.exists() and not g.MEMORY.exists() and not undo())

# --- saving, the undo copy and restore -----------------------------------------------------

check("a new skill is saved", file_edit.save("skill", "movies", "Movies go in /Volumes/Media") == (None, False))
check("it ends with one newline and is world-readable like a normal file",
      skill.read_text() == "Movies go in /Volumes/Media\n" and stat.S_IMODE(skill.stat().st_mode) == 0o644)
check("a new file has no earlier copy to keep", not undo() and not file_edit.can_restore("skill", "movies"))
check("a second save keeps the old text in .undo first",
      file_edit.save("skill", "movies", "Movies go in /Volumes/Films") == (None, False)
      and len(undo()) == 1 and undo()[0].read_text() == "Movies go in /Volumes/Media\n")
check(".undo is private, as write_file makes it",
      stat.S_IMODE(g.UNDO_DIR.stat().st_mode) == 0o700 and stat.S_IMODE(undo()[0].stat().st_mode) == 0o600)
check("restore puts the old text back", file_edit.can_restore("skill", "movies") and file_edit.restore("skill", "movies") is None
      and skill.read_text() == "Movies go in /Volumes/Media\n")
check("a restore can itself be undone", file_edit.restore("skill", "movies") is None
      and skill.read_text() == "Movies go in /Volumes/Films\n")
check("no temp files are left in the skills folder", [f.name for f in g.SKILLS.iterdir()] == ["movies.md"])
check("restoring with no copy says so", file_edit.restore("skill", "other") == "nothing to restore")

check("memory is saved and can be emptied", file_edit.save("memory", "", "- likes tea") == (None, False)
      and g.MEMORY.read_text() == "- likes tea\n" and file_edit.save("memory", "", "") == (None, False) and g.MEMORY.read_text() == ""
      and file_edit.can_restore("memory"))

# --- deleting -------------------------------------------------------------------------------

check("deleting a skill removes it but keeps a copy", file_edit.delete_skill("movies") is None and not skill.exists()
      and file_edit.can_restore("skill", "movies"))
check("a deleted skill can be restored", file_edit.restore("skill", "movies") is None and skill.exists())
check("deleting one that is not there is an error", file_edit.delete_skill("nope") == "no such skill")

# --- refusals leave the file alone ------------------------------------------------------------

before = skill.read_text()
n = len(undo())
for text, why in [("see [REDACTED] here", "the redaction marker"), ("x" * (file_edit.MAX_TEXT + 1), "too long"),
                  ("   \n", "an empty skill"), (None, "not a string"), (12, "a number")]:
    err, _ = file_edit.save("skill", "movies", text)
    check(f"save refused: {why}", bool(err) and skill.read_text() == before and len(undo()) == n)
check("the marker error never echoes the text", "hunter-token" not in (file_edit.save("skill", "movies", "hunter-token [REDACTED")[0] or ""))
check("text exactly at the limit is accepted and can be opened again",
      file_edit.save("skill", "movies", "y" * file_edit.MAX_TEXT)[0] is None and file_edit.read("skill", "movies")[1] is None)
skill.write_text("z" * (file_edit.MAX_TEXT + 5))
check("a file the agent made too long is refused for editing, not cut", file_edit.read("skill", "movies") == (None, "too large to edit here"))
skill.write_text("short\n")

# --- masking and the full text -------------------------------------------------------------------

g.NOTES.write_text("- svc: http://h:1 | key_env=EDIT_TEST_KEY\n")
os.environ["EDIT_TEST_KEY"] = "key-abcdef-123456"
check("a known secret in a skill is masked on save and the page is told",
      file_edit.save("skill", "movies", "use key-abcdef-123456 here") == (None, True)
      and "key-abcdef" not in skill.read_text() and "[REDACTED]" in skill.read_text())
check("a pasted credential in memory is masked too",
      file_edit.save("memory", "", "token ghp_" + "a1" * 15) == (None, True) and "ghp_" not in g.MEMORY.read_text())
skill.write_text("api key-abcdef-123456\n")
check("the text shown for editing is redacted", file_edit.read("skill", "movies")[0] == "api [REDACTED]\n")
long_text = "line\n" * 3000
skill.write_text(long_text)
check("the whole text is returned for editing, not the clipped view", file_edit.read("skill", "movies") == (long_text, None))
check("while the page's own view is clipped, which is why the editor must not use it", len(g._clip(long_text)) < len(long_text))

# --- the routes --------------------------------------------------------------------------------------

state = SimpleNamespace(status="idle")
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
token = "edit-test-token"
srv = web.serve("127.0.0.1", port, token, web.Approvals(), state, {})


def call(path: str, body: dict | None = None, tok: str | None = token) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Token": tok or "", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


skill.write_text("one\n")
code, data = call("/api/file_text?kind=skill&name=movies")
check("GET /api/file_text returns the full text and whether a copy exists",
      code == 200 and data == {"text": "one\n", "restorable": file_edit.can_restore("skill", "movies")})
check("GET /api/file_text for a bad name is a 404", call("/api/file_text?kind=skill&name=..%2Fx")[0] == 404
      and call("/api/file_text?kind=notes")[0] == 404)
code, data = call("/api/file_save", {"kind": "skill", "name": "movies", "text": "two"})
check("POST /api/file_save saves", code == 200 and data == {"ok": True, "masked": False} and skill.read_text() == "two\n")
check("a refused save is a 400 with a reason", call("/api/file_save", {"kind": "skill", "name": "movies", "text": "[REDACTED]"})[0] == 400
      and skill.read_text() == "two\n")
check("saving a new skill from the page", call("/api/file_save", {"kind": "skill", "name": "fresh-one", "text": "hello"})[0] == 200
      and (g.SKILLS / "fresh-one.md").read_text() == "hello\n")
check("POST /api/file_restore restores", call("/api/file_restore", {"kind": "skill", "name": "movies"})[0] == 200 and skill.read_text() == "one\n")
check("POST /api/skill_delete deletes", call("/api/skill_delete", {"name": "fresh-one"})[0] == 200 and not (g.SKILLS / "fresh-one.md").exists())
check("deleting memory is not a route: the name must be a skill", call("/api/skill_delete", {"name": "memory"})[0] == 400 and g.MEMORY.exists())
code, data = call("/api/files")
check("/api/files lists which files can be restored", code == 200 and "skill:movies" in data["restorable"])

state.status = "running"
before = skill.read_text()
check("every edit is refused with 409 while a run is active",
      call("/api/file_save", {"kind": "skill", "name": "movies", "text": "nope"})[0] == 409
      and call("/api/skill_delete", {"name": "movies"})[0] == 409
      and call("/api/file_restore", {"kind": "skill", "name": "movies"})[0] == 409 and skill.read_text() == before)
state.status = "idle"
check("a wrong token is refused on every route",
      all(call(path, body, "bad")[0] == 403 for path, body in [
          ("/api/file_save", {"kind": "memory", "text": "x"}), ("/api/skill_delete", {"name": "movies"}),
          ("/api/file_restore", {"kind": "memory"}), ("/api/file_text?kind=memory", None)]) and skill.read_text() == before)
srv.shutdown()

# --- the page ------------------------------------------------------------------------------------------

page = web.PAGE
check("the page has edit controls and no longer calls every file read-only",
      "openEditor" in page and "Files (read-only)" not in page and "notes.md, read-only" in page)
check("the page keeps an open editor from being rebuilt by the refresh", "if (editingFile) return;" in page)
check("the editor loads the full text, not the clipped view", '"/api/file_text?kind="' in page)

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
