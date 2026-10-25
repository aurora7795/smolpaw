"""
Safety tests for generic_tools. Run with: .venv/bin/python tests/test_generic_tools.py
The Radarr GET test is live and skipped if RADARR_URL/RADARR_API_KEY are unset.
"""

import json
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
g.MEMORY = tmp / "memory.md"
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
answer["value"] = False

# Windows support (#33): both paths route through PowerShell there, not a bare exec / cmd.exe
saved_windows, saved_run = g.WINDOWS, g.subprocess.run
captured = {}


def _fake_run(*a, **k):
    captured["argv"] = a[0]
    return type("R", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()


g.subprocess.run = _fake_run
g.WINDOWS = True
g.run_shell("ls")
check("read-only commands route through PowerShell on Windows",
      captured["argv"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
      and captured["argv"][4] == "ls")
answer["value"] = True
g.run_shell("rm something")
check("confirm-required commands also route through PowerShell on Windows",
      captured["argv"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
      and captured["argv"][4] == "rm something")
answer["value"] = False

# a filename with an apostrophe must be quoted PowerShell-style ('' ), not shlex's POSIX '"'"' escape
check("_ps_quote escapes an embedded single quote for PowerShell",
      g._ps_quote("O'Brien's notes.txt") == "'O''Brien''s notes.txt'")
g.run_shell('cat "O\'Brien\'s notes.txt"')
check("read-only args with an apostrophe are quoted PowerShell-style on Windows",
      "'\"'\"'" not in captured["argv"][4] and "O''Brien''s notes.txt" in captured["argv"][4])
g.WINDOWS = saved_windows


def _raise_oserror(*a, **k):
    raise FileNotFoundError("[WinError 2] The system cannot find the file specified")


g.subprocess.run = _raise_oserror
res = g.run_shell("ls")
check("a command that cannot run returns a clean ERROR instead of crashing",
      res.startswith("ERROR") and "could not run" in res)
g.subprocess.run = saved_run
prompts.clear()  # the "rm something" confirm above isn't what later "was anything asked?" checks care about

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

# memory: remember and recall (#27)
check("remember is in GENERIC_TOOLS", g.remember in g.GENERIC_TOOLS)
check("recall is in GENERIC_TOOLS", g.recall in g.GENERIC_TOOLS)
check("recall on empty memory reports no memories", g.recall() == "No memories saved yet.")
check("remember rejects empty fact", "ERROR" in g.remember(""))

# remember asks for approval and handles decline
answer["value"] = False
declined_res = g.remember("User prefers dark mode")
check("remember declined returns DECLINED", declined_res == g.DECLINED and asked())
check("declined fact not written to file", not g.MEMORY.exists() or "dark mode" not in g.MEMORY.read_text())

# remember approved writes fact
answer["value"] = True
approved_res = g.remember("User prefers dark mode")
check("remember approved returns SUCCESS", approved_res.startswith("SUCCESS") and asked())
check("fact written to memory.md", g.MEMORY.exists() and "User prefers dark mode" in g.MEMORY.read_text())

# remember appends subsequent facts
g.remember("Backup drive is /Volumes/Backup")
asked()
mem_content = g.MEMORY.read_text()
check("remember appends subsequent facts", "dark mode" in mem_content and "/Volumes/Backup" in mem_content)

# remember redacts credentials
g.remember("My API key is sk-1234567890abcdef12345678")
asked()
redacted_mem = g.MEMORY.read_text()
check("remember redacts credentials", "sk-1234567890abcdef12345678" not in redacted_mem and "[REDACTED" in redacted_mem)

# recall queries
all_facts = g.recall()
check("recall empty query returns all facts", "dark mode" in all_facts and "/Volumes/Backup" in all_facts)
single_hit = g.recall("dark mode")
check("recall single keyword returns matching line", "dark mode" in single_hit and "/Volumes/Backup" not in single_hit)
multi_hit = g.recall("backup drive")
check("recall multi-word query finds match", "/Volumes/Backup" in multi_hit)
no_hit = g.recall("nonexistent topic")
check("recall no match explains clearly", "No memories matching 'nonexistent topic'." in no_hit)
check("recall does not ask for confirmation", not asked())

# memory is NOT inlined into prompt (prompt overhead is 0)
check("memory is not inlined into prompt", "dark mode" not in g.build_instructions())

# Real token cost of the combined remember+recall schema, measured against the actual JSON
# smolagents sends (get_tool_json_schema), not the hand-reconstructed dict this test used to check
# (485 chars, missing "type": "object"/"required"/"nullable" -- about a third smaller than real).
# Checked against two tokenizers (Ollama /api/generate, raw prompt, no chat template): 179 tokens
# on Qwen 3.5 9B, 182 on Gemma 4 E4B. Both exceed #27's own 100-150 token budget and the "~147
# tokens" this test originally claimed. See CHANGELOG.md. No tokenizer is available to this test
# file, so there is no assertion here -- a char-count proxy already said something untrue once.

# logging of remember and recall
mem_log_file = tmp / "mem-log.jsonl"
saved_log_file = g._log_file
g._log_file = mem_log_file
g.remember("Favorite language is Python")
asked()
g.recall("Python")
g.recall("Ruby")
mem_logs = [json.loads(line) for line in mem_log_file.read_text().splitlines()]
g._log_file = saved_log_file

check("remember calls are logged", any(l["kind"] == "remember" and "Python" in l["fact"] for l in mem_logs))
check("recall calls are logged with query and hits", any(l["kind"] == "recall" and l["query"] == "Python" and l["hits"] > 0 for l in mem_logs))
check("recall zero-hits logged", any(l["kind"] == "recall" and l["query"] == "Ruby" and l["hits"] == 0 for l in mem_logs))

# ask_user redacts a pasted credential before it reaches the model or the log (#32)
check("a GitHub token in an answer is redacted",
      g.redact_pasted_secrets("ghp_0000000000000000000000000000000000") == "[REDACTED: looks like a credential]")
check("an AWS key in a sentence is redacted",
      "[REDACTED" in g.redact_pasted_secrets("here is my key: AKIAABCDEFGHIJKLMNOP thanks")
      and "AKIAABCDEFGHIJKLMNOP" not in g.redact_pasted_secrets("here is my key: AKIAABCDEFGHIJKLMNOP thanks"))
check("an ordinary path is not redacted", g.redact_pasted_secrets("/tmp/my demo") == "/tmp/my demo")
check("an ordinary short answer is not redacted", g.redact_pasted_secrets("Paris") == "Paris")
saved_ask, saved_log_file = g.ASK, g._log_file
g.ASK = lambda q: "my token is ghp_0000000000000000000000000000000000 ok"
g._log_file = tmp / "ask-user-redaction-log.jsonl"
res = g.ask_user("what is your token?")
check("ask_user itself redacts a pasted credential before returning it",
      "ghp_" not in res and "[REDACTED" in res)
check("the redacted answer, not the raw one, is what gets logged",
      "ghp_" not in g._log_file.read_text() and "[REDACTED" in g._log_file.read_text())
g.ASK = saved_ask
g._log_file = saved_log_file

# http: GET free, others ask
answer["value"] = False
check("POST asks and is declined", g.http_request("POST", "http://127.0.0.1:9/x", "{}") == g.DECLINED and asked())
check("bad JSON body rejected", g.http_request("POST", "http://127.0.0.1:9/x", "{bad").startswith("ERROR"))
check("GET failure reports error without asking", g.http_request("GET", "http://127.0.0.1:9/x").startswith("ERROR") and not asked())

# pre-flight validation on writes and required queries (#31)
net_called = [False]


def _fail_network(*a, **k):
    net_called[0] = True
    raise AssertionError("Network call was made during preflight validation")


saved_req = g.requests.request
g.requests.request = _fail_network

empty_post_res = g.http_request("POST", "http://127.0.0.1:9/x", "")
check("empty-body POST returns ERROR without asking and makes no network call",
      empty_post_res.startswith("ERROR") and "requires a request body" in empty_post_res
      and not asked() and not net_called[0])

ws_post_res = g.http_request("POST", "http://127.0.0.1:9/x", "   ")
check("whitespace-only-body POST returns ERROR without asking and makes no network call",
      ws_post_res.startswith("ERROR") and "requires a request body" in ws_post_res
      and not asked() and not net_called[0])

term_res = g.http_request("GET", "http://127.0.0.1:9/api/v3/movie/lookup?term=")
check("lookup?term= returns ERROR without asking and makes no network call",
      term_res.startswith("ERROR") and "query parameter 'term' is empty" in term_res
      and not asked() and not net_called[0])

q_res = g.http_request("GET", "http://127.0.0.1:9/search?q=")
check("search?q= returns ERROR without asking and makes no network call",
      q_res.startswith("ERROR") and "query parameter 'q' is empty" in q_res
      and not asked() and not net_called[0])

query_res = g.http_request("GET", "http://127.0.0.1:9/search?query=")
check("search?query= returns ERROR without asking and makes no network call",
      query_res.startswith("ERROR") and "query parameter 'query' is empty" in query_res
      and not asked() and not net_called[0])

check("empty body PUT returns ERROR without asking",
      g.http_request("PUT", "http://127.0.0.1:9/x", "").startswith("ERROR")
      and not asked() and not net_called[0])

check("empty body PATCH returns ERROR without asking",
      g.http_request("PATCH", "http://127.0.0.1:9/x", "").startswith("ERROR")
      and not asked() and not net_called[0])

g.requests.request = saved_req

check("DELETE with no body is unaffected", g.http_request("DELETE", "http://127.0.0.1:9/x", "") == g.DECLINED and asked())
check("?term=matrix is unaffected", "query parameter" not in g.http_request("GET", "http://127.0.0.1:9/api/v3/movie/lookup?term=matrix") and not asked())
check("URL with no query string is unaffected", "query parameter" not in g.http_request("GET", "http://127.0.0.1:9/api/v3/movie") and not asked())
check("action endpoint with empty body asks and is declined", g.http_request("POST", "http://127.0.0.1:9/api/v3/system/restart", "") == g.DECLINED and asked())
check("/command needs a JSON body, so an empty POST is rejected",
      g.http_request("POST", "http://127.0.0.1:9/api/v3/command", "").startswith("ERROR") and not asked())

saved_notes = g.NOTES.read_text() if g.NOTES.exists() else ""
g.NOTES.write_text("- svc: http://x:7878 | key_env=SMOLPAW_TEST_PREFLIGHT_KEY\n")
os.environ["SMOLPAW_TEST_PREFLIGHT_KEY"] = "preflight-test-key-abcdef"
preflight_redacted = g.http_request("POST", "http://x:7878/api?k=preflight-test-key-abcdef", "")
check("preflight error redacts secrets in URL",
      "preflight-test-key-abcdef" not in preflight_redacted and "[REDACTED]" in preflight_redacted)
del os.environ["SMOLPAW_TEST_PREFLIGHT_KEY"]
if saved_notes:
    g.NOTES.write_text(saved_notes)
else:
    g.NOTES.unlink(missing_ok=True)

# openapi_search (spec served from a fake requests.get)
class _Resp:
    def json(self):
        return {"paths": {"/api/v3/queue": {"get": {"summary": "List queue", "tags": ["Queue"]}},
                          "/api/v3/movie": {"get": {"summary": "List movies", "tags": ["Movie"]}}}}


g.requests.get = lambda *a, **k: _Resp()
check("openapi_search finds endpoint", "GET /api/v3/queue" in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search excludes others", "movie" not in g.openapi_search("http://x/spec.json", "queue"))
check("openapi_search lists tags", "Queue" in g.openapi_search("http://x/spec.json"))
class _Page:
    def json(self):
        return {"service": "x", "resources": {}}


g.requests.get = lambda *a, **k: _Page()
msg = g.openapi_search("http://x/index", "queue")
check("openapi_search explains non-spec JSON", "not an OpenAPI spec" in msg and "http_request" in msg)
g.requests.get = lambda *a, **k: _Resp()
check("openapi_search no match", g.openapi_search("http://x/spec.json", "zzz") == "No matching endpoints.")

# openapi_search calls are logged, like http_request and run_shell (#30)
_SPECS_SAVED = dict(g._SPECS)
g._SPECS.clear()
saved_log_file = g._log_file
g._log_file = tmp / "openapi-search-log.jsonl"
g.requests.get = lambda *a, **k: _Resp()
g.openapi_search("http://x/spec2.json", "queue")
g.openapi_search("http://x/spec2.json", "zzz")
entries = [g.json.loads(line) for line in g._log_file.read_text().splitlines()]
check("openapi_search calls are logged", [e["kind"] for e in entries] == ["openapi_search", "openapi_search"])
check("logged entry has the keyword and a hit count", entries[0]["keyword"] == "queue" and entries[0]["result"] == "1 hits")
check("a no-match call is logged too", entries[1]["keyword"] == "zzz" and entries[1]["result"] == "0 hits")
g._log_file = saved_log_file
g._SPECS.clear(); g._SPECS.update(_SPECS_SAVED)
import web  # noqa: E402
saved_feed_log, web.g._log_file = web.g._log_file, (tmp / "openapi-search-log.jsonl")
line = web.feed()[0]
check("web.py's feed shows the spec, keyword and result", "spec2.json" in line and "queue" in line and "1 hits" in line)
web.g._log_file = mem_log_file
feed_lines = web.feed()
check("web.py feed shows remember fact", any("remember" in fl and "Python" in fl for fl in feed_lines))
check("web.py feed shows recall query and hits", any("recall" in fl and "Python" in fl for fl in feed_lines))
web.g._log_file = saved_feed_log

# HTML responses are flagged, JSON is not
class _Http:
    def __init__(self, text, ctype, status=200):
        self.text, self.headers, self.status_code = text, {"content-type": ctype}, status


_real_request = g.requests.request
saved_notes = g.NOTES
g.NOTES = tmp / "html-notes.md"
g.NOTES.write_text("- svc: http://x:7878 | key_env=SMOLPAW_TEST_HTML_KEY\n")
g.requests.request = lambda *a, **k: _Http("<!doctype html><html>login</html>", "text/html")
res = g.http_request("GET", "http://x:7878/DownloadQueue")
check("HTML from a known service flagged as not an answer", "HTML web page" in res and "login" not in res)
page = ("<!doctype html><html><head><title>Release &amp; notes</title><style>p{x:1}</style>"
        "<script>var secret=1</script></head><body><nav>Home</nav><h1>Python 3.14</h1>"
        "<p>Released   in\n October.</p><ul><li>one</li><li>two</li></ul></body></html>")
g.requests.request = lambda *a, **k: _Http(page, "text/html; charset=utf-8")
res = g.http_request("GET", "https://www.example.org/news")
check("other web pages converted to text",
      res.startswith("HTTP 200 (web page converted to text)") and "Title: Release & notes" in res
      and "Python 3.14\nReleased in October.\none\ntwo" in res)
check("scripts, styles and tags dropped", "secret" not in res and "x:1" not in res and "<" not in res)
check("only <main> kept when it has text",
      g.html_to_text("<div>Menu</div><main><p>Body</p></main><div>Links</div>") == "Body")
os.environ["SMOLPAW_TEST_HTML_KEY"] = "html-key-12345678"
g.requests.request = lambda *a, **k: _Http("<p>key html-key-12345678</p>", "text/html")
check("converted page text is redacted", "html-key-12345678" not in g.http_request("GET", "http://other/"))
g.NOTES = saved_notes
g.requests.request = lambda *a, **k: _Http('{"ok": true}', "application/json")
check("JSON body passed through", g.http_request("GET", "http://x/api").endswith('{"ok": true}'))
g.requests.request = _real_request

# fetch_page (#28): on-demand web page text trimmed to query
check("fetch_page rejects non-http url", g.fetch_page("ftp://example.com").startswith("ERROR: URL must start with"))
check("fetch_page is in GENERIC_TOOLS", g.fetch_page in g.GENERIC_TOOLS)


class _FakeGetResp:
    def __init__(self, text, ctype="text/html", status=200):
        self.text = text
        self.headers = {"content-type": ctype}
        self.status_code = status
        self.ok = 200 <= status < 300


sample_html = """<!doctype html>
<html><head><title>Documentation Guide</title></head>
<body>
<h1>Welcome</h1>
<p>Introductory paragraph describing the project.</p>
<h2>Architecture</h2>
<p>The system uses SQLite for metadata storage.</p>
<p>Redis is used for caching session state.</p>
<h2>Deployment</h2>
<p>Deploy using Docker containers with compose.</p>
<p>Kubernetes Helm charts are also supported.</p>
</body></html>"""

saved_get = g.requests.get
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)

# empty query returns title and top of page
top_res = g.fetch_page("https://example.com/docs")
check("fetch_page empty query returns top text", "Title: Documentation Guide" in top_res and "Introductory paragraph" in top_res)

# query matching specific section
arch_res = g.fetch_page("https://example.com/docs", query="SQLite")
check("fetch_page extracts matching query section", "SQLite for metadata storage" in arch_res)
check("fetch_page includes context around match", "Architecture" in arch_res)
check("fetch_page excludes unrelated sections", "Kubernetes Helm charts" not in arch_res)

# query with no match gives clean message
no_match_res = g.fetch_page("https://example.com/docs", query="Postgres")
check("fetch_page explains no match with title and preview", "No content matching 'Postgres' found" in no_match_res and "Documentation Guide" in no_match_res)

# HTTP error handling
g.requests.get = lambda *a, **k: _FakeGetResp("Page Not Found", status=404)
err_res = g.fetch_page("https://example.com/missing", query="test")
check("fetch_page reports HTTP error status", err_res.startswith("HTTP 404"))

# Request exception handling
def _raise_req_err(*a, **k):
    raise g.requests.RequestException("connection timed out")


g.requests.get = _raise_req_err
net_err_res = g.fetch_page("https://example.com/timeout", query="test")
check("fetch_page reports request exception", net_err_res.startswith("ERROR: connection timed out"))

# secret redaction
os.environ["SMOLPAW_TEST_PAGE_KEY"] = "secret-page-token-999"
saved_notes = g.NOTES
g.NOTES = tmp / "page-notes.md"
g.NOTES.write_text("- page_svc: https://example.com | key_env=SMOLPAW_TEST_PAGE_KEY\n")
g.requests.get = lambda *a, **k: _FakeGetResp("<p>Token secret-page-token-999 is private</p>")
redacted_res = g.fetch_page("https://unregistered-page.example/secret", query="Token")
check("fetch_page redacts secrets", "secret-page-token-999" not in redacted_res and "[REDACTED]" in redacted_res)

# a registered service answering with HTML means a wrong API path, same warning as http_request (not silently trimmed)
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)
wrong_path_res = g.fetch_page("https://example.com/secret", query="SQLite")
check("fetch_page warns on a service's HTML instead of trimming it",
      "NOT an answer" in wrong_path_res and "SQLite" not in wrong_path_res)
g.NOTES = saved_notes

# logging and feed
saved_log = g._log_file
g._log_file = tmp / "fetch-page-log.jsonl"
g.requests.get = lambda *a, **k: _FakeGetResp(sample_html)
g.fetch_page("https://example.com/docs", query="Redis")
g.fetch_page("https://example.com/docs", query="nonexistent")
log_entries = [g.json.loads(line) for line in g._log_file.read_text().splitlines()]
check("fetch_page calls are logged", len(log_entries) == 2 and log_entries[0]["kind"] == "fetch_page")
check("fetch_page log records query and hit count", log_entries[0]["query"] == "Redis" and log_entries[0]["hits"] > 0)
check("fetch_page log records zero hits on no match", log_entries[1]["hits"] == 0)

saved_feed_log, web.g._log_file = web.g._log_file, g._log_file
feed_line = web.feed()[0]
check("web.py feed shows fetch_page query and result", "fetch_page" in feed_line and "Redis" in feed_line and "hits" in feed_line)
web.g._log_file = saved_feed_log
g._log_file = saved_log
g.requests.get = saved_get

# write verification (#19): a follow-up GET checks what a write actually did, beyond its status code
_real_get = g.requests.get


class _VResp:
    def __init__(self, status, json_body=None, headers=None):
        self.status_code, self.headers = status, {"content-type": "application/json", **(headers or {})}
        self._json = json_body
        self.text = g.json.dumps(json_body) if json_body is not None else ""

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


# POST, verified via Location header, fields match
g.requests.request = lambda *a, **k: _VResp(201, {"id": 5, "monitored": True}, {"Location": "http://x/items/5"})
g.requests.get = lambda *a, **k: _VResp(200, {"id": 5, "monitored": True})
answer["value"] = True
res = g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST verified via Location, fields match", "verified: now exists, fields match" in g.ACTIONS[-1])

# POST, verified via an id in the body (no Location), with a field mismatch
g.requests.request = lambda *a, **k: _VResp(201, {"id": 7, "monitored": True})
g.requests.get = lambda *a, **k: _VResp(200, {"id": 7, "monitored": False})
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST verified via id, mismatch reported",
      "mismatched: monitored: sent True, got False" in g.ACTIONS[-1])

# POST with nothing to verify against
g.requests.request = lambda *a, **k: _VResp(201, {"ok": True})
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("POST with no Location/id says so", "not verified: no Location header or id" in g.ACTIONS[-1])

# PUT, fields match
g.requests.request = lambda *a, **k: _VResp(200)
g.requests.get = lambda *a, **k: _VResp(200, {"monitored": True})
g.http_request("PUT", "http://x/items/5", '{"monitored": true}')
check("PUT verified, fields match", "verified: fields match" in g.ACTIONS[-1])

# PUT, fields do not match (the write did not really take)
g.requests.get = lambda *a, **k: _VResp(200, {"monitored": False})
g.http_request("PUT", "http://x/items/5", '{"monitored": true}')
check("PUT mismatch reported", "mismatched: monitored: sent True, got False" in g.ACTIONS[-1])

# DELETE, verified gone
g.requests.request = lambda *a, **k: _VResp(204)
g.requests.get = lambda *a, **k: _VResp(404)
g.http_request("DELETE", "http://x/items/5")
check("DELETE verified gone", "verified: now returns 404" in g.ACTIONS[-1])

# DELETE, NOT actually gone — the loud case this is meant to catch
g.requests.get = lambda *a, **k: _VResp(200, {"id": 5})
g.http_request("DELETE", "http://x/items/5")
check("DELETE still present is flagged as a WARNING",
      "WARNING" in g.ACTIONS[-1] and "may not actually be deleted" in g.ACTIONS[-1])

# a failed write (non-2xx) is never verified; behaviour is unchanged
g.requests.request = lambda *a, **k: _VResp(400)
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("a failed write is not verified", g.ACTIONS[-1] == "POST http://x/items -> HTTP 400")

# a verification GET that itself fails is reported, not raised
g.requests.request = lambda *a, **k: _VResp(201, {"id": 9})
def _raise(*a, **k):
    raise g.requests.RequestException("boom")
g.requests.get = _raise
g.http_request("POST", "http://x/items", '{"monitored": true}')
check("a verification failure is reported, not raised", "could not verify: RequestException" in g.ACTIONS[-1])

g.requests.request = _real_request
g.requests.get = _real_get
answer["value"] = False
prompts.clear()  # the approvals above aren't what later "was anything asked?" checks care about

# last tool result is remembered for the step-cap fallback
g.LAST_RESULT = ""
g.run_shell("ls")
check("last tool result remembered", g.LAST_RESULT.startswith("run_shell:"))

# short skills are inlined into the prompt, long ones only listed
(g.SKILLS / "short.md").write_text("# Short\nuse thing")
(g.SKILLS / "long.md").write_text("# Long\n" + "x" * 3000)
ins = g.build_instructions()
check("short skill inlined", "use thing" in ins)
check("long skill listed not inlined", "Longer skills" in ins and "xxxxxxxxxx" not in ins)

# key user facts in notes.md (#25): user preferences inlined into prompt, ignored by services()
saved_notes = g.NOTES
g.NOTES = tmp / "facts-notes.md"
g.NOTES.write_text("""# SmolPaw notes

## User facts
- timezone: Europe/London
- units: metric (Celsius, km)
- owner: Martin

## Services
- mysvc: https://example.com/api | key_env=MY_KEY
""")
facts_ins = g.build_instructions()
check("user facts inlined in prompt instructions", "timezone: Europe/London" in facts_ins and "units: metric" in facts_ins)
parsed_svcs = g.services()
check("services() parses valid service URL", "mysvc" in parsed_svcs and parsed_svcs["mysvc"]["url"] == "https://example.com/api")
check("services() ignores user facts lines", "timezone" not in parsed_svcs and "units" not in parsed_svcs and "owner" not in parsed_svcs)
g.NOTES = saved_notes
# The example "## User facts" block's token cost was measured against Qwen 3.5 9B's own tokenizer
# (Ollama /api/generate, raw prompt, no chat template): 27 tokens, not a char-count/4 guess. See
# CHANGELOG.md. No test asserts a token *count* here: nothing in this file has access to a real
# tokenizer, and a char-count proxy (as #27's schema-size check earlier in this file does) tests
# string length, not tokens -- it would pass or fail for reasons unrelated to what it claims to check.

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

# backend selection (no server needed: building the model makes no request)
from smolagents import OpenAIServerModel  # noqa: E402

from agent import build_agent  # noqa: E402

lm = build_agent(toolset="generic").model
check("default backend is LM Studio", lm.client_kwargs["base_url"] == "http://127.0.0.1:1234/v1"
      and lm.model_id == "ternary-bonsai-8b-mlx")
ol = build_agent(toolset="generic", backend="ollama").model
check("ollama backend uses port 11434 and its default model",
      ol.client_kwargs["base_url"] == "http://127.0.0.1:11434/v1" and ol.model_id == "qwen3.5:9b")
check("explicit model overrides backend default",
      build_agent("gemma4:e4b", toolset="generic", backend="ollama").model.model_id == "gemma4:e4b")

# web approvals: the browser answers the same prompts; only a correct token and a real boolean approve
import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import requests  # noqa: E402

import web  # noqa: E402


def run_in_thread(fn, *args) -> dict:
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(value=fn(*args)), daemon=True)
    t.start()
    out["thread"] = t
    return out


def wait_pending(approvals: web.Approvals) -> dict | None:
    for _ in range(100):
        if approvals.pending:
            return approvals.pending
        time.sleep(0.02)
    return None


with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
token = "test-token-123456"
appr = web.Approvals(timeout=5)
srv = web.serve("127.0.0.1", port, token, appr)
base = f"http://127.0.0.1:{port}"
hdr = {"X-Token": token}
http = requests.Session()  # earlier tests replace requests.get with a fake

check("web page refuses a missing token", http.get(f"{base}/api/state", timeout=5).status_code == 403)
check("web page refuses a wrong token",
      http.get(f"{base}/api/state", headers={"X-Token": "nope"}, timeout=5).status_code == 403)

job = run_in_thread(appr.confirm, "Run shell command?\n  rm x")
p = wait_pending(appr)
check("web prompt is shown as pending", p is not None and p["kind"] == "confirm" and "rm x" in p["text"])
bad = http.post(f"{base}/api/answer", json={"id": p["id"], "value": True},
                headers={"X-Token": "nope"}, timeout=5)
check("wrong token cannot answer", bad.status_code == 403 and appr.pending is not None)
s_yes = http.post(f"{base}/api/answer", json={"id": p["id"], "value": "yes"}, headers=hdr, timeout=5)
check("string 'yes' does not approve", s_yes.status_code == 409 and appr.pending is not None)
stale = http.post(f"{base}/api/answer", json={"id": p["id"] + 1, "value": True}, headers=hdr, timeout=5)
check("stale prompt id is refused", stale.status_code == 409 and appr.pending is not None)
ok = http.post(f"{base}/api/answer", json={"id": p["id"], "value": True}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser yes approves", ok.status_code == 200 and job.get("value") is True)

job = run_in_thread(appr.confirm, "Write file?")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": False}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser no declines", job.get("value") is False)

quick = web.Approvals(timeout=0.2)
check("unanswered confirm times out as no", quick.confirm("Run?") is False)
check("unanswered question times out with a no-answer note", quick.ask("Which one?") == web.NO_ANSWER)

job = run_in_thread(appr.ask, "Which host?")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": "the NAS"}, headers=hdr, timeout=5)
job["thread"].join(5)
check("browser reply reaches ask_user", job.get("value") == "the NAS")

saved_notes = g.NOTES
g.NOTES = tmp / "web-notes.md"
g.NOTES.write_text("- svc: http://example.com | key_env=SMOLPAW_TEST_WEB_KEY | header=X-Api-Key\n")
os.environ["SMOLPAW_TEST_WEB_KEY"] = "s3cret-value-for-test"
job = run_in_thread(appr.confirm, "POST with key s3cret-value-for-test?")
p = wait_pending(appr)
state = http.get(f"{base}/api/state", headers=hdr, timeout=5).json()
check("keys are redacted on the web page",
      "s3cret-value-for-test" not in json.dumps(state) and "[REDACTED]" in p["text"])
appr.cancel()
job["thread"].join(5)
check("stop declines the pending prompt", job.get("value") is False)
g.NOTES = saved_notes
del os.environ["SMOLPAW_TEST_WEB_KEY"]

appr.install()
g.ACTIONS.clear()
job = run_in_thread(g._approved, "Run shell command?\n  touch y")
p = wait_pending(appr)
http.post(f"{base}/api/answer", json={"id": p["id"], "value": False}, headers=hdr, timeout=5)
job["thread"].join(5)
check("web decline is recorded by the harness", job.get("value") is False and g.ACTIONS[-1].startswith("declined"))
g.CONFIRM = fake_confirm
srv.shutdown()

# native tool-call history (#14): smolagents' own calls go back as real tool_calls, model text stays text
from smolagents.memory import ActionStep, ToolCall  # noqa: E402
from smolagents.models import ChatMessage, MessageRole  # noqa: E402
from smolagents.monitoring import Timing  # noqa: E402

from agent import NativeHistoryModel  # noqa: E402

_t = Timing(0.0, 1.0)
_steps = [
    ActionStep(step_number=1, timing=_t, model_output="",
               tool_calls=[ToolCall("http_request", {"method": "GET", "url": "http://x/"}, "call_a")],
               observations="HTTP 200\nok"),
    ActionStep(step_number=2, timing=_t, model_output="Calling tools:\n[{'id': 'fake', 'function': {}}]",
               error=ValueError("could not parse a tool call")),
    ActionStep(step_number=3, timing=_t, model_output="",
               tool_calls=[ToolCall("read_file", {"path": "a"}, "call_b"),
                           ToolCall("read_file", {"path": "b"}, "call_c")],
               observations="a and b"),
]
_msgs = [ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": "task"}])]
for _s in _steps:
    _msgs += _s.to_messages()
_native = NativeHistoryModel(model_id="x", api_base="http://127.0.0.1:9/v1", api_key="k")
hist = _native._prepare_completion_kwargs(_msgs, tools_to_call_from=g.GENERIC_TOOLS)["messages"]
calls = [m for m in hist if m.get("tool_calls")]
check("earlier tool calls are sent as native tool_calls",
      [c["id"] for m in calls for c in m["tool_calls"]] == ["call_a", "call_b", "call_c"]
      and json.loads(calls[0]["tool_calls"][0]["function"]["arguments"]) == {"method": "GET", "url": "http://x/"})
check("tool results are tool messages with matching ids",
      [(m["tool_call_id"], m["content"]) for m in hist if m["role"] == "tool"]
      == [("call_a", "HTTP 200\nok"), ("call_b", "a and b"), ("call_c", "(see the result above)")])
check("no 'Calling tools:' text left from smolagents' own calls",
      sum("Calling tools:" in json.dumps(m) for m in hist) == 1)  # only the model's own invalid text remains
check("model-written tool-call text is not turned into a real call",
      not any(c["id"] == "fake" for m in calls for c in m["tool_calls"]))
check("no internal markers reach the server", "smolpaw-tool" not in json.dumps(hist))
_plain = OpenAIServerModel(model_id="x", api_base="http://127.0.0.1:9/v1", api_key="k")
check("text history is still available for comparison",
      not any(m.get("tool_calls") for m in _plain._prepare_completion_kwargs(_msgs)["messages"]))

# stall detection (#19): the harness stops a run that repeats the same failing call
from agent import STALL_WINDOW, check_stall  # noqa: E402


class _FakeAgent:
    def __init__(self, steps):
        self.memory = type("M", (), {"steps": steps})()
        self.stall_reason = None
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


def _step(tool_calls, observations=None, error=None):
    return ActionStep(step_number=1, timing=_t, model_output="", tool_calls=tool_calls,
                      observations=observations, error=error)


same_call = [ToolCall("http_request", {"method": "POST", "url": "http://x/add"}, f"c{i}") for i in range(5)]
failing = [_step([c], observations="HTTP 400\nbad request") for c in same_call]
a = _FakeAgent(failing[:STALL_WINDOW - 1])
check_stall(a.memory.steps[-1], a)
check("no stall flagged before the window fills", not a.interrupted)
a = _FakeAgent(failing[:STALL_WINDOW])
check_stall(a.memory.steps[-1], a)
check("same call failing with HTTP 4xx repeatedly is a stall", a.interrupted and a.stall_reason)
a = _FakeAgent([_step([ToolCall("run_shell", {"cmd": "echo a"}, "x")], observations="a\n")
                for _ in range(STALL_WINDOW)])
check_stall(a.memory.steps[-1], a)
check("repeating a succeeding call is not a stall", not a.interrupted)
a = _FakeAgent([_step([ToolCall("read_file", {"path": f"f{i}"}, "x")], observations="ERROR: no such file")
                for i in range(STALL_WINDOW)])
check_stall(a.memory.steps[-1], a)
check("different arguments each time is not a stall", not a.interrupted)
a = _FakeAgent(failing[:STALL_WINDOW - 1] + [_step([same_call[0]], error=ValueError("boom"))])
check_stall(a.memory.steps[-1], a)
check("a smolagents-level error counts as a failure too", a.interrupted)

# run_request() reports a stall as a finished answer, but still lets a real Stop-button interrupt through
from smolagents.utils import AgentError  # noqa: E402

from agent import run_request  # noqa: E402


class _StubAgent:
    def __init__(self, reason):
        self.memory = type("M", (), {"steps": []})()
        self._reason = reason

    def run(self, _task):
        g.LAST_RESULT = "openapi_search: no matching endpoints."  # as a real tool call would set it
        self.stall_reason = self._reason
        raise AgentError("Agent interrupted.", type("L", (), {"log_error": lambda *a: None})())


resp, _ = run_request(_StubAgent("the same call failed 3 times in a row"), "m", "generic", "task")
check("a stall is reported as the answer, with the last tool result",
      resp.startswith("STOPPED EARLY: the same call failed 3 times in a row")
      and "no matching endpoints" in resp)
try:
    run_request(_StubAgent(None), "m", "generic", "task")
    check("a non-stall interrupt (Stop button) is not swallowed", False)
except AgentError:
    check("a non-stall interrupt (Stop button) is not swallowed", True)

# export_findings.py: bundling run logs into one shareable report
sys.path.insert(0, str(Path(__file__).parent))
import export_findings as ef  # noqa: E402

_findings_dir = tmp / "efindings"
_findings_dir.mkdir()
ef.LOG_DIR = _findings_dir
_l1 = _findings_dir / "20261025-080000-demo-model.jsonl"
_l1.write_text("\n".join(json.dumps(e) for e in [
    {"t": "2026-10-25T08:00:00", "kind": "start", "model": "demo-model", "prompt": "rename the reports"},
    {"t": "2026-10-25T08:00:05", "kind": "shell", "command": "mv a.txt a-2026.txt", "read_only": False, "exit": 0},
    {"t": "2026-10-25T08:00:06", "kind": "http", "method": "GET", "url": "http://x/y", "status": 200},
    {"t": "2026-10-25T08:00:07", "kind": "fetch_page", "url": "http://x/docs", "query": "auth", "result": "2 hits"},
    {"t": "2026-10-25T08:00:08", "kind": "remember", "fact": "User prefers dark mode"},
    {"t": "2026-10-25T08:00:09", "kind": "recall", "query": "dark mode", "result": "1 hits"},
    {"t": "2026-10-25T08:00:10", "kind": "final", "answer": "Renamed a.txt.", "actions": ["shell exit 0: mv a.txt a-2026.txt"]},
]))
_l2 = _findings_dir / "20261025-079000-no-final.jsonl"
_l2.write_text(json.dumps({"t": "2026-10-25T07:50:00", "kind": "start", "model": "x", "prompt": "unfinished"}))
report = ef.render(_l1)
check("export_findings renders the prompt and model", "rename the reports" in report and "demo-model" in report)
check("export_findings renders a shell action", "`$ mv a.txt a-2026.txt`" in report)
check("export_findings renders an http action", "`GET http://x/y` -> 200" in report)
check("export_findings renders a fetch_page action", "`fetch_page` http://x/docs auth -> 2 hits" in report)
check("export_findings renders a remember action", "`remember` User prefers dark mode" in report)
check("export_findings renders a recall action", "`recall` dark mode -> 1 hits" in report)
check("export_findings renders the final answer and duration", "Renamed a.txt." in report and "10s" in report)
check("a run with no final answer is marked unfinished", "did not finish" in ef.render(_l2))
_l3 = _findings_dir / "20261025-078000-no-start.jsonl"
_l3.write_text(json.dumps({"t": "2026-10-25T07:00:00", "kind": "shell", "command": "ls", "read_only": True, "exit": 0}))
check("render returns None for a file with no start entry", ef.render(_l3) is None)
_out = tmp / "report.md"
sys_argv_saved = sys.argv
sys.argv = ["export_findings.py", "--out", str(_out)]
try:
    ef.main()
finally:
    sys.argv = sys_argv_saved
check("export_findings writes a combined report file",
      _out.exists() and "2 run(s)" in _out.read_text() and "unfinished" in _out.read_text())

# terminal_relay (--web on the CLI): the terminal can answer too, racing the web page
from agent import terminal_relay  # noqa: E402

_relay_approvals = web.Approvals(timeout=5)
_r, _w = os.pipe()
_saved_stdin = sys.stdin
sys.stdin = os.fdopen(_r)
threading.Thread(target=terminal_relay, args=(_relay_approvals,), daemon=True).start()

_confirm_result = {}
_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Do a thing?")))
_th.start()
time.sleep(0.8)  # let the relay thread see the pending prompt and start reading
os.write(_w, b"y\n")
_th.join(3)
check("terminal 'y' approves a confirm prompt", _confirm_result.get("v") is True)

_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Do another thing?")))
_th.start()
time.sleep(0.8)
os.write(_w, b"n\n")
_th.join(3)
check("terminal 'n' declines a confirm prompt", _confirm_result.get("v") is False)

_ask_result = {}
_th = threading.Thread(target=lambda: _ask_result.update(v=_relay_approvals.ask("What is the path?")))
_th.start()
time.sleep(0.8)
os.write(_w, b"/tmp/demo\n")
_th.join(3)
check("terminal free text answers an ask prompt", _ask_result.get("v") == "/tmp/demo")

# a stale terminal line arriving just after the web page already answered must not flip the result
_th = threading.Thread(target=lambda: _confirm_result.update(v=_relay_approvals.confirm("Race me?")))
_th.start()
time.sleep(0.8)
_pending_id = _relay_approvals.pending["id"]
_relay_approvals.answer(_pending_id, True)  # the "web page" answers first
os.write(_w, b"n\n")  # a stale terminal line, typed before the user saw the web had already answered
_th.join(3)
check("a stale terminal answer after the web already answered does not flip the result",
      _confirm_result.get("v") is True and _relay_approvals.pending is None)

sys.stdin = _saved_stdin

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
