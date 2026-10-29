# SmolPaw

A lean, local-first agent harness built on [smolagents](https://github.com/huggingface/smolagents), with models served locally by LM Studio or Ollama. The aim is OpenClaw-like functionality (an agent that works out how to use services and remembers what it learned) using small local models on a 16GB Mac, with far less prompt overhead.

Status: experimental. See [RESULTS.md](RESULTS.md) for what has been measured, [PLAN.md](PLAN.md) for the plan and decisions, and the [comparison with OpenClaw](#how-it-compares-with-openclaw) below.

## How it works

- `agent.py` runs a `ToolCallingAgent` against a model served by LM Studio (`http://127.0.0.1:1234/v1`, the default) or Ollama (`http://127.0.0.1:11434/v1`, with `--backend ollama`).
- The model gets a small set of general-purpose tools ([generic_tools.py](generic_tools.py)): shell, HTTP, web search, page fetching, files, skills, long-term memory and a way to ask you a question. It works out any service you list in `notes.md` from its API description, so nothing is built in for a particular service.
- Every safety rule is enforced in Python, not in the prompt, so a model cannot talk its way past it.
- `notes.md` lists the services the agent may use. Short skills in `skills/` are put straight into the prompt; longer ones are listed and read on demand.
- `web.py` is a browser front end for the same agent: chat, approvals from a phone, settings and run history. It can also run saved prompts on a cron schedule, read-only (see [Scheduled runs](#scheduled-runs)).
- The generic toolset is the product. A second, hand-written toolset for one service (`--tools radarr`, [radarr_tools.py](radarr_tools.py)) exists only as a baseline for measuring what the generic tools cost against purpose-built ones.

## How it compares with OpenClaw

SmolPaw exists to see how much of what OpenClaw does can run on small local models on modest hardware (a 16GB Apple Silicon Mac). The short version: OpenClaw with a strong cloud model is faster and far more capable. SmolPaw's advantage is that it is small enough for local models to use at all. Everything below is from one test machine; sources and caveats are in [RESULTS.md](RESULTS.md).

**What we measured**

| | OpenClaw (DeepSeek v4 flash, cloud) | SmolPaw (Gemma 4 E4B or Qwen 3.5 9B, local) |
|---|---|---|
| First-call prompt | about 24K tokens (system prompt about 68K characters: workspace memory, skills, tool docs) | about 4.1K to 4.4K tokens today (it was 2.2K to 2.9K in early builds, before more tools were added; [RESULTS.md](RESULTS.md)) |
| A question about a real service ("What's in my Radarr queue?") | correct, 11s, 3 model turns | correct, 35 to 71s on LM Studio and 20 to 43s on Ollama, 3 to 7 steps (12 of 12 runs across both runtimes after the harness fixes) |
| An API the model has never seen (invented "Tidepool" API) | not run | 6 of 6, then 17 of 18 on harder variants on LM Studio (404 at the root, details on a second endpoint, pagination); 25 of 30 clean passes on Ollama, weakest on the details variant |
| Cost per task | about $0.0013, and the prompt goes to a cloud provider | no per-task cost; model inference stays on the machine |

**What it means for limited hardware**

Reading a prompt is the bottleneck for a local model. Measured on this Mac with a 32K context (no prompt-cache help):

| Prompt size | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| about 2K tokens (SmolPaw's size) | 8s | 3s |
| about 23K tokens (OpenClaw's size) | 114s | 41s |

An OpenClaw-sized prompt would cost roughly 40 to 115 seconds of reading on every call, before the model writes anything, and its task used 3 calls. It also needs about 24K tokens of context plus a reply reserve of its own (20K by its own budget report), which is a poor fit for the 16K to 32K contexts that leave room for the model on 16GB. A harness of about 4K tokens takes roughly 7s (Gemma) to 20s (Qwen) to read cold on every call (worked out from the reading speeds in RESULTS.md, not timed at this size), much less with a cached prefix, and fits in 16K. That is the practical gain: local 4B to 9B models can run these agent tasks at an interactive pace, where the larger harness is expected to be too slow or too memory-hungry.

**How it compares with the lighter claw harnesses**

Several projects describe themselves as lightweight OpenClaw alternatives: nanobot (Python, under 4,000 lines), PicoClaw (Go, about 10 to 20 MB of RAM), ZeroClaw and IronClaw (Rust), NullClaw (Zig, a 678 KB binary) and others. Their published claims are about deployment footprint: code size, memory, binary size, startup time or isolation. As far as we found, none of them states a prompt size, tokens per request or the context window it needs.

SmolPaw measures something different. On a local model the harness's own memory hardly matters: the model takes 8 to 10 GB, and a harness of 10 MB or 300 MB is noise next to that. What costs time is the prompt the harness sends on every call, because the model must read all of it before answering, at about 5 seconds per 1K tokens for Qwen 3.5 9B on this Mac. So SmolPaw's goal is a small prompt (4.1K to 4.4K tokens on the first call today, measured), not a small binary.

We have not yet measured the prompt any of these harnesses actually sends, so this is not a claim that SmolPaw's prompt is smaller than theirs. A harness that is light on memory could still send a large prompt, or a small one. Measuring PicoClaw against the same local models and tasks is the next step for this comparison ([#18](https://github.com/aurora7795/smolpaw/issues/18)).

**What this does not show**

- OpenClaw was **not** run on a local model, so "OpenClaw would not work here" is an estimate from prompt size and measured reading speed, not a test. The cloud run also benefited from provider-side prompt caching (about 60K cached tokens), and a local server that caches a stable prompt prefix cuts reading time a lot: measured on SmolPaw's own prompt in RESULTS.md (#29), a whole run took at least 2.4 times shorter than the time just to read its prompts cold on Qwen, on both LM Studio and Ollama.
- OpenClaw does much more: chat channels, long-term memory, many ready-made skills, and recovery behaviour such as checking a download is really moving. SmolPaw has a shell, HTTP, web search, page fetching, files and folder listing, notes, skills, long-term memory, a web page and read-only scheduled runs, and a safety layer, nothing more.
- SmolPaw's results are small samples (3 runs per cell) on a few read-only tasks. Real writes through the generic tools are not yet measured: the first supervised attempt (adding a film to a Radarr server) failed because the model guessed the film's id and the root folder instead of looking them up ([#1](https://github.com/aurora7795/smolpaw/issues/1)).
- It also needs help a strong model would not: clear tool error messages, short skills placed in the prompt, and a warning when a server returns a web page instead of data. Some small models (Bonsai 8B, Nanbeige 3B) did not work at all.

## Requirements

- Python 3.10+
- A local model server with at least one model that supports tool use. Only one model fits at a time on 16GB, so unload the other server's model before switching.
  - [LM Studio](https://lmstudio.ai/) with its local server on port 1234 (default). Load the model with a context length of at least 16384 and one parallel slot.
  - Or [Ollama](https://ollama.com/) on port 11434. See [Using Ollama](#using-ollama) for the context setting.
- Models tried so far: on LM Studio `google/gemma-4-e4b`, `qwen3.5-9b-mlx`, `ternary-bonsai-8b-mlx`; on Ollama `qwen3.5:9b`, `gemma4:e4b`. See [RESULTS.md](RESULTS.md).
- Developed on macOS; tested on Windows too. `run_shell` runs commands through PowerShell there (it knows `ls`/`cat` as its own aliases); some of the read-only allow-list (`head`, `grep`, `find`, `wc`, `stat`, `file`) has no native PowerShell equivalent and will ask for approval rather than run free, same as any other command PowerShell does not recognise.

## Setup

```bash
./setup.sh                      # creates .venv and installs smolagents, openai and ddgs (web search)
cp .env.example .env            # then add an API key for each service you list in notes.md (Radarr variables are only for the baseline toolset)
cp notes.example.md notes.md    # then list the services you want the agent to reach
```

`.env` and `notes.md` are gitignored. Never put keys in `notes.md`; it only names which `.env` variable holds each key.

### notes.md format

`notes.md` is inlined into every model call, so keep it short.

#### User facts
Key preferences that shape answers (time zone, measurement units, ownership), replacing OpenClaw-style persona files. Keep to 2–3 lines:

```markdown
- timezone: Europe/London
- units: metric (Celsius, km)
- owner: Martin
```

#### Services
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
| `-p` | none | Non-interactive mode: run once with this request and exit (no banner, no `You:` loop, no `--web`). Generic tools only. Approvals are declined; `ask_user` returns a no-answer reply. Exit codes: 0 finished, 1 error, 2 step limit, 3 stall stop |
| `--json` | off | With `-p`: stream the run's redacted log entries as JSON lines to stdout as they are written, ending with `final`. Other output (`[log]` line, errors) goes to stderr |
| `--backend` | `lmstudio` | `lmstudio` (port 1234) or `ollama` (port 11434) |
| `--model` | `ternary-bonsai-8b-mlx` on LM Studio, `qwen3.5:9b` on Ollama | Model identifier on the chosen backend (see `lms ls` or `ollama list`) |
| `--tools` | `generic` | `generic`, or `radarr` (a hand-written single-service baseline for comparisons) |
| `--agent` | `code` | `radarr` baseline only: `code` writes Python, `tool` makes JSON tool calls |
| `--max-steps` | 12 | Also settable as `MAX_STEPS` in `.env` |
| `--web` | off | Also print a URL; `[y/N]` and `ask_user` prompts can be answered there instead of the terminal, whichever comes first. The terminal still runs the agent and types requests as normal — this only adds a second way to answer prompts, for example from a phone, without needing `web.py` as a separate process. |
| `--web-host`, `--web-port` | `127.0.0.1`, `web.py`'s default | `--web` only. `0.0.0.0` to reach it from other devices (for example over Tailscale) |

Type a request and press Enter; `quit` or Ctrl-C exits. In non-interactive mode (`-p`), the harness prints the answer and the `[Harness says]` report to stdout and exits. Since nobody is at the keyboard, every `[y/N]` approval is declined and `ask_user` receives a no-answer reply (the same read-only policy as scheduled runs), with declined actions reported in `[Harness says]`. Adding `--json` streams each log entry as JSON lines to stdout as it occurs, ending with the `final` entry, while other diagnostics (such as the `[log]` path line and errors) are routed to stderr.

After each answer the harness prints `[Harness says]`: what was actually changed or declined, so you do not have to trust the model's summary. If the agent hits the step cap, the harness says so and shows the last tool result. It also stops early, the same way, if the model makes the same tool call with the same arguments three times running and each attempt fails (an `ERROR:`/`DECLINED:` result, an HTTP 4xx/5xx response, or a parsing error) — no point letting it keep retrying something that is not going to start working.

`[Harness says]` also checks a write's own result, not just its status code: after a POST, PUT, PATCH or DELETE that returns 2xx, a follow-up GET (free, no approval needed) checks what actually happened — a POST is confirmed against its `Location` header or an `id` in the response; a PUT/PATCH's submitted fields are compared against what a GET now returns; a DELETE is confirmed gone (expecting 404). A mismatch or a resource that is still there after a delete is flagged with a loud `WARNING`, not quietly reported as a plain success. This never reaches the model, so it has no prompt cost — it is purely for the human reading the report.

Every run is logged to `logs/` (gitignored, keys redacted), including each file and skill tool call (`read_file`, `list_dir`, `write_file`, `list_skills`, `read_skill`, `write_skill`), each `openapi_search` and `fetch_page` call (url, query/keyword, hit count) and each write refused by the pre-flight check, each shell command with its exit code and the first 500 characters of its output, so a model's "I couldn't find it" can be checked against what it actually searched for.

### Using Ollama

```bash
ollama pull qwen3.5:9b
python3 agent.py --backend ollama --model qwen3.5:9b
```

Ollama cuts prompts that exceed the loaded context with no error to the client (only a warning in the server log), and its OpenAI-compatible API cannot set the context per request. Set it on the server instead. With the Ollama app, use its Context length setting (Settings): the app passes that to its server and it overrides `OLLAMA_CONTEXT_LENGTH` set with `launchctl`. With a server you start yourself, use `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`. With neither set, Ollama picks a default from available memory. `ollama ps` shows the context a loaded model is using. On Apple Silicon, Ollama's default tags may be MLX builds rather than GGUF; `ollama show <tag>` reports the format and runner.

### Web harness: answer prompts from your phone

`web.py` runs the same agent and puts every `[y/N]` prompt and `ask_user` question on a web page, so you can approve or decline from another device (for example over Tailscale) while a task runs. Enter in the request or answer box sends it (Shift+Enter for a newline). A follow-up continues the same chat: the model sees the last three turns (answers clipped to 600 characters) before your new message, and Recents in the left panel shows the chat as one entry. Click an entry to read the whole chat and its latest activity, send a message to continue it, and use New chat for a fresh one with no earlier context. Typing requests also happens on the page, not the terminal — for a terminal session that can *also* be answered from a browser (not just run from one), use `agent.py --web` instead (see [Run](#run)).

```bash
.venv/bin/python web.py --backend ollama --host 0.0.0.0
# SmolPaw web [ollama: qwen3.5:9b] at http://<this-machine>:8770/?t=<token>
```

Open the printed URL. On a wide screen the page has a sidebar (Chat, Settings, Recents); on a phone it is one column. The chat view reads like other chat clients: your request appears as a bubble with the answer below it, a collapsible **Activity** feed under the answer, and the request box pinned to the bottom of the page (it clears when you send). A card with **Yes / No** (or a reply box) when the agent is waiting on you, the answer with the `[Harness says]` lines (shown only when the run changed, declined or failed something; a run that changed nothing shows just the answer, and the terminal still prints "no changes made"), a **Settings** page (backend, model, step limit, prompt timeout, and run summaries toggle; the model box suggests the ids the backend's server lists, and a change rebuilds the agent between requests, never during one) with a read-only **Files** section below it showing `notes.md`, saved skills and `memory.md` (secret-redacted), an activity feed with a live run summary, a **Recent runs** card listing past runs, each with a title (a model-written summary if enabled, falling back to the first sentence of its prompt up to 80 characters) above its summary (start time, model, seconds, tool calls, and input/output tokens for runs from the terminal agent; clicking one shows its feed lines until the next run starts), and a Stop button. One request runs at a time. While a request is running, the page shows a small rotating "Pawing... (12s)"-style line so you can tell it is still working and how long it has taken. The answer has a Copy button for the agent's answer text. Below it, an **Output** card shows the result of the run's latest shell command or `list_dir` call (secret-redacted, clipped at 4,000 characters), because the model sometimes says a listing is "above" without repeating it in its answer. It lives in memory for the current run only; past runs from Recent runs do not show it.

| Flag | Default | Notes |
|---|---|---|
| `--backend`, `--model`, `--max-steps` | as for `agent.py` | Generic toolset only |
| `--host` | `127.0.0.1` | `0.0.0.0` to reach it from other devices |
| `--port` | 8770 | |
| `--timeout` | 0 (wait forever) | Seconds before an unanswered prompt counts as no. These flags set the starting values; the Settings card changes them without a restart |

The confirmation rules are the same as in the terminal; only where you answer changes. Every request must carry the access token (random per start, or fixed with `SMOLPAW_WEB_TOKEN` in `.env` so a bookmark keeps working). Only a real Yes approves: a wrong token, a stale prompt or a timeout counts as no. Keys are redacted from everything the page shows. Anyone with the URL can approve shell commands as you, so keep it on a private network and do not forward the port to the internet. The server is plain HTTP; over Tailscale the connection is encrypted by the tunnel.

The Recent runs list can optionally show a model-written one-sentence summary (at most 100 characters) for finished runs in place of the prompt title, stored in a sidecar `<log stem>.summary.txt` file in `logs/` (with registered keys and pasted credentials redacted). It is on by default, and can be switched off with the Run summaries toggle on the Settings card or `SMOLPAW_RUN_SUMMARIES=0` in the environment. Summaries generate lazily in a background thread after the answer has been shown and never block the next request (if a new run starts while a summary is in flight, it is skipped or cancelled). This adds one short extra model call per run, made with thinking off and output capped at 80 tokens: about 1.2 seconds and 20 output tokens on Qwen 3.5 9B, 0.4 seconds and 15 on Gemma 4 E4B, with no delay to the next request measurable above run-to-run noise (see [RESULTS.md](RESULTS.md)). Without that cap a thinking model took minutes.

`tests/eval.py --confirm web` sends the eval's prompts to the same page instead of answering no, so write tasks can be measured while you approve them remotely.

## Safety model

| Action | Behaviour |
|---|---|
| HTTP GET | Runs freely (after pre-flight query check). |
| Other HTTP methods | Ask `[y/N]` first (after pre-flight validation). |
| HTTP pre-flight validation | Empty required query parameters (`term=`, `query=`, `q=`) and empty `POST`/`PUT`/`PATCH` bodies (except action triggers) return `ERROR:` before any confirmation prompt or network call. |
| Read-only shell commands on `workspace/` or `skills/` (`ls`, `cat`, `head`, `grep`, `find`, `wc`, `stat`, `file`) | Run freely. |
| Any other shell command, pipes, redirects, `find -exec/-delete` | Ask first. |
| Reading outside `workspace/` and `skills/` | Ask first. |
| Writing any file or skill | Ask first, showing the text. |
| `.env` files | Never readable or writable by the file tools. |
| Web search (`web_search`) | Runs freely (read-only). Search queries leave your machine (to DuckDuckGo, or to your SearXNG instance) and need no approval, so the model could put text from your files into a query; set `SMOLPAW_SEARCH_PROVIDER=none` if that matters to you. Search results are untrusted web text and may contain prompt injections or instructions aimed at the model; the confirmation layer protects against acting on them. |
| An `ask_user` answer that looks like a credential (a GitHub/AWS/OpenAI/Slack token, a JWT, or any other long opaque token) | Redacted before it reaches the model, the log, or anything the model repeats back. |
| Declined action | The model is told and may try another way. |
| Scheduled runs | Read-only: every action that would ask is declined, see [Scheduled runs](#scheduled-runs). |

An approved shell command runs with your user's permissions, so read the prompt, in the terminal or on the web page. See [PLAN.md](PLAN.md) for the reasoning.

The model is told never to ask for a password, token or API key directly — a service's key belongs in `notes.md`/`.env`, where it is injected automatically and the model never sees it. It can still get asked anyway (small models do not always follow instructions), so the credential redaction above is the real backstop, not the instruction.

### Reversible file overwrites (.undo/)

Before an approved overwrite of an existing file (via `write_file` or `write_skill`), SmolPaw saves a copy of the old content to `.undo/` (gitignored in the repository root) as a safety net. Copies are private to your user (folder `0700`, files `0600`). Up to 10 copies (`UNDO_KEEP = 10`) are kept per original path, with older copies pruned automatically. Files exceeding 1 MB (`UNDO_MAX_BYTES = 1_000_000`), non-regular files, or unreadable files are not copied (and the report notes `not saved: too large` or `not saved: could not copy`). Secrets files (like `.env`) are blocked earlier and never copied.

To restore a file by hand, copy the saved file from `.undo/` back to its original location (for example `cp .undo/<filename> <target>`).

This safety net is not a replacement for the `[y/N]` prompt: always review proposed writes before approving them.

## Tools

`run_shell`, `http_request`, `fetch_page` (fetch a web page and return text trimmed to match a query), `web_search` (search the web for up to 5 results with title, URL and snippet), `openapi_search` (search a service's OpenAPI spec for endpoints), `read_file` (up to 4,000 characters per call; a long file ends with a footer giving the `offset` for the next page), `list_dir` (exact names, sizes and entry count of a folder), `write_file`, `ask_user`, `list_skills`, `read_skill`, `write_skill`, `remember` (save a fact to long-term memory with user approval), `recall` (search long-term memory for previously remembered facts). `http_request` turns ordinary web pages into plain text (the title and visible text, only the `<main>` part when a page has one, without scripts, menus or footers), so the model can read them. `fetch_page` trims large web pages to excerpts matching a query with surrounding context, so long pages do not flood memory. `remember` and `recall` provide on-demand memory without inlining stored facts into the prompt: facts stay in `memory.md` until the model asks for them. Pre-flight validation in `http_request` catches empty required query parameters (`term`, `query`, `q`) and empty-body writes before sending. When a service listed in `notes.md` answers with an HTML page, it warns instead, because that means a wrong API path (the service's web interface) and small models read those pages as answers. Requests carry a `SmolPaw` user agent, since some sites refuse requests without one.

### Web search

`web_search(query)` works out of the box with no configuration beyond `./setup.sh`. The default backend uses the `ddgs` package to query DuckDuckGo without requiring an API key or external service. Because `ddgs` is an unofficial scraper, DuckDuckGo searches can be patchy, rate-limited, or encounter timeouts; clear error messages instruct the model not to retry the same failed query. Searches are capped at 3 calls per request to avoid runaway loops; failed searches count towards the cap. An invalid `SMOLPAW_SEARCH_PROVIDER` prints a warning and falls back to `ddgs`.

Search provider selection is controlled by `SMOLPAW_SEARCH_PROVIDER` in `.env`:
- Unset or `ddgs` (default): uses DuckDuckGo via the `ddgs` package.
- `searxng`: queries a SearXNG instance configured by `SMOLPAW_SEARCH_URL` (e.g. `http://localhost:8080`). Note that SearXNG requires `json` listed under `search: formats:` in its `settings.yml`, otherwise its JSON endpoint returns HTTP 403.
- `none`: unregisters `web_search`, removing it from the model's tool schema so it costs 0 prompt tokens.

Search results are untrusted web text and can contain prompt injections or instructions aimed at the model. The confirmation layer (`_approved`, path scoping, `.env` blocking) is what protects against acting on them.

#### Adding a search provider

Providers follow a single minimal shape: a function `(query: str, limit: int) -> list[dict]`, where each dictionary contains string keys `title`, `url`, and `snippet`. Adding a provider requires only writing this fetching function and registering it in `SEARCH_PROVIDERS` in `generic_tools.py`:

```python
SEARCH_PROVIDERS = {
    "ddgs": _search_ddgs,
    "searxng": _search_searxng,
    "my_provider": _search_my_provider,
}
```

`web_search` handles all shared logic: capping to 5 results, formatting, secret redaction, clipping, per-request search limits, error reporting, and logging.

## Schedules and cron syntax

SmolPaw includes a pure-Python cron parser and schedule store ([schedules.py](schedules.py)) for running saved prompts without model or network overhead.

Standard 5-field cron expressions are supported:

```
minute   hour   day-of-month   month   day-of-week
(0-59)   (0-23)    (1-31)     (1-12)     (0-7)
```

- **Wildcard**: `*` matches every value in the field.
- **Numbers and ranges**: `5`, `1-5`, with `a <= b`. Both `0` and `7` in `day-of-week` represent Sunday.
- **Lists and steps**: `1,15,30`, `*/15`, and range steps like `1-5/2` or `9-17/2`.
- **Names**: Case-insensitive 3-letter month names (`jan` through `dec`) and weekday names (`sun` through `sat`).
- **Standard Vixie-cron day rule**: If both `day-of-month` and `day-of-week` are restricted (neither is `*`), a time matches when **either** field matches. If only one is restricted, only that one applies.

### Scheduled runs

`web.py` starts a scheduler thread ([scheduler.py](scheduler.py)) that checks `schedules.json` every 30 seconds. There is no way to add schedules from the UI or API yet, so for now they are added from Python with `schedules.add(prompt, cron)`.

- It starts at most one due schedule per check, the one with the oldest `next_run`, and only when no run is in progress and no prompt is waiting for an answer. It never interrupts a chat; a schedule that cannot start yet simply stays due. If a previous run's summary is in progress, the scheduler waits up to 120 seconds before starting the next schedule so model calls do not overlap. If marking a started run fails, an in-memory record skips that slot on subsequent ticks so the schedule does not re-run immediately.
- A schedule that was missed (the computer was asleep, or the server was stopped) runs once when it is next possible, not once per missed slot. Its next run is computed from the time it started, even if the run fails.
- A scheduled run is an ordinary run (same model, step limit, log file and run summary) in its own thread, so it does not join a chat. Its log's `start` entry carries `schedule: <id>`.
- **Time limit**: A wall-clock limit in seconds stops hanging scheduled runs. Configured via the `SCHEDULE_TIMEOUT` environment variable (default: `900` seconds / 15 minutes; `0` disables the limit). Interactive runs are not limited. When the limit expires, the run is stopped using the same interrupt mechanism as the Stop button, hooks are restored, a `timeout` entry is logged, and `last_status` is marked as `"timeout"`.
- *Interruption limitation*: `agent.interrupt()` is cooperative and takes effect between steps. If a model call or tool hangs and never returns, the thread cannot be killed forcefully; the session remains in `running` status until the worker thread actually terminates, preventing concurrent runs from corrupting the module-global state in `generic_tools`.
- `schedules.json` records `last_status` and `last_error` (class name only) per schedule. Status is one of `running` (in progress), `ok` (finished cleanly), `error` (raised an exception), `stopped` (interrupted by hand), `timeout` (hit the wall-clock time limit), or `needs_approval` (finished with deferred actions).
- A damaged `schedules.json` does not stop the thread; it prints the error once and keeps checking. Schedule prompts are never printed to the console.

**Read-only policy.** Nobody is at the keyboard for a scheduled run, so every action that would ask `[y/N]` is declined at once and `ask_user` gets the "no answer" reply. The model sees the usual `DECLINED` result and the run's final `[Harness says]` lines list what was declined. Actions that run freely in a chat (read-only shell, GET requests, reads inside `workspace/` and `skills/`) work the same. The declined actions are written to the log as a `deferred` entry and kept in `Session.needs_approval` as a list of dicts (`id`, `schedule_id`, `prompt`, `actions`, `t`), oldest first and at most one entry per schedule. They are rebuilt on startup from recent logs and can be dismissed via `Session.dismiss_approval(id)`. Approving them and re-running is not built yet. Interactive runs are unchanged.

## Tests

```bash
.venv/bin/python tests/test_generic_tools.py
.venv/bin/python tests/test_schedules.py
.venv/bin/python tests/test_scheduler.py
.venv/bin/python tests/test_noninteractive.py
.venv/bin/python tests/test_fake_mail.py
.venv/bin/python tests/test_fake_web.py
.venv/bin/python tests/test_tracking_fixture.py
.venv/bin/python tests/test_eval_tracking.py
```

`test_generic_tools.py` checks the confirmation layer, path scoping, secret handling, tool messages and the web page's server. `test_schedules.py` covers the cron parser and schedule store, `test_scheduler.py` the scheduler thread, read-only scheduled runs and deferred approvals, `test_noninteractive.py` non-interactive (`-p`) and JSON-lines modes, exit codes, approvals declining, and error conditions, `test_fake_mail.py` the local in-memory SMTP and IMAP test servers, and `test_fake_web.py` the fake web server and its search endpoint (page sizes, which facts show without a query, determinism across processes, and the real `fetch_page` and `web_search` against it), and `test_tracking_fixture.py` the long-file fixture for the read-and-write tracking eval (`tests/tracking_fixture.py`, #87: facts placed beyond the 4,000-character read clip, byte-exact disk checkers proved by mutation, determinism across processes). `test_eval_tracking.py` checks the eval's `--tracking` mode with a stub agent: the scripted approvals (writes in the run's workspace, a literal `sed -i`, read-only pipelines; nothing else) and pass or fail on the file written. Run it with `tests/eval.py --backend ollama --model <id> --tracking edit_one_section|append_keep_all|read_three_report|all --n 3` (results in RESULTS.md). An optional live check of the Radarr baseline runs if `RADARR_URL` and `RADARR_API_KEY` are set. [tests/fake_api.py](tests/fake_api.py) is "Tidepool", an invented harbour-logbook API for testing whether a model can discover an API it cannot have memorised, [tests/fake_mail.py](tests/fake_mail.py) is an in-memory SMTP/IMAP server for testing mail tools without a real mailbox, and [tests/fake_web.py](tests/fake_web.py) is a fake web server and SearXNG search endpoint for repeatable web-fetching tests:

```bash
.venv/bin/python tests/fake_api.py 8765 [easy|hint|detail|paged]
.venv/bin/python tests/fake_mail.py 8766 8767
.venv/bin/python tests/fake_web.py 8768
```

Repeatable runs and measurements:

```bash
# run a task N times on a model; confirmations are answered "no"; uses its own notes
.venv/bin/python tests/eval.py --model google/gemma-4-e4b --tidepool hint --n 3
.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --tidepool hint --n 3
# the first call's size in tokens: whole, instructions alone, and without web_search
.venv/bin/python tests/first_call_tokens.py --models qwen3.5:9b gemma4:e4b
# time prompts of increasing size (prefill)
.venv/bin/python tests/prefill_timing.py --model qwen3.5-9b-mlx --ctx 32768
```

Both take `--backend lmstudio|ollama` and first unload every model on both servers, since only one fits on 16GB. On LM Studio they load the model through `lms` with `--ctx`. Ollama sets the context on its server, so there they load the model, read the context it got from `/api/ps`, and warn if it differs from `--ctx`. `--no-load` (formerly `--no-lms`, still accepted) uses whatever is loaded. Results go to `logs/`, with the backend in the filename and the JSON.

`tests/export_findings.py` bundles every run log in `logs/` into one readable Markdown report (prompt, every action, the final answer), for sending exploratory testing results from another machine — see [TESTING.md](TESTING.md) for a guide aimed at a second tester with their own setup.

Earlier tool calls and results are sent to the model as native `tool_calls` and `tool` messages, because small models copy smolagents' `Calling tools: [...]` text instead of making a real call ([#14](https://github.com/aurora7795/smolpaw/issues/14)). `tests/eval.py --text-history` (or `build_agent(native_history=False)`) sends smolagents' original text format, so the two can be compared; the eval JSON records which was used. Across 48 Ollama runs (both models, all four Tidepool variants) it cut parse errors from 19 to 5 and raised passes from 19 to 23 of 24; an LM Studio sample on Gemma agrees. A recheck with the actual error text (`tests/eval.py` now records it, not just a count) found the history-copying bug itself is gone; the rare remaining errors are the model skipping a tool call, a different and much rarer issue. Samples are 3 to 14 runs per cell, see [RESULTS.md](RESULTS.md).

## Layout

```
agent.py              CLI and agent wiring
web.py                Web harness: run the agent and answer its prompts from a browser
generic_tools.py      Tools, confirmation layer, secrets, logging, prompt building
schedules.py          Schedule store and cron parser
scheduler.py          Thread that runs due schedules in read-only mode
radarr_tools.py       Hand-written single-service tools (baseline for comparisons)
skills/               Skills the agent follows or writes (api-discovery.md is hand-written)
notes.example.md      Template for notes.md (gitignored)
tests/                Safety tests, Tidepool test API, and fake mail server
workspace/            The agent's working folder (contents gitignored)
logs/                 Run logs (gitignored)
PLAN.md               Goals, decisions, test ladder, next steps (tracked as GitHub issues)
RESULTS.md            Measured results and caveats
CHANGELOG.md          Keep a Changelog history
CLAUDE.md             Project rules: commands, branching, issues, changelog, docs
```
