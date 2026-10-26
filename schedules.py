"""
Cron expression parser and schedule store.
Pure Python module with no external dependencies and no network/model access.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading

PATH: Path = Path(__file__).resolve().parent / "schedules.json"
MAX_PROMPT: int = 4_000
_LOCK: threading.RLock = threading.RLock()

MONTH_NAMES: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
WEEKDAY_NAMES: dict[str, int] = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}
MAX_DAYS_PER_MONTH: dict[int, int] = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}


def _parse_field_val(
    token: str, field_name: str, min_val: int, max_val: int, is_range_end: bool
) -> int:
    """Parse an individual value (number or name) within a cron field."""
    token_lower = token.lower()
    if field_name == "month" and token_lower in MONTH_NAMES:
        val = MONTH_NAMES[token_lower]
    elif field_name == "day-of-week" and token_lower in WEEKDAY_NAMES:
        # If 'sun' is at the end of a range (e.g. fri-sun), treat as 7 so start <= end.
        val = 7 if (is_range_end and token_lower == "sun") else WEEKDAY_NAMES[token_lower]
    else:
        if not (token.isascii() and token.isdigit()):  # int() would also accept "1_0", "+5", " 5"
            raise ValueError(f"Invalid {field_name}: invalid value {token!r}")
        val = int(token)
    if val < min_val or val > max_val:
        raise ValueError(f"Invalid {field_name}: value {val} out of range ({min_val}-{max_val})")
    return val


def _parse_field(
    expr: str, field_name: str, min_val: int, max_val: int
) -> tuple[set[int], bool]:
    """Parse a single cron field, returning (matched_values, is_unrestricted_star)."""
    if not expr:
        raise ValueError(f"Invalid {field_name}: empty field")
    is_star = expr.startswith("*")  # Vixie: a leading * (also "*/n") selects the AND day rule
    items = expr.split(",")
    values: set[int] = set()
    for item in items:
        if not item:
            raise ValueError(f"Invalid {field_name}: empty list item")
        if "/" in item:
            parts = item.split("/")
            if len(parts) != 2:
                raise ValueError(f"Invalid {field_name}: bad step syntax {item!r}")
            base, step_str = parts
            if not (step_str.isascii() and step_str.isdigit()) or int(step_str) <= 0:
                raise ValueError(f"Invalid {field_name}: step must be a positive integer, got {step_str!r}")
            step = int(step_str)
            if base == "*":
                start_val, end_val = min_val, max_val
            elif "-" in base:
                rparts = base.split("-")
                if len(rparts) != 2 or not rparts[0] or not rparts[1]:
                    raise ValueError(f"Invalid {field_name}: bad range {base!r}")
                start_val = _parse_field_val(rparts[0], field_name, min_val, max_val, False)
                end_val = _parse_field_val(rparts[1], field_name, min_val, max_val, True)
                if start_val > end_val:
                    raise ValueError(f"Invalid {field_name}: range start {start_val} must be <= end {end_val}")
            else:
                raise ValueError(f"Invalid {field_name}: bad step base {base!r}")
            for v in range(start_val, end_val + 1, step):
                values.add(v % 7 if field_name == "day-of-week" else v)
        elif "-" in item:
            rparts = item.split("-")
            if len(rparts) != 2 or not rparts[0] or not rparts[1]:
                raise ValueError(f"Invalid {field_name}: bad range {item!r}")
            start_val = _parse_field_val(rparts[0], field_name, min_val, max_val, False)
            end_val = _parse_field_val(rparts[1], field_name, min_val, max_val, True)
            if start_val > end_val:
                raise ValueError(f"Invalid {field_name}: range start {start_val} must be <= end {end_val}")
            for v in range(start_val, end_val + 1):
                values.add(v % 7 if field_name == "day-of-week" else v)
        elif item == "*":
            for v in range(min_val, max_val + 1):
                values.add(v % 7 if field_name == "day-of-week" else v)
        else:
            v = _parse_field_val(item, field_name, min_val, max_val, False)
            values.add(v % 7 if field_name == "day-of-week" else v)
    return values, is_star


def parse_cron(
    expr: str,
) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    """Parse and validate a 5-field cron expression."""
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid field count: expected 5 fields, got {len(fields)}")
    minutes, _ = _parse_field(fields[0], "minute", 0, 59)
    hours, _ = _parse_field(fields[1], "hour", 0, 23)
    doms, dom_star = _parse_field(fields[2], "day-of-month", 1, 31)
    months, _ = _parse_field(fields[3], "month", 1, 12)
    dows, dow_star = _parse_field(fields[4], "day-of-week", 0, 7)

    dom_restricted = not dom_star
    dow_restricted = not dow_star

    # Reject expressions whose day-of-month can never occur in the specified months
    if dom_restricted and not dow_restricted:
        if not any(d <= MAX_DAYS_PER_MONTH[m] for m in months for d in doms):
            raise ValueError(f"Invalid day-of-month: expression can never fire for month(s) {sorted(months)}")

    return minutes, hours, doms, months, dows, dom_restricted, dow_restricted


def next_run(expr: str, after: datetime) -> datetime:
    """Return the first matching minute strictly after after (seconds zeroed)."""
    minutes, hours, doms, months, dows, dom_restricted, dow_restricted = parse_cron(expr)

    # DST: times are naive wall-clock values. Spring-forward: a skipped minute fires as soon as the
    # clock passes it. Fall-back: next_run is computed from "now", so the repeated hour never fires
    # twice, but a job due within it may wait until the clock reaches its next slot again.
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_year = cur.year + 5

    def day_matches(y: int, m: int, d: int) -> bool:
        # In Python, Monday is 0 and Sunday is 6; map to cron (0=Sunday, 1=Monday, ..., 6=Saturday).
        cron_dow = (datetime(y, m, d).weekday() + 1) % 7
        if dom_restricted and dow_restricted:
            return d in doms or cron_dow in dows
        return d in doms and cron_dow in dows  # a field starting with * matches every value unless stepped

    while cur.year <= max_year:
        if cur.month not in months:
            next_m = [m for m in months if m > cur.month]
            if next_m:
                cur = datetime(cur.year, min(next_m), 1, 0, 0)
            else:
                cur = datetime(cur.year + 1, min(months), 1, 0, 0)
            continue

        days_in_m = calendar.monthrange(cur.year, cur.month)[1]
        if not day_matches(cur.year, cur.month, cur.day):
            next_d = None
            for d in range(cur.day + 1, days_in_m + 1):
                if day_matches(cur.year, cur.month, d):
                    next_d = d
                    break
            if next_d is not None:
                cur = datetime(cur.year, cur.month, next_d, 0, 0)
            else:
                next_m = [m for m in months if m > cur.month]
                if next_m:
                    cur = datetime(cur.year, min(next_m), 1, 0, 0)
                else:
                    cur = datetime(cur.year + 1, min(months), 1, 0, 0)
            continue

        if cur.hour not in hours:
            next_h = [h for h in hours if h > cur.hour]
            if next_h:
                cur = datetime(cur.year, cur.month, cur.day, min(next_h), 0)
            else:
                cur = datetime(cur.year, cur.month, cur.day, 0, 0) + timedelta(days=1)
            continue

        next_mins = [mn for mn in minutes if mn >= cur.minute]
        if next_mins:
            return datetime(cur.year, cur.month, cur.day, cur.hour, min(next_mins))

        cur = datetime(cur.year, cur.month, cur.day, cur.hour, 0) + timedelta(hours=1)

    raise ValueError("No matching run time found within 5 years")


def _atomic_save(schedules: list[dict]) -> None:
    """Save schedules to PATH atomically via tempfile and os.replace."""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=PATH.parent, delete=False, encoding="utf-8") as f:
            tmp_path = Path(f.name)
            json.dump(schedules, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, PATH)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def load() -> list[dict]:
    """Load schedules from schedules.json, returning an empty list if missing."""
    with _LOCK:
        if not PATH.exists():
            return []
        try:
            content = PATH.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"Failed to read schedules file {PATH}: {e}") from e
        try:
            data = json.loads(content)
        except Exception as e:
            raise ValueError(f"Corrupt schedules file {PATH}: {e}") from e
        if not isinstance(data, list):
            raise ValueError(
                f"Invalid schedules file {PATH}: expected JSON array/list, got {type(data).__name__}"
            )
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid schedules file {PATH}: entries must be dicts")
        return data


def add(prompt: str, cron: str, now: datetime | None = None) -> dict:
    """Add a new schedule, returning the created schedule dict."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError(f"Prompt must be non-empty and at most {MAX_PROMPT} characters")
    if not isinstance(cron, str) or not cron.strip():
        raise ValueError("Cron expression must be a non-empty string")

    now_dt = now if now is not None else datetime.now()
    next_dt = next_run(cron, now_dt)

    with _LOCK:
        schedules = load()
        existing_ids = {s.get("id") for s in schedules}
        sid = secrets.token_hex(4)
        while sid in existing_ids:
            sid = secrets.token_hex(4)

        item = {
            "id": sid,
            "prompt": prompt,
            "cron": cron,
            "enabled": True,
            "last_run": None,
            "next_run": next_dt.isoformat(),
        }
        schedules.append(item)
        _atomic_save(schedules)
        return item


def remove(id: str) -> bool:
    """Remove a schedule by id. Returns True if removed, False if not found."""
    with _LOCK:
        schedules = load()
        initial_len = len(schedules)
        schedules = [s for s in schedules if s.get("id") != id]
        if len(schedules) == initial_len:
            return False
        _atomic_save(schedules)
        return True


def set_enabled(id: str, enabled: bool) -> bool:
    """Enable or disable a schedule by id. Returns True if found, False otherwise."""
    with _LOCK:
        schedules = load()
        found = False
        for s in schedules:
            if s.get("id") == id:
                s["enabled"] = bool(enabled)
                found = True
                break
        if not found:
            return False
        _atomic_save(schedules)
        return True


def due(now: datetime) -> list[dict]:
    """Return enabled schedules whose next_run <= now."""
    with _LOCK:
        schedules = load()
        result: list[dict] = []
        for s in schedules:
            if not s.get("enabled"):
                continue
            nr = s.get("next_run")
            if not nr:
                continue
            try:
                nr_dt = datetime.fromisoformat(nr)
            except ValueError:
                continue
            if nr_dt <= now:
                result.append(s)
        return result


def mark_ran(id: str, now: datetime) -> None:
    """Mark schedule as ran, updating last_run to now and computing next_run from now."""
    with _LOCK:
        schedules = load()
        found = False
        for s in schedules:
            if s.get("id") == id:
                found = True
                s["last_run"] = now.isoformat()
                s["next_run"] = next_run(s["cron"], now).isoformat()
                break
        if not found:
            raise KeyError(f"Schedule not found: {id}")
        _atomic_save(schedules)
