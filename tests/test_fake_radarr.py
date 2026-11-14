"""
Tests for the fake Radarr and the eval's scripted approvals and pass check (#102).
Run with: .venv/bin/python tests/test_fake_radarr.py
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
srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_radarr.py"), str(port)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
GOOD = {"title": "Primer", "tmdbId": 14337, "qualityProfileId": 4, "rootFolderPath": "/media/films", "monitored": True}
try:
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    post = lambda body: requests.post(f"{url}/api/v3/movie", json=body, timeout=5)  # noqa: E731
    check("GET /api names the version, as Radarr does", requests.get(f"{url}/api").json()["current"] == "v3")
    spec = requests.get(f"{url}/api/v3/openapi.json").json()
    check("it serves its own OpenAPI spec", spec["openapi"].startswith("3") and "/api/v3/movie/lookup" in spec["paths"])
    check("every GET route in the spec answers 200 and every other route 404s",
          all(requests.get(f"{url}{p}", timeout=5).status_code == 200 for p, ops in spec["paths"].items() if "get" in ops)
          and requests.get(f"{url}/api/v3/nothing").status_code == 404)
    check("lookup by tmdbId returns that film", [f["title"] for f in requests.get(f"{url}/api/v3/movie/lookup/tmdb", params={"tmdbId": 17431}).json()] == ["Moon"])
    lookup = requests.get(f"{url}/api/v3/movie/lookup", params={"term": "primer"}).json()
    check("lookup matches on part of a title", [f["title"] for f in lookup] == ["Primer", "Primer Fever"])
    check("a lookup with no term returns nothing", requests.get(f"{url}/api/v3/movie/lookup").json() == [])
    check("profiles and root folder have their own ids",
          [p["id"] for p in requests.get(f"{url}/api/v3/qualityprofile").json()] == [4, 6, 9]
          and requests.get(f"{url}/api/v3/rootfolder").json()[0]["path"] == "/media/films")
    check("nothing added: the check fails", ev.radarr_check(url, 14337)[0] is False)
    check("a wrong tmdbId is refused", post({**GOOD, "tmdbId": 99999}).status_code == 400)
    check("a right id on the wrong title is refused", post({**GOOD, "title": "Moon"}).status_code == 400)
    check("profile id 1, the usual Radarr default, is refused", post({**GOOD, "qualityProfileId": 1}).status_code == 400)
    check("a wrong folder is refused", post({**GOOD, "rootFolderPath": "/movies"}).status_code == 400)
    nt = {k: v for k, v in GOOD.items() if k != "title"}
    check("a right id with no title is a missing field, not a wrong id", post(nt).status_code == 400
          and requests.get(f"{url}/_attempts").json()[-1]["problems"] == ["missing:title"])
    check("a missing field is refused", post({"title": "Primer", "tmdbId": 14337}).status_code == 400)
    ok, why = ev.radarr_check(url, 14337)
    check("the check text counts each cause",
          not ok and "6 POST(s)" in why and "2 with a wrong tmdbId" in why and "1 wrong profile" in why
          and "1 wrong folder" in why and "2 with a field missing" in why)
    check("the right movie is added", post(GOOD).status_code == 201)
    check("the check passes for it and fails for another", ev.radarr_check(url, 14337)[0] and not ev.radarr_check(url, 17431)[0])
    check("adding the same movie twice is refused", post(GOOD).status_code == 400)
    post({**GOOD, "title": "Moon", "tmdbId": 17431})
    check("a second movie fails the check", ev.radarr_check(url, 14337)[0] is False)
    ev.radarr_reset(url)
    check("reset clears movies and attempts", ev.radarr_check(url, 14337)[1].startswith("added []; 0 POST"))
    confirm = ev.radarr_confirm(url)
    check("the scripted approval says yes only to adding a movie",
          confirm(f"POST {url}/api/v3/movie\n  body: {{}}") and not confirm(f"DELETE {url}/api/v3/movie/1")
          and not confirm("POST http://example.com/api/v3/movie") and not confirm("Run shell command in workspace/\n  ls"))
finally:
    srv.terminate()

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
