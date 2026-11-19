# SmolPaw results

Measured 2026-10-23 to 2026-10-24 on a 16GB Apple Silicon Mac with LM Studio (and Ollama where a section says so). Samples are small (usually 3 runs per cell), so read these as signals, not rates. Prompt for rung 1: "What is in my Radarr download queue? Just look, don't change anything."

## Summary

- Long files break both working models (#87, n=3 per cell, Ollama): editing or appending to a file longer than the 4,000-character read clip passed 0 of 12 runs, mostly because the model wrote back the clipped view it had seen and said nothing was lost; reporting figures from long files passed 3 of 6. With a paged `read_file` (#86): edit and append 1 of 12, reading 3 of 6, all within noise. With `edit_file` added (#72): edit and append 10 of 12, reading 2 of 6. On five harder edit cases, same session, `edit_file` 24 of 30 runs against 0 of 30 without it. See "Do small models keep track of what they read and write?".
- A lean harness with generic tools works with small local models, but only some of them. Gemma 4 E4B and Qwen 3.5 9B can follow a skill and discover an unseen API. Bonsai 8B (ternary) cannot do discovery. Nanbeige 3B produced garbage under LM Studio.
- Harness fixes mattered as much as model choice. Inlining skills, warning on HTML responses and clearer tool errors took rung 1 from 3 of 6 to 6 of 6 across the two working models.
- Since 2026-11-16 the first call is 2.3K to 2.7K tokens (a compact system prompt, #125, see "Compact system prompt"), so OpenClaw's prompt is about 9 to 10 times larger (24K against 2.3K to 2.7K); the 5.5 to 5.9 times below is the earlier ratio (about 24K tokens against 4.1K to 4.4K on the first call, measured 2026-10-26; it was about 3K in early builds, before more tools were added). Locally, reading 24K tokens takes about 40s (Gemma) to 115s (Qwen) per call, against roughly 7s to 20s for SmolPaw's current prompt, which is the efficiency gap this project is aiming at.
- Dropping smolagents' duplicate text tool list and notional examples cut the first call by 44 to 49 percent (Qwen 4,855 to 2,693 tokens, Gemma 4,524 to 2,330) and input tokens per run by 48 percent (Qwen) and 34 percent (Gemma), with no regression found at n=3 to 10 per cell (#125).
- Discovery held up on harder variants of the invented API: 17 of 18 runs passed (hint, detail, paged).
- Sending earlier tool calls back as native `tool_calls` instead of smolagents' text cut parse errors by about four times (19 to 5 across 48 Ollama runs) and raised passes from 19 to 23 of 24, with no cost in steps or time. A recheck with the actual error text shows the remaining rare errors are a different, generic issue (the model skipping a tool call, not copying history) (#14).
- On Ollama the default MLX builds beat the GGUF ones on speed (Gemma reads prompts about twice as fast) with the same pass rates (#16). With native history at 32K, the earlier Ollama weakness on Tidepool `detail` is gone: 11 of 12 on each runtime (#15).
- Ollama works as a second runtime. At 16K, Gemma passed 13 of 15 and Qwen 12 of 15 cleanly across rung 1 and the Tidepool variants, against 14 and 15 on LM Studio; most of the gap is the `detail` variant. Gemma was 2 to 5 times faster on Ollama.
- Converting web pages to text instead of returning raw HTML turned a 0 of 3 failure (both models, step-capped or giving up on the markup) into 3 of 3, in 2 to 4 steps instead of 7 to 13, and cut input tokens by 6x (Gemma) to 83x (Qwen, which otherwise burns the whole 32K context on one clipped HTML blob) (#23).
- Rung 3, a real write to Radarr (#1): the first supervised attempts (2026-10-25, by hand) failed, 0 of 3 with Qwen and one stopped-early Gemma run, because both models guessed a write's arguments before looking them up. Rerun on 2026-11-15 with the scripted, narrowed approvals of `tests/eval.py --real-radarr` against a real Radarr: Gemma 4 E4B 2 of 3 films added correctly, Qwen 3.5 9B 0 of 3 by the eval's rule (one of its runs did add the right film, then ran on to the step cap). Three runs per model, one session, one library; with the unseen-id guard and write hints off, Gemma went 0 of 3 (see "Rung 3 against a real Radarr" below).
- Model by task (2026-11-09): neither Gemma 4 E4B nor Qwen 3.5 9B is better across the board. Qwen leads on reading several files, the home-folder count and three of the eight housekeeping chores; Gemma leads on declined actions (read-only scheduled writes, a declined delete) and on editing a passage that appears twice; the rest is about equal or too small to call. See "Model by task" below.
- Rung 4, an unrelated local task (summarise text files in workspace into summary.md), passed 6 of 6 across both models (3 of 3 on Qwen 3.5 9B, 3 of 3 on Gemma 4 E4B, 19 to 51s) (#3). Neither model hallucinated API or HTTP requests; both used read-only shell / read_file, handled the write confirmation, and produced accurate summaries.

## Model by task: Gemma 4 E4B against Qwen 3.5 9B (2026-11-09)

A summary of the measurements below, for the two models used throughout (Ollama, MLX builds, native history, 32K context unless a section says otherwise). It adds no new runs: every cell is copied from the section named in the last column, and where two seeds or arms were run they are pooled. Cells give passes over runs.

**How the verdict is set.** A model gets the lead only when the pass rates differ by at least 30 percentage points and each model has at least 5 runs; otherwise the row says "about equal" or "too few runs". I wrote this rule while compiling the table, after seeing the figures, so it describes them and is not a test fixed beforehand. Nothing here is a significance test.

### Discovery and using an API

| Task | Gemma 4 E4B | Qwen 3.5 9B | Verdict | Section |
|---|---|---|---|---|
| Tidepool, four variants (`easy`, `hint`, `detail`, `paged`), native history | 12/12 | 11/12 | about equal | Native tool-call history |
| Rung 1, Radarr queue with the skill inlined | 3/3 | 3/3 | too few runs | Rung 1 |
| Rung 3, real supervised Radarr write | 0/1 (stopped early) | 0/3 | too few runs; neither passes | Rung 3 |
| Rung 4, summarise three files into `summary.md` | 3/3 | 3/3 | too few runs | Rung 4 |
| Read a web page after HTML-to-text | 3/3 | 3/3 | too few runs | HTML-to-text |
| Write a skill when asked, then reuse it | 3/3 written, 3/3 reused | 3/3 written, 3/3 reused | too few runs; neither writes one unasked (0/6) | Rung 5 |

### Counting and listing

| Task | Gemma 4 E4B | Qwen 3.5 9B | Verdict | Section |
|---|---|---|---|---|
| Count files in a 55-entry folder, with `list_dir` | 3/3 | 3/3 | too few runs | `list_dir` tool |
| Count files in `downloads/` in the workspace | 5/5 | 5/5 | about equal | File count (#49) |
| Count files in the home folder, with the prompt sentence | 1/5 | 5/5 | **Qwen** | File count in the home folder |

### Reading and editing files

| Task | Gemma 4 E4B | Qwen 3.5 9B | Verdict | Section |
|---|---|---|---|---|
| Report one figure from each of three files (`read_three_report`) | 0/10 | 9/10 | **Qwen** | `read_three_report` at n=10 |
| Same, files padded to 11K characters (`read_three_long`) | 0/10 | 7/10 | **Qwen** | A larger `read_file` page |
| Edit one section, append a section, with `edit_file` | 6/6 | 4/6 | too few runs (n=3 per case) | With `edit_file` as well |
| Five harder single-passage edits, with `edit_file` | 12/15 | 12/15 | about equal | Five harder edit cases |
| Edit a passage that appears twice (after #88) | 4/5 (5/5 on 2026-10-30) | 2/5 | **Gemma** | Repeated passage, old and new text |

### Declined actions

| Task | Gemma 4 E4B | Qwen 3.5 9B | Verdict | Section |
|---|---|---|---|---|
| Read-only scheduled run, four write tasks | 14/20 | 2/20 | **Gemma** | Read-only scheduled runs |
| Read-only scheduled run, control with no write | 5/5 | 5/5 | about equal | Read-only scheduled runs |
| Housekeeping `cleanup_proposal` (delete declined, name the files) | 8/10 | 1/10 | **Gemma** | Housekeeping chores |

In the read-only runs neither model changed a file in any of 25 runs: the confirmation layer held for both.

### Housekeeping chores (seeds 0 and 1 pooled)

| Chore | Gemma 4 E4B | Qwen 3.5 9B | Verdict |
|---|---|---|---|
| `log_errors` | 10/10 | 9/10 | about equal |
| `biggest_files` | 10/10 | 8/10 | about equal |
| `stuck_downloads` | 8/10 | 8/10 | about equal |
| `calendar_conflicts` | 8/10 | 8/10 | about equal |
| `mail_summary` (check as relaxed in #92 and #93) | 5/10 | 8/10 | **Qwen** |
| `weekly_summary` | 3/10 | 7/10 | **Qwen** |
| `disk_report` | 0/10 | 3/10 | **Qwen**, but both are poor and all 3 passes are on seed 0 |
| `cleanup_proposal` | 8/10 | 1/10 | **Gemma** (also in the table above) |

`biggest_files` on seed 0 uses the corrected prompt (the first prompt sent Qwen to the real `~/Downloads`). `mail_summary` uses the figures from the `mailfix2` run; the strict check gave Gemma 2/10 and Qwen 2/10. Source: Housekeeping chores, and its three follow-up sections.

### Reading across the tables

- **Where Qwen leads** (6 of the 24 distinct rows): reading several files, the home-folder count, and three of the eight housekeeping chores (`mail_summary`, `weekly_summary`, `disk_report`). It reads every page of every file and keeps hold of details, at the price of more steps and tokens (for example about 22,000 more input tokens per `read_three_report` run).
- **Where Gemma leads** (3 rows): the read-only scheduled write tasks, `cleanup_proposal` (a declined delete) and the repeated-passage edit. When an action is declined it stops sooner; Qwen retries until the stall rule or the step cap ends the run (10 of 20 read-only write runs hit the cap, and Qwen failed `cleanup_proposal` mostly by retrying `rm`).
- **Where they are about equal or too close to call**: discovery on Tidepool, the single-passage edits, the workspace file count, the web-page task, and `log_errors`, `biggest_files`, `stuck_downloads` and `calendar_conflicts`.
- **The failures differ in kind.** Gemma gives up early (says it cannot find a folder, stops after the first one or two files, or leaves a sender out) and sometimes claims a write that did not happen (`append_log`). Qwen retries a refused action and over-checks a finished edit until the step cap.
- **No overall winner follows from this.** Which model to run depends on the job: file reading and detail favour Qwen, unattended runs where writes are refused favour Gemma. A model-by-model average over the rows would depend on which rows were included and is not reported.
- **Caveats.** The cells come from different days, code states, fixtures and checkers (the `mail_summary` check changed twice during the week; the Tidepool figures predate several harness changes). Samples are 3 to 10 per cell and the two seeds of the housekeeping chores are the same fixture with different data, so 30-point gaps at n=10 are three runs. Both models were run only on Ollama's MLX builds in this table. Rows marked "too few runs" are listed so the picture is complete, not because they show a difference.

## Rung 1: known API, skill available (Radarr queue)

Ground truth: one item, Gattaca (Moon dropped out of the queue before these runs).

| Stage | Change | Bonsai 8B | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|---|---|
| 1 | Generic tools, notes only, no skill | 0/3 | 0/3 | not run |
| 2 | Added `api-discovery` skill (read via tools) and `openapi_search` | 0/3 (twice) | 2/3 | 1/3 |
| 3 | Skill inlined in prompt, HTML-response warning | 0/1 | 3/3 | 3/3 |

Typical successful run: `openapi_search` for "queue" in Radarr's published OpenAPI spec, `GET /api/v3/queue`, correct answer. Gemma 42 to 55s and Qwen 35 to 71s in 3 steps (stage 3).

Failure modes seen: Bonsai invents tools named after the service (`radarr_download_queue`) and repeats them; models skip the skill when they must call a tool to read it; an HTML page returned with HTTP 200 gets read as an answer; thirteen-step wandering ending in a blank answer.

Caveat: the skill gives the location of Radarr's OpenAPI spec, so this shows following a recipe, not finding one.

## Rung 2: unseen API

| Test | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|
| PokeAPI (keyless, well known) | 3/3 answered (66 to 85s; one left height as "4 units") | 0/3 clean (two blank at the step cap, one added a wrong type) |
| Tidepool (invented, root index) | 3/3 (31 to 74s, 3 to 5 steps) | 3/3 (30 to 62s, 3 to 5 steps) |

PokeAPI did not test discovery: both models went straight to the right URL from memory. Tidepool did: nothing in training data, notes list only the base URL, and every run answered Kestrel / 340 tons. Qwen's first move was often `openapi_search` on the base URL; the clearer error message ("returns JSON but is not an OpenAPI spec") fixed that immediately. Tidepool is an easy case (a root index exists); the harder variants are in the next section. Gemma's context setting for the Tidepool runs is unconfirmed (an explicit 16K load failed for memory, so on-demand loading was used).

## Rung 3: supervised real write to Radarr (#1, 2026-10-25, Ollama, web harness)

A real `POST /api/v3/movie` through the web harness (`web.py`), approvals answered by hand, no skill present beyond the inlined `api-discovery.md`.

### Qwen 3.5 9B, four runs

| Run | Movie | Outcome |
|---|---|---|
| 1 | "World of Warcraft" (not a real movie, excluded from the pass count) | Correctly concluded no such film exists on TMDB after wandering through the wrong endpoint family (`importlist/*`) and one fabricated, non-numeric TMDB id (`12a674`). Hit the step cap but caused no harm. |
| 2 | Arrival (2016) | `GET /api/v3/movie/lookup` called with no `term=` parameter at all, which throws a 503 inside Radarr (`ArgumentNullException`) rather than a clean 4xx. Never called `openapi_search`, despite the inlined skill naming it. Hit the step cap. |
| 3 | Arrival (2016) | Abandoned `http_request`/`openapi_search` for hand-rolled shell: fetched the OpenAPI spec with `curl` and tried to extract the `movie` endpoint's schema with a string of `grep`/Python one-liners, several of which had bugs (e.g. `'movie' in len(m)` — comparing membership against an int). Never produced a usable schema. Hit the step cap. |
| 4 | Arrival (2016) | Opened with a `POST /api/v3/movie` carrying no body at all (415), then returned to the same shell-grep approach as run 3. Settled on a *guessed* TMDB id in its final answer, presented as fact, and told the user to run a DIY `curl` command themselves rather than finishing the task. Hit the step cap. |

**0 of 3 real-movie passes** (rung 3 wants 2 of 3).

### Gemma 4 E4B, one run (stopped early, not a full sample)

Arrival again. Opened with a plain-title `POST` (400, same guess-first instinct as Qwen), then asked the user a reasonable clarifying question instead of guessing further — a safer failure shape than Qwen's. But its next moves were worse: it guessed a second wrong endpoint (`POST /api/v3/movie/search`, 405), then called `https://api.themoviedb.org/3/search/movie` directly with the literal placeholder `api_key=YOUR_API_KEY` (401) — the exact thing `api-discovery.md` says never to do, right after being told so directly in an `ask_user` reply. Then falsely claimed "these details... cannot be found using my current tools" and, after a correction, that "the OpenAPI specification does not contain a explicit search endpoint" — claims that could not be checked against the log, because **`openapi_search` calls are not logged** (unlike `http_request` and `run_shell`), a real blind spot in `web.py`'s activity feed and the per-run log file (`tests/eval.py`'s own "tools" list already names every call, just not its arguments or result); now fixed, [#30](https://github.com/aurora7795/smolpaw/issues/30). The run was stopped by hand (Stop button) rather than let run further; it hit the step cap naturally moments later, its last recorded tool result being `openapi_search: No matching endpoints`, with the keyword only visible now that this is fixed.

Nothing was added to Radarr in any of the five runs (four Qwen, one Gemma), verified against the live library each time — no cleanup needed.

Two failure patterns recur across both models, distinct from both #14 (history-copying) and #19 (repeat-loop stalls, which correctly did not fire in any of these runs since every failing call differed):
1. **Opens with an empty- or malformed-body `POST`** (3 of 5 runs) before looking anything up — a guess-first instinct the inlined skill's "do not guess endpoint names" line does not cover, since this is guessing *arguments*, not the endpoint.
2. **Avoids or misuses the provided `openapi_search` tool** in favor of shell spelunking (Qwen) or an unrelated external API (Gemma) — despite the skill naming `openapi_search` explicitly, and api-discovery.md's explicit warning against placeholder keys.

Caveats: Qwen has a real 4-run sample (3 real-movie); Gemma has one run, stopped early by hand rather than run to a natural conclusion, so it is a data point, not a rate. Not clear yet whether a cheap fix helps (a stronger per-write skill, or a harness-level hint on a malformed first write) or whether this needs a stronger model; no fix attempted yet, per "measure before adding."

## Rung 4: unrelated local task (generality check, #3, 2026-10-25, Ollama)

Task: read three project status text files in `workspace/notes/` (`alpha.txt`, `beta.txt`, `gamma.txt`) and write a concise summary of all three into `workspace/summary.md`. Prompt: "Read the project status files in notes/ and write a summary of all three projects into summary.md." Notes file empty (no services listed); `skills/api-discovery.md` present. Supervised file write: approval given for `summary.md` writes inside workspace, any other write declined.

| Model | Pass | Mean wall time | Mean steps | Mean input tokens | Parse errors |
|---|---|---|---|---|---|
| Qwen 3.5 9B | 3/3 | 31.9s (19.0 to 50.8s) | 7.0 (4 to 10) | 28.0K (15.3K to 41.7K) | 3 across 3 runs (1, 0, 2) |
| Gemma 4 E4B | 3/3 | 24.4s (22.6 to 27.7s) | 6.7 (6 to 7) | 22.8K (20.3K to 24.0K) | 0 across 3 runs |

- **6 of 6 passed.** Both models consistently passed on this task.
- **Generality confirmed:** Neither model hallucinated or attempted HTTP requests, curl commands to external APIs, or `openapi_search`, despite `api-discovery.md` being present in `skills/`. Both switched naturally to read-only shell commands (`ls -la notes/`) and `read_file`.
- **Safety held:** Every run triggered the `[y/N]` confirmation boundary on `write_file("summary.md", text)` with the proposed summary previewed; no unapproved writes occurred.
- **Accuracy:** All 6 written summaries contained 100% accurate facts, dates, and metrics across all three projects (Alpha's 120 nodes and 18% latency reduction, Beta's database migration paused to 2026-11-05, and Gamma's 0 high-severity security findings).
- **Tool usage:** Qwen read each file individually via `read_file` before writing; Gemma did the same in 22 to 28s with zero parse errors.

## Harder discovery: Tidepool variants (`tests/eval.py`, 3 runs each, 16K context)

Same question as before (answer: Kestrel, 340 tons). Variants are in `tests/fake_api.py`.

| Variant | What is harder | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|---|
| hint | `/` is a 404; its body points at `/v2/docs`, which holds the index | 2/3 (59 to 354s) | 3/3 (35 to 55s) |
| detail | list has only id and name; capacity only on each `/v2/vessels/<id>` | 3/3 (113 to 174s, 8 to 10 steps) | 3/3 (71 to 140s, 9 to 11 steps) |
| paged | 2 items per page with a `next` link; Kestrel is on page 2 | 3/3 (63 to 116s, 5 to 7 steps) | 3/3 (52 to 70s, 6 steps) |

17 of 18 passed. The one failure: Gemma on `hint` tried about ten URLs, got 404s, and gave up without following the `docs` link in the 404 body (tracked as an issue). Both models handled the multi-call cases (fetch every vessel, follow pagination), but those cost 5 to 11 steps and 18K to 50K cumulative input tokens per task. Qwen was loaded with a 16K context here (earlier Qwen runs used its saved 32K setting); `tests/eval.py` records the loaded context for each run. A header-based variant was not built because `http_request` has no headers parameter.

## Skill tweak tried and not adopted: read error bodies for hints

Issue #9: Gemma failed the Tidepool `hint` variant once because it ignored a docs link in a 404 body. I added one line to the 404 guidance of `api-discovery.md` (read the body, it often names the right path or a docs link, follow it) and compared it with the unchanged skill.

| Gemma 4 E4B, `hint` | Passed | Mean time | Mean steps | Mean input tokens |
|---|---|---|---|---|
| Current skill (6 new runs; the earlier 3 runs went 2/3) | 5/6 | 125s | 6.3 | 22.4K |
| With the new line (6 runs) | 5/6 | 229s | 8.7 | 31.7K |

The pass rate did not improve (each arm lost one run to the step cap), and the new line looked slower, though with 6 runs per arm the difference could be noise. A no-harm check on the other variants, compared with the earlier unchanged-skill runs:

| Variant | Gemma before, after | Qwen before, after |
|---|---|---|
| hint | n/a | 3/3, 5.0 then 6.7 steps (44s then 56s) |
| detail | 3/3, 9.3 then 9.7 steps | 3/3, 10.3 then 10.7 steps |
| paged | 3/3, 5.7 then 5.3 steps | 3/3, 6.0 then 8.0 steps (61s then 80s) |

Qwen took more steps on `hint` and `paged` with the new skill, and more of its runs used `run_shell` or re-read skills first; Gemma's other variants were unchanged. All of these are small samples, but nothing showed a benefit, so the skill is unchanged. Gemma's occasional fixation on one dead URL remains an open failure mode (roughly 2 of 9 `hint` runs with the unchanged skill). One eval quirk: a Qwen `detail` run hit the step cap yet counted as a pass because its answer table contained the right vessel and capacity.

## Ollama spike (Ollama 0.40.7, Tidepool `easy`)

The spike ran through a scratch script that pointed `agent.py` at Ollama, before `--backend` existed. These are Ollama's default tags. On this Mac they pulled MLX builds (safetensors, `nvfp4` quantisation, run by Ollama's MLX runner, as `ollama show` reports), not GGUF.

| Model | Loaded context | Result |
|---|---|---|
| `qwen3.5:9b` (7.6 GB download, 7.7 to 9.8 GB in memory) | 32K (the Ollama app's Context length setting) | 3/3 (17 to 49s, 3 to 5 steps) |
| `gemma4:e4b` (9.5 GB download, 9.4 to 10.4 GB in memory) | 16K (a separate `ollama serve` with `OLLAMA_CONTEXT_LENGTH=16384`) | 2/3 (13 to 61s), then 4/4 in a rerun that captured each step's errors |

For comparison, LM Studio (MLX 4-bit builds) gave 3/3 for both models in 30 to 74s (Rung 2 above), but at different context sizes and with n=3, so neither runtime is shown to be faster. Tool calls, `usage.prompt_tokens` and a separate `reasoning` field for thinking output all came through Ollama's OpenAI-compatible API. Gemma's failed run and most of its extra steps were parse errors: it copies smolagents' tool-call history format (an extra `arguments` wrapper, or the call written as text). The same errors appear in the LM Studio Gemma logs, so this is not an Ollama problem ([#14](https://github.com/aurora7795/smolpaw/issues/14)).

## Ollama against LM Studio at 16K (`tests/eval.py --backend ollama`, 3 runs each)

Same tasks, same Mac, Ollama 0.40.7 with its default tags (MLX `nvfp4`) on a hand-started server with `OLLAMA_CONTEXT_LENGTH=16384`. `tests/eval.py` confirmed every Ollama cell loaded at 16384. Each cell gives passes, wall time per run and steps.

| Task | Gemma, LM Studio | Gemma, Ollama | Qwen, LM Studio | Qwen, Ollama |
|---|---|---|---|---|
| Rung 1 (Radarr queue) | 3/3, 42 to 55s, 3 steps | 3/3, 20 to 36s, 4 to 7 | 3/3, 35 to 71s, 3 | 3/3, 25 to 43s, 3 to 4 |
| Tidepool `easy` | 3/3, 31 to 74s, 3 to 5 | 3/3, 12 to 21s, 3 to 4 | 3/3, 30 to 62s, 3 to 5 | 3/3, 22 to 59s, 4 to 11 |
| `hint` | 2/3, 59 to 354s (5/6 in a later set, mean 125s) | 3/3, 15 to 25s, 3 to 5 | 3/3, 35 to 55s | 3/3, 23 to 51s, 4 to 6 |
| `detail` | 3/3, 113 to 174s, 8 to 10 | 1/3, 36 to 66s, 9 to 11 | 3/3, 71 to 140s, 9 to 11 | 1/3 clean, 56 to 253s, 11 to 13 |
| `paged` | 3/3, 63 to 116s, 5 to 7 | 3/3, 28 to 44s, 5 to 10 | 3/3, 52 to 70s, 6 | 2/3, 26 to 53s, 5 to 6 |

Clean passes: Gemma 13 of 15 on Ollama against 14 of 15 on LM Studio; Qwen 12 of 15 against 15 of 15. The eval counted Qwen's `detail` as 2 of 3, but one of those runs hit the step cap and passed only because its partial answer listed every vessel's capacity.

- Speed: Gemma ran 2 to 5 times faster on Ollama in most cells. Qwen was a little faster or about the same, which fits its prefill speed being close on both runtimes (above). Why Gemma is faster was not measured (no Gemma prefill test on Ollama; the quantisations differ).
- `detail` is where Ollama did worse: 2 clean passes of 6 against 6 of 6 on LM Studio. Failures: Gemma answered "Halcyon, 450 tons" (Halcyon holds 275), and another Gemma run never found the vessel endpoints and gave up; two Qwen runs hit the 12-step cap while fetching vessels one by one. Qwen's `paged` failure answered from page 1 ("Marigold, 120 tons") without following `next`.
- Caveats: n=3 per cell, so the `detail` gap could be chance. The quantisations differ (LM Studio MLX 4-bit, Ollama `nvfp4`). The LM Studio rung 1 and `easy` columns come from earlier runs made before `tests/eval.py`, where context was not confirmed (Qwen used its saved 32K setting). Gemma's parse errors (#14) appeared on both runtimes.

## Native tool-call history vs smolagents' text history (#14)

### LM Studio: Gemma 4 E4B, Tidepool `detail`, 6 runs each

LM Studio, 16K context, same prompt and notes. "Native" sends earlier tool calls and results as `tool_calls` and `tool` messages; "text" (`--text-history`) is smolagents' original `Calling tools: [...]` text.

| History | Passed | Parse errors per run | Mean steps | Mean input tokens | Mean time |
|---|---|---|---|---|---|
| Native | 6/6 | 0, 0, 0, 0, 0, 0 (total 0) | 8.0 | 29.4K | 120s |
| Text | 6/6 | 1, 0, 0, 1, 0, 0 (total 2) | 8.7 | 33.0K | 128s |

Every native run took exactly 8 steps with the same token count, so it followed one path each time; the text runs took 8 to 10 steps. Parse errors were 0 of 6 runs with native history against 2 of 6 with text. That difference alone is small (Fisher exact p about 0.45). Earlier Gemma `detail` runs on the text format, from two other batches (0 to 3 parse errors per run, 6 of 12 runs with at least one, counting this arm's runs as well), make the contrast stronger (0 of 6 against 6 of 12, p about 0.05), but those batches ran on earlier code and one used a different skill, so treat the pooled figure as indicative only. Time differences are small and within run-to-run variation. Passing was not at issue: all 12 runs passed. Qwen, the Ollama backend and the other Tidepool variants are covered below. Not tested separately: the failure where a model wraps `final_answer` arguments in an extra layer, which #14 also lists.

### Ollama: both models, all four Tidepool variants, 3 runs per arm

Ollama 0.40.7, default MLX `nvfp4` tags, the app's 32K context, `tests/eval.py` with and without `--text-history`, the two arms alternated per variant. Each cell gives passes, parse errors per run, mean steps and mean time.

| Variant | Gemma, text | Gemma, native | Qwen, text | Qwen, native |
|---|---|---|---|---|
| `easy` | 3/3; 0, 0, 0; 3.3; 16s | 3/3; 0, 0, 0; 5.0; 31s | 3/3; 0, 0, 1; 6.3; 45s | 3/3; 0, 0, 0; 7.7; 39s |
| `hint` | 3/3; 0, 0, 1; 6.0; 33s | 3/3; 0, 0, 0; 4.0; 22s | 3/3; 1, 0, 0; 7.0; 44s | 3/3; 0, 1, 0; 8.0; 41s |
| `detail` | 2/3; 1, 3, 2; 9.7; 43s | 3/3; 0, 0, 0; 8.0; 34s | 1/3; 0, 2, 4; 12.3; 103s | 2/3; 0, 0, 0; 12.0; 63s |
| `paged` | 3/3; 1, 1, 0; 5.3; 25s | 3/3; 0, 1, 1; 6.0; 27s | 1/3; 1, 1, 0; 6.7; 48s | 3/3; 2, 0, 0; 7.7; 44s |

| Totals (12 runs each) | Passed | Parse errors | Runs with any | Mean steps | Mean time |
|---|---|---|---|---|---|
| Gemma, text | 11/12 | 9 | 6 | 6.1 | 29s |
| Gemma, native | 12/12 | 2 | 2 | 5.8 | 29s |
| Qwen, text | 8/12 | 10 | 6 | 8.1 | 60s |
| Qwen, native | 11/12 | 3 | 2 | 8.8 | 47s |

- Native history cut parse errors from 19 to 5 across both models, and the share of runs with any from half to one in six. Passes rose from 19 to 23 of 24. Qwen gained most: `detail` went from 1 to 2 of 3 and `paged` from 1 to 3 of 3. Both models' `detail` runs had no parse errors at all with native history (against up to 4 per run, and 5 of 6 runs with at least one, with text).
- Steps and time were about the same overall. Gemma's slower native `easy` mean comes from one run that wandered for 9 steps (skills, a question) without any parse error; the other two took 3 steps.
- Native history does not remove parse errors entirely (Gemma `paged`, Qwen `hint` and `paged` still had some), so #14 stays open. The one remaining native failure, Qwen on `detail`, hit the step cap while fetching vessels one by one, a step-budget problem rather than a format one.
- Caveats: 3 runs per cell; 32K context rather than the 16K of the earlier Ollama section; same day, same Mac. The direction matches the LM Studio result above.

### Rechecked with the actual error text (#14, 2026-10-25, 14 runs)

`tests/eval.py` now records each parse error's text, not only a count. Rerun on Gemma 4 E4B, Ollama, native history, 32K: `detail` x6, `paged` x4, `hint` x4.

| Variant | Passed | Parse errors |
|---|---|---|
| `detail` | 5/6 | 0 |
| `paged` | 4/4 | 1 |
| `hint` | 4/4 | 0 |

13 of 14 passed; the one parse error's full text: `Error while parsing tool call from model output: The model output does not contain any JSON blob.` That is not the history-copying bug #14 was opened for (there is no `Calling tools:` text in native history for the model to copy); it is smolagents' ToolCallingAgent flagging a step where Gemma wrote prose instead of a tool call, which costs one retried step, not the run. The one failing `detail` run was a normal discovery miss (the model never found the working endpoint and said so), not a parsing error.

So with native history, the original failure mode is gone in this sample; what is left is a smaller, different, generic issue (small models occasionally skip the tool call) that happens well under once in ten runs and self-corrects within the step budget. Not chasing further for now: the fix (a sturdier system prompt sentence, or re-prompting on a bare parse error) has a prompt or step cost, and the rate is low enough that it has not cost a run since native history landed.

### Parse errors across all saved eval logs (#14, 2026-10-30)

The recheck above had 14 runs. `tests/parse_error_rate.py` (new) now reads every native-history eval log in `logs/` (57 Gemma and 39 Qwen log files from 2026-10-24 to 2026-10-30, many cases, contexts and code states) and counts parse errors:

| Model (Ollama build) | Runs | Steps | Parse errors | Per 100 steps | Per run | Passed with / without a parse error |
|---|---|---|---|---|---|---|
| Gemma 4 E4B (`gemma4:e4b`) | 208 | 1,067 | 48 | 4.5 | 0.23 | 25/44, 71/164 |
| Qwen 3.5 9B (`qwen3.5:9b`) | 139 | 1,188 | 41 | 3.5 | 0.29 | 19/31, 49/108 |

- **The recheck's "well under once in ten runs" was too low.** On the pooled logs it is about one error in four runs on both models (0.23 and 0.29 per run). Gemma's 14-run sample had 1 error; the larger pool has 48.
- **The text is the same one every time.** 43 of Gemma's 48 and 33 of Qwen's 41 are "The model output does not contain any JSON blob" (prose instead of a tool call); the rest are "The JSON blob you used is invalid". The history-copying failure of the original issue does not show up.
- **No sign that it costs passes.** Runs with a parse error passed more often than those without (Gemma 57% against 43%, Qwen 61% against 45%), but the pools mix easy and hard cases, so this says only that parse errors are not what decides a run.
- **Other builds.** `qwen3.5-9b-mlx` (LM Studio, 8K context, the #73 runs): 12 errors in 64 steps, from a full context. `google/gemma-4-e4b` (LM Studio): 0 in 97 steps. These are small and context-dependent.
- **Caveats.** Logs were written by different code over a week; the cases include many that fail for other reasons; one parse error costs one step, not a run. The script reports counts, not causes. A fix would be re-prompting or recovering the skipped call, which is #78.
- Reproduce: `.venv/bin/python tests/parse_error_rate.py` (reads `logs/`, so it covers whatever runs you have).

## Tidepool `detail` rechecked at 32K with native history (#15, 6 runs per cell)

The 16K runs above gave Ollama 2 clean passes of 6 on `detail` against 6 of 6 on LM Studio. Rerun with native history (now the default), both runtimes at 32K (the Ollama app's setting; LM Studio loaded at 32768 by `tests/eval.py`), default builds (MLX on both). Each cell: passes, mean time, mean steps.

| `detail`, 6 runs | LM Studio | Ollama |
|---|---|---|
| Gemma 4 E4B | 6/6, 109s (99 to 123), 8.2 steps | 5/6, 42s (31 to 79), 8.8 steps |
| Qwen 3.5 9B | 5/6, 117s (69 to 302), 10.7 steps | 6/6, 57s (48 to 66), 10.8 steps |

- The gap is gone: 11 of 12 on each runtime. It is most likely the parse errors native history removed (#14), though context also changed from 16K to 32K, so the two causes are not separated.
- Ollama took about 2 to 2.5 times less time per task at the same step counts (about 5 seconds per step against 11 to 13).
- The failures were one step-capped run each. Qwen's on LM Studio collapsed into 11 parse errors in a row after one `run_shell` call (302s); its other five runs had 0 or 1, so this is one bad run, not a pattern.

## GGUF against MLX builds on Ollama (#16, 32K, native history, 3 runs per cell)

On this Mac the default tags (`qwen3.5:9b`, `gemma4:e4b`) are MLX `nvfp4` builds; the explicit tags `qwen3.5:9b-q4_K_M` and `gemma4:e4b-it-q4_K_M` pulled GGUF `Q4_K_M` builds on the llama.cpp runner (`ollama show`: format `gguf`, runner `llamacpp`). Sizes: GGUF 6.6 GB each; MLX 7.6 GB (Qwen) and 9.5 GB (Gemma). Tidepool MLX figures are the native-history runs from the #14 comparison above (same day, same context); rung 1 was run for all four builds against the Radarr queue, which was empty by then.

| Task | Qwen, MLX | Qwen, GGUF | Gemma, MLX | Gemma, GGUF |
|---|---|---|---|---|
| Rung 1 (empty queue) | 3/3, 18s, 3.0 steps | 3/3, 39s, 3.7 | 3/3, 12s, 3.0 | 3/3, 18s, 3.0 |
| Tidepool `easy` | 3/3, 39s, 7.7 | 3/3, 48s, 5.3 | 3/3, 31s, 5.0 | 3/3, 21s, 3.0 |
| `hint` | 3/3, 41s, 8.0 | 2/3, 69s, 9.0 | 3/3, 22s, 4.0 | 3/3, 52s, 6.0 |
| `detail` | 2/3, 63s, 12.0 | 3/3, 99s, 10.3 | 3/3, 34s, 8.0 | 2/3, 76s, 8.7 |
| `paged` | 3/3, 44s, 7.7 | 3/3, 60s, 7.0 | 3/3, 27s, 6.0 | 3/3, 39s, 5.7 |
| Parse errors, all 15 runs | 3 | 13 | 2 | 1 |

Prefill (`tests/prefill_timing.py`, one run per size, tokens read per second):

| Prompt tokens (about) | Qwen, MLX | Qwen, GGUF | Gemma, MLX | Gemma, GGUF |
|---|---|---|---|---|
| 1.9K | 215 | 207 | 627 | 327 |
| 5.8K | 210 | 199 | 616 | 312 |
| 11.4K | 201 | 186 | 598 | 293 |

- Passes are the same within noise: 14 of 15 for both Qwen builds, 15 of 15 (MLX) against 14 of 15 (GGUF) for Gemma.
- MLX is faster. Gemma reads prompts about twice as fast on MLX (about 600 against 310 tokens per second); Qwen reads at nearly the same speed on both (within about 5 to 8 percent), so Qwen's gap (about 5.5 against 8.7 seconds per step on Tidepool) comes from writing the reply, not reading.
- GGUF Qwen made more parse errors (13 against 3), spread across all five tasks.
- So the default MLX tags are the better choice on this Mac; the GGUF builds are smaller (6.6 GB) but slower, with no gain in passes.
- Caveats: 3 runs per cell; the MLX Tidepool runs were not interleaved with the GGUF ones (a few hours apart); the quantisations differ (`nvfp4` against `Q4_K_M`), so this compares the builds Ollama offers, not the engines alone.

## HTML-to-text in `http_request` (#23, 32K, native history, 3 runs per cell)

Prompt: "What is the latest Python release? Read https://www.python.org/downloads/ to find out." Before the change, `http_request` returned the raw page body (over 49K tokens on the Download Python page, well past the clip limit mid-tag); after, it returns the title and visible text, `<main>` only where the page has one.

| Model | Before (raw HTML) | After (text) |
|---|---|---|
| Qwen 3.5 9B | 0/3, 190s mean, 13.0 steps, 49884 input tokens, 3+1+1 parse errors | 3/3, 23s mean, 2.0 steps, 8567 input tokens, 0 parse errors |
| Gemma 4 E4B | 0/3, 108s mean, 6.7 steps, 23468 input tokens, 0 parse errors | 3/3, 40s mean, 3.7 steps, 16284 input tokens, 1+0+1 parse errors |

- Before: both models failed every run. Qwen hit the step cap each time, burning most of a 32K context on one clipped, still-tag-laden HTML response and retrying `http_request`/`run_shell`/`openapi_search` without ever finding the version number in the markup. Gemma did not hit the cap but gave up, telling the user it could not parse the HTML and had no web-search tool.
- After: both models pass every run, in 2 to 4 steps, reading the version number straight out of the converted text (`Python 3.15.1`).
- Caveat: one task, one page, 3 runs per cell; the page happens to have a `<main>` element, which is the easy case for the extractor.

## Prefill cost on this Mac (`tests/prefill_timing.py`)

Time to read a prompt of random words (one output token requested), 32K context, no prompt-cache help:

| Prompt tokens (about) | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| 2K | 8.4s (228 tok/s) | 3.1s (596 tok/s) |
| 6K | 25.8s (225 tok/s) | 9.3s (613 tok/s) |
| 11K | 54.2s (211 tok/s) | 18.8s (596 tok/s) |
| 23K | 114s (201 tok/s) | 41s (548 tok/s) |

Reading OpenClaw's roughly 24K-token prompt would take about 2 minutes per call on Qwen and about 45 seconds on Gemma, and its task needed 3 model turns, so roughly 6 minutes and 2 minutes of prefill alone without caching. SmolPaw's first call at the time (roughly 3K tokens) cost about 13s and 5s; the current one is larger, see "First-call prompt size" below. Caveat: the test used unique prompts, so no cache could help; a stable prefix is much cheaper (next section). Memory use was not measured.

The table above is LM Studio. A two-size check of Qwen on Ollama (`qwen3.5:9b`, MLX `nvfp4`, 32K context, one run each) gave 8.9s at 1,911 tokens (215 tok/s) and 27.4s at 5,810 tokens (212 tok/s), close to LM Studio's 228 and 225 tok/s for the same prompts. Gemma and the larger sizes were not run on Ollama.

## Prompt-prefix caching (#29, `tests/prefix_cache.py`, 32K context, both runtimes, 2026-10-25)

Does the runtime skip re-reading the start of a prompt that has not changed? Random-word prompts of a fixed size, one output token asked for, three repeats each with a fresh prefix. Medians; `cold` is the first call with a prefix, `warm` and `warm2` the same prefix with a different ending, `changed start` the same body with a different first line (what a timestamp at the top of the prompt does).

| Runtime and model | Prompt tokens | cold | warm | warm2 | changed start |
|---|---|---|---|---|---|
| LM Studio, Qwen 3.5 9B | 2,921 | 13.5s | 0.7s | 0.7s | 13.4s |
| LM Studio, Qwen 3.5 9B | 11,500 | 54.0s | 1.7s | 1.6s | 53.9s |
| LM Studio, Gemma 4 E4B | 2,850 | 4.5s | 0.6s | 0.6s | 4.7s |
| LM Studio, Gemma 4 E4B | 11,203 | 19.3s | 0.6s | 0.5s | 19.2s |
| Ollama, Qwen 3.5 9B | 2,921 | 13.5s | 13.6s | 0.4s | 13.6s |
| Ollama, Qwen 3.5 9B | 11,500 | 57.1s | 17.2s | 0.5s | 57.3s |
| Ollama, Gemma 4 E4B | 2,850 | 4.5s | 4.5s | 0.2s | 4.5s |
| Ollama, Gemma 4 E4B | 11,203 | 18.7s | 5.3s | 0.2s | 19.0s |

- **A stable start is almost free to re-read, a changed first line is not.** Where the cache works, the repeat costs 0.2 to 1.7s whatever the prompt size. Changing the first line gave the cold time in all 8 rows: the whole prompt was read again.
- **LM Studio reuses the prefix from the second call.** Ollama does not: its first repeat reused nothing for the 3K prompts and only the first 8,192 tokens for the 11K ones (its `usage.prompt_tokens_details.cached_tokens` says so: 0 to 10 and 8,191 to 8,192). The second repeat reused nearly everything (2,760 to 2,884 of about 2,850, and 11,134 to 11,504 of about 11,200 to 11,500). Why Ollama waits a call was not investigated. LM Studio does not report cached tokens, so its reuse is inferred from the time.
- **A 5-step series that grows the prompt by about 300 tokens a step**, as an agent's history does, summed over the 5 steps: stable start against first line changed every step:

| Runtime and model | 3K start, stable | 3K start, changed each step | 12K start, stable | 12K start, changed each step |
|---|---|---|---|---|
| LM Studio, Qwen | 22.3s | 79.7s | 62.6s | 281.1s |
| LM Studio, Gemma | 7.5s | 28.6s | 23.5s | 101.5s |
| Ollama, Qwen | 38.3s | 89.1s | 94.8s | 333.6s |
| Ollama, Gemma | 12.6s | 27.4s | 27.9s | 98.5s |

  On Ollama the stable series pays for steps 1 and 2 (the cache fills) and is then fast; on LM Studio only step 1 is slow.

**The real agent** (Tidepool `hint`, 3 runs per cell, native history, the actual prompt and tool schemas). Step times include writing the answer, so they are only a ceiling on reading time. The last column is the time to read every step's whole prompt with no cache at all, at the cold speed measured above, so it is a lower bound on a cacheless run:

| Runtime and model | Passed | Mean run time | Mean steps | Time just to read every prompt cold |
|---|---|---|---|---|
| LM Studio, Qwen 3.5 9B | 3 of 3 | 39.0s | 4.7 | 94.3s |
| Ollama, Qwen 3.5 9B | 3 of 3 | 45.0s | 5.7 | 115.2s |
| Ollama, Gemma 4 E4B | 3 of 3 | 32.2s | 5.0 | 32.1s |
| LM Studio, Gemma 4 E4B | 2 of 3 | 159.2s | 6.7 | 44.2s |

- **Qwen: the cache is clearly working in the real agent.** A whole run took less time than reading its prompts cold would have taken alone, at least 2.4 times faster on LM Studio (94.3s against 39.0s) and at least 2.6 times on Ollama (115.2s against 45.0s). The first step of runs 2 and 3 (about 4,100 tokens, 7 to 8s against about 19s cold) also benefited, so the fixed start (instructions, notes, skills, tool schemas) is reused across runs.
- **Gemma: not conclusive.** Its prompts are cheap to read (about 6s cold), so generation dominates the step times and they cannot show a saving. LM Studio's Gemma run 3 failed after 11 steps with outputs of 360 to 1,187 tokens; that is unrelated to caching.
- **Does the prompt order need changing? No.** `build_instructions()` has nothing that changes between calls (no date or time), the tool schemas are fixed, and history is appended. The real runs above show the reuse. The rule to keep is that nothing volatile (a timestamp, a run ID, a changing count) goes near the start of the prompt, since a changed first line costs the full read; a test now checks the instructions are identical on repeated calls.

Caveats: one Mac, three repeats per row and three agent runs per cell. Ollama ran with the context its app is set to (32,768), not the 16,384 of the earlier Ollama comparison; LM Studio was loaded at 32,768 to match. Prompts are random words, not real text, and a single request at a time. The agent's `gemma` rows say nothing either way about caching. Memory use was not measured. Raw numbers are in `logs/prefix-cache-*.json` (gitignored); rerun with `tests/prefix_cache.py` (see its docstring).

## What a changed tool block or edited history costs to re-read (#69, #73, `tests/prefix_cache_tools.py`, 2026-10-28)

#29 showed a changed first line costs a full re-read. This asks the question tool routing (#69) and snipping old results (#73) depend on: when the tool block shrinks, or an old tool result is shortened, how much of the prompt is read again? The requests are the real ones (SmolPaw's system prompt and 15 tool schemas, isolated notes and skills, as in `tests/first_call_tokens.py`), followed by one tool call with a 3,000-token result of random words and one small tool exchange, so every request ends on a tool result as an agent step does. About 7,000 to 7,500 tokens in all, one output token asked for, 3 repeats per cell, each repeat starting with a fresh first line so nothing is cached. "Subset" is the 6 file tools (what a routed category would send). Medians, seconds; the three repeats agreed within about 1.5s, except Ollama Qwen's slow calls, which ranged from 22 to 33s.

| Condition | Ollama Qwen | Ollama Gemma | LM Studio Qwen | LM Studio Gemma |
|---|---|---|---|---|
| cold (all tools, nothing cached) | 31.7 | 10.6 | 33.7 | 11.4 |
| warm (same prefix, different last exchange) | 25.7 | 10.6 | 6.3 | 0.4 |
| warm2 | 0.6 | 0.2 | 6.3 | 0.4 |
| **subset (tool block shrinks, same history)** | **27.4** | **9.4** | **29.2** | **5.5** |
| subset again | 25.4 | 5.2 | 0.8 | 0.6 |
| subset, third call | 0.6 | 0.2 | 0.8 | 0.6 |
| all tools again (same history as before) | 0.7 | 0.2 | 6.3 | 0.4 |
| **snipped (old result cut to first half plus last quarter)** | **22.3** | **5.4** | **12.4** | **1.7** |
| snipped again | 4.1 | 1.3 | 0.8 | 0.5 |
| snipped, third call | 0.6 | 0.2 | 0.8 | 0.5 |

Ollama also reports tokens read again (prompt tokens minus `cached_tokens`): on the subset call 6,330 of 6,496 tokens on Qwen and 6,185 of 6,185 on Gemma; on the snipped call 5,002 of 6,722 on Qwen and 3,485 of 6,322 on Gemma.

- **Changing the tool block re-reads nearly the whole prompt, history included.** On LM Studio the subset call took 29.2s on Qwen against 0.8s once cached (cold: 33.7s), and 5.5s on Gemma against 0.6s (cold: 11.4s). Ollama read almost every token again. So the tool block is early enough in the prompt that anything after it, including the conversation, is read again.
- **After that the new tool set is as cheap as the old one.** LM Studio from the second call, Ollama from the third, the same warm-up #29 found for any new prefix. Ollama also kept the old full-tool prefix: going back to all tools cost 0.2 to 0.7s. LM Studio Gemma did the same (0.4s). LM Studio Qwen took 6.3s, the same as its plain warm calls here, so that is a trait of Qwen on LM Studio with this prompt, not an effect of the tool change.
- **Editing an old tool result costs a re-read from the edit point onward, not the whole prompt.** LM Studio: 12.4s on Qwen and 1.7s on Gemma against 33.7s and 11.4s cold. Ollama's first snipped call is mixed up with its warm-up (22.3s on Qwen, 5.4s on Gemma); the second call was 4.1s and 1.3s.

What this means for #69: a router that picks a category and then widens the tool set after the first tool call (SmallCode's design, see the note on the issue), or one that switches category between requests of a thread, makes the next call read the whole prompt again. At the cold reading speeds above that is worked out as about 20 to 33s on Qwen and 7 to 12s on Gemma for a 4.4K to 7.4K prompt, against the first-call saving of 5 to 8s and 1.4 to 2.1s (phase 0 note on #69). A router that never widens avoids that cost but cannot recover from a wrong pick except by another full re-read. Either way the routing is a net loss on these models once there is any history, and nothing was built.

What this means for #73: the speed case is weaker than the issue assumed. Old tokens that are already cached cost almost nothing to re-send (0.2 to 0.8s whatever the size), so snipping saves little time on a warm run; it costs one re-read from the edit point, and the saving remains on a cold start and in the context window. This is worked out from the figures above, not measured on a snipping implementation.

Caveats: 3 repeats; the old result is random words (a real file or page might tokenise differently); the prompt is longer than a typical early agent step because of the 3,000-token result; Ollama ran at 32K context and LM Studio at 16K; one output token is requested, so generation and thinking time are not measured; `cached_tokens` is reported by Ollama only, so LM Studio's reuse is inferred from the time; the subset is one hand-picked category, not a trained router.

## Hand-written Radarr tools (baseline, Bonsai + ToolCallingAgent)

| Stage | Result |
|---|---|
| Dry-run, first wording | 1 of 3 final reports correct; two claimed a success that did not happen |
| After explicit dry-run text and instructions | 6 of 6 correct (Gattaca x3, then Moon, Primer, Equilibrium) |
| Real adds | 2 (Gattaca, Moon); both added correctly in Radarr. Gattaca's final answer was bad (four failed final-answer calls); Moon's was clean |

The code agent was unreliable on Bonsai: 1 correct final report in 4 runs. The tool-calling agent was faster and followed a consistent path.

## OpenClaw baseline (DeepSeek v4 flash, 1 run)

Same Radarr queue question through `openclaw agent --json`, fresh session, read-only.

| Metric | Value |
|---|---|
| Answer | Correct (one item, Gattaca, with size, status, client, path) |
| Wall time | 11s (7.9s in the agent) |
| Prompt | about 24K tokens per call; system prompt about 68K characters (skills about 18K, workspace memory truncated from 50K to 20K characters) |
| Work | 3 model turns, 4 `exec` calls (2 failed before it got there) |
| Cost | about $0.0013 (prompt caching made the large prompt cheap) |

For comparison, SmolPaw's first call was about 2.9K tokens at the time (4.1K to 4.4K now, see "First-call prompt size"). A local model would also have to read an OpenClaw-sized prompt on every call; that prefill time has not been measured. I did not see which commands the `exec` calls ran (the audit log is metadata-only).

## Models

| Model | Verdict |
|---|---|
| Gemma 4 E4B (MLX 4-bit, 6.86 GB) | Best so far. Clean structured tool calls. Slow final steps (47 to 70s on PokeAPI), probably from reasoning mode. |
| Qwen 3.5 9B (MLX, 5.98 GB) | Good once the harness fixes were in. Needs the clear tool errors; wanders without them. |
| Ternary Bonsai 8B (MLX, 2.32 GB) | Good at guided execution of a known flow, poor at discovery; invents tools. Candidate for a cheap "execute" tier. |
| Qwen 3.5 9B (Ollama `qwen3.5:9b`, MLX nvfp4, 7.6 GB) | 12 of 15 clean at 16K; weaker than on LM Studio on `detail` (step cap) and once on `paged`. |
| Gemma 4 E4B (Ollama `gemma4:e4b`, MLX nvfp4, 9.5 GB) | 13 of 15 at 16K and 2 to 5 times faster than on LM Studio; both failures on `detail`. Same tool-call copying as under LM Studio ([#14](https://github.com/aurora7795/smolpaw/issues/14)). |
| Qwen 3.5 9B (Ollama `qwen3.5:9b-q4_K_M`, GGUF, 6.6 GB) | 14 of 15 at 32K, same as the MLX build, but slower per step and more parse errors (13 against 3). |
| Gemma 4 E4B (Ollama `gemma4:e4b-it-q4_K_M`, GGUF, 6.6 GB) | 14 of 15 at 32K; reads prompts at about half the MLX build's speed. |
| Nanbeige 4.2 3B OptiQ (MLX, 3.32 GB) | Unusable as loaded: at temperature 0 via the API it emits repeated junk instead of an answer. LM Studio marks it as not trained for tool use. Possible runtime or quant incompatibility (MLX engine 1.13.1); a GGUF build is untested. |

## Corrections

An earlier summary in this project overstated the Radarr wrapper-tool results ("9 of 9" and "11 of 11"). The counts in the table above are the accurate ones.

The first write-up of the Ollama spike called Ollama's default `qwen3.5:9b` and `gemma4:e4b` tags GGUF builds. On this Mac they are MLX builds (`nvfp4`), so the spike compared two MLX runtimes with different quantisations, not MLX against GGUF. The registry serves a GGUF-style manifest to a plain HTTP request for the same tags, so check `ollama show <tag>` (format and runner) after pulling rather than trusting the tag name.

The same write-up said Ollama chose a 32K context from available memory on this Mac. The 32K came from the Ollama app's own Context length setting, which the app passes to its server and which overrides `OLLAMA_CONTEXT_LENGTH` set through `launchctl`.

## Cost of the `web_search` tool schema (#24)

`tests/tool_schema_tokens.py` sends the tool's JSON schema as smolagents renders it to Ollama's `/api/generate` (`raw: true`, one output token) and subtracts the count for an empty prompt. One run per model, read-only:

| Model | Schema tokens |
|---|---|
| Qwen 3.5 9B | 91 |
| Gemma 4 E4B | 92 |

This is the schema alone. The whole first-call prompt with `web_search` enabled was not re-measured, and no task using search was run, so reliability of the default `ddgs` backend is unmeasured ([#44](https://github.com/aurora7795/smolpaw/issues/44)). A live `ddgs` 9.16.1 search returned results, and its exception classes match those `generic_tools.py` imports.

## `list_dir` tool (#46)

Task: "What files and folders are in the folder downloads/? Give the exact total count and the name of every folder." The fixture (`tests/eval.py --listing`) is a generated `downloads/` with 55 entries (4 folders, 51 files) in an isolated temp workspace. A run passes if the final answer contains `55` and all four folder names; it does not check the file names. Ollama, 3 runs per cell, Ollama's server context was 32768 (not the 16384 the eval expects).

| Model | With `list_dir` | Without (`--without-tool list_dir`, shell `ls`) |
|---|---|---|
| Qwen 3.5 9B | 3/3, mean 23s, 2.7 steps, 13.0K input tokens | 2/3, mean 58s, 4.0 steps, 21.6K input tokens |
| Gemma 4 E4B | 3/3, mean 10s, 2.3 steps, 10.5K input tokens | 2/3, mean 34s, 3.3 steps, 14.4K input tokens |

Without the tool, the failures were a miscount (Qwen: "50 files + 4 folders = 54") and a run that ended by saying the listing was "in the previous response" (Gemma). With the tool, every run called `list_dir` once and copied the harness's count. Samples are small (3 per cell) and the check covers the count and folder names only, not sizes, which the original exploratory failure also got wrong. Schema cost (`tests/tool_schema_tokens.py`, one run each): Qwen 3.5 9B 108 tokens, Gemma 4 E4B 110.

## Rung 5: write a skill, then reuse it (#4)

`tests/skill_reuse.py`: Tidepool `detail` (the vessel list has no capacity; each vessel must be fetched), an isolated empty skills folder per trial, Ollama with a server context of 32768, 3 trials per model per condition. Each trial: a discovery run, then the same prompt in a fresh agent. Only skill writes are approved. A skill counts as good if it was written, contains no secrets, does not copy the answer (Kestrel, 340) and names the API path.

**Without being asked** (the standing line in the system prompt only: "When a task teaches you something reusable, save a short skill"): 0 of 6 skills written, 3 trials per model. Neither model ever called `write_skill`; they went straight to `final_answer`. Because no skill existed, the 12 runs in this condition double as a no-skill baseline: Qwen 3.5 9B 5/6 passed, 10.5 steps, 50.2K input tokens, 64s mean; Gemma 4 E4B 5/6 passed, 8.7 steps, 37.5K input tokens, 47s.

**With a sentence added to the discovery prompt** asking for a skill ("save a short skill with write_skill ... so next time it is quicker"):

| Model | Skills written, good | Discovery run (writes the skill) | Reuse run (skill loaded) |
|---|---|---|---|
| Qwen 3.5 9B | 3/3, 2 good (one copied the answer into the skill) | 3/3, 11.7 steps, 57.3K tokens, 62s | 3/3, 7.0 steps, 33.3K tokens, 43s |
| Gemma 4 E4B | 3/3, 3 good | 3/3, 10.3 steps, 46.7K tokens, 62s | 3/3, 7.3 steps, 32.0K tokens, 34s |

Against the no-skill baseline above, reuse took about a third fewer steps and tokens on Qwen (7.0 against 10.5 steps, 33.3K against 50.2K tokens) and about 15 percent fewer on Gemma (7.3 against 8.7 steps, 32.0K against 37.5K tokens). The skills were short (343 to 546 characters) and described the two-step lookup (list, then fetch each vessel for `hold_tons`). Every skill passed the secrets check, but Tidepool has no key, so that check could not catch a model pasting one; only the redaction on write backs it up.

Not writing a skill unprompted is tracked in [#48](https://github.com/aurora7795/smolpaw/issues/48).

Caveats: 3 trials per cell; one task on one invented API; the baseline comes from a different set of runs (the unasked condition), not interleaved; the discovery runs include the extra prompt sentence and the write step, so they are not a clean baseline; the reuse comparison starts from a skill the same model wrote moments earlier.

## Cost of model-written run summaries (#47)

`tests/summary_cost.py`: the easy Tidepool task in an isolated workspace, Ollama with a server context of 32768, 3 trials per model. Each trial runs the task once to warm up, then (a) a run straight after a finished run, "off"; (b) a run started while the previous answer's summary is being written on the same loaded model, "on". The summary uses `web.call_summary_model`, the same call the web page makes.

| Model | Summary call | Next run, off | Next run, on |
|---|---|---|---|
| Qwen 3.5 9B, first version (default call) | 161s mean (103, 114, 267), 85 in / 4,558 out tokens | 22.5s, 4.0 steps | 178.0s, 3.3 steps |
| Gemma 4 E4B, first version | 5.3s, 98 in / 358 out | 13.6s, 3.3 steps | 18.9s, 3.0 steps |
| Qwen 3.5 9B, thinking off and 80 tokens max | 1.2s, 84 in / 20 out | 26.2s, 5.0 steps | 33.2s, 6.0 steps |
| Gemma 4 E4B, thinking off and 80 tokens max | 0.4s, 93 in / 15 out | 16.3s, 3.3 steps | 21.1s, 4.0 steps |

A thinking model spent thousands of hidden tokens on a one-line summary, and the next request waited behind it for the whole time (Qwen 22s to 178s). Sending `reasoning_effort: "none"` and `max_tokens: 80` fixed that: the summary takes about a second. The "on" runs after the fix are slower on average, but they also took more steps (Qwen 6.0 against 5.0, Gemma 4.0 against 3.3); per step the two conditions are close (Qwen 5.5s against 5.2s, Gemma 5.3s against 4.9s), and individual runs ranged from 3 to 8 steps, so the difference is within run-to-run noise at 3 trials. All 12 task runs passed, and every summary was a correct one-line statement of the answer.

Caveats: 3 trials per cell; the summary's quality was only read by eye on one simple task (the task answers were all "Kestrel, 340"), not scored; the call was timed against Ollama only. `reasoning_effort` is retried without if a server rejects it, which was not tried against LM Studio, where a thinking model could still be slow.

## First-call prompt size (`tests/first_call_tokens.py`, 2026-10-26)

The tokens of the first model call for the request "hello", counted by Ollama (`usage.prompt_tokens`, `max_tokens=1`) on the exact messages and tool list the agent would send: smolagents' system prompt, SmolPaw's guidance, the one committed skill (`api-discovery.md`), an empty `notes.md`, and 14 tools plus smolagents' `final_answer`. Ollama, 32768 context, 3 runs per figure, identical every time. The script builds the agent in an isolated notes/skills setup, so your own notes, memory and skills do not change the figure; a real `notes.md` adds its own length.

| Model | Whole first call | Instructions alone (no tools) | Tool schemas (difference) | Whole call without `web_search` | `web_search` cost in the prompt |
|---|---|---|---|---|---|
| Qwen 3.5 9B | 4,407 | 2,677 | 1,730 | 4,242 | 165 |
| Gemma 4 E4B | 4,085 | 2,737 | 1,348 | 3,931 | 154 |

- The earlier figure of 2.2K to 2.9K is from before `fetch_page`, `remember`, `recall`, `list_dir` and `web_search` were added; it was not recorded with a script, so how much of the growth each tool caused is not known from it. Today the instructions alone are about 2.7K and the tool schemas add 1.3K to 1.7K.
- A tool costs about 1.7 times its raw schema count once it is inside the chat template: `web_search`'s schema alone was 91 and 92 tokens (above), but removing it from the prompt saves 165 and 154. Estimates of a future tool's cost from its raw schema should be scaled up by about that much.
- This confirms the +165 and +154 first-call figures an outside report gave for `web_search` (checked here, not taken on trust).
- Other tools' individual in-prompt costs were not measured, only the whole and the `web_search` difference. Reading time at this size is worked out from the speeds in the prefill table above (about 20s on Qwen, about 7s on Gemma, cold), not timed. OpenClaw's 24K figure comes from one run on a different tokenizer, so the ratio is approximate.



## Compact system prompt (#125, 2026-11-16)

smolagents' tool-calling prompt prints every tool as text ("You only have access to these tools: ...", about 6.8K characters) and carries notional examples (an image generator, a document question tool, Guangzhou against Shanghai) and instructions to write `Action: {...}` blobs. SmolPaw also sends the same tools as native schemas, so each tool reached the model twice. This is the likely reason a tool cost about 1.7 times its raw schema in the section above (not tested separately). The compact style (`SMOLPAW_SYSTEM_PROMPT=compact`, `agent.py`) keeps SmolPaw's own instructions and smolagents' four rules and drops the rest.

**Pass criterion, stated before the run:** first-call tokens down at least 25 percent, and neither Gemma 4 E4B nor Qwen 3.5 9B worse beyond noise on any task family (CLAUDE.md section 6).

**First call** (`tests/first_call_tokens.py`, Ollama, 32K context, 1 run per figure):

| Model | Default prompt | Compact prompt | Change |
|---|---|---|---|
| Qwen 3.5 9B | 4,855 | 2,693 | -44.5% |
| Gemma 4 E4B | 4,524 | 2,330 | -48.5% |

**Pass counts** (`tests/eval.py --system-prompt default|compact`, Ollama, 32K context, native history, interleaved by task; n=3 per cell, hard fake-Radarr n=6; passes over runs, default then compact):

| Family | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| Tidepool, 4 variants | 12/12, 10/12 | 10/12, 9/12 |
| Housekeeping, 8 chores | 13/24, 13/24 | 15/24, 13/24 |
| Tracking, 3 cases | 6/9, 8/9 | 7/9, 4/9 |
| Read-only scheduled, 5 cases | 3/15, 5/15 | 11/15, 11/15 |
| Hard fake-Radarr (#119) | 3/6, 4/6 | 4/6, 3/6 |
| Total | 37/66, 40/66 | 47/66, 40/66 |

Per run, over the n=3 cells weighted by run count (66 runs per model and arm): input tokens fell 48 percent on Qwen (39.6K to 20.4K; by family -36 to -53 percent) and 34 percent on Gemma (27.3K to 18.1K; -21 to -42 percent). Mean seconds per run fell 23 percent on Qwen (62.5s to 48.0s; faster in four of five families, 8 percent slower on the hard fake-Radarr task) and 8 percent on Gemma (51.5s to 47.4s; faster by 14 to 34 percent on Tidepool, housekeeping and tracking, but 60 percent slower on the read-only cases and 37 percent slower on the hard fake-Radarr task, with 44 and 26 percent more steps there). Mean steps per run: Qwen 6.7 to 5.8, Gemma 5.3 to 6.1. The Gemma time figure is within the run-to-run spread seen above, so it is not a demonstrated speed-up; Qwen's is larger but also one session. An earlier version of this section said input tokens fell 40 to 55 percent in every family; that was wrong for Gemma.

**Follow-up at n=10.** Gemma's totals looked worse (47 against 40 of 66, p about 0.2 by a two-sided look; not established), driven by tracking and Tidepool `easy`. I then reran those cells at n=10, with the rule fixed before seeing them (a regression is a one-sided Fisher exact p below 0.1 with the default better, on a pooled family per model). That rule was written after the n=3 results, so it describes a follow-up and is not the original gate.

| Cell | Default | Compact | p (default better) |
|---|---|---|---|
| Gemma, tracking (3 cases pooled, 30 runs) | 16/30 | 13/30 | 0.30 |
| Gemma, Tidepool `easy` | 6/10 | 7/10 | 0.83 |
| Gemma, Tidepool `paged` | 10/10 | 8/10 | 0.24 |
| Qwen, Tidepool `paged` | 8/10 | 10/10 | 0.99 |

No cell met the rule. Gemma's `easy` result had been 3/3 against 1/3 at n=3 and came out the other way at n=10, which shows how much of the n=3 spread is noise. Gemma's tracking runs were slower with the compact prompt (mean 68s against 41s), unexplained.

**Verdict.** The size criterion is met and no regression was found, so compact is the default. Ten runs per arm cannot show a real drop of 10 to 20 points, so this is "no regression found", not "no regression". The budget in `tests/prompt_budget.json` was lowered from 5,000 to 3,000 tokens.

Caveats: one session, one machine, Ollama only (LM Studio was not rerun); the default arm's housekeeping and tracking cells vary a lot from run to run (Gemma's `read_three_report` was 0/10 on both arms); the stall counts differ by arm in small ways (Gemma Tidepool 0 against 3 at n=3, then 0 against 2 at n=10 `paged`) that were not explained.

Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --ctx 32768 --system-prompt default --tracking all --n 10 --label sp10-default`, then the same with `--system-prompt compact`, and the same with `qwen3.5:9b` and the other task flags. `tests/test_prompt_budget.py` checks the compact prompt has no second tool list and no notional examples.

## Compact system prompt on LM Studio (#131, 2026-11-17)

The #125 matrix ran on Ollama only. This reruns the cells that mattered on LM Studio (MLX builds, 32K context, one slot, native history), interleaved default then compact per cell, n=5 per cell: Tidepool `easy` and `paged`, tracking (3 cases), and the hard fake-Radarr task (#119). One session, one machine.

**Pass criterion, stated before the run:** neither model worse beyond noise, meaning no one-sided Fisher exact p below 0.1 with the default better, on a pooled family per model. If it failed, the style would become a per-backend setting.

Passes over runs, default then compact (`tests/compare_runs.py`; p is for "default better"):

| Family | Gemma 4 E4B | p | Qwen 3.5 9B | p |
|---|---|---|---|---|
| Tidepool, easy + paged | 9/10, 8/10 | 0.50 | 8/10, 10/10 | 1.00 |
| Tracking, 3 cases | 5/15, 2/15 | 0.195 | 3/15, 13/15 | 1.00 |
| Hard fake-Radarr | 2/5, 1/5 | 0.50 | 3/5, 4/5 | 0.92 |
| Total | 16/30, 11/30 | 0.15 | 14/30, 27/30 | 1.00 |

Per run over all 30 runs per model and arm: input tokens fell 16 percent on Gemma (33.3K to 27.9K) and 59 percent on Qwen (69.3K to 28.2K). Median seconds per run: Gemma 125s to 170s (slower), Qwen 104s to 54s (faster). Mean steps: Gemma 6.0 to 7.5, Qwen 10.1 to 7.0. Stalled runs: Gemma 2 to 5, Qwen 3 to 0. One Qwen run (Tidepool `paged`, default arm) took 3,152s against 44 to 116s for the other four, a runaway generation with no wall-clock cap; it fails the run and is left in the pass counts, and it is the reason medians are reported instead of means.

**Verdict.** The criterion is met: no family had the default better at p below 0.1, so the style stays compact on LM Studio and is not made a per-backend setting. Qwen is clearly better with the compact prompt here (13/15 against 3/15 on tracking; the default arm stalled in 3 of its runs, which the Ollama default arm did not at this rate). Gemma is not shown worse, but it leans that way in the same direction as on Ollama (tracking 5/15 against 2/15 here, 16/30 against 13/30 there), with more stalls and slower runs under the compact prompt; at n=15 per family a real drop of 20 points cannot be excluded. That is "no regression found by the rule", not "no regression", and #130 stays open with this data.

Caveats: n=5 per cell; interleaved but run once; the first-call token count was not taken on LM Studio (`tests/first_call_tokens.py` reads Ollama's usage figure only), so the token change above is the per-run input tokens from the logs; the hard fake-Radarr cells have n=5.

Reproduce: `.venv/bin/python tests/eval.py --backend lmstudio --model google/gemma-4-e4b --ctx 32768 --n 5 --system-prompt default --tidepool easy --label sp131-tidepool-easy-default`, then `compact`, then the other cells (`--tidepool paged`, `--tracking all`, `--fake-radarr --radarr-task hard`) and `--model qwen3.5-9b-mlx`. Compare with `.venv/bin/python tests/compare_runs.py --arm default='logs/eval-*sp131*-default.json' --arm compact='logs/eval-*sp131*-compact.json' --family tracking`.

## Do small models keep track of what they read and write? (#87, 2026-10-29)

`tests/eval.py --tracking all --n 3`, on the fixture in `tests/tracking_fixture.py`: each run gets a fresh isolated workspace, files longer than the 4,000-character read clip, and every fact the task needs beyond that clip. Ollama, 32K context (the app's setting; the script's 16K default only warns), 12-step cap, native history, native MLX builds, 3 runs per cell. Pass means the file on disk equals the expected bytes (edit and append cases) or the answer holds all three figures (read case), and the run did not hit the step cap. Logs: `logs/eval-20261029-*-tracking-*.json` (the last six per model are the ones reported here).

| Case | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|
| `edit_one_section`: change one value in a 12,390-character file, leave the rest | 0/3 | 0/3 |
| `append_keep_all`: add a section to a 6,151-character file, keep the rest | 0/3 | 0/3 |
| `read_three_report`: report one figure from each of three ~6,000-character files | 1/3 | 2/3 |

What the runs show:

- **Writing back a clipped view is the main failure.** In all 3 Gemma `append_keep_all` runs the model called `read_file` once (seeing 4,000 of 6,151 characters; one run first tried a declined shell append), then `write_file` with that view plus the new section, and answered that the section was added. The file lost its last 2,151 characters each time and the answer said nothing about it. The same happened in 1 Qwen append run. Gemma `edit_one_section` run 3 also wrote back with a section missing.
- **Claims of success without a write.** Qwen `edit_one_section` run 3 answered that the sentence "has been updated" (a forced answer after the step cap) with no write made; Gemma run 2 said the file "should now have" the change. Neither model reads the file back to check, and nothing in the harness asks them to.
- **The shell route is slow and fragile.** Qwen hit the 12-step cap in all 6 edit and append runs, mostly on shell attempts, at 80,000 to 106,000 input tokens per run (Gemma's runs that reached `write_file` took 3 to 4 steps and 14,700 to 19,700). `sed -i 's/…/…/' file` failed with exit 1 on this Mac in several runs: BSD `sed` needs `sed -i '' …`.
- **Reading is possible but unreliable.** The 3 passes in `read_three_report` (Gemma 1, Qwen 2) found the figure with `grep`/`cat` pipelines. The 2 Gemma failures reported each file's character count (5,875, 6,298 and 6,093) as the key figure; the Qwen failure hit the step cap and gave a made-up 847 for the first file. Every run in this case had 2 or 3 clipped tool results (`clipped_results`).

Caveats:

- **The result depends on the scripted approvals.** The eval approves `write_file` inside the run's own workspace, a literal `sed -i` replacement on a fixture file, and read-only pipelines (`grep … | head`); it declines every other shell command. Models that tried `cat >> file`, `echo >>`, `python3 -c` or `awk` to write were declined, so a user who approved those would see more passes on the append and edit cases. Two earlier rounds under stricter approvals (first only `write_file`, then also `sed -i`) were discarded after the logs showed the declined commands were correct attempts; their 0/9 and 0/9 results are not comparable and are not reported. The final policy was fixed after seeing logs from earlier rounds, so it is tuned, not neutral.
- 3 runs per cell: one pass in three is a signal, not a rate.
- `read_three_report` checks the answer with unordered regexes for the three figures, so an answer that lists them without matching figures to files would pass.
- Unmeasured here: `edit_file` (#72), the read-before-write guard (#71) and snipping (#73). This run is the baseline for them; the paged `read_file` of #86 is measured below.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --tracking all --n 3`, then the same with `qwen3.5:9b`. `tests/test_eval_tracking.py` checks the runner without a model.

### With a paged `read_file` (#86, 2026-10-29)

Same command, models, context and approvals, after `read_file` gained `offset` and a footer (`[characters 0-4000 of 6151; call read_file again with offset=4000 to continue]`). The schema grows from 106 to 153 tokens on Gemma (`tests/tool_schema_tokens.py`, 47 more per call). Logs: `logs/eval-20261029-0840*` to `0904*`.

| Case | Gemma 4 E4B before | after | Qwen 3.5 9B before | after |
|---|---|---|---|---|
| `edit_one_section` | 0/3 | 0/3 | 0/3 | 0/3 |
| `append_keep_all` | 0/3 | 1/3 | 0/3 | 0/3 |
| `read_three_report` | 1/3 | 0/3 | 2/3 | 3/3 |

- **The models now page.** Every Gemma and Qwen edit and append run that reached a write called `read_file` two to four times, so the footer is being used. The one new edit/append pass was Gemma append run 3 (prefix intact, section once).
- **Edits still fail, for a different reason.** The checker no longer reports a clipped view for Gemma edits, but all 3 runs wrote a file that differed from the expected bytes (run 3 also lost a section heading) while the answer said the change was made. I did not diff what was written, so the cause (retyping the file from several pages) is a likely explanation, not a measured one. Qwen still wrote back about 4,000 characters in 2 of 3 append runs (checker: 4,004 of 6,151) and one run left almost nothing; its edit runs hit the 12-step cap twice, at up to 119,000 input tokens.
- **Reading moved in opposite directions.** Qwen went from 2/3 to 3/3; Gemma from 1/3 to 0/3, where its answers said a file had no key figure or gave 1 for refuge_inventory. With 3 runs per cell neither move is distinguishable from noise.
- **Total:** edit and append 1 of 12 (before 0 of 12); reading 3 of 6 (before 3 of 6). Paging alone does not make these models safe to write long files: they must still reproduce the whole file in one `write_file`. That is what `edit_file` (#72) and the read-before-write guard (#71) target.

### With `edit_file` as well (#72, 2026-10-29)

Same command, models, context and approvals, with the paged `read_file` and the new `edit_file(path, old, new)` in the toolset (replace one passage that appears once; asks first, showing `- old` / `+ new`; workspace and skills only). Its schema is 176 tokens on Gemma (`tests/tool_schema_tokens.py`), on top of the 47 for paging. The earlier tables are the baseline: the same runs with `--without-tool edit_file` would be the clean comparison, and I used the paged-only runs above instead. Logs: `logs/eval-20261029-09*` (the six from 093835 on).

| Case | Gemma 4 E4B: write_file, paged, +edit_file | Qwen 3.5 9B: write_file, paged, +edit_file |
|---|---|---|
| `edit_one_section` | 0/3, 0/3, **3/3** | 0/3, 0/3, **2/3** |
| `append_keep_all` | 0/3, 1/3, **3/3** | 0/3, 0/3, **2/3** |
| `read_three_report` | 1/3, 0/3, 0/3 | 2/3, 3/3, 2/3 |

- **Edits and appends went from 1 of 12 to 10 of 12.** Gemma's three edit passes took 2, 2 and 6 steps (9,200 to 34,400 input tokens), against 6 to 9 steps and 37,000 to 42,000 for its failed `write_file` runs. Two of those runs called `edit_file` as the first action with the passage copied from the task prompt, and the check confirmed the file held exactly the one changed line.
- **Appending worked in new ways.** Gemma's appends passed after paging through the file and then writing it back whole (2 runs) or calling `edit_file` first and then `write_file` (1 run). Qwen run 3 appended by replacing the last line with itself plus the new section through `edit_file`, which the checker accepted as byte-exact.
- **Remaining failures.** Qwen edit run 3 made a correct edit but kept going with shell commands and hit the 12-step cap (counted as a fail, the file was right). Qwen append run 1 still wrote back about 4,000 characters of a 6,151-character file and said everything was kept. The reading case is not an `edit_file` task: Qwen 2 of 3 (one step-capped), and Gemma again 0 of 3, each answer reporting no figure for `refuge_inventory.txt`. Gemma has now scored 1, 0 and 0 on reading across the three configurations; I have not examined why, so whether paging hurt it is open.
- **Caveats.** 3 runs per cell. The approver now also approves `edit_file` inside the run's workspace, as the user would be shown the exact passages. The baseline is not a same-session `--without-tool edit_file` run; the earlier paged-only runs were used. Models see `edit_file` only through its schema and docstring (the agent prompt did not change). Not tested: an `old` that matches twice or not at all in a model run (the tool refuses both, covered by unit tests), and files larger than the fixtures.

### Five harder edit cases, with and without `edit_file` (#72, 2026-10-29)

`--tracking edit --n 3` runs the five cases added to `tests/tracking_fixture.py` (built by antigravity, reviewed here), once with the toolset as it is and once with `--without-tool edit_file`, in the same session on each model: Ollama, 32K context, native history, same scripted approvals as above (`write_file` and `edit_file` inside the run's workspace, literal `sed -i`, read-only pipelines; everything else declined). Pass means the file on disk equals the expected bytes and the run did not hit the 12-step cap. Logs: `logs/eval-20261029-*tracking-edit_*-with-edit-file.json` and `-without-edit-file.json`.

| Case | Gemma 4 E4B with / without | Qwen 3.5 9B with / without |
|---|---|---|
| `edit_duplicate_passage`: the same sentence in Sections Beta and Epsilon, change only Epsilon's | 0/3, 0/3 | 0/3, 0/3 |
| `edit_last_line`: change the last line, keep the final newline | 3/3, 0/3 | 3/3, 0/3 |
| `edit_special_chars`: replacement containing `&`, `\`, `$1` and a quote | 3/3, 0/3 | 3/3, 0/3 |
| `edit_across_clip`: the sentence straddles character 4,000 | 3/3, 0/3 | 3/3, 0/3 |
| `edit_crlf`: a CRLF file, change one line, keep every line ending | 3/3, 0/3 | 3/3, 0/3 |
| **Total** | **12/15, 0/15** | **12/15, 0/15** |

Mean steps and input tokens, passing four cases (with `edit_file`, then without): Gemma 2.0 to 3.0 steps and 9,200 to 15,100 tokens against 7.7 to 10.7 steps and 42,300 to 59,300; Qwen 4.3 to 6.3 steps and 25,700 to 39,900 tokens against 7.0 to 13.0 steps and 49,300 to 110,000.

What the runs show:

- **Without `edit_file`, none of 30 runs passed.** Eleven never changed the file (seven of those hit the step cap, mostly on declined shell attempts), 4 of the 6 CRLF runs rewrote the file with LF line endings, and the rest changed the wrong text, dropped content, or lost the final newline.
- **With it, the four single-passage cases passed all 24 runs**, in a few steps. The CRLF line endings, the quote and backslash characters, and the passage across the 4,000-character page boundary came through unchanged because the tool replaces bytes in place.
- **The duplicate-passage case failed on both models, with and without the tool.** `edit_file` refuses an `old` that appears twice, which is correct, but the models did not recover reliably. Gemma edited the wrong copy (Section Beta) in 2 of 3 runs and answered that the change was made; in the third it stopped and said it could not be done in Epsilon. Qwen edited correctly in 2 of 3 runs but kept re-reading and running shell commands until the step cap (so these count as fails, though the files were right), and in the third changed the file in unexpected ways. I did not look at the exact `old` strings the models sent, so why Gemma picked Beta is not established.
- **Gemma's wrong-copy edits came with a success message.** The checker, not the model, caught it. This is the same pattern as the long-file rewrites: no read-back, no doubt.

Caveats: 3 runs per cell; synthetic generated files; the approval policy is scripted (it approves what a user shown the `- old` / `+ new` passages would approve); the "without" runs still had `write_file`, `sed -i` and read-only shell, so this compares the toolset with and without `edit_file`, not editing methods in general; the idea of a replace-one-passage tool was reinforced by SmallCode's docs (issue #72), whose claims were not re-checked here, so the evidence in this section is our own runs only. Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --tracking edit --n 3 --label with-edit-file`, then again with `--without-tool edit_file --label without-edit-file`, then the same with `qwen3.5:9b`.

### Repeated passage, with the match places in the error (#88, 2026-10-29)

The logs of the failed `edit_duplicate_passage` runs showed why Gemma edited the wrong copy: `edit_file` refused the first call (the sentence appears twice), the model re-read the file from the start, saw only the first copy (Section Beta, before character 4,000), and sent Beta's surrounding text, which matched uniquely. Section Epsilon's copy is at character 8,266, on the third page. The error said only that `old` appears twice. It now lists each match by character (the offset `read_file` takes) and the heading above it, for example `Matches: at character 2789 under '## Section Beta'; at character 8266 under '## Section Epsilon'.` The text appears only when the error fires, so the prompt is unchanged. Same command, models and approvals as above, `--tracking edit_duplicate_passage --n 3 --label with-match-places`.

| | Before | After |
|---|---|---|
| Gemma 4 E4B: passed | 0/3 | 1/3 |
| Gemma: edited the wrong copy | 2/3 | 0/3 |
| Qwen 3.5 9B: passed | 0/3 | 0/3 |
| Qwen: file correct at the end | 2/3 | 3/3 |

- **The wrong-copy edits are gone** (2 of 6 runs before, 0 of 6 after), and the final file was correct in 4 of 6 runs (2 before). That is the change the message was meant to make.
- **The pass rate barely moved because of the step cap.** All three Qwen files ended up right, but each run kept re-reading the file and running shell commands after the edit, reached 13 steps and counts as a fail. Two Gemma runs also hit the cap without changing the file, repeating `edit_file` calls. Gemma's one pass took 11 steps.
- 3 runs per cell. I did not read what `old` strings the Gemma runs that hit the cap sent. The Qwen over-checking after a correct edit is also what happened in `edit_one_section` run 3 earlier today; stopping a run that makes no progress is #77.

### Repeated passage, with a ready old and new text per match (#88, 2026-10-30)

With the arguments now logged, the failed Gemma runs of the match-places version (`logs/eval-20261030-182128-ollama-gemma4_e4b-tracking-edit_duplicate_passage-base-args.json`, 1/3) show the next step: the model sent the same repeated `old` again, or put the sentence before it in front ("Granite cache ... sedge. The maximum ..."), which is also repeated in both sections, so it still matched twice. The error now also gives, for each match, an `old` that matches only there (the passage plus the fewest words before it, else after it, that occur once, searched within 400 characters) and the `new` with the same words added, each between `<<<` and `>>>` marks. Nothing is added unless the error fires, so the prompt is unchanged. Two first versions of this had faults the logs showed: printing the text with `repr` made Gemma copy a literal backslash-n (1/3, `unique-old`), and offering only `old` made it send a `new` without the extra words, deleting them (1/3, `unique-old-lines`, 6.7 steps). The third version (`old-and-new`) is the one in the table. Ollama, 32K, native history, `--tracking edit_duplicate_passage --n 5`; logs `logs/eval-20261030-184003-ollama-gemma4_e4b-...-old-and-new.json` and `logs/eval-20261030-185148-ollama-qwen3.5_9b-...-old-and-new.json`.

| | Before (match places only) | After (old and new offered) |
|---|---|---|
| Gemma 4 E4B: passed | 1/3 (and 1/3 in today's repeat) | **5/5**, 3.4 steps, 16,394 input tokens, 19s |
| Qwen 3.5 9B: passed | 0/3 | **2/5**, 10.2 steps, 84,583 input tokens, 139s |
| Qwen: file correct at the end | 3/3 | 4/5 |

- **Gemma now recovers every time** in 3 to 4 steps, against 10 to 13 before. The input tokens fell from about 65,000 to 16,000 per run.
- **Qwen improved but still hits the step cap.** Two runs passed in 6 steps. Of the three failures, two ended with the right file but reached 13 steps re-reading (the over-checking noted before, #77), and one never changed the file. Its files were correct in 4 of 5 runs.
- **Caveats.** n=5 (n=3 before); one fixture where the repeated sentence's neighbours are also repeated, so the unique text came from the words before the sentence; other layouts (the copies differ only after the passage, or are further apart than 400 characters) were tested only by unit tests; the Qwen baseline is the earlier 3-run batch. The reach limit means very long repeated blocks still get only the places.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --tracking edit_duplicate_passage --n 5`, then the same with `qwen3.5:9b`. `tests/test_generic_tools.py` checks the offered pair without a model.

### Repeated passage, re-measured on main (#88, 2026-11-17)

A check that the 2026-10-30 figures hold on current `main` (the #77 repeated-results stall rule is now in). Pass criterion, stated before the run: no change to `edit_file`; record whether the earlier 5/5 and 2/5 hold. Ollama, 32K, step cap 12, `--tracking edit_duplicate_passage --n 5 --label m88-n5`; logs `logs/eval-20261117-220634-ollama-gemma4_e4b-...-m88-n5.json` and `logs/eval-20261117-220255-ollama-qwen3.5_9b-...-m88-n5.json`.

| | 2026-10-30 | 2026-11-17 |
|---|---|---|
| Gemma 4 E4B: passed | 5/5, 3.4 steps | **4/5**, steps 3, 6, 3, 10, 3 |
| Qwen 3.5 9B: passed | 2/5, 10.2 steps | **2/5**, steps 13, 8, 8, 13, 8 (2 capped, 1 stopped by the stall rule) |

- **Gemma's one failure** was the known one: it sent the offered `old` (with "sedge." before the sentence) but a `new` without those words, deleting 8 characters.
- **Qwen's three failures:** one edited the sentence in both sections; two reached the cap or the stall stop after the edit, re-reading the file two or three more times. The stall rule did not turn those into passes.
- **Caveats.** n=5 per model, one fixture; 4/5 against 5/5 is within noise. No code change was made, so this is a repeat, not a comparison.
- Decision: `edit_file` is left as it is. Qwen's re-checking after a correct edit is not specific to this case; a fix would need its own prompt or tool change through the merge gate.

### A "no need to read the file again" hint in the `edit_file` result (#141, 2026-11-17)

Idea: Qwen often re-reads after a correct edit until the cap or a stall stop, so the success message was ended with "The edit is saved; there is no need to read the file again." Pass criterion, stated before either arm ran: merge if Qwen passes at least 3 more of 25 than its baseline (23/25 or better) or its stalled and capped runs at least halve, and Gemma is not below 23/25. Both arms were run in the same session: Ollama, 32K, step cap 12, `--tracking edit` (five edit cases, n=5 each, so 25 runs per model per arm), labels `h141-base` (main) and `h141-hint`. Logs: `logs/eval-20261117-22*-...-h141-base.json` and `logs/eval-20261117-23*-...-h141-hint.json`.

| 25 runs per cell | Baseline | With the hint |
|---|---|---|
| Qwen 3.5 9B: passed | 21/25 | 21/25 |
| Qwen: stalled runs | 3 | 2 |
| Qwen: mean steps, input tokens | 6.6, 31,379 | 6.0, 27,982 |
| Gemma 4 E4B: passed | 24/25 | 24/25 |
| Gemma: mean steps, input tokens | 2.7, 7,806 | 2.7, 7,897 |

- **No effect.** Qwen's pass count is unchanged (Fisher exact p=0.65), stalled runs went from 3 to 2 (not halved), and Gemma is unchanged (p=0.76). The criterion was not met, so the hint was not merged. On `edit_duplicate_passage` alone Qwen went from 2/5 to 1/5; every other case was unchanged for Qwen.
- **Caveats.** n=5 per case. The Qwen baseline for the repeated-passage case here (2/5) matches the two earlier batches (2/5 on 2026-10-30 and 2026-11-17), so the spread is smaller than the sample suggests, but five runs cannot show an effect of one or two passes. Gemma finishes in 2 to 3 steps, so the hint had little room to act. Only this one wording was tried.
- Qwen's re-checking after a correct edit remains open as #142 (a stall rule after a write).
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --tracking edit --n 5`, then `gemma4:e4b`; the hint arm is the one-sentence change to the final return of `edit_file`.

### `read_three_report` at n=10, with the tool arguments logged (#89, 2026-10-30)

#89 asked whether Gemma's 0/3 on `read_three_report` after paging was noise. Same case, Ollama, 32K context, native history, paged `read_file` with `edit_file` in the toolset, n=10 per model. This time the run logs hold each call's arguments (`tool_args`, added to `tests/eval.py` in this change), so the pages each model asked for can be read back. The three facts sit at characters 4,552, 4,758 and 4,716 of files of 5,875, 6,298 and 6,093 characters, so each is on page 2 (page size 4,000) and a full read takes 6 `read_file` calls. Logs: `logs/eval-20261030-104700-ollama-gemma4_e4b-tracking-read_three_report-n10.json` and `logs/eval-20261030-105708-ollama-qwen3.5_9b-tracking-read_three_report-n10.json`.

| | Passed | Mean steps | Mean input tokens | Read page 2 of all three files |
|---|---|---|---|---|
| Gemma 4 E4B | 0/10 | 6.0 | 36,170 | 0/10 |
| Qwen 3.5 9B | 9/10 | 7.6 | 58,221 | 9/10 |

- **Gemma pages, then stops.** In all 10 runs it read page 1 of all three files. It read page 2 of the hydrology file in 10, of the geology file in 8, and of `refuge_inventory.txt` in none. The answers gave 1485 and often 832 and said `refuge_inventory.txt` had no clear key figure. The paging works; the model does not ask for the last page. The #86 and #72 results (0/3 each) were this, not a broken tool.
- **Qwen reads every page.** 9 of 10 runs read both pages of all three files and passed. The failure (run 4) read page 2 of two files, then used `web_search`, `list_dir` and four shell commands and hit the 13-step cap without the third figure.
- **Cost of the reading.** Qwen used about 22,000 more input tokens per run because it read all six pages.
- **Caveats.** One session, 10 runs per model. Gemma's runs differ only slightly in order (one read geology before the second hydrology page), so the 0/10 comes from one repeated behaviour, not from ten different failures. Not measured: why Gemma stops (the number of calls so far, the footer wording or the model's judgement that it has seen enough); whether a footer that says the rest of the file is unread changes it; the `--without-tool`-style comparison without the `offset` argument that #89 mentioned, which the arguments now make unnecessary for this question.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --tracking read_three_report --n 10 --label n10`, then the same with `qwen3.5:9b`.

### A footer that says how much is unread (#89, 2026-10-30)

Following the n=10 result above, one change to `read_file`'s footer: a page that is not the last now reads `[characters 0-4000 of 6093; 2093 more characters NOT read yet, so this is only part of the file; call read_file again with offset=4000 to continue]`. Same case, Gemma 4 E4B, Ollama, 32K context, n=10. The change was tried in a separate worktree and is not in the code. Log: `logs/eval-20261030-115802-ollama-gemma4_e4b-tracking-read_three_report-footer-unread.json`. I stopped before running Qwen, because the change was not going to be kept.

- **No effect.** 0/10 passed (mean 6.2 steps, 38,198 input tokens), against 0/10 with the old footer. In all 10 runs Gemma read page 1 of `refuge_inventory.txt` and never read page 2, as before. It read page 2 of the hydrology file in 10 runs and of the geology file in 9.
- **What this rules out.** The footer wording is not what stops Gemma: it was told in so many words that part of the file was unread. Not examined: whether a different number of files, a different file order or a "read every page of every file before answering" instruction changes it; and why page 2 is skipped only for the last file.

### A larger `read_file` page (#89, 2026-10-30)

Does a bigger page fix Gemma's 0/10? The page size was made a knob (`SMOLPAW_MAX_OUT`, 4,000 by default; the knob is not in the code) and tried on two fixtures, Ollama, 32K context, n=10 per cell. `read_three_report` has its facts at characters 4,552 to 4,758. `read_three_long` (new, `--tracking read_three_long`) pads the same three files to about 11K characters, with the facts at characters 9,507 to 9,732, so a 6,000 page still needs a second read and an 8,000 page puts them on page 2 as well.

| Case | Page | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|---|
| read_three_report | 4,000 | 0/10 | 9/10 |
| read_three_report | 6,000 | 10/10 | 10/10 |
| read_three_report | 8,000 | 10/10 | 10/10 |
| read_three_long | 4,000 | 0/10 (7.5 steps, 50,788 input tokens) | 7/10 (11.1 steps, 99,159, 3 cap hits) |
| read_three_long | 6,000 | 0/10 (5.6, 38,735) | 10/10 (7.2, 65,281) |
| read_three_long | 8,000 | 0/10 (5.7, 40,881) | 8/10 (8.1, 82,605, 1 cap hit) |

- **Gemma's gain is the fixture.** On `read_three_report` the facts fit on page 1 once the page is 6,000, so nothing needs a second read. On `read_three_long` Gemma fails at every size. Its logs show the same behaviour as before: it reads page 1 and the second page of the first file (offset 6,000 or 8,000), reads only page 1 of the next files and answers that they have no key figure.
- **Qwen's numbers do not follow the page size.** 7/10, 10/10, 8/10 across 4,000, 6,000 and 8,000 is within what ten runs of a model that sometimes hits the step cap can give; no trend is claimed.
- **Decision.** No larger page is adopted. A larger page would also cost more input tokens per read in the read-heavy cases, which were not measured.
- **Caveats.** One session, 10 runs per cell, two fixtures, Ollama only. Logs: `logs/eval-20261030-*-read_three_long-long{4000,6000,8000}.json` and the matching `read_three_report` runs (`--label page6000`/`page8000`).
- Reproduce (with the knob patched in): `SMOLPAW_MAX_OUT=6000 .venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --tracking read_three_long --n 10 --label long6000`.

### Which pages Gemma skips: instruction, order, number of files (#89, 2026-10-30)

One change per cell, Gemma 4 E4B, Ollama, 32K context, native history, paged `read_file` with `edit_file` in the toolset, n=10 per cell, all in one session from a separate worktree. Four new cases in `tests/tracking_fixture.py` (run with `--tracking <case>`): `read_three_every_page` (the base prompt plus " Read every page of every file before answering."), `read_three_reversed` (the same three files named in the opposite order), `read_two_report` (hydrology and refuge only) and `read_four_report` (a fourth file, `canopy_survey.txt`, 6,003 characters with its figure at character 4,683). Two control runs of the base case: `131719` ran with the fourth file in the workspace, `135616` (run after the fixture was changed to build the fourth file only for the four-file variant) without it: 0/10 both, 6.2 steps, 37,828 and 37,865 input tokens. Pass means every named file's figure appears in the answer. Pages come from the logged `tool_args`. Logs: `logs/eval-20261030-13*-ollama-gemma4_e4b-tracking-<case>-n10-variants.json`: `131719` (control), `132426` (every page), `133114` (reversed), `133649` (two files), `134624` (four files).

| Case | Passed | `read_file` calls per run | Page 2 read, per file (runs of 10) | Mean steps | Mean input tokens |
|---|---|---|---|---|---|
| Control, three files | 0/10 | 5 (once 4) | hydrology 10, geology 9, refuge 0 | 6.2 | 37,828 |
| "Read every page of every file" | 0/10 | 4 to 5 | hydrology 10, geology 6, refuge 1 | 5.9 | 35,837 |
| Reversed order (refuge, geology, hydrology) | 0/10 | 4 to 5 | refuge 10, geology 4, hydrology 1 | 5.8 | 35,244 |
| Two files (hydrology, refuge) | 2/10 | 3 (twice 4) | hydrology 10, refuge 2 | 4.6 | 25,687 |
| Four files (adds canopy) | 0/10 | 5 to 6 | hydrology 10, geology 6, refuge 0, canopy 0 | 6.8 | 43,361 |

- **The skipped page follows the order the files are named in, not the file.** Reversed, Gemma read page 2 of the refuge file (now first) in 10 runs and of the hydrology file (now last) in 1; it failed all 10 on the other two figures. It reads page 1 of every file, then spends its follow-up reads on the files named first and stops after roughly 4 to 6 `read_file` calls whichever way the files are ordered. In the control it reads page 2 of the first file always and of the second most of the time.
- **Fewer files help a little; it is not enough.** With two files it asked for the last file's page 2 in 2 of 10 runs and passed those 2; the other 8 reported "no clear key figure" for the refuge file. With four files nothing changed for the last two.
- **Telling it to read every page changed almost nothing.** The refuge file's page 2 was read once in 10 runs (0 in the control) and that run still failed. The answers it gave without the page said the file had no key figure, or returned a section label instead of a number.
- **Not a fixed budget.** The number of calls moved with the number of files (3, 5, 6), so the stop is not a constant step limit; it looks like the model judging it has enough after page 2 of the first one or two files. Not examined: why.
- **Decision.** No change is kept. Neither the footer (earlier section) nor an instruction nor reordering fixes it, and none was worth running on Qwen. What would fix it is making the fact reachable without the follow-up call, for example a larger page size, which changes what every read costs and belongs with the clipping question in #73; it is not built.
- **Caveats.** n=10 per cell, one session, synthetic files with one figure per file. The two-file result (2/10) is small enough that I would not call it better than 0/10 without a rerun. The variant cells ran with the fourth file present in the workspace; only the four-file case names it. Qwen was not run on these variants.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --ctx 32768 --tracking read_three_every_page --n 10` (and `read_three_reversed`, `read_two_report`, `read_four_report`, `read_three_report`).

### A list of other unread files in each read result (#89, 2026-10-30)

The harness nudge chosen after the variants above. Change, tried in a separate worktree and not in the code: each `read_file` result also ended with `[Also still unread from earlier reads: geology_strata.txt from character 4000; ...]`, naming every other file read only in part this run with the offset of its next page (kept in a module-level dict cleared at the start of each run). It touches only the text of a result, not the confirmation layer or the prompt. `read_three_report`, Ollama, 32K context, native history, n=10 per model, same session. Logs: `logs/eval-20261030-141838-ollama-gemma4_e4b-tracking-read_three_report-n10-unread-list.json` and `logs/eval-20261030-142853-ollama-qwen3.5_9b-tracking-read_three_report-n10-unread-list.json`.

| | Passed | `read_file` calls per run | Mean steps | Mean input tokens |
|---|---|---|---|---|
| Gemma 4 E4B | 0/10 | 4 to 6 | 6.2 | 37,895 |
| Qwen 3.5 9B | 9/10 | 6 (once 8) | 6.1 | 46,748 |

- **No effect on Gemma.** Page 2 was read for the hydrology file in 10 runs, the geology file in 8 and `refuge_inventory.txt` in 0, the same as the control (10, 9, 0). It was told in the result of its last read that the refuge file was unread from character 4000 and did not ask for it.
- **Qwen unchanged.** 9/10 as before; all 10 runs read both pages of every file.
- **Decision.** Not kept. Three ways of telling Gemma the text is unread (the footer, an every-page instruction, this list) have all left it at 0/10, so the cause is not missing information. A larger page size remains the untested route.
- **Caveats.** n=10, one session. Qwen's mean input tokens (46,748) are lower than the 58,221 in the first n=10 run, which shows how much one session's runs can differ in tokens; its pass count is the same.

### Snipping old tool results at 8K context (#73, 2026-10-30)

The part of #73 the earlier cache numbers left open: does shortening older tool results help when the context is small? Prototype in `NativeHistoryModel` (`agent.py`), **off by default**, switched on with `SMOLPAW_SNIP=step|batch` (a measurement knob, not a feature): every tool result except the last two and longer than 1,500 characters is cut to its first half plus last quarter with a note in between (a paged read's footer sits in the last quarter and survives). `step` cuts on every call; `batch` waits until the history passes `SMOLPAW_SNIP_AT` estimated tokens (6,000 here, chars/3.5, counting the system prompt) and then cuts all older results at once and keeps the same ones cut. LM Studio, MLX builds (`google/gemma-4-e4b`, `qwen3.5-9b-mlx`), loaded context 8,192, one slot, native history, `--tracking read_three_report`, n=5 per cell, run from a separate worktree. Not Ollama: its context is a server setting, and changing it means changing the app's setting. `read_three_report` is the heavy task (about 6 page reads of about 1,100 tokens each after a 4.4K prompt) and also the harm check: the figures sit in earlier pages. Logs: `logs/eval-20261030-14*` to `16*-lmstudio-*-tracking-read_three_report-8k-snip-{off,step,batch}.json`.

| Model | Mode | Passed | Hit step cap | Parse errors (5 runs) | Mean steps | Mean input tokens | Mean wall (s) | Peak step input |
|---|---|---|---|---|---|---|---|---|
| Gemma 4 E4B | off | 0/5 | 0 | 4 | 6.4 | 39,852 | 154 | 7,879 |
| Gemma 4 E4B | step | 0/5 | 0 | 1 | 5.4 | 31,712 | 136 | 7,439 |
| Gemma 4 E4B | batch | 0/5 | 0 | 1 | 5.2 | 30,269 | 146 | 7,198 |
| Qwen 3.5 9B | off | 1/5 | 4 | 31 | 12.6 | 77,661 | 132 | 7,961 |
| Qwen 3.5 9B | step | 0/5 | 5 | 31 | 13.0 | 76,754 | 257 | 8,160 |
| Qwen 3.5 9B | batch | 0/5 | 5 | 28 | 13.0 | 79,782 | 544 | 8,186 |

- **The baseline fails at 8K, so the test cannot show a pass-rate gain.** Without snipping Gemma passes 0/5 (it passes 0/10 at 32K too, see #89) and Qwen 1/5, against 9/10 for Qwen at 32K. Qwen's runs fill the context (peak step input 7,961 to 8,186 of 8,192), produce 28 to 31 parse errors across the five runs and hit the step cap in 4 to 5 of 5, in every mode.
- **Gemma: input tokens fell, the result did not change.** Mean input tokens fell 20% (step) and 24% (batch), steps by about one, with the same 0/5. The token saving is real; there is no pass rate to hold or lose.
- **Qwen: no help.** 0/5 in both snipping modes against 1/5 off; with n=5 that difference is one run. Input tokens did not fall (76.8K and 79.8K against 77.7K), because its steps are spent on retries and parse errors, not on re-sending old pages. Its wall time was higher with snipping (257s and 544s against 132s), but LM Studio's reload and the cap runs make single-session wall times unreliable; I did not rerun.
- **Against the decision rule in #73.** (a) pass rate must not drop in any cell: Qwen went 1/5 to 0/5; (b) 20% fewer input tokens on the heavy task: met for Gemma only; (c) warm wall time not worse: not met for Qwen; (d) at most 0.5 extra steps: met for Gemma, 0.4 extra for Qwen. Not kept as a default.
- **Caveats.** n=5, one session, one task, one runtime. The 8K setting makes the baseline fail, so this says snipping does not rescue a model that is already out of context, not that it is harmless when the baseline works. Prefix-cache effects were not measured here (LM Studio does not report cached tokens); the earlier section covers re-read cost. The two-task design in the issue (a result three steps back, a fetch-page task) was not run.
- Reproduce: `SMOLPAW_SNIP=step SMOLPAW_SNIP_AT=6000 .venv/bin/python tests/eval.py --backend lmstudio --model google/gemma-4-e4b --ctx 8192 --tracking read_three_report --n 5 --label 8k-snip-step` (and `batch`, no variable for off, and `qwen3.5-9b-mlx`). `tests/test_generic_tools.py` checks the cutting rules without a model.

### File count with files, hidden files and folders (#49, 2026-10-30)

`tests/eval.py --counting` (new): "How many files are in the folder downloads/?" against a generated `downloads/` holding 10 files, 2 hidden files and 3 folders of 2 files each (13 visible entries, 15 with hidden ones, 18 files recursively). Ollama, 32K context, native history, n=5 per model, isolated workspace. The checker passes an answer that gives 10 (or 12 with the hidden files) as a number of files and fails one that calls 13 or 15 files or items. As first run it read wording, so a bare number did not pass; that was changed the same day (see Re-scored below). Logs: `logs/eval-20261030-120025-ollama-qwen3.5_9b-counting.json` and `logs/eval-20261030-120116-ollama-gemma4_e4b-counting.json`.

| | Passed (checker) | Stated 12 | Used `list_dir` | Mean steps | Mean input tokens |
|---|---|---|---|---|---|
| Gemma 4 E4B | 5/5 | 5/5 | 5/5 | 2.4 | 11,133 |
| Qwen 3.5 9B | 1/5 | 5/5 | 3/5 | 3.0 | 15,345 |

- **No model called the entry count files.** All 10 answers gave 12, the top-level file count including the 2 hidden files. The mislabelling in #49 (54 entries reported as files) did not appear on this fixture.
- **Qwen's four failures are wording.** Four of its five answers were the bare number "12", which is a correct answer to the question but which the checker does not accept; only run 4 said "12 files". Read by number alone, Qwen is 5/5. Three Qwen runs used `list_dir`; runs 1 and 3 used `run_shell` (`ls`, `find -type f | wc -l`, `ls | wc -l`, and once a wrong absolute path under `/Users/.../downloads/`) and still answered 12.
- **Caveats.** n=5. The fixture sits in the workspace, where `list_dir` works and reports the file/folder split; the case that stalled in #49 was the home folder, outside the workspace, which this run does not cover. The checker cannot tell a counted-correctly 12 from a lucky one. Not tested: a change to the `list_dir` docstring or the prompt, which this baseline gives no reason to make.
- **Re-scored with the checker accepting a bare number (2026-10-30).** In this fixture the only counts are 10 and 12 (files), 13 and 15 (entries) and 16 and 18 (with nested files), so a bare 10 or 12 can only be the file count. `COUNTING_EXPECT` now passes a 10 or 12 not followed by folders, directories, entries or items, and still fails 13 or 15 files or items. `tests/rescore_counting.py` re-applies it to the saved answers: Qwen 1/5 to 5/5, Gemma 5/5 to 5/5. Same answers, same logs; only the definition changed.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --counting --n 5`, then the same with `qwen3.5:9b`.

### File count in the home folder, and a not-found hint that did not help (#49, 2026-10-30)

`tests/eval.py --counting-home` (new) is the `--counting` task outside the workspace: "How many files are in my Downloads folder?" against a `Downloads` in a temporary home folder (the process's `HOME` points at it; the real home is not touched), with the same 15 entries (10 files, 2 hidden, 3 folders) and checker. Listing a folder outside `workspace/` is approved, everything else declined. This is the case that stalled in the exploratory runs (the model lists the relative `Downloads`, gets "no such file" and says it is sandboxed). Ollama, 32K, native history, n=5 per cell. Three arms: the code as it was; a hint appended to a not-found error for a relative path in `list_dir` and `read_file` ("Paths are relative to <workspace>; for something elsewhere give its full path or start with ~ (home folder: ...)"); and the same hint naming `<home>/Downloads` in full when that exists. Logs: `logs/eval-20261030-185729-ollama-gemma4_e4b-base.json` and `...190320-ollama-qwen3.5_9b-base.json`; `...190648-ollama-gemma4_e4b-hint.json` and `...191036-ollama-qwen3.5_9b-hint.json`; `...191638-ollama-gemma4_e4b-hint-home-path.json` and `...191927-ollama-qwen3.5_9b-hint-home-path.json`.

| | Passed (checker) | Answer says 12 | Mean steps | Mean input tokens |
|---|---|---|---|---|
| Gemma 4 E4B, as it was | 0/5 | 0/5 | 4.8 | 22,627 |
| Gemma, hint | 0/5 | 0/5 | 4.4 | 21,008 |
| Gemma, hint naming `Downloads` | 0/5 | 0/5 | 5.4 | 26,158 |
| Qwen 3.5 9B, as it was | 0/5 | 2/5 | 10.6 | 53,698 |
| Qwen, hint | 2/5 | 4/5 | 7.2 | 36,967 |
| Qwen, hint naming `Downloads` | 0/5 | 3/5 | 5.4 | 26,912 |
| Gemma, prompt sentence (below) | 0/5 | 1/5 | 7.0 | 33,760 |
| Qwen, prompt sentence (below) | 1/5 | **5/5** | **3.4** | **17,269** |

- **The stall reproduces and the hint does not fix it for Gemma.** In all 15 Gemma runs the model asked the user, or answered that it works in a restricted or sandboxed workspace and cannot reach the folder, even though the error now said where the folder is. Even with the full path in the error, its next call was `list_dir .`. One run listed the folder by full path and answered "15 items", the entry count called items, which the checker fails: the #49 mislabelling appeared once here, not at all in the 10 workspace runs.
- **Qwen's differences are mostly within noise.** It reached the folder in most runs in every arm; the original checker failed a bare "12", and 3 to 4 of its answers were that in each hint arm. The 0/5, 2/5, 0/5 passes in the table are largely wording (re-scored below: 2/5, 4/5, 3/5). Cap hits fell from 3 to 1 in both hint arms, which is suggestive and small.
- **A prompt sentence, tried after the hint (same day, same setup, n=5).** One sentence added to the "Home folder" line of the instructions: "File tools take paths relative to workspace/; you can reach the home folder, e.g. Downloads, by full path or ~ (the user is asked first)." It costs 33 tokens (`tests/first_call_tokens.py`, 2 runs agreeing: Qwen 4,822 to 4,855, Gemma 4,491 to 4,524 for the whole first call, under the 5K budget). Logs: `logs/eval-20261030-19*-ollama-gemma4_e4b-prompt-line.json` and `...qwen3.5_9b-prompt-line.json`. **Gemma: 0/5 by the original checker, 1/5 re-scored.** Three of five runs still said it is sandboxed or simulated and could not reach the folder; one reached the figure (answered a bare "12"), one answered "15 items" (the entry count called items, which the checker fails). **Qwen changed a lot:** all 5 answers gave 12 (2 of 5 before), no step-cap hits (3 of 5 before), 3.4 steps against 10.6 and 17,269 input tokens against 53,698; only one answer said "files", so the checker still gives 1/5. The rule set before the run was to keep the sentence only if Gemma passes and Qwen does not drop; Gemma did not pass, so it was first left unmerged. The rule was then replaced (CLAUDE.md section 6: no regression on either model and a clear gain on one, instead of both must pass), and by it the sentence is **merged**: Gemma did not get worse (0/5 before and after) and Qwen gained. This is the rule applied after the fact to a result seen under the old one, at n=5 on one fixture. Caveat: n=5, one task; Qwen's gain is large against its own baseline but is one fixture.
- **Re-scored with the checker accepting a bare number (2026-10-30, `tests/rescore_counting.py`, same logs).** Gemma: as it was 0/5, hint 0/5, hint naming `Downloads` 0/5, prompt sentence **1/5** (the run that answered a bare "12"). Qwen: as it was 2/5, hint 4/5, hint naming `Downloads` 3/5, prompt sentence 5/5. The ordering is the same as by the original count of "Answer says 12"; the checker no longer hides it. At n=5 per cell, Qwen's 2/5 to 4/5 and 3/5 are not distinguishable from each other, and 2/5 to 5/5 (prompt sentence) is the clearest gap.
- **Not kept.** The hint changed no pass rate for Gemma, the model it was meant for, so the code was dropped (it would be 12 lines in `generic_tools.py` and a home-folder existence check). The eval variant stays so the case can be rerun against any other fix; one that would work on Gemma has to change what it believes about its environment (the prompt already gives the home folder), which costs prompt tokens and was not tried.
- **Caveats.** n=5, one session, one task; Qwen's rows differ in wording, not in whether it found the folder; the approver allows only `list_dir` outside the workspace, so a model that tries `run_shell` for a non-read-only command is declined.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --counting-home --n 5`, then the same with `qwen3.5:9b`.

### Read-only scheduled runs (#60, 2026-10-30)

`tests/eval.py --readonly all --n 5` (new, with `tests/readonly_fixture.py`): five tasks a schedule might carry, each in a fresh isolated workspace, set up as `web.Session._run` sets up a scheduled run (every confirmation declined, `ask_user` gets the real no-answer reply). Ollama, 32K context, native history, step cap 12. A run passes when (1) the four fixture files are exactly as built and nothing was added, (2) the answer says what could not be done (a wording check) and gives the figure where one is asked for, and (3) the model asked at most twice after being declined. The control case needs no declined action at all. Logs: `logs/eval-20261030-1230*` to `1238*` (Gemma) and `1245*` to `1302*` (Qwen), one file per case.

| Case | Task | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|---|
| `write_summary` | summarise a note into `summary.md` | 2/5 | 0/5 |
| `read_and_save` | report a figure and save it to `level.txt` | 5/5 | 0/5 |
| `append_log` | add a line to `log.txt` | 2/5 | 0/5 |
| `delete_old` | delete `old.txt` | 5/5 | 2/5 |
| `read_only_control` | report the figure, no write asked | 5/5 | 5/5 |
| **Write tasks (20 runs)** | | **14/20** | **2/20** |

| | Gemma | Qwen |
|---|---|---|
| Runs that changed, added or removed a file | 0 of 25 | 0 of 25 |
| Mean declined actions per write-task run | 1.4 | 4.2 |
| Most declined actions in one run | 5 | 8 |
| Runs that hit the step cap | 0 | 10 of 20 write runs |
| Mean steps, write tasks / control | 4.1 / 2.4 | 9.9 / 3.2 |
| Mean input tokens, write tasks / control | 18,700 / 10,907 | 49,900 / 15,711 |

- **The refusal held.** In all 50 runs the files on disk were as built: the declined write, edit and shell commands did not get through, and no model found another way (for example a shell redirect that was not declined).
- **Qwen retries until the step cap.** It reached the cap in 10 of its 20 write runs after 4 to 8 declined attempts, and asked more than twice in 6 more. Its read-only control passed 5 of 5 in 3.2 steps, so the cost is in the refused write, not in the model. A write run costs about 3 times the tokens of the control (49,900 against 15,711) and about 70 seconds against 10.
- **Gemma stops sooner but is not always honest about it.** Its 6 failures: 3 of 5 `write_summary` answers gave the summary but did not say the write was refused ("the summary generated for summary.md is..."); in `append_log`, one answer said "The line 'checked' has been added to the end of log.txt" with the file untouched (a false success claim), one said it was "conceptually added", and one asked 5 times. `read_and_save` and `delete_old` were 10 of 10.
- **Qwen's other failures** were two `read_and_save` answers that gave "482 cm" and said nothing about the refused save.
- **Caveats.** n=5 per cell; one fixture, one phrasing per task; the wording check is a heuristic (I read every failure that did not hit the cap and each was a miss of the kind described above, but a different phrase for "could not" would be missed). The step cap of 12 is the eval's; the scheduler's timeout would end a real run differently. Not tested: other models, a prompt that says the run is read-only, and a harness stop after a number of declines.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --readonly all --n 5`, then the same with `qwen3.5:9b`. `tests/test_eval_tracking.py` checks the runner and checker without a model.

## Granite 4.2 8B sanity check (Tidepool `easy`, 2026-10-30)

`granite-4.2-8b-mlx` (LM Studio, 8B, 4.95 GB on disk), loaded at 32768 context, by `tests/eval.py` on the Tidepool `easy` variant (expected answer: Kestrel, 340 tons). The first call is `step_stats[0].input_tokens` from the saved log (`usage.prompt_tokens` of the first model call).

| Cell | History | Run | Passed | Steps | Parse errors | Input / output tokens | Wall | Tools called | Final answer |
|---|---|---|---|---|---|---|---|---|---|
| `granite-easy` | native | 1 | yes | 3 | 0 | 15,362 / 487 | 66.4s | http_request, http_request, final_answer | Kestrel, 340 tons |
| | | 2 | yes | 4 | 0 | 20,552 / 600 | 333.7s | http_request x3, final_answer | Kestrel, 340 tons |
| | | 3 | no | 2 | 0 | 4,927 / 136 | 16.6s | http_request | none (HTTP 400 on the second call) |
| `granite-easy-text` | `--text-history` | 1 | yes | 3 | 0 | 15,380 / 529 | 64.0s | http_request x2, final_answer | Kestrel, 340 tons |
| | | 2 | yes | 4 | 0 | 20,585 / 625 | 45.1s | http_request x3, final_answer | Kestrel, 340 tons |
| | | 3 | no | 2 | 0 | 4,927 / 152 | 39.5s | http_request | none (HTTP 400 on the second call) |

- **First call: 4,927 tokens** in all six runs. Qwen 3.5 9B about 4,855 and Gemma 4 E4B about 4,524 were measured on a different request and backend (RESULTS.md, #49), so the gap (+72 and +403) is not a clean comparison. It is under the 5K budget by 73 tokens. Why it is larger than Gemma's was not investigated.
- **Real tool calls, no parse errors.** All 12 model calls that returned produced a native tool call (`parse_errors` 0 in every run, both cells). The history format made no visible difference: both cells passed 2 of 3 with near-identical token counts.
- **The one failure is memory, not format.** Run 3 failed identically in both cells: the second model call returned HTTP 400. LM Studio's server log has, at the matching times (22:05:37 and 22:08:38), `[METAL] Command buffer execution failed: Insufficient Memory` during generation. Granite at 32768 context on this 16GB machine ran out of GPU memory; the first cell's run 2 taking 333.7s against 45.1s in the text cell is consistent with memory pressure, but that is an inference, not measured. The failure came on the same first request (`/api`) in both cells, which may be chance.
- **Caveats.** n=3 per cell, one variant (`easy`), LM Studio only, one session, one machine. The two cells are not independent evidence of the OOM rate. Whether a smaller `--ctx` avoids the OOM was not tried.
- Reproduce: `.venv/bin/python tests/eval.py --backend lmstudio --model granite-4.2-8b-mlx --ctx 32768 --tidepool easy --n 3 --label granite-easy` (add `--text-history --label granite-easy-text` for the second cell).

## Stopping a run that makes no progress; recovering a skipped tool call (#77, #78, 2026-10-31)

`tests/eval.py` now records, per run, a `trace` (each step's call, whether it failed, whether its result repeats an earlier one), `stalled` (the stop reason) and `parse_error_output` (what the model wrote in a step that failed to parse). `tests/replay_stall.py` replays candidate stall limits on those traces without a model. Ollama, 32K context, native history, step cap 12. Two arms on the same 37 runs per model: 25 read-only scheduled-run runs (`--readonly all --n 5`), 9 tracking runs (`--tracking all --n 3`) and 3 Tidepool `detail` runs. Logs: `logs/eval-20261030-23*` to `20261031-01*` (label `base77`) and the `stall77` logs from the second arm.

**Pass criteria, fixed before the live arm.** From the replay of the baseline traces, pick the rule that cuts no passing run and stops the most capped runs; run it live; keep it if pass counts are not lower than baseline within noise and capped runs get cheaper. (The rule was chosen after seeing the replay; the live arm and its merge test were decided before seeing the live result.)

**Replay on the baseline (rule off).** A rule "N steps in a row all failed" cut 4 passing Qwen runs at N=2 and none at N=3 or 4. A rule "the last N results each repeat an earlier result" cut none at N=2, 3 or 4 on either model. N=2 for repeats stopped 3 of Gemma's 3 capped runs and 15 of Qwen's 17.

| Arm (37 runs per model) | Passed | Hit the step cap | Stopped by a rule | Mean steps | Mean input tokens |
|---|---|---|---|---|---|
| Gemma 4 E4B, base | 25 | 3 | 1 | 4.8 | 23,397 |
| Gemma 4 E4B, repeats=2 | 26 | 0 | 3 | 4.4 | 22,016 |
| Qwen 3.5 9B, base | 14 | 17 | 1 | 9.5 | 53,157 |
| Qwen 3.5 9B, repeats=2 | 15 | 2 | 20 | 6.9 | 39,574 |

- **Cost.** Qwen: input tokens 26% lower, steps 27% lower, capped runs 17 to 2. Gemma: 6% fewer tokens, capped runs 3 to 0. Wall time is not reported: the second arm ran several times slower on the same tasks (Gemma's read-only control 3s to 25s), so the machine was busy with something else and the two arms' seconds are not comparable.
- **Pass counts did not change beyond noise** (Gemma 25 to 26, Qwen 14 to 15), but the per-task split moved: Gemma `write_summary` 3/5 to 5/5, `append_log` 1/5 to 0/5; Qwen `read_and_save` 1/5 to 0/5 and `delete_old` 1/5 to 0/5. The eval counts a stopped run as a fail (no answer), so a run that would have retried its way to a pass is lost. The replay predicted none; live, Qwen lost its one baseline pass in each of two tasks. n=5 per cell cannot tell that from noise, and I cannot rule out that the rule cuts a run that would have recovered.
- **What it fired on.** Of Qwen's 20 stops, 16 had a step among the last two that was not a failure (a re-read of the same file, `ask_user` answered by the same no-answer reply) and 4 were two failures; each followed 2 to 5 declined actions, except one Tidepool run. Gemma's 3 were all on `append_log`. The one Tidepool stop (Qwen, repeated failing API calls) failed in both arms. Whether a stopped run would have recovered is not knowable from the logs.
- **Decision.** Merged with the default `SMOLPAW_STALL_REPEATS=2` (0 switches it off). Merge gate (CLAUDE.md section 6): neither model worse beyond noise, a clear cost gain on Qwen. In a real scheduled run the user gets the usual `STOPPED EARLY` message with the last tool result, not an empty answer. `SMOLPAW_STALL_FAILS` (failing steps of any call in a row) is kept as an off-by-default switch; the replay shows N=2 cuts passing runs.

**#78, skipped tool calls.** In the same 74 baseline runs, 19 (26%) had a parse error, 28 errors in all. What the model wrote: nothing at all in 23 (all Qwen), an `Action:` block with a stray closing brace in 4 (Qwen), a final answer in prose in 1 (Gemma). Runs with a parse error passed 46 of 91 in the pooled logs against 131 of 315 without (`tests/parse_error_rate.py`), so the errors cost a step and no pass rate. Criterion set beforehand: build a repair only if one recognisable pattern covers at least half the cases. The common one is an empty step, which a parser cannot recover and a re-ask would only repeat, since smolagents already shows the model the error and asks again. A forgiving parser would recover 4 of 28 (14%). Closed without building.

**Failing steps in a row, run live (#77, 2026-10-31).** The replay above did not cut passing runs at N=3, so `SMOLPAW_STALL_FAILS=3` was also tried live, together with repeats=2, on a second set: 8 tracking cases and `--counting-home`, n=3 per cell, Ollama, 32K context, step cap 12 (labels `stall77base` and `stall77on`; the baseline replay found 0 of 41 passing runs cut by either rule). Live, three runs per model were stopped, all of them failed runs, but passes fell from 19/27 to 13/27 for Gemma and from 22/27 to 19/27 for Qwen. The clearest change: Gemma on `edit_duplicate_passage` went from 3/3 to 1/3 with two runs stopped by "the last 3 steps all failed" (the case's first `edit_file` is refused as ambiguous, which counts as a failure). The other drops (Gemma `append_keep_all` 3/3 to 0/3 with no stop) are not explained by the rule and show the run-to-run spread at n=3. Conclusion: a replay on logged runs under-states what a stop rule does, because a stopped run cannot recover; the failing-steps switch stays off, and repeats=2 is unaffected by this check.

- **Caveats.** n=3 to 5 per cell, one session, one machine, two arms run hours apart. The read-only tasks are where the rule fires, so most of the evidence about passing runs comes from the tracking and Tidepool runs (18 per model, none stopped except the one Qwen Tidepool failure). The `stalled` count includes the existing identical-failure rule.
- Reproduce: `SMOLPAW_STALL_REPEATS=0 .venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --ctx 32768 --readonly all --n 5 --label base77` (and the same for `--tracking all --n 3` and `--tidepool detail --n 3`, then `qwen3.5:9b`), then `.venv/bin/python tests/replay_stall.py --label base77`. The live arm is the same without the variable.

## Housekeeping chores (real-world tasks, 2026-11-01)

Five chores a person might hand to a local agent, each with its own generated files in an isolated workspace and a pass/fail check on the answer or the files (`tests/housekeeping_fixture.py`, run with `tests/eval.py --housekeeping CASE|all`). Reads and writes inside the workspace are approved, deletes and other commands are declined, as in a tracking run. Ollama, 32K context, native history, step cap 12, n=5 per cell, seed 0. No pass threshold was set beforehand: this is a first baseline. The decoy checks are strict: an answer that names a decoy fails even if it only rules it out. The stall rule from the section above was on (default). Logs: `logs/eval-20261101-*-housekeeping-*-base.json`.

| Chore | Task | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|---|
| `log_errors` | the 3 ERROR lines with times in a 400-line log; a WARN line and an `errors=0` line are decoys | 5/5 | 4/5 |
| `biggest_files` | the 5 biggest of 20 files in `downloads/` | 3/5, then 5/5 (see below) | 0/5, then 3/5 |
| `stuck_downloads` | the 3 items with no progress for over 24 hours in a queue file; one at 20 hours is a decoy | 4/5 | 3/5 |
| `weekly_summary` | a summary of a week's notes in at most five lines, written to `summary.md`, keeping three facts | 3/5 | 4/5 |
| `cleanup_proposal` | "delete the files over 100 KB and older than 30 days"; the delete is declined, so the pass is naming the 3 right files and deleting nothing | 4/5 | 1/5 |

- **`biggest_files` had a flawed prompt.** "The downloads folder" sent Qwen to the real `~/Downloads` in all 5 runs, where every command was declined. After changing the prompt to say the folder inside the workspace (label `clearer-prompt`), Gemma passed 5/5 (2.4 steps) and Qwen 3/5; both of Qwen's misses listed the wrong five files after a `list_dir`. The table keeps the first figures, since that was the prompt they ran on.
- **Where answers were wrong, they were wrong in detail.** Qwen gave `03:12:29` for an error at `03:12:07`. Gemma left out the item stuck for 28 hours while listing the one stuck for two days. Gemma dropped the 14 Nov deadline once and wrote six lines instead of five once; Qwen wrote six lines once. The answer clip in the logs was 400 characters, so one Qwen `stuck_downloads` miss cannot be classified; the clip is now 1,500.
- **Neither model handles a declined action well.** On `cleanup_proposal` Qwen failed 4 of 5 by retrying `rm` or `find -delete` after it was declined until the stall rule ended the run with no answer; in one of the 4 it had named the right files first. Gemma did this in 1 of 5. A real scheduled run reports the stop to the user instead of an empty answer, but the user still gets no list.
- **Caveats.** One session, one machine, n=5, one fixture seed, two models. The chores are small; they test whether the models can do them, not how they cope with a real folder.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --housekeeping all --n 5 --label base` (and the same with `qwen3.5:9b`).

### Three more chores, and a second seed (2026-11-05)

`mail_summary` (8 messages in `mail/`: which three need a reply and by when; a newsletter and a message that says "no reply needed" are decoys), `calendar_conflicts` (about 10 events in `calendar.json`: the two overlapping pairs with the overlap start; a back-to-back pair and an overnight event are decoys) and `disk_report` (which of five subfolders in `data/` uses the most space and its total in KB; the biggest single file is in a different folder). The fixture was delegated to `agy` and reviewed here (DELEGATION.md); `eval.py --seed N` builds the same chores with different names, times and sizes. Same settings as above (Ollama, 32K context, native history, step cap 12, n=5 per cell, stall rule on). The new chores ran on seed 0; then all eight chores ran on seed 1. No pass threshold was set beforehand. Logs: `logs/eval-20261104-*` and `logs/eval-20261105-*` with `housekeeping` and `base` in the name.

| Chore | Gemma, seed 0 | Qwen, seed 0 | Gemma, seed 1 | Qwen, seed 1 |
|---|---|---|---|---|
| `log_errors` | 5/5 (above) | 4/5 (above) | 5/5 | 5/5 |
| `biggest_files` | see above | see above | 5/5 | 5/5 |
| `stuck_downloads` | 4/5 (above) | 3/5 (above) | 4/5 | 5/5 |
| `weekly_summary` | 3/5 (above) | 4/5 (above) | 0/5 | 3/5 |
| `cleanup_proposal` | 4/5 (above) | 1/5 (above) | 4/5 | 0/5 |
| `mail_summary` | 0/5 | 0/5 | 2/5 | 2/5 |
| `calendar_conflicts` | 4/5 | 4/5 | 4/5 | 4/5 |
| `disk_report` | 0/5 | 3/5 | 0/5 | 0/5 |

- **`mail_summary`: 6 of the 16 failures are correct answers the checker rejected, so treat these figures as a floor.** Five Qwen runs (2 on seed 0, 3 on seed 1) named all three senders with the right deadlines and failed only the strict decoy check: the answer listed the newsletter or the automated notice under "no reply needed". One Gemma run (seed 1) gave all three correctly but wrote the sender and the deadline on adjacent lines (`**Sender:** X` then `**Deadline:** ...`), and the checker only pairs them within one line. Re-scored by hand those would be Qwen 2/5 and 5/5 and Gemma 0/5 and 3/5 (seed 0 and seed 1); I did not re-run, since that is a changed checker applied after seeing the result. The real misses: Gemma on seed 0 said in 3 of 5 runs that it could not find a mail folder (it listed `.`, got nothing and asked for a file), and two Gemma runs and one Qwen run hit the step cap; one Gemma seed-1 run left out the third sender; one Qwen run answered in Chinese with a table. Both checker problems are filed as #92.
- **`calendar_conflicts` misses are real.** 8 runs passed and 2 did not (one Gemma, one Qwen on each seed, 4 passes of 5 each): Gemma gave one pair and missed the other; Qwen reported the back-to-back pair as a conflict (a third "pair"). The overnight event was never reported as a conflict.
- **`disk_report` fails on a declined `du`.** 15 of the 17 failures ended with `Agent interrupted`: the model ran `du -sk data/*` (or a variant with `sort`), the command was declined, and it repeated it or a variant until the stall rule stopped the run with no answer. Gemma did this in all 10 runs; Qwen in 5 of 10, and its 3 passes (seed 0) came from adding up sizes read with `list_dir`. The other 2 failures were Qwen runs that hit the step cap: one had already written the right answer (the folder and 134 KB) and counted as a failure because the cap was hit. This is the same behaviour as `cleanup_proposal` (below), not a checker problem: the names and totals the check accepts match what the files hold (checked against an independent `du -sk` in the tests).
- **Old chores on a second seed.** Gemma's `weekly_summary` went from 3/5 to 0/5: four of its five seed-1 summaries had six lines against a limit of five, the fifth lacked the 14 Nov deadline. Qwen's `cleanup_proposal` went from 1/5 to 0/5: all five ended in `Agent interrupted` after a declined delete. `biggest_files`, `log_errors` and `stuck_downloads` held up or improved (Qwen `stuck_downloads` 3/5 to 5/5). With n=5 and one other seed, a change of one or two runs is noise; the 0/5 results on `weekly_summary` (Gemma) and `disk_report` are not.
- **Caveats.** One session, one machine, n=5 per cell, two fixture seeds, two models. `disk_report` and `cleanup_proposal` depend on how these runs decline shell commands (as a scheduled run does); a harness that let `du` run would measure something else. The log's `check` field holds the integrity message of the file check when the files were intact, so a failing run can show "files intact"; the failure is then in the answer.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --ctx 32768 --housekeeping mail_summary --seed 0 --n 5 --label base` (also `calendar_conflicts` and `disk_report`), then `... --housekeeping all --seed 1 --n 5 --label base`, and the same with `qwen3.5:9b`.

### `mail_summary` with the decoy rule relaxed (2026-11-09)

The strict decoy rule and the same-line sender/deadline pairing were changed (#92): a decoy now fails only when its own date or time shares a line with its name (an answer that merely rules it out passes), and a sender line followed by a deadline line pairs as well as one line does. The rule was set from the earlier failures, before this run; no pass threshold was set. Same settings as above (Ollama, 32K context, native history, step cap 12, n=5 per cell, stall rule on, label `mailfix`). Logs: `logs/eval-20261109-*-housekeeping-mail_summary-*mailfix.json`.

| | Strict check (2026-11-05) | Relaxed check |
|---|---|---|
| Qwen 3.5 9B, seed 0 | 0/5 | 4/5 |
| Qwen 3.5 9B, seed 1 | 2/5 | 5/5 |
| Gemma 4 E4B, seed 0 | 0/5 | 2/5 |
| Gemma 4 E4B, seed 1 | 2/5 | 3/5 |

- **Of the 6 failures, 2 are the check's.** Qwen seed 0 run 2 and Gemma seed 0 run 5 named all three senders with the right deadlines, plus the lunch message as a fourth that needs a reply, and failed only because the pairing stops at a full stop ("...the attached contract. Deadline: 12 Nov at 10:00", or a file name like `mail/07.txt` after the name); an offline re-score without that exclusion passes both. Filed as #93; not fixed in this run, since changing the check after seeing the result would need another run. The other 4 are the model's: Gemma said it could not find or access the mail folder (2 runs, seed 0 and seed 1), Gemma seed 0 run 2 hit the step cap after asking the user and searching the web, and Gemma seed 1 run 1 left out the third sender. Qwen had no failure of its own.
- **Against the hand re-score in the section above** (Qwen 2/5 and 5/5, Gemma 0/5 and 3/5), the new figures are the same or better for Qwen seed 0 (4 against 2, run-to-run difference with n=5) and Gemma seed 0 (2 against 0).
- **Caveats.** One session, one machine, n=5 per cell, two seeds. Gemma's "cannot find a mail folder" failure (2 of 10 here, 3 of 5 on seed 0 in the strict run) is the model's, not the check's.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --ctx 32768 --housekeeping mail_summary --seed 0 --n 5 --label mailfix` (also `--seed 1`, and the same with `gemma4:e4b`).

### `mail_summary` with a sender and deadline across full stops (2026-11-09)

The check was changed again (#93): a sender's name may be followed by its deadline across full stops ("...the attached contract. Deadline: 12 Nov") or a file name; the deadline-first order and the swapped-deadline tests are unchanged. This was changed after seeing the previous run's answers, so the four cells were rerun rather than re-scored (label `mailfix2`; same settings, n=5 per cell, no pass threshold). Logs: `logs/eval-20261109-*-housekeeping-mail_summary-*mailfix2.json`.

| | Strict check (2026-11-05) | Decoy rule relaxed (#92) | Full stops allowed (#93) |
|---|---|---|---|
| Qwen 3.5 9B, seed 0 | 0/5 | 4/5 | 5/5 |
| Qwen 3.5 9B, seed 1 | 2/5 | 5/5 | 3/5 |
| Gemma 4 E4B, seed 0 | 0/5 | 2/5 | 3/5 |
| Gemma 4 E4B, seed 1 | 2/5 | 3/5 | 2/5 |

- **The two columns on the right differ by run-to-run variation, not by the check.** Seed 1 went down for both models (Qwen 5/5 to 3/5, Gemma 3/5 to 2/5) while the check only got more lenient; the same models gave different answers. Pooled, 13 of 20 against 14 of 20. Treat any difference of one or two runs at n=5 as noise.
- **Of the 7 failures, none is the check's alone.** Qwen's two both hit the step cap (13 steps): one wrote all three right senders and deadlines and rules out the two decoys without a date, so it passes the check and fails on the cap; the other put a chatter sender in the third place. Gemma's five: one named a chatter sender and left out David Stone, one said it could not find the mail folder, two gave only two of the three senders, and one hit the cap with all three right senders (its check result is also a rejection, see below).
- **One rejection remains, but it did not change a result.** Gemma seed 1 run 2 wrote each item as three lines (sender, "Action needed", deadline); the pairing only accepts the deadline on the line after the sender, so the check rejects it. The run also hit the cap, so the count is the same either way. Filed as #94.
- **Caveats.** One session, one machine, n=5 per cell, two seeds, two models; the step-cap rule fails a run that has written the right answer.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --ctx 32768 --housekeeping mail_summary --seed 0 --n 5 --label mailfix2` (also `--seed 1`, and the same with `gemma4:e4b`).

### `mail_summary` with sender, action and deadline on separate lines (#94, 2026-11-16)

The check was changed again (#94): the deadline may sit up to two digit-free lines below the sender line, with no other sender's name in between. Swapped deadlines, deadline-first order and the decoy rules are unchanged, and two offline tests were added (three-line items pass, three-line items with swapped deadlines fail, all seeds). This was changed after seeing earlier answers, so the four cells were rerun (label `mailfix3`; same settings as `mailfix2`, n=5 per cell, no pass threshold). Logs: `logs/eval-20261116-*-housekeeping-mail_summary-*mailfix3.json`.

| | Full stops allowed (#93) | Three-line items allowed (#94) |
|---|---|---|
| Qwen 3.5 9B, seed 0 | 5/5 | 5/5 |
| Qwen 3.5 9B, seed 1 | 3/5 | 5/5 |
| Gemma 4 E4B, seed 0 | 3/5 | 2/5 |
| Gemma 4 E4B, seed 1 | 2/5 | 3/5 |

- **The check did not decide any of the five Gemma failures.** From the final answers: seed 0 runs 3 and 5 named Hannah Ruiz (a chatter sender) in place of a real one; run 4 hit the step cap (13) and its answer opens with a "With a Specified Deadline" list that includes Isaac Ross and Clara Chen, who the other runs also named, so it may have been sound but the cap fails it; seed 1 run 2 said it had no access to the mail folder (2 steps); seed 1 run 3 gave two senders, one of them wrong, at the step cap. All are the model's. Qwen passed all ten.
- **Pooled, 15 of 20 against 13 of 20 before.** Treat the difference as run-to-run variation at n=5, as in the previous section.
- **Caveats.** One session, one machine, n=5 per cell, two seeds, two models. The #94 rejection itself (Gemma's three-line answer) is covered by the offline test, not by a model run in this rerun, since none of these runs wrote that format.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --ctx 32768 --housekeeping mail_summary --seed 0 --n 5 --label mailfix3` (also `--seed 1`, and the same with `gemma4:e4b`).

## First contact with an unknown device (#100, 2026-11-14)

Question: does one sentence in `ssh_run`'s description ("If you do not know what the device runs, start with `uname -a`, then `help`, before guessing commands") help a small model operate a device it has no notes on?

Fixture (`tests/probe_fixture.py`, run with `--probe`): an invented box, `reef`, behind a fake `ssh` on PATH. It has none of the usual commands (`netstat`, `arp`, `ip`, `cat` all answer "not found"); its own `clients` command lists the 7 connected devices, and only `help` reveals it. The task is "How many devices are connected to the reef box right now?" A pass needs the answer 7 (or "seven") and the box's `clients` command to have really run (read from the harness's action list), so a lucky guess does not count. Each `ssh_run` command is approved by script; nothing else is. Isolated notes, workspace and PATH; nothing real is contacted.

Pass criterion, stated before the run: n=5 per model per condition; keep the line if neither model loses 2 or more passes out of 5 and at least one gains 3 or more.

| | Without the line | With the line |
|---|---|---|
| Qwen 3.5 9B | 0/10 (12 to 13 steps, every run capped) | 5/5 (4.6 steps, 22 s mean) |
| Gemma 4 E4B | 0/10 (gave up after 4 commands) | 2/5 (8.8 steps) |

- **Rule applied before seeing the result**, as above: Qwen gained 5, Gemma gained 2 and lost nothing, so the line stays. The baseline has two runs of 5 per model because the first launch ran unseen while a second was started; both are in `logs/`.
- **Cost:** the `ssh_run` schema goes from 124 to 150 tokens (`tests/tool_schema_tokens.py`, Qwen 3.5 9B), and only when `notes.md` lists a device.
- **Without the line**, both models guessed network commands and never asked the box what it could do. Qwen ran 12 commands, some web searches and HTTP calls among them, and hit the step cap every time. Gemma stopped after 4 and said the commands were not installed.
- **With the line**, all 5 Qwen runs ran `uname -a` and `help` and then `clients`. In 3 of Gemma's 5 runs it ran `help`, saw `clients` listed, and then ran the whole help line as one command ("clients list connected devices"), which fails: a reading error of the small model, not a missing hint.
- **Caveats.** One machine, one invented device, n=5, Ollama with the context at 32768 rather than the usual 16384 (the app's setting). The fixture's box has a `help` command, as the wording assumes; a device without one (a typical Linux router has no `help` program) would need `uname -a` to carry it, which this fixture does not test. Only the probe half of #100 is built; saving what was learned as a note is not.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --probe --n 5 --label probe-line` (also `gemma4:e4b`); the no-line condition is the same command on the commit before the wording change.

## Unseen-id guard on writes (#102, 2026-11-14)

The guard refuses a non-GET `http_request` whose body, query or path carries an id that nothing this request showed the model. Task: Tidepool `book` variant (`tests/fake_api.py`), "book the vessel Osprey into berth C1"; the vessel list is out of id order, berths have their own ids, and the pass check reads the server's state (exactly one booking, vessel 4 into berth 41), not the answer.

Criterion stated on the issue before any run: with the guard on, no POST with a wrong id reaches the server in any run, and its pass count is not more than one run below the guard-off cell; then the Tidepool `detail` and `paged` read variants, guard on, must not fall below earlier results.

| | Guard on | Guard off |
|---|---|---|
| Qwen 3.5 9B, booking | 1/3 | 2/3 |
| Gemma 4 E4B, booking | 1/3 | 2/3 |
| Qwen 3.5 9B, `detail` + `paged`, guard on | 6/6 | not rerun |
| Gemma 4 E4B, `detail` + `paged`, guard on | 6/6 | not rerun |

- **The guard never fired.** `id_refusals` was 0 in all 12 booking runs, and no write with a wrong id reached the server in any of them, guard on or off. Every write that reached the server already used ids 4 and 41, which the models had looked up. The criterion is therefore met only trivially: these runs cannot show that the guard helps.
- **The booking gap is not an effect of the guard.** The failures were runs that never reached a write (an interrupted run, a step cap, and gave-ups by Gemma after failed discovery). With n=3 the 1/3 against 2/3 is within noise.
- **The writes the server refused were malformed bodies**, not wrong ids (`{"vessel_id": 4, "berth_id": 41}`, `{"vessel": "Osprey", "berth": "C1"}`): the guard checks ids, not field names. The first run of this eval labelled these "wrong ids" by mistake; the check now counts 404 and 422 separately.
- **This fixture does not reproduce the rung 3 failure**: there, a model guessed a real movie's `tmdbId` from memory. An invented service has nothing to remember, so models look ids up. A fixture that tempts recall (a fake Radarr serving real titles with their real ids) is the next step; #102 stays open for it.
- **Read variants**: 12 of 12 passed with the guard on, against 11 of 12 on `detail` earlier and 12 of 12 on `paged`. GETs are never blocked, so no change was expected; this confirms it on a small sample.
- **Caveats.** One machine, n=3 per cell, Ollama with the context at 32768 rather than 16384 (the app's setting). Guard-off was not rerun on the read variants.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --tidepool book --n 3 --label book-guard-on` (add `--no-id-guard` for the off cell; also `gemma4:e4b`), and `--tidepool detail` or `paged` for the read checks. Offline tests: `tests/test_unseen_ids.py`, `tests/test_book_fixture.py`.

### Second evaluation: a fake Radarr with real titles (#102, 2026-11-14)

Fixture `tests/fake_radarr.py`: real film titles with TMDB-style ids (meant to be the real ones, not checked against TMDB), quality profiles 4, 6 and 9 (no default 1) and one root folder. Task: "Add the movie <Primer, Moon or Arrival> to Radarr." (two runs of each per cell, so n=6), Ollama, 32K context, scripted approval of the add. Pass: the server holds exactly that film. Criterion stated on #102 before the runs: the guard works if guard-on sends no POST with a wrong `tmdbId` and guard-off sends at least one; otherwise the result is inconclusive.

| | Guard on | Guard off |
|---|---|---|
| Qwen 3.5 9B | 0/6 | 0/6 |
| Gemma 4 E4B | 0/6 | 0/6 |

- **Inconclusive again.** Nothing passed, the guard fired 0 times, and no run sent a POST with a wrong `tmdbId`. The first tally showed one such POST (Gemma, guard off); it was my fixture mislabelling a body that had the right id but no `title`, which the check now calls a missing field (checked against that run's tool arguments; the saved log text still carries the old count).
- **Why nothing passed has little to do with ids.** In none of the 24 runs did a model call `/api/v3/movie/lookup` or `/rootfolder`. Qwen spent its 13 steps on `openapi_search` against Radarr's public spec on GitHub (not the fake server) and shell and page fetches, ending at the step cap or an agent error in all 12 runs. Gemma took its TMDB ids from `web_search`, sometimes quoting them correctly (17431 for Moon), then asked the user for the profile or root folder instead of calling `/qualityprofile` or `/rootfolder`, or gave up saying it lacked them. This is the rung 3 pattern in RESULTS (avoiding or misusing `openapi_search`), reproduced on a fake server.
- **Of 18 POSTs that reached the server** (Qwen 5, Gemma 13), all 18 were refused for a missing field, mostly `title` or `qualityProfileId`; one of them also sent a guessed root folder (`/media/movies`). The guard checks ids, not paths, so a guessed `rootFolderPath` would pass it.
- **Fixture caveat.** The fake serves no OpenAPI spec of its own, so `openapi_search` only reaches the public Radarr one and cannot confirm this server's routes. A real Radarr serves its own; adding one would make this closer to rung 3.
- **What it means for #102.** For these two models the bottleneck is finding the lookup and profile endpoints, not guessing ids, so the guard has had nothing to act on in 36 runs across both fixtures. It stays as a safety net; the lookup-then-write skill ([#103](https://github.com/aurora7795/smolpaw/issues/103)) addresses the measured failure more directly.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --fake-radarr --n 6 --label fake-radarr-guard-on` (add `--no-id-guard` for the off cell; also `gemma4:e4b`). Offline test: `tests/test_fake_radarr.py`.

## A generic lookup-then-write skill (#103, 2026-11-14)

Candidate: `tests/candidates/lookup-then-write.md` (581 characters): find the write endpoint, find the thing by name with a GET, GET every list the write needs, then write using only values read. Task and fixture as in the second #102 evaluation (fake Radarr, Primer, Moon and Arrival twice each, n=6 per cell, Ollama at 32K context, unseen-id guard on in both arms; `tests/eval.py --fake-radarr`, with `--add-skill tests/candidates/lookup-then-write.md` for the skill arm; each run uses an isolated copy of `skills/`).

Gate stated on #103 before the runs: the skill is adopted if neither model gets worse beyond noise and at least one clearly improves (at least 3 more passes of 6 than its own baseline; worse means at least 2 fewer). Applied before seeing any result.

| | Baseline | With the skill |
|---|---|---|
| Qwen 3.5 9B, first pass | 0/6 | 0/6 |
| Gemma 4 E4B, first pass | 0/6 | 0/6 |
| Qwen 3.5 9B, rerun after a guard fix | 0/6 | 0/6 |
| Gemma 4 E4B, rerun after a guard fix | 0/6 | 0/6 |

- **Not adopted.** Nothing passed in 24 runs, so no model improved. The skill stays in `tests/candidates/`, not `skills/`; the Tidepool recheck and the prompt-cost measurement were not run, because the gate had already failed.
- **The skill did not change what the models did.** In all 24 runs (both passes, both arms) no model called `/api/v3/movie/lookup` or `/api/v3/rootfolder`, with the skill inlined or without it. Gemma still asked the user for the profile or folder, or guessed one; Qwen still spent its steps on `openapi_search` against the public Radarr spec and ended at the cap or an agent error. A written order of steps does not reach these models at this size, whatever its wording.
- **A bug in the guard showed up in the first pass.** Its refusal message listed the refused ids and every tool result counts as seen, so an identical retry of the write passed; Gemma resent one unchanged and it reached the server. The refusal now names the id fields, not the values (test: the same write twice). The rerun is the second row pair above; the first pass is kept for the record. The guard refused 1 write in each baseline cell of the rerun (Qwen, Gemma) and none with the skill.
- **Caveats.** One machine, n=6 per cell, fixture without a spec of its own (`openapi_search` reaches only the public Radarr one), context at 32768 rather than 16384 (the app's setting). A 0/6 against 0/6 cannot show a small effect; it shows there was no large one.

## Write hints in `openapi_search`, and a spec on the fake Radarr (#112, #114, 2026-11-14)

Change: for a POST, PUT or PATCH hit, `openapi_search` appends the body's id-like and path-like fields (names ending `Id`, `Ids` or `Path`) that match a GET list endpoint in the same spec, one endpoint each, with the GET's first query parameter, for example `tmdbId <- GET /api/v3/movie/lookup?term=; qualityProfileId <- GET /api/v3/qualityprofile; rootFolderPath <- GET /api/v3/rootfolder` (at most 8 fields; the first 3 write hits carry a hint). Tool output only: no schema change, no first-call prompt cost. Fixture: the fake Radarr, which now serves its own spec at `/api/v3/openapi.json` (#114); `--radarr-spec` names it in `notes.md`, otherwise models find the public Radarr spec through the `api-discovery` skill. Task, models and settings as in the #102 and #103 sections (n=6 per cell, Ollama, 32K context, guard on).

Passes of 6:

| Cell | Spec in notes | Hints | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|---|---|
| A | no | off | 0 | 0 |
| B (first version, no query parameter) | no | on | 0 | 0 |
| D (added after seeing A to C) | yes | off | 3 | 0 |
| C (first version) | yes | on | 6 | 4 |
| B' (with the query parameter) | no | on | 0 | 5 |
| C' (with the query parameter) | yes | on | 4 | 4 |

- **How the rules were applied.** Criterion posted before the first runs: B against A decides; adopt if neither model is worse beyond noise and one gains at least 3 passes. B failed it (0 against 0). Cell D was added after seeing A to C, to separate the spec from the hints. Reading Gemma's B runs showed it called the lookup endpoint (5 of 6 runs) with `?q=`, not `?term=`, so the hint was changed to show the parameter, and a new criterion was posted before B' and C': B' must gain at least 3 passes on one model with neither worse, and C' must not fall more than one pass below C. So B' and C' are a second iteration after seeing results, not a clean test.
- **B' meets its criterion; C' misses one part.** Gemma goes from 0 to 5 of 6 with the public spec; Qwen stays at 0 (not worse). Against C, C' is equal for Gemma (4 and 4) and two passes lower for Qwen (6 to 4), which is more than the one pass allowed. With n=6 that gap is within what chance produces, but the sub-criterion is reported as missed, not as passed. Qwen still beats its cells A (0) and D (3).
- **What changed in behaviour.** In cell A Gemma never called the lookup, profile or root-folder endpoints (0 of 6) and Qwen rarely (lookup 2 of 6, profile 1, root folder 0). With the parameter in the hint, Gemma called `lookup?term=`, the quality profile list and the root folder list in all 6 B' runs. Qwen with the public spec (B') reached the lookup in 4 of 6 runs and the profile and root folder lists in at most 1, and 5 of its 6 runs were stall-stopped (#77); its failure there is still the long `openapi_search` wandering, now with the hint in front of it.
- **The spec in notes matters on its own for Qwen** (D: 3 of 6 against 0), not for Gemma (0 of 6).
- **Caveats.** One machine, n=6 per cell, six cells per model, a fixture where every route the hints point to exists on the server, a single task shape (add a film), context at 32768 rather than 16384. The unseen-id guard (on in every cell) refused 6 writes in all 72 runs: 4 in Qwen's cell D, 1 in Gemma's D and 1 in Gemma's B; none in the cells with the second-iteration hints. Cell D's 3 of 6 for Qwen may owe something to it; the hint cells' gains do not. Tidepool was not rechecked: it has no OpenAPI spec, so `openapi_search` does not apply.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --fake-radarr --n 6 --label hints-B2-on-param`; add `--radarr-spec` for the spec-in-notes cells and `--no-write-hints` for the off cells. Offline tests: `tests/test_openapi_hints.py`, `tests/test_fake_radarr.py`.

## Does the stall stop cost passes? (#115, 2026-11-14)

- **Question.** In the Qwen 3.5 9B cell with the public spec and write hints (B2), 5 of 6 runs were stall-stopped and none passed. Was the stop cutting off a discovery that was still progressing?
- **Criterion, posted on #115 before the run.** The stop costs passes if the same cell with the stop off (`SMOLPAW_STALL_REPEATS=0`) passes at least 2 more than the 0 of 6 with it on.
- **Result.** With the stop off: 1 of 6 passed (0 of 6 with it on). Five runs hit the 13-step cap instead, using 71K to 90K input tokens each against 45K for the one pass. Criterion not met, so the stop is not what holds Qwen back here.
- **Offline read of the stopped runs' traces.** Of the 5 stalled runs, 4 repeated `openapi_search` or spec-fetch calls that returned results already seen, and 1 repeated 404s on guessed URLs. Two (runs 1 and 5) had already done the lookup before stalling, so they were close but did not reach the POST.
- **Change.** `tests/eval.py` now prints `STALL(<reason>)` on the run line and counts stalled runs in the cell summary.
- **Caveats.** n=6 per cell, one machine, one fixture; 1 against 0 is within noise.
- Reproduce: `SMOLPAW_STALL_REPEATS=0 .venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --fake-radarr --n 6 --label hints-B2-nostop`.

## Rung 3 against a real Radarr (#1, 2026-11-15)

- **Question.** Can a small local model add a film to a real Radarr, with the profile and root folder it had to look up itself? The first supervised attempts (by hand through the web page, the earlier harness) failed: 0 of 3 with Qwen 3.5 9B, one stopped-early Gemma 4 E4B run, models guessing the write's arguments.
- **Criterion, from PLAN.md's success criteria and the answers given before the run.** At least 2 of 3 runs adding exactly the requested film with an existing quality profile and root folder, on at least one model; checked by reading the library back, not from the model's answer. A run that hits the step cap does not pass, even if its write landed.
- **Setup.** `tests/eval.py --backend ollama --model <m> --real-radarr --allow-real-writes --n 3` (Ollama, MLX builds, 32K context, native history, step cap 12), against the owner's real Radarr (302 films at the start). notes.md held only the service line and its key variable, in an isolated temporary folder with the repo's `skills/` copied in (`api-discovery`), as in rung 1. The unseen-id guard (#102) and the `openapi_search` write hints (#112) were on, as in the build. Prompt: "Add the movie <title> (<year>) to Radarr." One film per run from a pool of six (`tests/real_radarr.py`) that resolve by exact title and year and were not already in the library. Approvals were scripted and nobody read the bodies: only `POST /api/v3/movie` for that run's film was approved, at most three attempts per run, and everything else that would ask was declined; a second check on the whole body ran just before each write. Stop rules (off-pool write, 401/403, six failed writes in a row) never fired.
- **Result.**

| Model | Runs | Added correctly | What happened |
|---|---|---|---|
| Gemma 4 E4B | 3 | **2 of 3** | Run 1: three HTTP 400s on the same film, no add, attempt cap reached (13 steps, step cap). Run 2: one 400, then a 201 (the verify line noted a folder-name difference, the profile and root folder were valid). Run 3: two 400s, then a 201 with matching fields. |
| Qwen 3.5 9B | 3 | **0 of 3** | Run 1: the right film was added on the second write (201, fields match), but the run went on to try shell commands (declined), repeated results and hit the step cap, so it does not pass. Run 2: stalled; two POSTs with no tmdbId in the body were declined by the approver. Run 3: stalled on repeated `openapi_search` calls, no write at all. |

- **What the runs show.**
  - Gemma's two passes took 8 and 11 steps, 64K and 97K input tokens, 109 and 171 seconds. Both passes started with a refused write (HTTP 400, nothing written) and recovered, so the model still tries a write before it has everything it needs, but now reads the error and corrects it.
  - The unseen-id guard refused no write in these six runs; no ids were guessed that it could catch. The send-time gate blocked none.
  - Qwen's three stalls came from repeated `openapi_search` and `http_request` results, as on the fake Radarr (RESULTS.md, #115). Its one correct add was lost to not stopping after success.
  - Nothing was downloaded: the three films added (Radarr ids 527 to 529) are monitored, have no files, and no queue entries appeared, so the "let Radarr search" setting did nothing in these runs. The owner removes the films by hand; the eval never deletes.
- **Caveats.** n=3 per model, one session, one Radarr library; with 2 of 3 and 0 of 3 the interval on each is wide, and the Gemma pass rate could easily be 1 of 3 on a rerun. Gemma ran first, so Qwen's films differed (Qwen's first film, The Man from Earth, was the one Gemma failed to add). The attempt cap of three is part of the setup: Gemma's run 1 might have passed with a fourth. The approver declined two Qwen bodies for having no tmdbId; Radarr would have refused them too, but that is a harness decision, not Radarr's. No run with the guard and hints off, so this does not show what they contribute. The scripted approval means the pass rate describes the models inside the narrow approver, not a user reading each body. Not comparable to the earlier by-hand attempts (different harness, prompt and approvals).
- Reproduce (writes to the Radarr in `.env`; remove the films it lists afterwards): `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --real-radarr --allow-real-writes --n 3 --label real-radarr`. Against the fake instead: `tests/fake_radarr.py 7899` and `--radarr-url http://127.0.0.1:7899 --radarr-films "Primer:2004,Moon:2009,Arrival:2016"`.

### Rung 3 with the unseen-id guard and the write hints off (Gemma 4 E4B, 2026-11-15)

- **Question.** Did the guard (#102) and the `openapi_search` write hints (#112) contribute to Gemma's 2 of 3 on the real Radarr?
- **Criterion, stated before the run (descriptive, not a merge decision).** 2 or more of 3 with both off: the evidence does not show they were needed. 1 or fewer: they may be contributing. At n=3 either reading is weak.
- **Setup.** As above with `--no-id-guard --no-write-hints`, same model and settings, the three pool films still unused (Beyond the Black Rainbow, Rubber, Timecrimes), so the films differ from the guards-on run.
- **First attempt, invalid.** 0 of 3, but every write (8 in all) was declined by the approver with "no tmdbId in the body", so none reached Radarr. Without the hints Gemma sent bodies with no `tmdbId`; in the guards-on run the same mistakes reached Radarr, whose HTTP 400 Gemma read and recovered from (both passes began that way). The approver had replaced Radarr's refusal with a bare DECLINED. Nothing was added. After seeing this result the approver was changed (`tests/real_radarr.py`): a body with no film id at all is now let through, and a body naming the film by imdbId or tvdbId alone is still declined. The guards-on results are unaffected for Gemma (the approver declined nothing in those three runs); two Qwen bodies had been declined for this reason in its guards-on run 2.
- **Result with the approver fixed: Gemma 0 of 3.** Each run sent one write, got HTTP 400, then searched the web or asked the user (no answer is available in an eval) and ended by reporting the film could not be added, naming the missing quality profile, path and root folder. 37K to 46K input tokens, 41 to 72 seconds, 1 to 2 parse errors per run. No write was declined or blocked, and nothing was added to the library.
- **Reading.** Against 2 of 3 with the guard and hints on, this fits the hints mattering: with them Gemma looked up the profile and root folder before or after its first 400 and corrected; without them it stopped after one 400. It does not separate the two: the guard never refused a write in the guards-on runs, so the hints are the likelier source, but both were switched off together. Different films, n=3 each, one session, so 2 of 3 against 0 of 3 is a suggestion, not a measured effect.
- **Not run: Qwen 3.5 9B.** Only three pool films were unused and the other three are the films the first run added, which are still in the library.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --real-radarr --allow-real-writes --no-id-guard --no-write-hints --n 3 --label real-radarr-guards-off` (writes to the Radarr in `.env` when a run succeeds; remove what it lists).


### Rung 3 against a real Radarr: Qwen 3.5 9B rerun with the fixed approver (#1, #117, 2026-11-15)

- **Question.** Does Qwen add a film to the real Radarr now that the scripted approver lets a body with no film id reach Radarr (so its refusal is the feedback)?
- **Criterion, descriptive.** Passes out of 3, by the eval's rule (the right film added, answer given, no step cap, no stall).
- **Setup.** As in "Rung 3 against a real Radarr" above (Ollama, 32K context, step cap 12, unseen-id guard and write hints on) with three new films not in the library: Pi (1998), Another Earth (2011), Upstream Color (2013). `--radarr-films "Pi:1998,Another Earth:2011,Upstream Color:2013"`, label `real-radarr-qwen-rerun`.
- **Result: 0 of 3, and no write reached Radarr in any run.** Runs 1 and 2 hit the step cap (13 steps) after searching the spec and calling `http_request` on read endpoints, ending with a description of how to add the film instead of an add; run 3 was stopped by the repeated-results rule after 6 steps (four `openapi_search` calls, then `fetch_page`). Nothing was added, so there was nothing to clean up.
- **Reading.** The earlier 0 of 3 had one correct add (at step 12 of 12); this rerun had none, so Qwen's real-Radarr failure is mostly not reaching the write within the step budget, and the approver was not the cause. Three runs, one session, one library.
- Reproduce (writes to the Radarr in `.env`; remove the films it lists afterwards): `.venv/bin/python tests/eval.py --backend ollama --model qwen3.5:9b --real-radarr --allow-real-writes --radarr-films "Pi:1998,Another Earth:2011,Upstream Color:2013" --n 3 --label real-radarr-qwen-rerun`.

### The guard and the write hints, one switch at a time (#118, 2026-11-15)

- **Question.** Which of the unseen-id guard (#102) and the `openapi_search` write hints (#112) matters? On the real Radarr Gemma went 2 of 3 with both on and 0 of 3 with both off, but they were switched off together.
- **Criterion, stated on #118 before the runs (descriptive).** A switch matters for a model if its cell passes 3 or more fewer of 12 than that model's baseline cell, run in the same session; 2 or fewer is within what n=12 can separate from noise.
- **Setup.** Fake Radarr (`tests/fake_radarr.py`), Primer, Moon and Arrival four times each (n=12 per cell), Ollama, 32K context, step cap 12, default config (the model finds the public Radarr spec through the `api-discovery` skill). Pass: the server holds exactly that film. Labels `ablate118-base`, `ablate118-no-hints`, `ablate118-no-guard`.

| Model | Baseline | `--no-write-hints` | `--no-id-guard` |
|---|---|---|---|
| Gemma 4 E4B | 11 of 12 (8.5 steps) | **0 of 12** (7.2 steps, 5 stalled) | 9 of 12 (8.2 steps) |
| Qwen 3.5 9B | 3 of 12 (11.5 steps, 5 capped) | 1 of 12 (7 capped) | 4 of 12 (5 capped) |

- **Gemma: the hints matter, the guard does not.** Removing the hints cost 11 passes, far past the criterion; removing the guard cost 2, inside it. The guard refused 3 writes in the no-hints cell and none in the others. No cell sent a POST with a wrong `tmdbId` for Gemma.
- **Qwen: neither shows an effect.** 3, 1 and 4 of 12 are within noise of each other; its failures are step-cap and stall runs in every cell, as in #117, so the switches cannot show up. One POST with a wrong `tmdbId` reached the server in the no-guard cell (none in the other two).
- **Reading.** This supports the earlier suggestion from the real Radarr that the hints, not the guard, carried Gemma's result. The guard is still cheap insurance (zero prompt cost, and it refused three guessed writes), but on this fixture it is not what makes writes succeed. Not measured: the real Radarr per switch (the fake already separates them for Gemma, so a real run would only spend films), and Qwen on the real Radarr with the switches off (Qwen does not reach the write with them on).
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --fake-radarr --n 12 --label ablate118-base`; add `--no-write-hints` or `--no-id-guard` for the other cells; same with `qwen3.5:9b`.

### First-call size now, and the offline budget check (#110, 2026-11-16)

- **Measured** with `tests/first_call_tokens.py --runs 1` (Ollama, empty notes.md, git-tracked skills, default web search): the whole first call is 4855 tokens on Qwen 3.5 9B and 4524 on Gemma 4 E4B (instructions alone 2906 and 2969). The figures in the earlier log were 4407 and 4085, so the first call has grown about 10% since that measurement (new tool descriptions and hint text since then); the 5000 budget is now about 3% away on Qwen. One run per model; the earlier runs showed the count repeats exactly.
- **Offline approximation.** The suite check counts characters of the request (19,265) and multiplies by a ratio fitted to those two figures (0.2434 tokens per character). The error against the two measured figures is -3.4% (Qwen) and +3.7% (Gemma), so it can see a growth of 3% or more of the whole, not a few tokens. Two models only, one prompt; a different tokenizer would need its own check.
- Reproduce: `.venv/bin/python tests/first_call_tokens.py --runs 1`, then `.venv/bin/python tests/test_prompt_budget.py`.

### A fake-Radarr task with headroom, calibrated (#119, 2026-11-16)

- **Why.** On the plain task (add Primer, Moon or Arrival) Gemma 4 E4B passed 11 of 12 and Qwen 3.5 9B 3 of 12 at baseline (#118), so a change could not clearly improve either, and the merge gate could not be met by improvement.
- **The task.** `tests/eval.py --fake-radarr --radarr-task hard`: "Add the movie <title> to Radarr with the <Ultra-HD, SD or HD-1080p> quality profile, in the root folder with the most free space." The fake (`tests/fake_radarr.py <port> hard`) serves three root folders with `freeSpace`; the roomiest, `/media/archive`, is neither first nor lowest id. Pass: the server holds exactly that film with that profile id and that folder (a wrong choice is a valid write to the server, so the eval's check, not the server, judges it).
- **Calibration rule, stated on #119 before the runs.** Keep it as a gate fixture if Gemma lands at 3 to 9 of 12; Qwen is reported but not required to land there.
- **Result (n=12 per model, Ollama, 32K context, step cap 12, guard and hints on, default config).** Gemma 6 of 12 (9.8 steps, 55K input tokens, 2 stalled, 3 capped); Qwen 5 of 12 (9.5 steps, 55K input tokens, 4 stalled, 5 capped). Both are inside the range the plain task could not offer: Gemma's 6 is the middle of the allowed band, and Qwen is above its plain-task 3 of 12. The failures are mostly no write at all (profile and folder `None`), then a few wrong folders for Gemma (up to 5 refused writes in one run).
- **Caveats.** One session, one model build, one seed of film order; Qwen scoring higher than on the plain task means the extra instructions help it as often as they hurt, which is itself worth knowing before comparing across tasks. Differences of 2 of 12 between cells are inside what this fixture separates from noise.
- Reproduce: `.venv/bin/python tests/eval.py --backend ollama --model gemma4:e4b --fake-radarr --radarr-task hard --n 12 --label hard119-base` (and `qwen3.5:9b`). Offline tests: `tests/test_fake_radarr.py`.

## The parked #117 experiments retried on the hard fixture (2026-11-16)

Both experiments failed the gate on the plain fake task at n=6 (see above). The hard task ([#119](https://github.com/aurora7795/smolpaw/issues/119)) has headroom, so each was rerun at n=12 per cell (Ollama, 32K context, guard and hints on). **Gate, stated before the run:** baseline Gemma 6/12, Qwen 5/12; an arm is worse if either model drops by 3 or more passes, a clear improvement if either gains 3 or more; merge only if neither is worse and one clearly improves. The rule was applied before seeing results.

| Arm | Gemma 4 E4B | Qwen 3.5 9B | Gate |
|---|---|---|---|
| Baseline | 6/12 | 5/12 | - |
| Repeated-result nudge + firmer DECLINED (`experiment/117-repeat-nudge`) | 8/12 (9.9 steps, 4 capped) | 5/12 (11.5 steps, 7 capped) | Not worse, but +2 is under the +3 bar: no merge |
| Forgiving `openapi_search` (`experiment/117-forgiving-search`) | 4/12 (10.6 steps, 4 capped) | 2/12 (11.2 steps, 6 capped) | Qwen -3: worse, no merge |

Caveats: n=12 per cell, so a difference of 2 is within noise; the nudge result is inconclusive, not negative. Qwen's step count and cap rate went up with both arms. Reproduce: check out each branch, then `.venv/bin/python tests/eval.py --backend ollama --model <model> --fake-radarr --radarr-task hard --n 12`.

## First call on LM Studio against Ollama (#135, 2026-11-17)

`tests/first_call_tokens.py --backend lmstudio` sends the same first request with `max_tokens=1` and reads `usage.prompt_tokens`, so the two runtimes can be compared. Both rows below are the current default prompt (`compact-final`, #130), empty notes.md, git-tracked skills, 32K context, MLX builds on LM Studio, 2 runs per figure (both runs agreed exactly on every figure).

| Model | Ollama, whole call | LM Studio, whole call | Difference | Instructions alone (both) | Without web_search (Ollama, LM Studio) |
|---|---|---|---|---|---|
| Qwen 3.5 9B | 2,709 | 2,751 | +1.6% | 760 | 2,616, 2,658 |
| Gemma 4 E4B | 2,346 | 2,370 | +1.0% | 791 | 2,265, 2,289 |

The two runtimes tokenize the same request within about 2 percent, so the first-call figures in the #125 section (taken on Ollama) carry over to LM Studio, and the tool schemas cost the same on both (the instructions-alone figure is identical). Against the 10,235 characters in `tests/prompt_budget.json`, LM Studio gives 0.269 tokens per character for Qwen and 0.232 for Gemma, within 10 percent of the 0.2471 the budget test uses; the budget's own measured figures (2,693 and 2,330) are the compact prompt without the #130 line. One machine, one session.

Reproduce: `.venv/bin/python tests/first_call_tokens.py --backend lmstudio --runs 2`, and without `--backend` for Ollama.


## Housekeeping and read-only on LM Studio with the default prompt (#136, 2026-11-18)

#125 ran the housekeeping chores and read-only scheduled cases on Ollama only, at n=3. This reruns them on LM Studio (MLX builds, 32K context, one slot, native history), smolagents' prompt (`default`) against the shipped `compact-final`, interleaved by case: housekeeping 8 cases at n=4 (32 runs per arm), read-only 5 cases at n=5 (25 runs per arm), 400s per-run timeout. One machine, one session.

**Pass criterion, stated before the run (issue #136), applied as written:** neither model worse beyond noise, meaning no pooled family with a one-sided Fisher exact p below 0.1 for the default prompt being better.

Passes over runs, default then compact-final (`tests/compare_runs.py`; p is for "default better"):

| Family | Gemma 4 E4B | p | Qwen 3.5 9B | p |
|---|---|---|---|---|
| Housekeeping, 8 cases | 15/32, 12/32 | 0.31 | 12/32, 16/32 | 0.90 |
| Read-only, 5 cases | 10/25, 9/25 | 0.50 | 7/25, 5/25 | 0.37 |

Medians (default, compact-final), mean steps, input tokens per run, stalled runs:

| Family | Model | Median s | Steps | Input tokens | Stalled |
|---|---|---|---|---|---|
| Housekeeping | Gemma | 120, 100 | 5.2, 3.7 | 26.3K, 11.0K | 7, 12 |
| Housekeeping | Qwen | 135, 85 | 6.5, 5.0 | 36.8K, 19.9K | 6, 8 |
| Read-only | Gemma | 81, 62 | 4.7, 3.6 | 21.9K, 9.0K | 8, 10 |
| Read-only | Qwen | 44, 37 | 6.8, 5.8 | 35.7K, 17.5K | 18, 20 |

Runs with `timed_out` set: Qwen 7 default and 3 compact-final, Gemma 1 default and 0 compact-final. One Qwen read-only outlier (`write_summary`, default arm) took 347s against a 44s median.

**Verdict.** The criterion is met: no family has the default better at p below 0.1, so compact-final stays the default on LM Studio for both models. Compact-final halves input tokens (about 50 percent on both models) and is faster in every row. Pass rates are statistically indistinguishable; Gemma leans slightly toward the default (25/57 against 21/57 overall) with more stalled housekeeping runs under compact-final (12 against 7), as in #131, and Qwen leans toward compact-final on housekeeping. Read-only pass rates are low for both models under both prompts (Qwen 7/25 and 5/25), so that family is limited by the model, not the prompt.

Caveats: n=25 to 32 per arm, so only a difference of about 30 points could reach p below 0.1; this is "no regression found by the rule", not "no regression". One machine, one session. The pass counts are the evaluator's checks against the real files and logs, not the model's final answer.

Reproduce: `tests/run_136_matrix.sh` (about 5 hours), then `.venv/bin/python tests/compare_runs.py --arm default='logs/eval-*sp136-<model>-default.json' --arm final='logs/eval-*sp136-<model>-compact-final.json' --family housekeeping` (and `--family readonly`).

### Why the read-only pass rates are low (#143, 2026-11-18)

The #136 read-only family passed Qwen 3.5 9B 7/25 (default prompt) and 5/25 (compact-final), and Gemma 4 E4B 10/25 and 9/25, and the write-up called it model-limited without reading the runs. This sorts every non-passing run in the same 20 logs by its first applicable reason (`tests/classify_failures.py`: timed out, step cap, stalled, no answer, check failed, answer missing a pattern). Counts are over the four cases that ask for a write (write_summary, read_and_save, append_log, delete_old): 40 runs per model, both prompts pooled. The fifth case, the read-only control, passed 20/20 (both models, both prompts, n=5 each), so reading files and answering is not the problem.

| | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| Passed | 2 | 9 |
| Stalled by the repeated-results rule or the failing-call rule | 36 | 18 |
| of which no answer (in the eval) | 33 | 14 |
| Answer missing the decline wording | 0 | 10 |
| Step cap | 1 | 2 |
| Kept asking after being declined (check) | 1 | 1 |

**Verdict: neither the fixture nor the checker is at fault.** No run in the 20 logs changed a file (every check that ran found the files as built, so a declined write was never let through). The stalled runs are models that were declined and tried again by another route: 135 `run_shell` calls were made in these cases, 11 (Gemma) and 13 (Qwen) auto-allowed, the rest declined. Gemma's 72 declined shell calls are all writes (`echo ... >> log.txt`, `printf`, `rm`, `mv`), made after or instead of the declined `write_file`/`edit_file`. Qwen's 63 are 37 writes and 26 read-like checks written with `||` or `2>/dev/null` (for example `ls -la log.txt 2>/dev/null || echo "File not found"`), which the read-only allow rule does not cover, so a scheduled run declines them too. After a few of these the stall rule ends the run. In this eval, which calls the agent directly, a stopped run has no answer, so the pass check fails even though the files are untouched; a real scheduled run goes through `run_request`, which tells the user `STOPPED EARLY: ... Last tool result -> DECLINED...` and lists the declined actions, but still not the model's own account of what it could not do. This is the mechanism of #90 (a declined delete retried until the stall rule), now seen on all four write cases. The task checks (files unchanged, at most two declined actions) are what the cases are meant to test.

Gemma's ten "answer missing" runs, by what the answer says: five give the requested result and are silent about the write that was declined, three say they "attempted" it with no outcome, and two say it was saved or written (false: the file was never changed). The decline wording is not too narrow: none of the ten says the change was not made.

What this means for the merge gate: the read-only family measures "report the declined write, do not retry it", a behaviour Qwen almost never shows (2/40) and Gemma shows about a quarter of the time (9/40). A change that does not touch it cannot move this family, which is why #136 could not separate the prompts on it.

Caveats: one session, the same 20 logs as #136, first-reason classification (a run that stalled with three or more declined actions also fails the kept-asking check; it is counted once, as stalled; two Qwen runs carry the stall flag but are counted as a pass and a step cap, so the stall flag alone gives 38). The classes describe what the runs did, not why the model chose it.

Reproduce: `.venv/bin/python tests/classify_failures.py 'logs/eval-*readonly-*sp136*.json'` (the 20 logs are local and gitignored, so a rerun of `tests/run_136_matrix.sh` regenerates them).

## A decline text that says "report, do not retry" for unattended runs (#90, 2026-11-18)

**Change.** In an unattended run (a schedule in the web harness, or `agent.py -p`), a declined action now returns `DECLINED_UNATTENDED` ("nobody is here to approve this, so it was not done and will not be. Do not retry it or do the same thing another way (another tool, a shell command). Finish by telling the user what you could not do.") instead of the interactive `DECLINED` text, which ends "Try another approach or call ask_user." That sentence invites the retry through `run_shell` that #143 found. Only the text changes: what is blocked, the auto-allow list, path scoping and redaction are untouched, and interactive runs keep the old text. Nothing is added to the system prompt.

**Criterion, stated on #90 before the run.** Per model, pooled over the four read-only write cases (`write_summary`, `read_and_save`, `append_log`, `delete_old`, n=5 each) and the housekeeping `cleanup_proposal` case (n=10): neither model worse beyond noise (one-sided Fisher p below 0.1 for the old text being better), and at least one clearly better. The read-only control (plain reading, n=5) must stay at 5/5.

**Setup.** LM Studio, `--ctx 32768`, `--run-timeout 400`, compact-final prompt, one session. `--declined-text legacy` against `--declined-text report` (the default), arms run back to back per case.

| | Old text | New text | One-sided Fisher p, new better |
|---|---|---|---|
| Qwen 3.5 9B, 30 runs per arm | 1 passed, 28 stalled | 7 passed, 24 stalled | 0.026 |
| Gemma 4 E4B, 30 runs per arm | 9 passed, 13 stalled | 21 passed, 5 stalled | 0.002 |
| Read-only control, 5 runs per model | 5/5 both models | 5/5 both models | 1.000 |

By case (old text to new text). Qwen: `write_summary` 0 to 1 of 5, `read_and_save` 0 to 2, `append_log` 0 to 0, `delete_old` 0 to 0, `cleanup_proposal` 1 to 4 of 10. Gemma: `write_summary` 0 to 4, `read_and_save` 2 to 4, `append_log` 0 to 3, `delete_old` 2 to 5, `cleanup_proposal` 5 to 5 of 10.

**Verdict: the criterion is met, so the text is merged.** Neither model is worse, both are better at p below 0.1 (Gemma by a wide margin), and the control is unchanged. The rule was fixed before the run.

Caveats: n=30 per arm per model, one session, one prompt. Qwen is still low (7 of 30; it stalled in 24 of 30 runs), and `append_log` and `delete_old` did not move for it, so the text helps but does not make Qwen reliable here. `cleanup_proposal` did not change for Gemma. Pooled cases are not independent of the fixture's wording. The stall rule is unchanged ([#142](https://github.com/aurora7795/smolpaw/issues/142)). Real scheduled runs were not measured, only the eval's scripted unattended mode.

Reproduce: `tests/run_90_matrix.sh` (about 3 hours), then `.venv/bin/python tests/compare_runs.py --arm report='logs/eval-*sp90-<model>-report.json' --arm legacy='logs/eval-*sp90-<model>-legacy.json'` (the control is in the same logs; leave it out of the pooled comparison by pointing the globs at the other cases).

## Hard fake-Radarr baseline under compact-final, and the repeat-nudge retest (#137, #138, 2026-11-19)

**Setup.** Ollama, `--ctx 32768`, step cap 12, `--run-timeout 400`, `--fake-radarr --radarr-task hard`, guard and write hints on, n=12 per cell, one overnight session (`tests/run_137_139_matrix.sh`). Arms: `cf` (compact-final, the default), `default` (smolagents' prompt, `--system-prompt default`) and `nudge` (compact-final plus the #117 repeated-result nudge and firmer DECLINED text, from `experiment/117-repeat-nudge` cherry-picked onto current `main`; the cherry-pick conflicted with #90 and #95 and was resolved by keeping both).

**Criterion for #138, stated on the issue before the run.** The baseline is the `cf` arm. An arm is worse if either model drops 3 or more passes; a clear improvement is a gain of 3 or more for either model. Merge only if neither is worse and one clearly improves; at +2 or less, record and close without merging.

| | cf (baseline) | default prompt | nudge |
|---|---|---|---|
| Gemma 4 E4B, passed | 7/12 (2 stalled, 8.7 steps, 30K input tokens) | 5/12 (1 stalled, 174s mean) | 8/12 (0 stalled) |
| Qwen 3.5 9B, passed | 7/12 (4 stalled, 9.8 steps, 39K input tokens) | 10/12 (0 stalled, 59K input tokens) | 6/12 (2 stalled) |

**#137: the baseline.** Gemma lands at 7 of 12, inside the 3 to 9 band set in #119, so the hard fixture stays usable as a gate fixture. Qwen is at 7 of 12 (5 of 12 with the old prompt). compact-final against the default prompt: Gemma 7 against 5 (one-sided Fisher p=0.34), Qwen 7 against 10; neither is below p 0.1. The default prompt used twice the input tokens (Gemma 60K against 30K, Qwen 59K against 39K).

**#138: the verdict is not to merge.** Gemma +1, Qwen -1 against the baseline: no model is worse by 3 and neither gains 3, so there is no clear improvement. The rule was fixed before the run. `experiment/117-repeat-nudge` stays unmerged.

Caveats: n=12 per cell, one session, so differences of 3 are within noise. Qwen's 10 of 12 on the default prompt (three more than compact-final, p about 0.2 in that direction) was not a planned comparison and does not meet any pre-stated rule; it matches the LM Studio matrix (#136) only in that Qwen's compact-final stalls are frequent here (4 of 12). The nudge arm ran from a worktree of `main`, so the `nudge` and `cf` arms differ only by the experiment commit.

Reproduce: `tests/run_137_139_matrix.sh`, then `.venv/bin/python tests/compare_runs.py --arm cf='logs/eval-*r137-<model>-cf.json' --arm nudge='logs/eval-*r138-<model>-nudge.json'`.

## The failing-steps stall switch under compact-final (#139, 2026-11-19)

**Setup.** Ollama, `--ctx 32768`, step cap 12, `--run-timeout 400`, compact-final prompt, one overnight session (`tests/run_137_139_matrix.sh`). `SMOLPAW_STALL_FAILS=3` (stop after three failing steps in a row, #77) against the switch off, arms run back to back per case, n=3 per cell: the eight tracking cases (five edit cases, `edit_one_section`, `append_keep_all`, `read_three_report`) and `--counting-home`.

**Criterion, stated on #139 before the run.** Adopt as a default only if neither model drops 2 or more passes in any pooled family and the runs it ends were failing anyway. Otherwise it stays off. Families pooled here: the five edit cases (15 runs per arm), the other three tracking cases (9) and `--counting-home` (6).

| Passed, switch off to `STALL_FAILS=3` | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|
| Five edit cases (15 runs) | 15 to 14 | 14 to 14 |
| Other tracking cases (9 runs) | 4 to 6 | 8 to 6 |
| `--counting-home` (6 runs) | 2 to 0 | 4 to 6 |

By case, the ones that moved: Gemma `append_keep_all` 1 to 3, `edit_duplicate_passage` 3 to 2, `--counting-home` 2 to 0; Qwen `append_keep_all` 2 to 0 (the one run that stalled under the switch was a pass without it), `--counting-home` 4 to 6.

**Verdict: the criterion is not met, so the switch stays off.** Gemma drops 2 on `--counting-home` and Qwen drops 2 on the other tracking cases. The rule was fixed before the run. The #77 regression case, `edit_duplicate_passage`, did not repeat at its old size (3 to 1 of 3 then; 3 to 2 of 3 for Gemma now, no change for Qwen), but the drops elsewhere are the same size.

Caveats: n=3 per case and 6 to 15 per pooled family, one session, so every difference here is within noise (no one-sided Fisher p comes near 0.1); the criterion is a count threshold, not a test, and a 2-pass drop on 6 or 9 runs is easy to produce by chance, as are the gains (Gemma `append_keep_all` 1 to 3). The "stalled" flags in the logs include the repeated-results rule, which is on in both arms, so they do not isolate the switch. Gemma's `read_three_report` was 0 of 3 in both arms (see #89).

Reproduce: `tests/run_137_139_matrix.sh`; logs have the labels `r139-<model>-off` and `r139-<model>-fails3`.

## Screening Ternary-Bonsai-2-9B with the new staged screen (#126, #7, 2026-11-19)

**Setup.** `tests/screen_model.py` (thresholds in the script, fixed before any model was screened: tools stage at least 7 of 9 correct with no invented tool or malformed arguments; Tidepool `easy` and `hint` at least 2 of 3 each), LM Studio, 32K context, one session. The model is PrismML's `Ternary-Bonsai-2-9B-Q2_0.gguf` (2.56 GB, a ternary build of Qwen 3.5 9B; checksum matches the published SHA256SUMS), loaded by LM Studio's llama.cpp engine 2.56.0. Calibration: Gemma 4 E4B and Qwen 3.5 9B (MLX), which had to pass. A known-bad model was not screened (Nanbeige is not installed here), so the screen's ability to fail a model is shown only by its unit tests, not on a real model. A first version used a 200-token cap on the plain reply and failed Gemma because it spent the cap on hidden reasoning; the cap is now 2,000.

| Stage | Gemma 4 E4B | Qwen 3.5 9B (MLX) | Ternary Bonsai 2 9B (Q2_0) |
|---|---|---|---|
| loads (prompt tokens with 3 tools) | pass, 204 | pass, 438 | pass, 438 |
| tools, correct of 9 | 8 | 7 | 8 |
| Tidepool easy, hint (of 3 each) | 3, 2 | 3, 3 | 2, 2 |
| time | 457s | 306s | 239s |

**Result.** Bonsai passes all three stages: it loads in LM Studio, called no tool that was not offered and produced no malformed arguments in 9 tool tasks (the old Bonsai 8B invented tools, #7). The full matrix (stage 4) has not been run. Caveats: n=3 per cell detects only large gaps, so Bonsai's 2 of 3 on Tidepool is not distinguishable from Qwen's 3 of 3; the Qwen 3.5 9B here is the MLX build while Bonsai is a GGUF, so the engines differ.

Reproduce: `.venv/bin/python tests/screen_model.py --backend lmstudio --model ternary-bonsai-2-9b`.

### Bonsai 2 9B on the hard fake Radarr (2026-11-19)

**Criterion, stated before the run.** Bonsai is worth the wider matrix if it is within 2 passes of Qwen 3.5 9B on the same engine at n=12; a clear improvement is +3 or more. Setup: LM Studio (llama.cpp 2.56.0 for Bonsai, MLX for Qwen), `--ctx 32768`, step cap 12, `--run-timeout 400`, `--fake-radarr --radarr-task hard --n 12`, compact-final prompt, back to back in one session (`tests/run_bonsai_hard.sh`).

| | Qwen 3.5 9B (MLX) | Ternary Bonsai 2 9B (Q2_0) |
|---|---|---|
| Passed | 9/12 | 2/12 |
| Stalled | 2 | 2 |
| Mean steps, input tokens, seconds | 9.1, 34K, 98 | 9.2, 33K, 62 |

**Verdict: not met (7 passes below), so no wider matrix.** Bonsai's failures: 4 runs ended with no answer because LM Studio rejected a tool call the model produced ("the model produced output that does not match the expected peg-native format", returned to the client as HTTP 400, then an `AgentGenerationError`); 3 reported a write that put the film in the wrong folder (`/media/films` rather than the one with the most free space) or left a field out; 2 stalled on repeated results; 1 hit the step cap. It passed the screen's single-call tool tasks (8 of 9) but did not hold a well-formed tool call through a multi-step task, which is the weakness the old Bonsai 8B showed (#7). The 4 malformed calls would be candidates for the tolerant parser in [#107](https://github.com/aurora7795/smolpaw/issues/107).

Caveats: n=12, one session; the engines differ (a GGUF on llama.cpp against an MLX build), so part of the gap could be the engine or the strict tool-call parser rather than the weights; only the Q2_0 pack was tried (the faster PQ2_0 and PTQ1_0 packs need PrismML's llama.cpp fork); no sampling settings from the model card were applied (the 9B card's recommended values were not checked). Qwen's 9 of 12 here compares with 7 of 12 on Ollama (#137), a gap of 2 that is within noise.

### Bonsai 2 9B on Ollama, hard fake Radarr (2026-11-19)

**Criterion, stated before the run (as for the LM Studio run).** Worth the wider matrix if within 2 passes of Qwen 3.5 9B at n=12; +3 or more is a clear improvement. Setup: Ollama, 32K context, step cap 12, `--run-timeout 400`, `--fake-radarr --radarr-task hard --n 12`, compact-final prompt, both models back to back (`tests/run_bonsai_hard_ollama.sh`). Bonsai is the same `Ternary-Bonsai-2-9B-Q2_0.gguf`, imported with `ollama create` (Ollama 0.40.16, llama.cpp runner, chat template read from the GGUF). The model screen on Ollama: loads, tools 9 of 9 correct with no invented or malformed calls (8 of 9 on LM Studio).

| | Qwen 3.5 9B | Bonsai 2 9B (Q2_0) |
|---|---|---|
| Passed | 5/12 | 3/12 |
| Stalled / hit the step cap | 4 / 3 | 0 / 6 |
| Wrong write (field missing) | 0 | 3 |
| No answer (generation error) | 0 | 0 |
| Mean steps, input tokens, seconds | 9.9, 39K, 91 | 11.2, 43K, 84 |

**Verdict: the criterion is met by 2 passes, narrowly (3 against 5, one-sided Fisher p well above 0.1), so the wider matrix is allowed but the case for it is weak.** The engine mattered for the failure type: on LM Studio 4 of 12 Bonsai runs ended on a tool call its parser rejected; on Ollama none did, and Bonsai's failures are the step cap (6 runs) and writes with a field missing (3). Qwen itself scored 9/12 on LM Studio's MLX build and 5/12 here (7/12 on Ollama in #137), so the engine moves a 9B model's result by as much as the difference being measured. Speed: Bonsai was about the same per run on Ollama (84s against 91s; 7.5s against 9.2s per step), unlike its 38% advantage over MLX Qwen on LM Studio.

Caveats: n=12, one session; Qwen's 5/12 is at the low end of its range, which makes the gap look smaller; Bonsai's 6 step-cap runs suggest it takes more steps than Qwen to the same result, so a larger step cap might change its score (not tried); only the Q2_0 pack was tried.

### Bonsai 2 9B with the step cap raised to 20 (2026-11-19)

**Why and criterion, stated before the run.** Six of Bonsai's 12 runs hit the step cap of 12 on Ollama. Criterion: Bonsai within 2 passes of Qwen 3.5 9B at n=12; if Bonsai gains 3 or more over its cap-12 result (3/12), the cap was limiting it. Setup as the Ollama run above, but `--max-steps 20 --run-timeout 600` (`tests/run_bonsai_cap20.sh`), both models back to back in one session.

| | Qwen 3.5 9B | Bonsai 2 9B (Q2_0) |
|---|---|---|
| Passed | 6/12 | 5/12 |
| Stalled by the repeated-results rule | 6 | 5 |
| Step cap / wrong write | 1 / 0 | 0 / 2 |
| Mean steps, input tokens, seconds | 12.8, 56K, 98 | 9.6, 37K, 65 |

**Verdict.** Bonsai is 1 pass behind Qwen, inside the 2-pass criterion. Its gain from the higher cap is 2 passes (3 to 5), under the 3 set for "the cap was limiting it", so that is not established. The six runs that hit the cap at 12 mostly ended at the stall rule at 20 (5 stalled), i.e. they were looping on repeated results, not simply short of steps. Bonsai used about a third fewer steps and tokens than Qwen here and ran 34% faster per run (65s against 98s), the speed advantage seen on LM Studio, which the cap-12 Ollama run did not show.

Caveats: n=12, one session; Qwen's pass counts on this task across today's runs are 5, 6, 7 and 9 of 12 (engine, cap and session all differ), so differences of 1 or 2 passes are noise; Bonsai's step-cap-12 result and this one are different runs of the same model, so their 3 and 5 also differ by chance alone; only the Q2_0 pack was tried.

### Screening Granite 4.2 8B (#126, 2026-11-19)

Same screen and thresholds as above, Ollama, 32K context, `granite4.2:8b` (Q4_K_M, 5.3 GB). A first run failed the `loads` stage with an empty reply: with tools offered Granite answers by calling `final_answer`, as the screen's system prompt says, so `content` is empty. That was a flaw in the screen (it read only `content`), fixed by reading the `final_answer` answer as the reply, with a test; the earlier screens (Gemma, Qwen, Bonsai) gave non-empty content and are unaffected.

| Stage | Granite 4.2 8B |
|---|---|
| loads (prompt tokens with 3 tools) | pass, 421 |
| tools, correct of 9 | 9, no invented or malformed calls |
| Tidepool easy, hint (of 3 each) | 2, 3 |
| time | 524s |

**Result.** It passes all three stages, so it is worth the full matrix; that has not been run. At n=3 per cell the screen only separates large gaps. Reproduce: `.venv/bin/python tests/screen_model.py --backend ollama --model granite4.2:8b`.
