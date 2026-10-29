"""
Deterministic tracking fixture generator for long-document reading and writing eval (#87).

Generates test cases to evaluate whether models keep track of what they read and write
in files longer than the read clip (MAX_OUT), without dropping or truncating content.

Run standalone:
  .venv/bin/python tests/tracking_fixture.py <output_dir> [seed]

Importable:
  from tests.tracking_fixture import Case, build
  cases = build(workspace_path, seed=0)
"""

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generic_tools import MAX_OUT
from tests.fake_web import FILLER_WORDS

REAL_WORKSPACE = (ROOT / "workspace").resolve()
REAL_NOTES = (ROOT / "notes.md").resolve()
REAL_MEMORY = (ROOT / "memory.md").resolve()


@dataclass
class Case:
    name: str
    prompt: str
    files: list[str]
    expects: list[str]
    check: Callable[[Path], tuple[bool, str]]


# --- Case specifications & facts -------------------------------------------------

CASE_A_FILENAME = "facility_guide.md"
CASE_A_TITLE = "# Facility Engineering Guide and Operational Specifications"
CASE_A_SECTIONS = [
    (
        "## Section Alpha: Primary Power Generation",
        "The primary generator turbine operates at a continuous output of 520 kilowatts.",
    ),
    (
        "## Section Beta: Environmental Control System",
        "The environmental control intake maintains ventilation flow across 140 air ducts.",
    ),
    (
        "## Section Gamma: Structural Foundation Pillars",
        "The structural foundation resting frame is anchored by 75 granite columns.",
    ),
    (
        "## Section Delta: Atmospheric Pressure Monitoring",
        "The barometric sensor network reports an ambient baseline of 960 millibars.",
    ),
    (
        "## Section Epsilon: Water Treatment and Reservoir Flow",
        "The secondary spillway channel discharges water at 310 litres per second.",
    ),
    (
        "## Section Zeta: Auxiliary Battery Storage",
        "The auxiliary battery storage bank maintains a reserve capacity of 420 kilowatt hours.",
    ),
    (
        "## Section Eta: Emergency Heating Array",
        "The emergency heating element produces a thermal radiation output of 880 watts.",
    ),
    (
        "## Section Theta: Solar Radiation Shielding",
        "The perimeter radiation shielding canopy spans an aperture of 260 metres.",
    ),
]
CASE_A_TARGET_OLD = "The auxiliary battery storage bank maintains a reserve capacity of 420 kilowatt hours."
CASE_A_TARGET_NEW = "The auxiliary battery storage bank maintains a reserve capacity of 980 kilowatt hours."

CASE_B_FILENAME = "system_records.md"
CASE_B_TITLE = "# Station Operational Logs and Maintenance Records"
CASE_B_HEADINGS = [
    "## Primary System Overview",
    "## Environmental Monitoring Registry",
    "## Structural Maintenance Log",
    "## Auxiliary Power Distribution",
]
CASE_B_NEW_HEADING = "## Archive Verification Status"
CASE_B_NEW_BODY = "All station telemetry logs and system records have been verified and archived."
CASE_B_NEW_SECTION = f"{CASE_B_NEW_HEADING}\n{CASE_B_NEW_BODY}"

CASE_C_FILES = [
    "hydrology_network.txt",
    "geology_strata.txt",
    "refuge_inventory.txt",
]
CASE_C_FACTS = [
    ("hydrology_network.txt", "1485", "Peak catchment flow rate recorded at the gorge weir: 1485 litres per second."),
    ("geology_strata.txt", "832", "The exploratory granite bedrock drill reached a total depth of 832 metres."),
    ("refuge_inventory.txt", "674", "The auxiliary emergency heating kerosene store holds 674 litres."),
]
CASE_C_EXPECTS = [rf"\b{fact[1]}\b" for fact in CASE_C_FACTS]

CASE_DUP_FILENAME = "operating_procedures.md"
CASE_DUP_TITLE = "# Operational Specifications and Unit Capacity Guide"
CASE_DUP_SECTIONS = [
    ("## Section Alpha: Primary Intake Configuration", "The baseline intake filtration rate is 460 litres per minute."),
    ("## Section Beta: Secondary Processing Unit", "The maximum rated operational load for this unit is 750 kilograms."),
    ("## Section Gamma: Thermal Exchange Network", "The thermal exchange core temperature ceiling is 640 kelvins."),
    ("## Section Delta: Atmospheric Venting System", "The atmospheric exhaust valve releases 580 cubic metres per hour."),
    ("## Section Epsilon: Mechanical Recovery Unit", "The maximum rated operational load for this unit is 750 kilograms."),
    ("## Section Zeta: Emergency Reservoir Station", "The emergency reserve tank capacity is 950 litres."),
]
CASE_DUP_TARGET_OLD = "The maximum rated operational load for this unit is 750 kilograms."
CASE_DUP_TARGET_NEW = "The maximum rated operational load for this unit is 920 kilograms."

CASE_LAST_FILENAME = "maintenance_log.txt"
CASE_LAST_TITLE = "# Facility Maintenance Log and Scheduled Service Records"
CASE_LAST_TARGET_OLD = "Final scheduled inspection countdown interval: 85 days."
CASE_LAST_TARGET_NEW = "Final scheduled inspection countdown interval: 140 days."

CASE_SPEC_FILENAME = "deploy_config.txt"
CASE_SPEC_TITLE = "# System Deployment and Pipeline Configuration Registry"
CASE_SPEC_TARGET_OLD = "Deployment filter rule: default_unprocessed_stream"
CASE_SPEC_TARGET_NEW = 'Deployment filter rule: "token & $1" -> \\path/filter'

CASE_CLIP_FILENAME = "boundary_telemetry.txt"
CASE_CLIP_TITLE = "# Boundary Telemetry and Atmosphere Monitoring Station"
CASE_CLIP_TARGET_OLD = (
    "The environmental ventilation telemetry monitor records an operational airflow velocity of "
    "864 feet per minute across the boundary aperture."
)
CASE_CLIP_TARGET_NEW = (
    "The environmental ventilation telemetry monitor records an operational airflow velocity of "
    "932 feet per minute across the boundary aperture."
)

CASE_CRLF_FILENAME = "sensor_readings.txt"
CASE_CRLF_TITLE = "# Environmental Sensor Network Telemetry Registry"
CASE_CRLF_TARGET_OLD = "Secondary circulation intake pump telemetry: 1420 rotations per minute."
CASE_CRLF_TARGET_NEW = "Secondary circulation intake pump telemetry: 1850 rotations per minute."


# --- Deterministic text generators -----------------------------------------------

def _make_filler_paragraph(rng: random.Random, min_chars: int) -> str:
    """Generate a single paragraph of filler containing letters and spaces only, no digits."""
    sentences = []
    total = 0
    while total < min_chars:
        length = rng.randint(10, 16)
        words = [rng.choice(FILLER_WORDS) for _ in range(length)]
        sentence = " ".join(words).capitalize() + "."
        sentences.append(sentence)
        total += len(sentence) + 1
    return " ".join(sentences)


def _make_filler_paragraphs(rng: random.Random, min_chars: int, p_count: int = 3) -> str:
    """Generate multi-paragraph filler containing letters, spaces, and newlines only."""
    paragraphs = []
    chars_per_p = max(100, min_chars // max(1, p_count))
    total = 0
    while total < min_chars or len(paragraphs) < p_count:
        p = _make_filler_paragraph(rng, chars_per_p)
        paragraphs.append(p)
        total += len(p) + 2
    return "\n\n".join(paragraphs)


def _generate_case_a_text(seed: int) -> str:
    rng = random.Random(seed + 101)
    parts = [f"{CASE_A_TITLE}\n\n"]
    for heading, fact in CASE_A_SECTIONS:
        p1 = _make_filler_paragraph(rng, 650)
        p2 = _make_filler_paragraph(rng, 650)
        parts.append(f"{heading}\n\n{p1}\n\n{fact}\n\n{p2}\n\n")
    return "".join(parts).strip() + "\n"


def _generate_case_b_text(seed: int) -> str:
    rng = random.Random(seed + 202)
    parts = [f"{CASE_B_TITLE}\n\n"]
    for heading in CASE_B_HEADINGS:
        p1 = _make_filler_paragraph(rng, 700)
        p2 = _make_filler_paragraph(rng, 700)
        parts.append(f"{heading}\n\n{p1}\n\n{p2}\n\n")
    return "".join(parts).strip() + "\n"


def _generate_case_c_texts(seed: int) -> dict[str, str]:
    rng = random.Random(seed + 303)

    # File 1: Markdown hierarchy with gorge weir flow rate
    f1_pre = "# Hydrology Network Field Log\n\n" + _make_filler_paragraphs(rng, 4200, 6)
    f1_fact = f"\n\n{CASE_C_FACTS[0][2]}\n\n"
    f1_post = _make_filler_paragraphs(rng, 1200, 2)
    f1 = (f1_pre + f1_fact + f1_post).strip() + "\n"

    # File 2: Part-based structure with bedrock drill depth
    f2_pre = (
        "PART ONE: Core Sample Extraction\n\n"
        + _make_filler_paragraphs(rng, 2100, 3)
        + "\n\nPART TWO: Lithology and Structural Analysis\n\n"
        + _make_filler_paragraphs(rng, 2200, 3)
    )
    f2_fact = f"\n\n{CASE_C_FACTS[1][2]}\n\n"
    f2_post = _make_filler_paragraphs(rng, 1400, 2)
    f2 = (f2_pre + f2_fact + f2_post).strip() + "\n"

    # File 3: Station manifest layout with kerosene store volume
    f3_pre = (
        "[REFUGE MANIFEST: HIGH PASS STATION]\n\n== Bulk Supply Storage ==\n\n"
        + _make_filler_paragraphs(rng, 2000, 3)
        + "\n\n== Thermal Heating Reserves ==\n\n"
        + _make_filler_paragraphs(rng, 2100, 3)
    )
    f3_fact = f"\n\n{CASE_C_FACTS[2][2]}\n\n"
    f3_post = "== Emergency Utility Depot ==\n\n" + _make_filler_paragraphs(rng, 1200, 2)
    f3 = (f3_pre + f3_fact + f3_post).strip() + "\n"

    return {
        CASE_C_FILES[0]: f1,
        CASE_C_FILES[1]: f2,
        CASE_C_FILES[2]: f3,
    }


def _generate_case_dup_text(seed: int) -> str:
    rng = random.Random(seed + 404)
    parts = [f"{CASE_DUP_TITLE}\n\n"]
    for heading, fact in CASE_DUP_SECTIONS:
        p1 = _make_filler_paragraph(rng, 800)
        p2 = _make_filler_paragraph(rng, 800)
        parts.append(f"{heading}\n\n{p1}\n\n{fact}\n\n{p2}\n\n")
    return "".join(parts).strip() + "\n"


def _generate_case_last_text(seed: int) -> str:
    rng = random.Random(seed + 505)
    pre = f"{CASE_LAST_TITLE}\n\n" + _make_filler_paragraphs(rng, 6100, 6)
    return pre.strip() + f"\n\n{CASE_LAST_TARGET_OLD}\n"


def _generate_case_spec_text(seed: int) -> str:
    rng = random.Random(seed + 606)
    pre = f"{CASE_SPEC_TITLE}\n\n" + _make_filler_paragraphs(rng, 4500, 5)
    post = _make_filler_paragraphs(rng, 1800, 2)
    return (pre.strip() + f"\n\n{CASE_SPEC_TARGET_OLD}\n\n" + post.strip()).strip() + "\n"


def _generate_case_clip_text(seed: int) -> str:
    rng = random.Random(seed + 707)
    header = f"{CASE_CLIP_TITLE}\n\n"
    paragraphs = []
    total_len = len(header)
    while total_len < 3800:
        length = rng.randint(10, 16)
        words = [rng.choice(FILLER_WORDS) for _ in range(length)]
        sentence = " ".join(words).capitalize() + "."
        paragraphs.append(sentence)
        total_len += len(sentence) + 2
    # Reach precisely around offset 3940 so target sentence starts before 4000 and ends after 4000
    needed = 3940 - total_len
    final_words = []
    cur = 0
    while cur < needed - 15:
        w = rng.choice(FILLER_WORDS)
        final_words.append(w)
        cur += len(w) + 1
    rem = needed - cur
    candidates = [w for w in FILLER_WORDS if len(w) == rem - 1]
    if candidates:
        w = rng.choice(candidates)
    else:
        candidates = sorted(FILLER_WORDS, key=lambda w: abs(len(w) - (rem - 1)))
        w = candidates[0]
    final_words.append(w)
    final_sentence = " ".join(final_words).capitalize() + "."
    paragraphs.append(final_sentence)
    pre = header + "\n\n".join(paragraphs) + "\n\n"
    post = "\n\n" + _make_filler_paragraphs(rng, 6500, 6)
    return (pre + CASE_CLIP_TARGET_OLD + post).strip() + "\n"


def _generate_case_crlf_bytes(seed: int) -> bytes:
    rng = random.Random(seed + 808)
    pre = f"{CASE_CRLF_TITLE}\n\n" + _make_filler_paragraphs(rng, 4500, 5)
    post = _make_filler_paragraphs(rng, 1800, 2)
    unix_text = (pre.strip() + f"\n\n{CASE_CRLF_TARGET_OLD}\n\n" + post.strip()).strip() + "\n"
    crlf_text = unix_text.replace("\n", "\r\n")
    return crlf_text.encode("utf-8")


# --- Public API ------------------------------------------------------------------

def build(workspace: Path | str, seed: int = 0) -> list[Case]:
    """Materialise tracking eval test fixtures into workspace and return Case descriptors."""
    ws = Path(workspace).resolve()

    # Safety checks: never write into the real workspace/ directory or repo notes/memory
    if ws == REAL_WORKSPACE or REAL_WORKSPACE in ws.parents:
        raise ValueError(f"Refusing to write into repository workspace/ directory: {ws}")
    if ws == REAL_NOTES or REAL_NOTES in ws.parents or ws == REAL_MEMORY or REAL_MEMORY in ws.parents:
        raise ValueError(f"Refusing to write into repository protected files: {ws}")

    ws.mkdir(parents=True, exist_ok=True)

    # 1. Case A: edit_one_section
    text_a = _generate_case_a_text(seed)
    file_a = ws / CASE_A_FILENAME
    file_a.write_text(text_a, encoding="utf-8")
    expected_text_a = text_a.replace(CASE_A_TARGET_OLD, CASE_A_TARGET_NEW, 1)

    def check_a(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_A_FILENAME
        if not p.is_file():
            return False, f"{CASE_A_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_a:
            return False, "file was not modified (untouched workspace)"
        if current == expected_text_a:
            return True, "file equals original with exactly the target line changed"
        if len(current) <= MAX_OUT and text_a.startswith(current):
            return False, f"file was truncated to the read clip ({len(current)} <= {MAX_OUT})"
        if text_a.startswith(current) and len(current) < len(text_a):
            return False, f"file was truncated ({len(current)} < {len(text_a)})"
        for heading, _ in CASE_A_SECTIONS:
            if heading not in current:
                return False, f"section heading '{heading}' was dropped or modified"
        if CASE_A_TARGET_OLD in current and CASE_A_TARGET_NEW not in current:
            return False, "target fact line was not changed"
        if CASE_A_TARGET_OLD not in current and CASE_A_TARGET_NEW not in current:
            return False, "target fact line was removed but replacement was not found"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_a = Case(
        name="edit_one_section",
        prompt=(
            f"In {CASE_A_FILENAME}, change the auxiliary battery storage bank reserve capacity from "
            "420 kilowatt hours to 980 kilowatt hours. Leave all other text exactly as it is."
        ),
        files=[CASE_A_FILENAME],
        expects=[],
        check=check_a,
    )

    # 2. Case B: append_keep_all
    text_b = _generate_case_b_text(seed)
    file_b = ws / CASE_B_FILENAME
    file_b.write_text(text_b, encoding="utf-8")

    def check_b(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_B_FILENAME
        if not p.is_file():
            return False, f"{CASE_B_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_b:
            return False, "file was not modified (untouched workspace)"
        if not current.startswith(text_b):
            common = os.path.commonprefix([current, text_b])
            if len(common) <= MAX_OUT:
                return False, f"original content was truncated to read clip ({len(common)} <= {MAX_OUT}) before appending"
            if len(common) < len(text_b):
                return False, f"original content was truncated ({len(common)} < {len(text_b)}) before appending"
            return False, "original content is not an exact prefix of new content (existing text was modified or dropped)"
        remainder = current[len(text_b):]
        if current.count(CASE_B_NEW_HEADING) == 0:
            return False, f"appended section heading '{CASE_B_NEW_HEADING}' is missing"
        if current.count(CASE_B_NEW_HEADING) > 1:
            return False, f"appended section heading '{CASE_B_NEW_HEADING}' is present more than once"
        if current.count(CASE_B_NEW_BODY) == 0:
            return False, "appended section body is missing"
        if current.count(CASE_B_NEW_BODY) > 1:
            return False, "appended section body is present more than once"
        if remainder.strip() != CASE_B_NEW_SECTION:
            return False, "appended content differs from expected section or contains extra text"
        return True, "original content is an exact prefix and new section is present once"

    case_b = Case(
        name="append_keep_all",
        prompt=(
            f"In {CASE_B_FILENAME}, add a new section at the end:\n\n"
            f"{CASE_B_NEW_SECTION}\n\n"
            "Leave all existing content intact."
        ),
        files=[CASE_B_FILENAME],
        expects=[],
        check=check_b,
    )

    # 3. Case C: read_three_report
    texts_c = _generate_case_c_texts(seed)
    for fname, fcontent in texts_c.items():
        (ws / fname).write_text(fcontent, encoding="utf-8")

    def check_c(target_ws: Path | str) -> tuple[bool, str]:
        target_path = Path(target_ws).resolve()
        missing = [f for f in CASE_C_FILES if not (target_path / f).is_file()]
        if missing:
            return False, f"missing files: {', '.join(missing)}"
        changed = [f for f in CASE_C_FILES if (target_path / f).read_text(encoding="utf-8") != texts_c[f]]
        if changed:
            return False, f"files were modified: {', '.join(changed)}"
        return True, "all files present and unmodified (the answer is checked via expects)"

    case_c = Case(
        name="read_three_report",
        prompt=(
            f"Read {', '.join(CASE_C_FILES)}. "
            "Report the key figure (number) recorded in each file."
        ),
        files=list(CASE_C_FILES),
        expects=list(CASE_C_EXPECTS),
        check=check_c,
    )

    # 4. Case D: edit_duplicate_passage
    text_dup = _generate_case_dup_text(seed)
    file_dup = ws / CASE_DUP_FILENAME
    file_dup.write_text(text_dup, encoding="utf-8")
    eps_marker = "## Section Epsilon"
    eps_idx = text_dup.find(eps_marker)
    dup_target_idx = text_dup.find(CASE_DUP_TARGET_OLD, eps_idx)
    expected_text_dup = (
        text_dup[:dup_target_idx]
        + CASE_DUP_TARGET_NEW
        + text_dup[dup_target_idx + len(CASE_DUP_TARGET_OLD):]
    )

    def check_dup(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_DUP_FILENAME
        if not p.is_file():
            return False, f"{CASE_DUP_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_dup:
            return False, "file was not modified (untouched workspace)"
        if current == expected_text_dup:
            return True, "Section Epsilon copy updated while Section Beta copy and all other text remain byte for byte"
        if len(current) <= MAX_OUT and text_dup.startswith(current):
            return False, f"file was truncated to the read clip ({len(current)} <= {MAX_OUT})"
        if text_dup.startswith(current) and len(current) < len(text_dup):
            return False, f"file was truncated ({len(current)} < {len(text_dup)})"
        for heading, _ in CASE_DUP_SECTIONS:
            if heading not in current:
                return False, f"section heading '{heading}' was dropped or modified"
        beta_pos = current.find("## Section Beta")
        epsilon_pos = current.find("## Section Epsilon")
        if beta_pos != -1 and epsilon_pos != -1:
            beta_to_eps = current[beta_pos:epsilon_pos]
            eps_onward = current[epsilon_pos:]
            if CASE_DUP_TARGET_NEW in beta_to_eps and CASE_DUP_TARGET_OLD in eps_onward:
                return False, "target sentence in Section Beta was modified instead of Section Epsilon"
            if CASE_DUP_TARGET_NEW in beta_to_eps and CASE_DUP_TARGET_NEW in eps_onward:
                return False, "target sentence was modified in both sections instead of only Section Epsilon"
        if CASE_DUP_TARGET_OLD in current and current.count(CASE_DUP_TARGET_OLD) == 2:
            return False, "target sentence in Section Epsilon was not changed"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_dup = Case(
        name="edit_duplicate_passage",
        prompt=(
            f"In {CASE_DUP_FILENAME}, under Section Epsilon, change the rated operational load from "
            f"'{CASE_DUP_TARGET_OLD}' to '{CASE_DUP_TARGET_NEW}'. "
            "Leave Section Beta and all other text exactly as it is."
        ),
        files=[CASE_DUP_FILENAME],
        expects=[],
        check=check_dup,
    )

    # 5. Case E: edit_last_line
    text_last = _generate_case_last_text(seed)
    file_last = ws / CASE_LAST_FILENAME
    file_last.write_text(text_last, encoding="utf-8")
    expected_text_last = text_last.replace(CASE_LAST_TARGET_OLD, CASE_LAST_TARGET_NEW, 1)

    def check_last(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_LAST_FILENAME
        if not p.is_file():
            return False, f"{CASE_LAST_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_last:
            return False, "file was not modified (untouched workspace)"
        if current == expected_text_last:
            return True, "final line value changed and trailing newline preserved"
        if len(current) <= MAX_OUT and text_last.startswith(current):
            return False, f"file was truncated to the read clip ({len(current)} <= {MAX_OUT})"
        if text_last.startswith(current) and len(current) < len(text_last):
            return False, f"file was truncated ({len(current)} < {len(text_last)})"
        if not current.endswith("\n"):
            return False, "trailing newline was removed from final line"
        if current.endswith("\n\n"):
            return False, "extra trailing newline was added to final line"
        if CASE_LAST_TARGET_OLD in current and CASE_LAST_TARGET_NEW not in current:
            return False, "target value on final line was not changed"
        if CASE_LAST_TARGET_OLD not in current and CASE_LAST_TARGET_NEW not in current:
            return False, "target value on final line was removed but replacement was not found"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_last = Case(
        name="edit_last_line",
        prompt=(
            f"In {CASE_LAST_FILENAME}, change the final line from "
            f"'{CASE_LAST_TARGET_OLD}' to '{CASE_LAST_TARGET_NEW}'. "
            "Leave all other text and the trailing newline unchanged."
        ),
        files=[CASE_LAST_FILENAME],
        expects=[],
        check=check_last,
    )

    # 6. Case F: edit_special_chars
    text_spec = _generate_case_spec_text(seed)
    file_spec = ws / CASE_SPEC_FILENAME
    file_spec.write_text(text_spec, encoding="utf-8")
    expected_text_spec = text_spec.replace(CASE_SPEC_TARGET_OLD, CASE_SPEC_TARGET_NEW, 1)

    def check_spec(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_SPEC_FILENAME
        if not p.is_file():
            return False, f"{CASE_SPEC_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_spec:
            return False, "file was not modified (untouched workspace)"
        if current == expected_text_spec:
            return True, "file equals original with special characters replacement byte for byte"
        if len(current) <= MAX_OUT and text_spec.startswith(current):
            return False, f"file was truncated to the read clip ({len(current)} <= {MAX_OUT})"
        if text_spec.startswith(current) and len(current) < len(text_spec):
            return False, f"file was truncated ({len(current)} < {len(text_spec)})"
        if CASE_SPEC_TARGET_OLD in current and CASE_SPEC_TARGET_NEW not in current:
            return False, "target line was not changed"
        if CASE_SPEC_TARGET_OLD not in current and CASE_SPEC_TARGET_NEW not in current:
            return False, "replacement text was mangled or improperly escaped"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_spec = Case(
        name="edit_special_chars",
        prompt=(
            f"In {CASE_SPEC_FILENAME}, change "
            f"'{CASE_SPEC_TARGET_OLD}' to '{CASE_SPEC_TARGET_NEW}'. "
            "Leave all other text exactly as it is."
        ),
        files=[CASE_SPEC_FILENAME],
        expects=[],
        check=check_spec,
    )

    # 7. Case G: edit_across_clip
    text_clip = _generate_case_clip_text(seed)
    file_clip = ws / CASE_CLIP_FILENAME
    file_clip.write_text(text_clip, encoding="utf-8")
    expected_text_clip = text_clip.replace(CASE_CLIP_TARGET_OLD, CASE_CLIP_TARGET_NEW, 1)

    def check_clip(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_CLIP_FILENAME
        if not p.is_file():
            return False, f"{CASE_CLIP_FILENAME} does not exist"
        current = p.read_text(encoding="utf-8")
        if current == text_clip:
            return False, "file was not modified (untouched workspace)"
        if current == expected_text_clip:
            return True, "file equals original with boundary sentence edited byte for byte"
        if len(current) <= MAX_OUT and text_clip.startswith(current):
            return False, f"file was truncated to the read clip ({len(current)} <= {MAX_OUT})"
        if text_clip.startswith(current) and len(current) < len(text_clip):
            return False, f"file was truncated ({len(current)} < {len(text_clip)})"
        if CASE_CLIP_TARGET_OLD in current and CASE_CLIP_TARGET_NEW not in current:
            return False, "target fact was not changed"
        if CASE_CLIP_TARGET_OLD not in current and CASE_CLIP_TARGET_NEW not in current:
            return False, "target fact was removed but replacement was not found"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_clip = Case(
        name="edit_across_clip",
        prompt=(
            f"In {CASE_CLIP_FILENAME}, change the airflow velocity in the boundary aperture sentence from "
            "'864 feet per minute' to '932 feet per minute'. "
            "Leave all other text exactly as it is."
        ),
        files=[CASE_CLIP_FILENAME],
        expects=[],
        check=check_clip,
    )

    # 8. Case H: edit_crlf
    bytes_crlf = _generate_case_crlf_bytes(seed)
    file_crlf = ws / CASE_CRLF_FILENAME
    file_crlf.write_bytes(bytes_crlf)
    expected_bytes_crlf = bytes_crlf.replace(
        CASE_CRLF_TARGET_OLD.encode("utf-8"),
        CASE_CRLF_TARGET_NEW.encode("utf-8"),
        1,
    )

    def check_crlf(target_ws: Path | str) -> tuple[bool, str]:
        p = Path(target_ws).resolve() / CASE_CRLF_FILENAME
        if not p.is_file():
            return False, f"{CASE_CRLF_FILENAME} does not exist"
        current_bytes = p.read_bytes()
        if current_bytes == bytes_crlf:
            return False, "file was not modified (untouched workspace)"
        if current_bytes == expected_bytes_crlf:
            return True, "file equals original with target line changed and CRLF line endings preserved"
        if current_bytes == expected_bytes_crlf.replace(b"\r\n", b"\n") or bool(re.search(rb"(?<!\r)\n", current_bytes)):
            return False, "CRLF line endings were converted to LF"
        if len(current_bytes) <= MAX_OUT and bytes_crlf.startswith(current_bytes):
            return False, f"file was truncated to the read clip ({len(current_bytes)} <= {MAX_OUT})"
        if bytes_crlf.startswith(current_bytes) and len(current_bytes) < len(bytes_crlf):
            return False, f"file was truncated ({len(current_bytes)} < {len(bytes_crlf)})"
        if CASE_CRLF_TARGET_OLD.encode("utf-8") in current_bytes and CASE_CRLF_TARGET_NEW.encode("utf-8") not in current_bytes:
            return False, "target line was not changed"
        if CASE_CRLF_TARGET_OLD.encode("utf-8") not in current_bytes and CASE_CRLF_TARGET_NEW.encode("utf-8") not in current_bytes:
            return False, "target line was removed but replacement was not found"
        return False, "file differs from expected content (unexpected edits, dropped content, or extra changes)"

    case_crlf = Case(
        name="edit_crlf",
        prompt=(
            f"In {CASE_CRLF_FILENAME}, change the secondary circulation intake pump telemetry from "
            f"'{CASE_CRLF_TARGET_OLD}' to '{CASE_CRLF_TARGET_NEW}'. "
            "Preserve all line endings and leave all other content intact."
        ),
        files=[CASE_CRLF_FILENAME],
        expects=[],
        check=check_crlf,
    )

    return [
        case_a,
        case_b,
        case_c,
        case_dup,
        case_last,
        case_spec,
        case_clip,
        case_crlf,
    ]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/tracking_fixture.py <output_dir> [seed]", file=sys.stderr)
        sys.exit(1)
    out_dir = Path(sys.argv[1])
    seed_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    try:
        built_cases = build(out_dir, seed=seed_arg)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Materialised {len(built_cases)} cases into {out_dir}:")
    for c in built_cases:
        print(f"  - {c.name}: {', '.join(c.files)}")
