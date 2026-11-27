"""
Tests for tests/speed.py (#148). Run with: .venv/bin/python tests/test_speed.py

Uses a local server that streams canned events; touches no real model, workspace or notes.
"""

import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import speed  # noqa: E402


def chunk(text="", **delta):
    return {"choices": [{"delta": {"content": text, **delta}}]}


# Timing from events: first token at 2.0s, last at 6.0s, 41 output tokens -> 40 tokens over 4s = 10 tok/s.
events = [(1.0, {"choices": [{"delta": {"role": "assistant"}}]}), (2.0, chunk("a")), (4.0, chunk("b")), (6.0, chunk("c")),
          (6.1, {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 41}})]
row = speed.timing_from_events(0.0, events)
assert row["ttft_s"] == 2.0 and row["total_s"] == 6.0, row
assert row["decode_tok_s"] == 10.0 and row["prefill_tok_s"] == 500 and row["output_tokens"] == 41, row

# Thinking tokens and tool calls count as the first token; an empty role chunk does not.
assert speed.timing_from_events(0.0, [(0.5, {"choices": [{"delta": {"content": "", "reasoning": "hm"}}]})])["ttft_s"] == 0.5
assert speed.timing_from_events(0.0, [(0.7, {"choices": [{"delta": {"tool_calls": [{"x": 1}]}}]})])["ttft_s"] == 0.7
assert "error" in speed.timing_from_events(0.0, [(1.0, {"choices": [{"delta": {"role": "assistant"}}]})])

# A single-token reply has no decode rate rather than a division by zero.
one = speed.timing_from_events(0.0, [(1.0, chunk("a")), (1.0, {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}})])
assert "decode_tok_s" not in one

# Verdicts: higher-is-better and lower-is-better, with the edges.
assert speed.verdict("decode_tok_s", 20) == "good" and speed.verdict("decode_tok_s", 10) == "usable"
assert speed.verdict("decode_tok_s", 9.9) == "slow" and speed.verdict("first_cold_s", 5) == "good"
assert speed.verdict("first_cold_s", 15.1) == "slow" and speed.verdict("load_s", None) == "n/a"

assert speed.median([{"a": 1}, {"a": 3}, {}], "a") == 2 and speed.median([{}], "a") is None

# A fresh start is added to a string or a list system message, and the original request is untouched.
body = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]}
fresh = speed.with_fresh_start(body, "t1")
assert fresh["messages"][0]["content"] == "[t1]\nS" and body["messages"][0]["content"] == "S"
parts = speed.with_fresh_start({"messages": [{"role": "system", "content": [{"type": "text", "text": "S"}]}]}, "t2")
assert parts["messages"][0]["content"] == [{"type": "text", "text": "[t2]\nS"}]

# A real streamed request against a local server.
class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        if body["model"] == "bad":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in [chunk("x"), chunk("y"), {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}]:
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *a):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/chat"
got = speed.stream_request(url, {"model": "m", "messages": []})
assert got["output_tokens"] == 2 and got["prompt_tokens"] == 9 and got["ttft_s"] >= 0, got
assert speed.stream_request(url, {"model": "bad", "messages": []})["error"].startswith("500")
server.shutdown()

# The headline figures come from the smallest sweep size.
res = {"load_s": 4, "first": {"cold_ttft_s": 6}, "long": {"total_s": 200},
       "sweep": [{"target_tokens": 0, "decode_tok_s": 25}, {"target_tokens": 12000, "decode_tok_s": 12}]}
j = speed.judged(res)
assert j["decode_tok_s"] == {"value": 25, "verdict": "good"} and j["first_cold_s"]["verdict"] == "usable"
assert j["long_s"]["verdict"] == "slow" and j["load_s"]["verdict"] == "good"
print("test_speed: ok")
