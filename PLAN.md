# Smolpaw — Next Tranche Plan

## Goal

Test whether a small local model (Bonsai 8B on LM Studio, 16GB Mac Mini) running in Smolpaw can **work out how to achieve a goal on its own**, the way the OpenClaw setup did with DeepSeek in the cloud. Radarr was one example; the harness must not be Radarr-specific.

## Where we are

- Smolpaw is a smolagents CLI (`agent.py`) with `--model`, `--agent code|tool` and `--max-steps`.
- `radarr_tools.py` holds hand-written Radarr tools: search, list options, add (dry-run default, id validation, `[y/N]` confirm), queue.
- Results with those tools, Bonsai + `ToolCallingAgent`: 2 real adds succeeded, 9 of 9 dry-runs reported correctly after fixes. The code agent was unreliable on Bonsai.
- Caveat: those tools hand the model the method. OpenClaw was not handed it; it had a shell, notes, and a skill it wrote after its own mistakes. The Radarr result is therefore a **baseline**, not proof of the goal.

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

1. **Generic tools**: `http_request`, `run_shell`, file tools, `ask_user`, with the confirmation layer and secret injection.
2. **Notes + skills loader**: `notes.md`, `skills/`, tools to list/read/write, prompt wiring.
3. **Eval harness**: a script that runs a prompt N times on a model and records steps, wall time, parse errors, final answer and the harness-reported outcome, so runs are comparable.
4. **Keep the Radarr tools as a baseline** behind a flag (`--tools radarr|generic`).
5. Commit in small steps; no secrets in git (`.env` stays ignored).

## Test ladder

Run each rung 3 times on Bonsai and on Qwen 3.5 9B, with the `tool` agent. Start each from an empty `skills/` folder unless stated.

| # | Goal given to the agent | What it shows |
|---|---|---|
| 1 | "What's in my Radarr queue?" (URL/key only in notes) | Can it use a known API from a note? |
| 2 | Same for Sonarr or Plex (not used before) | Can it discover an unfamiliar API? |
| 3 | "Add Moon to Radarr" (write, with confirm) | Does it work out add + profile + folder? |
| 4 | An unrelated local task (e.g. summarise a folder of text files) | Is it general, not Radarr-shaped? |
| 5 | Rerun #3 after it wrote a skill | Does a written skill reduce steps and errors? |

Record per run: success, steps, time, parse errors, number of confirm prompts, whether the final answer matched the real outcome, peak memory.

## Success criteria

- Rungs 1 and 3: succeeds without help in at least 2 of 3 runs on Bonsai.
- Final answers never claim an outcome the harness line contradicts.
- Rung 5 shows fewer steps or errors than rung 3.
- If Bonsai fails where Qwen succeeds, note whether better notes or skills close the gap before blaming the model.

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
| Models | Bonsai 8B and Qwen 3.5 9B (one loaded at a time on 16GB). |
| Transmission | Credentials not needed until the later grab-and-verify rung. |

## Housekeeping

- The Radarr API key has appeared in chat history. Regenerate it in Radarr (Settings → General), then update `.env` and OpenClaw's `AGENTS.md`.
- `transmission-query.sh` in OpenClaw's skill has a quoting bug (`$2` is not expanded inside single quotes), so `GET`/`REMOVE`/`ADD` with an argument don't work. Do not copy it as is.
