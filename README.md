# Smolpaw

A lean, local-first agent harness built on [smolagents](https://github.com/huggingface/smolagents) and LM Studio. The aim is OpenClaw-like functionality (an agent that works out how to use services and remembers what it learned) using small local models on a 16GB Mac, with far less prompt overhead.

Status: experimental. See [RESULTS.md](RESULTS.md) for what has been measured, [PLAN.md](PLAN.md) for the plan and decisions, and the [comparison with OpenClaw](#how-it-compares-with-openclaw) below.

## How it works

- `agent.py` runs a `ToolCallingAgent` against a model served by LM Studio (`http://127.0.0.1:1234/v1`).
- The model gets a small set of generic tools ([generic_tools.py](generic_tools.py)): shell, HTTP, files, skills and a way to ask you a question.
- Every safety rule is enforced in Python, not in the prompt, so a model cannot talk its way past it.
- `notes.md` lists the services the agent may use. Short skills in `skills/` are put straight into the prompt; longer ones are listed and read on demand.
- Two toolsets: `--tools generic` (default) and `--tools radarr`, a hand-written Radarr baseline that hands the model the method ([radarr_tools.py](radarr_tools.py)).

## How it compares with OpenClaw

Smolpaw exists to see how much of what OpenClaw does can run on small local models on modest hardware (a 16GB Apple Silicon Mac). The short version: OpenClaw with a strong cloud model is faster and far more capable. Smolpaw's advantage is that it is small enough for local models to use at all. Everything below is from one test machine; sources and caveats are in [RESULTS.md](RESULTS.md).

**What we measured**

| | OpenClaw (DeepSeek v4 flash, cloud) | Smolpaw (Gemma 4 E4B or Qwen 3.5 9B, local) |
|---|---|---|
| First-call prompt | about 24K tokens (system prompt about 68K characters: workspace memory, skills, tool docs) | about 2.2K to 2.9K tokens |
| "What's in my Radarr queue?" | correct, 11s, 3 model turns | correct, 35 to 71s, 3 steps (6 of 6 runs after the harness fixes) |
| An API the model has never seen (invented "Tidepool" API) | not run | 6 of 6, then 17 of 18 on harder variants (404 at the root, details on a second endpoint, pagination) |
| Cost per task | about $0.0013, and the prompt goes to a cloud provider | no per-task cost; model inference stays on the machine |

**What it means for limited hardware**

Reading a prompt is the bottleneck for a local model. Measured on this Mac with a 32K context (no prompt-cache help):

| Prompt size | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| about 2K tokens (Smolpaw's size) | 8s | 3s |
| about 23K tokens (OpenClaw's size) | 114s | 41s |

An OpenClaw-sized prompt would cost roughly 40 to 115 seconds of reading on every call, before the model writes anything, and its task used 3 calls. It also needs about 24K tokens of context plus a reply reserve of its own (20K by its own budget report), which is a poor fit for the 16K to 32K contexts that leave room for the model on 16GB. A 3K-token harness keeps each call to a few seconds and fits in 16K. That is the practical gain: local 4B to 9B models can run these agent tasks at an interactive pace, where the larger harness is expected to be too slow or too memory-hungry.

**What this does not show**

- OpenClaw was **not** run on a local model, so "OpenClaw would not work here" is an estimate from prompt size and measured reading speed, not a test. The cloud run also benefited from provider-side prompt caching (about 60K cached tokens), and a local server that caches a stable prompt prefix could cut reading time a lot; that was not measured.
- OpenClaw does much more: chat channels, long-term memory, many ready-made skills, and recovery behaviour such as checking a download is really moving. Smolpaw has a shell, HTTP, files, notes and skills, and a safety layer, nothing more.
- Smolpaw's results are small samples (3 runs per cell) on a few read-only tasks. Real writes through the generic tools are not yet tested ([#1](https://github.com/aurora7795/smolpaw/issues/1)).
- It also needs help a strong model would not: clear tool error messages, short skills placed in the prompt, and a warning when a server returns a web page instead of data. Some small models (Bonsai 8B, Nanbeige 3B) did not work at all.

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
