# Gemini experiments

Every experiment that shaped how the agent calls Gemini, in the order they were run, and what each one changed. All runs used the Gemini free tier. The figures come from the evaluation reports and timing scripts of the day. Later runs were evaluated on a committed version of the code with no uncommitted changes.

## Summary

| # | Date (2026) | Experiment | Result | What changed |
| --- | --- | --- | --- | --- |
| 1 | 5 Nov | First live run: `gemini-3.5-flash-lite`, SDK retries on, the brief's 10 questions | 8 of 10 strict; median 9.0 s, p95 35.9 s | Latency had to be investigated |
| 2 | 5 Nov | Direct calls to each model, retries off | Lite models swung from about 1 s to 13 s on identical requests; `gemini-2.5-flash-lite` was closed to new users | SDK retries turned off |
| 3 | 5 Nov | Five calls each to six models | `gemini-3.5-flash` 1.3 to 1.7 s when up; `gemini-3.8-flash` failed every time | Primary `gemini-3.5-flash`, with hedged requests |
| 4 | 5 Nov | 40 questions with hedging | 93.1% on the 29 scored; **11 outages** | Found the free tier's 20-requests-a-day limit per model |
| 5 | 6 Nov | 40 questions, paced | 94.9% on the 39 scored; median 1.91 s, p95 5.72 s | Sharpe ratio bug found and fixed |
| 6 | 7 Nov | 40 questions after removing prompt hints taken from the ground truth | 95.0% (38 of 40); median 2.49 s, p95 6.85 s | Quota ran out part-way; most answers came from fallbacks |
| 7 | 7 Nov | Brief's 10 questions twice more, new key | Same 8 passed; median 4.57 s, p95 7.01 s; 16 of 41 requests failed | Latency clearly depended on the free tier |
| 8 | 7 Nov | Each model alone, 15 calls, fresh project | `gemini-3.5-flash` **4 of 15** succeeded; `gemini-3.1-flash-lite` 11 of 15, median **1.87 s** | The primary model was the bottleneck |
| 9 | 7 Nov | Old order, full agent, fresh project | Median **7.7 s**; 4 of 8 model questions failed | Confirmed the order was the cause |
| 10 | 7 Nov | **Lite first**, 40 questions plus two more runs of the brief's 10 | 92.3% (36 of 39); median **2.10 s**; the brief's 10 fully consistent over 3 runs | **Final configuration** |

## The experiments in detail

### 1. First live run
`gemini-3.5-flash-lite` with `gemini-3.1-flash-lite` as fallback, and the SDK's automatic retries on (3 attempts on 429 and 5xx). On the brief's 10 questions, 8 were strictly correct, but the median answer took 9.0 s and the 95th percentile 35.9 s. The model was assumed to be the fastest tier, so this needed explaining.

### 2. Direct model calls
Calling models directly with retries off showed latency was **bimodal**: identical requests took about 1 s or more than 10 s. `gemini-3.5-flash-lite` took 12.6 s, 13.4 s, then 1.2 s in a row. The SDK's retries made this worse by waiting on a congested model instead of trying another. `gemini-2.5-flash-lite` returned "no longer available to new users".

**Change:** SDK retries off.

### 3. Comparing six models
Five calls each, retries off, in one session:

| Model | Successful calls | Failures |
| --- | --- | --- |
| `gemini-3.5-flash` | 1.3 to 1.7 s | two fast 503s |
| `gemini-3.6-flash` | 1.9 to 3.3 s | none |
| `gemini-3.1-flash-lite` | 1.0 to 9.9 s | one 504 after 24.6 s |
| `gemini-3.5-flash-lite` | 1.2 to 13.4 s | none |
| `gemini-flash-lite-latest` | 9.2 to 14.5 s | none |
| `gemini-3.8-flash` | none | five 503 or 504 |

**Changes:**
- The primary became `gemini-3.5-flash`, with `gemini-3.6-flash` and `gemini-3.1-flash-lite` as fallbacks.
- **Hedged requests:** if a model has not answered in 2.5 s, or fails, the next one starts, and the first answer wins. A slow request then costs about 2.5 s instead of 10 s or more.
- Thinking set to the minimum level, since writing one SQL query needs little deliberation.

### 4. Discovering the daily quota
A 40-question run scored 93.1% on the 29 it could score, but 11 questions failed with every model unreachable. The error said: 20 requests per model per day on the free tier. Hedging had used up the quota faster, because each slow question tried several models.

**Changes:** the evaluator paces requests, reports outages separately from wrong answers, and can resume only the questions that failed to run.

### 5. Paced 40-question run
94.9% strict on the 39 scored, with a median of 1.91 s and p95 of 5.72 s. It exposed a real bug: asked for the highest Sharpe ratio, the model searched the wrong table, and its repair attempt substituted the Sortino ratio.

**Changes:**
- The glossary now says which table holds each metric.
- A new rule and repair path make the agent decline rather than substitute a different metric.

### 6. Run after removing prompt hints
Two glossary lines had been written after reading the ground truth answers, for Q5 and Q8, so they were removed. The result was 95.0% strict on all 40, with a median of 2.49 s and p95 of 6.85 s. Of 80 requests, 39 were rejected for quota, so most answers came from fallbacks.

### 7. Stability runs
The brief's 10 questions twice more, on a new API key. The same 8 questions passed every time, and Q5 and Q8 never fully did. The median rose to 4.57 s, and 16 of 41 requests failed with 429, 503 or 504. Latency was evidently set by the free tier, not by the agent, whose own work takes about a millisecond.

### 8. Each model alone, with fresh quota
To separate quota from congestion, a key from a new Google project was used. Fifteen requests went to each of two models, with no fallback, spaced under the 5-a-minute limit:

| Model | Succeeded | Median | p95 | Under 2 s |
| --- | --- | --- | --- | --- |
| `gemini-3.5-flash` | 4 of 15 (8 timeouts, 3 overloaded) | 6.59 s | 10.64 s | 0 |
| `gemini-3.1-flash-lite` | 11 of 15 | 1.87 s | 8.84 s | 6 |

No request was rejected for quota, so the slowness was congestion. **The primary model was the most congested one.**

### 9. Old order, full agent, fresh project
With the original order, the agent spent 2.5 s on each congested Flash model before reaching Lite: a median of 7.7 s, and 4 of the 8 model questions failed outright. Starting a second model while the first was still running also burst past the 5-a-minute limit, causing 11 rejections.

### 10. Lite first
The order became `gemini-3.1-flash-lite`, then `gemini-3.5-flash`, then `gemini-3.6-flash`. The evidence:
- Lite was the fastest and most reliable in experiment 8.
- It had already answered 21 of the 34 model questions in the 95% run of experiment 6, so accuracy was not expected to suffer.
- It allows 15 requests a minute and 500 a day, against 5 and 20 for Flash.

On commit `16c9b86`:

| Measure | Result |
| --- | --- |
| All 40 questions | 92.3% strict (36 of 39 scored), 97.4% lenient, 1 outage after two resumes |
| Safety, refusal and ambiguity cases | 10 of 10 |
| Median, p95 with Gemini | 2.10 s, 7.29 s |
| Brief's 10, three runs | The same 8 pass every time; Q5 and Q8 are partial every time; fully consistent |
| Answering model | `gemini-3.1-flash-lite` for all 33 model questions |

## Why the agent calls Gemini the way it does

Each choice came from one of the experiments above.

| Choice | Why | Experiments |
| --- | --- | --- |
| **One Gemini call returns the whole plan**, including both steps of a hybrid question | Every extra round trip adds seconds on the free tier | 1, 7 |
| **Code writes the answer, never the model** | Avoids a second call, and the model cannot misquote a figure | design |
| **Sector exposure for one named fund skips Gemini** | About 10 ms instead of seconds, with no quota used | 7, 10 |
| **Exact-match cache** | Repeat questions in under 1 ms; matching on meaning risks wrong answers, such as "high" and "low" risk | design |
| **SDK retries off** | Retrying a congested model is slower than asking another | 2 |
| **Hedged requests across three models** | Free-tier latency is bimodal and failures are common | 2, 3, 8 |
| **`gemini-3.1-flash-lite` first** | Fastest and most reliable when measured, with 25 times the daily quota | 8, 9, 10 |
| **Minimal thinking** | Writing one query needs little deliberation, and it is the largest latency setting under the agent's control | 3 |
| **Paced, resumable evaluation, with outages reported separately** | Free-tier quotas and congestion would otherwise distort accuracy | 4, 6, 7 |
| **No schema retrieval or vector database** | Missed a needed table on 3 of 23 questions to save about 480 tokens | see [DESIGN.md](DESIGN.md) |

## Limits of these experiments

- **Free tier only.** Free-tier latency changes by the hour, and a paid tier would remove most rate limiting. No paid-tier figure is claimed because none was measured.
- **Small samples.** Each run measured 6 to 15 calls per model, so the medians are indicative rather than precise.
- **The 30 extra questions are not a blind test.** Three fixes were made after seeing failures there.
- **The Gemini model line-up changes.** `gemini-2.5-*` models were closed or deprecated during this work, so the order is worth re-measuring before relying on it.
