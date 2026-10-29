"""
Tests for the deterministic tracking fixture generator (tests/tracking_fixture.py).
Run with: .venv/bin/python tests/test_tracking_fixture.py

Tests must not write to the real workspace/, notes.md or logs/.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generic_tools import MAX_OUT
from tests.tracking_fixture import (
    CASE_A_FILENAME,
    CASE_A_SECTIONS,
    CASE_A_TARGET_NEW,
    CASE_A_TARGET_OLD,
    CASE_B_FILENAME,
    CASE_B_HEADINGS,
    CASE_B_NEW_BODY,
    CASE_B_NEW_HEADING,
    CASE_B_NEW_SECTION,
    CASE_C_FACTS,
    CASE_C_FILES,
    REAL_WORKSPACE,
    build,
)

check_failed = 0


def check(name: str, cond: bool) -> None:
    global check_failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check_failed += 1


real_logs = ROOT / "logs"
logs_snapshot = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()
ws_snapshot = {(p.name, p.stat().st_size) for p in REAL_WORKSPACE.iterdir()} if REAL_WORKSPACE.exists() else set()
notes_snapshot = (ROOT / "notes.md").stat().st_mtime if (ROOT / "notes.md").exists() else None

tmp_base = Path(tempfile.mkdtemp(prefix="test_tracking_fixture_"))

try:
    # --- 1. Public API & Generator structure -----------------------------------------

    ws_init = tmp_base / "ws_init"
    cases = build(ws_init, seed=0)

    check("build returns a list of 3 cases", len(cases) == 3)
    case_names = [c.name for c in cases]
    check("cases contain expected names in order", case_names == ["edit_one_section", "append_keep_all", "read_three_report"])

    case_a, case_b, case_c = cases

    check("case_a expects is empty (disk checked)", case_a.expects == [])
    check("case_b expects is empty (disk checked)", case_b.expects == [])
    check("case_c expects contains 3 regexes", len(case_c.expects) == 3)

    all_written_files = [f for c in cases for f in c.files]
    check("build created all declared files on disk", all((ws_init / f).is_file() for f in all_written_files))

    # --- 2. Size, offsets, and letter-only filler assertions -------------------------

    for f in all_written_files:
        content = (ws_init / f).read_text(encoding="utf-8")
        check(f"file {f} length ({len(content)}) exceeds MAX_OUT ({MAX_OUT})", len(content) > MAX_OUT)

    # Case A: facility_guide.md
    text_a = (ws_init / CASE_A_FILENAME).read_text(encoding="utf-8")
    check("case_a document is ~12,000 characters", 11000 <= len(text_a) <= 13000)
    check("case_a document contains all 8 section headings", all(h in text_a for h, _ in CASE_A_SECTIONS))
    fact_a_offset = text_a.find(CASE_A_TARGET_OLD)
    check(f"case_a target fact offset ({fact_a_offset}) exceeds MAX_OUT ({MAX_OUT})", fact_a_offset > MAX_OUT)

    # No digits outside the 8 facts in Case A
    stripped_a = text_a
    for _, fact in CASE_A_SECTIONS:
        stripped_a = stripped_a.replace(fact, "")
    check("case_a document contains no digits outside its 8 fact lines", len(re.findall(r"\d", stripped_a)) == 0)

    # Case B: system_records.md
    text_b = (ws_init / CASE_B_FILENAME).read_text(encoding="utf-8")
    check("case_b document contains all headings", all(h in text_b for h in CASE_B_HEADINGS))
    check("case_b document contains no digits anywhere", len(re.findall(r"\d", text_b)) == 0)

    # Case C: 3 files with key figures beyond MAX_OUT and differing structures
    texts_c = {f: (ws_init / f).read_text(encoding="utf-8") for f in CASE_C_FILES}
    for fname, fig, fact_sent in CASE_C_FACTS:
        t = texts_c[fname]
        offset = t.find(fig)
        check(f"case_c file {fname} key figure {fig} offset ({offset}) exceeds MAX_OUT ({MAX_OUT})", offset > MAX_OUT)
        stripped = t.replace(fact_sent, "")
        check(f"case_c file {fname} contains no digits outside its fact", len(re.findall(r"\d", stripped)) == 0)

    # Structural diversity in Case C
    check("case_c files have distinct formatting headers",
          "# Hydrology" in texts_c[CASE_C_FILES[0]] and
          "PART ONE" in texts_c[CASE_C_FILES[1]] and
          "[REFUGE MANIFEST" in texts_c[CASE_C_FILES[2]])

    # Spoken answer regex validation
    sample_answer = "Hydrology is 1485, geology reached 832, and refuge inventory has 674 litres."
    check("case_c expects all match a correct report", all(re.search(e, sample_answer, re.I) for e in case_c.expects))
    incomplete_answer = "Hydrology is 1485, geology reached 832."
    check("case_c expects fail when one figure is missing", not all(re.search(e, incomplete_answer, re.I) for e in case_c.expects))

    # --- 3. Determinism across processes with different PYTHONHASHSEED --------------

    proc_dir_1 = tmp_base / "proc_dir_1"
    proc_dir_2 = tmp_base / "proc_dir_2"

    cmd = [sys.executable, str(ROOT / "tests" / "tracking_fixture.py")]

    res1 = subprocess.run(cmd + [str(proc_dir_1), "42"], capture_output=True, text=True,
                          env={**os.environ, "PYTHONHASHSEED": "1"})
    res2 = subprocess.run(cmd + [str(proc_dir_2), "42"], capture_output=True, text=True,
                          env={**os.environ, "PYTHONHASHSEED": "999"})

    check("CLI run 1 with PYTHONHASHSEED=1 exited with code 0", res1.returncode == 0)
    check("CLI run 2 with PYTHONHASHSEED=999 exited with code 0", res2.returncode == 0)

    hashes_1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in proc_dir_1.iterdir()}
    hashes_2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in proc_dir_2.iterdir()}

    check("generator output files are byte-identical across processes with different PYTHONHASHSEED",
          hashes_1 == hashes_2 and len(hashes_1) == 5)

    # --- 4. Mutation tests for Case A (edit_one_section) -----------------------------

    ws_mut_a = tmp_base / "ws_mut_a"
    mut_cases_a = build(ws_mut_a, seed=10)
    checker_a = mut_cases_a[0].check
    orig_a = (ws_mut_a / CASE_A_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: one section dropped fails
    dropped_section_text = orig_a.replace(CASE_A_SECTIONS[7][0], "")
    (ws_mut_a / CASE_A_FILENAME).write_text(dropped_section_text, encoding="utf-8")
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 2: dropped section fails", not passed and "dropped" in reason)

    # Mutation 3: section truncated to read clip fails
    clipped_text = orig_a[:MAX_OUT]
    (ws_mut_a / CASE_A_FILENAME).write_text(clipped_text, encoding="utf-8")
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 3: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 4: correct edit passes
    correct_edit_text = orig_a.replace(CASE_A_TARGET_OLD, CASE_A_TARGET_NEW, 1)
    (ws_mut_a / CASE_A_FILENAME).write_text(correct_edit_text, encoding="utf-8")
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 4: correct edit passes", passed)

    # Mutation 5: wrong line edited fails
    wrong_edit_text = orig_a.replace("520 kilowatts", "980 kilowatts", 1)
    (ws_mut_a / CASE_A_FILENAME).write_text(wrong_edit_text, encoding="utf-8")
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 5: wrong line edited fails", not passed)

    # Mutation 6: edit applied plus extra change fails
    extra_change_text = correct_edit_text + "\n# Extra trailing text\n"
    (ws_mut_a / CASE_A_FILENAME).write_text(extra_change_text, encoding="utf-8")
    passed, reason = checker_a(ws_mut_a)
    check("case_a mutation 6: edit applied plus extra change fails", not passed)

    # Missing file fails
    (ws_mut_a / CASE_A_FILENAME).unlink()
    passed, reason = checker_a(ws_mut_a)
    check("case_a missing file fails", not passed and "does not exist" in reason)

    # --- 5. Mutation tests for Case B (append_keep_all) ------------------------------

    ws_mut_b = tmp_base / "ws_mut_b"
    mut_cases_b = build(ws_mut_b, seed=20)
    checker_b = mut_cases_b[1].check
    orig_b = (ws_mut_b / CASE_B_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: one section dropped from prefix fails
    dropped_prefix = orig_b.replace(CASE_B_HEADINGS[0], "## Modified")
    (ws_mut_b / CASE_B_FILENAME).write_text(f"{dropped_prefix}\n\n{CASE_B_NEW_SECTION}\n", encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 2: dropped section from prefix fails", not passed)

    # Mutation 3: section truncated to read clip fails
    clipped_prefix = orig_b[:MAX_OUT]
    (ws_mut_b / CASE_B_FILENAME).write_text(f"{clipped_prefix}\n\n{CASE_B_NEW_SECTION}\n", encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 3: truncated prefix fails", not passed and "truncated" in reason)

    # Mutation 4: correct edit passes
    correct_append_text = f"{orig_b}\n\n{CASE_B_NEW_SECTION}\n"
    (ws_mut_b / CASE_B_FILENAME).write_text(correct_append_text, encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 4: correct append passes", passed)

    # Mutation 5: wrong line edited fails (modified existing content without appending)
    wrong_edit_b = orig_b.replace("Environmental", "Atmospheric")
    (ws_mut_b / CASE_B_FILENAME).write_text(wrong_edit_b, encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 5: wrong line edited without append fails", not passed)

    # Mutation 6: edit applied plus extra change fails
    extra_change_b = f"{correct_append_text}\nExtra unexpected line.\n"
    (ws_mut_b / CASE_B_FILENAME).write_text(extra_change_b, encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b mutation 6: append plus extra text fails", not passed)

    # Appending section twice fails
    double_append_b = f"{orig_b}\n\n{CASE_B_NEW_SECTION}\n\n{CASE_B_NEW_SECTION}\n"
    (ws_mut_b / CASE_B_FILENAME).write_text(double_append_b, encoding="utf-8")
    passed, reason = checker_b(ws_mut_b)
    check("case_b duplicate append fails", not passed and "more than once" in reason)

    # Missing file fails
    (ws_mut_b / CASE_B_FILENAME).unlink()
    passed, reason = checker_b(ws_mut_b)
    check("case_b missing file fails", not passed and "does not exist" in reason)

    # --- 6. Case C check behavior ----------------------------------------------------

    ws_mut_c = tmp_base / "ws_mut_c"
    mut_cases_c = build(ws_mut_c, seed=30)
    checker_c = mut_cases_c[2].check

    passed, reason = checker_c(ws_mut_c)
    check("case_c untouched workspace passes disk integrity check", passed)

    (ws_mut_c / CASE_C_FILES[1]).write_text("overwritten")
    passed, reason = checker_c(ws_mut_c)
    check("case_c overwritten file fails disk check", not passed and "modified" in reason)

    kept = (ws_mut_c / CASE_C_FILES[2]).read_text(encoding="utf-8")
    (ws_mut_c / CASE_C_FILES[2]).write_text(kept[:MAX_OUT])
    passed, reason = checker_c(ws_mut_c)
    check("case_c file truncated to the clip fails disk check", not passed and "modified" in reason)

    (ws_mut_c / CASE_C_FILES[0]).unlink()
    passed, reason = checker_c(ws_mut_c)
    check("case_c missing file fails disk check", not passed and "missing" in reason)

    # --- 7. CLI invocation & workspace protection checks -----------------------------

    cli_out_dir = tmp_base / "cli_valid"
    proc_cli = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "tracking_fixture.py"), str(cli_out_dir)],
        capture_output=True,
        text=True,
    )
    check("CLI writes into given directory and exits with code 0", proc_cli.returncode == 0)
    check("CLI output mentions materialised cases", "Materialised 3 cases" in proc_cli.stdout)
    check("CLI wrote files inside destination directory", (cli_out_dir / CASE_A_FILENAME).is_file())

    # CLI refuses to write into real workspace/
    proc_bad = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "tracking_fixture.py"), str(REAL_WORKSPACE)],
        capture_output=True,
        text=True,
    )
    check("CLI refuses writing into repo's real workspace/ (exit non-zero)", proc_bad.returncode != 0)
    check("CLI prints refusal message to stderr", "Refusing to write" in proc_bad.stderr)

    # Direct build() refuses real workspace/ and subdirectories
    raised_real_ws = False
    try:
        build(REAL_WORKSPACE)
    except ValueError:
        raised_real_ws = True
    check("direct build(REAL_WORKSPACE) raises ValueError", raised_real_ws)

    raised_sub_ws = False
    try:
        build(REAL_WORKSPACE / "subfolder")
    except ValueError:
        raised_sub_ws = True
    check("direct build(REAL_WORKSPACE / 'subfolder') raises ValueError", raised_sub_ws)

    # Direct build() refuses notes.md and memory.md
    raised_notes = False
    try:
        build(ROOT / "notes.md")
    except ValueError:
        raised_notes = True
    check("direct build(ROOT / 'notes.md') raises ValueError", raised_notes)

finally:
    shutil.rmtree(tmp_base, ignore_errors=True)

# --- 8. Isolation assertions -----------------------------------------------------

if real_logs.exists():
    logs_after = {(p.name, p.stat().st_size) for p in real_logs.iterdir()}
    check("the test suite wrote no run logs to the real logs/ directory", logs_after == logs_snapshot)

if REAL_WORKSPACE.exists():
    ws_after = {(p.name, p.stat().st_size) for p in REAL_WORKSPACE.iterdir()}
    check("the test suite wrote nothing to the real workspace/ directory", ws_after == ws_snapshot)

if (ROOT / "notes.md").exists():
    check("real notes.md was not modified", (ROOT / "notes.md").stat().st_mtime == notes_snapshot)

print(f"\n{check_failed} failed")
sys.exit(1 if check_failed else 0)
