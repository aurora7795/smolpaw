"""
Tests for the per-run wall-clock timeout in tests/eval.py (issue #133).
Run with: .venv/bin/python tests/test_run_timeout.py

Uses a local socket server that accepts and never answers; touches no real model, workspace or notes.
"""

import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent as agent_mod  # noqa: E402
from tests import eval as ev  # noqa: E402


class Fast:
    def run(self, prompt):
        return "done"


class Boom:
    def run(self, prompt):
        raise ValueError("bad")


assert ev.run_with_timeout(Fast(), "x", 5) == ("done", "", False)
answer, error, timed_out = ev.run_with_timeout(Boom(), "x", 5)
assert (answer, timed_out) == ("", False) and error == "ValueError: bad", (answer, error)
assert ev.run_with_timeout(Fast(), "x", None)[0] == "done"

# A server that accepts the connection and never replies: the run must end at the timeout, not hang.
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(5)
held = []
threading.Thread(target=lambda: [held.append(srv.accept()) for _ in range(5)], daemon=True).start()
agent_mod.BACKENDS["lmstudio"] = {**agent_mod.BACKENDS["lmstudio"], "url": f"http://127.0.0.1:{srv.getsockname()[1]}/v1"}

t0 = time.time()
r = ev.run_once("m", "hello", [], 3, "lmstudio") if not setattr(ev, "RUN_TIMEOUT", 2.0) else None
wall = time.time() - t0
assert r["timed_out"] and not r["passed"], r
assert r["error"].startswith("TimedOut"), r["error"]
assert wall < 20, wall
print(f"ok: hung model ended after {wall:.1f}s with timed_out set")
