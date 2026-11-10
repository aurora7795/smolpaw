"""
Tests for per-chat models in the web harness (issue #96).
Run with: .venv/bin/python tests/test_chat_models.py

Uses a fake agent, a fake build_agent and temporary logs; never touches the real workspace, notes.md or logs/.
"""

import datetime as dt
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generic_tools as g  # noqa: E402
import schedules  # noqa: E402
import web  # noqa: E402

tmp = Path(tempfile.mkdtemp())
schedules.PATH = tmp / "schedules.json"
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.WORKSPACE.mkdir()


class Clock(dt.datetime):
    """Each call to now() is one second later, so every run log gets its own file name."""
    t = dt.datetime(2026, 11, 10, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        cls.t += dt.timedelta(seconds=1)
        return cls.t


g.datetime = Clock


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0


class FakeAgent:
    """Answers at once; remembers which backend and model it was built for."""

    def __init__(self, model: str = "m", backend: str = "lmstudio"):
        self.model_id, self.backend = model, backend
        self.memory = type("M", (), {"steps": []})()
        self.monitor = type("Mon", (), {"get_total_token_counts": lambda s: type("T", (), {
            "input_tokens": 1, "output_tokens": 1})()})()
        self.stall_reason = None
        self.inputs: list[str] = []

    def run(self, text):
        self.inputs.append(text)
        return "done"

    def interrupt(self):
        pass


built: list[tuple[str, str]] = []
fail_models: set[str] = set()


def fake_build_agent(model, toolset, max_steps, tools, backend):
    if model in fail_models:
        raise RuntimeError("cannot build")
    built.append((backend, model))
    return FakeAgent(model, backend)


released: list[tuple[str, str]] = []
installed: dict[str, list[str]] = {"lmstudio": ["m", "m2", "m3", "gone-ok"], "ollama": ["o1", "o2"]}

web.build_agent = fake_build_agent
web.release_model = lambda backend, model: released.append((backend, model))
web.list_models = lambda backend: installed.get(backend, [])


def make(model: str = "m", backend: str = "lmstudio") -> web.Session:
    return web.Session(FakeAgent(model, backend), model, web.Approvals(), backend, 5, run_summaries=False)


def wait_idle(sess: web.Session) -> None:
    for _ in range(400):
        if sess.status == "idle":
            return
        time.sleep(0.02)


def run(sess: web.Session, prompt: str, **kw) -> bool:
    ok = sess.start(prompt, **kw)
    wait_idle(sess)
    return ok


def starts(thread: str | None = None) -> list[dict]:
    out = []
    for f in sorted(g.LOG_DIR.glob("*.jsonl")):
        e = web._log_start(f)
        if thread is None or e.get("thread") == thread:
            out.append(e)
    return out


def write_log(name: str, **start) -> None:
    g.LOG_DIR.mkdir(exist_ok=True)
    (g.LOG_DIR / f"{name}.jsonl").write_text(json.dumps({"t": "2026-11-10T10:00:00", "kind": "start", **start}) + "\n")


# --- the log records the backend --------------------------------------------------------------

p = g.start_log("mod-a", "hello", "th-0", None, "ollama")
check("start_log records the backend", web._log_start(p).get("backend") == "ollama")
p = g.start_log("mod-b", "hello")
check("start_log without a backend leaves the entry as it was", "backend" not in web._log_start(p))

s = make("m")
run(s, "first")
st = starts()[-1]
check("a web run logs its backend and model", st.get("backend") == "lmstudio" and st.get("model") == "m")

# --- reading a chat's model back -------------------------------------------------------------

write_log("20261110-100000-x", thread="t-new", model="o1", backend="ollama")
write_log("20261110-100100-x", thread="t-mixed", model="m", backend="lmstudio")
write_log("20261110-100200-x", thread="t-mixed", model="o2", backend="ollama")
write_log("20261110-100300-x", thread="t-old", model="m2")
write_log("20261110-100400-x", thread="t-badbackend", model="m3", backend="bogus")
check("a chat's backend and model come from its log", web._thread_choice("t-new") == ("ollama", "o1"))
check("the latest run in a chat decides", web._thread_choice("t-mixed") == ("ollama", "o2"))
check("a log from before the backend was recorded gives no backend", web._thread_choice("t-old") == (None, "m2"))
check("an unknown backend in a log is ignored", web._thread_choice("t-badbackend") == (None, "m3"))
check("a chat with no log gives nothing", web._thread_choice("t-none") is None)
detail = web._run_detail(g.LOG_DIR / "20261110-100200-x.jsonl")
check("run detail carries the model and backend", detail["model"] == "o2" and detail["backend"] == "ollama")
detail = web._run_detail(g.LOG_DIR / "20261110-100300-x.jsonl")
check("run detail has an empty backend for old logs", detail["model"] == "m2" and detail["backend"] == "")

# --- switching in the middle of a chat -----------------------------------------------------

built.clear(), released.clear()
s = make("m")
run(s, "one")
chat = s.thread
agent_before = s.agent
run(s, "two", backend="ollama", model="o1")
check("an explicit model rebuilds the agent for the chat", built == [("ollama", "o1")] and s.model == "o1"
      and s.backend == "ollama" and s.agent is not agent_before)
check("the switch is recorded in that run's log", starts(chat)[-1].get("model") == "o1"
      and starts(chat)[-1].get("backend") == "ollama" and starts(chat)[0].get("model") == "m")
check("the default is unchanged by a chat's choice", (s.default_backend, s.default_model) == ("lmstudio", "m"))
check("the chat stays one thread", s.thread == chat and len(s.history) == 1)
check("the old backend's model is unloaded before the run", released == [("lmstudio", "m")])
agent_o1 = s.agent
run(s, "three")
check("a follow-up with no model keeps the chat's model", s.agent is agent_o1 and s.model == "o1" and len(built) == 1)
released.clear()
run(s, "four", backend="ollama", model="o2")
check("a switch within one backend unloads nothing", released == [] and s.model == "o2")
run(s, "five", backend="lmstudio", model="m2")
check("switching back releases the other backend's model", released == [("ollama", "o2")])

# --- continuing a chat from Recents restores its model ------------------------------------------

s = make("m")
run(s, "continue it", thread="t-new")
check("a chat picked from Recents gets its own backend and model", (s.backend, s.model) == ("ollama", "o1")
      and s.notice == "")
check("it keeps its earlier turns' thread", s.thread == "t-new")
s = make("m")
run(s, "old log", thread="t-old")
check("a log with no backend uses the default backend and its model", (s.backend, s.model) == ("lmstudio", "m2"))
write_log("20261110-100500-x", thread="t-gone", model="vanished", backend="ollama")
write_log("20261110-100600-x", thread="t-gone2", model="vanished", backend="ollama")
s = make("m")
run(s, "continue gone", thread="t-gone")
check("a model that is no longer installed falls back to the default with a notice",
      (s.backend, s.model) == ("lmstudio", "m") and "vanished" in s.notice and "m" in s.notice)
run(s, "next message in the same chat")
check("the notice clears on the next message", s.notice == "")
installed_saved = installed["ollama"]
installed["ollama"] = []  # server unreachable: it cannot be told, so the model is tried
s = make("m")
run(s, "unreachable", thread="t-gone2")
check("an unreachable server does not trigger the fallback", s.model == "vanished" and s.notice == "")
installed["ollama"] = installed_saved
fail_models.add("o1")
s = make("m")
run(s, "cannot build", thread="t-new")
check("a model that cannot be built falls back to the default with a notice",
      s.model == "m" and "o1" in s.notice)
fail_models.clear()
s = make("m")
run(s, "explicit, cannot build", backend="ollama", model="o1")
check("an explicit model that exists switches", s.model == "o1")
s = make("m")
run(s, "viewing t-new but picking another", thread="t-new", backend="lmstudio", model="m3")
check("an explicit model beats the chat's own", s.model == "m3" and s.thread == "t-new")

# --- new chats and scheduled runs use the default --------------------------------------------

s = make("m")
run(s, "a", backend="ollama", model="o1")
s.new_thread()
check("a new chat goes back to the default model", (s.backend, s.model) == ("lmstudio", "m") and s.thread is None)
run(s, "b", backend="ollama", model="o1")
chat = s.thread
sid = schedules.add("check", "*/5 * * * *")["id"]
run(s, "scheduled", schedule=sid)
check("a scheduled run uses the default model", starts()[-1].get("schedule") == sid
      and starts()[-1].get("model") == "m" and starts()[-1].get("backend") == "lmstudio")
check("a scheduled run does not touch the chat's log", starts(chat)[-1].get("model") == "o1")
run(s, "back to the chat", thread=chat)
check("the chat is still on its own model after a scheduled run", s.model == "o1" and s.thread == chat)

# --- the Settings card changes the default, not a chat's own model ------------------------------

s = make("m")
s.configure("lmstudio", "m2", 5, 0)
check("Settings moves a chat that is on the default to the new default",
      s.model == "m2" and s.default_model == "m2")
run(s, "x", backend="ollama", model="o1")
s.configure("lmstudio", "m3", 5, 0)
check("Settings leaves a chat on its own model alone but changes the default",
      s.model == "o1" and s.default_model == "m3" and s.default_backend == "lmstudio")
s.new_thread()
check("the next new chat uses the new default", s.model == "m3")
agent_x = s.agent
s.configure("lmstudio", "m3", 9, 0)
check("a step-limit change still rebuilds the agent", s.agent is not agent_x and s.max_steps == 9)

# --- the HTTP interface ------------------------------------------------------------------------

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
token = "tok"
s = make("m")
srv = web.serve("127.0.0.1", port, token, s.approvals, s, {"mode": "agent"})
base = f"http://127.0.0.1:{port}"


def post(path: str, body: dict) -> int:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"X-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def state() -> dict:
    req = urllib.request.Request(base + "/api/state", headers={"X-Token": token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


for label, body in [("an unknown backend", {"prompt": "p", "backend": "x", "model": "m"}),
                    ("a backend with no model", {"prompt": "p", "backend": "ollama"}),
                    ("a model with no backend", {"prompt": "p", "model": "o1"}),
                    ("an empty model", {"prompt": "p", "backend": "ollama", "model": " "}),
                    ("a number for a model", {"prompt": "p", "backend": "ollama", "model": 5}),
                    ("a very long model", {"prompt": "p", "backend": "ollama", "model": "x" * 201})]:
    check(f"/api/run refuses {label}", post("/api/run", body) == 400 and s.status == "idle" and s.model == "m")
check("/api/run accepts a backend and model", post("/api/run", {"prompt": "p", "backend": "ollama", "model": "o1"}) == 200)
wait_idle(s)
st = state()
check("/api/state reports the chat's model and the default",
      st["model"] == "o1" and st["backend"] == "ollama" and st["default_model"] == "m"
      and st["default_backend"] == "lmstudio" and st["notice"] == "")
srv.shutdown()

# --- listing models and unloading them -----------------------------------------------------------

del web.list_models  # use the module's own again for the next checks (the fake was set on the module)
import importlib  # noqa: E402

importlib.reload(web)


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.data

    def close(self):
        pass


real_urlopen = urllib.request.urlopen
payload = {"data": [{"id": "qwen3.5-9b-mlx"}, {"id": "text-embedding-nomic-embed-text-v1.5"},
                    {"id": "google/gemma-4-e4b"}, {"id": "nomic-embed-text:latest"}]}
urllib.request.urlopen = lambda req, timeout=None: FakeResponse(json.dumps(payload).encode())
listed = web.list_models("lmstudio")
urllib.request.urlopen = real_urlopen
check("embedding models are left out of the model list", listed == ["google/gemma-4-e4b", "qwen3.5-9b-mlx"])

sent = {}


def fake_urlopen(req, timeout=None):
    sent["url"], sent["body"] = req.full_url, json.loads(req.data)
    return FakeResponse(b"{}")


urllib.request.urlopen = fake_urlopen
web.release_model("ollama", "qwen3.5:9b")
urllib.request.urlopen = real_urlopen
check("Ollama is told to drop the model at once", sent.get("url") == "http://127.0.0.1:11434/api/generate"
      and sent.get("body") == {"model": "qwen3.5:9b", "keep_alive": 0})

calls = []
real_run, real_exists = web.subprocess.run, web.os.path.exists
web.subprocess.run = lambda cmd, **kw: calls.append(cmd)
web.os.path.exists = lambda p: True
web.release_model("lmstudio", "qwen3.5-9b-mlx")
web.subprocess.run, web.os.path.exists = real_run, real_exists
check("LM Studio is asked to unload the model by name",
      len(calls) == 1 and calls[0][1:] == ["unload", "qwen3.5-9b-mlx"] and calls[0][0].endswith("lms"))


def boom(req, timeout=None):
    raise OSError("down")


urllib.request.urlopen = boom
try:
    web.release_model("ollama", "x")
    survived = True
except Exception:  # noqa: BLE001
    survived = False
urllib.request.urlopen = real_urlopen
check("an unreachable server does not break a switch", survived)

page = web.PAGE
check("the page has a model dropdown in the composer", 'id="cmodel"' in page and 'id="notice"' in page)

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
