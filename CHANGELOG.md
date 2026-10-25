# Changelog

All notable changes to SmolPaw are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There have been no versioned releases yet; dates are when changes landed.

## [Unreleased]

### Added
- `openapi_search` calls are now logged (spec URL, keyword, hit count or error), matching `http_request` and `run_shell`; `web.py`'s activity feed shows them too. Found as a real gap during rung 3 testing, where a model's "could not find it" claims could not be checked against the log (#30).
- `web.py`: a small rotating "Pawing... (12s)"-style line while a request is running, so the page shows it is still working and how long it has taken (standard library only, ticks client-side off the run's start time, no extra polling).
- `web.py`: a Copy button on the Answer card, using the Clipboard API where the page is a secure context, with a `document.execCommand` fallback for plain-HTTP access over Tailscale.
- Stall detection, the first half of #19 (recovery checks still open: verifying the outcome of a write): a `step_callbacks` hook in `agent.py` stops a run early if the model makes the same tool call with the same arguments three times running and every attempt fails (`ERROR:`/`DECLINED:`, an HTTP 4xx/5xx response, or a smolagents-level parsing/execution error). Reported the same way as the step cap: `STOPPED EARLY: ...` plus the last tool result. No prompt cost (pure bookkeeping over `agent.memory.steps`); a genuine interrupt from the web harness's Stop button is unaffected. Tests cover the matching logic and `run_request`'s handling of both cases.
- `http_request` converts web pages to plain text (title and visible text, `<main>` only when present, no scripts, menus or footers), standard library only. HTML from a service listed in `notes.md` still gets the wrong-path warning. Requests send a `SmolPaw` user agent. Tests cover conversion, the service warning and redaction ([#23](https://github.com/aurora7795/smolpaw/issues/23)).
- `web.py`: a web harness that runs the agent and puts its `[y/N]` prompts and `ask_user` questions on a phone-friendly page, with an access token, key redaction, an optional timeout (unanswered counts as no) and a Stop button. Standard library only. `tests/eval.py --confirm web` uses the same page. Tests cover tokens, stale and non-boolean answers, timeouts, redaction and the harness's decline record.
- Ollama as a second model backend: `agent.py --backend ollama` (port 11434, default model `qwen3.5:9b`). `build_agent()` takes a `backend` argument; LM Studio stays the default. Tests cover the backend selection ([#13](https://github.com/aurora7795/smolpaw/issues/13)).
- `--backend` for `tests/eval.py` and `tests/prefill_timing.py`. On Ollama they load the model, read its context from `/api/ps` and warn if it differs from `--ctx` ([#13](https://github.com/aurora7795/smolpaw/issues/13)).
- README section comparing SmolPaw with OpenClaw on prompt size, task time and local reading speed, with the limits of what was measured.
- `tests/eval.py`: runs a prompt N times on a model and records pass/fail, steps, time, tokens, tools and answer, with scripted confirmations and its own notes (the real `notes.md` is untouched). Can serve Tidepool itself (`--tidepool`).
- Tidepool variants `hint`, `detail` and `paged` in `tests/fake_api.py` for harder discovery tests.
- `tests/prefill_timing.py`: times prompts of increasing size through LM Studio's API.
- Project rules in `CLAUDE.md` (branching, GitHub issues, changelog, docs upkeep), adapted from the InkTag project, and this changelog. Deferred work is now tracked as GitHub issues, linked from `PLAN.md`.

### Changed
- PLAN.md: a Roadmap section (phases 0 to 3 under a prompt budget of about 3.5K tokens, issues #19 to #29) and an up-to-date "Where we are".
- The project is now written SmolPaw everywhere it is named: docs, the startup and web harness lines, the web page title and the agent's own prompt ("You are SmolPaw"). Identifiers stay lowercase: the repository and its URLs, `SMOLPAW_WEB_TOKEN`, file names and folder paths.
- `CLAUDE.md`: finished work is committed, merged into `main` and pushed without asking; read-only measurements, issues and docs need no approval. Writes to real services, stopping the user's apps, large downloads, irreversible actions, new software and confirmation-layer changes still need approval.
- `agent.py`: earlier tool calls and results are sent to the model as native `tool_calls` and `tool` messages (`NativeHistoryModel`) instead of smolagents' `Calling tools: [...]` text, which small models copy instead of making a real call. Only messages smolagents generated are converted; text a model wrote is left alone. `build_agent(native_history=False)` and `tests/eval.py --text-history` keep the old format for comparison, and the eval JSON records which was used. Measured on LM Studio (Gemma, Tidepool `detail`, 6 runs each: 0 parse errors against 2) and on Ollama (both models, all four Tidepool variants, 48 runs: parse errors 19 to 5, passes 19 to 23 of 24); see RESULTS.md and [#14](https://github.com/aurora7795/smolpaw/issues/14).
- README: a comparison with the lighter claw harnesses (they advertise footprint, not prompt size; their prompts are not yet measured), Ollama figures in the OpenClaw table, and the first rung 3 attempt.
- `agent.py`: the per-request logic moved into `run_request()`, shared by the CLI and `web.py`. CLI output is unchanged.
- `tests/eval.py` and `tests/prefill_timing.py` unload models on both LM Studio and Ollama before loading, and on Ollama runs only call `lms` when LM Studio's server is running. `--no-lms` is now `--no-load` (the old name still works). Log filenames include the backend and replace `:` in model ids.

### Fixed
- `tests/eval.py` no longer counts a run that hit the step cap as a pass when its forced last answer happens to match. It also records every harness action and approval prompt per run.
- RESULTS.md and PLAN.md called Ollama's default `qwen3.5:9b` and `gemma4:e4b` tags GGUF; on this Mac they are MLX `nvfp4` builds.
- README, PLAN, RESULTS and CLAUDE.md said Ollama picked a 32K context from available memory. It came from the Ollama app's Context length setting, which overrides `OLLAMA_CONTEXT_LENGTH`; the README now says how to set the context for the app and for a hand-started server.

## 2026-10-24

### Added
- Paw banner shown at startup in an interactive terminal.
- `RESULTS.md` collecting measured results and caveats; `PLAN.md` now tracks status, the test ladder and next steps.
- "Tidepool" (`tests/fake_api.py`), an invented harbour-logbook API for testing whether a model can discover an API it cannot have memorised.
- `openapi_search` tool for finding real endpoints in a service's OpenAPI spec, and a hand-written `api-discovery` skill.
- Generic tools with a Python-side confirmation layer: `run_shell`, `http_request`, `read_file`, `write_file`, `ask_user`, `list_skills`, `read_skill`, `write_skill`. Read-only commands and HTTP GET run freely; everything else asks `[y/N]`.
- `notes.md` service list with per-host API key injection from `.env`; keys are redacted from output and logs. Every run is logged to `logs/`.
- `--tools generic|radarr` flag; the generic toolset is the default and always uses `ToolCallingAgent`.
- Safety tests (`tests/test_generic_tools.py`).

### Changed
- Short skills are inlined into the prompt instead of being read on demand.
- `README.md` rewritten for the generic harness, safety model and layout.
- `openapi_search` explains when a URL is not an OpenAPI spec instead of reporting "0 endpoints".
- When the agent hits the step cap the harness reports it and shows the last tool result instead of a blank or misleading answer.

### Fixed
- `http_request` no longer passes an HTML page back as if it were API data; it warns that the path is probably wrong.
- Log filenames no longer break for model identifiers containing `/`.

## 2026-10-23

### Added
- Hand-written Radarr tools (`search_movie`, `list_add_options`, `add_movie`, `get_queue`) with dry-run by default, id validation and a `[y/N]` confirm before any real add.
- `--model`, `--agent code|tool` and `--max-steps` flags; the step cap can also be set with `MAX_STEPS` in `.env`.
- `.env` loading and `.env.example`.
- A ground-truth `[Radarr says]` line printed after each Radarr-toolset run.

### Changed
- Default step cap raised from 8 to 12 and made configurable.
- Dry-run and success messages from `add_movie` made unmistakable, and the agent is told to report exactly what tools returned.

### Fixed
- The model looping after a dry-run result (the result now says the task is finished).

## 2026-10-23 (initial)

### Added
- Minimal smolagents CLI harness backed by LM Studio.
