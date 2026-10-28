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

Rows above were written from memory notes after the fact, so their cost and fix-commit columns are blank. Rows from here on are filled in as the review happens.

## Running totals

Update after each row.

- Delegated issues logged: 4
- Clean: 0, scoped fix: 3, rework: 0, rejected: 1
- Verdict yes: 3, no: 1, unclear: 0
