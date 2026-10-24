# Smolpaw — Plan and Status

Last updated 2026-10-24. Measured results are in [RESULTS.md](RESULTS.md).

## Goal

Test whether a small local model (Bonsai 8B on LM Studio, 16GB Mac Mini) running in Smolpaw can **work out how to achieve a goal on its own**, the way the OpenClaw setup did with DeepSeek in the cloud. Radarr was one example; the harness must not be Radarr-specific.

## Where we are

- Built and pushed: generic tools with a Python-side confirmation layer, `notes.md` and skills (short skills inlined into the prompt), `openapi_search`, an HTML-response warning, a step-cap fallback that shows the last tool result, run logs, 40+ safety tests, and the Tidepool test API. `agent.py` has `--model`, `--tools generic|radarr`, `--agent` and `--max-steps`.
- Rung 1 (known API, skill) passes 6 of 6 on Gemma 4 E4B and Qwen 3.5 9B. Rung 2 on an invented API (Tidepool) passes 6 of 6. Bonsai 8B cannot do discovery; Nanbeige 3B is unusable under LM Studio.
- OpenClaw baseline (one read-only run): correct in 11s on DeepSeek with about 24K prompt tokens per call, against about 3K for Smolpaw.
- Not yet done: rungs 3 to 5, the eval script, harder discovery tests, a measured prefill cost for a large prompt on this Mac.
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

## Work items

1. **Generic tools** (done): `http_request`, `run_shell`, file tools, `ask_user`, with the confirmation layer and secret injection.
2. **Notes + skills loader** (done): `notes.md`, `skills/`, tools to list/read/write, prompt wiring.
3. **Eval harness** (not built; runs so far were shell loops): a script that runs a prompt N times on a model and records steps, wall time, parse errors, final answer and the harness-reported outcome, so runs are comparable.
4. **Keep the Radarr tools as a baseline** (done) behind a flag (`--tools radarr|generic`).
5. Commit in small steps; no secrets in git (`.env` stays ignored).

## Test ladder

Run each rung 3 times on Gemma 4 E4B and Qwen 3.5 9B (Bonsai failed discovery; see RESULTS.md). Start each from an empty `skills/` folder unless stated.

| # | Goal given to the agent | What it shows | Status |
|---|---|---|---|
| 1 | "What's in my Radarr queue?" (URL/key only in notes) | Can it use a known API from a note? | Done: 6/6 on Gemma and Qwen after harness fixes |
| 2 | An API it has not seen (PokeAPI, then invented Tidepool) | Can it discover an unfamiliar API? | Done: Tidepool 6/6; PokeAPI only measured memory. Harder variants pending |
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

1. Rung 3: a supervised real Radarr add with the `[y/N]` prompt, a different movie each run, on Gemma first.
2. Harder Tidepool: no root index, a field only on the detail endpoint, pagination. See where discovery breaks.
3. Rung 4 (unrelated local task) and rung 5 (does a written skill help).
4. Build a small eval script so runs are comparable and token counts are recorded.
5. Measure prefill time for a 24K-token prompt on this Mac, to quantify OpenClaw's overhead locally (no OpenClaw config change needed).
6. Test whether a model can write a useful skill itself and a second run benefits ("discover once, then run cheaply").
7. Decide whether Bonsai belongs in an execute-only tier, and whether a GGUF build of Nanbeige is worth one try.

Not planned: pointing OpenClaw itself at a local model. Its prompt (about 24K tokens plus a 20K reserve) would not fit comfortably in the contexts we can run on 16GB, so little would be learned for the risk of editing its config.

## Housekeeping

- The Radarr API key has appeared in this project's chat history and in an OpenClaw session. Regenerate it in Radarr (Settings → General), then update `.env` and OpenClaw's `AGENTS.md`.
- `transmission-query.sh` in OpenClaw's skill has a quoting bug (`$2` is not expanded inside single quotes), so `GET`/`REMOVE`/`ADD` with an argument don't work. Do not copy it as is.
