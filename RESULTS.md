# Smolpaw results

Measured 2026-10-23 to 2026-10-24 on a 16GB Apple Silicon Mac with LM Studio (and Ollama where a section says so). Samples are small (usually 3 runs per cell), so read these as signals, not rates. Prompt for rung 1: "What is in my Radarr download queue? Just look, don't change anything."

## Summary

- A lean harness with generic tools works with small local models, but only some of them. Gemma 4 E4B and Qwen 3.5 9B can follow a skill and discover an unseen API. Bonsai 8B (ternary) cannot do discovery. Nanbeige 3B produced garbage under LM Studio.
- Harness fixes mattered as much as model choice. Inlining skills, warning on HTML responses and clearer tool errors took rung 1 from 3 of 6 to 6 of 6 across the two working models.
- OpenClaw's prompt is roughly 8x larger than Smolpaw's (about 24K tokens against about 3K on the first call). Locally, reading 24K tokens takes about 40s (Gemma) to 115s (Qwen) per call, against 5s to 13s for 3K, which is the efficiency gap this project is aiming at.
- Discovery held up on harder variants of the invented API: 17 of 18 runs passed (hint, detail, paged).
- Ollama works as a second runtime. At 16K, Gemma passed 13 of 15 and Qwen 12 of 15 cleanly across rung 1 and the Tidepool variants, against 14 and 15 on LM Studio; most of the gap is the `detail` variant. Gemma was 2 to 5 times faster on Ollama.

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

## Prefill cost on this Mac (`tests/prefill_timing.py`)

Time to read a prompt of random words (one output token requested), 32K context, no prompt-cache help:

| Prompt tokens (about) | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| 2K | 8.4s (228 tok/s) | 3.1s (596 tok/s) |
| 6K | 25.8s (225 tok/s) | 9.3s (613 tok/s) |
| 11K | 54.2s (211 tok/s) | 18.8s (596 tok/s) |
| 23K | 114s (201 tok/s) | 41s (548 tok/s) |

Reading OpenClaw's roughly 24K-token prompt would take about 2 minutes per call on Qwen and about 45 seconds on Gemma, and its task needed 3 model turns, so roughly 6 minutes and 2 minutes of prefill alone without caching. Smolpaw's roughly 3K-token first call costs about 13s and 5s. Caveat: the test used unique prompts. A server that caches a stable prompt prefix between calls (OpenClaw's prompt is mostly constant) could reduce this a lot; that has not been measured, nor has memory use.

The table above is LM Studio. A two-size check of Qwen on Ollama (`qwen3.5:9b`, MLX `nvfp4`, 32K context, one run each) gave 8.9s at 1,911 tokens (215 tok/s) and 27.4s at 5,810 tokens (212 tok/s), close to LM Studio's 228 and 225 tok/s for the same prompts. Gemma and the larger sizes were not run on Ollama.

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

For comparison, Smolpaw's first call is about 2.9K tokens. A local model would also have to read an OpenClaw-sized prompt on every call; that prefill time has not been measured. I did not see which commands the `exec` calls ran (the audit log is metadata-only).

## Models

| Model | Verdict |
|---|---|
| Gemma 4 E4B (MLX 4-bit, 6.86 GB) | Best so far. Clean structured tool calls. Slow final steps (47 to 70s on PokeAPI), probably from reasoning mode. |
| Qwen 3.5 9B (MLX, 5.98 GB) | Good once the harness fixes were in. Needs the clear tool errors; wanders without them. |
| Ternary Bonsai 8B (MLX, 2.32 GB) | Good at guided execution of a known flow, poor at discovery; invents tools. Candidate for a cheap "execute" tier. |
| Qwen 3.5 9B (Ollama `qwen3.5:9b`, MLX nvfp4, 7.6 GB) | 12 of 15 clean at 16K; weaker than on LM Studio on `detail` (step cap) and once on `paged`. |
| Gemma 4 E4B (Ollama `gemma4:e4b`, MLX nvfp4, 9.5 GB) | 13 of 15 at 16K and 2 to 5 times faster than on LM Studio; both failures on `detail`. Same tool-call copying as under LM Studio ([#14](https://github.com/aurora7795/smolpaw/issues/14)). |
| Nanbeige 4.2 3B OptiQ (MLX, 3.32 GB) | Unusable as loaded: at temperature 0 via the API it emits repeated junk instead of an answer. LM Studio marks it as not trained for tool use. Possible runtime or quant incompatibility (MLX engine 1.13.1); a GGUF build is untested. |

## Corrections

An earlier summary in this project overstated the Radarr wrapper-tool results ("9 of 9" and "11 of 11"). The counts in the table above are the accurate ones.

The first write-up of the Ollama spike called Ollama's default `qwen3.5:9b` and `gemma4:e4b` tags GGUF builds. On this Mac they are MLX builds (`nvfp4`), so the spike compared two MLX runtimes with different quantisations, not MLX against GGUF. The registry serves a GGUF-style manifest to a plain HTTP request for the same tags, so check `ollama show <tag>` (format and runner) after pulling rather than trusting the tag name.

The same write-up said Ollama chose a 32K context from available memory on this Mac. The 32K came from the Ollama app's own Context length setting, which the app passes to its server and which overrides `OLLAMA_CONTEXT_LENGTH` set through `launchctl`.
