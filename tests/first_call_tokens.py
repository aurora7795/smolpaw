"""
Measure the size of SmolPaw's first model call, in tokens, on Ollama models.

Builds the generic agent exactly as agent.py does, with an empty notes.md and a temporary skills folder
holding only the skills tracked in git (so the real notes, memory and any skills you wrote do not change
the figure), writes the first-turn messages the way smolagents does, and sends them to Ollama's
OpenAI-compatible endpoint with max_tokens=1. The count is `usage.prompt_tokens`: the real tokenized
prompt including the chat template and the tool schemas.

Three figures per model: the whole first call, the same call with no tools (the instructions alone, so the
difference is the tool schemas), and the whole call with web_search unregistered (its default-on cost, #44).
Read-only; unloads whatever Ollama has loaded first, since only one model fits on 16GB.

  .venv/bin/python tests/first_call_tokens.py --models qwen3.5:9b gemma4:e4b
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from smolagents.agents import SystemPromptStep, TaskStep

sys.path.insert(0, str(Path(__file__).parent.parent))
import agent as agent_mod  # noqa: E402
import generic_tools as g  # noqa: E402

OLLAMA = "http://localhost:11434"
PROMPT = "hello"


def isolate(tmp: Path, notes: str) -> None:
    """Point the harness at an empty notes.md and a skills folder with only git-tracked skills."""
    (tmp / "notes.md").write_text(notes)
    skills = tmp / "skills"
    skills.mkdir()
    tracked = subprocess.run(["git", "ls-files", "skills/*.md"], cwd=g.ROOT, capture_output=True, text=True).stdout.split()
    for name in tracked:
        (skills / Path(name).name).write_text((g.ROOT / name).read_text())
    g.NOTES, g.SKILLS = tmp / "notes.md", skills


def unload_all() -> None:
    for m in requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", []):
        requests.post(f"{OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def first_call_tokens(agent, with_tools: bool = True) -> int:
    """prompt_tokens of the first model call the agent would make for PROMPT."""
    agent.memory.reset()
    agent.memory.system_prompt = SystemPromptStep(system_prompt=agent.initialize_system_prompt())
    agent.memory.steps.append(TaskStep(task=PROMPT))
    messages = agent.write_memory_to_messages()
    kwargs = agent.model._prepare_completion_kwargs(
        messages, tools_to_call_from=list(agent.tools.values()) if with_tools else None, max_tokens=1)
    kwargs.setdefault("model", agent.model.model_id)
    r = requests.post(f"{OLLAMA}/v1/chat/completions", json=kwargs, timeout=600)
    if not r.ok:
        raise SystemExit(f"Ollama refused the request ({r.status_code}): {r.text[:300]}")
    return r.json()["usage"]["prompt_tokens"]


def loaded_context(model: str) -> int | None:
    for m in requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", []):
        if m["name"] == model:
            return m.get("context_length")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen3.5:9b", "gemma4:e4b"])
    ap.add_argument("--runs", type=int, default=3, help="repeats per figure; they should agree exactly")
    ap.add_argument("--notes-file", help="measure with this notes.md instead of an empty one")
    ap.add_argument("--json", help="write the results here")
    args = ap.parse_args()

    agent_mod.load_env()
    tmp = Path(tempfile.mkdtemp())
    isolate(tmp, Path(args.notes_file).read_text() if args.notes_file else "# notes\n")
    results = {}
    for model in args.models:
        unload_all()
        os.environ["SMOLPAW_SEARCH_PROVIDER"] = "ddgs"
        full_agent = agent_mod.build_agent(model, backend="ollama")
        row = {"tools": [t.name for t in full_agent.tools.values() if t.name != "final_answer"]}
        row["full"] = [first_call_tokens(full_agent) for _ in range(args.runs)]
        row["no_tools"] = [first_call_tokens(full_agent, with_tools=False) for _ in range(args.runs)]
        os.environ["SMOLPAW_SEARCH_PROVIDER"] = "none"
        row["no_web_search"] = [first_call_tokens(agent_mod.build_agent(model, backend="ollama")) for _ in range(args.runs)]
        row["context"] = loaded_context(model)
        results[model] = row
        print(f"{model} (context {row['context']}): whole first call {row['full']}, no tools {row['no_tools']}, "
              f"without web_search {row['no_web_search']}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    unload_all()


if __name__ == "__main__":
    main()
