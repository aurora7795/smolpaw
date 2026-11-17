"""
first_call_tokens on LM Studio (#135): the first request goes to the backend's own /v1 endpoint with max_tokens=1, and the
count read is usage.prompt_tokens. A local fake server stands in for the model; nothing is loaded and no real notes are read.
"""

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import agent as agent_mod  # noqa: E402
from tests import first_call_tokens as fct  # noqa: E402

failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


seen: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append({"path": self.path, "body": body})
        out = json.dumps({"choices": [{"message": {"role": "assistant", "content": "x"}}],
                          "usage": {"prompt_tokens": 1234 if body.get("tools") else 321}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}/v1"

fct.isolate(Path(tempfile.mkdtemp()), "# notes\n")
agent = agent_mod.build_agent("fake-model", backend="lmstudio")
check("the full first call reads usage.prompt_tokens", fct.first_call_tokens(agent, base_url=base) == 1234)
check("the call without tools reads its own count", fct.first_call_tokens(agent, with_tools=False, base_url=base) == 321)
check("the request goes to the given base url's /chat/completions", all(s["path"] == "/v1/chat/completions" for s in seen))
check("the request asks for one token and carries the model id",
      all(s["body"].get("max_tokens") == 1 and s["body"].get("model") == "fake-model" for s in seen))
check("LM Studio's base url is the one the agent uses", agent_mod.BACKENDS["lmstudio"]["url"].endswith("/v1"))

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
