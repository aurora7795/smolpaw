"""
Tests for the real-Radarr eval helpers (#1), run against tests/fake_radarr.py: film resolution, the scripted approver,
the read-back check and the cleanup report. No real service is touched.
Run with: .venv/bin/python tests/test_real_radarr.py
"""

import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests import eval as ev  # noqa: E402
from tests import real_radarr as rr  # noqa: E402

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
POOL = [("Primer", 2004), ("Moon", 2009), ("Arrival", 2016), ("No Such Film", 1999)]
BODY = {"title": "Primer", "tmdbId": 14337, "qualityProfileId": 4, "rootFolderPath": "/media/films", "monitored": True}
try:
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    post = lambda body: requests.post(f"{url}/api/v3/movie", json=body, timeout=5)  # noqa: E731
    prompt = lambda tmdb, rest="": f'POST {url}/api/v3/movie\n  body: {{"title": "x", "tmdbId": {tmdb}{rest}}}'  # noqa: E731

    check("a local server is local, a LAN address is not",
          rr.is_local(url) and rr.is_local("http://localhost:7878") and not rr.is_local("http://192.168.1.50:7878")
          and not rr.is_local("http://127.0.0.1.example.com"))

    films, skipped, found = rr.resolve_films(url, "", POOL)
    check("pool films are resolved by exact title and year",
          [(f.title, f.tmdb_id) for f in films] == [("Primer", 14337), ("Moon", 17431), ("Arrival", 329865)])
    check("a film the lookup cannot find is skipped with a reason, not guessed",
          len(skipped) == 1 and "No Such Film" in skipped[0] and "not found" in skipped[0])
    check("the wrong year is not a match",
          rr.resolve_films(url, "", [("Primer", 1999)])[0] == [])
    check("every found pool film is in the pool ids", found == {14337, 17431, 329865})
    post(BODY)
    films2, skipped2, found2 = rr.resolve_films(url, "", POOL)
    check("a film already in the library is skipped but still counts as a pool film",
          [f.title for f in films2] == ["Moon", "Arrival"] and any("already in the library" in s for s in skipped2)
          and 14337 in found2)
    requests.post(f"{url}/_reset", timeout=5)

    check("the tmdbId is read from a prompt preview", rr.preview_tmdb_id(prompt(123)) == 123)
    check("a preview with no tmdbId gives none", rr.preview_tmdb_id(f"POST {url}/api/v3/movie\n  body: {{\"title\": \"x\"") is None)

    actions: list[str] = []
    ap = rr.Approver(url, {14337, 17431, 329865}, actions, current=14337)
    check("the film for this run is approved", ap.confirm(prompt(14337)) and ap.approved == [14337])
    actions.append(f"POST {url}/api/v3/movie -> HTTP 400")
    check("after a refused write (HTTP 400, nothing written) the same film may be tried again", ap.confirm(prompt(14337)))
    actions.append(f"POST {url}/api/v3/movie -> HTTP 201")
    check("once a write succeeded the same film is not written again", not ap.confirm(prompt(14337)) and not ap.stop_reason)
    check("another pool film is declined without stopping the eval",
          not ap.confirm(prompt(17431)) and not ap.stop_reason)
    for desc in (f"DELETE {url}/api/v3/movie/1", f"PUT {url}/api/v3/movie/1\n  body: {{\"tmdbId\": 14337}}",
                 f"POST {url}/api/v3/qualityprofile\n  body: {{\"tmdbId\": 14337}}", "POST http://example.com/api/v3/movie\n  body: {\"tmdbId\": 14337}",
                 "Run shell command in workspace/\n  curl -X POST " + url + "/api/v3/movie", "Write 10 chars to /tmp/x"):
        ap.start_run(14337)
        ap.succeeded.clear()
        check(f"declined: {desc.splitlines()[0][:50]}", not ap.confirm(desc))
    actions.clear()
    ap.start_run(14337)
    ap.succeeded.clear()
    check("a body with no film id at all is approved, so Radarr's own refusal reaches the model",
          ap.confirm(f"POST {url}/api/v3/movie\n  body: {{\"title\": \"x\", \"qualityProfileId\": 4}}"))
    check("a body naming the film by imdbId or tvdbId alone is declined",
          not ap.confirm(f"POST {url}/api/v3/movie\n  body: {{\"title\": \"x\", \"imdbId\": \"tt0\"}}")
          and not ap.confirm(f"POST {url}/api/v3/movie\n  body: {{\"tvdbId\": 5}}"))
    long_body = '{"title": "x", "overview": "' + "a" * 600
    actions.clear()
    ap.start_run(14337)
    ap.succeeded.clear()
    check("a body cut off at 500 characters before any tmdbId is approved for the gate to check",
          rr.preview_cut_off("POST u\n  body: " + long_body[:500]) and ap.confirm(f"POST {url}/api/v3/movie\n  body: " + long_body[:500]))
    check("a short body is not cut off", not rr.preview_cut_off(prompt(1)) and not rr.preview_cut_off("Run shell command\n  ls"))
    check("none of those stopped the eval", ap.stop_reason == "")
    check("a trailing slash on the url is the same endpoint", rr.Approver(url + "/", {1}, [], current=1).confirm(prompt(1)))
    check("a write for a film outside the pool is declined and stops the eval",
          not ap.confirm(prompt(603)) and "603" in ap.stop_reason)
    check("after a stop everything is declined, even the right film", not ap.confirm(prompt(14337)))

    ap = rr.Approver(url, {1}, [], current=1)
    ap.start_run(1)
    check("a run gets three write attempts and no more",
          [ap.confirm(prompt(1)) for _ in range(4)] == [True, True, True, False] and not ap.stop_reason)
    ap.start_run(1)
    check("the allowance comes back for the next run", ap.confirm(prompt(1)))

    actions = []
    ap = rr.Approver(url, {1}, actions, current=1)
    actions.append(f"POST {url}/api/v3/movie -> HTTP 401")
    check("an auth failure stops the eval", not ap.confirm(prompt(1)) and "401" in ap.stop_reason)
    actions = []
    ap = rr.Approver(url, {1}, actions, current=1)
    actions.extend(["POST x -> HTTP 400"] * 5)
    check("five failed writes in a row do not stop it", ap.confirm(prompt(1)) and not ap.stop_reason)
    actions.append("POST x -> HTTP 500")
    check("six in a row stop it", not ap.confirm(prompt(1)) and "6 failed" in ap.stop_reason)
    actions.clear()
    actions.extend(["POST x -> HTTP 400", "POST x -> HTTP 400", "POST x -> HTTP 201", "POST x -> HTTP 400"] * 3)
    ap = rr.Approver(url, {1, 2}, actions, current=2)
    ap.confirm(prompt(2))
    check("a success between failures resets the streak", ap._fail_streak == 1 and not ap.stop_reason)
    actions.clear()
    actions.extend(["POST x -> HTTP 500"] * 6)
    ap = rr.Approver(url, {1}, actions, current=1)
    ap.after_run()
    check("after_run catches a streak at the end of a run", "6 failed" in ap.stop_reason)
    actions.clear()
    ap = rr.Approver(url, {1}, actions, current=1)
    ap._seen = 5  # the run's action list was cleared since the last count
    check("a cleared action list is counted from the start", ap.confirm(prompt(1)))

    sent = []
    real = lambda method, u, **kw: sent.append((method, u, kw)) or "sent"  # noqa: E731
    ap = rr.Approver(url, {14337, 17431}, [], current=14337)
    guarded = ap.wrap(real)
    api = f"{url}/api/v3/movie"
    check("the gate lets a GET through untouched", guarded("GET", f"{url}/api/v3/rootfolder") == "sent")
    check("the gate lets this run's film through", guarded("POST", api, json={"tmdbId": 14337, "title": "x"}) == "sent")
    for what, args in (("another pool film", ("POST", api, {"tmdbId": 17431})), ("an imdbId and no tmdbId", ("POST", api, {"title": "Primer", "imdbId": "tt0390384"})),
                       ("a DELETE", ("DELETE", f"{api}/1", None)), ("a PUT", ("PUT", f"{api}/1", {"tmdbId": 14337})),
                       ("another endpoint", ("POST", f"{url}/api/v3/rootfolder", {"tmdbId": 14337})),
                       ("another host", ("POST", "http://example.com/api/v3/movie", {"tmdbId": 14337})), ("a non-dict body", ("POST", api, [14337]))):
        n = len(sent)
        try:
            guarded(args[0], args[1], json=args[2])
            blocked = False
        except requests.RequestException:
            blocked = True
        check(f"the gate blocks {what} before it is sent", blocked and len(sent) == n)
    check("blocked writes are recorded", len(ap.blocked) == 7 and not ap.stop_reason)
    n = len(sent)
    check("the gate sends a body with no film id at all, for Radarr to refuse", guarded("POST", api, json={"title": "Primer"}) == "sent" and len(sent) == n + 1)
    try:
        guarded("POST", api, json={"tmdbId": 603})
    except requests.RequestException:
        pass
    check("the gate stops the eval on a write for a film outside the pool", "603" in ap.stop_reason)
    ap.start_run(17431)
    check("run_record covers only the run that is on", ap.run_record() == {"approved_writes": [], "declined_prompts": [], "blocked_writes": []})

    film = films[0]  # Primer
    before = rr.library_ids(url, "")
    added: list[rr.Added] = []
    ok, why = rr.check(url, "", film, before, added)
    check("nothing added: the check fails and logs nothing", not ok and added == [])
    post(BODY)
    ok, why = rr.check(url, "", film, before, added)
    check("the right film with an existing profile and folder passes", ok and "radarr id 1" in why)
    check("what was added is logged for cleanup", [(a.title, a.tmdb_id) for a in added] == [("Primer", 14337)])
    post({**BODY, "title": "Moon", "tmdbId": 17431})
    ok, why = rr.check(url, "", film, before, added)
    check("an extra film in the library fails the check", not ok and "Moon" in why)
    report = rr.cleanup_report(url, "", added)
    check("the cleanup report names the films with Radarr's ids and says to check downloads",
          "Primer (radarr id 1, tmdb 14337)" in report and "downloaded files" in report)
    check("with nothing added there is nothing to clean up", "nothing to clean up" in rr.cleanup_report(url, "", []))
    check("a server with no queue endpoint gives no queue lines", rr.queue_report(url, "", added) == [])
    check("the built-in pool has six distinct films, so real adds are capped at six",
          len(rr.POOL) == 6 and len(set(rr.POOL)) == 6)
    check("the prompt names the title and the year", rr.PROMPT.format(title="Dark Star", year=1974) == "Add the movie Dark Star (1974) to Radarr.")
finally:
    srv.terminate()

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
