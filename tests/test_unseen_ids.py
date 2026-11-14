"""
Tests for the unseen-id guard on writes (#102). Run with: .venv/bin/python tests/test_unseen_ids.py
A non-GET http_request whose body, query or path carries an id that the request text, the notes and skills,
earlier turns and this run's tool output never showed is refused before the [y/N] prompt.
"""

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402

tmp = Path(tempfile.mkdtemp())
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.SKILLS = tmp / "skills"
g.NOTES = tmp / "notes.md"
g.WORKSPACE.mkdir()
g.SKILLS.mkdir()
g.NOTES.write_text("No services here.\n")
real_logs = g.ROOT / "logs"
logs_before = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()

asked: list[str] = []
g.CONFIRM = lambda desc: asked.append(desc) or False
hits: list[tuple[str, str]] = []
CATALOG = [{"id": 603, "title": "Alpha", "tmdbId": 111}, {"id": 604, "title": "Beta", "tmdbId": 222}]


class H(BaseHTTPRequestHandler):
    def _go(self) -> None:
        hits.append((self.command, self.path))
        if self.path.startswith("/big"):
            body = ('{"pad": "' + "x" * 5000 + '", "tail": {"id": 98765}}').encode()
        else:
            body = json.dumps(CATALOG).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = _go

    def log_message(self, *a) -> None:
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


def fresh(*texts: str) -> None:
    asked.clear()
    hits.clear()
    g.reset_seen(*texts)


# a guessed id is refused: no prompt, no network call
fresh("add a movie")
r = g.http_request("POST", f"{BASE}/movie", '{"title": "Alpha", "tmdbId": 603}')
check("a guessed tmdbId is refused", r.startswith("ERROR") and "tmdbId" in r and "603" not in r and "Look them up first" in r)
check("a refused write neither asks nor sends", not asked and not hits)

# looking it up first makes the same write go through to the prompt
fresh("add a movie")
g.http_request("GET", f"{BASE}/lookup")
r = g.http_request("POST", f"{BASE}/movie", '{"title": "Alpha", "tmdbId": 111}')
check("an id shown by an earlier GET passes the guard", r == g.DECLINED and len(asked) == 1)
check("an id in a result the model was shown is learned from any wrapped tool", "111" in g.SEEN_TOKENS)

# other sources
fresh("please use quality profile 7")
check("an id typed in the request passes", g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 7}') == g.DECLINED)
fresh("add it", "Earlier I listed the folder id abc-123.")
check("an id from earlier turns passes", g.http_request("POST", f"{BASE}/x", '{"folderId": "abc-123"}') == g.DECLINED)
fresh("add it", "", "--- skill: radarr ---\nUse qualityProfileId 4 for HD.")
check("an id named in notes or a skill passes", g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 4}') == g.DECLINED)
fresh("the folder is abc-123")
check("string ids match without regard to case", g.http_request("POST", f"{BASE}/x", '{"folderId": "ABC-123"}') == g.DECLINED)
fresh("go")
check("an answer to ask_user counts as seen", (setattr(g, "ASK", lambda q: "use profile 9"), g.ask_user("which?"))[1] == "use profile 9"
      and g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 9}') == g.DECLINED)
(g.SKILLS / "api.md").write_text("The root folder id is 55.\n")
fresh("go")
g.read_skill("api")
check("a skill read this run counts as seen", g.http_request("POST", f"{BASE}/x", '{"rootFolderId": 55}') == g.DECLINED)

# what is checked
fresh("go")
check("0, -1 and an empty id are placeholders, not guesses", g.http_request("POST", f"{BASE}/x", '{"id": 0, "seriesId": -1, "tagId": ""}') == g.DECLINED)
check("fields that are not ids are never checked", g.http_request("POST", f"{BASE}/x", '{"title": "999", "year": 2001, "monitored": true}') == g.DECLINED)
check("a true or false value under an id key is ignored", g.http_request("POST", f"{BASE}/x", '{"hasId": true, "myId": false}') == g.DECLINED)
r = g.http_request("POST", f"{BASE}/x", '{"movie": {"files": [{"movieFileId": 424242}]}}')
check("nested ids are found", r.startswith("ERROR") and "movieFileId" in r)
r = g.http_request("POST", f"{BASE}/x", '{"tagIds": [31, 32]}')
check("every id in a list is checked and the field is named", r.startswith("ERROR") and "tagIds" in r)
r = g.http_request("PUT", f"{BASE}/movie/777", '{"title": "A"}')
check("a numeric path segment on a PUT is checked", r.startswith("ERROR") and "path" in r)
r = g.http_request("DELETE", f"{BASE}/movie/778")
check("a DELETE of an unseen id is refused", r.startswith("ERROR") and "path" in r and not hits)
r = g.http_request("POST", f"{BASE}/x?seriesId=779", '{"a": 1}')
check("an id in the query string is checked", r.startswith("ERROR") and "seriesId" in r)
check("a GET is never blocked", g.http_request("GET", f"{BASE}/movie/780").startswith("HTTP 200") and hits == [("GET", "/movie/780")])

# the model sees only the clipped text, so ids past the clip were not seen
fresh("go")
g.http_request("GET", f"{BASE}/big")
check("an id beyond the 4,000 character clip was not seen", g.http_request("POST", f"{BASE}/x", '{"movieId": 98765}').startswith("ERROR"))

# the refusal text must not teach the guard the ids it refused (an identical retry is refused again)
fresh("add a movie")
body = '{"title": "Alpha", "tmdbId": 603, "qualityProfileId": 1}'
first = g.http_request("POST", f"{BASE}/movie", body)
second = g.http_request("POST", f"{BASE}/movie", body)
check("an identical retry of a refused write is refused again", first.startswith("ERROR") and second == first and not asked and not hits)
check("the refusal names the fields, not the values", "tmdbId" in first and "qualityProfileId" in first and "603" not in first)

# a new request starts clean
fresh("go")
g.http_request("GET", f"{BASE}/lookup")
g.start_log("test-model", "second request", context="")
check("start_log resets what was seen", g.http_request("POST", f"{BASE}/x", '{"tmdbId": 111}').startswith("ERROR"))
g.start_log("test-model", "use tmdb 111 please", context="")
check("start_log seeds the request text", g.http_request("POST", f"{BASE}/x", '{"tmdbId": 111}') == g.DECLINED)
g.start_log("test-model", "go", context="Earlier: the profile id is 6.")
check("start_log seeds earlier turns", g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 6}') == g.DECLINED)
g.NOTES.write_text("Radarr profile id 8.\n")
g.start_log("test-model", "go")
check("start_log seeds notes.md", g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 8}') == g.DECLINED)
g.http_request("POST", f"{BASE}/x", '{"qualityProfileId": 12345}')
log = next(g.LOG_DIR.glob("*.jsonl")).read_text() if g.LOG_DIR.exists() else ""
check("a refusal is logged with the id fields", '"kind": "unseen_id"' in log and "qualityProfileId" in log)

srv.shutdown()
logs_after = {(p.name, p.stat().st_size) for p in real_logs.iterdir()} if real_logs.exists() else set()
check("the test wrote no run logs to the real logs/ directory", logs_before == logs_after)
print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
