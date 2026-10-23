"""
Smolpaw — minimal smolagents CLI harness backed by LM Studio.
"""

import argparse
import os
from pathlib import Path

from smolagents import CodeAgent, OpenAIServerModel, ToolCallingAgent

import radarr_tools
from radarr_tools import RADARR_TOOLS

MODEL_ID = "ternary-bonsai-8b-mlx"
MAX_STEPS = 12
BASE_URL = "http://127.0.0.1:1234/v1"
API_KEY = "lm-studio"

INSTRUCTIONS = (
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


def build_agent(model_id: str = MODEL_ID, agent_type: str = "code", max_steps: int = MAX_STEPS):
    model = OpenAIServerModel(
        model_id=model_id,
        api_base=BASE_URL,
        api_key=API_KEY,
    )
    cls = ToolCallingAgent if agent_type == "tool" else CodeAgent
    kwargs = {} if agent_type == "tool" else {"add_base_tools": False}
    return cls(tools=RADARR_TOOLS, model=model, max_steps=max_steps, instructions=INSTRUCTIONS, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_ID, help="LM Studio model identifier")
    parser.add_argument("--agent", choices=["code", "tool"], default="code",
                        help="code = write Python; tool = JSON tool calls")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="step cap per request (default: MAX_STEPS env var, else 12)")
    args = parser.parse_args()

    load_env()
    max_steps = args.max_steps or int(os.environ.get("MAX_STEPS", MAX_STEPS))
    print(f"Smolpaw [{args.model}, {args.agent}] — type your message, Ctrl-C or 'quit' to exit.\n")
    agent = build_agent(args.model, args.agent, max_steps)

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
            radarr_tools.LAST_ACTION = ""
            response = agent.run(user_input)
            print(f"\nAgent: {response}\n")
            if radarr_tools.LAST_ACTION:
                print(f"[Radarr says] {radarr_tools.LAST_ACTION}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
