# Changelog

All notable changes to Smolpaw are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There have been no versioned releases yet; dates are when changes landed.

## [Unreleased]

### Added
- Ollama as a second model backend: `agent.py --backend ollama` (port 11434, default model `qwen3.5:9b`). `build_agent()` takes a `backend` argument; LM Studio stays the default. Tests cover the backend selection ([#13](https://github.com/aurora7795/smolpaw/issues/13)).
- `--backend` for `tests/eval.py` and `tests/prefill_timing.py`. On Ollama they load the model, read its context from `/api/ps` and warn if it differs from `--ctx` ([#13](https://github.com/aurora7795/smolpaw/issues/13)).
- README section comparing Smolpaw with OpenClaw on prompt size, task time and local reading speed, with the limits of what was measured.
- `tests/eval.py`: runs a prompt N times on a model and records pass/fail, steps, time, tokens, tools and answer, with scripted confirmations and its own notes (the real `notes.md` is untouched). Can serve Tidepool itself (`--tidepool`).
- Tidepool variants `hint`, `detail` and `paged` in `tests/fake_api.py` for harder discovery tests.
- `tests/prefill_timing.py`: times prompts of increasing size through LM Studio's API.
- Project rules in `CLAUDE.md` (branching, GitHub issues, changelog, docs upkeep), adapted from the InkTag project, and this changelog. Deferred work is now tracked as GitHub issues, linked from `PLAN.md`.

### Changed
- `tests/eval.py` and `tests/prefill_timing.py` unload models on both LM Studio and Ollama before loading, and on Ollama runs only call `lms` when LM Studio's server is running. `--no-lms` is now `--no-load` (the old name still works). Log filenames include the backend and replace `:` in model ids.

### Fixed
- RESULTS.md and PLAN.md called Ollama's default `qwen3.5:9b` and `gemma4:e4b` tags GGUF; on this Mac they are MLX `nvfp4` builds.

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
