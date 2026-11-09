# Pre-submission final audit — 9 November 2026

## Verified

- Current branch is `main`; HEAD and `origin/main` both resolved to `2ab7c47d30ddc1b120e16cab2eb846b63b4d056f` before these local edits.
- Actual production fallback: 10/10 official ground-truth exact; no Gemini client and zero network attempts; cache and stored plans disabled.
- Reference-plan extended self-test: 40/40 exact; explicitly separate from planner accuracy.
- Full tests: 279 passed. Dataset checks: 35 passed. Ruff lint and format pass.
- Planner tests: 70 distinct SQL/exposure/hybrid/negative question examples plus ambiguity and unknown-entity checks.
- Official ground-truth and source dataset files unchanged.
- Render configuration deploys Docker Streamlit; deployed `/_stcore/health` returned HTTP 200 `ok`.
- Hybrid evaluator regression and actual production agent are covered by tests.

## Submission caveats

- No live Gemini evaluation was performed in this run; prior live reports contain scored samples and provider outages, not a complete live 10/10 or 40/40.
- GitHub Actions status could not be queried because GitHub CLI is unavailable. CI now includes `evaluate.py --local-fallback --min-accuracy 1.0`; that workflow change has not yet run remotely.
- Local changes have not yet been committed or pushed. They consist of the UI prepared-cache label fix, CI fallback step, and current audit/report/documentation updates. Do not claim publication until verified.
- The local planner covers a bounded intent set; unsupported intents require Gemini or return a clear error/clarification.

## Verdict

**READY WITH DOCUMENTED LIMITATIONS** for the official task’s Gemini-independent acceptance. The verified 10/10 production fallback meets the key deterministic acceptance target. Before claiming a fully published submission, commit and push the reviewed local changes and verify the resulting GitHub Actions run. Live Gemini behavior remains separately unverified by this run.
