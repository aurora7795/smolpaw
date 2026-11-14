"""
Tests for the booking fixture (#102): Tidepool's `book` variant and the eval's scripted approvals and pass check.
Run with: .venv/bin/python tests/test_book_fixture.py
"""

import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests import eval as ev  # noqa: E402

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


port = ev.free_port()
url = f"http://127.0.0.1:{port}"
srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_api.py"), str(port), "book"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    post = lambda body: requests.post(f"{url}/v2/reservations", json=body, timeout=5)  # noqa: E731
    check("the index lists reservations", "reservations" in requests.get(url).json()["resources"])
    check("berths carry ids and the vessel list is not in id order",
          requests.get(f"{url}/v2/berths").json()[6] == {"id": 41, "code": "C1"}
          and [v["id"] for v in requests.get(f"{url}/v2/vessels").json()] != [1, 2, 3, 4, 5])
    check("nothing booked yet: the check fails", ev.book_check(url)[0] is False)
    check("a wrong vessel id is refused with 404", post({"vesselId": 3, "berthId": 99}).status_code == 404)
    check("a missing field is refused with 422", post({"vesselId": 4}).status_code == 422)
    ok, why = ev.book_check(url)
    check("refused writes are counted in the check text", not ok and "2 POST(s)" in why and "2 refused" in why)
    check("the right booking is created", post({"vesselId": ev.OSPREY_ID, "berthId": ev.C1_ID}).status_code == 201)
    ok, why = ev.book_check(url)
    check("the right booking passes the check even after earlier refusals", ok and "2 refused" in why)
    post({"vesselId": ev.OSPREY_ID, "berthId": 24})
    check("a second, different booking fails the check", ev.book_check(url)[0] is False)
    ev.book_reset(url)
    check("reset clears bookings and attempts", ev.book_check(url)[1].startswith("reservations []; 0 POST"))
    confirm = ev.book_confirm(url)
    check("the scripted approval says yes only to the reservations POST",
          confirm(f"POST {url}/v2/reservations\n  body: {{}}") and not confirm(f"POST {url}/v2/other")
          and not confirm("POST http://example.com/v2/reservations") and not confirm("Run shell command in workspace/\n  ls"))
finally:
    srv.terminate()

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
