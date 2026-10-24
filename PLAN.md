# Smolpaw — Plan and Status

Last updated 2026-10-24. Measured results are in [RESULTS.md](RESULTS.md).

## Goal

Test whether a small local model (Bonsai 8B on LM Studio, 16GB Mac Mini) running in Smolpaw can **work out how to achieve a goal on its own**, the way the OpenClaw setup did with DeepSeek in the cloud. Radarr was one example; the harness must not be Radarr-specific.

## Where we are

- Built and pushed: generic tools with a Python-side confirmation layer, `notes.md` and skills (short skills inlined into the prompt), `openapi_search`, an HTML-response warning, a step-cap fallback that shows the last tool result, run logs, 40+ safety tests, and the Tidepool test API. `agent.py` has `--backend lmstudio|ollama`, `--model`, `--tools generic|radarr`, `--agent` and `--max-steps`.
- Rung 1 (known API, skill) passes 6 of 6 on Gemma 4 E4B and Qwen 3.5 9B. Rung 2 on an invented API (Tidepool) passes 6 of 6. Bonsai 8B cannot do discovery; Nanbeige 3B is unusable under LM Studio.
- OpenClaw baseline (one read-only run): correct in 11s on DeepSeek with about 24K prompt tokens per call, against about 3K for Smolpaw.
- Done and merged: the eval script (`tests/eval.py`), harder Tidepool variants (17 of 18 passed), prefill timing, the error-hint skill experiment (no benefit) and an Ollama backend (`--backend ollama` for the agent, eval and prefill scripts), measured at 16K against LM Studio (see RESULTS.md).
- Not yet done: rungs 3 to 5 (they need a person to approve write prompts, now possible remotely with `web.py` or `tests/eval.py --confirm web`), more models, a GGUF arm on Ollama.
- Caveats: the `api-discovery` skill supplies Radarr's spec URL, so rung 1 shows recipe-following, not discovery; samples are 3 runs per cell.

## What OpenClaw had that Smolpaw lacks

1. A shell and HTTP access, so any service is reachable.
2. Always-loaded notes (`AGENTS.md`) listing hosts and where credentials live.
3. A way to record lessons as skills (`radarr-grab-and-verify` was written after failures).
4. Recovery behaviour: verify results, notice stalls, retry. (Likely depends on model strength.)

## Design

### Generic tools
| Tool | Behaviour |
|---|---|
| `run_shell(cmd)` | Read-only commands run freely; anything else asks `[y/N]` first. |
| `http_request(method, url, body)` | GET runs freely; any other method asks `[y/N]`. API keys are injected by the harness from `.env`, never shown to the model. |
| `read_file(path)` / `write_file(path, text)` | Writes outside `skills/` ask `[y/N]`. |
| `ask_user(question)` | Lets the model stop and ask instead of guessing. |

### Notes and skills
- `notes.md`: always in the prompt. Lists services (name, URL, which `.env` variable holds the key). Contains no secrets.
- `skills/*.md`: short markdown files. Tools: `list_skills()`, `read_skill(name)`, `write_skill(name, text)`.
- After finishing a task or hitting an error, the agent may write or update a skill. Skill writes show the text and ask `[y/N]`.

### Safety layer (in the harness, not the model)
- All confirmation lives in Python; the model cannot disable it (the sandbox already blocked its `import os` attempt).
- A final `[Harness says]` line prints the real outcome of every side-effecting call under the model's answer.
- Step cap stays configurable (`--max-steps`, `MAX_STEPS`, default 12).
- `run_shell` is the main risk (it can do anything the user account can). Keep confirm-by-default; no unrestricted mode.

### Ollama backend (done, [#13](https://github.com/aurora7795/smolpaw/issues/13); follow-ups [#15](https://github.com/aurora7795/smolpaw/issues/15), [#16](https://github.com/aurora7795/smolpaw/issues/16))
- Ollama serves an OpenAI-compatible API at `http://127.0.0.1:11434/v1` with tool calling, so `OpenAIServerModel` stays; only the base URL, API key and default model ID change per backend.
- Main risk is context length: over-long prompts are cut silently, and the `/v1` endpoint has no per-request `num_ctx`. The context comes from the server: the Ollama app's Context length setting (32K on this Mac, which overrides `OLLAMA_CONTEXT_LENGTH`), or `OLLAMA_CONTEXT_LENGTH=16384` for a hand-started server (fallback: a Modelfile with `PARAMETER num_ctx`), and `tests/eval.py` reads the loaded context from `/api/ps`. LiteLLM's `ollama_chat/` route is not used: it adds a heavy dependency.
- Steps:
  1. Spike (done, see RESULTS.md): tool calls, `usage.prompt_tokens` and the server-side context setting all work. The default context on this Mac is 32K, not 4K.
  2. `agent.py` (done): a `BACKENDS` dict, a `--backend lmstudio|ollama` flag (default `lmstudio`), a `backend` parameter on `build_agent()`, and a default model per backend. The prompt and the confirmation layer are unchanged.
  3. `tests/eval.py` and `tests/prefill_timing.py` (done): model management per backend (unload with `keep_alive: 0`, a warm-up load, the `/api/ps` context check), `--backend`, and the backend recorded in log names and JSON. Replace `:` in model names in log filenames.
  4. A backend-selection test (done).
  5. Measure rung 1 and the Tidepool variants on Ollama (done at 16K: Gemma 13 of 15, Qwen 12 of 15 clean; weaker on `detail`, tracked in #15). On this Mac Ollama's default tags are MLX `nvfp4` builds, not GGUF. For an MLX vs GGUF comparison, pull an explicit quantisation tag (for example `qwen3.5:9b-q4_K_M`) and confirm with `ollama show` that it is GGUF on the llama.cpp runner. A GGUF Nanbeige build (#7) needs the same check. Tracked in #16.
  6. Update README, CHANGELOG and RESULTS (done).
- Only one model fits on 16GB: unload LM Studio before loading a model in Ollama, and the reverse.

## Work items

1. **Generic tools** (done): `http_request`, `run_shell`, file tools, `ask_user`, with the confirmation layer and secret injection.
2. **Notes + skills loader** (done): `notes.md`, `skills/`, tools to list/read/write, prompt wiring.
3. **Eval harness** (done, `tests/eval.py`): a script that runs a prompt N times on a model and records steps, wall time, parse errors, final answer and the harness-reported outcome, so runs are comparable.
4. **Keep the Radarr tools as a baseline** (done) behind a flag (`--tools radarr|generic`).
5. Commit in small steps; no secrets in git (`.env` stays ignored).

## Test ladder

Run each rung 3 times on Gemma 4 E4B and Qwen 3.5 9B (Bonsai failed discovery; see RESULTS.md). Start each from an empty `skills/` folder unless stated.

| # | Goal given to the agent | What it shows | Status |
|---|---|---|---|
| 1 | "What's in my Radarr queue?" (URL/key only in notes) | Can it use a known API from a note? | Done: 6/6 on Gemma and Qwen after harness fixes |
| 2 | An API it has not seen (PokeAPI, then invented Tidepool) | Can it discover an unfamiliar API? | Done: Tidepool 6/6 and harder variants 17/18; PokeAPI only measured memory |
| 3 | "Add <movie> to Radarr" (write, with confirm) | Does it work out add + profile + folder? | Not run |
| 4 | An unrelated local task (e.g. summarise a folder of text files) | Is it general, not Radarr-shaped? | Not run |
| 5 | Rerun #3 after it wrote a skill | Does a written skill reduce steps and errors? | Not run |

Record per run: success, steps, time, parse errors, number of confirm prompts, whether the final answer matched the real outcome, peak memory.

## Success criteria

- Rungs 1 and 3: succeeds without help in at least 2 of 3 runs on at least one local model.
- Final answers never claim an outcome the harness line contradicts.
- Rung 5 shows fewer steps or errors than rung 3.
- If one model fails where another succeeds, note whether better notes, skills or tool messages close the gap before blaming the model (this was true for Qwen: clearer tool errors fixed it).

## Out of scope for this tranche

- Deleting data, editing Radarr's database, torrent swap/recovery, direct-source fallbacks (all in OpenClaw's skill; risky or rare).
- Multi-agent setups, a UI, scheduling.
- Porting OpenClaw's full `radarr-grab-and-verify` flow (release selection, Transmission checks). Revisit once the generic path works; it is a good later rung.

## Decisions (settled 2026-10-24)

| Area | Decision |
|---|---|
| Shell scope | `run_shell` runs in `workspace/`; paths outside it need `[y/N]`. |
| Auto-allowed | Read-only file commands (`ls`, `cat`, `head`, `grep`, `find`, `wc`, `stat`, `file`) and HTTP GET. Everything else asks `[y/N]`. |
| Read scope | Reads limited to `workspace/` and `skills/`; anything else asks. |
| Secrets | Harness injects keys from `.env`, only for hosts listed in `notes.md`. The model never sees keys; logs redact them. |
| Skill writes | Allowed; show the text and ask `[y/N]` each time. |
| Agent type | `ToolCallingAgent` only for the generic path. |
| On decline | The model is told it was declined and continues (it may try another way or `ask_user`). |
| `notes.md` | Lists only the services each rung needs. |
| Logging | Every run saved to `logs/` (gitignored), keys redacted. |
| Pass bar | 3 runs per rung, pass = 2 of 3. |
| Rung 2 | A public API with no key (nothing of yours at risk). |
| Rung 3 | Real Radarr add, a different movie each run, approved by hand. Remove the extras from Radarr afterwards. |
| Rung 4 | Summarise sample text files in `workspace/` into `workspace/summary.md`. |
| Models | Gemma 4 E4B and Qwen 3.5 9B for discovery rungs (one loaded at a time on 16GB, 16K context, one parallel slot). Bonsai 8B kept as a candidate for cheap guided execution. |
| Transmission | Credentials not needed until the later grab-and-verify rung. |

## Next steps

Tracked as GitHub issues:

1. Rung 3, a supervised real Radarr add with the `[y/N]` prompt, on Gemma first: [#1](https://github.com/aurora7795/smolpaw/issues/1).
2. Done: harder Tidepool (no root index, a detail-only field, pagination): [#2](https://github.com/aurora7795/smolpaw/issues/2).
3. Rung 4, an unrelated local task: [#3](https://github.com/aurora7795/smolpaw/issues/3).
4. Rung 5, can a model write a useful skill and reuse it ("discover once, then run cheaply"): [#4](https://github.com/aurora7795/smolpaw/issues/4).
5. Done: a small eval script so runs are comparable and token counts are recorded: [#5](https://github.com/aurora7795/smolpaw/issues/5).
6. Done: prefill time on this Mac, to quantify OpenClaw's overhead locally: [#6](https://github.com/aurora7795/smolpaw/issues/6).
7. More models: a GGUF build of Nanbeige, Bonsai as an execute-only tier: [#7](https://github.com/aurora7795/smolpaw/issues/7). Gemma's loaded context is now confirmed as 16384 by `tests/eval.py`.
8. Teach the api-discovery skill to read error bodies for hints (Gemma failed the `hint` variant once): tried, no benefit, skill unchanged (see RESULTS.md). Closed: [#9](https://github.com/aurora7795/smolpaw/issues/9).
9. Done: Ollama as a second backend, measured at 16K against LM Studio (see "Ollama backend" above): [#13](https://github.com/aurora7795/smolpaw/issues/13).
10. Gemma copies smolagents' tool-call history format (an extra `arguments` wrapper, or the call as text), costing steps and sometimes a run, on both runtimes: [#14](https://github.com/aurora7795/smolpaw/issues/14).
11. Recheck Tidepool `detail` on Ollama with more runs (2 clean passes of 6 against 6 of 6 on LM Studio): [#15](https://github.com/aurora7795/smolpaw/issues/15).
12. Compare GGUF and MLX builds of the same model on Ollama (the default tags here are MLX): [#16](https://github.com/aurora7795/smolpaw/issues/16).
13. Measure the prompt PicoClaw actually sends, and its results, on the same local models and Tidepool tasks; the lighter claw harnesses advertise footprint, not prompt size: [#18](https://github.com/aurora7795/smolpaw/issues/18).

Not planned: pointing OpenClaw itself at a local model. Its prompt (about 24K tokens plus a 20K reserve) would not fit comfortably in the contexts we can run on 16GB, so little would be learned for the risk of editing its config.

## Housekeeping

- The Radarr API key has appeared in this project's chat history and in an OpenClaw session. Regenerate it in Radarr (Settings → General), then update `.env` and OpenClaw's `AGENTS.md`.
- `transmission-query.sh` in OpenClaw's skill has a quoting bug (`$2` is not expanded inside single quotes), so `GET`/`REMOVE`/`ADD` with an argument don't work. Do not copy it as is.
