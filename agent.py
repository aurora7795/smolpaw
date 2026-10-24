"""
Smolpaw — minimal smolagents CLI harness backed by LM Studio or Ollama.
"""

import argparse
import os
import sys
from pathlib import Path

from smolagents import CodeAgent, OpenAIServerModel, ToolCallingAgent
from smolagents.utils import AgentMaxStepsError

import generic_tools
import radarr_tools
from generic_tools import GENERIC_TOOLS
from radarr_tools import RADARR_TOOLS

BANNER = r"""
      .-.     .-.
     ( o )   ( o )
      '-'     '-'        S M O L P A W
  .-.             .-.    a small agent with big paws
 ( o )   .-"-.   ( o )
  '-'   /     \   '-'
       |  \_/  |
        \     /
         '-.-'
"""

MAX_STEPS = 12
# Both serve an OpenAI-compatible API; the key is ignored by either server but must be non-empty.
BACKENDS = {
    "lmstudio": {"url": "http://127.0.0.1:1234/v1", "key": "lm-studio", "model": "ternary-bonsai-8b-mlx"},
    "ollama": {"url": "http://127.0.0.1:11434/v1", "key": "ollama", "model": "qwen3.5:9b"},
}

RADARR_INSTRUCTIONS = (
    "To add a movie: call search_movie, then list_add_options, then add_movie using ids "
    "from those results. Your final answer must report exactly what the tools returned. "
    "If a tool says NOT ADDED or DRY RUN, say the movie was not added. "
    "Never claim success unless add_movie returned 'Added'."
)


def load_env(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a .env file without overriding the real environment."""
    p = Path(__file__).parent / path
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def build_agent(model_id: str | None = None, agent_type: str = "code", max_steps: int = MAX_STEPS,
                toolset: str = "generic", backend: str = "lmstudio"):
    cfg = BACKENDS[backend]
    model = OpenAIServerModel(
        model_id=model_id or cfg["model"],
        api_base=cfg["url"],
        api_key=cfg["key"],
    )
    if toolset == "generic":
        # The generic path is ToolCallingAgent only: Bonsai was far more reliable with JSON tool calls.
        return ToolCallingAgent(tools=GENERIC_TOOLS, model=model, max_steps=max_steps,
                                instructions=generic_tools.build_instructions())
    cls = ToolCallingAgent if agent_type == "tool" else CodeAgent
    kwargs = {} if agent_type == "tool" else {"add_base_tools": False}
    return cls(tools=RADARR_TOOLS, model=model, max_steps=max_steps,
               instructions=RADARR_INSTRUCTIONS, **kwargs)


def run_request(agent, model: str, toolset: str, user_input: str) -> tuple[str, str]:
    """Run one request; return the answer and the harness's own account of what changed."""
    radarr_tools.LAST_ACTION = ""
    generic_tools.ACTIONS.clear()
    generic_tools.LAST_RESULT = ""
    if toolset == "generic":
        print(f"[log] {generic_tools.start_log(model, user_input)}")
    response = agent.run(user_input)
    hit_cap = any(isinstance(getattr(step, "error", None), AgentMaxStepsError)
                  for step in agent.memory.steps)
    if hit_cap and toolset == "generic":
        response = (f"STEP LIMIT REACHED: the agent did not finish. Its answer, if any: "
                    f"{str(response).strip() or '(none)'}\nLast tool result -> "
                    f"{generic_tools.LAST_RESULT or '(no tool results)'}")
    if toolset == "generic":
        generic_tools.log_final(response)
        actions = "\n  ".join(generic_tools.ACTIONS) or "no changes made"
        return str(response), f"[Harness says]\n  {actions}"
    return str(response), f"[Radarr says] {radarr_tools.LAST_ACTION}" if radarr_tools.LAST_ACTION else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=sorted(BACKENDS), default="lmstudio",
                        help="model server: lmstudio (port 1234) or ollama (port 11434)")
    parser.add_argument("--model", default=None,
                        help="model identifier on the chosen backend (default depends on --backend)")
    parser.add_argument("--tools", choices=["generic", "radarr"], default="generic",
                        help="generic = shell/http/files/skills; radarr = hand-written Radarr baseline")
    parser.add_argument("--agent", choices=["code", "tool"], default="code",
                        help="radarr toolset only. code = write Python; tool = JSON tool calls")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="step cap per request (default: MAX_STEPS env var, else 12)")
    args = parser.parse_args()

    load_env()
    args.model = args.model or BACKENDS[args.backend]["model"]
    max_steps = args.max_steps or int(os.environ.get("MAX_STEPS", MAX_STEPS))
    if sys.stdout.isatty():  # keep piped runs and logs clean
        print(BANNER)
    label = args.tools if args.tools == "generic" else f"radarr, {args.agent}"
    print(f"Smolpaw [{args.backend}: {args.model}, {label}] — type your message, Ctrl-C or 'quit' to exit.\n")
    agent = build_agent(args.model, args.agent, max_steps, args.tools, args.backend)

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not user_input or user_input.lower() in {"quit", "exit"}:
            print("Bye.")
            break

        try:
            response, outcome = run_request(agent, args.model, args.tools, user_input)
            print(f"\nAgent: {response}\n")
            if outcome:
                print(f"{outcome}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
