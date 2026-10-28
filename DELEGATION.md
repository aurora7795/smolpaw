# Delegation log

Work handed to a second AI coding tool (antigravity) and reviewed here before it lands on `main`. The point of this file is to answer one question with data: does delegating save effort overall, once the review is paid for? Update it at the end of every review.

## How to record a row

One row per delegated issue, added when the review finishes (accepted, fixed, or rejected).

| Column | Meaning |
|---|---|
| Issue | The GitHub issue. |
| Kind | What sort of task it was (new tool, bug fix, test or fixture, docs, measurement). |
| Review outcome | `clean` (merged as delivered), `scoped fix` (small changes on a branch), `rework` (large parts redone), `rejected` (discarded, built again from scratch). |
| Defects found | Short list of what the review caught, or `none`. Say whether each was a correctness bug, a missing test, a wrong number, a missed requirement or a safety gap. |
| Review cost | Context tokens added to the reviewing session, from the context figure before the review and after it (the session's context window as the app reports it). Write `unmeasured` when there is no figure. Do not estimate. |
| Fix commits | The commits that carry the review fixes, or `none`. |
| Verdict | Was it cheaper than building it directly? `yes`, `no` or `unclear`, with one line of why. |

Rules:
- Record failures and rejections as carefully as successes. A log of only wins answers nothing.
- The verdict is a judgment, so give the reason next to it.
- Review cost is a proxy: it counts reading the diff, running the tests and verifying claims, but not the original generation on antigravity's side, which is not visible here. Compare it with the size of the diff, not with zero.
- Public repository: no keys, private addresses or personal data in this file.

## Which tasks to delegate

The filter used so far. Safe: mechanical, self-contained, testable tasks with a clear input and output contract (a new tool, a convention, a narrow heuristic fix, a fixture). Not safe: measurements and judgment calls, the confirmation layer in `generic_tools.py`, the core history and request flow in `agent.py`, architecture decisions, and anything that needs a credential path.

## Log

| Issue | Kind | Review outcome | Defects found | Review cost | Fix commits | Verdict |
|---|---|---|---|---|---|---|
| [#3](https://github.com/aurora7795/smolpaw/issues/3) | measurement (rung 4) | rejected | No script, no fixture, no real pass criterion; `"passed": true` with nothing checkable. Missed requirement and unauditable result. | unmeasured | none (rebuilt) | no: review was paid and the work still had to be redone. This is why CLAUDE.md section 5 requires a committed script and fixture. |
| [#25](https://github.com/aurora7795/smolpaw/issues/25) | notes.md facts | scoped fix | Token estimate was an unmeasured guess (it landed close). | unmeasured | not recorded | yes |
| [#27](https://github.com/aurora7795/smolpaw/issues/27) | new tools (`remember`, `recall`) | scoped fix | The "token budget" test measured a hand-built schema, hiding a real overrun (179 to 182 real tokens against the roughly 147 claimed and the 100 to 150 budget). Wrong number. | unmeasured | not recorded | yes: the budget check caught a real problem |
| [#28](https://github.com/aurora7795/smolpaw/issues/28) | new tool (`fetch_page`) | scoped fix | Dropped the wrong-API-path HTML warning that `http_request` has. Missed requirement. | unmeasured | not recorded | yes |
| [#53](https://github.com/aurora7795/smolpaw/issues/53) | scheduler feature (wall-clock limit) | scoped fix | Robustness gap: `SCHEDULE_TIMEOUT=inf` made the timer thread raise `OverflowError` (no limit, no message); negative and `nan` silently disabled the limit. No correctness bug in the stop path; all five suites passed, scheduler suite stable over 6 runs. | 7,694 tokens (109,550 to 117,244), partial: the baseline was read after the diff had already been loaded, so this undercounts. The figure covers the tests, the edge-case probes, the fix and the merge. | 9ab1b16 | yes: close to mergeable as delivered; one small fix and a test. |
| [#70](https://github.com/aurora7795/smolpaw/issues/70) | safety-adjacent feature (undo copies for approved writes) | scoped fix | (1) Correctness: copy names truncated at 150 characters or stripped of `..` let different files share copies and retention, so saving one deleted another's backups. (2) Safety gap: copies were `0644` in a `0755` folder even for `0600` originals. (3) Test quality: tests 2 to 4 failed on `main` only through `hasattr` guards, test 9 patched the save function instead of making it fail, test 7 never wrote a path with `..`. Held up: the approval logic untouched, tool schemas identical to `main` (checked with `get_tool_json_schema`, so no prompt tokens added), nothing written to the real `.undo/`, failure to save never blocks a write. | 26,299 tokens (151,669 to 177,968), baseline taken before reading anything; covers the diff, the tests, the edge-case probes, the fix and the merge. | 8fbed9a | yes: close to mergeable, the defects were small and fixed in one commit. The review cost more than #53's because the diff is larger and sits next to the confirmation layer. |
| [#59](https://github.com/aurora7795/smolpaw/issues/59) | scheduler fix (summary wait, not-run-twice) | scoped fix | (1) Correctness: the summary-wait start was reset only on ticks past the running/pending early return, so after an interactive run a stale start let a schedule begin during a fresh summary (reproduced: it started instead of waiting). (2) Test quality: the cap test passed vacuously, since its dummy ids were dropped as unknown and the cap never ran. (3) Dead code: a float-clock branch nothing used. Held up: both fixes behave as briefed, 7 new tests fail on `main` for the stated behaviour (real gates, a real raising `mark_ran`), scope respected, docs updated, branch pushed. Also: one unreproduced failure of an older test ("one line per distinct error") in 33 runs. | 17,466 tokens (188,521 to 205,987), baseline taken before reading anything. | 949756e | yes: close to mergeable, the one real bug was narrow and fixed in one commit. |
| [#69](https://github.com/aurora7795/smolpaw/issues/69) (research input) | read-only research (how SmallCode routes tools), not code | scoped fix | (1) Wrong answer: question 4 said prefix/KV caching was "not found" and inferred the authors had not considered it; `bin/smallcode.js:2054-2058` and `:2293` show SmallCode moves dynamic context out of the system prompt (`SMALLCODE_CACHE_SPLIT`, default on) to keep the prefix stable for llama.cpp. (2) Wrong citations: `tool_router.js:144-150` is not the plan/respond cases (they are at 245 and 249), `:88-124` is not the classifier (it starts at 156), `two_stage_router.js:79-91` is not the savings estimate (95-105), `smallcode.js:1372-1380` is tool-result printing, not the no-fallback claim. (3) Overreach: "dormant" for the model-picks-category path; the code keeps it as the fallback when classification throws or `SMALLCODE_TOOL_ROUTING` is set, and `ARCHITECTURE.md:23-28` documents it. (4) Gap: it searched `SMALLCODE_TOOL_ROUTING` but did not report it. Held up: commit and date, the regex classifier, the escape hatch to `plan` after the first tool call, validation against the full registry, no on/off benchmark, and savings figures that are estimates (`estimateSavings` is JSON length divided by 4). | 16,626 tokens (140,605 to 157,231); the baseline was taken after the report was already in context, so reading it is not counted. Covers fetching and reading the cited files at the commit. | none (no code) | yes: the structure and most evidence were right and checkable, one finding was wrong in a way that matters for the plan. Cheaper than reading the repo cold, but only because the citations let me jump to the lines. |
| [#73](https://github.com/aurora7795/smolpaw/issues/73) (fixture) | test fixture (fake web server and SearXNG-shaped search, `tests/fake_web.py`) | scoped fix | (1) Design flaw: each search result's snippet carried the first fact of its page, so a task could be answered without fetching. (2) Tests that let broken fixtures pass (found by mutating the fixture): "does not contain all six facts" passed with four facts visible without a query; determinism was checked only inside one process, so a clock-seeded page still passed. (3) Port: the default 8766 is `fake_mail.py`'s SMTP port (an error in my brief, copied into the README). (4) The CLI test passed on a banner that printed the requested port 0 and ran the script by a cwd-relative path; unused imports. Held up: the three page sizes (6,376, 6,611, 6,428 characters) match my measurement; the length and uniqueness mutations fail as reported; `fetch_page` and `web_search` are exercised through the real tools; the forbidden files are untouched; identical page bytes across processes with different hash seeds; all six suites pass. | 28,837 tokens (252,951 to 281,788); the baseline was taken after the report was already in context. Covers the diff, the suites, eight mutation runs, the fixes and the merge. | 6e60345, 2f38999 | yes: the fixture was sound and the gaps were in what the tests checked, fixed in one commit. One slip of mine along the way: restoring a mutated file with `git checkout` also reverted my uncommitted fixes, and the next run exposed it; commit fixes before mutating. |

Rows for #3 to #28 were written from memory notes after the fact, so their cost and fix-commit columns are blank. Rows from #53 on are filled in as the review happens.

## Running totals

Update after each row.

- Delegated issues logged: 9
- Clean: 0, scoped fix: 8, rework: 0, rejected: 1
- Verdict yes: 8, no: 1, unclear: 0
