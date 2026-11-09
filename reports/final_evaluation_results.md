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

## Latest recorded live Gemini evaluation

The 40-question run recorded on 8 November 2026 scored 16 answers: **15 exact and 1 equivalent**. The other 24 attempts were infrastructure errors and were not scored. Thus 16/16 scored answers passed under strict scoring (which accepts exact and equivalent), but the run did not establish 40/40 live coverage. See the dated per-question evidence in `reports/live_extended.md`. This is historical live evidence; no new Gemini evaluation was run for this documentation update.

## Generalization and quality checks

The production planner is exercised by 58 SQL paraphrase cases, 7 exposure cases, 5 hybrid cases and 22 negative cases (92 question examples), plus ambiguity/unknown-entity and safety checks. The historical test baseline was 124 passed; the latest verified result is 303 passed, including 35 dataset integrity tests. Ruff check/format pass. CI: run for commit `a255ecda` passed ([run details](https://github.com/Mrudula211/portfolio-analytics-agent/actions/runs/42555331261)).

## Deployment verification

- **Source-code verification:** [streamlit_app.py](../streamlit_app.py), [render.yaml](../render.yaml), and [Dockerfile](../Dockerfile) show the Streamlit app is served without an application login gate.
- **Render operational verification:** the deployed root and Streamlit health endpoint returned HTTP 200 in the recorded operational check; see the evidence table in [the 8 November validation report](validation_46f3a4a.md).
- **Public access verification:** the owner confirms the deployed app is publicly accessible, opens in an incognito window, and does not require login.
- **Deployment parity:** the exact commit served by Render has not been independently established. The access confirmation does not prove commit parity with this repository.

## Extended production-agent fallback (no Gemini)

`python evaluate.py --local-fallback --extended --min-accuracy 1.0` scored 40/40 exact (no infrastructure errors, 0 network attempts). An earlier run scored 29/40; x02, x03, x05-x12 and x20 passed after generic planner intents were added, so this set is not a blind test. x21-x29 were blocked or declined with exact expected policy outcomes; x30 was clarified correctly. Coverage remains bounded to the planner's intents. Report: `reports/local_fallback_extended.md`.

The 40/40 extended self-test above is reference-plan replay and is a separate check from the 40/40 production fallback result. Gemini may handle questions outside the local planner when configured, subject to provider availability, quota, and successful execution.
