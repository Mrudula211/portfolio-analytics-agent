# Local fallback assessment

## Architecture

`PortfolioAgent` routes supported, bounded intents through `portfolio_agent/local_planner.py`; the planner produces ordinary tool calls. SQL passes through the same SQL guard and read-only executor as model plans. Exposure requests use the production `exposure_calculator`. Supported intents include portfolio counts and lists, AUM aggregations/rankings, sector security lists and average prices, top/bottom holdings, sector value shares, diversification, sector exposure, supported hybrid select-then-exposure requests, latest recorded performance and risk measures, one-day security prices, transaction counts, bond coupon filters, asset-class market value and portfolios holding a security. Unsupported/ambiguous requests decline or ask for clarification; this is a bounded intent planner, not general natural-language SQL.

When configured, Gemini may handle requests outside local coverage, subject to provider availability, quota, and successful execution. Gemini failure/invalid-plan handling can fall back for supported intents. Client status distinguishes configured, successful, unavailable, quota exhausted, and unconfigured. Route source appears in the UI.

## Verified production evaluation

Command: `python evaluate.py --local-fallback --min-accuracy 1.0` (2026-11-09).

- 10 official questions; 10 exact; 0 equivalent/partial/fail/infrastructure errors.
- Routes: 8 `local_deterministic`; 2 `direct_calculator`.
- Tool selection: 10/10.
- Gemini client: none; network attempts: 0; cache disabled; demo plans not loaded.
- The evaluator instantiated the actual production agent against the assessment database.

Detailed per-question evidence: `reports/local_fallback.md`.

## Generalization limits and evidence

Production planner tests contain 58 SQL paraphrase cases, 7 exposure variants, 5 hybrid variants and 22 unsupported/negative cases: 92 distinct question examples, plus ambiguity and unknown-entity tests. These tests use the production agent/tools and independent SQL/CSV oracles; see `tests/test_local_planner.py`. The separate extended 40-case self-test is reference-plan replay and is not evidence of planner accuracy.
