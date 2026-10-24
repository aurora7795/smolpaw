"""
Safety tests for generic_tools. Run with: .venv/bin/python tests/test_generic_tools.py
The Radarr GET test is live and skipped if RADARR_URL/RADARR_API_KEY are unset.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from agent import load_env  # noqa: E402

load_env()
prompts: list[str] = []
answer = {"value": False}


def fake_confirm(desc: str) -> bool:
    prompts.append(desc)
    return answer["value"]


g.CONFIRM = fake_confirm
tmp = Path(tempfile.mkdtemp())
g.WORKSPACE = tmp / "workspace"
g.SKILLS = tmp / "skills"
g.WORKSPACE.mkdir()
(g.WORKSPACE / "a.txt").write_text("hello world\n")
(g.WORKSPACE / ".env").write_text("SECRET=1\n")


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0


def asked() -> bool:
    got = bool(prompts)
    prompts.clear()
    return got


# read-only commands run without asking
check("ls runs free", "a.txt" in g.run_shell("ls") and not asked())
check("cat in workspace runs free", "hello" in g.run_shell("cat a.txt") and not asked())
check("grep runs free", "hello" in g.run_shell("grep hello a.txt") and not asked())

# everything else asks
answer["value"] = False
check("rm asks and is declined", g.run_shell("rm a.txt") == g.DECLINED and asked())
check("rm did not run", (g.WORKSPACE / "a.txt").exists())
check("cat outside scope asks", g.run_shell("cat /etc/hosts") == g.DECLINED and asked())
check("path traversal asks", g.run_shell("cat ../../etc/hosts") == g.DECLINED and asked())
check("pipe asks", g.run_shell("cat a.txt | wc -c") == g.DECLINED and asked())
check("redirect asks", g.run_shell("cat a.txt > b.txt") == g.DECLINED and asked())
check("command substitution asks", g.run_shell("cat $(echo a.txt)") == g.DECLINED and asked())
check("find -delete asks", g.run_shell("find . -delete") == g.DECLINED and asked())
check("find -exec asks", g.run_shell("find . -exec rm {} ;") == g.DECLINED and asked())
check("cat .env asks (not free)", g.run_shell("cat .env") == g.DECLINED and asked())

answer["value"] = True
check("approved write command runs", "exit code 0" in g.run_shell("echo hi > b.txt") and asked())
check("approved write took effect", (g.WORKSPACE / "b.txt").read_text() == "hi\n")

# files
check(".env read blocked without asking", g.read_file(".env").startswith("BLOCKED") and not asked())
check(".env write blocked without asking", g.write_file(".env", "x").startswith("BLOCKED") and not asked())
check("read in workspace free", "hello" in g.read_file("a.txt") and not asked())
answer["value"] = False
check("write declined", g.write_file("c.txt", "x") == g.DECLINED and asked())
check("declined write did not happen", not (g.WORKSPACE / "c.txt").exists())
answer["value"] = True
check("write approved", g.write_file("c.txt", "x").startswith("SUCCESS") and asked())
check("outside-scope read asks", "hello" not in g.read_file("../../outside") and asked())

# skills
answer["value"] = False
check("skill write declined", g.write_skill("demo", "# Demo\nx") == g.DECLINED and asked())
answer["value"] = True
check("skill write approved", g.write_skill("Demo!!", "# Demo\nx").startswith("SUCCESS") and asked())
check("skill name sanitised", (g.SKILLS / "demo.md").exists())
check("list_skills shows it", "demo: Demo" in g.list_skills())
check("read_skill works", "x" in g.read_skill("demo"))

# http: GET free, others ask
answer["value"] = False
check("POST asks and is declined", g.http_request("POST", "http://127.0.0.1:9/x", "{}") == g.DECLINED and asked())
check("bad JSON body rejected", g.http_request("POST", "http://127.0.0.1:9/x", "{bad").startswith("ERROR"))
check("GET failure reports error without asking", g.http_request("GET", "http://127.0.0.1:9/x").startswith("ERROR") and not asked())

# openapi_search (spec served from a fake requests.get)
class _Resp:
    def json(self):
        return {"paths": {"/api/v3/queue": {"get": {"summary": "List queue", "tags": ["Queue"]}},
                          "/api/v3/movie": {"get": {"summary": "List movies", "tags": ["Movie"]}}}}


g.requests.get = lambda *a, **k: _Resp()
check("openapi_search finds endpoint", "GET /api/v3/queue" in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search excludes others", "movie" not in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search lists tags", "Queue" in g.openapi_search("http://x/spec.json"))
check("openapi_search no match", g.openapi_search("http://x/spec.json", "zzz") == "No matching endpoints.")

# HTML responses are flagged, JSON is not
class _Http:
    def __init__(self, text, ctype, status=200):
        self.text, self.headers, self.status_code = text, {"content-type": ctype}, status


_real_request = g.requests.request
g.requests.request = lambda *a, **k: _Http("<!doctype html><html>login</html>", "text/html")
res = g.http_request("GET", "http://x/DownloadQueue")
check("HTML body flagged as not an answer", "HTML web page" in res and "login" not in res)
g.requests.request = lambda *a, **k: _Http('{"ok": true}', "application/json")
check("JSON body passed through", g.http_request("GET", "http://x/api").endswith('{"ok": true}'))
g.requests.request = _real_request

# short skills are inlined into the prompt, long ones only listed
(g.SKILLS / "short.md").write_text("# Short\nuse thing")
(g.SKILLS / "long.md").write_text("# Long\n" + "x" * 3000)
ins = g.build_instructions()
check("short skill inlined", "use thing" in ins)
check("long skill listed not inlined", "Longer skills" in ins and "xxxxxxxxxx" not in ins)

# secrets
if os.environ.get("RADARR_URL") and os.environ.get("RADARR_API_KEY"):
    g.NOTES = tmp / "notes.md"
    g.NOTES.write_text(f"- radarr: {os.environ['RADARR_URL']} | key_env=RADARR_API_KEY | header=X-Api-Key\n")
    key = os.environ["RADARR_API_KEY"]
    res = g.http_request("GET", f"{os.environ['RADARR_URL']}/api/v3/system/status")
    check("key injected for listed host (HTTP 200)", res.startswith("HTTP 200") and not asked())
    check("key not in output", key not in res)
    check("redaction removes key from any text", key not in g._redact(f"key is {key}") and "[REDACTED]" in g._redact(f"key is {key}"))
    check("services parsed", "radarr" in g.services())
    other = g._auth_headers("http://example.com/api")
    check("no key sent to unlisted host", other == {})
else:
    print("SKIP  live Radarr tests (RADARR_URL/RADARR_API_KEY unset)")

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
