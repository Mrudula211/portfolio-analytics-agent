# Pre-submission final audit ? 9 November 2026

## Repository reconciliation (earlier audit snapshot)

At task start, the local `main` and `origin/main` both pointed to `34c873a040244f977b214e00823e43ba4f23dc40`; the working tree was clean and there were no divergent commits. The subsequent changes have been committed and pushed to `main`; current HEAD is recorded by `git rev-parse HEAD`.

## Earlier implementation evidence

- Streamlit and the standalone API no longer have a shared-password gate. `DEMO_PASSWORD` is not read by runtime configuration and is absent from `render.yaml`; regression tests confirm a legacy variable cannot restore login.
- `GEMINI_API_KEY` and `DAILY_MODEL_QUESTIONS` remain configured in Render. Rate limits, input limits, read-only SQL and daily Gemini caps remain in place.
- Official production fallback: 10/10 exact, 0 equivalent/partial/fail/infra, 0 network attempts, no Gemini client, cache off, demo plans not loaded.
- Extended production fallback: 29/40 exact, 11 unsupported intents, 0 infrastructure errors, 0 network attempts. The unsupported cases are documented in `reports/local_fallback_extended.md`.
- Extended reference-plan replay: 40/40 exact. This is a separate tool/evaluator check, not planner accuracy.
- Full suite: 281 passed. Dataset integrity: 35 tests passed and `python -m portfolio_agent --check-data` reports the known sample-data limitations. Ruff lint and format pass.
- The production planner has 70 paraphrase/generalization cases (45 SQL, 7 exposure, 4 hybrid, 14 negative), plus ambiguity, unknown-entity and policy tests.
- Render config is Docker Streamlit. The public health endpoint returned HTTP 200 `ok`; the root page returned HTTP 200. The audit's public no-login verification was incomplete at that time; see the current status below.
- No live Gemini request was made.

## Earlier CI and publication evidence

- Latest verified source commit at this audit: `a255ecda` on `main`.
- GitHub Actions CI succeeded for that commit: https://github.com/Mrudula211/portfolio-analytics-agent/actions/runs/42555331261
- The workflow includes Ruff, full tests, dataset check, production fallback 10/10, extended reference replay, Docker build and Streamlit health smoke checks.
- That audit's statement that public authentication behavior was pending is superseded by the owner confirmation below. Exact deployed source parity remains unverified.

## Remaining limitations

- The deterministic planner is intentionally bounded. Eleven extended cases covering passive status/AUM phrasing, NAV/risk/performance history, transactions, bond queries, NVDA holdings, and beta-to-exposure hybrid remain unsupported by the local planner. Gemini may handle such questions when configured, subject to provider availability, quota, and successful execution.
- Exact commit currently served by Render is unverified. Live Gemini results remain limited to the dated reports.

## Verdict

**READY WITH DOCUMENTED LIMITATIONS** for the official Gemini-independent acceptance: Q1–Q10 pass exactly in production offline mode. Owner-confirmed deployment status: the Render app is public, works in an incognito window, and has no application login requirement. Recorded source and Render health checks are separate evidence; exact deployed-commit parity has not been independently established. The latest recorded live Gemini evaluation scored 16 answers (15 exact, 1 equivalent) and had 24 infrastructure errors; see `reports/live_extended.md`.
