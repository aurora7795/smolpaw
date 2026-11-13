"""
Tests for secrets entered on the web page (secret_store.py, the /api/secret* routes, and masking in generic_tools).
Run with: .venv/bin/python tests/test_secrets.py

Uses a temporary .env, workspace and logs; never touches the real .env, workspace/ or logs/.
"""

import json
import os
import socket
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent  # noqa: E402
import generic_tools as g  # noqa: E402
import secret_store  # noqa: E402
import web  # noqa: E402

tmp = Path(tempfile.mkdtemp())
secret_store.PATH = tmp / ".env"
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.WORKSPACE.mkdir()
g.NOTES = tmp / "notes.md"


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0

env = secret_store.PATH
for name in ("ROUTER_PASS", "ROUTER_USER", "QUOTE_PASS", "WEB_SECRET", "RESTART_PASS", "OKNAME"):
    os.environ.pop(name, None)  # importing agent loaded the real .env, which may already define some of these
PW = "santiago-7"

# --- the store -------------------------------------------------------------------

check("no .env yet: no names", secret_store.names() == [])
check("a secret is saved", secret_store.set_secret("ROUTER_PASS", PW) is None)
check("it is listed by name", secret_store.names() == ["ROUTER_PASS"])
check("it is in the environment for shell commands and services", os.environ.get("ROUTER_PASS") == PW)
check(".env is readable by the owner only", stat.S_IMODE(env.stat().st_mode) == 0o600)
check(".env holds a NAME=value line in the marked block",
      f"ROUTER_PASS={PW}" in env.read_text() and secret_store.BEGIN in env.read_text())
check("its value is returned for masking", secret_store.values() == [PW])

env.write_text("RADARR_API_KEY=abc123\n# keep me\n" + env.read_text())
check("setting another secret keeps the other lines",
      secret_store.set_secret("ROUTER_USER", "admin-user") is None
      and "RADARR_API_KEY=abc123" in env.read_text() and "# keep me" in env.read_text())
check("both are listed, sorted", secret_store.names() == ["ROUTER_PASS", "ROUTER_USER"])
check("saving a name again replaces it, with one line",
      secret_store.set_secret("ROUTER_PASS", "other-pass-1") is None
      and env.read_text().count("ROUTER_PASS=") == 1 and os.environ["ROUTER_PASS"] == "other-pass-1")
check("values are masked longest first", secret_store.values() == ["other-pass-1", "admin-user"])

os.environ["ALREADY_SET"] = "x"
for bad, why in [("lower", "lowercase"), ("A", "one character"), ("1ABC", "starts with a digit"), ("A B", "a space"),
                 ("A=B", "an equals sign"), ("PATH", "reserved"), ("LD_PRELOAD", "reserved prefix"),
                 ("DYLD_INSERT_LIBRARIES", "reserved prefix"), ("SMOLPAW_WEB_TOKEN", "reserved prefix"),
                 ("ALREADY_SET", "set outside this page"), ("A" * 65, "too long"), (7, "not a string"), (None, "none")]:
    check(f"refused name: {why}", secret_store.set_secret(bad, "value-1234") is not None)
for bad, why in [("", "empty"), (" x ", "spaces at the ends"), ("a\nb", "a newline"), ("a\0b", "a NUL"),
                 ("x" * 5000, "too long"), (5, "not a string"), (None, "none")]:
    check(f"refused value: {why}", secret_store.set_secret("OKNAME", bad) is not None)
check("a refused save changes nothing", secret_store.names() == ["ROUTER_PASS", "ROUTER_USER"] and "OKNAME" not in os.environ)
check("an error message never contains the value", PW not in (secret_store.set_secret("PATH", PW) or ""))

check("deleting removes it from the file and the environment",
      secret_store.delete_secret("ROUTER_USER") and "ROUTER_USER" not in os.environ
      and "ROUTER_USER" not in env.read_text() and "RADARR_API_KEY=abc123" in env.read_text())
check("deleting an unknown name is False", secret_store.delete_secret("NOPE") is False)
secret_store.delete_secret("ROUTER_PASS")
check("with none left the block is gone and other lines stay",
      secret_store.BEGIN not in env.read_text() and "RADARR_API_KEY=abc123" in env.read_text())

# --- masking in tool output and the run log ----------------------------------------

secret_store.set_secret("ROUTER_PASS", PW)
secret_store.set_secret("QUOTE_PASS", 'pa"ss\\word9')
check("_redact masks a saved secret", g._redact(f"login with {PW} ok") == "login with [REDACTED] ok")
check("_redact masks a saved secret that has JSON-escaped characters",
      "pa" not in g._redact(json.dumps({"o": 'pa"ss\\word9'})).replace("[REDACTED]", ""))

g._approved = lambda desc: True
out = g.run_shell('echo "pw is $ROUTER_PASS"')
check("a shell command can use $NAME and the value is masked in what the model sees",
      "[REDACTED]" in out and PW not in out)
g.start_log("m", "hello")
g.run_shell('echo "again $ROUTER_PASS"')
logs = "".join(f.read_text() for f in g.LOG_DIR.glob("*.jsonl"))
check("the run log never holds the value", PW not in logs and "[REDACTED]" in logs)

# --- the web routes ------------------------------------------------------------------

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
token = "t0ken-for-tests"
srv = web.serve("127.0.0.1", port, token, web.Approvals(), None, {})
base = f"http://127.0.0.1:{port}"


def call(path: str, body: dict | None = None, tok: str | None = token) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Token": tok or "", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


for name in secret_store.names():
    secret_store.delete_secret(name)
code, data = call("/api/secret_set", {"name": "WEB_SECRET", "value": "from-the-web-1"})
check("POST /api/secret_set saves it and answers with names only",
      code == 200 and data == {"ok": True, "names": ["WEB_SECRET"]} and os.environ["WEB_SECRET"] == "from-the-web-1")
code, data = call("/api/secrets")
check("GET /api/secrets lists names, never values", code == 200 and data == {"names": ["WEB_SECRET"]})
check("no response contains the value", "from-the-web-1" not in json.dumps(data))
code, data = call("/api/secret_set", {"name": "PATH", "value": "from-the-web-1"})
check("a refused save is a 400 with a reason that does not hold the value",
      code == 400 and data.get("error") and "from-the-web-1" not in json.dumps(data))
check("missing fields are a 400", call("/api/secret_set", {})[0] == 400)
check("a wrong token is refused", call("/api/secret_set", {"name": "NOPE_X", "value": "value-1234"}, "bad")[0] == 403
      and call("/api/secrets", None, "bad")[0] == 403 and "NOPE_X" not in secret_store.names())
code, data = call("/api/secret_delete", {"name": "WEB_SECRET"})
check("POST /api/secret_delete removes it", code == 200 and data == {"ok": True, "names": []} and "WEB_SECRET" not in os.environ)
check("deleting an unknown name is a 404", call("/api/secret_delete", {"name": "WEB_SECRET"})[0] == 404)
srv.shutdown()

page = web.PAGE
check("the Settings page has a Secrets form with a password-type value field",
      'id="secname"' in page and 'id="secvalue" type="password"' in page and 'id="secretlist"' in page)
check("the page clears the value after every save", '$("secvalue").value = ""' in page)

# --- startup reads the block back, like any .env line ------------------------------------

secret_store.set_secret("RESTART_PASS", "survives-restart-1")
del os.environ["RESTART_PASS"]
agent.load_env(str(env))  # an absolute path is used as given
check("after a restart the saved secret loads from .env like any other line",
      os.environ.get("RESTART_PASS") == "survives-restart-1")

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
