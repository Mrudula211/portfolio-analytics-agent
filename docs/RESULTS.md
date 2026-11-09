# Results

Live results for the current configuration, how answers are graded, and what the data revealed. The experiments that led to this configuration are in [EXPERIMENTS.md](EXPERIMENTS.md).

## Current configuration

Models are tried in the order `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`. The system prompt's SHA-256 prefix is `781d7b712874fccf`.

### Latest live validation

Run on 8 November 2026 against the current checkout (`6d5d7aa` plus the uncommitted fixes in this workspace), with cache disabled. Full per-question report: [reports/live_extended.md](../reports/live_extended.md).

| Measure | Result |
| --- | --- |
| Strict accuracy among scored answers | **100%** (16 of 16) |
| Model/infrastructure errors | 24 of 40 attempts unscored |
| Lenient accuracy among scored answers | 100% |
| Tool selection among scored answers | 100% |
| End-to-end full-credit rate, counting outages as unsuccessful | **40%** (16 of 40) |
| Gemini latency for scored model answers | p50 4.56 s, p95 11.41 s |

This run does not prove 100% accuracy across all 40 questions: most were unavailable. In particular, X20 was an outage, so the hybrid fix has regression-test and offline-replay evidence, not a fresh live result. The report predates provider failure-category instrumentation and records these as model outages without distinguishing timeout from API errors.

### Original assessment: three uncached live attempts

Run on 8 November 2026 with `python evaluate.py --runs 3 --delay 6`; [full report](../reports/live.md). The evaluator calls `answer_question(..., use_cache=False)` for every attempt.

| Question | Result across the three attempts |
| --- | --- |
| Q1 | Exact, 3/3 |
| Q2 | Exact, 3/3 |
| Q3 | Exact, 3/3 |
| Q4 | Infrastructure outage, 3/3; no scored answer |
| Q5 | Exact, 1/3; outage, 2/3 |
| Q6 | Exact, 3/3 |
| Q7 | Equivalent, 3/3; all expected data present |
| Q8 | Exact, 3/3 |
| Q9 | Exact, 3/3 |
| Q10 | Exact, 3/3 |

Aggregate: **25/25 scored attempts passed**, 5/30 attempts were infrastructure errors, and tool selection was 100% for scored cases. Eight questions were scored repeatedly with consistent outcomes; Q5 was scored once. A complete, single-run live 10/10 has not yet been observed because Q4 was unavailable on all three attempts. The latest live evaluator now records timeout and provider/API error categories for future runs.

### Earlier 40-question run (7 November)

The 10 in the brief plus 30 I wrote. The earlier three-attempt run below took place on 7 November 2026, 04:31 to 04:43 UTC; it is retained as historical context.

| Measure | Brief's 10 questions | All 40 questions |
| --- | --- | --- |
| Strict accuracy | 8 of 10 | **92.3%** (36 of 39 scored) |
| Lenient, counting partial answers | 10 of 10 | 97.4% |
| Correct tool chosen | 10 of 10 | 97.4% |
| Safety, refusal and ambiguity cases | n/a | 10 of 10 |

| Latency | p50 | p95 |
| --- | --- | --- |
| With a Gemini call (33 questions) | 2.10 s | 7.29 s |
| Sector exposure fast path, no model (6 questions) | 13 ms | 22 ms |

What did not pass:

- **Q5, partial:** the right five holdings in the right order, but without the reference's `holding_id`, `symbol` and `quantity`.
- **Q8, partial:** the right portfolio and sector count, but not the reference's `total_holdings` and `diversification_ratio`. The ratio is defined only in the answer key. A glossary entry copied from it was removed on purpose.
- **x20, wrong:** it found the right portfolio, Tech Innovation Fund, but did not go on to run the exposure calculator.
- **x11, not scored:** the model was unreachable on all three attempts.

**Cost and conditions.** The three attempts made 109 Gemini requests and used 73,033 prompt and 2,015 output tokens:
- **`gemini-3.1-flash-lite` answered all 33 model questions.**
- The fallbacks' requests were rejected for quota: 31 for `gemini-3.5-flash` and 25 for `gemini-3.6-flash`. Their quota had been used up by experiments earlier that day.
- Lite itself failed 19 times: 11 timeouts (504), 7 overloaded (503) and 1 read timeout.

### Stability: the brief's 10 questions, three runs

The 40-question run above, plus `python evaluate.py --runs 2 --delay 6`, run on 7 November 2026, 04:36 to 04:39 UTC, on the same commit. Report: [reports/live.md](../reports/live.md).

| Question | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| Q2, Q4, Q9, Q10 | pass | pass | pass |
| Q1, Q3, Q7 | pass | not scored (outage) | pass |
| Q6 | pass | pass | not scored (outage) |
| Q5, top 5 holdings | partial | partial | partial |
| Q8, diversification metrics | partial | partial | partial |

Every question that was scored more than once got the same verdict each time. Q5 and Q8 are consistently partial, not tuned for, because fixing them would mean teaching the prompt the answer key. Across these runs, answers that needed Gemini had a median of 2.57 s.

### Measured without the model

| Measure | Result |
| --- | --- |
| Unit and integration tests | 124 passed |
| Self-test: 40 cases with reference plans replayed | 40 of 40 |
| Sector exposure fast path, uncached, 300 runs | p50 2.7 ms, p95 4.3 ms |
| Exact-repeat cache hit, 300 runs | p50 0.015 ms |

The self-test proves the tools, the SQL guard and the scorer work together. It says nothing about the model's accuracy. Timings were taken in process on a Windows laptop and exclude network time.

### Earlier configuration

With `gemini-3.5-flash` first, the same evaluation scored 95.0% (38 of 40) on 7 November, with a median of 2.49 s. A fresh-project test that day showed that model timing out on 11 of 15 calls, and the full agent then took a median of 7.7 s. That is why Lite now comes first. Details are in [EXPERIMENTS.md](EXPERIMENTS.md).

**Not blind.** Three fixes were made after seeing failures among the 30 extra questions (x06, x08 and a percentage example). Nothing in the prompt comes from the ground truth.

## How answers are graded

The ground truth gives reference SQL rather than answers, so the evaluator computes the expected results and compares data, not query text.

- **Grades:**
  - `exact`
  - `equivalent`: extra columns, or extra rows showing zero
  - `partial`: right rows, missing columns
  - `fail`

  Strict accuracy counts only the first two.
- **Independent exposure check:** expected exposures are calculated from the raw CSVs by separate code. A test confirms both implementations agree on all 13 portfolios.
- **The scorer is tested itself:** deliberately wrong answers (swapped rows, a wrong filter, an altered exposure) must fail.
- **No leakage:** a test fails if any evaluation question or query appears in a prompt or among the UI's stored demo questions.
- **Query cost:** SQLite VM steps stand in for logical I/O and are compared with the reference query. Full table scans are recorded.
- **Stability:** `--runs` repeats cases. Only questions scored more than once count towards stability.
- **Outages are separate:** a model that cannot be reached is reported as an outage, not as a wrong answer.

## What the data revealed

Run `python -m portfolio_agent --check-data` to reproduce the computed findings.

| Finding | What the agent does |
| --- | --- |
| Total Stock Market Index Fund weights sum to 98%, not 100% | Normalises over equities and shows a warning |
| Fixed Income Plus and Total Bond Market hold no equities | Says there is no exposure, rather than dividing by zero |
| `current_weight` disagrees with quantity x price, by 11 points for International Equity | Reports both, and warns that weights may be stale |
| `total_aum` is 7x to 59x the value of listed holdings | Defines "value" as quantity x price and never mixes the two |
| Performance and risk data cover only 4 of 13 portfolios | Returns only what exists |
| Home Depot is classified as Consumer Staples (usually Consumer Discretionary) | Uses the data as given; noted for data owners |

Exposure is ambiguous for mixed funds, so the tool returns both definitions:
- the share of equity holdings, which sums to 100% and is the headline figure, since the brief says to consider only equities
- the share of the whole portfolio

**Issues in the ground truth:**
- Q7 says "for each portfolio", but its reference query leaves out the five portfolios with no technology holdings. Listing them at zero is arguably more correct, so the scorer grades that `equivalent`.
- Q10's explanation mentions a portfolio ID, while its parameters use a name.
- The brief's `gemini-pro` model and `google.generativeai` package are obsolete; this project uses `google-genai`.

## Current offline production validation (9 November 2026)

The current checked-out implementation passed `python evaluate.py --local-fallback --min-accuracy 1.0`: all 10 official questions were **exact**, with zero infrastructure errors, zero network attempts, no Gemini client, cache disabled, and demo plans not loaded. Eight used `local_deterministic`; the two sector-exposure questions used `direct_calculator`. Full per-question evidence is in [reports/local_fallback.md](../reports/local_fallback.md).

`python evaluate.py --self-test --extended --min-accuracy 1.0` also passed 40/40 exact. This is **reference-plan replay**, not a production-planner or Gemini evaluation. The production planner has 70 positive/negative paraphrase examples in its test suite. The current test suite has 281 passing tests, including 35 dataset integrity tests; Ruff lint and formatting pass.

No live Gemini run was made for this validation. The deployed Streamlit health endpoint returned HTTP 200 (`ok`) on 9 November 2026. GitHub Actions run for `a255ecda` passed ([workflow run](https://github.com/Mrudula211/portfolio-analytics-agent/actions/runs/42555171699)).


### Extended production fallback coverage

The real production agent was also run on all 40 official plus extended cases without Gemini: **29 exact, 11 unsupported/fail, 0 infrastructure errors, 0 network attempts**. The unsupported cases are x02, x03, x05-x12 and x20, which ask for unsupported filters, time-series/risk/transaction/bond/NVDA queries or a beta-to-exposure hybrid. Safety and out-of-scope refusals x21-x29 and the ambiguous x30 were handled correctly. See [the per-case report](../reports/local_fallback_extended.md). The 40/40 reference-plan self-test does not measure planner coverage.
