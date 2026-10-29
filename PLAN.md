# SmolPaw — Plan and Status

Last updated 2026-10-24. Measured results are in [RESULTS.md](RESULTS.md).

## Goal

Test whether a small local model (Bonsai 8B on LM Studio, 16GB Mac Mini) running in SmolPaw can **work out how to achieve a goal on its own**, the way the OpenClaw setup did with DeepSeek in the cloud. Radarr was one example; the harness must not be Radarr-specific.

## Where we are

- Built and pushed: generic tools with a Python-side confirmation layer, `notes.md` and skills (short skills inlined into the prompt), `openapi_search`, an HTML-response warning, a step-cap fallback that shows the last tool result, run logs, 40+ safety tests, and the Tidepool test API. `agent.py` has `--backend lmstudio|ollama`, `--model`, `--tools generic|radarr`, `--agent` and `--max-steps`.
- Rung 1 (known API, skill) passes 6 of 6 on Gemma 4 E4B and Qwen 3.5 9B. Rung 2 on an invented API (Tidepool) passes 6 of 6. Bonsai 8B cannot do discovery; Nanbeige 3B is unusable under LM Studio.
- OpenClaw baseline (one read-only run): correct in 11s on DeepSeek with about 24K prompt tokens per call, against about 3K for SmolPaw at the time (4.1K to 4.4K now, measured 2026-10-26; see RESULTS.md).
- Done and merged: the eval script (`tests/eval.py`), harder Tidepool variants (17 of 18 passed), prefill timing, the error-hint skill experiment (no benefit) and an Ollama backend (`--backend ollama` for the agent, eval and prefill scripts), measured against LM Studio at 16K and 32K; native tool-call history (parse errors cut about four times); GGUF against MLX builds (MLX stays); `http_request` converts web pages to text instead of returning raw HTML; stall detection and write verification (#19, both halves); `openapi_search` logging (#30); and the web harness (`web.py`, plus `agent.py --web` for a terminal session that can also be answered from a browser) for answering prompts remotely (see RESULTS.md).
- Rung 3 (a real supervised Radarr write) tried: 0 of 3 real-movie passes on Qwen (4 runs) and one failed, stopped-early run on Gemma — every attempt safely contained, nothing ever actually added. Both models tend to guess a write's arguments before looking them up and avoid or misuse `openapi_search`. Rung 4 done: 6 of 6 passes across Qwen 3.5 9B and Gemma 4 E4B (19 to 51s), confirming the harness is general and not Radarr-shaped. Rung 5 done: neither model writes a skill unprompted (0 of 6), but both do when asked (6 of 6, 5 good) and reusing the skill cut steps and tokens by about a third (Qwen) and 15 percent (Gemma), see RESULTS.md.
- Found from a real exploratory-testing session (on Windows): a model asked a user directly for a GitHub token (against an existing instruction not to) and the pasted token went unredacted into the log and the model's own answer. Fixed: `ask_user` answers are now checked for pasted-credential shapes regardless of source, a backstop beyond the pre-registered-secret redaction (#32). Root cause of the model getting stuck in the first place: `run_shell` was broken on Windows (read-only commands execed a nonexistent binary; the confirm path used `cmd.exe`, which does not understand `ls`/`cat` either) — fixed, both paths now route through PowerShell there (#33).
- Caveats: the `api-discovery` skill supplies Radarr's spec URL, so rung 1 shows recipe-following, not discovery; samples are 3 runs per cell.

## Roadmap

Build what costs no prompt first, then cheap tools, then on-demand versions of OpenClaw's prompt-expensive features. The first-call prompt budget is about 5K tokens, raised from 3.5K on 2026-10-26: the build already sends 4.1K to 4.4K (measured with `tests/first_call_tokens.py`; RESULTS.md, "First-call prompt size"), because the tools added since the budget was set cost more in the prompt than their raw schemas suggested (about 1.7 times). 5K leaves room for the unbuilt roadmap items (estimated at 0.3K to 0.7K) and is still about one fifth of OpenClaw's roughly 24K. Rule: measure every addition with `tests/first_call_tokens.py` (the whole call and its difference) and `tests/eval.py` before keeping it, record the figures in RESULTS.md, and revisit this budget rather than drift past it. The early tool-cost estimates in the table below are raw schema counts and understate the in-prompt cost. The owner keeps a fuller working copy, with progress and the feature-by-feature reasoning, outside the repo; the issues below are shared by both.

| Phase | What it includes | Prompt cost | Done when | Issues |
|---|---|---|---|---|
| 0. Finish the test ladder | Rung 3 (a supervised real write, fixing the skipped movie lookup), rung 4 (done, [#3](https://github.com/aurora7795/smolpaw/issues/3)), rung 5 (write a skill, then reuse it) | None | Rungs 1 and 3 pass 2 of 3 on a local model; rung 5 needs fewer steps than rung 3 | [#1](https://github.com/aurora7795/smolpaw/issues/1), [#3](https://github.com/aurora7795/smolpaw/issues/3), [#4](https://github.com/aurora7795/smolpaw/issues/4) |
| 1. Free features | Recovery checks in Python (done, [#19](https://github.com/aurora7795/smolpaw/issues/19); pre-flight write checks proposed, [#31](https://github.com/aurora7795/smolpaw/issues/31)), harness-run schedules, one chat channel, cheap and strong model routing | None (within about 50 tokens) | Each works end to end and ladder results are no worse | [#20](https://github.com/aurora7795/smolpaw/issues/20), [#21](https://github.com/aurora7795/smolpaw/issues/21), [#22](https://github.com/aurora7795/smolpaw/issues/22) (overlaps [#7](https://github.com/aurora7795/smolpaw/issues/7)) |
| 2. Cheap tools | HTML-to-text in `http_request` (done, about 6 tokens), web search (done, [#24](https://github.com/aurora7795/smolpaw/issues/24), ~91 tokens schema), key user facts in `notes.md` (done, [#25](https://github.com/aurora7795/smolpaw/issues/25), ~25 tokens); `edit_file` only if a task needs it | About 100 to 150 tokens each for the rest | Each measured on a task that needs it, within budget | [#24](https://github.com/aurora7795/smolpaw/issues/24), [#25](https://github.com/aurora7795/smolpaw/issues/25) |
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

### Scheduler and daemon (planned, [#20](https://github.com/aurora7795/smolpaw/issues/20))
Heartbeats and scheduled runs need something always running; today `web.py` and `agent.py` each own the agent and stop when closed. Decision (2026-10-26): turn `web.py` into the daemon that owns the agent, the scheduler, the approvals and the run logs, and make the CLI a thin client of its token-protected HTTP API. No separate service or message queue (against the efficiency goal). Zero prompt cost: the schedule lives outside the model's context.

| Piece | Plan |
|---|---|
| Schedule store | `schedules.json` (gitignored): id, prompt, standard 5-field cron expression, `enabled`, `last_run`, `next_run`. A small own parser (no new dependency) with unit tests. |
| Scheduler thread | Wakes every 30s, enqueues due jobs, starts one only when `Session` is idle; never interrupts an interactive run (the agent state in `generic_tools` is module-global, so runs cannot overlap). Missed slots after sleep or restart fire once, not once per slot. Wall-clock limit (default 900s, `SCHEDULE_TIMEOUT`; done, [#53](https://github.com/aurora7795/smolpaw/issues/53)) stops hanging runs; waits up to 120s for in-flight summaries, skips re-running on failed mark_ran (done, [#59](https://github.com/aurora7795/smolpaw/issues/59)). |
| Unattended policy | A scheduled run uses a read-only approvals mode: `confirm()` returns False at once and records the action as deferred; `ask()` returns the existing `NO_ANSWER`. The model sees `DECLINED` through the normal path. A run with deferred writes shows as "needs approval"; approving re-runs the prompt with the user present (no replay of a half-finished tool call). This touches the confirmation flow, so it needs the owner's explicit OK and tests before merge. |
| Model not loaded | The daemon loads the configured model through `lms` or `ollama` when a job fires and none is loaded. It never unloads another model or restarts an app without asking (ask-first list in CLAUDE.md); if loading fails or something else occupies memory, the run is logged as skipped and retried at the next slot. |
| Logs | Ordinary run logs with `schedule: <id>` in the start entry; Recents tags them. `export_findings.py` needs no change. |
| API and UI | `GET/POST /api/schedules` plus run-now and delete, same token; a Schedules section on the Settings page. |
| CLI client | `agent.py --connect URL` talks to the daemon, so a scheduled run that needs approval shows up in whichever client is open. |
| launchd | A LaunchAgent plist example and a README section (`KeepAlive`, `--host 0.0.0.0` for Tailscale, a fixed `SMOLPAW_WEB_TOKEN`). |

Order: schedule store and parser, then scheduler thread with the read-only mode (with tests), then API and Settings UI, then model loading, then the CLI client, then launchd. Check the first-call prompt is unchanged with `tests/eval.py` at the end.

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
| 5 | Rerun #3 after it wrote a skill | Does a written skill reduce steps and errors? | Done (Tidepool `detail`): yes when the skill is asked for, see RESULTS.md |

Record per run: success, steps, time, parse errors, number of confirm prompts, whether the final answer matched the real outcome, peak memory.

## Success criteria

- Rungs 1 and 3: succeeds without help in at least 2 of 3 runs on at least one local model.
- Final answers never claim an outcome the harness line contradicts.
- Rung 5 shows fewer steps or errors than rung 3.
- If one model fails where another succeeds, note whether better notes, skills or tool messages close the gap before blaming the model (this was true for Qwen: clearer tool errors fixed it).

## Out of scope for this tranche

- Deleting data, editing Radarr's database, torrent swap/recovery, direct-source fallbacks (all in OpenClaw's skill; risky or rare).
- Multi-agent setups. (A web UI exists; scheduling is now planned, see "Scheduler and daemon".)
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
4. Done: Rung 5, can a model write a useful skill and reuse it ("discover once, then run cheaply"): [#4](https://github.com/aurora7795/smolpaw/issues/4). Yes when asked; neither model writes one unprompted, tracked in [#48](https://github.com/aurora7795/smolpaw/issues/48).
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
18. Web UI review (web.py): done: a settings card for backend, model, step limit and prompt timeout ([#37](https://github.com/aurora7795/smolpaw/issues/37); loading models, the loaded context and the Radarr toolset are not covered); done: a read-only view of `notes.md`, skills and `memory.md` ([#38](https://github.com/aurora7795/smolpaw/issues/38)); done: file and skill tool logging, past runs list, run summaries with token totals ([#39](https://github.com/aurora7795/smolpaw/issues/39)), and recent-runs polish ([#43](https://github.com/aurora7795/smolpaw/issues/43)).

19. Done: Web search ([#24](https://github.com/aurora7795/smolpaw/issues/24)): a pluggable `web_search` tool, on by default with the `ddgs` package so users get search with no setup (it scrapes DuckDuckGo and may be patchy), SearXNG as an alternative, 3 searches per request cap. Schema measured at 91/92 tokens (Qwen/Gemma, `tests/tool_schema_tokens.py`). Revisit the default-on choice once its cost and reliability are measured: [#44](https://github.com/aurora7795/smolpaw/issues/44).

20. A `list_dir` tool returning exact names, sizes and a count: [#46](https://github.com/aurora7795/smolpaw/issues/46). Done: built and measured (schema about 108 to 110 tokens; 6/6 with the tool against 4/6 without on a 55-entry fixture, small sample, see RESULTS.md). Found in an exploratory run: asked what is in a folder of about 55 entries, Qwen 3.5 9B ran one `ls -la` but its answer missed five entries, got some sizes wrong and over-counted subfolder items by two (it read the link-count column).
21. Model-written one-sentence summaries for recent runs ([#47](https://github.com/aurora7795/smolpaw/issues/47)): done (plumbing). On by default; toggle on the Settings card and SMOLPAW_RUN_SUMMARIES=0 env var to switch off. Generates lazily in a background thread after the answer is shown, stored in `<log stem>.summary.txt` sidecar files in `logs/`, redacted, and displayed as the run title in Recent runs with fallback to prompt title. Measured: about 1.2 s and 20 output tokens per summary on Qwen 3.5 9B and 0.4 s and 15 on Gemma 4 E4B with thinking off and output capped; without the cap Qwen took 100 to 267 s and delayed the next request to 178 s (see RESULTS.md). Turned on by default on the user's say-so.
22. Exploratory run, "how many files in my downloads folder": the shell answer counted entries (folders included) as files, and `exit 0` hid a failed first stage of a pipe: [#49](https://github.com/aurora7795/smolpaw/issues/49). The `pipefail` half is done. `list_dir` already returns the file/folder split, so the counting half is a tool-choice problem (the model ran shell instead); measure with a fixture before adding to the prompt.
23. Web UI layout like the Claude app: Recents in the left panel, click a run to read it (done). Found along the way: the test suite wrote its logs into the real `logs/` folder, fixed in [#50](https://github.com/aurora7795/smolpaw/issues/50).
24. Exploratory run, "what is the time in Madrid right now": web search and page fetches could not give a live time (29s, about 18.7K tokens, no answer) while `TZ=Europe/Madrid date` would have; `date` also asks `[y/N]`: [#51](https://github.com/aurora7795/smolpaw/issues/51).
25. Scheduler and daemon, planned in full above ("Scheduler and daemon"): [#20](https://github.com/aurora7795/smolpaw/issues/20). Scope settled 2026-10-26: cron syntax, read-only scheduled runs with re-run-to-approve, model loading by the daemon, CLI client and launchd in the first slice. Step 1 done (2026-10-26): `schedules.py` cron parser and schedule store with `tests/test_schedules.py`, built by antigravity and reviewed here (checked against a minute-by-minute reference on 3,000 random expressions, no mismatches; fixes: strict numbers, Vixie star rule for `*/n`). Step 2 built on branch `feat/scheduler-thread` (2026-10-26), awaiting review: `scheduler.py` and the read-only mode for scheduled runs, [#52](https://github.com/aurora7795/smolpaw/issues/52), with `tests/test_scheduler.py`. Next: step 3, `/api/schedules`, the Settings UI and approving a deferred run, split into [#80](https://github.com/aurora7795/smolpaw/issues/80), [#81](https://github.com/aurora7795/smolpaw/issues/81) and [#82](https://github.com/aurora7795/smolpaw/issues/82). Scheduler follow-ups, filed 2026-10-26: run time limit (done, [#53](https://github.com/aurora7795/smolpaw/issues/53)), run outcomes (done, [#54](https://github.com/aurora7795/smolpaw/issues/54)), several persistent deferred approvals (done, [#55](https://github.com/aurora7795/smolpaw/issues/55), needed for step 3), notifications ([#56](https://github.com/aurora7795/smolpaw/issues/56)), per-schedule options ([#57](https://github.com/aurora7795/smolpaw/issues/57)), opt-in write allow-list, needs owner sign-off ([#58](https://github.com/aurora7795/smolpaw/issues/58)), edge cases (done, [#59](https://github.com/aurora7795/smolpaw/issues/59)), measuring models on read-only runs ([#60](https://github.com/aurora7795/smolpaw/issues/60)).
26. A `schedule` tool so the model can set up a scheduled run from chat: [#61](https://github.com/aurora7795/smolpaw/issues/61). Found in a web chat: asked to put a file in Downloads in 30 minutes, the model said it cannot schedule actions (true, it has no tool for it) and offered a reminder SmolPaw cannot give. Not built; open points are confirmation, one-off times against cron, scheduled runs being read-only, and the prompt cost against the 5K budget.
27. Final answers that drop or overstate fetched results, and a log that keeps no fetched text: [#62](https://github.com/aurora7795/smolpaw/issues/62). Found in a web chat asking for the top 10 Steam games: after a search and three page fetches the model named two games and claimed it had provided the data. Options (clipped result in the log, the Output card for `fetch_page` and `web_search`, a guidance line) are listed in the issue; none chosen.
28. Email through IMAP/SMTP: [#63](https://github.com/aurora7795/smolpaw/issues/63). A design to settle first (sends always ask, recipient allow-list, drafts before sends, whether reads ask, a fake mail server for tests); unattended sending from scheduled runs depends on the allow-list in [#58](https://github.com/aurora7795/smolpaw/issues/58). Not built. Split into [#64](https://github.com/aurora7795/smolpaw/issues/64) (draft and send tools plus a fake mail server; fake server exists in `tests/fake_mail.py` with `tests/test_fake_mail.py`), [#65](https://github.com/aurora7795/smolpaw/issues/65) (read and search, mail treated as untrusted) and [#66](https://github.com/aurora7795/smolpaw/issues/66) (unattended scheduled sends, needing #58 and #61). Decisions needed first are listed on #63.

29. Done: non-interactive mode, `agent.py -p "request"` with plain and JSON-lines output ([#67](https://github.com/aurora7795/smolpaw/issues/67)). Borrowed from the Pi agent harness (pi.dev). Approvals are declined as in scheduled runs (#52); no auto-approve flag without owner sign-off. Exit codes: 0 finished, 1 exception, 2 step limit, 3 stall stop. No prompt cost. Tests in `tests/test_noninteractive.py`.
30. Evaluate an MCP client with on-demand tool discovery: [#68](https://github.com/aurora7795/smolpaw/issues/68). Also borrowed from Pi. An evaluation first: prompt budget, confirmation of every non-read-only call, untrusted results and small-model reliability decide whether it is built; it may be a cheaper route to email than [#64](https://github.com/aurora7795/smolpaw/issues/64) to [#66](https://github.com/aurora7795/smolpaw/issues/66).
31. Pi's compaction and session-tree ideas are noted on [#26](https://github.com/aurora7795/smolpaw/issues/26) (rolling summary), which now follows the 5K budget. A comparison with Pi (pi.dev) was done from its public docs on 2026-10-26; Pi's own first-call prompt has not been measured (it needs a Node install, so ask first; the same kind of check as [#18](https://github.com/aurora7795/smolpaw/issues/18)).

32. Ideas from comparing with SmallCode (github.com/Doorman11991/smallcode; its benchmark figures are its own, with the method unstated, so treated as claims): an evaluation of two-stage tool routing to shrink the first-call prompt, [#69](https://github.com/aurora7795/smolpaw/issues/69) (evaluated and closed 2026-10-28 without building it: the best case saves 5 to 8s on Qwen and 1.4 to 2.1s on Gemma on a cold start only, and changing the tool block makes the next call re-read the whole prompt, see RESULTS.md, "What a changed tool block or edited history costs to re-read"); reversible approved writes by keeping the previous content, [#70](https://github.com/aurora7795/smolpaw/issues/70) (done 2026-10-28, built by antigravity and reviewed here: saves old content to `.undo/`, 10 copies per path, 1 MB cap, private files, reported in the harness summary and log; tool schemas identical to before, so no prompt cost; review fixed colliding copy names and permissions); a read-before-write guard, [#71](https://github.com/aurora7795/smolpaw/issues/71); an `edit_file` evaluation against whole-file writes, [#72](https://github.com/aurora7795/smolpaw/issues/72). A forgiving tool-call parser is noted on [#14](https://github.com/aurora7795/smolpaw/issues/14). #71 touches the confirmation layer's neighbourhood and needs tests and the owner's sign-off.

33. Ideas from comparing with little-coder (github.com/itayinbarr/little-coder; built on Pi, its benchmark figures are its own and have no per-mechanism ablations, so treated as claims): an evaluation of snipping old tool results between steps, [#73](https://github.com/aurora7795/smolpaw/issues/73) (the most promising: input tokens grow per step, 40K over 5 to 6 calls in logged runs); a thinking-token budget for thinking models, [#74](https://github.com/aurora7795/smolpaw/issues/74); short situational hints added at the end of the conversation, [#75](https://github.com/aurora7795/smolpaw/issues/75); and a user-extendable read-only shell list, [#76](https://github.com/aurora7795/smolpaw/issues/76), which touches the confirmation layer and needs the owner's decision first. Supporting comments are on #26, #67, #71 and #72. For #73 a fake web and search fixture is built (`tests/fake_web.py`, built by antigravity and reviewed here, 2026-10-28) and an evaluation design is posted on the issue; the logged eval runs show old tool output is only 4 to 22% of input, and tool results are already clipped to 4,000 characters, so the clip rule's ceiling is low and a harder clip should be considered before running it. None of the ideas themselves is built.

34. Ideas from comparing with effGen (github.com/ctrl-gaurav/effGen, a broad small-model agent framework; its benchmark figures are self-reported on Qwen2.5 models and other kinds of task, so treated as claims; read from its README and paper, not its docs site): an evaluation of stopping a run that makes no progress beyond identical failing calls, [#77](https://github.com/aurora7795/smolpaw/issues/77); an evaluation of recovering a skipped tool call, [#78](https://github.com/aurora7795/smolpaw/issues/78); and a scripted model capability probe, [#79](https://github.com/aurora7795/smolpaw/issues/79). Supporting comments are on #73, #63, #69, #14 and #7. effGen's own performance against smolagents has not been rerun here (it needs a package install, so ask first; the same kind of check as [#18](https://github.com/aurora7795/smolpaw/issues/18)). None built.
35. Web UI gaps found in a review of what the code does against what the page shows (2026-10-28). The scheduler is invisible in the page: schedules list, add, edit, enable and delete, with status and scheduler errors ([#80](https://github.com/aurora7795/smolpaw/issues/80)); deferred approvals from read-only scheduled runs, shown and dismissable ([#81](https://github.com/aurora7795/smolpaw/issues/81), approve-and-re-run is a separate decision that touches the confirmation flow and needs the owner's OK first); the scheduled-run time limit in Settings ([#82](https://github.com/aurora7795/smolpaw/issues/82)); a web search toggle and provider, after the default is decided in [#44](https://github.com/aurora7795/smolpaw/issues/44) ([#83](https://github.com/aurora7795/smolpaw/issues/83)); model load/unload, loaded context and toolset, scope to settle first ([#84](https://github.com/aurora7795/smolpaw/issues/84)). #80 to #82 are step 3 of the scheduler above and edit `web.py`, so they follow the scheduler edge-case fix (done, [#59](https://github.com/aurora7795/smolpaw/issues/59)) and are built here, not delegated. Notes, skills and memory stay read-only in the page on purpose.
36. Small-model tracking of what was read and written (2026-10-28): a paged `read_file` with `offset` and a footer (built 2026-10-29: models use it, but edit and append passed 1 of 12 with it, see RESULTS.md); `edit_file` ([#72](https://github.com/aurora7795/smolpaw/issues/72), built 2026-10-29: edit and append 10 of 12; open: #71, and why Gemma's reading score dropped) ([#86](https://github.com/aurora7795/smolpaw/issues/86)); an eval for whether 4B to 9B models keep track of long files and edits, the baseline for #71, #72, #73 and #26 (fixture done 2026-10-29, built by antigravity and reviewed here; first measurement 2026-10-29: edit and append 0 of 12 on both models, reading 3 of 6, see RESULTS.md; the eval is the baseline for #71, #72, #73, #86) ([#87](https://github.com/aurora7795/smolpaw/issues/87)).

Not planned: pointing OpenClaw itself at a local model. Its prompt (about 24K tokens plus a 20K reserve) would not fit comfortably in the contexts we can run on 16GB, so little would be learned for the risk of editing its config.

## Housekeeping

- The Radarr API key has appeared in this project's chat history and in an OpenClaw session. Regenerate it in Radarr (Settings → General), then update `.env` and OpenClaw's `AGENTS.md`.
- `transmission-query.sh` in OpenClaw's skill has a quoting bug (`$2` is not expanded inside single quotes), so `GET`/`REMOVE`/`ADD` with an argument don't work. Do not copy it as is.
