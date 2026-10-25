# SmolPaw — Plan and Status

Last updated 2026-10-24. Measured results are in [RESULTS.md](RESULTS.md).

## Goal

Test whether a small local model (Bonsai 8B on LM Studio, 16GB Mac Mini) running in SmolPaw can **work out how to achieve a goal on its own**, the way the OpenClaw setup did with DeepSeek in the cloud. Radarr was one example; the harness must not be Radarr-specific.

## Where we are

- Built and pushed: generic tools with a Python-side confirmation layer, `notes.md` and skills (short skills inlined into the prompt), `openapi_search`, an HTML-response warning, a step-cap fallback that shows the last tool result, run logs, 40+ safety tests, and the Tidepool test API. `agent.py` has `--backend lmstudio|ollama`, `--model`, `--tools generic|radarr`, `--agent` and `--max-steps`.
- Rung 1 (known API, skill) passes 6 of 6 on Gemma 4 E4B and Qwen 3.5 9B. Rung 2 on an invented API (Tidepool) passes 6 of 6. Bonsai 8B cannot do discovery; Nanbeige 3B is unusable under LM Studio.
- OpenClaw baseline (one read-only run): correct in 11s on DeepSeek with about 24K prompt tokens per call, against about 3K for SmolPaw.
- Done and merged: the eval script (`tests/eval.py`), harder Tidepool variants (17 of 18 passed), prefill timing, the error-hint skill experiment (no benefit) and an Ollama backend (`--backend ollama` for the agent, eval and prefill scripts), measured against LM Studio at 16K and 32K; native tool-call history (parse errors cut about four times); GGUF against MLX builds (MLX stays); `http_request` converts web pages to text instead of returning raw HTML; stall detection and write verification (#19, both halves); `openapi_search` logging (#30); and the web harness (`web.py`, plus `agent.py --web` for a terminal session that can also be answered from a browser) for answering prompts remotely (see RESULTS.md).
- Rung 3 (a real supervised Radarr write) tried: 0 of 3 real-movie passes on Qwen (4 runs) and one failed, stopped-early run on Gemma — every attempt safely contained, nothing ever actually added. Both models tend to guess a write's arguments before looking them up and avoid or misuse `openapi_search`. Rung 4 done: 6 of 6 passes across Qwen 3.5 9B and Gemma 4 E4B (19 to 51s), confirming the harness is general and not Radarr-shaped. Rung 5 not yet done.
- Found from a real exploratory-testing session (on Windows): a model asked a user directly for a GitHub token (against an existing instruction not to) and the pasted token went unredacted into the log and the model's own answer. Fixed: `ask_user` answers are now checked for pasted-credential shapes regardless of source, a backstop beyond the pre-registered-secret redaction (#32). Root cause of the model getting stuck in the first place: `run_shell` was broken on Windows (read-only commands execed a nonexistent binary; the confirm path used `cmd.exe`, which does not understand `ls`/`cat` either) — fixed, both paths now route through PowerShell there (#33).
- Caveats: the `api-discovery` skill supplies Radarr's spec URL, so rung 1 shows recipe-following, not discovery; samples are 3 runs per cell.

## Roadmap

Build what costs no prompt first, then cheap tools, then on-demand versions of OpenClaw's prompt-expensive features. Keep the first-call prompt under about 3.5K tokens (about 2.2K to 2.9K today) and measure every addition with `tests/eval.py` before keeping it. The owner keeps a fuller working copy, with progress and the feature-by-feature reasoning, outside the repo; the issues below are shared by both.

| Phase | What it includes | Prompt cost | Done when | Issues |
|---|---|---|---|---|
| 0. Finish the test ladder | Rung 3 (a supervised real write, fixing the skipped movie lookup), rung 4 (done, [#3](https://github.com/aurora7795/smolpaw/issues/3)), rung 5 (write a skill, then reuse it) | None | Rungs 1 and 3 pass 2 of 3 on a local model; rung 5 needs fewer steps than rung 3 | [#1](https://github.com/aurora7795/smolpaw/issues/1), [#3](https://github.com/aurora7795/smolpaw/issues/3), [#4](https://github.com/aurora7795/smolpaw/issues/4) |
| 1. Free features | Recovery checks in Python (done, [#19](https://github.com/aurora7795/smolpaw/issues/19); pre-flight write checks proposed, [#31](https://github.com/aurora7795/smolpaw/issues/31)), harness-run schedules, one chat channel, cheap and strong model routing | None (within about 50 tokens) | Each works end to end and ladder results are no worse | [#20](https://github.com/aurora7795/smolpaw/issues/20), [#21](https://github.com/aurora7795/smolpaw/issues/21), [#22](https://github.com/aurora7795/smolpaw/issues/22) (overlaps [#7](https://github.com/aurora7795/smolpaw/issues/7)) |
| 2. Cheap tools | HTML-to-text in `http_request` (done, about 6 tokens), web search, key user facts in `notes.md` (done, [#25](https://github.com/aurora7795/smolpaw/issues/25), ~25 tokens); `edit_file` only if a task needs it | About 100 to 150 tokens each for the rest | Each measured on a task that needs it, within budget | [#24](https://github.com/aurora7795/smolpaw/issues/24), [#25](https://github.com/aurora7795/smolpaw/issues/25) |
| 3. On-demand versions of the expensive four | A rolling summary of earlier requests, `remember` and `recall` (done, [#27](https://github.com/aurora7795/smolpaw/issues/27)), `fetch_page(url, query)` (done, [#28](https://github.com/aurora7795/smolpaw/issues/28)), prompt-prefix caching measured (done, [#29](https://github.com/aurora7795/smolpaw/issues/29)) | About 100 to 300 tokens in total, not growing per turn | A follow-up across two requests works and the prompt does not grow per turn | [#26](https://github.com/aurora7795/smolpaw/issues/26), [#27](https://github.com/aurora7795/smolpaw/issues/27), [#28](https://github.com/aurora7795/smolpaw/issues/28), [#29](https://github.com/aurora7795/smolpaw/issues/29) |
| Ongoing | The PicoClaw prompt comparison; the remaining Gemma parse errors | None | A measured answer in RESULTS.md | [#18](https://github.com/aurora7795/smolpaw/issues/18), [#14](https://github.com/aurora7795/smolpaw/issues/14) |

Not planned: persona files and full browser automation (all prompt cost, little task value), and sub-agents (one model fits on a 16GB Mac). The expensive four are conversation history, browser automation, persona files and inlined memory: each puts text into every call whether the task needs it or not, so phase 3 makes the useful part of each arrive only when the model asks.

## What OpenClaw had that SmolPaw lacks

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
  5. Measure rung 1 and the Tidepool variants on Ollama (done at 16K: Gemma 13 of 15, Qwen 12 of 15 clean; weaker on `detail`, tracked in #15). On this Mac Ollama's default tags are MLX `nvfp4` builds; explicit `-q4_K_M` tags pull GGUF (checked with `ollama show`). Measured in #16: same passes, MLX faster. A GGUF Nanbeige build (#7) needs the same check.
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
| 4 | An unrelated local task (e.g. summarise a folder of text files) | Is it general, not Radarr-shaped? | Done: 6/6 on Qwen and Gemma (see RESULTS.md) |
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

1. Rung 3, a supervised real Radarr add with the `[y/N]` prompt: [#1](https://github.com/aurora7795/smolpaw/issues/1). Measured via `web.py` (2026-10-25): Qwen 3.5 9B 0 of 3 real-movie passes over 4 runs; Gemma 4 E4B one stopped-early run, also failed. Nothing ever actually added (see RESULTS.md). Recurring pattern on both models: guessing a write's arguments before looking them up, and avoiding or misusing `openapi_search` (Qwen via shell spelunking, Gemma by calling an unrelated external API with a placeholder key). Found along the way: `openapi_search` calls are not logged, unlike `http_request`/`run_shell`, making discovery claims hard to audit: done, [#30](https://github.com/aurora7795/smolpaw/issues/30). Recovery checks (#19, both halves) are done; a cheap pre-flight complement — catching an empty/malformed write before it is sent, not only verifying after — is done in [#31](https://github.com/aurora7795/smolpaw/issues/31) (unmeasured on real models); its rejections are logged so they can be counted: done, [#36](https://github.com/aurora7795/smolpaw/issues/36).
2. Done: harder Tidepool (no root index, a detail-only field, pagination): [#2](https://github.com/aurora7795/smolpaw/issues/2).
3. Done: Rung 4, an unrelated local task: [#3](https://github.com/aurora7795/smolpaw/issues/3). 6 of 6 passed (3/3 Qwen 3.5 9B, 3/3 Gemma 4 E4B, 19 to 51s). Both models stuck cleanly to shell and file tools, avoided phantom API calls, and handled the write confirmation safely (see RESULTS.md). Closed: [#3](https://github.com/aurora7795/smolpaw/issues/3).
4. Rung 5, can a model write a useful skill and reuse it ("discover once, then run cheaply"): [#4](https://github.com/aurora7795/smolpaw/issues/4).
5. Done: a small eval script so runs are comparable and token counts are recorded: [#5](https://github.com/aurora7795/smolpaw/issues/5).
6. Done: prefill time on this Mac, to quantify OpenClaw's overhead locally: [#6](https://github.com/aurora7795/smolpaw/issues/6).
7. More models: a GGUF build of Nanbeige, Bonsai as an execute-only tier: [#7](https://github.com/aurora7795/smolpaw/issues/7). Gemma's loaded context is now confirmed as 16384 by `tests/eval.py`.
8. Teach the api-discovery skill to read error bodies for hints (Gemma failed the `hint` variant once): tried, no benefit, skill unchanged (see RESULTS.md). Closed: [#9](https://github.com/aurora7795/smolpaw/issues/9).
9. Done: Ollama as a second backend, measured at 16K against LM Studio (see "Ollama backend" above): [#13](https://github.com/aurora7795/smolpaw/issues/13).
10. Gemma copies smolagents' tool-call history format (an extra `arguments` wrapper, or the call as text), costing steps and sometimes a run, on both runtimes: [#14](https://github.com/aurora7795/smolpaw/issues/14). Native tool-call history (PR #17) cut parse errors about four times on both models and fixed the history-copying failure itself; a recheck with the actual error text (RESULTS.md) found the rare remaining errors are a different, generic issue (the model skipping a tool call), well under once in ten runs and not costing a run so far. Narrowed, not closed.
11. Done: Tidepool `detail` rechecked at 32K with native history; 11 of 12 on both LM Studio and Ollama, so the gap is gone (see RESULTS.md). Closed: [#15](https://github.com/aurora7795/smolpaw/issues/15).
12. Done: GGUF against MLX builds on Ollama; same pass rates, MLX faster (Gemma prefill about twice as fast), so the default MLX tags stay. Closed: [#16](https://github.com/aurora7795/smolpaw/issues/16).
13. Measure the prompt PicoClaw actually sends, and its results, on the same local models and Tidepool tasks; the lighter claw harnesses advertise footprint, not prompt size: [#18](https://github.com/aurora7795/smolpaw/issues/18).
14. Done: `fetch_page(url, query)` on-demand web page trimming tool ([#28](https://github.com/aurora7795/smolpaw/issues/28)).
15. Done: key user facts in `notes.md` ([#25](https://github.com/aurora7795/smolpaw/issues/25)).
16. Done: `remember` and `recall` on-demand memory tools ([#27](https://github.com/aurora7795/smolpaw/issues/27)).
17. The roadmap phases 1 to 3 (see Roadmap above): [#19](https://github.com/aurora7795/smolpaw/issues/19) to [#29](https://github.com/aurora7795/smolpaw/issues/29).
18. Web UI review (web.py): settings the page cannot change without a restart (backend, model, step limit, timeout): [#37](https://github.com/aurora7795/smolpaw/issues/37); done: a read-only view of `notes.md`, skills and `memory.md` ([#38](https://github.com/aurora7795/smolpaw/issues/38)); done: file and skill tool logging, past runs list and run summaries ([#39](https://github.com/aurora7795/smolpaw/issues/39); per-run token counts deferred as they require `agent.py` changes).

Not planned: pointing OpenClaw itself at a local model. Its prompt (about 24K tokens plus a 20K reserve) would not fit comfortably in the contexts we can run on 16GB, so little would be learned for the risk of editing its config.

## Housekeeping

- The Radarr API key has appeared in this project's chat history and in an OpenClaw session. Regenerate it in Radarr (Settings → General), then update `.env` and OpenClaw's `AGENTS.md`.
- `transmission-query.sh` in OpenClaw's skill has a quoting bug (`$2` is not expanded inside single quotes), so `GET`/`REMOVE`/`ADD` with an argument don't work. Do not copy it as is.
