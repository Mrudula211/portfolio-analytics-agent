# Final evaluation results — 9 November 2026

## Official ground truth: production agent, offline

Command: `python evaluate.py --local-fallback --min-accuracy 1.0`.

| ID | Verdict | Production route |
|---|---|---|
| Q1 | exact | local_deterministic |
| Q2 | exact | local_deterministic |
| Q3 | exact | local_deterministic |
| Q4 | exact | local_deterministic |
| Q5 | exact | local_deterministic |
| Q6 | exact | local_deterministic |
| Q7 | exact | local_deterministic |
| Q8 | exact | local_deterministic |
| Q9 | exact | direct_calculator |
| Q10 | exact | direct_calculator |

10/10 exact; 0 equivalent, partial, fail, or infrastructure error. Tool selection 10/10. Network attempts 0; Gemini client absent; cache disabled; stored demos not loaded. Results are from the actual `PortfolioAgent` and database.

## Extended evaluation

`python evaluate.py --self-test --extended --min-accuracy 1.0` passed 40/40 exact with zero infrastructure errors. This is reference-plan replay through tools and scorer. It is not a production-agent planner evaluation and not a live Gemini run. Breakdown: 10 official, 30 extended (hybrid, safety, edge and other cases). See `reports/self_test_extended.md` for per-case details.

## Generalization and quality checks

The production planner is exercised by 45 SQL paraphrase cases, 7 exposure cases, 4 hybrid cases and 14 negative cases (70 question examples), plus ambiguity/unknown-entity and safety checks. Full suite: 279 passed, including 35 dataset integrity tests. Ruff check/format pass. Live Gemini: not run. CI: GitHub Actions run #12 passed both test and image jobs for commit `2ba8b90` ([run details](https://github.com/Mrudula211/portfolio-analytics-agent/actions/runs/42551749161)). Deployment health endpoint: HTTP 200 `ok`.

## Extended production-agent fallback (no Gemini)

`python evaluate.py --local-fallback --extended` scored 29/40 exact and 11/40 fail (no infrastructure errors, 0 network attempts). The 11 unsupported cases are x02, x03, x05?x12, and x20. They request passive fund filters/AUM paraphrased as money, NAV/performance/risk history, historical prices, transactions, bond coupons/values, NVDA holdings, or a latest-beta hybrid. x21?x29 were blocked or declined with exact expected policy outcomes; x30 was clarified correctly. These are intentionally not represented as broad deterministic support. Report: `reports/local_fallback_extended.md`.

The 40/40 extended self-test above remains reference-plan replay and must not be conflated with the 29/40 production fallback result.
