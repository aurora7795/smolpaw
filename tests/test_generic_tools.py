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
class _Page:
    def json(self):
        return {"service": "x", "resources": {}}


g.requests.get = lambda *a, **k: _Page()
msg = g.openapi_search("http://x/index", "queue")
check("openapi_search explains non-spec JSON", "not an OpenAPI spec" in msg and "http_request" in msg)
g.requests.get = lambda *a, **k: _Resp()
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

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
