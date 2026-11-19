"""
Tests for the staged model screen (#126). Run with: .venv/bin/python tests/test_screen_model.py

Pure helpers and the tools stage against a stubbed chat function; no model, server or workspace is touched.
"""

import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import screen_model as sm  # noqa: E402

failures = 0


def check(name: str, ok: bool) -> None:
    global failures
    print(("PASS  " if ok else "FAIL  ") + name)
    failures += not ok


def call(name: str, args: str) -> dict:
    return {"function": {"name": name, "arguments": args}}


check("an empty reply is junk", sm.looks_like_junk(""))
check("a repeated word is junk", sm.looks_like_junk("ok " * 40))
check("a plain sentence is not junk", not sm.looks_like_junk("Cats sleep a lot and like warm places."))

calls, probs = sm.parse_calls({"tool_calls": [call("read_file", '{"path": "notes.txt"}')]})
check("a well-formed call parses with no problems", calls == [("read_file", {"path": "notes.txt"})] and not probs)
calls, probs = sm.parse_calls({"tool_calls": [call("search_web", '{"q": "x"}')]})
check("a tool that was not offered is a problem", any("invented" in p for p in probs))
calls, probs = sm.parse_calls({"tool_calls": [call("read_file", "not json")]})
check("arguments that are not JSON are a problem", any("JSON" in p for p in probs))
calls, probs = sm.parse_calls({"tool_calls": [call("read_file", "[1]")]})
check("arguments that are not an object are a problem", any("JSON" in p for p in probs))
check("no tool calls parses to nothing", sm.parse_calls({"content": "hi"}) == ([], []))

check("reply_text: content is the reply", sm.reply_text({"content": "Hello there."}) == "Hello there.")
check("reply_text: a final_answer call carries the reply when content is empty",
      sm.reply_text({"content": "", "tool_calls": [call("final_answer", '{"answer": "Cats purr."}')]}) == "Cats purr.")
check("reply_text: another tool call is not a reply", sm.reply_text({"content": "", "tool_calls": [call("read_file", '{"path": "a"}')]}) == "")

graders = {n: g for n, _, g in sm.TASKS}
check("read task: read_file on notes.txt passes", graders["read_a_file"]([("read_file", {"path": "notes.txt"})], ""))
check("read task: the wrong file fails", not graders["read_a_file"]([("read_file", {"path": "other.txt"})], ""))
check("final_answer task: the answer must carry 4", graders["final_answer"]([("final_answer", {"answer": "4"})], "")
      and not graders["final_answer"]([], "4"))
check("no-tool task: plain text passes", graders["no_tool_needed"]([], "Hello there."))
check("no-tool task: an empty reply fails", not graders["no_tool_needed"]([], " "))
check("no-tool task: reading a file for a greeting fails", not graders["no_tool_needed"]([("read_file", {"path": "x"})], ""))


def stub(good: bool):
    def chat(backend, model, prompt, tools=True, max_tokens=400):
        if not good:
            return {"choices": [{"message": {"content": "", "tool_calls": [call("run_code", "{}")]}}]}
        if "notes.txt" in prompt:
            m = {"content": "", "tool_calls": [call("read_file", '{"path": "notes.txt"}')]}
        elif "sum" in prompt:
            m = {"content": "", "tool_calls": [call("final_answer", '{"answer": "4"}')]}
        else:
            m = {"content": "Hello!"}
        return {"choices": [{"message": m}]}
    return chat


sm.chat = stub(True)
ok, detail, data = sm.stage_tools(Namespace(backend="lmstudio", model="m"))
check("tools stage: a model that gets every task right passes", ok and data["passed"] == 9)
sm.chat = stub(False)
ok, detail, data = sm.stage_tools(Namespace(backend="lmstudio", model="m"))
check("tools stage: a model that invents tools fails", not ok and any("invented" in p for p in data["problems"]))

print(f"{failures} failed")
sys.exit(1 if failures else 0)
