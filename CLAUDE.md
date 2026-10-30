# SmolPaw: project rules (CLAUDE.md)

Build, run and workflow rules for this repository. Several rules are adapted from the InkTag project. For what the project is, see [README.md](README.md); for goals and status see [PLAN.md](PLAN.md); for measurements see [RESULTS.md](RESULTS.md).

## 1. Commands

* **Setup**: `./setup.sh` (creates `.venv` and installs smolagents), then `cp .env.example .env` and `cp notes.example.md notes.md`.
* **Run**: `.venv/bin/python agent.py --model <lm-studio-model-id>` (see the README for flags).
* **Tests**: `tests/test_generic_tools.py`, `tests/test_schedules.py`, `tests/test_scheduler.py`, `tests/test_noninteractive.py`, `tests/test_fake_mail.py`, `tests/test_fake_web.py`, `tests/test_tracking_fixture.py` and `tests/test_eval_tracking.py`, each run with `.venv/bin/python` (all must pass before every commit).
* **Web harness**: `.venv/bin/python web.py --backend ollama --host 0.0.0.0` answers `[y/N]` prompts from a browser (see the README).
* **Invented test API**: `.venv/bin/python tests/fake_api.py 8765`.
* **Export findings**: `.venv/bin/python tests/export_findings.py` bundles every run log in `logs/` into one Markdown report (see [TESTING.md](TESTING.md), for exploratory testing on a second machine).
* **LM Studio CLI**: `~/.lmstudio/bin/lms` (`ls`, `ps`, `load`, `unload`). It is not on PATH. Only one model fits at a time on 16GB.
* **Ollama**: `ollama` (`list`, `ps`, `pull`, `stop`), server on port 11434; run the agent with `--backend ollama`. Set the context on the server, not per request: the app's Context length setting (it overrides `OLLAMA_CONTEXT_LENGTH`), or `OLLAMA_CONTEXT_LENGTH` for a hand-started `ollama serve`. Unload LM Studio's model before loading one in Ollama, and the reverse.

## 2. Git workflow

* **Never edit code directly on `main`.** Before changing files, check the branch. On `main`, create a descriptive branch first (`feat/...`, `fix/...`, `docs/...`, `chore/...`). Stay on the current branch only for follow-up work on that branch.
* Commit messages end with the standard Claude co-author line.
* When a piece of work is finished and the tests pass, commit, merge it into `main` with a merge commit (`--no-ff`), push, and delete the merged local branch, without asking. Pull requests are optional; open or update one for work the user may want to review on GitHub.
* Batch questions into one message rather than asking several times.

### Without asking
* Git as above, issues (open, update, close), PLAN.md, CHANGELOG.md and other docs.
* Read-only measurement runs (Tidepool, prefill, reading the Radarr queue), including loading and unloading models and cleaning up afterwards.

### Ask first
* Writes to real services (for example adding or removing movies in Radarr).
* Stopping or restarting the user's apps (Ollama, LM Studio, a running `web.py`).
* Downloads over about 5 GB, or anything that leaves less than about 10 GB of disk free.
* Deleting branches on GitHub, or any other action that cannot be undone.
* Installing new software (for example another agent harness).
* Any change to the confirmation layer (see section 6).
* Never commit `.env`, `notes.md`, `memory.md`, `logs/`, or the contents of `workspace/` (all gitignored). The repository is public: no keys, private addresses or personal data in commits, issues or docs.

## 3. Issue tracking (GitHub CLI)

* Use `gh` to track deferred work. When something is found and deliberately not fixed or built now, create an issue straight away:
  `gh issue create --title "<Brief title>" --body "<Description + affected files>"`
* When working from an existing issue, read it first (`gh issue view <n>`) and reference it in commits: `Fixes #<n>: <description>`.
* Issues are public. Keep them concise and actionable, tag them (`enhancement`, `bug`, `documentation`), and leave out keys, hostnames and private network details.
* When an issue is created or closed, update the next-steps list in [PLAN.md](PLAN.md) to match.

## 4. Changelog

* [CHANGELOG.md](CHANGELOG.md) is mandatory. Every feature, fix, behaviour change or release updates it under `## [Unreleased]`, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) categories: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
* When cutting a release, turn `[Unreleased]` into the new version header (`## [x.y.z] - YYYY-MM-DD`) and leave an empty `[Unreleased]` at the top.

## 5. Documentation upkeep

* When code changes behaviour, update the docs in the same change: [README.md](README.md) for usage, flags, tools and safety rules; [RESULTS.md](RESULTS.md) for any new measurement; [PLAN.md](PLAN.md) for status and next steps.
* No placeholders, dummy text or TODOs in docs. Describe what actually exists. Report numbers as measured, including small sample sizes and caveats, and correct earlier figures if they were wrong.
* A measurement in RESULTS.md is not finished until its script and fixture are committed to the repo (ideally `tests/eval.py` or a sibling using its conventions and JSON log shape). It needs a pass/fail check against real output (the file written, the API actually called), not just the model's final spoken answer, and it must run against an isolated workspace/notes, never the real `workspace/` or `notes.md`. A result nobody else can rerun from the repo doesn't go in RESULTS.md, however plausible the numbers look.

## 5a. Delegated work

* Work handed to antigravity is reviewed here before it lands on `main`, and recorded in [DELEGATION.md](DELEGATION.md). Before starting a review, note the session's context tokens (`get_usage`); when it finishes, add one row with the outcome, defects found, review cost and a verdict, and update the running totals. Do not delegate measurements, the confirmation layer or `agent.py`'s core flow (the filter is in that file).

## 6. Project-specific rules

* The confirmation layer in `generic_tools.py` is a safety boundary. Do not weaken it (auto-allowed actions, path scoping, `.env` blocking, secret redaction) without the user's explicit say-so, and add a test for any change to it.
* Keep the agent's prompt small. Efficiency against OpenClaw is the point of the project; measure before adding to it.
* **Merge gate for prompt and tool changes.** State the pass criterion before the run. Merge when neither Qwen nor Gemma gets worse beyond noise and at least one clearly improves; a model that was already failing does not have to pass. Report the sample size and whether the rule was applied before or after seeing the result.
* Match the surrounding code's style: type hints, short docstrings, comments only where the reason is not obvious.
