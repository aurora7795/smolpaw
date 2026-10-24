# Smolpaw

A lean, local-first agent harness built on [smolagents](https://github.com/huggingface/smolagents) and LM Studio. The aim is OpenClaw-like functionality (an agent that works out how to use services and remembers what it learned) using small local models on a 16GB Mac, with far less prompt overhead.

Status: experimental. See [RESULTS.md](RESULTS.md) for what has been measured and [PLAN.md](PLAN.md) for the plan and decisions.

## How it works

- `agent.py` runs a `ToolCallingAgent` against a model served by LM Studio (`http://127.0.0.1:1234/v1`).
- The model gets a small set of generic tools ([generic_tools.py](generic_tools.py)): shell, HTTP, files, skills and a way to ask you a question.
- Every safety rule is enforced in Python, not in the prompt, so a model cannot talk its way past it.
- `notes.md` lists the services the agent may use. Short skills in `skills/` are put straight into the prompt; longer ones are listed and read on demand.
- Two toolsets: `--tools generic` (default) and `--tools radarr`, a hand-written Radarr baseline that hands the model the method ([radarr_tools.py](radarr_tools.py)).

## Requirements

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) with its local server on port 1234, and at least one model that supports tool use. Only one model fits at a time on 16GB.
- Models tried so far: `google/gemma-4-e4b`, `qwen3.5-9b-mlx`, `ternary-bonsai-8b-mlx`. See [RESULTS.md](RESULTS.md).
- For the best behaviour load the model with a context length of at least 16384 and one parallel slot.

## Setup

```bash
./setup.sh                      # creates .venv and installs smolagents
cp .env.example .env            # then fill in RADARR_URL / RADARR_API_KEY if you use Radarr
cp notes.example.md notes.md    # then list the services you want the agent to reach
```

`.env` and `notes.md` are gitignored. Never put keys in `notes.md`; it only names which `.env` variable holds each key.

### notes.md format

```
- name: http://host:port | key_env=ENV_VAR | header=Header-Name
  A one-line description.
```

The harness adds the key from `.env` to requests for those hosts only. The model never sees it, and logs redact it. A service with no key is just `- name: https://host`.

## Run

```bash
source .venv/bin/activate
python3 agent.py --model google/gemma-4-e4b
```

| Flag | Default | Notes |
|---|---|---|
| `--model` | `ternary-bonsai-8b-mlx` | LM Studio model identifier (see `lms ls`) |
| `--tools` | `generic` | `generic` or `radarr` (hand-written baseline) |
| `--agent` | `code` | `radarr` toolset only: `code` writes Python, `tool` makes JSON tool calls |
| `--max-steps` | 12 | Also settable as `MAX_STEPS` in `.env` |

Type a request and press Enter; `quit` or Ctrl-C exits. After each answer the harness prints `[Harness says]`: what was actually changed or declined, so you do not have to trust the model's summary. If the agent hits the step cap, the harness says so and shows the last tool result.

Every run is logged to `logs/` (gitignored, keys redacted).

## Safety model

| Action | Behaviour |
|---|---|
| HTTP GET | Runs freely. |
| Other HTTP methods | Ask `[y/N]` first. |
| Read-only shell commands on `workspace/` or `skills/` (`ls`, `cat`, `head`, `grep`, `find`, `wc`, `stat`, `file`) | Run freely. |
| Any other shell command, pipes, redirects, `find -exec/-delete` | Ask first. |
| Reading outside `workspace/` and `skills/` | Ask first. |
| Writing any file or skill | Ask first, showing the text. |
| `.env` files | Never readable or writable by the file tools. |
| Declined action | The model is told and may try another way. |

An approved shell command runs with your user's permissions, so read the prompt. See [PLAN.md](PLAN.md) for the reasoning.

## Tools

`run_shell`, `http_request`, `openapi_search` (search a service's OpenAPI spec for endpoints), `read_file`, `write_file`, `ask_user`, `list_skills`, `read_skill`, `write_skill`. `http_request` also warns when a response is an HTML page instead of API data, because small models read those as answers.

## Tests

```bash
.venv/bin/python tests/test_generic_tools.py
```

Checks the confirmation layer, path scoping, secret handling and tool messages. A live Radarr check runs if `RADARR_URL` and `RADARR_API_KEY` are set. [tests/fake_api.py](tests/fake_api.py) is "Tidepool", an invented harbour-logbook API for testing whether a model can discover an API it cannot have memorised:

```bash
.venv/bin/python tests/fake_api.py 8765 [easy|hint|detail|paged]
```

Repeatable runs and measurements:

```bash
# run a task N times on a model; confirmations are answered "no"; uses its own notes
.venv/bin/python tests/eval.py --model google/gemma-4-e4b --tidepool hint --n 3
# time prompts of increasing size (prefill) through LM Studio
.venv/bin/python tests/prefill_timing.py --model qwen3.5-9b-mlx --ctx 32768
```

Both unload and load models through `lms`, and write results to `logs/`.

## Layout

```
agent.py              CLI and agent wiring
generic_tools.py      Tools, confirmation layer, secrets, logging, prompt building
radarr_tools.py       Hand-written Radarr tools (baseline)
skills/               Skills the agent follows or writes (api-discovery.md is hand-written)
notes.example.md      Template for notes.md (gitignored)
tests/                Safety tests and the Tidepool test API
workspace/            The agent's working folder (contents gitignored)
logs/                 Run logs (gitignored)
PLAN.md               Goals, decisions, test ladder, next steps (tracked as GitHub issues)
RESULTS.md            Measured results and caveats
CHANGELOG.md          Keep a Changelog history
CLAUDE.md             Project rules: commands, branching, issues, changelog, docs
```
