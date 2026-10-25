# SmolPaw results

Measured 2026-10-23 to 2026-10-24 on a 16GB Apple Silicon Mac with LM Studio (and Ollama where a section says so). Samples are small (usually 3 runs per cell), so read these as signals, not rates. Prompt for rung 1: "What is in my Radarr download queue? Just look, don't change anything."

## Summary

- A lean harness with generic tools works with small local models, but only some of them. Gemma 4 E4B and Qwen 3.5 9B can follow a skill and discover an unseen API. Bonsai 8B (ternary) cannot do discovery. Nanbeige 3B produced garbage under LM Studio.
- Harness fixes mattered as much as model choice. Inlining skills, warning on HTML responses and clearer tool errors took rung 1 from 3 of 6 to 6 of 6 across the two working models.
- OpenClaw's prompt is roughly 8x larger than SmolPaw's (about 24K tokens against about 3K on the first call). Locally, reading 24K tokens takes about 40s (Gemma) to 115s (Qwen) per call, against 5s to 13s for 3K, which is the efficiency gap this project is aiming at.
- Discovery held up on harder variants of the invented API: 17 of 18 runs passed (hint, detail, paged).
- Sending earlier tool calls back as native `tool_calls` instead of smolagents' text cut parse errors by about four times (19 to 5 across 48 Ollama runs) and raised passes from 19 to 23 of 24, with no cost in steps or time. A recheck with the actual error text shows the remaining rare errors are a different, generic issue (the model skipping a tool call, not copying history) (#14).
- On Ollama the default MLX builds beat the GGUF ones on speed (Gemma reads prompts about twice as fast) with the same pass rates (#16). With native history at 32K, the earlier Ollama weakness on Tidepool `detail` is gone: 11 of 12 on each runtime (#15).
- Ollama works as a second runtime. At 16K, Gemma passed 13 of 15 and Qwen 12 of 15 cleanly across rung 1 and the Tidepool variants, against 14 and 15 on LM Studio; most of the gap is the `detail` variant. Gemma was 2 to 5 times faster on Ollama.
- Converting web pages to text instead of returning raw HTML turned a 0 of 3 failure (both models, step-capped or giving up on the markup) into 3 of 3, in 2 to 4 steps instead of 7 to 13, and cut input tokens by 6x (Gemma) to 83x (Qwen, which otherwise burns the whole 32K context on one clipped HTML blob) (#23).
- Rung 3, a real supervised Radarr write, is not yet passing on either model tried (#1): 0 of 3 real-movie attempts with Qwen, one stopped-early Gemma attempt that also failed. Every attempt was safely contained (nothing was ever added to Radarr), but both models tend to guess a write's arguments before looking them up, and avoid or misuse the `openapi_search` tool they are told to use (Qwen with shell spelunking, Gemma by calling an unrelated external API with a placeholder key).
- Rung 4, an unrelated local task (summarise text files in workspace into summary.md), passed 6 of 6 across both models (3 of 3 on Qwen 3.5 9B, 3 of 3 on Gemma 4 E4B, 19 to 51s) (#3). Neither model hallucinated API or HTTP requests; both used read-only shell / read_file, handled the write confirmation, and produced accurate summaries.

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

Reading OpenClaw's roughly 24K-token prompt would take about 2 minutes per call on Qwen and about 45 seconds on Gemma, and its task needed 3 model turns, so roughly 6 minutes and 2 minutes of prefill alone without caching. SmolPaw's roughly 3K-token first call costs about 13s and 5s. Caveat: the test used unique prompts, so no cache could help; a stable prefix is much cheaper (next section). Memory use was not measured.

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

For comparison, SmolPaw's first call is about 2.9K tokens. A local model would also have to read an OpenClaw-sized prompt on every call; that prefill time has not been measured. I did not see which commands the `exec` calls ran (the audit log is metadata-only).

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
