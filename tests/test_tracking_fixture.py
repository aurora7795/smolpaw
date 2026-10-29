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
    CASE_CLIP_FILENAME,
    CASE_CLIP_TARGET_NEW,
    CASE_CLIP_TARGET_OLD,
    CASE_CRLF_FILENAME,
    CASE_CRLF_TARGET_NEW,
    CASE_CRLF_TARGET_OLD,
    CASE_DUP_FILENAME,
    CASE_DUP_SECTIONS,
    CASE_DUP_TARGET_NEW,
    CASE_DUP_TARGET_OLD,
    CASE_LAST_FILENAME,
    CASE_LAST_TARGET_NEW,
    CASE_LAST_TARGET_OLD,
    CASE_SPEC_FILENAME,
    CASE_SPEC_TARGET_NEW,
    CASE_SPEC_TARGET_OLD,
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

    check("build returns a list of 8 cases", len(cases) == 8)
    case_names = [c.name for c in cases]
    check(
        "cases contain expected names in order",
        case_names
        == [
            "edit_one_section",
            "append_keep_all",
            "read_three_report",
            "edit_duplicate_passage",
            "edit_last_line",
            "edit_special_chars",
            "edit_across_clip",
            "edit_crlf",
        ],
    )

    case_a, case_b, case_c, case_dup, case_last, case_spec, case_clip, case_crlf = cases

    check("case_a expects is empty (disk checked)", case_a.expects == [])
    check("case_b expects is empty (disk checked)", case_b.expects == [])
    check("case_c expects contains 3 regexes", len(case_c.expects) == 3)
    check("case_dup expects is empty (disk checked)", case_dup.expects == [])
    check("case_last expects is empty (disk checked)", case_last.expects == [])
    check("case_spec expects is empty (disk checked)", case_spec.expects == [])
    check("case_clip expects is empty (disk checked)", case_clip.expects == [])
    check("case_crlf expects is empty (disk checked)", case_crlf.expects == [])

    all_written_files = [f for c in cases for f in c.files]
    check("build created all declared files on disk", all((ws_init / f).is_file() for f in all_written_files))
    check("build declared 10 total files across all cases", len(all_written_files) == 10)

    # --- 2. Size, offsets, and letter-only filler assertions -------------------------

    for f in all_written_files:
        if f == CASE_CRLF_FILENAME:
            content_len = len((ws_init / f).read_bytes())
        else:
            content_len = len((ws_init / f).read_text(encoding="utf-8"))
        check(f"file {f} length ({content_len}) exceeds MAX_OUT ({MAX_OUT})", content_len > MAX_OUT)

    # Existing 3 cases SHA-256 baseline
    existing_cases_sha256 = {
        "facility_guide.md": "ffee9be4d51de3f478075cab8ec54fcd1985210246c279074a48fbce2ef5cf23",
        "system_records.md": "6efe214c6db729f06262f8c27a4d212a1de520d4714ea51b60610337103f2600",
        "hydrology_network.txt": "25aa3907d7b64af0a2c83a43088986b0c61c234af12622beb3a573152883bdca",
        "geology_strata.txt": "f08f12a66c842366a0a31fb938e52bcf8549a2ff004f9e21294a9cc0da3ec993",
        "refuge_inventory.txt": "758a9ae3e5e72ef0656ed5484b054a6c990e6fcfa080a452bff3c2fdd2980401",
    }
    for fname, expected_hash in existing_cases_sha256.items():
        actual_hash = hashlib.sha256((ws_init / fname).read_bytes()).hexdigest()
        check(f"existing case file {fname} SHA-256 is byte-identical to baseline", actual_hash == expected_hash)

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

    # Case D: edit_duplicate_passage (operating_procedures.md)
    text_dup = (ws_init / CASE_DUP_FILENAME).read_text(encoding="utf-8")
    check("case_dup document is 10,000+ characters", len(text_dup) >= 10000)
    check("case_dup document contains all 6 section headings", all(h in text_dup for h, _ in CASE_DUP_SECTIONS))
    check("case_dup target sentence appears exactly twice", text_dup.count(CASE_DUP_TARGET_OLD) == 2)
    b_idx = text_dup.find("## Section Beta")
    e_idx = text_dup.find("## Section Epsilon")
    first_dup_offset = text_dup.find(CASE_DUP_TARGET_OLD)
    second_dup_offset = text_dup.find(CASE_DUP_TARGET_OLD, first_dup_offset + 1)
    check("case_dup Beta occurrence appears before MAX_OUT", b_idx < first_dup_offset < MAX_OUT)
    check(
        f"case_dup Epsilon occurrence ({second_dup_offset}) appears beyond MAX_OUT ({MAX_OUT})",
        second_dup_offset > MAX_OUT and second_dup_offset > e_idx,
    )
    stripped_dup = text_dup
    for _, fact in CASE_DUP_SECTIONS:
        stripped_dup = stripped_dup.replace(fact, "")
    check("case_dup document contains no digits outside its 6 fact lines", len(re.findall(r"\d", stripped_dup)) == 0)

    # Case E: edit_last_line (maintenance_log.txt)
    text_last = (ws_init / CASE_LAST_FILENAME).read_text(encoding="utf-8")
    check("case_last document is 6,000+ characters", len(text_last) >= 6000)
    check("case_last target line is the final line", text_last.endswith(f"{CASE_LAST_TARGET_OLD}\n"))
    check("case_last has single trailing newline", text_last.endswith("\n") and not text_last.endswith("\n\n"))
    last_offset = text_last.find(CASE_LAST_TARGET_OLD)
    check(f"case_last target offset ({last_offset}) exceeds MAX_OUT ({MAX_OUT})", last_offset > MAX_OUT)
    stripped_last = text_last.replace(CASE_LAST_TARGET_OLD, "")
    check("case_last document contains no digits outside target line", len(re.findall(r"\d", stripped_last)) == 0)

    # Case F: edit_special_chars (deploy_config.txt)
    text_spec = (ws_init / CASE_SPEC_FILENAME).read_text(encoding="utf-8")
    check("case_spec document is 6,000+ characters", len(text_spec) >= 6000)
    spec_offset = text_spec.find(CASE_SPEC_TARGET_OLD)
    check(f"case_spec target offset ({spec_offset}) exceeds MAX_OUT ({MAX_OUT})", spec_offset > MAX_OUT)
    check(
        "case_spec target replacement contains &, /, \\, $1 and quotes",
        "&" in CASE_SPEC_TARGET_NEW
        and "/" in CASE_SPEC_TARGET_NEW
        and "\\" in CASE_SPEC_TARGET_NEW
        and "$1" in CASE_SPEC_TARGET_NEW
        and '"' in CASE_SPEC_TARGET_NEW,
    )
    stripped_spec = text_spec.replace(CASE_SPEC_TARGET_OLD, "")
    check("case_spec document contains no digits outside target", len(re.findall(r"\d", stripped_spec)) == 0)

    # Case G: edit_across_clip (boundary_telemetry.txt)
    text_clip = (ws_init / CASE_CLIP_FILENAME).read_text(encoding="utf-8")
    check("case_clip document is 10,000+ characters", len(text_clip) >= 10000)
    clip_start = text_clip.find(CASE_CLIP_TARGET_OLD)
    clip_end = clip_start + len(CASE_CLIP_TARGET_OLD)
    check(f"case_clip target sentence starts before MAX_OUT ({clip_start} < {MAX_OUT})", clip_start < MAX_OUT)
    check(f"case_clip target sentence ends after MAX_OUT ({clip_end} > {MAX_OUT})", clip_end > MAX_OUT)
    clip_num_offset = text_clip.find("864")
    check(f"case_clip target number sits beyond MAX_OUT ({clip_num_offset} > {MAX_OUT})", clip_num_offset > MAX_OUT)
    stripped_clip = text_clip.replace(CASE_CLIP_TARGET_OLD, "")
    check("case_clip document contains no digits outside target sentence", len(re.findall(r"\d", stripped_clip)) == 0)

    # Case H: edit_crlf (sensor_readings.txt)
    bytes_crlf = (ws_init / CASE_CRLF_FILENAME).read_bytes()
    check("case_crlf document is 6,000+ bytes", len(bytes_crlf) >= 6000)
    check("case_crlf uses CRLF line endings", b"\r\n" in bytes_crlf)
    check("case_crlf contains no bare LF", not bool(re.search(rb"(?<!\r)\n", bytes_crlf)))
    crlf_target_offset = bytes_crlf.find(CASE_CRLF_TARGET_OLD.encode("utf-8"))
    check(f"case_crlf target offset ({crlf_target_offset}) exceeds MAX_OUT ({MAX_OUT})", crlf_target_offset > MAX_OUT)
    stripped_crlf = bytes_crlf.decode("utf-8").replace(CASE_CRLF_TARGET_OLD, "")
    check("case_crlf document contains no digits outside target line", len(re.findall(r"\d", stripped_crlf)) == 0)

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
          hashes_1 == hashes_2 and len(hashes_1) == 10)

    # Seed sensitivity: files differ when seed differs
    ws_seed_diff = tmp_base / "ws_seed_diff"
    build(ws_seed_diff, seed=999)
    for c in cases[3:]:
        for fname in c.files:
            orig_b = (ws_init / fname).read_bytes()
            diff_b = (ws_seed_diff / fname).read_bytes()
            check(f"case {c.name} file {fname} differs when seed differs", orig_b != diff_b)

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
    check("CLI output mentions materialised cases", "Materialised 8 cases" in proc_cli.stdout)
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

    # --- 8. Mutation tests for Case D (edit_duplicate_passage) -----------------------

    ws_mut_dup = tmp_base / "ws_mut_dup"
    mut_cases_dup = build(ws_mut_dup, seed=40)
    checker_dup = mut_cases_dup[3].check
    orig_dup = (ws_mut_dup / CASE_DUP_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: correct edit in Section Epsilon passes
    eps_marker = "## Section Epsilon"
    eps_idx = orig_dup.find(eps_marker)
    dup_target_idx = orig_dup.find(CASE_DUP_TARGET_OLD, eps_idx)
    correct_edit_dup = (
        orig_dup[:dup_target_idx]
        + CASE_DUP_TARGET_NEW
        + orig_dup[dup_target_idx + len(CASE_DUP_TARGET_OLD):]
    )
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(correct_edit_dup, encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 2: correct edit passes", passed and "updated" in reason)

    # Mutation 3: wrong copy edited (Section Beta edited instead of Section Epsilon) fails
    beta_idx = orig_dup.find(CASE_DUP_TARGET_OLD)
    wrong_copy_dup = (
        orig_dup[:beta_idx]
        + CASE_DUP_TARGET_NEW
        + orig_dup[beta_idx + len(CASE_DUP_TARGET_OLD):]
    )
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(wrong_copy_dup, encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 3: wrong copy edited fails", not passed and "Section Beta was modified" in reason)

    # Mutation 4: both copies edited fails
    both_copies_dup = orig_dup.replace(CASE_DUP_TARGET_OLD, CASE_DUP_TARGET_NEW)
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(both_copies_dup, encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 4: both copies edited fails", not passed and "both sections" in reason)

    # Mutation 5: truncated to read clip fails
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(orig_dup[:MAX_OUT], encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 5: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 6: extra change elsewhere fails
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(correct_edit_dup + "\n# Extra trailing text\n", encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 6: extra change elsewhere fails", not passed and "unexpected edits" in reason)

    # Mutation 7: heading dropped fails
    dropped_heading_dup = correct_edit_dup.replace(CASE_DUP_SECTIONS[0][0], "")
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(dropped_heading_dup, encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 7: dropped heading fails", not passed and "dropped" in reason)

    # Mutation 8: a whitespace-only change (the edit applied, final newline stripped) fails
    (ws_mut_dup / CASE_DUP_FILENAME).write_text(correct_edit_dup.rstrip("\n"), encoding="utf-8")
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup mutation 8: final newline stripped fails", not passed)

    # Missing file fails
    (ws_mut_dup / CASE_DUP_FILENAME).unlink()
    passed, reason = checker_dup(ws_mut_dup)
    check("case_dup missing file fails", not passed and "does not exist" in reason)

    # --- 9. Mutation tests for Case E (edit_last_line) -------------------------------

    ws_mut_last = tmp_base / "ws_mut_last"
    mut_cases_last = build(ws_mut_last, seed=50)
    checker_last = mut_cases_last[4].check
    orig_last = (ws_mut_last / CASE_LAST_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: correct edit passes
    correct_edit_last = orig_last.replace(CASE_LAST_TARGET_OLD, CASE_LAST_TARGET_NEW, 1)
    (ws_mut_last / CASE_LAST_FILENAME).write_text(correct_edit_last, encoding="utf-8")
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 2: correct edit passes", passed and "preserved" in reason)

    # Mutation 3: trailing newline removed fails
    (ws_mut_last / CASE_LAST_FILENAME).write_text(correct_edit_last.rstrip("\n"), encoding="utf-8")
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 3: trailing newline removed fails", not passed and "trailing newline was removed" in reason)

    # Mutation 4: extra trailing newline added fails
    (ws_mut_last / CASE_LAST_FILENAME).write_text(correct_edit_last + "\n", encoding="utf-8")
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 4: extra trailing newline added fails", not passed and "extra trailing newline was added" in reason)

    # Mutation 5: truncated to read clip fails
    (ws_mut_last / CASE_LAST_FILENAME).write_text(orig_last[:MAX_OUT], encoding="utf-8")
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 5: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 6: extra change elsewhere fails
    (ws_mut_last / CASE_LAST_FILENAME).write_text("Prefix edit\n\n" + correct_edit_last, encoding="utf-8")
    passed, reason = checker_last(ws_mut_last)
    check("case_last mutation 6: extra change elsewhere fails", not passed and "unexpected edits" in reason)

    # Missing file fails
    (ws_mut_last / CASE_LAST_FILENAME).unlink()
    passed, reason = checker_last(ws_mut_last)
    check("case_last missing file fails", not passed and "does not exist" in reason)

    # --- 10. Mutation tests for Case F (edit_special_chars) ---------------------------

    ws_mut_spec = tmp_base / "ws_mut_spec"
    mut_cases_spec = build(ws_mut_spec, seed=60)
    checker_spec = mut_cases_spec[5].check
    orig_spec = (ws_mut_spec / CASE_SPEC_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: correct edit passes
    correct_edit_spec = orig_spec.replace(CASE_SPEC_TARGET_OLD, CASE_SPEC_TARGET_NEW, 1)
    (ws_mut_spec / CASE_SPEC_FILENAME).write_text(correct_edit_spec, encoding="utf-8")
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 2: correct edit passes", passed and "special characters replacement" in reason)

    # Mutation 3: mangled replacement (dropped backslash) fails
    mangled_spec_1 = orig_spec.replace(CASE_SPEC_TARGET_OLD, 'Deployment filter rule: "token & $1" -> path/filter', 1)
    (ws_mut_spec / CASE_SPEC_FILENAME).write_text(mangled_spec_1, encoding="utf-8")
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 3: mangled replacement (dropped backslash) fails", not passed and "mangled" in reason)

    # Mutation 3b: mangled replacement (expanded &) fails
    mangled_spec_2 = orig_spec.replace(CASE_SPEC_TARGET_OLD, 'Deployment filter rule: "token default_unprocessed_stream $1" -> \\path/filter', 1)
    (ws_mut_spec / CASE_SPEC_FILENAME).write_text(mangled_spec_2, encoding="utf-8")
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 3b: mangled replacement (expanded &) fails", not passed and "mangled" in reason)

    # Mutation 4: truncated to read clip fails
    (ws_mut_spec / CASE_SPEC_FILENAME).write_text(orig_spec[:MAX_OUT], encoding="utf-8")
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 4: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 5: extra change elsewhere fails
    (ws_mut_spec / CASE_SPEC_FILENAME).write_text(correct_edit_spec + "\nExtra change\n", encoding="utf-8")
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec mutation 5: extra change elsewhere fails", not passed and "unexpected edits" in reason)

    # Missing file fails
    (ws_mut_spec / CASE_SPEC_FILENAME).unlink()
    passed, reason = checker_spec(ws_mut_spec)
    check("case_spec missing file fails", not passed and "does not exist" in reason)

    # --- 11. Mutation tests for Case G (edit_across_clip) -----------------------------

    ws_mut_clip = tmp_base / "ws_mut_clip"
    mut_cases_clip = build(ws_mut_clip, seed=70)
    checker_clip = mut_cases_clip[6].check
    orig_clip = (ws_mut_clip / CASE_CLIP_FILENAME).read_text(encoding="utf-8")

    # Mutation 1: untouched workspace fails
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: correct edit passes
    correct_edit_clip = orig_clip.replace(CASE_CLIP_TARGET_OLD, CASE_CLIP_TARGET_NEW, 1)
    (ws_mut_clip / CASE_CLIP_FILENAME).write_text(correct_edit_clip, encoding="utf-8")
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip mutation 2: correct edit passes", passed and "boundary sentence edited" in reason)

    # Mutation 3: target fact not changed fails
    wrong_edit_clip = orig_clip.replace("Boundary Telemetry", "Boundary Monitoring")
    (ws_mut_clip / CASE_CLIP_FILENAME).write_text(wrong_edit_clip, encoding="utf-8")
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip mutation 3: target fact not changed fails", not passed and "target fact was not changed" in reason)

    # Mutation 4: truncated to read clip fails
    (ws_mut_clip / CASE_CLIP_FILENAME).write_text(orig_clip[:MAX_OUT], encoding="utf-8")
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip mutation 4: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 5: extra change elsewhere fails
    (ws_mut_clip / CASE_CLIP_FILENAME).write_text(correct_edit_clip + "\nExtra change\n", encoding="utf-8")
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip mutation 5: extra change elsewhere fails", not passed and "unexpected edits" in reason)

    # Missing file fails
    (ws_mut_clip / CASE_CLIP_FILENAME).unlink()
    passed, reason = checker_clip(ws_mut_clip)
    check("case_clip missing file fails", not passed and "does not exist" in reason)

    # --- 12. Mutation tests for Case H (edit_crlf) -----------------------------------

    ws_mut_crlf = tmp_base / "ws_mut_crlf"
    mut_cases_crlf = build(ws_mut_crlf, seed=80)
    checker_crlf = mut_cases_crlf[7].check
    orig_crlf = (ws_mut_crlf / CASE_CRLF_FILENAME).read_bytes()

    # Mutation 1: untouched workspace fails
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf mutation 1: untouched workspace fails", not passed and "untouched" in reason)

    # Mutation 2: correct edit passes
    correct_edit_crlf = orig_crlf.replace(
        CASE_CRLF_TARGET_OLD.encode("utf-8"),
        CASE_CRLF_TARGET_NEW.encode("utf-8"),
        1,
    )
    (ws_mut_crlf / CASE_CRLF_FILENAME).write_bytes(correct_edit_crlf)
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf mutation 2: correct edit passes", passed and "CRLF line endings preserved" in reason)

    # Mutation 3: file converted to LF fails
    lf_converted = correct_edit_crlf.replace(b"\r\n", b"\n")
    (ws_mut_crlf / CASE_CRLF_FILENAME).write_bytes(lf_converted)
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf mutation 3: file converted to LF fails", not passed and "CRLF line endings were converted to LF" in reason)

    # Mutation 4: truncated to read clip fails
    (ws_mut_crlf / CASE_CRLF_FILENAME).write_bytes(orig_crlf[:MAX_OUT])
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf mutation 4: truncated to read clip fails", not passed and "truncated" in reason)

    # Mutation 5: extra change elsewhere fails
    (ws_mut_crlf / CASE_CRLF_FILENAME).write_bytes(correct_edit_crlf + b"Extra change\r\n")
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf mutation 5: extra change elsewhere fails", not passed and "unexpected edits" in reason)

    # Missing file fails
    (ws_mut_crlf / CASE_CRLF_FILENAME).unlink()
    passed, reason = checker_crlf(ws_mut_crlf)
    check("case_crlf missing file fails", not passed and "does not exist" in reason)

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
