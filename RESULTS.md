# SmolPaw results

Measured 2026-10-23 to 2026-10-24 on a 16GB Apple Silicon Mac with LM Studio (and Ollama where a section says so). Samples are small (usually 3 runs per cell), so read these as signals, not rates. Prompt for rung 1: "What is in my Radarr download queue? Just look, don't change anything."

## Summary

- Long files break both working models (#87, n=3 per cell, Ollama): editing or appending to a file longer than the 4,000-character read clip passed 0 of 12 runs, mostly because the model wrote back the clipped view it had seen and said nothing was lost; reporting figures from long files passed 3 of 6. With a paged `read_file` (#86): edit and append 1 of 12, reading 3 of 6, all within noise. With `edit_file` added (#72): edit and append 10 of 12, reading 2 of 6. On five harder edit cases, same session, `edit_file` 24 of 30 runs against 0 of 30 without it. See "Do small models keep track of what they read and write?".
- A lean harness with generic tools works with small local models, but only some of them. Gemma 4 E4B and Qwen 3.5 9B can follow a skill and discover an unseen API. Bonsai 8B (ternary) cannot do discovery. Nanbeige 3B produced garbage under LM Studio.
- Harness fixes mattered as much as model choice. Inlining skills, warning on HTML responses and clearer tool errors took rung 1 from 3 of 6 to 6 of 6 across the two working models.
- OpenClaw's prompt is still about 5.5 to 5.9 times larger than SmolPaw's (about 24K tokens against 4.1K to 4.4K on the first call, measured 2026-10-26; it was about 3K in early builds, before more tools were added). Locally, reading 24K tokens takes about 40s (Gemma) to 115s (Qwen) per call, against roughly 7s to 20s for SmolPaw's current prompt, which is the efficiency gap this project is aiming at.
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
