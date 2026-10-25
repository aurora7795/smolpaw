# SmolPaw

A lean, local-first agent harness built on [smolagents](https://github.com/huggingface/smolagents), with models served locally by LM Studio or Ollama. The aim is OpenClaw-like functionality (an agent that works out how to use services and remembers what it learned) using small local models on a 16GB Mac, with far less prompt overhead.

Status: experimental. See [RESULTS.md](RESULTS.md) for what has been measured, [PLAN.md](PLAN.md) for the plan and decisions, and the [comparison with OpenClaw](#how-it-compares-with-openclaw) below.

## How it works

- `agent.py` runs a `ToolCallingAgent` against a model served by LM Studio (`http://127.0.0.1:1234/v1`, the default) or Ollama (`http://127.0.0.1:11434/v1`, with `--backend ollama`).
- The model gets a small set of generic tools ([generic_tools.py](generic_tools.py)): shell, HTTP, files, skills and a way to ask you a question.
- Every safety rule is enforced in Python, not in the prompt, so a model cannot talk its way past it.
- `notes.md` lists the services the agent may use. Short skills in `skills/` are put straight into the prompt; longer ones are listed and read on demand.
- Two toolsets: `--tools generic` (default) and `--tools radarr`, a hand-written Radarr baseline that hands the model the method ([radarr_tools.py](radarr_tools.py)).

## How it compares with OpenClaw

SmolPaw exists to see how much of what OpenClaw does can run on small local models on modest hardware (a 16GB Apple Silicon Mac). The short version: OpenClaw with a strong cloud model is faster and far more capable. SmolPaw's advantage is that it is small enough for local models to use at all. Everything below is from one test machine; sources and caveats are in [RESULTS.md](RESULTS.md).

**What we measured**

| | OpenClaw (DeepSeek v4 flash, cloud) | SmolPaw (Gemma 4 E4B or Qwen 3.5 9B, local) |
|---|---|---|
| First-call prompt | about 24K tokens (system prompt about 68K characters: workspace memory, skills, tool docs) | about 2.2K to 2.9K tokens |
| "What's in my Radarr queue?" | correct, 11s, 3 model turns | correct, 35 to 71s on LM Studio and 20 to 43s on Ollama, 3 to 7 steps (12 of 12 runs across both runtimes after the harness fixes) |
| An API the model has never seen (invented "Tidepool" API) | not run | 6 of 6, then 17 of 18 on harder variants on LM Studio (404 at the root, details on a second endpoint, pagination); 25 of 30 clean passes on Ollama, weakest on the details variant |
| Cost per task | about $0.0013, and the prompt goes to a cloud provider | no per-task cost; model inference stays on the machine |

**What it means for limited hardware**

Reading a prompt is the bottleneck for a local model. Measured on this Mac with a 32K context (no prompt-cache help):

| Prompt size | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| about 2K tokens (SmolPaw's size) | 8s | 3s |
| about 23K tokens (OpenClaw's size) | 114s | 41s |

An OpenClaw-sized prompt would cost roughly 40 to 115 seconds of reading on every call, before the model writes anything, and its task used 3 calls. It also needs about 24K tokens of context plus a reply reserve of its own (20K by its own budget report), which is a poor fit for the 16K to 32K contexts that leave room for the model on 16GB. A 3K-token harness keeps each call to a few seconds and fits in 16K. That is the practical gain: local 4B to 9B models can run these agent tasks at an interactive pace, where the larger harness is expected to be too slow or too memory-hungry.

**How it compares with the lighter claw harnesses**

Several projects describe themselves as lightweight OpenClaw alternatives: nanobot (Python, under 4,000 lines), PicoClaw (Go, about 10 to 20 MB of RAM), ZeroClaw and IronClaw (Rust), NullClaw (Zig, a 678 KB binary) and others. Their published claims are about deployment footprint: code size, memory, binary size, startup time or isolation. As far as we found, none of them states a prompt size, tokens per request or the context window it needs.

SmolPaw measures something different. On a local model the harness's own memory hardly matters: the model takes 8 to 10 GB, and a harness of 10 MB or 300 MB is noise next to that. What costs time is the prompt the harness sends on every call, because the model must read all of it before answering, at about 5 seconds per 1K tokens for Qwen 3.5 9B on this Mac. So SmolPaw's goal is a small prompt (about 2.2K to 2.9K tokens on the first call), not a small binary.

We have not yet measured the prompt any of these harnesses actually sends, so this is not a claim that SmolPaw's prompt is smaller than theirs. A harness that is light on memory could still send a large prompt, or a small one. Measuring PicoClaw against the same local models and tasks is the next step for this comparison ([#18](https://github.com/aurora7795/smolpaw/issues/18)).

**What this does not show**

- OpenClaw was **not** run on a local model, so "OpenClaw would not work here" is an estimate from prompt size and measured reading speed, not a test. The cloud run also benefited from provider-side prompt caching (about 60K cached tokens), and a local server that caches a stable prompt prefix could cut reading time a lot; that was not measured.
- OpenClaw does much more: chat channels, long-term memory, many ready-made skills, and recovery behaviour such as checking a download is really moving. SmolPaw has a shell, HTTP, files, notes and skills, and a safety layer, nothing more.
- SmolPaw's results are small samples (3 runs per cell) on a few read-only tasks. Real writes through the generic tools are not yet measured: the first supervised attempt (adding a film to Radarr) failed because the model guessed the film's id and the root folder instead of looking them up ([#1](https://github.com/aurora7795/smolpaw/issues/1)).
- It also needs help a strong model would not: clear tool error messages, short skills placed in the prompt, and a warning when a server returns a web page instead of data. Some small models (Bonsai 8B, Nanbeige 3B) did not work at all.

## Requirements

- Python 3.10+
- A local model server with at least one model that supports tool use. Only one model fits at a time on 16GB, so unload the other server's model before switching.
  - [LM Studio](https://lmstudio.ai/) with its local server on port 1234 (default). Load the model with a context length of at least 16384 and one parallel slot.
  - Or [Ollama](https://ollama.com/) on port 11434. See [Using Ollama](#using-ollama) for the context setting.
- Models tried so far: on LM Studio `google/gemma-4-e4b`, `qwen3.5-9b-mlx`, `ternary-bonsai-8b-mlx`; on Ollama `qwen3.5:9b`, `gemma4:e4b`. See [RESULTS.md](RESULTS.md).

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
| `--backend` | `lmstudio` | `lmstudio` (port 1234) or `ollama` (port 11434) |
| `--model` | `ternary-bonsai-8b-mlx` on LM Studio, `qwen3.5:9b` on Ollama | Model identifier on the chosen backend (see `lms ls` or `ollama list`) |
| `--tools` | `generic` | `generic` or `radarr` (hand-written baseline) |
| `--agent` | `code` | `radarr` toolset only: `code` writes Python, `tool` makes JSON tool calls |
| `--max-steps` | 12 | Also settable as `MAX_STEPS` in `.env` |

Type a request and press Enter; `quit` or Ctrl-C exits. After each answer the harness prints `[Harness says]`: what was actually changed or declined, so you do not have to trust the model's summary. If the agent hits the step cap, the harness says so and shows the last tool result. It also stops early, the same way, if the model makes the same tool call with the same arguments three times running and each attempt fails (an `ERROR:`/`DECLINED:` result, an HTTP 4xx/5xx response, or a parsing error) — no point letting it keep retrying something that is not going to start working.

Every run is logged to `logs/` (gitignored, keys redacted).

### Using Ollama

```bash
ollama pull qwen3.5:9b
python3 agent.py --backend ollama --model qwen3.5:9b
```

Ollama cuts prompts that exceed the loaded context with no error to the client (only a warning in the server log), and its OpenAI-compatible API cannot set the context per request. Set it on the server instead. With the Ollama app, use its Context length setting (Settings): the app passes that to its server and it overrides `OLLAMA_CONTEXT_LENGTH` set with `launchctl`. With a server you start yourself, use `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`. With neither set, Ollama picks a default from available memory. `ollama ps` shows the context a loaded model is using. On Apple Silicon, Ollama's default tags may be MLX builds rather than GGUF; `ollama show <tag>` reports the format and runner.

### Web harness: answer prompts from your phone

`web.py` runs the same agent and puts every `[y/N]` prompt and `ask_user` question on a web page, so you can approve or decline from another device (for example over Tailscale) while a task runs.

```bash
.venv/bin/python web.py --backend ollama --host 0.0.0.0
# SmolPaw web [ollama: qwen3.5:9b] at http://<this-machine>:8770/?t=<token>
```

Open the printed URL. The page has a box for requests, a card with **Yes / No** (or a reply box) when the agent is waiting on you, the answer with the `[Harness says]` lines, a short activity feed from the run log, and a Stop button. One request runs at a time.

| Flag | Default | Notes |
|---|---|---|
| `--backend`, `--model`, `--max-steps` | as for `agent.py` | Generic toolset only |
| `--host` | `127.0.0.1` | `0.0.0.0` to reach it from other devices |
| `--port` | 8770 | |
| `--timeout` | 0 (wait forever) | Seconds before an unanswered prompt counts as no |

The confirmation rules are the same as in the terminal; only where you answer changes. Every request must carry the access token (random per start, or fixed with `SMOLPAW_WEB_TOKEN` in `.env` so a bookmark keeps working). Only a real Yes approves: a wrong token, a stale prompt or a timeout counts as no. Keys are redacted from everything the page shows. Anyone with the URL can approve shell commands as you, so keep it on a private network and do not forward the port to the internet. The server is plain HTTP; over Tailscale the connection is encrypted by the tunnel.

`tests/eval.py --confirm web` sends the eval's prompts to the same page instead of answering no, so write tasks can be measured while you approve them remotely.

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

An approved shell command runs with your user's permissions, so read the prompt, in the terminal or on the web page. See [PLAN.md](PLAN.md) for the reasoning.

## Tools

`run_shell`, `http_request`, `openapi_search` (search a service's OpenAPI spec for endpoints), `read_file`, `write_file`, `ask_user`, `list_skills`, `read_skill`, `write_skill`. `http_request` turns ordinary web pages into plain text (the title and visible text, only the `<main>` part when a page has one, without scripts, menus or footers), so the model can read them. When a service listed in `notes.md` answers with an HTML page, it warns instead, because that means a wrong API path (the service's web interface) and small models read those pages as answers. Requests carry a `SmolPaw` user agent, since some sites refuse requests without one.

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
.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --tidepool hint --n 3
# time prompts of increasing size (prefill)
.venv/bin/python tests/prefill_timing.py --model qwen3.5-9b-mlx --ctx 32768
```

Both take `--backend lmstudio|ollama` and first unload every model on both servers, since only one fits on 16GB. On LM Studio they load the model through `lms` with `--ctx`. Ollama sets the context on its server, so there they load the model, read the context it got from `/api/ps`, and warn if it differs from `--ctx`. `--no-load` (formerly `--no-lms`, still accepted) uses whatever is loaded. Results go to `logs/`, with the backend in the filename and the JSON.

Earlier tool calls and results are sent to the model as native `tool_calls` and `tool` messages, because small models copy smolagents' `Calling tools: [...]` text instead of making a real call ([#14](https://github.com/aurora7795/smolpaw/issues/14)). `tests/eval.py --text-history` (or `build_agent(native_history=False)`) sends smolagents' original text format, so the two can be compared; the eval JSON records which was used. Across 48 Ollama runs (both models, all four Tidepool variants) it cut parse errors from 19 to 5 and raised passes from 19 to 23 of 24; an LM Studio sample on Gemma agrees. Samples are 3 to 6 runs per cell, see [RESULTS.md](RESULTS.md).

## Layout

```
agent.py              CLI and agent wiring
web.py                Web harness: run the agent and answer its prompts from a browser
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
