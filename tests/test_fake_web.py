"""
Tests for the deterministic fake web server and search endpoint (tests/fake_web.py).
Run with: .venv/bin/python tests/test_fake_web.py

Tests must not write to the real workspace/, notes.md or logs/.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generic_tools as g
from tests.fake_web import (
    FACT_SENTENCES,
    FACTS,
    PAGE_TITLES,
    PAGE_SPECS,
    start,
)

check_failed = 0


def check(name: str, cond: bool) -> None:
    global check_failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check_failed += 1


real_logs = Path(__file__).resolve().parent.parent / "logs"
logs_snapshot = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()

# Direct test logging away from real logs/ directory
tmp_dir = Path(tempfile.mkdtemp())
saved_log_file = g._log_file
g._log_file = tmp_dir / "test-fake-web-log.jsonl"

try:
    # --- Fact uniqueness & structure checks ---------------------------------------

    slugs = ("orrin", "vale", "tarn")
    check("facts table contains exactly three slugs", set(FACTS.keys()) == set(slugs))

    for s in slugs:
        check(f"facts table for {s} contains exactly 6 facts", len(FACTS[s]) == 6)

    all_values = [f["value"] for s in slugs for f in FACTS[s]]
    check("all 18 fact values are distinct across all pages", len(all_values) == len(set(all_values)))

    all_keys = [f["key"] for s in slugs for f in FACTS[s]]
    check("all 18 fact keys are distinct across all pages", len(all_keys) == len(set(all_keys)))

    # --- Server lifecycle and HTTP response determinism ----------------------------

    server, base_url = start(port=0)
    server_port = server.server_address[1]
    check("server starts on 127.0.0.1 with dynamic port > 0", server_port > 0 and base_url == f"http://127.0.0.1:{server_port}")

    for s in slugs:
        page_url = f"{base_url}/pages/{s}"

        # 1. Page returns 200 with HTML and is byte-identical across requests
        with urlopen(page_url) as r1:
            code1 = r1.status
            ctype1 = r1.headers.get_content_type()
            body1 = r1.read()
        with urlopen(page_url) as r2:
            code2 = r2.status
            body2 = r2.read()

        check(f"page {s} returns HTTP 200 with text/html", code1 == 200 and ctype1 == "text/html")
        check(f"page {s} is byte-identical across two requests", body1 == body2 and len(body1) > 0)

        # 2. Text length after HTML conversion must exceed 4,000 characters
        page_text = g.html_to_text(body1.decode("utf-8"))
        check(f"page {s} converted text exceeds 4,000 characters", len(page_text) > 4000)

        # 3. No digits outside facts (strip facts and check)
        stripped_text = page_text
        for sent in FACT_SENTENCES[s]:
            stripped_text = stripped_text.replace(sent, "")
        digits_left = re.findall(r"\d", stripped_text)
        check(f"page {s} text has no digits outside the facts", len(digits_left) == 0)

    # --- Fetch page through real generic_tools.fetch_page --------------------------

    for s in slugs:
        page_url = f"{base_url}/pages/{s}"

        # Empty query returns top of page, hits length cap, does NOT contain all 6 facts
        top_res = g.fetch_page(page_url, "")
        check(f"fetch_page {s} empty query is long (near 2500 char cap)", len(top_res) >= 2500)
        facts_in_top = [f["value"] in top_res for f in FACTS[s]]
        check(f"fetch_page {s} empty query does NOT contain all six fact values", not all(facts_in_top))
        check(f"fetch_page {s} empty query contains at least one fact value", any(facts_in_top))

        # Query for each fact finds its value
        for f in FACTS[s]:
            fact_res = g.fetch_page(page_url, f["key"])
            check(f"fetch_page {s} query for '{f['key']}' finds '{f['value']}'", f["value"] in fact_res)

    # --- Real search path through generic_tools.web_search -------------------------

    saved_provider = os.environ.get("SMOLPAW_SEARCH_PROVIDER")
    saved_search_url = os.environ.get("SMOLPAW_SEARCH_URL")
    try:
        os.environ["SMOLPAW_SEARCH_PROVIDER"] = "searxng"
        os.environ["SMOLPAW_SEARCH_URL"] = base_url

        for s in slugs:
            g.reset_search_count()
            # Build query from this page's facts
            query = f"{FACTS[s][0]['key']} {FACTS[s][1]['key']}"
            search_out = g.web_search(query)

            # All 3 page URLs must come back
            expected_urls = [f"{base_url}/pages/{target}" for target in slugs]
            all_returned = all(u in search_out for u in expected_urls)
            check(f"web_search for {s} facts returns all three page URLs", all_returned)

            # Best match must be first
            first_url = ""
            for line in search_out.splitlines():
                line_s = line.strip()
                if line_s.startswith("http://"):
                    first_url = line_s
                    break
            check(f"web_search for {s} facts places {s} as the best match first", first_url == f"{base_url}/pages/{s}")

    finally:
        if saved_provider is not None:
            os.environ["SMOLPAW_SEARCH_PROVIDER"] = saved_provider
        else:
            os.environ.pop("SMOLPAW_SEARCH_PROVIDER", None)
        if saved_search_url is not None:
            os.environ["SMOLPAW_SEARCH_URL"] = saved_search_url
        else:
            os.environ.pop("SMOLPAW_SEARCH_URL", None)
        g.reset_search_count()

    # --- 404 and robustness checks -------------------------------------------------

    # Unknown paths give 404
    for bad_path in ("/unknown", "/pages/nonexistent", "/", "/pages", "/search/extra"):
        try:
            with urlopen(f"{base_url}{bad_path}") as resp:
                status = resp.status
        except Exception as exc:
            status = getattr(exc, "code", 500)
        check(f"unknown path '{bad_path}' returns 404", status == 404)

    # Robustness on /search: odd query strings, empty q, very long q
    for q_test in ("", "odd=%FF%FE&another=val", "q=", "q=" + "a" * 10000, "q=???&&&format=json"):
        with urlopen(f"{base_url}/search?{q_test}") as resp:
            check(f"search endpoint does not crash on '{q_test[:25]}...'", resp.status == 200)

    # --- Clean shutdown ------------------------------------------------------------

    server.shutdown()
    server.server_close()
    check("server shut down cleanly", True)

    # --- CLI invocation check ------------------------------------------------------

    proc = subprocess.Popen(
        [sys.executable, "-u", "tests/fake_web.py", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        banner = proc.stdout.readline()
        check("CLI fake_web.py starts and announces port", "FakeWeb running on http://127.0.0.1:" in banner)
    finally:
        proc.terminate()
        proc.wait(timeout=2.0)

finally:
    g._log_file = saved_log_file

# --- Isolation test ----------------------------------------------------------------

if real_logs.exists():
    after = {(p.name, p.stat().st_size) for p in real_logs.iterdir()}
    check("the test suite wrote no run logs to the real logs/ directory", after == logs_snapshot)

print(f"\n{check_failed} failed")
sys.exit(1 if check_failed else 0)
