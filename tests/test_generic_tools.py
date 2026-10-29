"""
Safety tests for generic_tools. Run with: .venv/bin/python tests/test_generic_tools.py
The Radarr GET test is live and skipped if RADARR_URL/RADARR_API_KEY are unset.
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from agent import load_env  # noqa: E402

load_env()
prompts: list[str] = []
answer = {"value": False}


def fake_confirm(desc: str) -> bool:
    prompts.append(desc)
    return answer["value"]


g.CONFIRM = fake_confirm
real_logs = g.ROOT / "logs"
logs_snapshot = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()
real_undo = g.ROOT / ".undo"
undo_snapshot = {(p.name, p.stat().st_size) for p in real_undo.iterdir()} if real_undo.exists() else set()
tmp = Path(tempfile.mkdtemp())
saved_initial_undo_dir = getattr(g, "UNDO_DIR", None)
saved_initial_undo_max = getattr(g, "UNDO_MAX_BYTES", None)
saved_initial_undo_keep = getattr(g, "UNDO_KEEP", None)
g.LOG_DIR = tmp / "logs"
g.UNDO_DIR = tmp / "undo"
g.WORKSPACE = tmp / "workspace"
g.SKILLS = tmp / "skills"
g.MEMORY = tmp / "memory.md"
g.WORKSPACE.mkdir()
(g.WORKSPACE / "a.txt").write_text("hello world\n")
(g.WORKSPACE / ".env").write_text("SECRET=1\n")


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0
check("UNDO_DIR is ROOT / .undo", saved_initial_undo_dir == g.ROOT / ".undo")
check("UNDO_MAX_BYTES is 1_000_000", saved_initial_undo_max == 1_000_000)
check("UNDO_KEEP is 10", saved_initial_undo_keep == 10)


def asked() -> bool:
    got = bool(prompts)
    prompts.clear()
    return got


# read-only commands run without asking
check("ls runs free", "a.txt" in g.run_shell("ls") and not asked())
check("cat in workspace runs free", "hello" in g.run_shell("cat a.txt") and not asked())
check("grep runs free", "hello" in g.run_shell("grep hello a.txt") and not asked())

# everything else asks
answer["value"] = False
check("rm asks and is declined", g.run_shell("rm a.txt") == g.DECLINED and asked())
check("rm did not run", (g.WORKSPACE / "a.txt").exists())
check("cat outside scope asks", g.run_shell("cat /etc/hosts") == g.DECLINED and asked())
check("path traversal asks", g.run_shell("cat ../../etc/hosts") == g.DECLINED and asked())
check("~ path outside workspace asks (not treated as a workspace/~ folder)", g.run_shell("ls ~/Downloads") == g.DECLINED and asked())
check("~ is expanded for scope checks", g._resolve("~") == Path.home().resolve())
check("~ alone is outside scope, so not free", g._read_only_argv("ls ~") is None)
check("home folder hint is in the prompt", str(Path.home()) in g.build_instructions())
shell_log = tmp / "shell-log.jsonl"
saved_shell_log, g._log_file = g._log_file, shell_log
g.run_shell("cat a.txt")
shell_entry = [json.loads(line) for line in shell_log.read_text().splitlines() if json.loads(line).get("kind") == "shell"][-1]
g._log_file = saved_shell_log
check("shell log records clipped output", "exit code 0" in shell_entry["output"] and len(shell_entry["output"]) <= g.LOG_OUT)
check("pipe asks", g.run_shell("cat a.txt | wc -c") == g.DECLINED and asked())
check("redirect asks", g.run_shell("cat a.txt > b.txt") == g.DECLINED and asked())
check("command substitution asks", g.run_shell("cat $(echo a.txt)") == g.DECLINED and asked())
check("find -delete asks", g.run_shell("find . -delete") == g.DECLINED and asked())
check("find -exec asks", g.run_shell("find . -exec rm {} ;") == g.DECLINED and asked())
check("cat .env asks (not free)", g.run_shell("cat .env") == g.DECLINED and asked())

answer["value"] = True
check("approved write command runs", "exit code 0" in g.run_shell("echo hi > b.txt") and asked())
check("approved write took effect", (g.WORKSPACE / "b.txt").read_text() == "hi\n")
check("approved pipe reports a failing first stage (#49)", "exit code 0" not in g.run_shell("ls no_such_dir | wc -l"))
answer["value"] = False

# Windows support (#33): both paths route through PowerShell there, not a bare exec / cmd.exe
saved_windows, saved_run = g.WINDOWS, g.subprocess.run
captured = {}


def _fake_run(*a, **k):
    captured["argv"] = a[0]
    return type("R", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()


g.subprocess.run = _fake_run
g.WINDOWS = True
g.run_shell("ls")
check("read-only commands route through PowerShell on Windows",
      captured["argv"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
      and captured["argv"][4] == "ls")
answer["value"] = True
g.run_shell("rm something")
check("confirm-required commands also route through PowerShell on Windows",
      captured["argv"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
      and captured["argv"][4] == "rm something")
answer["value"] = False

# a filename with an apostrophe must be quoted PowerShell-style ('' ), not shlex's POSIX '"'"' escape
check("_ps_quote escapes an embedded single quote for PowerShell",
      g._ps_quote("O'Brien's notes.txt") == "'O''Brien''s notes.txt'")
g.run_shell('cat "O\'Brien\'s notes.txt"')
check("read-only args with an apostrophe are quoted PowerShell-style on Windows",
      "'\"'\"'" not in captured["argv"][4] and "O''Brien''s notes.txt" in captured["argv"][4])
g.WINDOWS = saved_windows


def _raise_oserror(*a, **k):
    raise FileNotFoundError("[WinError 2] The system cannot find the file specified")


g.subprocess.run = _raise_oserror
res = g.run_shell("ls")
check("a command that cannot run returns a clean ERROR instead of crashing",
      res.startswith("ERROR") and "could not run" in res)
g.subprocess.run = saved_run
prompts.clear()  # the "rm something" confirm above isn't what later "was anything asked?" checks care about

# files
check(".env read blocked without asking", g.read_file(".env").startswith("BLOCKED") and not asked())
check(".env write blocked without asking", g.write_file(".env", "x").startswith("BLOCKED") and not asked())
check("read in workspace free", "hello" in g.read_file("a.txt") and not asked())
answer["value"] = False
check("write declined", g.write_file("c.txt", "x") == g.DECLINED and asked())
check("declined write did not happen", not (g.WORKSPACE / "c.txt").exists())
answer["value"] = True
check("write approved", g.write_file("c.txt", "x").startswith("SUCCESS") and asked())
check("outside-scope read asks", "hello" not in g.read_file("../../outside") and asked())

# paged read_file (#86)
big = "".join(f"{i % 10}" for i in range(g.MAX_OUT * 2 + 1500))  # 9,500 characters
(g.WORKSPACE / "big.txt").write_text(big)
(g.WORKSPACE / "exact.txt").write_text("x" * g.MAX_OUT)
p0 = g.read_file("big.txt")
check("first page of a long file is MAX_OUT characters plus a footer with the next offset",
      p0.startswith(big[:g.MAX_OUT]) and p0.endswith(f"[characters 0-{g.MAX_OUT} of {len(big)}; call read_file again with offset={g.MAX_OUT} to continue]"))
p1 = g.read_file("big.txt", offset=g.MAX_OUT)
check("the next offset continues exactly where the page ended", p1.startswith(big[g.MAX_OUT:g.MAX_OUT * 2]) and "offset=8000 to continue" in p1)
p2 = g.read_file("big.txt", offset=2 * g.MAX_OUT)
check("the last page says end of file", p2.startswith(big[2 * g.MAX_OUT:]) and p2.endswith(f"[characters 8000-{len(big)} of {len(big)}; end of file]"))
pages = [g.read_file("big.txt", offset=o).rsplit("\n[characters", 1)[0] for o in (0, 4000, 8000)]
check("the pages join back into the whole file", "".join(pages) == big)
check("an offset past the end says so", "past the end" in g.read_file("big.txt", offset=99999))
check("a negative offset reads from the start", g.read_file("big.txt", offset=-5) == p0)
check("a file of exactly MAX_OUT characters has no footer", g.read_file("exact.txt") == "x" * g.MAX_OUT)
check("a short file read at offset 0 is unchanged", g.read_file("a.txt") == (g.WORKSPACE / "a.txt").read_text())
(g.WORKSPACE / "sec.txt").write_text("x" * 3995 + "page-edge-secret-4242" + "y" * 500)  # the secret straddles the page boundary
saved_secrets = g._secrets
g._secrets = lambda: ["page-edge-secret-4242"]
sec_pages = [g.read_file("sec.txt", offset=o) for o in (0, 3000)]
g._secrets = saved_secrets
check("paging redacts a secret that straddles a page boundary",
      all("page-edge" not in pg and "secret-4242" not in pg for pg in sec_pages) and "[REDACTED]" in sec_pages[1])

# edit_file (#72)
ef = g.WORKSPACE / "ef.txt"
ef.write_text("alpha 420 kWh\nbeta 420 kWh\ngamma\n")
prompts.clear(); answer["value"] = True
r = g.edit_file("ef.txt", "gamma", "delta")
check("edit_file replaces one passage and keeps the rest", ef.read_text() == "alpha 420 kWh\nbeta 420 kWh\ndelta\n" and r.startswith("SUCCESS"))
check("edit_file result reports the size change", "(" in r and "->" in r)
shown = prompts[-1] if prompts else ""
check("edit_file asks first and shows the old and new text", asked() and "- gamma" in shown and "+ delta" in shown)
before = ef.read_text(); prompts.clear()
r = g.edit_file("ef.txt", "420 kWh", "980 kWh")
check("edit_file refuses an old text that matches twice, without asking", "2 times" in r and ef.read_text() == before and not asked())
r = g.edit_file("ef.txt", "no such text", "x")
check("edit_file refuses an old text that is not found, without asking", "not found" in r and ef.read_text() == before and not asked())
check("edit_file refuses an empty old text", g.edit_file("ef.txt", "", "x").startswith("ERROR") and ef.read_text() == before)
answer["value"] = False
r = g.edit_file("ef.txt", "delta", "epsilon")
check("a declined edit changes nothing", r == g.DECLINED and ef.read_text() == before)
answer["value"] = True; prompts.clear()
check("edit_file on a missing file is an error", g.edit_file("nope.txt", "a", "b").startswith("ERROR") and not (g.WORKSPACE / "nope.txt").exists())
check("edit_file blocks .env without asking", g.edit_file(".env", "a", "b").startswith("BLOCKED") and not asked())
(g.WORKSPACE.parent / "outside_ef.txt").write_text("keep me")
r = g.edit_file("../outside_ef.txt", "keep", "lose")
check("edit_file refuses a file outside workspace/ without reading or asking",
      "workspace/" in r and (g.WORKSPACE.parent / "outside_ef.txt").read_text() == "keep me" and not asked())
(g.WORKSPACE / "crlf.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
g.edit_file("crlf.txt", "two", "2")
check("edit_file keeps the other lines' line endings byte for byte", (g.WORKSPACE / "crlf.txt").read_bytes() == b"one\r\n2\r\nthree\r\n")
(g.WORKSPACE / "bin.dat").write_bytes(b"\xff\xfe\x00")
check("edit_file on a non-text file is an error", g.edit_file("bin.dat", "a", "b").startswith("ERROR"))
ef.write_text("price: $1 & done \\1 /x/\n")
g.edit_file("ef.txt", "$1 & done \\1", "&\\1 $2")
check("edit_file treats old and new literally", ef.read_text() == "price: &\\1 $2 /x/\n")
undo_before = {q.name for q in g.UNDO_DIR.iterdir()} if g.UNDO_DIR.exists() else set()
g.edit_file("ef.txt", "/x/", "/y/")
undo_after = {q.name for q in g.UNDO_DIR.iterdir()}
check("an approved edit saves the previous content to the undo folder",
      len(undo_after - undo_before) == 1 and any(q.read_text() == "price: &\\1 $2 /x/\n" for q in g.UNDO_DIR.iterdir() if q.name in undo_after - undo_before))
check("edit_file is in the generic toolset", g.edit_file in g.GENERIC_TOOLS)
answer["value"] = False; prompts.clear()

# list_dir
(g.WORKSPACE / "ld").mkdir()
(g.WORKSPACE / "ld" / "sub").mkdir()
(g.WORKSPACE / "ld" / "sub" / "x").write_text("1")
(g.WORKSPACE / "ld" / "sub" / "y").write_text("2")
(g.WORKSPACE / "ld" / "big.bin").write_bytes(b"0" * 2048)
(g.WORKSPACE / "ld" / "b.txt").write_text("12345")
listing = g.list_dir("ld")
check("list_dir result is kept for the page", g.SHOWN_OUTPUT == ("list_dir ld", listing))
g.run_shell("ls ld")
check("shell result is kept for the page, labelled with the command",
      g.SHOWN_OUTPUT is not None and g.SHOWN_OUTPUT[0] == "$ ls ld" and "big.bin" in g.SHOWN_OUTPUT[1])
g.start_log("m", "p")
check("starting a run clears the shown output", g.SHOWN_OUTPUT is None)
g.run_shell("ls ld")
check("list_dir gives an exact count line", ": 3 entries (1 folders, 2 files)" in listing.splitlines()[0])
check("list_dir counts a subfolder's items exactly", "sub/  folder, 2 items" in listing)
check("list_dir shows sizes", "b.txt  5 B" in listing and "big.bin  2.0 KB" in listing)
check("list_dir lists folders first", listing.splitlines()[1].startswith("sub/"))
check("list_dir in workspace is free", not asked())
check("list_dir blocks .ssh without asking", g.list_dir(".ssh").startswith("BLOCKED") and not asked())
answer["value"] = False
check("outside-scope list_dir asks and can be declined", g.list_dir("../..") == g.DECLINED and asked())
answer["value"] = True
check("list_dir of a missing folder is a clean ERROR", g.list_dir("nope").startswith("ERROR"))
(g.WORKSPACE / "many").mkdir()
for i in range(g.LIST_DIR_MAX + 5):
    (g.WORKSPACE / "many" / f"f{i:03}").write_text("")
many = g.list_dir("many")
check("list_dir caps long listings but keeps the true count",
      f": {g.LIST_DIR_MAX + 5} entries" in many.splitlines()[0] and len(many.splitlines()) == g.LIST_DIR_MAX + 1)
check("list_dir is in the generic toolset", g.list_dir in g.GENERIC_TOOLS)
prompts.clear()

# skills
answer["value"] = False
check("skill write declined", g.write_skill("demo", "# Demo\nx") == g.DECLINED and asked())
answer["value"] = True
check("skill write approved", g.write_skill("Demo!!", "# Demo\nx").startswith("SUCCESS") and asked())
check("skill name sanitised", (g.SKILLS / "demo.md").exists())
check("list_skills shows it", "demo: Demo" in g.list_skills())
check("read_skill works", "x" in g.read_skill("demo"))

# file and skill tools logging (#39)
import web  # noqa: E402
fs_log = tmp / "file-skill-log.jsonl"
saved_log_file = g._log_file
g._log_file = fs_log

# 1. read_file logging
(g.WORKSPACE / "distinctive_read.txt").write_text("DISTINCTIVE_READ_PAYLOAD_12345\n")
g.read_file("distinctive_read.txt")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("read_file writes one entry of kind read_file", len(entries) == 1 and entries[0]["kind"] == "read_file")
check("read_file entry has path and result fields", entries[0]["path"] == "distinctive_read.txt" and entries[0]["result"] == "ok")
check("read_file log entry never contains file contents", "DISTINCTIVE_READ_PAYLOAD_12345" not in fs_log.read_text())

# edit_file logging (#72): one entry, never the file contents or the passages
answer["value"] = True
(g.WORKSPACE / "distinctive_edit.txt").write_text("keep DISTINCTIVE_EDIT_OLD_777 keep")
fs_log.unlink()
g.edit_file("distinctive_edit.txt", "DISTINCTIVE_EDIT_OLD_777", "DISTINCTIVE_EDIT_NEW_888")
entries = [e for e in map(json.loads, fs_log.read_text().splitlines()) if e["kind"] == "edit_file"]  # the approval is logged separately
check("edit_file writes one entry of kind edit_file with path and result",
      len(entries) == 1 and entries[0]["kind"] == "edit_file" and entries[0]["path"] == "distinctive_edit.txt" and entries[0]["result"] == "ok")
check("the edit_file log entry never contains the file contents or passages", "DISTINCTIVE_EDIT" not in json.dumps(entries))
answer["value"] = False
fs_log.unlink()
g.read_file("distinctive_read.txt")

# blocked secret read
fs_log.unlink()
res_secret = g.read_file(".env")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("blocked secrets-file read is logged as blocked",
      len(entries) == 1 and entries[0]["kind"] == "read_file" and entries[0]["result"] == "blocked (secrets file)")
check("blocked secrets-file read returned string is unchanged",
      res_secret == "BLOCKED: this file holds secrets and cannot be read.")

# declined read (outside workspace)
fs_log.unlink()
answer["value"] = False
res_read_declined = g.read_file("../../outside")
prompts.clear()
rf_entries = [json.loads(line) for line in fs_log.read_text().splitlines() if json.loads(line).get("kind") == "read_file"]
check("declined read is logged as declined",
      len(rf_entries) == 1 and rf_entries[0]["result"] == "declined" and res_read_declined == g.DECLINED)

# read error
fs_log.unlink()
res_read_err = g.read_file("nonexistent_file.txt")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("missing file read is logged with exception class name",
      len(entries) == 1 and entries[0]["kind"] == "read_file" and entries[0]["result"] == "error (FileNotFoundError)")

# 2. write_file logging
fs_log.unlink()
answer["value"] = True
distinctive_text = "SECRET_DISTINCTIVE_BODY_ABCXYZ123456"
res_write = g.write_file("distinctive.txt", distinctive_text)
prompts.clear()
wf_entries = [json.loads(line) for line in fs_log.read_text().splitlines() if json.loads(line).get("kind") == "write_file"]
check("write_file writes one entry with path, chars, result",
      len(wf_entries) == 1 and wf_entries[0]["path"] == "distinctive.txt"
      and wf_entries[0]["chars"] == len(distinctive_text) and wf_entries[0]["result"] == "ok")
check("write_file log entry never contains file contents",
      distinctive_text not in json.dumps(wf_entries[0]))

# declined write
fs_log.unlink()
answer["value"] = False
res_write_dec = g.write_file("declined.txt", "declined text")
prompts.clear()
wf_entries = [json.loads(line) for line in fs_log.read_text().splitlines() if json.loads(line).get("kind") == "write_file"]
check("declined write is logged as declined",
      len(wf_entries) == 1 and wf_entries[0]["result"] == "declined" and res_write_dec == g.DECLINED)

# blocked secret write
fs_log.unlink()
res_write_sec = g.write_file(".env", "SECRET=1")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("blocked secrets-file write is logged as blocked",
      len(entries) == 1 and entries[0]["kind"] == "write_file" and entries[0]["result"] == "blocked (secrets file)")

# 3. list_skills logging
fs_log.unlink()
g.list_skills()
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("list_skills writes one entry with result",
      len(entries) == 1 and entries[0]["kind"] == "list_skills" and "skills" in entries[0]["result"])

# 4. read_skill logging
fs_log.unlink()
g.read_skill("demo")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("read_skill writes one entry with name and result",
      len(entries) == 1 and entries[0]["kind"] == "read_skill" and entries[0]["name"] == "demo" and entries[0]["result"] == "ok")

fs_log.unlink()
res_sk_missing = g.read_skill("nonexistent_skill")
entries = [json.loads(line) for line in fs_log.read_text().splitlines()]
check("nonexistent read_skill logged as not found",
      len(entries) == 1 and entries[0]["kind"] == "read_skill" and entries[0]["result"] == "not found"
      and res_sk_missing == "No such skill. Call list_skills.")

# 5. write_skill logging
fs_log.unlink()
answer["value"] = True
distinctive_skill = "# Unique Skill\nUNIQUE_SKILL_BODY_QWERTY987"
g.write_skill("unique_skill", distinctive_skill)
prompts.clear()
ws_entries = [json.loads(line) for line in fs_log.read_text().splitlines() if json.loads(line).get("kind") == "write_skill"]
check("write_skill writes one entry with name, chars, result",
      len(ws_entries) == 1 and ws_entries[0]["name"] == "unique_skill"
      and ws_entries[0]["chars"] == len(distinctive_skill) and ws_entries[0]["result"] == "ok")
check("write_skill log entry never contains skill contents",
      distinctive_skill not in json.dumps(ws_entries[0]) and "UNIQUE_SKILL_BODY_QWERTY987" not in json.dumps(ws_entries[0]))

# declined write_skill
fs_log.unlink()
answer["value"] = False
res_sk_dec = g.write_skill("declined_sk", "# Decl\ntext")
prompts.clear()
ws_entries = [json.loads(line) for line in fs_log.read_text().splitlines() if json.loads(line).get("kind") == "write_skill"]
check("declined write_skill logged as declined",
      len(ws_entries) == 1 and ws_entries[0]["result"] == "declined" and res_sk_dec == g.DECLINED)

# 6. web.feed() renders all 5 new kinds
fs_log.unlink()
answer["value"] = True
g.read_file("a.txt")
g.write_file("feed_w.txt", "hello")
prompts.clear()
g.list_skills()
g.read_skill("demo")
g.write_skill("feed_sk", "# Sk\ncontent")
prompts.clear()

saved_feed_log, web.g._log_file = web.g._log_file, fs_log
feed_lines = web.feed()
web.g._log_file = saved_feed_log
g._log_file = saved_log_file

check("web.feed() shows read_file", any("read_file a.txt -> ok" in fl for fl in feed_lines))
check("web.feed() shows write_file with chars", any("write_file feed_w.txt (5 chars) -> ok" in fl for fl in feed_lines))
check("web.feed() shows list_skills", any("list_skills ->" in fl for fl in feed_lines))
check("web.feed() shows read_skill", any("read_skill demo -> ok" in fl for fl in feed_lines))
check("web.feed() shows write_skill with chars", any("write_skill feed_sk" in fl and "chars) -> ok" in fl for fl in feed_lines))

# memory: remember and recall (#27)
check("remember is in GENERIC_TOOLS", g.remember in g.GENERIC_TOOLS)
check("recall is in GENERIC_TOOLS", g.recall in g.GENERIC_TOOLS)
check("recall on empty memory reports no memories", g.recall() == "No memories saved yet.")
check("remember rejects empty fact", "ERROR" in g.remember(""))

# remember asks for approval and handles decline
answer["value"] = False
declined_res = g.remember("User prefers dark mode")
check("remember declined returns DECLINED", declined_res == g.DECLINED and asked())
check("declined fact not written to file", not g.MEMORY.exists() or "dark mode" not in g.MEMORY.read_text())

# remember approved writes fact
answer["value"] = True
approved_res = g.remember("User prefers dark mode")
check("remember approved returns SUCCESS", approved_res.startswith("SUCCESS") and asked())
check("fact written to memory.md", g.MEMORY.exists() and "User prefers dark mode" in g.MEMORY.read_text())

# remember appends subsequent facts
g.remember("Backup drive is /Volumes/Backup")
asked()
mem_content = g.MEMORY.read_text()
check("remember appends subsequent facts", "dark mode" in mem_content and "/Volumes/Backup" in mem_content)

# remember redacts credentials
g.remember("My API key is sk-1234567890abcdef12345678")
asked()
redacted_mem = g.MEMORY.read_text()
check("remember redacts credentials", "sk-1234567890abcdef12345678" not in redacted_mem and "[REDACTED" in redacted_mem)

# recall queries
all_facts = g.recall()
check("recall empty query returns all facts", "dark mode" in all_facts and "/Volumes/Backup" in all_facts)
single_hit = g.recall("dark mode")
check("recall single keyword returns matching line", "dark mode" in single_hit and "/Volumes/Backup" not in single_hit)
multi_hit = g.recall("backup drive")
check("recall multi-word query finds match", "/Volumes/Backup" in multi_hit)
no_hit = g.recall("nonexistent topic")
check("recall no match explains clearly", "No memories matching 'nonexistent topic'." in no_hit)
check("recall does not ask for confirmation", not asked())

# memory is NOT inlined into prompt (prompt overhead is 0)
check("memory is not inlined into prompt", "dark mode" not in g.build_instructions())

# Real token cost of the combined remember+recall schema, measured against the actual JSON
# smolagents sends (get_tool_json_schema), not the hand-reconstructed dict this test used to check
# (485 chars, missing "type": "object"/"required"/"nullable" -- about a third smaller than real).
# Checked against two tokenizers (Ollama /api/generate, raw prompt, no chat template): 179 tokens
# on Qwen 3.5 9B, 182 on Gemma 4 E4B. Both exceed #27's own 100-150 token budget and the "~147
# tokens" this test originally claimed. See CHANGELOG.md. No tokenizer is available to this test
# file, so there is no assertion here -- a char-count proxy already said something untrue once.

# logging of remember and recall
mem_log_file = tmp / "mem-log.jsonl"
saved_log_file = g._log_file
g._log_file = mem_log_file
g.remember("Favorite language is Python")
asked()
g.recall("Python")
g.recall("Ruby")
mem_logs = [json.loads(line) for line in mem_log_file.read_text().splitlines()]
g._log_file = saved_log_file

check("remember calls are logged", any(l["kind"] == "remember" and "Python" in l["fact"] for l in mem_logs))
check("recall calls are logged with query and hits", any(l["kind"] == "recall" and l["query"] == "Python" and l["hits"] > 0 for l in mem_logs))
check("recall zero-hits logged", any(l["kind"] == "recall" and l["query"] == "Ruby" and l["hits"] == 0 for l in mem_logs))

# ask_user redacts a pasted credential before it reaches the model or the log (#32)
check("a GitHub token in an answer is redacted",
      g.redact_pasted_secrets("ghp_0000000000000000000000000000000000") == "[REDACTED: looks like a credential]")
check("an AWS key in a sentence is redacted",
      "[REDACTED" in g.redact_pasted_secrets("here is my key: AKIAABCDEFGHIJKLMNOP thanks")
      and "AKIAABCDEFGHIJKLMNOP" not in g.redact_pasted_secrets("here is my key: AKIAABCDEFGHIJKLMNOP thanks"))
check("an ordinary path is not redacted", g.redact_pasted_secrets("/tmp/my demo") == "/tmp/my demo")
check("an ordinary short answer is not redacted", g.redact_pasted_secrets("Paris") == "Paris")
saved_ask, saved_log_file = g.ASK, g._log_file
g.ASK = lambda q: "my token is ghp_0000000000000000000000000000000000 ok"
g._log_file = tmp / "ask-user-redaction-log.jsonl"
res = g.ask_user("what is your token?")
check("ask_user itself redacts a pasted credential before returning it",
      "ghp_" not in res and "[REDACTED" in res)
check("the redacted answer, not the raw one, is what gets logged",
      "ghp_" not in g._log_file.read_text() and "[REDACTED" in g._log_file.read_text())
g.ASK = saved_ask
g._log_file = saved_log_file

# http: GET free, others ask
answer["value"] = False
check("POST asks and is declined", g.http_request("POST", "http://127.0.0.1:9/x", "{}") == g.DECLINED and asked())
check("bad JSON body rejected", g.http_request("POST", "http://127.0.0.1:9/x", "{bad").startswith("ERROR"))
check("GET failure reports error without asking", g.http_request("GET", "http://127.0.0.1:9/x").startswith("ERROR") and not asked())

# pre-flight validation on writes and required queries (#31)
net_called = [False]


def _fail_network(*a, **k):
    net_called[0] = True
    raise AssertionError("Network call was made during preflight validation")


saved_req = g.requests.request
g.requests.request = _fail_network

empty_post_res = g.http_request("POST", "http://127.0.0.1:9/x", "")
check("empty-body POST returns ERROR without asking and makes no network call",
      empty_post_res.startswith("ERROR") and "requires a request body" in empty_post_res
      and not asked() and not net_called[0])

ws_post_res = g.http_request("POST", "http://127.0.0.1:9/x", "   ")
check("whitespace-only-body POST returns ERROR without asking and makes no network call",
      ws_post_res.startswith("ERROR") and "requires a request body" in ws_post_res
      and not asked() and not net_called[0])

term_res = g.http_request("GET", "http://127.0.0.1:9/api/v3/movie/lookup?term=")
check("lookup?term= returns ERROR without asking and makes no network call",
      term_res.startswith("ERROR") and "query parameter 'term' is empty" in term_res
      and not asked() and not net_called[0])

q_res = g.http_request("GET", "http://127.0.0.1:9/search?q=")
check("search?q= returns ERROR without asking and makes no network call",
      q_res.startswith("ERROR") and "query parameter 'q' is empty" in q_res
      and not asked() and not net_called[0])

query_res = g.http_request("GET", "http://127.0.0.1:9/search?query=")
check("search?query= returns ERROR without asking and makes no network call",
      query_res.startswith("ERROR") and "query parameter 'query' is empty" in query_res
      and not asked() and not net_called[0])

check("empty body PUT returns ERROR without asking",
      g.http_request("PUT", "http://127.0.0.1:9/x", "").startswith("ERROR")
      and not asked() and not net_called[0])

check("empty body PATCH returns ERROR without asking",
      g.http_request("PATCH", "http://127.0.0.1:9/x", "").startswith("ERROR")
      and not asked() and not net_called[0])

g.requests.request = saved_req

# rejections are logged, so a run can count them (#36)
saved_pf_log = g._log_file
g._log_file = tmp / "preflight-log.jsonl"
g.requests.request = _fail_network
g.http_request("POST", "http://127.0.0.1:9/api/v3/movie", "")
g.http_request("GET", "http://127.0.0.1:9/api/v3/movie/lookup?term=")
g.requests.request = saved_req
pf_entries = [g.json.loads(line) for line in g._log_file.read_text().splitlines()]
check("each pre-flight rejection is logged once, as kind preflight", [e["kind"] for e in pf_entries] == ["preflight", "preflight"])
check("the log entry has the method, URL and reason",
      pf_entries[0]["method"] == "POST" and pf_entries[0]["url"].endswith("/api/v3/movie") and "requires a request body" in pf_entries[0]["reason"]
      and "'term' is empty" in pf_entries[1]["reason"])
g.http_request("GET", "http://127.0.0.1:9/x")
check("a request that passes pre-flight logs no preflight entry",
      [g.json.loads(line)["kind"] for line in g._log_file.read_text().splitlines()].count("preflight") == 2)
import web  # noqa: E402
saved_pf_feed, web.g._log_file = web.g._log_file, g._log_file
check("web.py's feed shows a refused request and why",
      any("refused before sending" in fl and "POST" in fl and "requires a request body" in fl for fl in web.feed()))
web.g._log_file = saved_pf_feed
g._log_file = saved_pf_log

check("DELETE with no body is unaffected", g.http_request("DELETE", "http://127.0.0.1:9/x", "") == g.DECLINED and asked())
check("?term=matrix is unaffected", "query parameter" not in g.http_request("GET", "http://127.0.0.1:9/api/v3/movie/lookup?term=matrix") and not asked())
check("URL with no query string is unaffected", "query parameter" not in g.http_request("GET", "http://127.0.0.1:9/api/v3/movie") and not asked())
check("action endpoint with empty body asks and is declined", g.http_request("POST", "http://127.0.0.1:9/api/v3/system/restart", "") == g.DECLINED and asked())
check("/command needs a JSON body, so an empty POST is rejected",
      g.http_request("POST", "http://127.0.0.1:9/api/v3/command", "").startswith("ERROR") and not asked())

saved_notes = g.NOTES.read_text() if g.NOTES.exists() else ""
g.NOTES.write_text("- svc: http://x:7878 | key_env=SMOLPAW_TEST_PREFLIGHT_KEY\n")
os.environ["SMOLPAW_TEST_PREFLIGHT_KEY"] = "preflight-test-key-abcdef"
preflight_redacted = g.http_request("POST", "http://x:7878/api?k=preflight-test-key-abcdef", "")
check("preflight error redacts secrets in URL",
      "preflight-test-key-abcdef" not in preflight_redacted and "[REDACTED]" in preflight_redacted)
del os.environ["SMOLPAW_TEST_PREFLIGHT_KEY"]
if saved_notes:
    g.NOTES.write_text(saved_notes)
else:
    g.NOTES.unlink(missing_ok=True)

# openapi_search (spec served from a fake requests.get)
class _Resp:
    def json(self):
        return {"paths": {"/api/v3/queue": {"get": {"summary": "List queue", "tags": ["Queue"]}},
                          "/api/v3/movie": {"get": {"summary": "List movies", "tags": ["Movie"]}}}}


g.requests.get = lambda *a, **k: _Resp()
check("openapi_search finds endpoint", "GET /api/v3/queue" in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search excludes others", "movie" not in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search lists tags", "Queue" in g.openapi_search("http://x/spec.json"))
class _Page:
    def json(self):
        return {"service": "x", "resources": {}}


g.requests.get = lambda *a, **k: _Page()
msg = g.openapi_search("http://x/index", "queue")
check("openapi_search explains non-spec JSON", "not an OpenAPI spec" in msg and "http_request" in msg)
g.requests.get = lambda *a, **k: _Resp()
check("openapi_search no match", g.openapi_search("http://x/spec.json", "zzz") == "No matching endpoints.")

# openapi_search calls are logged, like http_request and run_shell (#30)
_SPECS_SAVED = dict(g._SPECS)
g._SPECS.clear()
saved_log_file = g._log_file
g._log_file = tmp / "openapi-search-log.jsonl"
g.requests.get = lambda *a, **k: _Resp()
g.openapi_search("http://x/spec2.json", "queue")
g.openapi_search("http://x/spec2.json", "zzz")
entries = [g.json.loads(line) for line in g._log_file.read_text().splitlines()]
check("openapi_search calls are logged", [e["kind"] for e in entries] == ["openapi_search", "openapi_search"])
check("logged entry has the keyword and a hit count", entries[0]["keyword"] == "queue" and entries[0]["result"] == "1 hits")
check("a no-match call is logged too", entries[1]["keyword"] == "zzz" and entries[1]["result"] == "0 hits")
g._log_file = saved_log_file
g._SPECS.clear(); g._SPECS.update(_SPECS_SAVED)
import web  # noqa: E402
saved_feed_log, web.g._log_file = web.g._log_file, (tmp / "openapi-search-log.jsonl")
line = web.feed()[0]
check("web.py's feed shows the spec, keyword and result", "spec2.json" in line and "queue" in line and "1 hits" in line)
web.g._log_file = mem_log_file
feed_lines = web.feed()
check("web.py feed shows remember fact", any("remember" in fl and "Python" in fl for fl in feed_lines))
check("web.py feed shows recall query and hits", any("recall" in fl and "Python" in fl for fl in feed_lines))
web.g._log_file = saved_feed_log

# HTML responses are flagged, JSON is not
class _Http:
    def __init__(self, text, ctype, status=200):
        self.text, self.headers, self.status_code = text, {"content-type": ctype}, status


_real_request = g.requests.request
saved_notes = g.NOTES
g.NOTES = tmp / "html-notes.md"
g.NOTES.write_text("- svc: http://x:7878 | key_env=SMOLPAW_TEST_HTML_KEY\n")
g.requests.request = lambda *a, **k: _Http("<!doctype html><html>login</html>", "text/html")
res = g.http_request("GET", "http://x:7878/DownloadQueue")
check("HTML from a known service flagged as not an answer", "HTML web page" in res and "login" not in res)
page = ("<!doctype html><html><head><title>Release &amp; notes</title><style>p{x:1}</style>"
        "<script>var secret=1</script></head><body><nav>Home</nav><h1>Python 3.14</h1>"
        "<p>Released   in\n October.</p><ul><li>one</li><li>two</li></ul></body></html>")
g.requests.request = lambda *a, **k: _Http(page, "text/html; charset=utf-8")
res = g.http_request("GET", "https://www.example.org/news")
check("other web pages converted to text",
      res.startswith("HTTP 200 (web page converted to text)") and "Title: Release & notes" in res
      and "Python 3.14\nReleased in October.\none\ntwo" in res)
check("scripts, styles and tags dropped", "secret" not in res and "x:1" not in res and "<" not in res)
check("only <main> kept when it has text",
      g.html_to_text("<div>Menu</div><main><p>Body</p></main><div>Links</div>") == "Body")
os.environ["SMOLPAW_TEST_HTML_KEY"] = "html-key-12345678"
g.requests.request = lambda *a, **k: _Http("<p>key html-key-12345678</p>", "text/html")
check("converted page text is redacted", "html-key-12345678" not in g.http_request("GET", "http://other/"))
g.NOTES = saved_notes
g.requests.request = lambda *a, **k: _Http('{"ok": true}', "application/json")
check("JSON body passed through", g.http_request("GET", "http://x/api").endswith('{"ok": true}'))
g.requests.request = _real_request

# fetch_page (#28): on-demand web page text trimmed to query
check("fetch_page rejects non-http url", g.fetch_page("ftp://example.com").startswith("ERROR: URL must start with"))
check("fetch_page is in GENERIC_TOOLS", g.fetch_page in g.GENERIC_TOOLS)


class _FakeGetResp:
    def __init__(self, text, ctype="text/html", status=200):
        self.text = text
        self.headers = {"content-type": ctype}
        self.status_code = status
        self.ok = 200 <= status < 300


sample_html = """<!doctype html>
<html><head><title>Documentation Guide</title></head>
<body>
<h1>Welcome</h1>
<p>Introductory paragraph describing the project.</p>
<h2>Architecture</h2>
<p>The system uses SQLite for metadata storage.</p>
<p>Redis is used for caching session state.</p>
<h2>Deployment</h2>
<p>Deploy using Docker containers with compose.</p>
<p>Kubernetes Helm charts are also supported.</p>
</body></html>"""

saved_get = g.requests.get
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)

# empty query returns title and top of page
top_res = g.fetch_page("https://example.com/docs")
check("fetch_page empty query returns top text", "Title: Documentation Guide" in top_res and "Introductory paragraph" in top_res)

# query matching specific section
arch_res = g.fetch_page("https://example.com/docs", query="SQLite")
check("fetch_page extracts matching query section", "SQLite for metadata storage" in arch_res)
check("fetch_page includes context around match", "Architecture" in arch_res)
check("fetch_page excludes unrelated sections", "Kubernetes Helm charts" not in arch_res)

# query with no match gives clean message
no_match_res = g.fetch_page("https://example.com/docs", query="Postgres")
check("fetch_page explains no match with title and preview", "No content matching 'Postgres' found" in no_match_res and "Documentation Guide" in no_match_res)

# HTTP error handling
g.requests.get = lambda *a, **k: _FakeGetResp("Page Not Found", status=404)
err_res = g.fetch_page("https://example.com/missing", query="test")
check("fetch_page reports HTTP error status", err_res.startswith("HTTP 404"))

# Request exception handling
def _raise_req_err(*a, **k):
    raise g.requests.RequestException("connection timed out")


g.requests.get = _raise_req_err
net_err_res = g.fetch_page("https://example.com/timeout", query="test")
check("fetch_page reports request exception", net_err_res.startswith("ERROR: connection timed out"))

# secret redaction
os.environ["SMOLPAW_TEST_PAGE_KEY"] = "secret-page-token-999"
saved_notes = g.NOTES
g.NOTES = tmp / "page-notes.md"
g.NOTES.write_text("- page_svc: https://example.com | key_env=SMOLPAW_TEST_PAGE_KEY\n")
g.requests.get = lambda *a, **k: _FakeGetResp("<p>Token secret-page-token-999 is private</p>")
redacted_res = g.fetch_page("https://unregistered-page.example/secret", query="Token")
check("fetch_page redacts secrets", "secret-page-token-999" not in redacted_res and "[REDACTED]" in redacted_res)

# a registered service answering with HTML means a wrong API path, same warning as http_request (not silently trimmed)
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)
wrong_path_res = g.fetch_page("https://example.com/secret", query="SQLite")
check("fetch_page warns on a service's HTML instead of trimming it",
      "NOT an answer" in wrong_path_res and "SQLite" not in wrong_path_res)
g.NOTES = saved_notes

# logging and feed
saved_log = g._log_file
g._log_file = tmp / "fetch-page-log.jsonl"
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)
g.fetch_page("https://example.com/docs", query="Redis")
g.fetch_page("https://example.com/docs", query="nonexistent")
log_entries = [g.json.loads(line) for line in g._log_file.read_text().splitlines()]
check("fetch_page calls are logged", len(log_entries) == 2 and log_entries[0]["kind"] == "fetch_page")
check("fetch_page log records query and hit count", log_entries[0]["query"] == "Redis" and log_entries[0]["hits"] > 0)
check("fetch_page log records zero hits on no match", log_entries[1]["hits"] == 0)

saved_feed_log, web.g._log_file = web.g._log_file, g._log_file
feed_line = web.feed()[0]
check("web.py feed shows fetch_page query and result", "fetch_page" in feed_line and "Redis" in feed_line and "hits" in feed_line)
web.g._log_file = saved_feed_log
g._log_file = saved_log
g.requests.get = saved_get

# --- web_search (#24) -----------------------------------------------------------

# 1. Shared behaviour (against a fake provider in SEARCH_PROVIDERS)
def _fake_search(query: str, limit: int) -> list[dict]:
    if query == "error":
        raise ValueError("simulated provider error")
    return [
        {"title": f"Title {i}", "url": f"https://example.com/{i}", "snippet": f"Snippet {i} line1\nline2"}
        for i in range(1, 9)
    ]

g.SEARCH_PROVIDERS["fake"] = _fake_search
saved_provider = os.environ.get("SMOLPAW_SEARCH_PROVIDER")
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "fake"
g.reset_search_count()

# 5-result cap
res_cap = g.web_search("test")
check("web_search caps results at 5", "5. Title 5" in res_cap and "6. Title 6" not in res_cap)

# Formatting
check("web_search formats title, url and one-line snippet",
      "1. Title 1\n   https://example.com/1\n   Snippet 1 line1 line2" in res_cap)

# Redaction
saved_notes = g.NOTES
g.NOTES = tmp / "search-notes.md"
os.environ["SMOLPAW_SEARCH_SECRET"] = "secret-search-token-999"
g.NOTES.write_text("- search_svc: https://example.com | key_env=SMOLPAW_SEARCH_SECRET\n")

def _secret_search(query: str, limit: int) -> list[dict]:
    return [{"title": "Secret", "url": "https://example.com/secret", "snippet": "Found secret-search-token-999 in text"}]

g.SEARCH_PROVIDERS["secret_fake"] = _secret_search
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "secret_fake"
g.reset_search_count()
res_redacted = g.web_search("secret")
check("web_search redacts secrets from results",
      "secret-search-token-999" not in res_redacted and "[REDACTED]" in res_redacted)
g.NOTES = saved_notes

# Logging fields with no result contents
saved_log = g._log_file
g._log_file = tmp / "web-search-log.jsonl"
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "fake"
g.reset_search_count()
g.web_search("test_query")
ws_log = [g.json.loads(line) for line in g._log_file.read_text().splitlines()][-1]
check("web_search logs kind web_search", ws_log.get("kind") == "web_search")
check("web_search logs provider and query", ws_log.get("provider") == "fake" and ws_log.get("query") == "test_query")
check("web_search logs status and hit count", ws_log.get("status") == "ok" and ws_log.get("hits") == 5 and ws_log.get("result") == "5 hits")
check("web_search log entry never contains result contents",
      "Title 1" not in str(ws_log) and "Snippet 1" not in str(ws_log) and "https://example.com" not in str(ws_log))

# Error handling
g.reset_search_count()
err_out = g.web_search("error")
check("web_search turns provider failure into ERROR string", err_out.startswith("ERROR: simulated provider error"))
ws_err_log = [g.json.loads(line) for line in g._log_file.read_text().splitlines()][-1]
check("web_search error logged with error status and hit count 0",
      ws_err_log.get("status") == "error" and ws_err_log.get("hits") == 0 and "ValueError" in ws_err_log.get("result", ""))

# Web feed line for web_search
saved_feed_log, web.g._log_file = web.g._log_file, g._log_file
ws_feed_line = web.feed()[-2]  # the success log entry
check("web.py feed shows web_search query, provider and hits",
      "web_search" in ws_feed_line and "test_query" in ws_feed_line and "fake" in ws_feed_line and "5 hits" in ws_feed_line)
web.g._log_file = saved_feed_log
g._log_file = saved_log

# 2. ddgs provider
import types
mock_ddgs_mod = types.ModuleType("ddgs")
mock_exc_mod = types.ModuleType("ddgs.exceptions")
class MockDDGSException(Exception): pass
class MockRatelimitException(MockDDGSException): pass
class MockTimeoutException(MockDDGSException): pass
mock_exc_mod.DDGSException = MockDDGSException
mock_exc_mod.RatelimitException = MockRatelimitException
mock_exc_mod.TimeoutException = MockTimeoutException
mock_ddgs_mod.exceptions = mock_exc_mod
mock_ddgs_mod.DDGSException = MockDDGSException
mock_ddgs_mod.RatelimitException = MockRatelimitException
mock_ddgs_mod.TimeoutException = MockTimeoutException

saved_ddgs = sys.modules.get("ddgs")
saved_ddgs_exc = sys.modules.get("ddgs.exceptions")
sys.modules["ddgs"] = mock_ddgs_mod
sys.modules["ddgs.exceptions"] = mock_exc_mod

class FakeDDGS:
    def __init__(self, mode="ok"):
        self.mode = mode
    def text(self, query, max_results=10):
        if self.mode == "ok":
            return [
                {"title": "DDG 1", "href": "https://ddg.example/1", "body": "Snippet 1"},
                {"title": "DDG 2", "url": "https://ddg.example/2", "snippet": "Snippet 2"},
            ]
        elif self.mode == "empty":
            return []
        elif self.mode == "empty_exc":
            raise MockDDGSException("No results found.")
        elif self.mode == "ratelimit":
            raise MockRatelimitException("Ratelimit 202")
        elif self.mode == "timeout":
            raise MockTimeoutException("search timed out")
        elif self.mode == "lib_exc":
            raise MockDDGSException("internal ddgs exception")

# result mapping
mock_ddgs_mod.DDGS = lambda: FakeDDGS("ok")
mapped = g._search_ddgs("ddgs test", 5)
check("ddgs maps results with title, url, snippet",
      len(mapped) == 2 and mapped[0]["title"] == "DDG 1" and mapped[0]["url"] == "https://ddg.example/1"
      and mapped[0]["snippet"] == "Snippet 1" and mapped[1]["url"] == "https://ddg.example/2")

# empty results (list and exception)
mock_ddgs_mod.DDGS = lambda: FakeDDGS("empty")
check("ddgs returns empty list on empty results", g._search_ddgs("empty", 5) == [])
mock_ddgs_mod.DDGS = lambda: FakeDDGS("empty_exc")
check("ddgs returns empty list on No results found exception", g._search_ddgs("empty", 5) == [])

os.environ["SMOLPAW_SEARCH_PROVIDER"] = "ddgs"
g.reset_search_count()
empty_msg = g.web_search("empty_query")
check("web_search returns clean no-results message telling not to repeat query",
      "No results found" in empty_msg and "Try different" in empty_msg and "do not repeat" in empty_msg)

# library exception
mock_ddgs_mod.DDGS = lambda: FakeDDGS("lib_exc")
g.reset_search_count()
lib_err = g.web_search("lib_query")
check("ddgs library exception returns ERROR and tells not to retry",
      lib_err.startswith("ERROR:") and "internal ddgs exception" in lib_err and "Do not retry" in lib_err)

# rate-limit exception
mock_ddgs_mod.DDGS = lambda: FakeDDGS("ratelimit")
g.reset_search_count()
rate_err = g.web_search("rate_query")
check("ddgs rate-limit exception returns ERROR and tells not to retry",
      rate_err.startswith("ERROR:") and "rate limit" in rate_err.lower() and "Do not retry" in rate_err)

# missing-library case
sys.modules["ddgs"] = None
g.reset_search_count()
missing_err = g.web_search("missing_lib")
check("ddgs missing library returns ERROR saying to re-run setup.sh",
      missing_err.startswith("ERROR:") and "./setup.sh" in missing_err)

# restore ddgs sys.modules
if saved_ddgs is not None:
    sys.modules["ddgs"] = saved_ddgs
else:
    sys.modules.pop("ddgs", None)
if saved_ddgs_exc is not None:
    sys.modules["ddgs.exceptions"] = saved_ddgs_exc
else:
    sys.modules.pop("ddgs.exceptions", None)

# 3. searxng provider
class _FakeSearxngResp:
    def __init__(self, status_code=200, json_data=None, ok=True):
        self.status_code = status_code
        self._json_data = json_data
        self.ok = ok
    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

saved_get = g.requests.get
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "searxng"
os.environ["SMOLPAW_SEARCH_URL"] = "http://searxng.local:8080"

# JSON mapping
g.requests.get = lambda *a, **k: _FakeSearxngResp(
    200,
    {"results": [
        {"title": "SearX 1", "url": "https://searx.example/1", "content": "Content 1"},
        {"title": "SearX 2", "url": "https://searx.example/2", "snippet": "Snippet 2"},
    ]}
)
sx_mapped = g._search_searxng("searx test", 5)
check("searxng maps JSON results to title, url, snippet",
      len(sx_mapped) == 2 and sx_mapped[0]["title"] == "SearX 1" and sx_mapped[0]["url"] == "https://searx.example/1"
      and sx_mapped[0]["snippet"] == "Content 1" and sx_mapped[1]["snippet"] == "Snippet 2")

# 403 "JSON format not enabled" case
g.requests.get = lambda *a, **k: _FakeSearxngResp(403, ok=False)
g.reset_search_count()
sx_403_err = g.web_search("403 test")
check("searxng 403 returns ERROR naming the fix (search: formats: in settings.yml)",
      sx_403_err.startswith("ERROR:") and "403" in sx_403_err and "settings.yml" in sx_403_err and "search: formats:" in sx_403_err)

# connection error
def _raise_conn_err(*a, **k):
    raise g.requests.RequestException("SearXNG unreachable")
g.requests.get = _raise_conn_err
g.reset_search_count()
sx_conn_err = g.web_search("conn test")
check("searxng connection error returns ERROR telling not to retry",
      sx_conn_err.startswith("ERROR:") and "SearXNG unreachable" in sx_conn_err and "Do not retry" in sx_conn_err)

# malformed JSON
g.requests.get = lambda *a, **k: _FakeSearxngResp(200, json_data=ValueError("bad json syntax"))
g.reset_search_count()
sx_json_err = g.web_search("malformed json")
check("searxng malformed JSON returns ERROR",
      sx_json_err.startswith("ERROR:") and "malformed JSON" in sx_json_err)

# restore requests.get and unset SMOLPAW_SEARCH_URL
g.requests.get = saved_get
os.environ.pop("SMOLPAW_SEARCH_URL", None)

# 4. Selection
# unset gives ddgs
os.environ.pop("SMOLPAW_SEARCH_PROVIDER", None)
check("unset SMOLPAW_SEARCH_PROVIDER gives ddgs",
      g._configure_search_provider() == "ddgs" and g.web_search in g.GENERIC_TOOLS)

# none removes the tool
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "none"
check("SMOLPAW_SEARCH_PROVIDER=none removes web_search from GENERIC_TOOLS",
      g._configure_search_provider() == "none" and g.web_search not in g.GENERIC_TOOLS)

# searxng works with URL set
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "searxng"
check("SMOLPAW_SEARCH_PROVIDER=searxng configures provider and keeps tool in GENERIC_TOOLS",
      g._configure_search_provider() == "searxng" and g.web_search in g.GENERIC_TOOLS)

# unknown value is a clear startup error
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "unknown_engine"
startup_err_raised = False
try:
    g._configure_search_provider()
except ValueError as exc:
    startup_err_raised = "ddgs" in str(exc) and "searxng" in str(exc) and "none" in str(exc)
check("unknown SMOLPAW_SEARCH_PROVIDER raises startup error naming valid choices", startup_err_raised)

# restore SMOLPAW_SEARCH_PROVIDER
if saved_provider is not None:
    os.environ["SMOLPAW_SEARCH_PROVIDER"] = saved_provider
    g._configure_search_provider()
else:
    os.environ.pop("SMOLPAW_SEARCH_PROVIDER", None)
    g._configure_search_provider()

import subprocess as _sp  # noqa: E402
# The setting is read after .env is loaded: import first, set the variable afterwards, then build_agent()
_code = (
    "import os, generic_tools as g\n"
    "from agent import build_agent\n"
    "def names(): return [t.name for t in build_agent('m', 'tool', 3, 'generic', 'lmstudio').tools.values()]\n"
    "os.environ['SMOLPAW_SEARCH_PROVIDER'] = 'none'; a = 'web_search' in names()\n"
    "os.environ['SMOLPAW_SEARCH_PROVIDER'] = 'ddgs'; b = 'web_search' in names()\n"
    "os.environ['SMOLPAW_SEARCH_PROVIDER'] = 'bogus'; c = 'web_search' in names()\n"
    "print(a, b, c)"
)
_env = {k: v for k, v in os.environ.items() if k != "SMOLPAW_SEARCH_PROVIDER"}
_r2 = _sp.run([sys.executable, "-c", _code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
              env=_env)
check("build_agent applies SMOLPAW_SEARCH_PROVIDER set after import (none removes, ddgs adds, bad value falls back)",
      _r2.stdout.strip() == "False True True" and "Falling back to ddgs" in _r2.stderr)

# An invalid provider in the environment warns and falls back to ddgs at import (does not crash)
import subprocess as _sp
_r = _sp.run([sys.executable, "-c", "import generic_tools as g; print(g.web_search in g.GENERIC_TOOLS)"],
             cwd=str(Path(__file__).parent.parent), capture_output=True, text=True,
             env={**os.environ, "SMOLPAW_SEARCH_PROVIDER": "typo_engine"})
check("invalid SMOLPAW_SEARCH_PROVIDER at import warns and keeps web_search on ddgs",
      _r.returncode == 0 and "WARNING" in _r.stderr and "typo_engine" in _r.stderr and _r.stdout.strip() == "True")

# The per-request search cap resets when a request's run log starts, and ACTIONS.clear() no longer does it
g.SEARCH_PROVIDERS["fake_reset"] = lambda q, n: [{"title": "R", "url": "https://r.example", "snippet": "s"}]
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "fake_reset"
g.reset_search_count()
for _i in range(3):
    g.web_search(f"q{_i}")
g.ACTIONS.clear()
check("ACTIONS.clear() does not reset the search cap", "limit reached" in g.web_search("q3").lower())
_saved_logdir = g.LOG_DIR
g.LOG_DIR = Path(tempfile.mkdtemp())
g.start_log("m", "next request")
g.LOG_DIR = _saved_logdir
check("start_log() resets the search cap for a new request", "limit reached" not in g.web_search("q4").lower())
g.SEARCH_PROVIDERS.pop("fake_reset", None)

# Parallel searches cannot slip past the cap
import threading as _th  # noqa: E402
g.SEARCH_PROVIDERS["fake_par"] = lambda q, n: (time.sleep(0.05), [{"title": "P", "url": "https://p.example", "snippet": "s"}])[1]
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "fake_par"
g.reset_search_count()
_outs: list[str] = []
_ts = [_th.Thread(target=lambda: _outs.append(g.web_search("par"))) for _ in range(10)]
[x.start() for x in _ts]
[x.join() for x in _ts]
check("10 parallel searches let exactly 3 through", sum("limit reached" not in o.lower() for o in _outs) == 3)
g.SEARCH_PROVIDERS.pop("fake_par", None)

# Long snippets are clipped
g.SEARCH_PROVIDERS["long_fake"] = lambda q, n: [{"title": "T", "url": "https://e.com", "snippet": "word " * 500}]
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "long_fake"
g.reset_search_count()
check("web_search clips each snippet to 300 characters", len(g.web_search("long").splitlines()[2].strip()) <= 300)

# 5. 3-searches-per-request cap and its reset
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "fake"
g.reset_search_count()
r1 = g.web_search("query 1")
r2 = g.web_search("query 2")
r3 = g.web_search("query 3")
r4 = g.web_search("query 4")
check("first 3 searches succeed", "1. Title 1" in r1 and "1. Title 1" in r2 and "1. Title 1" in r3)
check("4th search hit the 3-search limit", "limit reached" in r4.lower() and "maximum 3 searches" in r4)

# reset_search_count() gives a new allowance
g.reset_search_count()
r5 = g.web_search("query after reset")
check("reset_search_count() allows new searches", "1. Title 1" in r5)

# 6. A provider added to the dict works with no other code changes
def _custom_provider(query: str, limit: int) -> list[dict]:
    return [{"title": "Custom Result", "url": "https://custom.example", "snippet": "Custom snippet for " + query}]

g.SEARCH_PROVIDERS["my_custom"] = _custom_provider
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "my_custom"
g.reset_search_count()
custom_res = g.web_search("pluggable test")
check("provider added to SEARCH_PROVIDERS works with no other code changes",
      "Custom Result" in custom_res and "https://custom.example" in custom_res and "Custom snippet for pluggable test" in custom_res)

# Clean up fake providers and restore
g.SEARCH_PROVIDERS.pop("fake", None)
g.SEARCH_PROVIDERS.pop("secret_fake", None)
g.SEARCH_PROVIDERS.pop("my_custom", None)
if saved_provider is not None:
    os.environ["SMOLPAW_SEARCH_PROVIDER"] = saved_provider
    g._configure_search_provider()
else:
    os.environ.pop("SMOLPAW_SEARCH_PROVIDER", None)
    g._configure_search_provider()
g.reset_search_count()

# write verification (#19): a follow-up GET checks what a write actually did, beyond its status code
_real_get = g.requests.get


class _VResp:
    def __init__(self, status, json_body=None, headers=None):
        self.status_code, self.headers = status, {"content-type": "application/json", **(headers or {})}
        self._json = json_body
        self.text = g.json.dumps(json_body) if json_body is not None else ""

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


# POST, verified via Location header, fields match
g.requests.request = lambda *a, **k: _VResp(201, {"id": 5, "monitored": True}, {"Location": "http://x/items/5"})
g.requests.get = lambda *a, **k: _VResp(200, {"id": 5, "monitored": True})
answer["value"] = True
res = g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST verified via Location, fields match", "verified: now exists, fields match" in g.ACTIONS[-1])

# POST, verified via an id in the body (no Location), with a field mismatch
g.requests.request = lambda *a, **k: _VResp(201, {"id": 7, "monitored": True})
g.requests.get = lambda *a, **k: _VResp(200, {"id": 7, "monitored": False})
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST verified via id, mismatch reported",
      "mismatched: monitored: sent True, got False" in g.ACTIONS[-1])

# POST with nothing to verify against
g.requests.request = lambda *a, **k: _VResp(201, {"ok": True})
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST with no Location/id says so", "not verified: no Location header or id" in g.ACTIONS[-1])

# PUT, fields match
g.requests.request = lambda *a, **k: _VResp(200)
g.requests.get = lambda *a, **k: _VResp(200, {"monitored": True})
g.http_request("PUT", "http://x/items/5", '{"monitored": true}')
check("PUT verified, fields match", "verified: fields match" in g.ACTIONS[-1])

# PUT, fields do not match (the write did not really take)
g.requests.get = lambda *a, **k: _VResp(200, {"monitored": False})
g.http_request("PUT", "http://x/items/5", '{"monitored": true}')
check("PUT mismatch reported", "mismatched: monitored: sent True, got False" in g.ACTIONS[-1])

# DELETE, verified gone
g.requests.request = lambda *a, **k: _VResp(204)
g.requests.get = lambda *a, **k: _VResp(404)
g.http_request("DELETE", "http://x/items/5")
check("DELETE verified gone", "verified: now returns 404" in g.ACTIONS[-1])

# DELETE, NOT actually gone — the loud case this is meant to catch
g.requests.get = lambda *a, **k: _VResp(200, {"id": 5})
g.http_request("DELETE", "http://x/items/5")
check("DELETE still present is flagged as a WARNING",
      "WARNING" in g.ACTIONS[-1] and "may not actually be deleted" in g.ACTIONS[-1])

# a failed write (non-2xx) is never verified; behaviour is unchanged
g.requests.request = lambda *a, **k: _VResp(400)
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("a failed write is not verified", g.ACTIONS[-1] == "POST http://x/items -> HTTP 400")

# a verification GET that itself fails is reported, not raised
g.requests.request = lambda *a, **k: _VResp(201, {"id": 9})
def _raise(*a, **k):
    raise g.requests.RequestException("boom")
g.requests.get = _raise
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("a verification failure is reported, not raised", "could not verify: RequestException" in g.ACTIONS[-1])

g.requests.request = _real_request
g.requests.get = _real_get
answer["value"] = False
prompts.clear()  # the approvals above aren't what later "was anything asked?" checks care about

# last tool result is remembered for the step-cap fallback
g.LAST_RESULT = ""
g.run_shell("ls")
check("last tool result remembered", g.LAST_RESULT.startswith("run_shell:"))

# short skills are inlined into the prompt, long ones only listed
(g.SKILLS / "short.md").write_text("# Short\nuse thing")
(g.SKILLS / "long.md").write_text("# Long\n" + "x" * 3000)
ins = g.build_instructions()
check("short skill inlined", "use thing" in ins)
check("long skill listed not inlined", "Longer skills" in ins and "xxxxxxxxxx" not in ins)

# key user facts in notes.md (#25): user preferences inlined into prompt, ignored by services()
saved_notes = g.NOTES
g.NOTES = tmp / "facts-notes.md"
g.NOTES.write_text("""# SmolPaw notes

## User facts
- timezone: Europe/London
- units: metric (Celsius, km)
- owner: Martin

## Services
- mysvc: https://example.com/api | key_env=MY_KEY
""")
facts_ins = g.build_instructions()
check("user facts inlined in prompt instructions", "timezone: Europe/London" in facts_ins and "units: metric" in facts_ins)
parsed_svcs = g.services()
check("services() parses valid service URL", "mysvc" in parsed_svcs and parsed_svcs["mysvc"]["url"] == "https://example.com/api")
check("services() ignores user facts lines", "timezone" not in parsed_svcs and "units" not in parsed_svcs and "owner" not in parsed_svcs)
g.NOTES = saved_notes
# The example "## User facts" block's token cost was measured against Qwen 3.5 9B's own tokenizer
# (Ollama /api/generate, raw prompt, no chat template): 27 tokens, not a char-count/4 guess. See
# CHANGELOG.md. No test asserts a token *count* here: nothing in this file has access to a real
# tokenizer, and a char-count proxy (as #27's schema-size check earlier in this file does) tests
# string length, not tokens -- it would pass or fail for reasons unrelated to what it claims to check.

# secrets
if os.environ.get("RADARR_URL") and os.environ.get("RADARR_API_KEY"):
    g.NOTES = tmp / "notes.md"
    g.NOTES.write_text(f"- radarr: {os.environ['RADARR_URL']} | key_env=RADARR_API_KEY | header=X-Api-Key\n")
    key = os.environ["RADARR_API_KEY"]
    res = g.http_request("GET", f"{os.environ['RADARR_URL']}/api/v3/system/status")
    check("key injected for listed host (HTTP 200)", res.startswith("HTTP 200") and not asked())
    check("key not in output", key not in res)
    check("redaction removes key from any text", key not in g._redact(f"key is {key}") and "[REDACTED]" in g._redact(f"key is {key}"))
    check("services parsed", "radarr" in g.services())
    other = g._auth_headers("http://example.com/api")
    check("no key sent to unlisted host", other == {})
else:
    print("SKIP  live Radarr tests (RADARR_URL/RADARR_API_KEY unset)")

# backend selection (no server needed: building the model makes no request)
from smolagents import OpenAIServerModel  # noqa: E402

from agent import build_agent  # noqa: E402

lm = build_agent(toolset="generic").model
check("default backend is LM Studio", lm.client_kwargs["base_url"] == "http://127.0.0.1:1234/v1"
      and lm.model_id == "ternary-bonsai-8b-mlx")
ol = build_agent(toolset="generic", backend="ollama").model
check("ollama backend uses port 11434 and its default model",
      ol.client_kwargs["base_url"] == "http://127.0.0.1:11434/v1" and ol.model_id == "qwen3.5:9b")
check("explicit model overrides backend default",
      build_agent("gemma4:e4b", toolset="generic", backend="ollama").model.model_id == "gemma4:e4b")

# web approvals: the browser answers the same prompts; only a correct token and a real boolean approve
import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import requests  # noqa: E402

import web  # noqa: E402


def run_in_thread(fn, *args) -> dict:
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(value=fn(*args)), daemon=True)
    t.start()
    out["thread"] = t
    return out


def wait_pending(approvals: web.Approvals) -> dict | None:
    for _ in range(100):
        if approvals.pending:
            return approvals.pending
        time.sleep(0.02)
    return None


with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
token = "test-token-123456"
appr = web.Approvals(timeout=5)
srv = web.serve("127.0.0.1", port, token, appr)
base = f"http://127.0.0.1:{port}"
hdr = {"X-Token": token}
http = requests.Session()  # earlier tests replace requests.get with a fake

check("web page refuses a missing token", http.get(f"{base}/api/state", timeout=5).status_code == 403)
check("web page refuses a wrong token",
      http.get(f"{base}/api/state", headers={"X-Token": "nope"}, timeout=5).status_code == 403)

job = run_in_thread(appr.confirm, "Run shell command?\n  rm x")
p = wait_pending(appr)
check("web prompt is shown as pending", p is not None and p["kind"] == "confirm" and "rm x" in p["text"])
bad = http.post(f"{base}/api/answer", json={"id": p["id"], "value": True},
                headers={"X-Token": "nope"}, timeout=5)
check("wrong token cannot answer", bad.status_code == 403 and appr.pending is not None)
s_yes = http.post(f"{base}/api/answer", json={"id": p["id"], "value": "yes"}, headers=hdr, timeout=5)
check("string 'yes' does not approve", s_yes.status_code == 409 and appr.pending is not None)
stale = http.post(f"{base}/api/answer", json={"id": p["id"] + 1, "value": True}, headers=hdr, timeout=5)
check("stale prompt id is refused", stale.status_code == 409 and appr.pending is not None)
ok = http.post(f"{base}/api/answer", json={"id": p["id"], "value": True}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser yes approves", ok.status_code == 200 and job.get("value") is True)

job = run_in_thread(appr.confirm, "Write file?")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": False}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser no declines", job.get("value") is False)

quick = web.Approvals(timeout=0.2)
check("unanswered confirm times out as no", quick.confirm("Run?") is False)
check("unanswered question times out with a no-answer note", quick.ask("Which one?") == web.NO_ANSWER)

job = run_in_thread(appr.ask, "Which host?")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": "the NAS"}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser reply reaches ask_user", job.get("value") == "the NAS")

saved_notes = g.NOTES
g.NOTES = tmp / "web-notes.md"
g.NOTES.write_text("- svc: http://example.com | key_env=SMOLPAW_TEST_WEB_KEY | header=X-Api-Key\n")
os.environ["SMOLPAW_TEST_WEB_KEY"] = "s3cret-value-for-test"
job = run_in_thread(appr.confirm, "POST with key s3cret-value-for-test?")
p = wait_pending(appr)
g._show("$ echo s3cret-value-for-test", "listing")
state = http.get(f"{base}/api/state", headers=hdr, timeout=5).json()
check("api/state carries the shown tool output, label redacted",
      (state.get("tool_output") or {}).get("label") == "$ echo [REDACTED]" and state["tool_output"]["text"] == "listing")
check("keys are redacted on the web page",
      "s3cret-value-for-test" not in json.dumps(state) and "[REDACTED]" in p["text"])
appr.cancel()
job["thread"].join(5)
check("stop declines the pending prompt", job.get("value") is False)
g.NOTES = saved_notes
del os.environ["SMOLPAW_TEST_WEB_KEY"]

appr.install()
g.ACTIONS.clear()
job = run_in_thread(g._approved, "Run shell command?\n  touch y")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": False}, headers=hdr, timeout=5)
job["thread"].join(5)
check("web decline is recorded by the harness", job.get("value") is False and g.ACTIONS[-1].startswith("declined"))

# read-only files endpoint (#38)
saved_notes, saved_skills, saved_memory = g.NOTES, g.SKILLS, g.MEMORY

# 1. returns contents of temp files
test_notes = tmp / "files-view-notes.md"
test_notes.write_text("- svc: http://example.com\nUser prefers dark mode\n")
test_skills = tmp / "files-view-skills"
test_skills.mkdir(exist_ok=True)
(test_skills / "radarr.md").write_text("# Radarr\nskill text here\n")
(test_skills / "sonarr.md").write_text("# Sonarr\nsonarr skill text\n")
test_mem = tmp / "files-view-memory.md"
test_mem.write_text("# Memory\n- fact 1\n- fact 2\n")

g.NOTES = test_notes
g.SKILLS = test_skills
g.MEMORY = test_mem

res_files = http.get(f"{base}/api/files", headers=hdr, timeout=5)
check("/api/files returns 200 with valid token", res_files.status_code == 200)
files_data = res_files.json()
check("with temp files, endpoint returns their contents",
      files_data["notes"] == test_notes.read_text()
      and len(files_data["skills"]) == 2
      and files_data["skills"][0] == {"name": "radarr", "text": (test_skills / "radarr.md").read_text()}
      and files_data["skills"][1] == {"name": "sonarr", "text": (test_skills / "sonarr.md").read_text()}
      and files_data["memory"] == test_mem.read_text())

# 2. wrong or missing token gets 403
check("/api/files refuses a missing token with 403",
      http.get(f"{base}/api/files", timeout=5).status_code == 403)
check("/api/files refuses a wrong token with 403",
      http.get(f"{base}/api/files", headers={"X-Token": "wrong"}, timeout=5).status_code == 403)

# 3. missing files give empty values, not a 500
g.NOTES = tmp / "missing-notes.md"
g.SKILLS = tmp / "missing-skills"
g.MEMORY = tmp / "missing-memory.md"
res_missing = http.get(f"{base}/api/files", headers=hdr, timeout=5)
check("missing files return 200 not 500", res_missing.status_code == 200)
check("missing files return empty strings and empty list",
      res_missing.json() == {"notes": "", "skills": [], "memory": ""})

# 4. secret value from key_env comes back [REDACTED]
sec_notes = tmp / "sec-notes.md"
sec_notes.write_text("- radarr: http://example.com:7878 | key_env=TEST_FILES_KEY\nSecret is private-key-xyz123\n")
os.environ["TEST_FILES_KEY"] = "private-key-xyz123"
g.NOTES = sec_notes
sec_res = http.get(f"{base}/api/files", headers=hdr, timeout=5).json()
check("secret value from key_env in notes comes back as [REDACTED]",
      "private-key-xyz123" not in json.dumps(sec_res) and "[REDACTED]" in sec_res["notes"])
del os.environ["TEST_FILES_KEY"]

# 5. query string (?path=../.env, ?name=../x) returns exactly the same fixed things
g.NOTES = test_notes
g.SKILLS = test_skills
g.MEMORY = test_mem
baseline = http.get(f"{base}/api/files", headers=hdr, timeout=5).json()
q_path = http.get(f"{base}/api/files?path=../.env", headers=hdr, timeout=5).json()
q_name = http.get(f"{base}/api/files?name=../x", headers=hdr, timeout=5).json()
check("query string like ?path=../.env returns exactly the fixed files",
      q_path == baseline and q_name == baseline)

# 6. POST to /api/files returns 404
check("POST to /api/files returns 404",
      http.post(f"{base}/api/files", json={}, headers=hdr, timeout=5).status_code == 404)
_page_html = http.get(f"{base}/?t={token}", timeout=5).text
check("web page puts the read-only files inside Settings", 'id="fnotes"' in _page_html and 'id="filescard"' not in _page_html)

g.NOTES, g.SKILLS, g.MEMORY = saved_notes, saved_skills, saved_memory

# recent runs and run summary (#39)
saved_log_dir = g.LOG_DIR
fake_log_dir = tmp / "fake_logs"
fake_log_dir.mkdir(exist_ok=True)
g.LOG_DIR = fake_log_dir

f_finished = fake_log_dir / "20261025-100000-model_a.jsonl"
f_finished.write_text("\n".join([
    json.dumps({"t": "2026-10-25T10:00:00", "kind": "start", "model": "model_a", "prompt": "do something"}),
    json.dumps({"t": "2026-10-25T10:00:04", "kind": "shell", "command": "ls", "read_only": True, "exit": 0}),
    json.dumps({"t": "2026-10-25T10:00:07", "kind": "http", "method": "GET", "url": "http://x", "status": 200}),
    json.dumps({"t": "2026-10-25T10:00:12", "kind": "final", "answer": "done",
                "actions": ["declined: write notes.txt"], "input_tokens": 12345, "output_tokens": 678}),
]) + "\n")

f_unfinished = fake_log_dir / "20261025-110000-model_b.jsonl"
f_unfinished.write_text("\n".join([
    json.dumps({"t": "2026-10-25T11:00:00", "kind": "start", "model": "model_b", "prompt": "unfinished task"}),
    json.dumps({"t": "2026-10-25T11:00:05", "kind": "fetch_page", "url": "http://x", "query": "q", "hits": 1}),
]) + "\n")

f_malformed = fake_log_dir / "20261025-120000-broken.jsonl"
f_malformed.write_text("corrupted json {bad\n")

# 1. /api/runs returns newest first, correct summaries, skips malformed file
res_runs = http.get(f"{base}/api/runs", headers=hdr, timeout=5)
check("/api/runs returns 200 with valid token", res_runs.status_code == 200)
runs = res_runs.json()
check("malformed log file is skipped and valid runs returned", len(runs) == 2)
check("runs list is newest first",
      runs[0]["id"] == "20261025-110000-model_b.jsonl" and runs[1]["id"] == "20261025-100000-model_a.jsonl")
check("unfinished run summary has model, 'unfinished', and tool count",
      "model_b" in runs[0]["summary"] and "unfinished" in runs[0]["summary"] and "1 tool call" in runs[0]["summary"])
check("run titles come from the prompt's first sentence",
      runs[1]["title"] == "do something" and runs[0]["title"] == "unfinished task")
_long = fake_log_dir / "20261025-130000-long.jsonl"
_long.write_text(json.dumps({"t": "2026-10-25T13:00:00", "kind": "start", "model": "m",
                             "prompt": "Check the queue.  Then " + "x" * 200}) + "\n")
_long2 = fake_log_dir / "20261025-140000-long2.jsonl"
_long2.write_text(json.dumps({"t": "2026-10-25T14:00:00", "kind": "start", "model": "m",
                              "prompt": "w" * 200}) + "\n")
_titles = {r["id"]: r["title"] for r in web._list_runs()}
check("title stops at the first sentence", _titles[_long.name] == "Check the queue.")
check("long title is clipped to 80 characters with an ellipsis",
      len(_titles[_long2.name]) == 80 and _titles[_long2.name].endswith("\u2026"))
_long.unlink(); _long2.unlink()
check("finished run summary has model, elapsed seconds, and tool count",
      "model_a" in runs[1]["summary"] and "12s" in runs[1]["summary"] and "2 tool calls" in runs[1]["summary"]
      and "12,345 in / 678 out tokens" in runs[1]["summary"] and "tokens" not in runs[0]["summary"])

# 2. /api/run_feed returns lines for a real id, 404 for unknown
r_feed = http.get(f"{base}/api/run_feed?id={f_finished.name}", headers=hdr, timeout=5)
check("/api/run_feed returns 200 for real id", r_feed.status_code == 200)
feed_lines = r_feed.json()
check("/api/run_feed returns formatted lines",
      any("$ ls" in fl for fl in feed_lines) and any("GET http://x" in fl for fl in feed_lines))
check("/api/run_feed returns 404 for unknown id",
      http.get(f"{base}/api/run_feed?id=unknown.jsonl", headers=hdr, timeout=5).status_code == 404)

# /api/run_detail: what a past run asked and answered, for the sidebar chat view
detail = http.get(f"{base}/api/run_detail?id={f_finished.name}", headers=hdr, timeout=5).json()
check("/api/run_detail returns prompt, answer, outcome and feed for a finished run",
      detail["prompt"] == "do something" and detail["answer"] == "done" and detail["finished"]
      and detail["outcome"].startswith("[Harness says]") and any("$ ls" in fl for fl in detail["feed"]))
f_clean = fake_log_dir / "20261025-130000-model_c.jsonl"
f_clean.write_text("\n".join([
    json.dumps({"t": "2026-10-25T13:00:00", "kind": "start", "model": "model_c", "prompt": "just asking"}),
    json.dumps({"t": "2026-10-25T13:00:03", "kind": "final", "answer": "fine", "actions": []}),
]) + "\n")
detail_c = http.get(f"{base}/api/run_detail?id={f_clean.name}", headers=hdr, timeout=5).json()
check("/api/run_detail shows no [Harness says] block for a run that changed nothing",
      detail_c["finished"] and detail_c["outcome"] == "" and detail_c["answer"] == "fine")
f_clean.unlink()
detail_u = http.get(f"{base}/api/run_detail?id={f_unfinished.name}", headers=hdr, timeout=5).json()
check("/api/run_detail marks an unfinished run and gives no answer",
      detail_u["prompt"] == "unfinished task" and not detail_u["finished"] and detail_u["answer"] == "")
check("/api/run_detail returns 404 for unknown id and for traversal",
      http.get(f"{base}/api/run_detail?id=unknown.jsonl", headers=hdr, timeout=5).status_code == 404
      and http.get(f"{base}/api/run_detail?id=../x", headers=hdr, timeout=5).status_code == 404)
check("/api/run_detail refuses a missing token with 403",
      http.get(f"{base}/api/run_detail?id={f_finished.name}", timeout=5).status_code == 403)

# 3. Path traversal attempts return 404
check("/api/run_feed returns 404 for ?id=../x",
      http.get(f"{base}/api/run_feed?id=../x", headers=hdr, timeout=5).status_code == 404)
check("/api/run_feed returns 404 for absolute path",
      http.get(f"{base}/api/run_feed?id=/etc/passwd", headers=hdr, timeout=5).status_code == 404)
check("/api/run_feed returns 404 for id with slash",
      http.get(f"{base}/api/run_feed?id=sub/file.jsonl", headers=hdr, timeout=5).status_code == 404)

# 4. Wrong or missing token gets 403 on both routes; POST gets 404
check("/api/runs refuses missing token with 403",
      http.get(f"{base}/api/runs", timeout=5).status_code == 403)
check("/api/runs refuses wrong token with 403",
      http.get(f"{base}/api/runs", headers={"X-Token": "bad"}, timeout=5).status_code == 403)
check("/api/run_feed refuses missing token with 403",
      http.get(f"{base}/api/run_feed?id={f_finished.name}", timeout=5).status_code == 403)
check("/api/run_feed refuses wrong token with 403",
      http.get(f"{base}/api/run_feed?id={f_finished.name}", headers={"X-Token": "bad"}, timeout=5).status_code == 403)
check("POST to /api/runs returns 404",
      http.post(f"{base}/api/runs", json={}, headers=hdr, timeout=5).status_code == 404)
check("POST to /api/run_feed returns 404",
      http.post(f"{base}/api/run_feed?id={f_finished.name}", json={}, headers=hdr, timeout=5).status_code == 404)

# 5. Secret written into log file comes back masked
saved_notes = g.NOTES
g.NOTES = tmp / "notes_for_run_secret.md"
g.NOTES.write_text("- svc: http://example.com | key_env=MY_RUN_SECRET\n")
os.environ["MY_RUN_SECRET"] = "super-secret-token-777"
f_secret = fake_log_dir / "20261025-130000-secret.jsonl"
f_secret.write_text("\n".join([
    json.dumps({"t": "2026-10-25T13:00:00", "kind": "start", "model": "m", "prompt": "p"}),
    json.dumps({"t": "2026-10-25T13:00:01", "kind": "shell", "command": "echo super-secret-token-777", "read_only": False, "exit": 0}),
]) + "\n")
sec_feed = http.get(f"{base}/api/run_feed?id={f_secret.name}", headers=hdr, timeout=5).json()
check("secret in log file comes back masked in run_feed",
      "super-secret-token-777" not in json.dumps(sec_feed) and "[REDACTED]" in json.dumps(sec_feed))
del os.environ["MY_RUN_SECRET"]
g.NOTES = saved_notes

# 6. Current run summary in /api/state and web page has the Recents list
saved_curr_log = g._log_file
g._log_file = f_finished
state_with_summary = http.get(f"{base}/api/state", headers=hdr, timeout=5).json()
check("/api/state contains summary line for current run",
      "model_a" in state_with_summary.get("summary", "") and "12s" in state_with_summary.get("summary", ""))
check("/api/state names the current run's log file as run_id", state_with_summary.get("run_id") == f_finished.name)
g._log_file = None
check("/api/state run_id is empty before any run has started",
      http.get(f"{base}/api/state", headers=hdr, timeout=5).json().get("run_id") == "")
g._log_file = saved_curr_log
_page = http.get(f"{base}/?t={token}", timeout=5).text
check("page returns to the live feed when the run changes and reloads the list only when it changes",
      "s.run_id !== lastRunId) selectedRunId = null" in _page and "key !== runsKey" in _page
      and _page.count("loadRuns();") == 1)  # only the gated call, not an unconditional one per refresh

_page = http.get(f"{base}/?t={token}", timeout=5).text
check("web page has the Recents list and New chat button in the left panel",
      '<div class="recents">' in _page and 'id="runslist"' in _page and 'id="newchat"' in _page
      and 'id="recentcard"' not in _page)

g.LOG_DIR = saved_log_dir

g.CONFIRM = fake_confirm
srv.shutdown()

# native tool-call history (#14): smolagents' own calls go back as real tool_calls, model text stays text
from smolagents.memory import ActionStep, ToolCall  # noqa: E402
from smolagents.models import ChatMessage, MessageRole  # noqa: E402
from smolagents.monitoring import Timing  # noqa: E402

from agent import NativeHistoryModel  # noqa: E402

_t = Timing(0.0, 1.0)
_steps = [
    ActionStep(step_number=1, timing=_t, model_output="",
               tool_calls=[ToolCall("http_request", {"method": "GET", "url": "http://x/"}, "call_a")],
               observations="HTTP 200\nok"),
    ActionStep(step_number=2, timing=_t, model_output="Calling tools:\n[{'id': 'fake', 'function': {}}]",
               error=ValueError("could not parse a tool call")),
    ActionStep(step_number=3, timing=_t, model_output="",
               tool_calls=[ToolCall("read_file", {"path": "a"}, "call_b"),
                           ToolCall("read_file", {"path": "b"}, "call_c")],
               observations="a and b"),
]
_msgs = [ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": "task"}])]
for _s in _steps:
    _msgs += _s.to_messages()
_native = NativeHistoryModel(model_id="x", api_base="http://127.0.0.1:9/v1", api_key="k")
hist = _native._prepare_completion_kwargs(_msgs, tools_to_call_from=g.GENERIC_TOOLS)["messages"]
calls = [m for m in hist if m.get("tool_calls")]
check("earlier tool calls are sent as native tool_calls",
      [c["id"] for m in calls for c in m["tool_calls"]] == ["call_a", "call_b", "call_c"]
      and json.loads(calls[0]["tool_calls"][0]["function"]["arguments"]) == {"method": "GET", "url": "http://x/"})
check("tool results are tool messages with matching ids",
      [(m["tool_call_id"], m["content"]) for m in hist if m["role"] == "tool"]
      == [("call_a", "HTTP 200\nok"), ("call_b", "a and b"), ("call_c", "(see the result above)")])
check("no 'Calling tools:' text left from smolagents' own calls",
      sum("Calling tools:" in json.dumps(m) for m in hist) == 1)  # only the model's own invalid text remains
check("model-written tool-call text is not turned into a real call",
      not any(c["id"] == "fake" for m in calls for c in m["tool_calls"]))
check("no internal markers reach the server", "smolpaw-tool" not in json.dumps(hist))
_plain = OpenAIServerModel(model_id="x", api_base="http://127.0.0.1:9/v1", api_key="k")
check("text history is still available for comparison",
      not any(m.get("tool_calls") for m in _plain._prepare_completion_kwargs(_msgs)["messages"]))

# stall detection (#19): the harness stops a run that repeats the same failing call
from agent import STALL_WINDOW, check_stall  # noqa: E402


class _FakeAgent:
    def __init__(self, steps):
        self.memory = type("M", (), {"steps": steps})()
        self.stall_reason = None
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


def _step(tool_calls, observations=None, error=None):
    return ActionStep(step_number=1, timing=_t, model_output="", tool_calls=tool_calls,
                      observations=observations, error=error)


same_call = [ToolCall("http_request", {"method": "POST", "url": "http://x/add"}, f"c{i}") for i in range(5)]
failing = [_step([c], observations="HTTP 400\nbad request") for c in same_call]
a = _FakeAgent(failing[:STALL_WINDOW - 1])
check_stall(a.memory.steps[-1], a)
check("no stall flagged before the window fills", not a.interrupted)
a = _FakeAgent(failing[:STALL_WINDOW])
check_stall(a.memory.steps[-1], a)
check("same call failing with HTTP 4xx repeatedly is a stall", a.interrupted and a.stall_reason)
a = _FakeAgent([_step([ToolCall("run_shell", {"cmd": "echo a"}, "x")], observations="a\n")
                for _ in range(STALL_WINDOW)])
check_stall(a.memory.steps[-1], a)
check("repeating a succeeding call is not a stall", not a.interrupted)
a = _FakeAgent([_step([ToolCall("read_file", {"path": f"f{i}"}, "x")], observations="ERROR: no such file")
                for i in range(STALL_WINDOW)])
check_stall(a.memory.steps[-1], a)
check("different arguments each time is not a stall", not a.interrupted)
a = _FakeAgent(failing[:STALL_WINDOW - 1] + [_step([same_call[0]], error=ValueError("boom"))])
check_stall(a.memory.steps[-1], a)
check("a smolagents-level error counts as a failure too", a.interrupted)

# run_request() reports a stall as a finished answer, but still lets a real Stop-button interrupt through
from smolagents.utils import AgentError  # noqa: E402

from agent import run_request  # noqa: E402


class _StubAgent:
    def __init__(self, reason):
        self.memory = type("M", (), {"steps": []})()
        self._reason = reason
        self.monitor = type("Mon", (), {"get_total_token_counts": lambda s: type("T", (), {
            "input_tokens": 1500, "output_tokens": 40})()})()

    def run(self, _task):
        g.LAST_RESULT = "openapi_search: no matching endpoints."  # as a real tool call would set it
        self.stall_reason = self._reason
        raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *a: None})())


# run_request starts a run log: keep it out of the real logs/ (and the page's Recent runs list)
saved_log_dir, saved_log_file = g.LOG_DIR, g._log_file
g.LOG_DIR = tmp / "stub-run-logs"
resp, _ = run_request(_StubAgent("the same call failed 3 times in a row"), "m", "generic", "task")
_final = [json.loads(x) for x in g._log_file.read_text().splitlines()][-1]
check("the run log's final entry records the run's token totals",
      _final["kind"] == "final" and _final["input_tokens"] == 1500 and _final["output_tokens"] == 40)
check("a stall is reported as the answer, with the last tool result",
      resp.startswith("STOPPED EARLY: the same call failed 3 times in a row")
      and "no matching endpoints" in resp)
try:
    run_request(_StubAgent(None), "m", "generic", "task")
    check("a non-stall interrupt (Stop button) is not swallowed", False)
except AgentError:
    check("a non-stall interrupt (Stop button) is not swallowed", True)
g.LOG_DIR, g._log_file = saved_log_dir, saved_log_file

# the prompt start must not change between calls, or the runtime re-reads all of it (#29)
_first_call = g.build_instructions()
time.sleep(1.1)
check("build_instructions is identical across calls, so a prompt prefix cache can reuse it", g.build_instructions() == _first_call)

# export_findings.py: bundling run logs into one shareable report
sys.path.insert(0, str(Path(__file__).parent))
import export_findings as ef  # noqa: E402

_findings_dir = tmp / "efindings"
_findings_dir.mkdir()
ef.LOG_DIR = _findings_dir
_l1 = _findings_dir / "20261025-080000-demo-model.jsonl"
_l1.write_text("\n".join(json.dumps(e) for e in [
    {"t": "2026-10-25T08:00:00", "kind": "start", "model": "demo-model", "prompt": "rename the reports"},
    {"t": "2026-10-25T08:00:05", "kind": "shell", "command": "mv a.txt a-2026.txt", "read_only": False, "exit": 0},
    {"t": "2026-10-25T08:00:06", "kind": "http", "method": "GET", "url": "http://x/y", "status": 200},
    {"t": "2026-10-25T08:00:07", "kind": "fetch_page", "url": "http://x/docs", "query": "auth", "result": "2 hits"},
    {"t": "2026-10-25T08:00:07", "kind": "web_search", "query": "auth docs", "provider": "ddgs", "result": "2 hits"},
    {"t": "2026-10-25T08:00:08", "kind": "remember", "fact": "User prefers dark mode"},
    {"t": "2026-10-25T08:00:09", "kind": "recall", "query": "dark mode", "result": "1 hits"},
    {"t": "2026-10-25T08:00:09", "kind": "preflight", "method": "POST", "url": "http://x/api/v3/movie", "reason": "POST http://x/api/v3/movie requires a request body."},
    {"t": "2026-10-25T08:00:09", "kind": "read_file", "path": "a.txt", "result": "ok"},
    {"t": "2026-10-25T08:00:09", "kind": "write_file", "path": "out.txt", "chars": 42, "result": "ok"},
    {"t": "2026-10-25T08:00:09", "kind": "list_skills", "result": "3 skills"},
    {"t": "2026-10-25T08:00:09", "kind": "read_skill", "name": "radarr", "result": "ok"},
    {"t": "2026-10-25T08:00:09", "kind": "write_skill", "name": "radarr", "chars": 150, "result": "ok"},
    {"t": "2026-10-25T08:00:10", "kind": "final", "answer": "Renamed a.txt.", "actions": ["shell exit 0: mv a.txt a-2026.txt"]},
]))
_l2 = _findings_dir / "20261025-079000-no-final.jsonl"
_l2.write_text(json.dumps({"t": "2026-10-25T07:50:00", "kind": "start", "model": "x", "prompt": "unfinished"}))
report = ef.render(_l1)
check("export_findings renders the prompt and model", "rename the reports" in report and "demo-model" in report)
check("export_findings renders a refused pre-flight request", "refused before sending: `POST http://x/api/v3/movie`" in report)
check("export_findings renders a shell action", "`$ mv a.txt a-2026.txt`" in report)
check("export_findings renders an http action", "`GET http://x/y` -> 200" in report)
check("export_findings renders a fetch_page action", "`fetch_page` http://x/docs auth -> 2 hits" in report)
check("export_findings renders a web_search action", "`web_search` auth docs (ddgs) -> 2 hits" in report)
check("export_findings renders a remember action", "`remember` User prefers dark mode" in report)
check("export_findings renders a recall action", "`recall` dark mode -> 1 hits" in report)
check("export_findings renders a read_file action", "`read_file` a.txt -> ok" in report)
check("export_findings renders a write_file action", "`write_file` out.txt (42 chars) -> ok" in report)
check("export_findings renders a list_skills action", "`list_skills` -> 3 skills" in report)
check("export_findings renders a read_skill action", "`read_skill` radarr -> ok" in report)
check("export_findings renders a write_skill action", "`write_skill` radarr (150 chars) -> ok" in report)
check("export_findings renders the final answer and duration", "Renamed a.txt." in report and "10s" in report)
check("a run with no final answer is marked unfinished", "did not finish" in ef.render(_l2))
_l3 = _findings_dir / "20261025-078000-no-start.jsonl"
_l3.write_text(json.dumps({"t": "2026-10-25T07:00:00", "kind": "shell", "command": "ls", "read_only": True, "exit": 0}))
check("render returns None for a file with no start entry", ef.render(_l3) is None)
_out = tmp / "report.md"
sys_argv_saved = sys.argv
sys.argv = ["export_findings.py", "--out", str(_out)]
try:
    ef.main()
finally:
    sys.argv = sys_argv_saved
check("export_findings writes a combined report file",
      _out.exists() and "2 run(s)" in _out.read_text() and "unfinished" in _out.read_text())

# terminal_relay (--web on the CLI): the terminal can answer too, racing the web page
from agent import terminal_relay  # noqa: E402

_relay_approvals = web.Approvals(timeout=5)
_r, _w = os.pipe()
_saved_stdin = sys.stdin
sys.stdin = os.fdopen(_r)
threading.Thread(target=terminal_relay, args=(_relay_approvals,), daemon=True).start()

_confirm_result = {}
_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Do a thing?")))
_th.start()
time.sleep(0.8)  # let the relay thread see the pending prompt and start reading
os.write(_w, b"y\n")
_th.join(3)
check("terminal 'y' approves a confirm prompt", _confirm_result.get("v") is True)

_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Do another thing?")))
_th.start()
time.sleep(0.8)
os.write(_w, b"n\n")
_th.join(3)
check("terminal 'n' declines a confirm prompt", _confirm_result.get("v") is False)

_ask_result = {}
_th = threading.Thread(target=lambda: _ask_result.update(v=_relay_approvals.ask("What is the path?")))
_th.start()
time.sleep(0.8)
os.write(_w, b"/tmp/demo\n")
_th.join(3)
check("terminal free text answers an ask prompt", _ask_result.get("v") == "/tmp/demo")

# a stale terminal line arriving just after the web page already answered must not flip the result
_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Race me?")))
_th.start()
time.sleep(0.8)
_pending_id = _relay_approvals.pending["id"]
_relay_approvals.answer(_pending_id, True)  # the "web page" answers first
os.write(_w, b"n\n")  # a stale terminal line, typed before the user saw the web had already answered
_th.join(3)
check("a stale terminal answer after the web already answered does not flip the result",
      _confirm_result.get("v") is True and _relay_approvals.pending is None)

sys.stdin = _saved_stdin

# settings card (#37): backend, model, step limit and timeout change between requests
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    set_port = s.getsockname()[1]
set_appr = web.Approvals(timeout=0)
set_sess = web.Session(build_agent("m1", "tool", 5, "generic", "lmstudio"), "m1", set_appr, "lmstudio", 5)
set_srv = web.serve("127.0.0.1", set_port, token, set_appr, set_sess, {"mode": "agent"})
set_base = f"http://127.0.0.1:{set_port}"
good = {"backend": "ollama", "model": "m2", "max_steps": 7, "timeout": 30}
old_agent = set_sess.agent
st = http.get(f"{set_base}/api/state", headers=hdr, timeout=5).json()
check("state reports the current settings",
      st["backend"] == "lmstudio" and st["model"] == "m1" and st["max_steps"] == 5 and "ollama" in st["backends"])
check("settings need the token", http.post(f"{set_base}/api/settings", json=good, timeout=5).status_code == 403)
for label, bad_body in [("unknown backend", {**good, "backend": "x"}), ("empty model", {**good, "model": " "}),
                        ("zero steps", {**good, "max_steps": 0}), ("string steps", {**good, "max_steps": "7"}),
                        ("negative timeout", {**good, "timeout": -1})]:
    r = http.post(f"{set_base}/api/settings", json=bad_body, headers=hdr, timeout=5)
    check(f"settings refuse {label}", r.status_code == 400 and set_sess.model == "m1")
set_sess.status = "running"
r = http.post(f"{set_base}/api/settings", json=good, headers=hdr, timeout=5)
check("settings are refused while a request runs", r.status_code == 409 and set_sess.agent is old_agent)
set_sess.status = "idle"
r = http.post(f"{set_base}/api/settings", json=good, headers=hdr, timeout=5)
check("settings rebuild the agent between requests",
      r.status_code == 200 and set_sess.agent is not old_agent and set_sess.backend == "ollama"
      and set_sess.model == "m2" and set_sess.max_steps == 7 and set_appr.timeout == 30
      and set_sess.agent.max_steps == 7 and set_sess.agent.model.model_id == "m2")
kept = set_sess.agent
http.post(f"{set_base}/api/settings", json={**good, "timeout": 5}, headers=hdr, timeout=5)
check("a timeout-only change keeps the agent", set_sess.agent is kept and set_appr.timeout == 5)
http.post(f"{set_base}/api/settings", json={**good, "timeout": 5, "run_summaries": True}, headers=hdr, timeout=5)
check("settings toggle enables run_summaries", set_sess.run_summaries is True)
http.post(f"{set_base}/api/settings", json={**good, "timeout": 5, "run_summaries": False}, headers=hdr, timeout=5)
check("settings toggle disables run_summaries", set_sess.run_summaries is False)
r_bad = http.post(f"{set_base}/api/settings", json={**good, "timeout": 5, "run_summaries": "invalid"}, headers=hdr, timeout=5)
check("settings refuse invalid run_summaries type", r_bad.status_code == 400)
check("web page contains run summaries toggle", 'id="ssummaries"' in http.get(f"{set_base}/?t={token}", timeout=5).text)

# scheduled-run time limit in settings (#82)
st = http.get(f"{set_base}/api/state", headers=hdr, timeout=5).json()
check("/api/state includes schedule_timeout with current value",
      "schedule_timeout" in st and st["schedule_timeout"] == set_sess.schedule_timeout)

for val in (120, 30.5, 0):
    r = http.post(f"{set_base}/api/settings", json={**good, "schedule_timeout": val}, headers=hdr, timeout=5)
    st = http.get(f"{set_base}/api/state", headers=hdr, timeout=5).json()
    check(f"valid schedule_timeout {val} stored and reported",
          r.status_code == 200 and set_sess.schedule_timeout == float(val) and st.get("schedule_timeout") == float(val))

set_sess.schedule_timeout = 42.0
r = http.post(f"{set_base}/api/settings", json=good, headers=hdr, timeout=5)
check("request without schedule_timeout leaves stored value unchanged",
      r.status_code == 200 and set_sess.schedule_timeout == 42.0)

for label, bad_val in [
    ("true", True),
    ('"60"', "60"),
    ("null", None),
    ("-1", -1),
    ("nan", float("nan")),
    ("inf", float("inf")),
    ("86401", 86401),
    ("a list", [60]),
]:
    cur = set_sess.schedule_timeout
    payload = json.dumps({**good, "schedule_timeout": bad_val})
    r = http.post(f"{set_base}/api/settings", data=payload, headers={"Content-Type": "application/json", **hdr}, timeout=5)
    check(f"schedule_timeout refuses {label} with 400 and leaves value unchanged",
          r.status_code == 400 and set_sess.schedule_timeout == cur)

set_sess.status = "running"
cur = set_sess.schedule_timeout
r = http.post(f"{set_base}/api/settings", json={**good, "schedule_timeout": 120}, headers=hdr, timeout=5)
check("valid schedule_timeout refused with 409 while running and leaves value unchanged",
      r.status_code == 409 and set_sess.schedule_timeout == cur)
set_sess.status = "idle"

page_html = http.get(f"{set_base}/?t={token}", timeout=5).text
check("web page contains scheduled-run time limit input", 'id="sschedtimeout"' in page_html)
# there is no browser test harness: these only catch the wiring being deleted, not it being wrong
check("the page fills the field from /api/state", '$("sschedtimeout").value = s.schedule_timeout' in page_html)
check("the page sends the field on Apply, and omits it when the field is empty (an empty number field is 0, which would turn the limit off)",
      'schedule_timeout: $("sschedtimeout").value.trim() === "" ? undefined' in page_html)
check("models endpoint refuses an unknown backend",
      http.get(f"{set_base}/api/models?backend=x", headers=hdr, timeout=5).status_code == 404)
saved_list_models = web.list_models
web.list_models = lambda backend: ["b-model", "a-model"]
check("models endpoint returns the server's list",
      http.get(f"{set_base}/api/models?backend=ollama", headers=hdr, timeout=5).json() == ["b-model", "a-model"])
web.list_models = saved_list_models
saved_url = web.BACKENDS["ollama"]["url"]
web.BACKENDS["ollama"]["url"] = "http://127.0.0.1:1/v1"
check("an unreachable model server gives an empty list", web.list_models("ollama") == [])
web.BACKENDS["ollama"]["url"] = saved_url
set_srv.shutdown()

# deferred approvals in web view and dismiss endpoint (#81)
saved_log_dir = g.LOG_DIR
appr_log_dir = tmp / "deferred_approval_logs"
appr_log_dir.mkdir(exist_ok=True)
g.LOG_DIR = appr_log_dir

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    da_port = s.getsockname()[1]
da_appr = web.Approvals(timeout=0)
da_sess = web.Session(build_agent("m1", "tool", 5, "generic", "lmstudio"), "m1", da_appr, "lmstudio", 5)
da_srv = web.serve("127.0.0.1", da_port, token, da_appr, da_sess, {"mode": "agent"})
da_base = f"http://127.0.0.1:{da_port}"

# /api/state: field presence, empty list with no entries
da_sess.needs_approval = []
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
check("needs_approval field is present in /api/state", "needs_approval" in st)
check("with no entries needs_approval is an empty list", st["needs_approval"] == [])

# /api/state: ordered newest first
entry1 = {"id": "run1", "schedule_id": "s1", "prompt": "p1", "actions": ["a1"], "t": "2026-10-29T10:00:00"}
entry2 = {"id": "run2", "schedule_id": "s2", "prompt": "p2", "actions": ["a2"], "t": "2026-10-29T11:00:00"}
entry3 = {"id": "run3", "schedule_id": "s3", "prompt": "p3", "actions": ["a3"], "t": "2026-10-29T12:00:00"}
da_sess.needs_approval = [entry1, entry2, entry3]
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
check("needs_approval is ordered newest first", [e["id"] for e in st["needs_approval"]] == ["run3", "run2", "run1"])

# /api/state: capped at 50 entries, newest first
da_sess.needs_approval = [{"id": f"cap_run_{i}", "schedule_id": f"s_{i}", "prompt": f"p_{i}",
                           "actions": [f"a_{i}"], "t": f"2026-10-29T{i:02d}:00:00"} for i in range(60)]
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
check("api/state caps needs_approval at 50 entries newest first",
      len(st["needs_approval"]) == 50
      and st["needs_approval"][0]["id"] == "cap_run_59"
      and st["needs_approval"][-1]["id"] == "cap_run_10")

# /api/state: action strings capped at 500 characters
long_act = "x" * 600
da_sess.needs_approval = [{"id": "act_cap", "schedule_id": "s_act", "prompt": "p",
                           "actions": [long_act], "t": "2026-10-29T10:00:00"}]
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
check("action strings are capped at 500 characters",
      len(st["needs_approval"][0]["actions"][0]) == 500
      and st["needs_approval"][0]["actions"][0] == "x" * 500)

# /api/state: registered secret in prompt or action does not appear (re-redacted on the way out)
saved_notes = g.NOTES
test_sec_notes = tmp / "notes_for_da_secret.md"
test_sec_notes.write_text("- svc: http://example.com | key_env=TEST_DA_SECRET\n")
os.environ["TEST_DA_SECRET"] = "registered-secret-da-99999"
g.NOTES = test_sec_notes
da_sess.needs_approval = [{
    "id": "sec_run",
    "schedule_id": "s_sec",
    "prompt": "run task with registered-secret-da-99999 in prompt",
    "actions": ["execute with registered-secret-da-99999 in action"],
    "t": "2026-10-29T10:00:00"
}]
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
dumped = json.dumps(st["needs_approval"])
check("api/state re-redacts secrets in prompt and actions on the way out",
      "registered-secret-da-99999" not in dumped and "[REDACTED]" in dumped
      and st["needs_approval"][0]["prompt"] == "run task with [REDACTED] in prompt"
      and st["needs_approval"][0]["actions"] == ["execute with [REDACTED] in action"])
g.NOTES = saved_notes
del os.environ["TEST_DA_SECRET"]

# empty or odd inputs: empty actions list, empty prompt, prompt with <script> and HTML tags
script_prompt = "<script>alert('xss')</script><b>bold</b>"
da_sess.needs_approval = [
    {"id": "odd_empty_actions", "schedule_id": "s_odd1", "prompt": "some prompt", "actions": [], "t": "2026-10-29T10:00:00"},
    {"id": "odd_empty_prompt", "schedule_id": "s_odd2", "prompt": "", "actions": ["act1"], "t": "2026-10-29T10:01:00"},
    {"id": "odd_script", "schedule_id": "s_odd3", "prompt": script_prompt, "actions": ["<script>rm()</script>"], "t": "2026-10-29T10:02:00"},
]
st = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
by_id = {e["id"]: e for e in st["needs_approval"]}
check("odd inputs: empty actions list preserved as empty list", by_id["odd_empty_actions"]["actions"] == [])
check("odd inputs: empty prompt preserved as empty string", by_id["odd_empty_prompt"]["prompt"] == "")
check("odd inputs: script and HTML tags carried unchanged as plain text",
      by_id["odd_script"]["prompt"] == script_prompt and by_id["odd_script"]["actions"] == ["<script>rm()</script>"])

# dismiss: authentication refusal
e_dismiss = {"id": "dismiss_target_1", "schedule_id": "s_d1", "prompt": "p1", "actions": ["act1"], "t": "2026-10-29T10:00:00"}
e_keep = {"id": "dismiss_target_2", "schedule_id": "s_d2", "prompt": "p2", "actions": ["act2"], "t": "2026-10-29T10:05:00"}
da_sess.needs_approval = [e_dismiss, e_keep]

r_notok = http.post(f"{da_base}/api/dismiss_approval", json={"id": "dismiss_target_1"}, timeout=5)
check("dismiss_approval refuses missing token with 403", r_notok.status_code == 403)
r_wrong = http.post(f"{da_base}/api/dismiss_approval", headers={"X-Token": "bad"}, json={"id": "dismiss_target_1"}, timeout=5)
check("dismiss_approval refuses wrong token with 403", r_wrong.status_code == 403)

# dismiss: id validation rejecting missing, non-string, empty, 201-character, slashes and dot-dot
for label, bad_body in [
    ("missing id", {}),
    ("integer id", {"id": 12345}),
    ("boolean id", {"id": True}),
    ("list id", {"id": ["foo"]}),
    ("dict id", {"id": {"x": 1}}),
    ("empty id", {"id": ""}),
    ("201-char id", {"id": "x" * 201}),
    ("forward slash", {"id": "a/b"}),
    ("backslash", {"id": "a\\b"}),
    ("parent directory ..", {"id": ".."}),
    ("subfolder traversal", {"id": "../escape"}),
]:
    r_bad = http.post(f"{da_base}/api/dismiss_approval", headers=hdr, json=bad_body, timeout=5)
    check(f"dismiss_approval endpoint validates id rejecting {label} with 400",
          r_bad.status_code == 400 and r_bad.json() == {"error": "invalid"} and len(da_sess.needs_approval) == 2)

# dismiss: unknown id gives 404 and changes nothing
r_unknown = http.post(f"{da_base}/api/dismiss_approval", headers=hdr, json={"id": "nonexistent_id"}, timeout=5)
check("dismiss_approval returns 404 for unknown id and changes nothing",
      r_unknown.status_code == 404 and r_unknown.json() == {"ok": False} and len(da_sess.needs_approval) == 2)

# dismiss: valid id removes entry, 200 {"ok": true}, sidecar appears, next /api/state no longer lists it
r_valid = http.post(f"{da_base}/api/dismiss_approval", headers=hdr, json={"id": "dismiss_target_1"}, timeout=5)
sidecar_file = appr_log_dir / "dismiss_target_1.handled.txt"
st_after = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
check("valid id removes entry, returns 200, writes handled sidecar, and next /api/state no longer lists it",
      r_valid.status_code == 200 and r_valid.json() == {"ok": True}
      and [e["id"] for e in da_sess.needs_approval] == ["dismiss_target_2"]
      and sidecar_file.exists() and sidecar_file.read_text() == "handled\n"
      and [e["id"] for e in st_after["needs_approval"]] == ["dismiss_target_2"])

# dismiss: allowed while run is in progress
da_sess.status = "running"
r_while_running = http.post(f"{da_base}/api/dismiss_approval", headers=hdr, json={"id": "dismiss_target_2"}, timeout=5)
check("dismiss_approval is allowed while run is in progress",
      r_while_running.status_code == 200 and r_while_running.json() == {"ok": True} and len(da_sess.needs_approval) == 0)
da_sess.status = "idle"

# viewing and dismissing execute nothing: assert no run starts, status unchanged, and confirm hook uncalled
confirm_prompts: list[str] = []
saved_confirm = g.CONFIRM
g.CONFIRM = lambda d: (confirm_prompts.append(d), False)[1]
initial_run_id = da_sess._run_id
initial_status = da_sess.status

da_sess.needs_approval = [{"id": "exec_check", "schedule_id": "s_exec", "prompt": "run rm -rf",
                           "actions": ["rm -rf /"], "t": "2026-10-29T10:00:00"}]
st_check = http.get(f"{da_base}/api/state", headers=hdr, timeout=5).json()
r_dcheck = http.post(f"{da_base}/api/dismiss_approval", headers=hdr, json={"id": "exec_check"}, timeout=5)

check("viewing and dismissing execute nothing: no run starts, status unchanged, confirm hook uncalled",
      len(confirm_prompts) == 0
      and da_sess._run_id == initial_run_id
      and da_sess.status == initial_status
      and r_dcheck.status_code == 200)
g.CONFIRM = saved_confirm

# page checks: presence of element id, badge text, dismiss call, textContent, and no innerHTML
page_html = http.get(f"{da_base}/?t={token}", timeout=5).text
check("web page contains approvals card element id", 'id="approvalscard"' in page_html)
check("web page contains badge text and line that renders the badge",
      'badge.textContent = "needs approval"' in page_html and 'm.appendChild(badge)' in page_html)
check("web page contains dismiss approval api call",
      'api("/api/dismiss_approval", {id: a.id})' in page_html)
check("web page uses textContent for prompt and actions",
      'p.textContent = (a.prompt || "").slice(0, 200)' in page_html and 'li.textContent = act' in page_html)
idx_appr_start = page_html.index("function renderApprovals")
idx_appr_end = page_html.index("function renderHistory")
appr_code_path = page_html[idx_appr_start:idx_appr_end]
check("the new code path contains no innerHTML", "innerHTML" not in appr_code_path)

da_srv.shutdown()
g.LOG_DIR = saved_log_dir

# model-written one-sentence summaries for recent runs (#47)
# 1. first line only, clipped to 100 characters
stub_multiline = lambda text: "First line of summary.\nSecond line should be ignored.\nThird line."
check("first line only, clipped to 100 characters",
      web.summarize_run("prompt", "answer", stub_multiline) == "First line of summary.")

stub_long = lambda text: "x" * 150
check("summary reply is clipped to 100 characters",
      web.summarize_run("prompt", "answer", stub_long) == "x" * 100)

rec_query = []
def stub_rec(t):
    rec_query.append(t)
    return "ok"
web.summarize_run("P" * 2000, "A" * 2000, stub_rec)
check("prompt and answer passed to model are clipped to 1500 characters",
      len(rec_query) == 1 and "P" * 1500 in rec_query[0] and "P" * 1501 not in rec_query[0]
      and "A" * 1500 in rec_query[0] and "A" * 1501 not in rec_query[0])

# 2. a secret (a registered key or a ghp_-shaped token) in the reply is redacted
saved_notes = g.NOTES
test_sec_notes = tmp / "notes_for_summary_secret.md"
test_sec_notes.write_text("- svc: http://example.com | key_env=TEST_SUMM_SECRET\n")
os.environ["TEST_SUMM_SECRET"] = "registered-secret-abc12345"
g.NOTES = test_sec_notes

stub_secrets = lambda text: "Got registered-secret-abc12345 and ghp_0123456789abcdef0123456789 from api."
sec_res = web.summarize_run("prompt", "answer", stub_secrets)
check("a secret (a registered key or a ghp_-shaped token) in the reply is redacted",
      sec_res is not None
      and "registered-secret-abc12345" not in sec_res
      and "ghp_0123456789abcdef0123456789" not in sec_res
      and "[REDACTED]" in sec_res
      and "[REDACTED: looks like a credential]" in sec_res)

del os.environ["TEST_SUMM_SECRET"]
g.NOTES = saved_notes

# 3. a raising, empty or whitespace stub gives None and no sidecar
def stub_raising(text):
    raise RuntimeError("Model service down")

check("a raising, empty or whitespace stub gives None and no sidecar",
      web.summarize_run("prompt", "answer", stub_raising) is None
      and web.summarize_run("prompt", "answer", lambda t: "") is None
      and web.summarize_run("prompt", "answer", lambda t: "   \n\t  \n  ") is None)

summary_logs_dir = tmp / "summary_logs"
summary_logs_dir.mkdir(exist_ok=True)
saved_log_dir = g.LOG_DIR
g.LOG_DIR = summary_logs_dir

dummy_agent = type("DummyAgent", (), {
    "interrupt": lambda self: None,
    "run": lambda self, prompt: "dummy answer",
    "monitor": type("M", (), {"get_total_token_counts": lambda self: None})(),
    "memory": type("Mem", (), {"steps": []})(),
    "stall_reason": None,
})()
dummy_appr = web.Approvals(timeout=0)

log_fail = summary_logs_dir / "20261026-100000-fail.jsonl"
log_fail.write_text(json.dumps({"t": "2026-10-26T10:00:00", "kind": "start", "model": "m", "prompt": "test fail"}) + "\n")
sidecar_fail = log_fail.with_name(f"{log_fail.stem}.summary.txt")

sess_raising = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5, run_summaries=True,
                           call_model=stub_raising)
sess_raising._summarize(1, "test fail", "dummy answer", log_fail)
check("raising stub writes no sidecar", not sidecar_fail.exists())

sess_empty = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5, run_summaries=True,
                         call_model=lambda t: "")
sess_empty._summarize(1, "test empty", "dummy answer", log_fail)
check("empty stub writes no sidecar", not sidecar_fail.exists())

sess_ws = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5, run_summaries=True,
                      call_model=lambda t: "   \n\t  ")
sess_ws._summarize(1, "test ws", "dummy answer", log_fail)
check("whitespace stub writes no sidecar", not sidecar_fail.exists())

# 4. _list_runs() shows the sidecar text as title when present and the prompt-derived title when absent, including an old log with no sidecar
f_old = summary_logs_dir / "20261026-090000-old.jsonl"
f_old.write_text("\n".join([
    json.dumps({"t": "2026-10-26T09:00:00", "kind": "start", "model": "m", "prompt": "Old task prompt. More details."}),
    json.dumps({"t": "2026-10-26T09:00:05", "kind": "final", "answer": "old answer"}),
]) + "\n")

f_with_sidecar = summary_logs_dir / "20261026-093000-sidecar.jsonl"
f_with_sidecar.write_text("\n".join([
    json.dumps({"t": "2026-10-26T09:30:00", "kind": "start", "model": "m", "prompt": "Prompt for run with sidecar."}),
    json.dumps({"t": "2026-10-26T09:30:05", "kind": "final", "answer": "sidecar answer"}),
]) + "\n")
sidecar_file = f_with_sidecar.with_name(f"{f_with_sidecar.stem}.summary.txt")
sidecar_file.write_text("Model-written summary for run with sidecar")

runs_by_id = {r["id"]: r for r in web._list_runs()}
check("_list_runs() shows the sidecar text as title when present and the prompt-derived title when absent, including an old log with no sidecar",
      runs_by_id[f_with_sidecar.name]["title"] == "Model-written summary for run with sidecar"
      and runs_by_id[f_old.name]["title"] == "Old task prompt.")

f_with_sidecar.with_name(f"{f_with_sidecar.stem}.summary.txt").write_text("Leaked ghp_0123456789abcdef0123456789 " + "y" * 200)
leaky = {r["id"]: r for r in web._list_runs()}[f_with_sidecar.name]["title"]
check("_list_runs() redacts and clips a sidecar on read", "ghp_0123" not in leaky and len(leaky) <= 100)
sidecar_file.write_text("Model-written summary for run with sidecar")

seen_kwargs = []
def stub_model(messages, **kw):
    seen_kwargs.append(kw)
    if "reasoning_effort" in kw:
        raise RuntimeError("unknown parameter")
    return type("Msg", (), {"content": "ok"})()
check("summary call turns thinking off and caps output, retrying without the reasoning setting if rejected",
      web.call_summary_model(stub_model, "x") == "ok"
      and seen_kwargs == [{"reasoning_effort": "none", "max_tokens": 80}, {"max_tokens": 80}])

# 5. no sidecar is written when the setting is off
sess_off = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5, run_summaries=False,
                       call_model=lambda t: "Summary should not be written")
sess_off._run("Task with summaries off", 1)
log_file_off = g._log_file
sidecar_off = log_file_off.with_name(f"{log_file_off.stem}.summary.txt") if log_file_off else None
check("no sidecar is written when the setting is off",
      sidecar_off is not None and not sidecar_off.exists())

# 6. a run started while a summary is in flight does not get the older run’s summary (stub blocking on an event)
block_event = threading.Event()
model_called = threading.Event()

def blocking_call_model(prompt_text):
    model_called.set()
    block_event.wait(5)
    return "Older run summary"

sess_inflight = web.Session(dummy_agent, "m1", dummy_appr, "lmstudio", 5, run_summaries=True,
                            call_model=blocking_call_model)

# Start run 1 (creates log 1)
sess_inflight.start("Run 1 prompt")
model_called.wait(3)

run1_log = g._log_file
# Run 1 summary is currently in flight. Start run 2 while summary is in flight!
sess_inflight.model = "m2"
sess_inflight.call_model = lambda t: "Run 2 summary"
sess_inflight.start("Run 2 prompt")

# Unblock run 1's call_model
block_event.set()

# Wait for run 2 to finish
time.sleep(0.5)
run2_log = g._log_file

runs_by_id = {r["id"]: r for r in web._list_runs()}
run1_sidecar = run1_log.with_name(f"{run1_log.stem}.summary.txt") if run1_log else None
run2_sidecar = run2_log.with_name(f"{run2_log.stem}.summary.txt") if run2_log else None

check("a run started while a summary is in flight does not get the older run’s summary",
      runs_by_id.get(run2_log.name, {}).get("title") != "Older run summary"
      and (run2_sidecar is not None and run2_sidecar.exists() and run2_sidecar.read_text().strip() == "Run 2 summary")
      and (run1_sidecar is not None and not run1_sidecar.exists()))

# env var default SMOLPAW_RUN_SUMMARIES
os.environ["SMOLPAW_RUN_SUMMARIES"] = "1"
sess_env_on = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5)
check("SMOLPAW_RUN_SUMMARIES=1 enables summaries by default", sess_env_on.run_summaries is True)
os.environ.pop("SMOLPAW_RUN_SUMMARIES", None)
sess_env_off = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5)
check("summaries are on by default when SMOLPAW_RUN_SUMMARIES is unset", sess_env_off.run_summaries is True)
os.environ["SMOLPAW_RUN_SUMMARIES"] = "0"
sess_env_zero = web.Session(dummy_agent, "m", dummy_appr, "lmstudio", 5)
check("SMOLPAW_RUN_SUMMARIES=0 turns summaries off", sess_env_zero.run_summaries is False)
os.environ.pop("SMOLPAW_RUN_SUMMARIES", None)


# ---- chat threads: follow-ups share a thread, carry context, and group in Recents ----
import agent as _agent_mod  # noqa: E402

thread_dir = tmp / "thread-logs"
saved_ld_t, g.LOG_DIR = g.LOG_DIR, thread_dir
seen_inputs: list[str] = []


class _ThreadAgent:
    def __init__(self):
        self.stall_reason = None
        self.memory = type("M", (), {"steps": []})()
        self.monitor = type("Mon", (), {"get_total_token_counts": lambda self: type("T", (), {"input_tokens": 1, "output_tokens": 1})()})()

    def run(self, text):
        seen_inputs.append(text)
        return f"answer {len(seen_inputs)}"


def _wait_idle(sess):
    for _ in range(100):
        if sess.status == "idle":
            return
        time.sleep(0.05)


tsess = web.Session(_ThreadAgent(), "m", web.Approvals(), "lmstudio", 5, run_summaries=False)
tsess.start("first question")
_wait_idle(tsess)
time.sleep(1.1)  # log files are named to the second
tsess.start("and a follow up")
_wait_idle(tsess)
check("first message carries no earlier-chat context", seen_inputs[0] == "first question")
check("a follow-up carries the earlier turn as context",
      "User: first question" in seen_inputs[1] and "You: answer 1" in seen_inputs[1]
      and seen_inputs[1].endswith("New message from the user: and a follow up"))
check("the session keeps earlier turns for the page", tsess.history == [("first question", "answer 1")])
chats = web._list_runs()
check("follow-ups group into one Recents entry", len(chats) == 1 and chats[0]["turns"] == 2 and len(chats[0]["ids"]) == 2)
check("the log keeps the user's own message, not the context",
      web._run_detail(thread_dir / chats[0]["ids"][1])["prompt"] == "and a follow up")
check("a chat's title comes from its first message", chats[0]["title"] == "first question")
check("a chat is rebuilt from its logs", web._thread_turns(chats[0]["thread"]) ==
      [("first question", "answer 1"), ("and a follow up", "answer 2")])

time.sleep(1.1)
check("new_thread clears the chat", tsess.new_thread() and tsess.history == [] and tsess.thread is None)
tsess.start("unrelated")
_wait_idle(tsess)
check("a new chat starts without context", seen_inputs[2] == "unrelated" and len(web._list_runs()) == 2)

time.sleep(1.1)
tsess.start("back to the first one", chats[0]["thread"])
_wait_idle(tsess)
check("continuing a chat from Recents restores its context",
      "User: first question" in seen_inputs[3] and "User: and a follow up" in seen_inputs[3]
      and "unrelated" not in seen_inputs[3] and len(web._list_runs()) == 2)
check("build_context keeps only the last turns and clips long answers",
      "turn0" not in web.build_context([(f"turn{i}", "x" * 2000) for i in range(5)])
      and "x" * 700 not in web.build_context([("q", "x" * 2000)]))
g.LOG_DIR = saved_ld_t

g.LOG_DIR = saved_log_dir

# interactive runs keep today's confirmation behaviour (the scheduled read-only mode must not leak into them, #52)
_ia_prompts: list[str] = []
_ia_answer = {"v": True}
_ia_saved = g.CONFIRM, g.ASK
g.CONFIRM = lambda d: (_ia_prompts.append(d), _ia_answer["v"])[1]
g.ASK = lambda q: "typed answer"
_ia_sess = web.Session(_ThreadAgent(), "m", web.Approvals(), "lmstudio", 5, run_summaries=False)
saved_ld_ia = g.LOG_DIR
g.LOG_DIR = tmp / "interactive-logs"
_ia_sess.start("plain interactive run")
_wait_idle(_ia_sess)
check("an interactive run leaves the confirm and ask hooks alone", g.CONFIRM is not _ia_saved[0] and g.ASK("q") == "typed answer")
_ia_prompts.clear()
check("an interactive write still asks and goes ahead when approved",
      "wrote" in g.write_file("ia.txt", "x").lower() and len(_ia_prompts) == 1 and (g.WORKSPACE / "ia.txt").exists())
_ia_answer["v"] = False
check("an interactive write still comes back DECLINED when refused",
      g.write_file("ia2.txt", "x") == g.DECLINED and not (g.WORKSPACE / "ia2.txt").exists())
_start = json.loads(g._log_file.read_text().splitlines()[0]) if g._log_file and g._log_file.exists() else {}
check("an interactive run's start log entry has no schedule field", _start.get("kind") == "start" and "schedule" not in _start)
g.LOG_DIR = saved_ld_ia
g.CONFIRM, g.ASK = _ia_saved
current_logs = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()
check("real logs folder is untouched", current_logs == logs_snapshot)

# ---- reversible file overwrites (.undo) ----

# 1. Approved overwrite of an existing file: old content saved byte-for-byte before new content lands
test1_file = g.WORKSPACE / "undo_test1.txt"
old_content1 = b"original byte content \x00\x01\xff with special chars\n"
test1_file.write_bytes(old_content1)
undo_dir1 = tmp / "undo_t1"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir1
answer["value"] = True
res1 = g.write_file("undo_test1.txt", "new content 1")
t1_copies = list(undo_dir1.iterdir()) if undo_dir1.exists() else []
check("1. approved overwrite of an existing file: old content is saved byte-for-byte before new content lands",
      test1_file.read_text() == "new content 1"
      and len(t1_copies) == 1
      and t1_copies[0].read_bytes() == old_content1)
g.UNDO_DIR = saved_undo_dir

# 2. Declined write: nothing is saved and original file is unchanged
test2_file = g.WORKSPACE / "undo_test2.txt"
test2_file.write_text("original content 2")
undo_dir2 = tmp / "undo_t2"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir2
answer["value"] = False
res2 = g.write_file("undo_test2.txt", "declined content 2")
t2_copies = list(undo_dir2.iterdir()) if undo_dir2.exists() else []
check("2. declined write: nothing is saved and the original file is unchanged",
      hasattr(g, "_save_undo")
      and res2 == g.DECLINED
      and test2_file.read_text() == "original content 2"
      and len(t2_copies) == 0)
g.UNDO_DIR = saved_undo_dir

# 3. New file: nothing is saved
test3_file = g.WORKSPACE / "undo_test3_new.txt"
if test3_file.exists():
    test3_file.unlink()
undo_dir3 = tmp / "undo_t3"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir3
answer["value"] = True
res3 = g.write_file("undo_test3_new.txt", "brand new file content")
t3_copies = list(undo_dir3.iterdir()) if undo_dir3.exists() else []
check("3. new file: nothing is saved",
      hasattr(g, "_save_undo")
      and test3_file.read_text() == "brand new file content"
      and len(t3_copies) == 0
      and "previous content saved at" not in g.ACTIONS[-1]
      and "not saved:" not in g.ACTIONS[-1])
g.UNDO_DIR = saved_undo_dir

# 4. Secrets file (.env): write is blocked and nothing is saved
test4_env = g.WORKSPACE / ".env"
old_env = test4_env.read_text()
undo_dir4 = tmp / "undo_t4"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir4
answer["value"] = True
res4 = g.write_file(".env", "MALICIOUS_KEY=123")
t4_copies = list(undo_dir4.iterdir()) if undo_dir4.exists() else []
check("4. secrets file (.env): write is blocked and nothing is saved",
      hasattr(g, "_save_undo")
      and res4.startswith("BLOCKED")
      and test4_env.read_text() == old_env
      and len(t4_copies) == 0)
g.UNDO_DIR = saved_undo_dir

# 5. File over the size cap: write still happens, nothing is saved, report says not saved: too large
test5_file = g.WORKSPACE / "undo_test5_large.txt"
test5_file.write_bytes(b"x" * (getattr(g, "UNDO_MAX_BYTES", 1_000_000) + 100))
undo_dir5 = tmp / "undo_t5"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir5
answer["value"] = True
res5 = g.write_file("undo_test5_large.txt", "small replacement")
t5_copies = list(undo_dir5.iterdir()) if undo_dir5.exists() else []
check("5. file over the size cap: the write still happens, nothing is saved, and the report says not saved: too large",
      test5_file.read_text() == "small replacement"
      and len(t5_copies) == 0
      and "not saved: too large" in g.ACTIONS[-1])
g.UNDO_DIR = saved_undo_dir

# 6. Retention: after 12 overwrites of same path only newest 10 copies remain; different path untouched
undo_dir6 = tmp / "undo_t6"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir6
answer["value"] = True
g.write_file("undo_test6_b.txt", "b_initial")
g.write_file("undo_test6_b.txt", "b_overwritten")
b_copies_before = [f.name for f in undo_dir6.iterdir() if f.is_file() and "undo_test6_b" in f.name] if undo_dir6.exists() else []

g.write_file("undo_test6_a.txt", "v0")
for i in range(1, 13):
    g.write_file("undo_test6_a.txt", f"v{i}")

a_copies = sorted([f for f in undo_dir6.iterdir() if f.is_file() and "undo_test6_a" in f.name], key=lambda x: x.name) if undo_dir6.exists() else []
b_copies_after = [f.name for f in undo_dir6.iterdir() if f.is_file() and "undo_test6_b" in f.name] if undo_dir6.exists() else []
check("6. retention: after 12 overwrites of the same path only the newest 10 copies remain; a different path's copies are untouched",
      len(b_copies_before) == 1
      and b_copies_after == b_copies_before
      and len(a_copies) == 10
      and [f.read_text() for f in a_copies] == [f"v{i}" for i in range(2, 12)])
g.UNDO_DIR = saved_undo_dir

# 7. A path containing .. or separators produces a saved name inside UNDO_DIR only
undo_dir7 = tmp / "undo_t7"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir7
answer["value"] = True
sub_dir = g.WORKSPACE / "sub_undo"
sub_dir.mkdir(exist_ok=True)
(sub_dir / "nested.txt").write_text("old nested")
g.write_file("sub_undo/nested.txt", "new nested")
nested_copies = list(undo_dir7.iterdir()) if undo_dir7.exists() else []
check("7. a path containing .. or separators produces a saved name inside UNDO_DIR only",
      len(nested_copies) == 1
      and nested_copies[0].parent.resolve() == undo_dir7.resolve()
      and ".." not in nested_copies[0].name
      and "/" not in nested_copies[0].name
      and "\\" not in nested_copies[0].name
      and hasattr(g, "_undo_name")
      and (undo_dir7 / g._undo_name("../../escape.txt")).parent.resolve() == undo_dir7.resolve()
      and ".." not in g._undo_name("../../escape.txt")
      and "/" not in g._undo_name("../../escape.txt")
      and "\\" not in g._undo_name("../../escape.txt"))
g.UNDO_DIR = saved_undo_dir

# 8. Saved path appears in ACTIONS and in log entry; no file contents appear in either
undo_dir8 = tmp / "undo_t8"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir8
test8_file = g.WORKSPACE / "undo_test8.txt"
secret_content8 = "SECRET_OLD_CONTENT_XYZ987_DO_NOT_LEAK"
test8_file.write_text(secret_content8)
test8_log = tmp / "undo_test8_log.jsonl"
saved_log_file, g._log_file = g._log_file, test8_log
answer["value"] = True
g.write_file("undo_test8.txt", "new content 8")
t8_copies = list(undo_dir8.iterdir()) if undo_dir8.exists() else []
saved_path_str = str(t8_copies[0]) if t8_copies else ""
t8_entries = [json.loads(l) for l in test8_log.read_text().splitlines() if json.loads(l).get("kind") == "write_file"] if test8_log.exists() else []
entry8 = t8_entries[-1] if t8_entries else {}
check("8. the saved path appears in ACTIONS and in the log entry; no file contents appear in either",
      bool(saved_path_str)
      and saved_path_str in g.ACTIONS[-1]
      and entry8.get("undo") == saved_path_str
      and secret_content8 not in g.ACTIONS[-1]
      and secret_content8 not in json.dumps(entry8))
g._log_file = saved_log_file
g.UNDO_DIR = saved_undo_dir

# 9. Failure to save does not stop the write
undo_dir9 = tmp / "undo_t9"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir9
test9_file = g.WORKSPACE / "undo_test9.txt"
test9_file.write_text("old text 9")
answer["value"] = True
saved_save_undo = getattr(g, "_save_undo", None)
g._save_undo = lambda p: (None, "not saved: could not copy")
res9 = g.write_file("undo_test9.txt", "new text 9")
check("9. a failure to save (make UNDO_DIR unwritable or patch the copy to raise) does not stop the write",
      res9.startswith("SUCCESS")
      and test9_file.read_text() == "new text 9"
      and "not saved: could not copy" in g.ACTIONS[-1])
if saved_save_undo:
    g._save_undo = saved_save_undo
else:
    delattr(g, "_save_undo")
g.UNDO_DIR = saved_undo_dir

# 10. write_skill overwriting an existing skill saves old content same way
undo_dir10 = tmp / "undo_t10"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir10
test10_log = tmp / "undo_test10_log.jsonl"
saved_log_file, g._log_file = g._log_file, test10_log
g.SKILLS.mkdir(exist_ok=True)
skill_file = g.SKILLS / "undo_test_skill.md"
old_skill_content = "# Old Skill\nold instructions for skill\n"
skill_file.write_text(old_skill_content)
answer["value"] = True
res10 = g.write_skill("undo_test_skill", "# New Skill\nnew instructions for skill\n")
t10_copies = list(undo_dir10.iterdir()) if undo_dir10.exists() else []
saved_skill_path_str = str(t10_copies[0]) if t10_copies else ""
t10_entries = [json.loads(l) for l in test10_log.read_text().splitlines() if json.loads(l).get("kind") == "write_skill"] if test10_log.exists() else []
entry10 = t10_entries[-1] if t10_entries else {}
check("10. write_skill overwriting an existing skill saves the old content the same way",
      res10.startswith("SUCCESS")
      and skill_file.read_text() == "# New Skill\nnew instructions for skill\n"
      and len(t10_copies) == 1
      and t10_copies[0].read_bytes() == old_skill_content.encode("utf-8")
      and saved_skill_path_str in g.ACTIONS[-1]
      and entry10.get("undo") == saved_skill_path_str
      and old_skill_content not in g.ACTIONS[-1]
      and old_skill_content not in json.dumps(entry10))
g._log_file = saved_log_file
g.UNDO_DIR = saved_undo_dir

# 11. Review additions: different paths never share copies or retention, even when sanitising or
#     truncation would give the same text
undo_dir11 = tmp / "undo_t11"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir11
saved_keep, g.UNDO_KEEP = g.UNDO_KEEP, 2
long_tail = "d" * 150
long_a = g.WORKSPACE / ("A" + long_tail) / "f.txt"
long_b = g.WORKSPACE / ("B" + long_tail) / "f.txt"
for lp in (long_a, long_b):
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("v0")
answer["value"] = True
for i in range(1, 4):
    g.write_file(str(long_a), f"a{i}")
for i in range(1, 3):
    g.write_file(str(long_b), f"b{i}")
by_content = sorted(f.read_text() for f in undo_dir11.iterdir())
check("11a. two long paths with the same tail keep separate copies and separate retention",
      g._undo_tag(long_a) != g._undo_tag(long_b) and by_content == ["a1", "a2", "b1", "v0"])
check("11b. a..b.txt and ab.txt do not share a tag", g._undo_tag(g.WORKSPACE / "a..b.txt") != g._undo_tag(g.WORKSPACE / "ab.txt"))
g.UNDO_KEEP = saved_keep
g.UNDO_DIR = saved_undo_dir

# 12. Copies are private: folder 0700, files 0600
if os.name == "posix":
    undo_dir12 = tmp / "undo_t12"
    saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir12
    priv = g.WORKSPACE / "undo_test12.txt"
    priv.write_text("private")
    priv.chmod(0o600)
    answer["value"] = True
    g.write_file("undo_test12.txt", "new")
    copy12 = list(undo_dir12.iterdir())
    check("12. the undo folder is 0700 and the copy is 0600",
          len(copy12) == 1 and stat.S_IMODE(undo_dir12.stat().st_mode) == 0o700
          and stat.S_IMODE(copy12[0].stat().st_mode) == 0o600)
    g.UNDO_DIR = saved_undo_dir

# 13. A real failure to save (UNDO_DIR is a regular file) does not stop the write and is reported
blocker = tmp / "undo_t13_blocker"
blocker.write_text("not a folder")
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, blocker
f13 = g.WORKSPACE / "undo_test13.txt"
f13.write_text("old 13")
answer["value"] = True
res13 = g.write_file("undo_test13.txt", "new 13")
check("13. a real save failure leaves the write intact and says not saved: could not copy",
      res13.startswith("SUCCESS") and f13.read_text() == "new 13" and "not saved: could not copy" in g.ACTIONS[-1])
g.UNDO_DIR = saved_undo_dir

# 14. A path with .. components resolves, saves inside UNDO_DIR, and the name carries no separators
undo_dir14 = tmp / "undo_t14"
saved_undo_dir, g.UNDO_DIR = g.UNDO_DIR, undo_dir14
f14 = g.WORKSPACE / "undo_test14.txt"
f14.write_text("old 14")
answer["value"] = True
g.write_file("sub_undo/../undo_test14.txt", "new 14")
c14 = list(undo_dir14.iterdir())
check("14. a path written with .. components saves one copy inside UNDO_DIR",
      len(c14) == 1 and c14[0].parent.resolve() == undo_dir14.resolve() and c14[0].read_bytes() == b"old 14"
      and ".." not in c14[0].name and "/" not in c14[0].name)
g.UNDO_DIR = saved_undo_dir

current_undo = {(p.name, p.stat().st_size) for p in real_undo.iterdir()} if real_undo.exists() else set()
check("real .undo folder is untouched", not real_undo.exists() if not undo_snapshot else current_undo == undo_snapshot)

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
