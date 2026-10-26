"""
Tests for cron parser and schedule store. Run with: .venv/bin/python tests/test_schedules.py
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schedules

tmp = Path(tempfile.mkdtemp())
schedules.PATH = tmp / "schedules.json"


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0

# --- Cron parser: valid expressions and concrete expected datetimes ---

# */15 * * * * (every 15 minutes)
check(
    "*/15 * * * * advances to next 15-minute slot",
    schedules.next_run("*/15 * * * *", datetime(2026, 10, 26, 12, 0))
    == datetime(2026, 10, 26, 12, 15),
)
check(
    "*/15 * * * * rolls over hour",
    schedules.next_run("*/15 * * * *", datetime(2026, 10, 26, 12, 45))
    == datetime(2026, 10, 26, 13, 0),
)

# 0 9 * * 1-5 (weekday mornings at 09:00)
# 2026-10-26 is Monday.
check(
    "0 9 * * 1-5 advances to next weekday morning",
    schedules.next_run("0 9 * * 1-5", datetime(2026, 10, 26, 8, 30))
    == datetime(2026, 10, 26, 9, 0),
)
# From Friday 2026-10-30 09:00, next run is Monday 2026-11-02 09:00
check(
    "0 9 * * 1-5 skips weekend from Friday to Monday",
    schedules.next_run("0 9 * * 1-5", datetime(2026, 10, 30, 9, 0))
    == datetime(2026, 11, 2, 9, 0),
)

# 30 2 1 * * (1st of month at 02:30)
check(
    "30 2 1 * * advances to 1st of next month",
    schedules.next_run("30 2 1 * *", datetime(2026, 1, 1, 2, 30))
    == datetime(2026, 2, 1, 2, 30),
)

# 0 0 * * 0 and 0 0 * * 7 give the same result (Sunday midnight)
# 2026-10-25 is Sunday. From Sunday midnight, next is 2026-11-01.
dt_ref = datetime(2026, 10, 25, 0, 0)
res_0 = schedules.next_run("0 0 * * 0", dt_ref)
res_7 = schedules.next_run("0 0 * * 7", dt_ref)
check("0 0 * * 0 produces Sunday", res_0 == datetime(2026, 11, 1, 0, 0))
check("0 0 * * 0 and 0 0 * * 7 give the same result", res_0 == res_7)

# Month and weekday names (case-insensitive)
check(
    "month and weekday names jan and mon",
    schedules.next_run("0 10 * jan mon", datetime(2026, 1, 1, 0, 0))
    == datetime(2026, 1, 5, 10, 0),  # 2026-01-05 is first Monday of Jan
)
check(
    "case-insensitive month and weekday names",
    schedules.next_run("0 10 * JAN MON", datetime(2026, 1, 1, 0, 0))
    == datetime(2026, 1, 5, 10, 0),
)

# Lists: a,b,c
check(
    "comma-separated list in minute field",
    schedules.next_run("5,20,35 * * * *", datetime(2026, 10, 26, 10, 5))
    == datetime(2026, 10, 26, 10, 20),
)

# Steps on ranges: a-b/n
check(
    "a-b/n range step in hour field",
    schedules.next_run("0 9-17/2 * * *", datetime(2026, 10, 26, 9, 0))
    == datetime(2026, 10, 26, 11, 0),
)

# Combinations like 1-5,10
check(
    "combinations 1-5,10 in minute field",
    schedules.next_run("1-5,10 * * * *", datetime(2026, 10, 26, 10, 4))
    == datetime(2026, 10, 26, 10, 5),
)
check(
    "combinations 1-5,10 advancing to list element",
    schedules.next_run("1-5,10 * * * *", datetime(2026, 10, 26, 10, 5))
    == datetime(2026, 10, 26, 10, 10),
)

# Weekday range with sun at end: fri-sun
check(
    "fri-sun weekday range",
    schedules.next_run("0 0 * * fri-sun", datetime(2026, 10, 29, 0, 0))  # Thursday
    == datetime(2026, 10, 30, 0, 0),  # Friday
)

# --- Standard Vixie-cron day rule ---
# When both day-of-month and day-of-week are restricted: EITHER matches.
# 0 0 1 * 1: matches if 1st of month OR Monday.
# 2026-10-01 is Thursday (matches DOM 1).
# From 2026-10-01 00:00:
# Oct 2 (Fri), Oct 3 (Sat), Oct 4 (Sun) do not match.
# Oct 5 is Monday -> matches DOW 1!
check(
    "day rule both restricted matches on DOW when DOM differs",
    schedules.next_run("0 0 1 * 1", datetime(2026, 10, 1, 0, 0))
    == datetime(2026, 10, 5, 0, 0),
)
# From Monday 2026-10-26 00:00:
# Next match is Sunday 2026-11-01 (matches DOM 1 even though Sunday)!
check(
    "day rule both restricted matches on DOM when DOW differs",
    schedules.next_run("0 0 1 * 1", datetime(2026, 10, 26, 0, 0))
    == datetime(2026, 11, 1, 0, 0),
)

# Only day-of-month restricted: only DOM applies.
# 0 0 1 * *: from 2026-10-01 00:00, next is 2026-11-01 (does NOT match Oct 5 Monday).
check(
    "day rule DOM alone restricted ignores weekdays",
    schedules.next_run("0 0 1 * *", datetime(2026, 10, 1, 0, 0))
    == datetime(2026, 11, 1, 0, 0),
)

# Only day-of-week restricted: only DOW applies.
# 0 0 * * 1: from 2026-10-26 00:00 (Monday), next is Monday 2026-11-02 (does NOT match Nov 1 Sunday).
check(
    "day rule DOW alone restricted ignores DOM",
    schedules.next_run("0 0 * * 1", datetime(2026, 10, 26, 0, 0))
    == datetime(2026, 11, 2, 0, 0),
)

# --- Rollovers and strictly-after semantics ---

# End of month rollover
check(
    "end of month rollover",
    schedules.next_run("0 0 1 * *", datetime(2026, 1, 31, 23, 59))
    == datetime(2026, 2, 1, 0, 0),
)

# End of year rollover
check(
    "end of year rollover",
    schedules.next_run("0 0 1 1 *", datetime(2026, 12, 31, 23, 59))
    == datetime(2027, 1, 1, 0, 0),
)

# Leap day: 0 0 29 2 * from 2027-01-01 -> 2028-02-29
check(
    "leap day rollover from non-leap year 2027 to 2028",
    schedules.next_run("0 0 29 2 *", datetime(2027, 1, 1, 0, 0))
    == datetime(2028, 2, 29, 0, 0),
)

# Strictly-after semantics: starting exactly on a matching minute returns the NEXT matching minute
check(
    "strictly-after semantics from exact matching minute",
    schedules.next_run("0 12 * * *", datetime(2026, 10, 26, 12, 0))
    == datetime(2026, 10, 27, 12, 0),
)
check(
    "strictly-after ignores non-zero seconds on after datetime",
    schedules.next_run("*/5 * * * *", datetime(2026, 10, 26, 12, 0, 45))
    == datetime(2026, 10, 26, 12, 5),
)

# --- Invalid inputs: raises ValueError and names the bad field ---


def raises_and_names(expr: str, expected_field: str) -> bool:
    try:
        schedules.next_run(expr, datetime(2026, 1, 1))
        return False
    except ValueError as e:
        return expected_field.lower() in str(e).lower()


# Wrong field count
check("invalid field count: 4 fields", raises_and_names("* * * *", "field"))
check("invalid field count: 6 fields", raises_and_names("* * * * * *", "field"))
check("invalid field count: empty string", raises_and_names("", "field"))

# Out of range
check("out of range: minute 60", raises_and_names("60 * * * *", "minute"))
check("out of range: minute -1", raises_and_names("-1 * * * *", "minute"))
check("out of range: hour 24", raises_and_names("* 24 * * *", "hour"))
check("out of range: hour -1", raises_and_names("* -1 * * *", "hour"))
check("out of range: day-of-month 0", raises_and_names("* * 0 * *", "day-of-month"))
check("out of range: day-of-month 32", raises_and_names("* * 32 * *", "day-of-month"))
check("out of range: month 0", raises_and_names("* * * 0 *", "month"))
check("out of range: month 13", raises_and_names("* * * 13 *", "month"))
check("out of range: day-of-week 8", raises_and_names("* * * * 8", "day-of-week"))
check("out of range: day-of-week -1", raises_and_names("* * * * -1", "day-of-week"))

# Bad step
check("bad step: zero step */0", raises_and_names("*/0 * * * *", "minute"))
check("bad step: negative step */-1", raises_and_names("*/-1 * * * *", "minute"))
check("bad step: empty step */", raises_and_names("*/ * * * *", "minute"))
check("bad step: non-numeric step */abc", raises_and_names("*/abc * * * *", "minute"))
check("bad step: zero step on range 1-5/0", raises_and_names("1-5/0 * * * *", "minute"))

# Empty list item
check("empty list item: double comma 1,,2", raises_and_names("1,,2 * * * *", "minute"))
check("empty list item: leading comma ,1", raises_and_names(",1 * * * *", "minute"))
check("empty list item: trailing comma 1,", raises_and_names("1, * * * *", "minute"))
check("empty list item: bare commas ,,,", raises_and_names(",,, * * * *", "minute"))

# Junk / malformed tokens
check("junk: non-numeric string in minute", raises_and_names("abc * * * *", "minute"))
check("junk: bad range 1-2-3", raises_and_names("1-2-3 * * * *", "minute"))
check("junk: range start > end 5-2", raises_and_names("5-2 * * * *", "minute"))
check("junk: unknown month name foo", raises_and_names("* * * foo *", "month"))
check("junk: unknown weekday name bar", raises_and_names("* * * * bar", "day-of-week"))

# Expressions that can never fire
check("never fires: Feb 31 (0 0 31 2 *)", raises_and_names("0 0 31 2 *", "day-of-month"))
check("never fires: Feb 30 (0 0 30 2 *)", raises_and_names("0 0 30 2 *", "day-of-month"))
check("never fires: Apr 31 (0 0 31 4 *)", raises_and_names("0 0 31 4 *", "day-of-month"))
check("never fires: 31st of months without 31", raises_and_names("0 0 31 2,4,6,9,11 *", "day-of-month"))

# --- DST handling ---
# Assumption: Naive datetimes represent local wall-clock time; on spring-forward,
# skipped hours fire once as soon as the clock reaches or exceeds the target time;
# on fall-back, mark_ran advances next_run past the current day so the repeated
# hour fires only once without looping.
#
# Fixed spring-forward example: 2026-03-29 in Europe/London (clock skips 01:00-01:59 to 02:00 BST).
# (Or in US Eastern: 2026-03-08, skipping 02:00-02:59 to 03:00).
# Testing a daily 01:30 schedule around UK spring-forward:
dst_tmp = tmp / "dst_schedules.json"
saved_path = schedules.PATH
schedules.PATH = dst_tmp
try:
    if dst_tmp.exists():
        dst_tmp.unlink()
    s = schedules.add("daily check", "30 1 * * *", now=datetime(2026, 3, 28, 1, 30))
    check("DST schedule next_run initialized", s["next_run"] == "2026-03-29T01:30:00")

    # On spring forward, the clock advances directly from 01:00 to 02:00.
    # At 02:00, due() must detect that 01:30 <= 02:00 (not skipped!).
    due_jobs = schedules.due(datetime(2026, 3, 29, 2, 0))
    check("DST spring-forward: skipped time is not lost, fires at 02:00", len(due_jobs) == 1)

    # Calling mark_ran advances next_run to 2026-03-30 01:30.
    schedules.mark_ran(s["id"], datetime(2026, 3, 29, 2, 0))
    updated = schedules.load()[0]
    check("DST spring-forward: next_run advanced to tomorrow", updated["next_run"] == "2026-03-30T01:30:00")
    check("DST spring-forward: not due again immediately", len(schedules.due(datetime(2026, 3, 29, 2, 0))) == 0)

    # Fixed fall-back example: 2026-10-25 in Europe/London (clock repeats 01:00-01:59).
    # A daily 01:30 schedule fires on the first occurrence of 01:30.
    dst_tmp.unlink()
    s2 = schedules.add("daily check 2", "30 1 * * *", now=datetime(2026, 10, 24, 1, 30))
    check("DST fall-back initialized", s2["next_run"] == "2026-10-25T01:30:00")
    due_first = schedules.due(datetime(2026, 10, 25, 1, 30))
    check("DST fall-back: fires on first 01:30", len(due_first) == 1)
    schedules.mark_ran(s2["id"], datetime(2026, 10, 25, 1, 30))

    # When 01:30 occurs a second time (or any time later that day, e.g. 01:45 or second 01:30):
    due_second = schedules.due(datetime(2026, 10, 25, 1, 30))
    check("DST fall-back: does not fire twice during repeated hour", len(due_second) == 0)
    check("DST fall-back: next_run moved to next day", schedules.load()[0]["next_run"] == "2026-10-26T01:30:00")
finally:
    schedules.PATH = saved_path
    if dst_tmp.exists():
        dst_tmp.unlink()

# --- Schedule store ---

# Reset test store
store_tmp = tmp / "store_test.json"
schedules.PATH = store_tmp
if store_tmp.exists():
    store_tmp.unlink()

# Missing file returns empty list
check("load() on missing file returns empty list", schedules.load() == [])

# Add schedule
s1 = schedules.add("check queue", "0 9 * * 1-5", now=datetime(2026, 10, 26, 8, 0))
check("add() returns dict with id", isinstance(s1.get("id"), str) and len(s1["id"]) == 8)
check("add() returns prompt", s1.get("prompt") == "check queue")
check("add() returns cron", s1.get("cron") == "0 9 * * 1-5")
check("add() enabled is True", s1.get("enabled") is True)
check("add() last_run is None", s1.get("last_run") is None)
check("add() sets next_run", s1.get("next_run") == "2026-10-26T09:00:00")

# Add second schedule
s2 = schedules.add("nightly cleanup", "0 0 * * *", now=datetime(2026, 10, 26, 8, 0))
check("add() creates unique ids", s1["id"] != s2["id"])

# Prompt validation
def prompt_rejected(prompt_val: str) -> bool:
    try:
        schedules.add(prompt_val, "0 0 * * *")
        return False
    except ValueError:
        return True

check("add() rejects empty prompt", prompt_rejected(""))
check("add() rejects whitespace prompt", prompt_rejected("   \n\t  "))
check("add() rejects prompt over 4000 characters", prompt_rejected("x" * 4001))
check("add() accepts prompt of exactly 4000 characters", len(schedules.add("x" * 4000, "0 0 * * *")["prompt"]) == 4000)

# Invalid cron rejected by add
def cron_rejected(cron_val: str) -> bool:
    try:
        schedules.add("test prompt", cron_val)
        return False
    except ValueError:
        return True

check("add() rejects invalid cron expression", cron_rejected("invalid cron"))

# Load schedules
loaded = schedules.load()
check("load() returns all added schedules", len(loaded) == 3)

# set_enabled
sid1 = s1["id"]
check("set_enabled() returns True when found", schedules.set_enabled(sid1, False) is True)
loaded_disabled = [s for s in schedules.load() if s["id"] == sid1][0]
check("set_enabled() persists False", loaded_disabled["enabled"] is False)
check("set_enabled() returns False for unknown id", schedules.set_enabled("nonexistent", True) is False)
schedules.set_enabled(sid1, True)
check("set_enabled() restores True", [s for s in schedules.load() if s["id"] == sid1][0]["enabled"] is True)

# due()
# s1 has next_run 2026-10-26T09:00:00.
check("due() before next_run returns empty list", len(schedules.due(datetime(2026, 10, 26, 8, 59))) == 0)
due_at_9 = schedules.due(datetime(2026, 10, 26, 9, 0))
check("due() at next_run returns schedule", len(due_at_9) >= 1 and any(s["id"] == sid1 for s in due_at_9))
# Disabled schedule is never due
schedules.set_enabled(sid1, False)
check("due() skips disabled schedules", not any(s["id"] == sid1 for s in schedules.due(datetime(2026, 10, 26, 9, 0))))
schedules.set_enabled(sid1, True)

# mark_ran()
schedules.mark_ran(sid1, datetime(2026, 10, 26, 9, 0))
s1_after_ran = [s for s in schedules.load() if s["id"] == sid1][0]
check("mark_ran() updates last_run", s1_after_ran["last_run"] == "2026-10-26T09:00:00")
check("mark_ran() advances next_run", s1_after_ran["next_run"] == "2026-10-27T09:00:00")

# mark_ran on unknown id raises KeyError
def mark_ran_raises(bad_id: str) -> bool:
    try:
        schedules.mark_ran(bad_id, datetime.now())
        return False
    except KeyError:
        return True

check("mark_ran() raises KeyError on unknown id", mark_ran_raises("nonexistent_id"))

# Missed slots fire once (laptop asleep scenario)
# A schedule was scheduled for 09:00. Laptop slept until 18:00.
# At 18:00 it is due. mark_ran advances next_run to next slot after 18:00 (tomorrow 09:00),
# so it does not fire again for the missed slots.
missed_tmp = tmp / "missed_test.json"
schedules.PATH = missed_tmp
try:
    sm = schedules.add("daily sync", "0 9 * * *", now=datetime(2026, 10, 25, 9, 0))
    # next_run is 2026-10-26 09:00. Laptop wakes up at 18:00.
    wake_time = datetime(2026, 10, 26, 18, 0)
    due_missed = schedules.due(wake_time)
    check("missed slot: schedule is due after sleep", len(due_missed) == 1 and due_missed[0]["id"] == sm["id"])
    schedules.mark_ran(sm["id"], wake_time)
    # Checked immediately after mark_ran at the same wake_time
    check("missed slot: fires only once, not due again at same time", len(schedules.due(wake_time)) == 0)
    check(
        "missed slot: next_run is strictly after wake_time",
        schedules.load()[0]["next_run"] == "2026-10-27T09:00:00",
    )
finally:
    if missed_tmp.exists():
        missed_tmp.unlink()

schedules.PATH = store_tmp

# remove()
check("remove() returns True when found", schedules.remove(sid1) is True)
check("remove() removes entry from store", not any(s["id"] == sid1 for s in schedules.load()))
check("remove() returns False for unknown id", schedules.remove("nonexistent") is False)

# Atomic writes leave no stray temp files
files_in_dir = list(tmp.iterdir())
check(
    "atomic write leaves no stray temp files",
    all(not f.name.startswith("tmp") for f in files_in_dir if f.is_file() and f != store_tmp),
)

# Corrupt JSON file raises ValueError without modifying file
corrupt_tmp = tmp / "corrupt.json"
schedules.PATH = corrupt_tmp
corrupt_content = '{"broken": [json'
corrupt_tmp.write_text(corrupt_content, encoding="utf-8")
def corrupt_raises() -> bool:
    try:
        schedules.load()
        return False
    except ValueError as e:
        return "corrupt" in str(e).lower()

check("corrupt JSON raises clear ValueError from load()", corrupt_raises())
check("corrupt file is untouched on load failure", corrupt_tmp.read_text(encoding="utf-8") == corrupt_content)

# Non-list JSON file raises ValueError without modifying file
non_list_tmp = tmp / "non_list.json"
schedules.PATH = non_list_tmp
non_list_content = '{"id": "not_a_list"}'
non_list_tmp.write_text(non_list_content, encoding="utf-8")
def non_list_raises() -> bool:
    try:
        schedules.load()
        return False
    except ValueError as e:
        return "list" in str(e).lower()

check("non-list JSON raises clear ValueError from load()", non_list_raises())
check("non-list file is untouched on load failure", non_list_tmp.read_text(encoding="utf-8") == non_list_content)

# Clean up corrupt test files
corrupt_tmp.unlink()
non_list_tmp.unlink()

# Concurrent add calls from several threads do not lose entries
concurrent_tmp = tmp / "concurrent.json"
schedules.PATH = concurrent_tmp
NUM_THREADS = 8
ITEMS_PER_THREAD = 6
barrier = threading.Barrier(NUM_THREADS)


def worker(thread_idx: int) -> None:
    barrier.wait()
    for item_idx in range(ITEMS_PER_THREAD):
        schedules.add(f"thread-{thread_idx}-item-{item_idx}", "*/5 * * * *")


threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
for t in threads:
    t.start()
for t in threads:
    t.join()

final_entries = schedules.load()
check(
    "concurrent add calls preserve all entries without loss",
    len(final_entries) == NUM_THREADS * ITEMS_PER_THREAD,
)
unique_prompts = {e["prompt"] for e in final_entries}
check(
    "concurrent add calls preserve unique entries",
    len(unique_prompts) == NUM_THREADS * ITEMS_PER_THREAD,
)
check(
    "concurrent add leaves no stray temp files",
    len([f for f in tmp.iterdir() if f.name.startswith("tmp")]) == 0,
)

# Clean up
if concurrent_tmp.exists():
    concurrent_tmp.unlink()
if store_tmp.exists():
    store_tmp.unlink()

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
