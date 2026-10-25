# Exploratory testing on a second machine

A guide for testing SmolPaw on your own machine and sending back what you find. No Radarr (or
any other service) is needed — plain local file tasks exercise the same tools and safety layer.

## Setup

```bash
git clone https://github.com/aurora7795/smolpaw.git
cd smolpaw
./setup.sh                      # creates .venv and installs smolagents
cp notes.example.md notes.md    # leave it empty, or delete the Radarr example line — no services needed
```

You need a local model server with at least one tool-using model loaded — see
[Requirements](README.md#requirements) in the README for LM Studio or Ollama setup. Any of the
models listed there is fine; smaller/faster is a more interesting test than bigger/slower.

Run it:

```bash
.venv/bin/python agent.py --model <your-model-id>          # LM Studio
.venv/bin/python agent.py --backend ollama --model <id>     # Ollama
```

Add `--web` to also print a URL — approval prompts can then be answered either in the terminal
or on that page, whichever you prefer at the time (requests are still typed in the terminal).
Add `--web-host 0.0.0.0` too if you want to reach it from your phone. If you would rather run the
whole thing from a browser, including typing requests, use `web.py --backend ollama --host
0.0.0.0` instead (see the README's [Web harness](README.md#web-harness-answer-prompts-from-your-phone)
section) — pick whichever fits how you are testing.

Every `run_shell` command beyond a few read-only ones (`ls`, `cat`, `grep`, `find`, `wc`, `stat`,
`file`) asks you `[y/N]` before running — read the command before you approve it, the same as you
would for Radarr writes. `run_shell` runs with your own account's permissions: it can touch
anything that account can touch, not just a sandboxed folder, so the confirmation prompt is the
real safety boundary. The agent writes outside `skills/` only inside `workspace/`, without asking
first.

## Things to try

Pick a few — no need to do all of them. Each one exercises something different:

1. **Rename or organize some real files.** "There are some screenshots in `~/Desktop/old` —
   rename them to a consistent `YYYY-MM-DD-description.png` scheme" or "sort the files in
   `~/Downloads` into subfolders by type." A real supervised write, each `mv`/`mkdir` asks first.
   This is the project's "rung 4" test (an unrelated local task, not a scripted demo) — if you try
   it, say so when you send findings back, it is useful on its own.
2. **Ask it to do something it has no tool for** ("email me a summary", "open a GUI app"). Worth
   seeing whether it says so plainly (`ask_user`, or just saying it can't) or invents a fake
   success — that is exactly the kind of failure the harness's `[Harness says]` line exists to
   catch.
3. **A multi-step judgement call.** "Find the largest file under `~/Downloads` and tell me
   whether it looks safe to delete" (read-only: no write tools needed, just `run_shell` plus
   reasoning).
4. **Look something up on a real, public, keyless API** (for example `https://api.open-meteo.com`
   for weather, or `https://api.github.com`). Tests discovery (`openapi_search`, or just probing
   with `http_request`) against something it was not told about in `notes.md`.
5. **Deliberately break the task.** Ask it to rename files in a folder that does not exist, or to
   add two conflicting instructions in one request. How it fails is as informative as whether it
   succeeds.
6. **Teach it something, then reuse it.** After it works out a file-renaming convention once, ask
   it to write that down as a skill (`write_skill`), then give it a second, similar batch of files
   and see whether it reuses the skill and needs fewer steps. This is the project's "rung 5" test
   (discover once, run cheaply) if you want to call it that in your notes.
7. **If you have more than one local model**, run the same prompt on each and note which finishes,
   in how many steps, and how long it took — a real, if informal, model comparison.

## Sending findings back

Every request writes one file to `logs/` (gitignored, already redacted — no keys ever reach the
model or the log). Bundle them into one readable report:

```bash
.venv/bin/python tests/export_findings.py            # writes findings.md
.venv/bin/python tests/export_findings.py --stdout    # or just print it
```

Send `findings.md` back (paste it, attach it, however is easiest) — it has every prompt, every
command/request the agent made, every approval you answered, and its final answer, in one file.
Note which model and backend you used, and anything the report does not capture (what you
expected to happen, what felt off). If something looks like a real bug, a GitHub issue is also
welcome: `gh issue create` or the web UI, no special access needed for a public repo.
