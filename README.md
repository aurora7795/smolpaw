# Smolpaw

A minimal smolagents-based local agent harness backed by LM Studio.

## Requirements

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) running locally with `ternary-bonsai-8b-mlx` loaded
  - Enable the local server on `http://127.0.0.1:1234`

## Setup

```bash
cd smolpaw
python3 -m venv .venv
source .venv/bin/activate
pip install smolagents openai
```

> **Note:** if `python3 -m venv` fails with an ensurepip error, use:
> `python3 -m venv .venv --without-pip` then bootstrap pip manually.

## Run

```bash
source .venv/bin/activate
python3 agent.py
```

Type a message and press Enter. The agent uses smolagents' `CodeAgent` in
code-action mode — it writes and executes Python to answer your query.

Type `quit` or press `Ctrl-C` to exit.

## Configuration

Edit the top of `agent.py` to change:

| Variable | Default | Notes |
|---|---|---|
| `MODEL_ID` | `ternary-bonsai-8b-mlx` | Must match LM Studio model identifier |
| `BASE_URL` | `http://127.0.0.1:1234/v1` | LM Studio server URL |
| `API_KEY` | `lm-studio` | Any string works |

## Structure

```
smolpaw/
├── agent.py     # Main agent loop
├── README.md    # This file
└── .venv/       # Python virtual environment
```
