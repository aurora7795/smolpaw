"""
Tests for model-call status reporting (model_status.py and agent.StatusModel).
Run with: .venv/bin/python tests/test_model_status.py

Uses a local HTTP server that fails on command; touches no real model, workspace or notes.
"""

import io
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent as agent_mod  # noqa: E402
import model_status as ms  # noqa: E402

OK = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
      "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}],
      "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}


class Handler(BaseHTTPRequestHandler):
    script: list = []  # one entry per request: an HTTP status, or ("sleep", seconds) then 200
    hits = 0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        step = Handler.script[min(Handler.hits, len(Handler.script) - 1)]
        Handler.hits += 1
        if isinstance(step, tuple):
            time.sleep(step[1])
            step = 200
        body = json.dumps(OK if step == 200 else {"error": {"message": f"boom {step}"}}).encode()
        self.send_response(step)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_port}/v1"


def model(url=URL):
    m = agent_mod.StatusModel(model_id="m", api_base=url, api_key="k")
    return m


def run(script, retries=2, url=URL, idle=30.0):
    """Return (reply or None, error or None, status text) for one generate() call."""
    Handler.script, Handler.hits = script, 0
    out = io.StringIO()
    ms.REPORTER.stream, ms.REPORTER.idle_interval = out, idle
    saved_pause, ms.pause = ms.pause, lambda s: None  # no real backoff waits
    try:
        m = model(url)
        m.retries = retries
        try:
            return m.generate([{"role": "user", "content": "hi"}]), None, out.getvalue()
        except Exception as exc:  # noqa: BLE001
            return None, exc, out.getvalue()
    finally:
        ms.pause = saved_pause
        ms.REPORTER.stream = None


# 1. Two 503s then success: the call works, each retry is announced with its number, and the server saw 3 requests.
reply, err, text = run([503, 503, 200])
assert reply is not None and reply.content == "hi" and err is None, (reply, err)
assert Handler.hits == 3, Handler.hits
assert "HTTP 503" in text and "Retry 1 of 2" in text and "Retry 2 of 2" in text, text
print("ok: transient 503s are retried and announced")

# 2. Retries run out: a ModelCallError that says so, after exactly retries+1 requests.
reply, err, text = run([500], retries=2)
assert isinstance(err, ms.ModelCallError) and "HTTP 500" in str(err) and "3 attempts" in str(err), err
assert Handler.hits == 3 and "failed after 3 attempts" in text, (Handler.hits, text)
print("ok: persistent 500 ends in a clear error after the configured retries")

# 3. retries=0 means one attempt, no retry line.
reply, err, text = run([503], retries=0)
assert isinstance(err, ms.ModelCallError) and Handler.hits == 1 and "Retry" not in text, (Handler.hits, text)
print("ok: retries=0 does not retry")

# 4. A 404 (wrong model name) is not transient: no retry, and the message names the model.
reply, err, text = run([404])
assert isinstance(err, ms.ModelCallError) and Handler.hits == 1 and "Retry" not in text, (Handler.hits, text)
assert "'m'" in str(err) and "HTTP 404" in str(err), err
print("ok: 404 is not retried and names the model")

# 5. Nothing listening: the error says the server cannot be reached and is retried.
free = socket.socket()
free.bind(("127.0.0.1", 0))
dead = f"http://127.0.0.1:{free.getsockname()[1]}/v1"
free.close()
reply, err, text = run([200], retries=1, url=dead)
assert isinstance(err, ms.ModelCallError) and "cannot reach the model server" in str(err), err
assert dead in str(err) and "Retry 1 of 1" in text and "failed after 2 attempts" in text, text
assert isinstance(err.__cause__, ms.openai.APIConnectionError)
print("ok: a dead server is reported as unreachable, with the address")

# 6. A slow reply shows an elapsed-time heartbeat (non-terminal output: one line per interval) and a slow-reply note.
ms.SLOW_REPLY = 0.5
reply, err, text = run([("sleep", 1.3)], idle=0.4)
assert reply is not None, err
assert "[model] waiting for m... 0s" in text and text.count("waiting for m...") >= 2, text
assert "replied after" in text, text
ms.SLOW_REPLY = 10.0
print("ok: a slow call prints elapsed time and a note when it replies")

# 7. A fast reply prints nothing, and with no stream set nothing is printed at all.
reply, err, text = run([200])
assert text == "", text
Handler.script, Handler.hits = [503, 200], 0
assert ms.REPORTER.stream is None
ms.pause, saved = (lambda s: None), ms.pause
m = model()
m.retries = 2
assert m.generate([{"role": "user", "content": "hi"}]).content == "hi"
ms.pause = saved
print("ok: quiet when fast, and silent when no stream is set")

# 8. describe() on its own, and the retry predicate.
import httpx2 as httpx  # noqa: E402  (the module this openai version builds on)

req = httpx.Request("POST", URL)
assert ms.is_retryable(ms.openai.APITimeoutError(request=req))
assert not ms.is_retryable(ms.openai.NotFoundError("x", response=httpx.Response(404, request=req), body=None))
assert ms.is_retryable(ms.openai.RateLimitError("x", response=httpx.Response(429, request=req), body=None))
assert "timed out" in ms.describe(ms.openai.APITimeoutError(request=req), URL)
assert ms.fmt_elapsed(5) == "5s" and ms.fmt_elapsed(65) == "1m 05s"
print("ok: classification and formatting")

# 9. The status layer replaces both retry layers: the client is built with max_retries=0 and smolagents' retry off.
m = model()
assert m.client.max_retries == 0 and m.retryer.max_attempts == 1
print("ok: client and smolagents retries are off")
