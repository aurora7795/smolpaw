# Smolpaw results

Measured 2026-10-23 to 2026-10-24 on a 16GB Apple Silicon Mac with LM Studio. Samples are small (usually 3 runs per cell), so read these as signals, not rates. Prompt for rung 1: "What is in my Radarr download queue? Just look, don't change anything."

## Summary

- A lean harness with generic tools works with small local models, but only some of them. Gemma 4 E4B and Qwen 3.5 9B can follow a skill and discover an unseen API. Bonsai 8B (ternary) cannot do discovery. Nanbeige 3B produced garbage under LM Studio.
- Harness fixes mattered as much as model choice. Inlining skills, warning on HTML responses and clearer tool errors took rung 1 from 3 of 6 to 6 of 6 across the two working models.
- OpenClaw's prompt is roughly 8x larger than Smolpaw's (about 24K tokens against about 3K on the first call). Locally, reading 24K tokens takes about 40s (Gemma) to 115s (Qwen) per call, against 5s to 13s for 3K, which is the efficiency gap this project is aiming at.
- Discovery held up on harder variants of the invented API: 17 of 18 runs passed (hint, detail, paged).

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

PokeAPI did not test discovery: both models went straight to the right URL from memory. Tidepool did: nothing in training data, notes list only the base URL, and every run answered Kestrel / 340 tons. Qwen's first move was often `openapi_search` on the base URL; the clearer error message ("returns JSON but is not an OpenAPI spec") fixed that immediately. Tidepool is an easy case (a root index exists); harder variants are not yet tested. Gemma's context setting for the Tidepool runs is unconfirmed (an explicit 16K load failed for memory, so on-demand loading was used).

## Harder discovery: Tidepool variants (`tests/eval.py`, 3 runs each, 16K context)

Same question as before (answer: Kestrel, 340 tons). Variants are in `tests/fake_api.py`.

| Variant | What is harder | Gemma 4 E4B | Qwen 3.5 9B |
|---|---|---|---|
| hint | `/` is a 404; its body points at `/v2/docs`, which holds the index | 2/3 (59 to 354s) | 3/3 (35 to 55s) |
| detail | list has only id and name; capacity only on each `/v2/vessels/<id>` | 3/3 (113 to 174s, 8 to 10 steps) | 3/3 (71 to 140s, 9 to 11 steps) |
| paged | 2 items per page with a `next` link; Kestrel is on page 2 | 3/3 (63 to 116s, 5 to 7 steps) | 3/3 (52 to 70s, 6 steps) |

17 of 18 passed. The one failure: Gemma on `hint` tried about ten URLs, got 404s, and gave up without following the `docs` link in the 404 body (tracked as an issue). Both models handled the multi-call cases (fetch every vessel, follow pagination), but those cost 5 to 11 steps and 18K to 50K cumulative input tokens per task. Qwen was loaded with a 16K context here (earlier Qwen runs used its saved 32K setting); `tests/eval.py` records the loaded context for each run. A header-based variant was not built because `http_request` has no headers parameter.

## Prefill cost on this Mac (`tests/prefill_timing.py`)

Time to read a prompt of random words (one output token requested), 32K context, no prompt-cache help:

| Prompt tokens (about) | Qwen 3.5 9B | Gemma 4 E4B |
|---|---|---|
| 2K | 8.4s (228 tok/s) | 3.1s (596 tok/s) |
| 6K | 25.8s (225 tok/s) | 9.3s (613 tok/s) |
| 11K | 54.2s (211 tok/s) | 18.8s (596 tok/s) |
| 23K | 114s (201 tok/s) | 41s (548 tok/s) |

Reading OpenClaw's roughly 24K-token prompt would take about 2 minutes per call on Qwen and about 45 seconds on Gemma, and its task needed 3 model turns, so roughly 6 minutes and 2 minutes of prefill alone without caching. Smolpaw's roughly 3K-token first call costs about 13s and 5s. Caveat: the test used unique prompts. A server that caches a stable prompt prefix between calls (OpenClaw's prompt is mostly constant) could reduce this a lot; that has not been measured, nor has memory use.

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
| Nanbeige 4.2 3B OptiQ (MLX, 3.32 GB) | Unusable as loaded: at temperature 0 via the API it emits repeated junk instead of an answer. LM Studio marks it as not trained for tool use. Possible runtime or quant incompatibility (MLX engine 1.13.1); a GGUF build is untested. |

## Corrections

An earlier summary in this project overstated the Radarr wrapper-tool results ("9 of 9" and "11 of 11"). The counts in the table above are the accurate ones.
