# Smolpaw: project rules (CLAUDE.md)

Build, run and workflow rules for this repository. Several rules are adapted from the InkTag project. For what the project is, see [README.md](README.md); for goals and status see [PLAN.md](PLAN.md); for measurements see [RESULTS.md](RESULTS.md).

## 1. Commands

* **Setup**: `./setup.sh` (creates `.venv` and installs smolagents), then `cp .env.example .env` and `cp notes.example.md notes.md`.
* **Run**: `.venv/bin/python agent.py --model <lm-studio-model-id>` (see the README for flags).
* **Tests**: `.venv/bin/python tests/test_generic_tools.py` (must pass before every commit).
* **Invented test API**: `.venv/bin/python tests/fake_api.py 8765`.
* **LM Studio CLI**: `~/.lmstudio/bin/lms` (`ls`, `ps`, `load`, `unload`). It is not on PATH. Only one model fits at a time on 16GB.
* **Ollama**: `ollama` (`list`, `ps`, `pull`, `stop`), server on port 11434; run the agent with `--backend ollama`. Set the context on the server, not per request: the app's Context length setting (it overrides `OLLAMA_CONTEXT_LENGTH`), or `OLLAMA_CONTEXT_LENGTH` for a hand-started `ollama serve`. Unload LM Studio's model before loading one in Ollama, and the reverse.

## 2. Git workflow

* **Never edit code directly on `main`.** Before changing files, check the branch. On `main`, create a descriptive branch first (`feat/...`, `fix/...`, `docs/...`, `chore/...`). Stay on the current branch only for follow-up work on that branch.
* Commit messages end with the standard Claude co-author line.
* Pushing is done when the user says so. Do not merge into `main` or open a pull request unasked.
* Never commit `.env`, `notes.md`, `logs/`, or the contents of `workspace/` (all gitignored). The repository is public: no keys, private addresses or personal data in commits, issues or docs.

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

## 6. Project-specific rules

* The confirmation layer in `generic_tools.py` is a safety boundary. Do not weaken it (auto-allowed actions, path scoping, `.env` blocking, secret redaction) without the user's explicit say-so, and add a test for any change to it.
* Keep the agent's prompt small. Efficiency against OpenClaw is the point of the project; measure before adding to it.
* Match the surrounding code's style: type hints, short docstrings, comments only where the reason is not obvious.
