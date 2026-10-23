"""
Smolpaw — minimal smolagents CLI harness backed by LM Studio.
"""

from smolagents import CodeAgent, OpenAIServerModel

MODEL_ID = "ternary-bonsai-8b-mlx"
BASE_URL = "http://127.0.0.1:1234/v1"
API_KEY = "lm-studio"


def build_agent() -> CodeAgent:
    model = OpenAIServerModel(
        model_id=MODEL_ID,
        api_base=BASE_URL,
        api_key=API_KEY,
    )
    return CodeAgent(tools=[], model=model, add_base_tools=False)


def main() -> None:
    print("Smolpaw — type your message, Ctrl-C or 'quit' to exit.\n")
    agent = build_agent()

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
            response = agent.run(user_input)
            print(f"\nAgent: {response}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
