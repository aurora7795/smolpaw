"""
Tests for the `long` Tidepool variant (#105, #123): a vessel list longer than the clip, with the answer last.
Run with: .venv/bin/python tests/test_fake_api_long.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from tests import eval as ev  # noqa: E402

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


port = ev.free_port()
url = f"http://127.0.0.1:{port}"
srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_api.py"), str(port), "long"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)

    body = requests.get(f"{url}/v2/vessels", timeout=5).text
    vessels = requests.get(f"{url}/v2/vessels", timeout=5).json()
    check("the list has 60 vessels", len(vessels) == 60)
    check("the plain list is longer than the clip", len(body) > g.MAX_OUT)
    check("Kestrel, the biggest, is the last and lies past the cut", "Kestrel" not in body[:g.MAX_OUT] and vessels[-1]["name"] == "Kestrel")
    check("no other vessel holds as much as Kestrel", all(v["hold_tons"] < 340 for v in vessels[:-1]))
    clipped = g._clip(body, g.CLIP_HINT_REQUEST)
    check("the clipped list does not show the answer, and the marker says to ask for less",
          "Kestrel" not in clipped and "limit, filter or page" in clipped)
    os.environ["SMOLPAW_OLD_CLIP_MARKER"] = "1"
    old = g._clip(body, g.CLIP_HINT_REQUEST)
    del os.environ["SMOLPAW_OLD_CLIP_MARKER"]
    check("SMOLPAW_OLD_CLIP_MARKER restores the old marker, without counts or hint",
          old.endswith(f"\n... [truncated, {len(body)} chars total]") and "limit" not in old)
    top = requests.get(f"{url}/v2/vessels?sort=hold_tons&order=desc&limit=1", timeout=5).json()
    check("sorting by hold, descending, limit 1 returns Kestrel", len(top) == 1 and top[0]["name"] == "Kestrel")
    check("limit alone returns that many vessels in id order",
          [v["id"] for v in requests.get(f"{url}/v2/vessels?limit=3", timeout=5).json()] == [1, 2, 3])
    check("the index names the query parameters", "sort" in requests.get(url, timeout=5).json().get("query", {}).get("vessels", ""))
    check("one vessel by id works", requests.get(f"{url}/v2/vessels/60", timeout=5).json()["name"] == "Kestrel")
finally:
    srv.terminate()

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
