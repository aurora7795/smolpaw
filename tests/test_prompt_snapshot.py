"""
Prompt snapshot (#127): the first call's request as the model sees it, committed so a change shows up as a diff.

Renders the system prompt and then each tool's schema (as JSON, sorted by tool name) for the generic agent built as
agent.py does, with an empty notes.md, only git-tracked skills and the default web search (the isolation used by
tests/first_call_tokens.py). The home folder is written as <HOME> so the file is the same on every machine. The check
fails when the rendering differs from tests/prompt_snapshot.txt, and prints the diff. After a deliberate change:

  .venv/bin/python tests/test_prompt_snapshot.py --update
"""

import difflib
import json
import os
import sys
import tempfile
from pathlib import Path

from smolagents.agents import SystemPromptStep, TaskStep
from smolagents.models import get_tool_json_schema

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["SMOLPAW_SEARCH_PROVIDER"] = "ddgs"
os.environ.pop("SMOLPAW_SYSTEM_PROMPT", None)  # the default (compact) style
import agent as agent_mod  # noqa: E402
from tests.first_call_tokens import isolate  # noqa: E402

SNAPSHOT = Path(__file__).parent / "prompt_snapshot.txt"


def render() -> str:
    """The first call's request as text: each message, then each tool schema."""
    isolate(Path(tempfile.mkdtemp()), "# notes\n")
    agent = agent_mod.build_agent("snapshot", backend="ollama")
    agent.memory.reset()
    agent.memory.system_prompt = SystemPromptStep(system_prompt=agent.initialize_system_prompt())
    agent.memory.steps.append(TaskStep(task="hello"))
    parts = []
    for m in agent.write_memory_to_messages():
        content = m.content
        text = "".join(c.get("text", "") for c in content) if isinstance(content, list) else str(content)
        parts.append(f"===== message: {getattr(m.role, 'value', m.role)} =====\n{text}")
    for name in sorted(agent.tools):
        schema = json.dumps(get_tool_json_schema(agent.tools[name]), indent=2, sort_keys=True)
        parts.append(f"===== tool: {name} =====\n{schema}")
    return "\n\n".join(parts).replace(str(Path.home()), "<HOME>") + "\n"


def main() -> None:
    now = render()
    if "--update" in sys.argv:
        SNAPSHOT.write_text(now)
        print(f"wrote {SNAPSHOT}: {len(now)} characters")
        return
    old = SNAPSHOT.read_text() if SNAPSHOT.exists() else ""
    if now == old:
        print(f"PASS  the first-call request matches {SNAPSHOT.name} ({len(now)} characters)")
        print("\n0 failed")
        return
    print(f"FAIL  the first-call request differs from {SNAPSHOT.name}:\n")
    diff = list(difflib.unified_diff(old.splitlines(), now.splitlines(), "recorded", "now", lineterm="", n=2))
    print("\n".join(diff[:200]) + ("\n... (diff cut at 200 lines)" if len(diff) > 200 else ""))
    print("\nIf the change is deliberate, refresh with: .venv/bin/python tests/test_prompt_snapshot.py --update")
    print("\n1 failed")
    sys.exit(1)


if __name__ == "__main__":
    main()
