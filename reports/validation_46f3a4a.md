# Validation report: commit 46f3a4a

**Date:** 8 November 2026  
**Scope:** Quota-efficient review of the portfolio analytics application after the Q5, Q8 and X20 changes.  
**Live Gemini requests made for this validation:** 0.  
**Git changes:** The evaluator correction and regression test described below are local and uncommitted; no history or remote changes were made.

## 1. Executive summary

The application passes all local checks: 125 tests, Ruff lint and format checks, dataset integrity command, and all 40 offline reference-plan replays. These replay results validate the deterministic tools and orchestration against scripted plans; they are **not** live Gemini accuracy.

Q5 and Q8 are enforced in the normal SQL path through output contracts and a bounded repair. The X20 workflow runs SQL then exposure calculation, and a regression test exercises the agent path. During this audit, I found that the evaluator did not independently check the SQL selection in hybrid cases. It could give credit for accurate exposure data for the wrong portfolio. The evaluator now verifies the reference SQL result and that the calculated portfolio names match that selection. A regression test demonstrates that the old scorer would have accepted the mismatched hybrid.

The existing uncached live reports remain conditional: the original assessment has 25 passing scored answers and five infrastructure errors over 30 attempts; the extended run has 16 passing scored answers and 24 infrastructure errors over 40 attempts. They show 100% among scored answers, not a complete live 10/10 or 40/40. I made no new Gemini calls because recent runs show substantial provider outages and the user identified limited quota.

Render's home and Streamlit health endpoints returned HTTP 200. I did not submit a deployed query, so query execution and evaluation-tab rendering were not validated in the hosted browser.

## 2. Repository and commit verification

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Workspace and branch | `git status --short --branch` | Project checkout on expected branch | `G:\Projects\PL_Capital`, `main`; before this audit the tree was clean | PASS | Git status |
| Current commit | `git rev-parse HEAD` | Expected `46f3a4a` | `46f3a4a8d7a8c469c93fa85b041694d2ebe60437` | PASS | Git output |
| Sync with origin | Compare `HEAD` and `origin/main` | Same commit | Both hashes were identical before this audit | PASS | Git output |
| Expected commit in history | `git merge-base --is-ancestor 46f3a4a HEAD` | Exit 0 | Exit 0 | PASS | Git output |
| Official dataset preserved | SHA-256 of project dataset and downloaded assessment file | Identical bytes | Both `7A5C9E4EA18F973D047D31AECE044A84A179010E53CA06A6FB65F00AE0343244` | PASS | `Get-FileHash` |

This validation introduced local edits in `portfolio_agent/evaluation.py` and `tests/test_scorer.py`. The expected commit remains unchanged, and nothing was committed or pushed.

## 3. Automated tests

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Complete test suite | `python -m pytest -q` | All tests pass without Gemini | `125 passed in 15.13s` | PASS | Pytest output; added `test_hybrid_grade_checks_sql_selection_not_only_exposure` |
| No unexpected Gemini dependency in tests | Tests use `ScriptedLLM`, fixtures, and mocked SDK calls | Offline completion without provider call | Entire suite completed; no API request made | PASS | `tests/conftest.py`, `tests/test_gemini_client.py`, test run |

## 4. Ruff results

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Lint | `.venv\Scripts\ruff.exe check .` | No lint violations | `All checks passed!` | PASS | Ruff output |
| Formatting | `.venv\Scripts\ruff.exe format --check .` | All files formatted | `35 files already formatted` | PASS | Ruff output |

The global `ruff` command and default Python installation did not provide Ruff. The project virtual environment did, and its executable was used for the successful checks. The initial format check caught line wrapping in the new evaluator change; Ruff formatted those two changed files, after which both checks passed.

## 5. Dataset integrity

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Dataset/database checks | `python -m portfolio_agent --check-data` | Exit 0 and report integrity findings | Exit 0; emits the caveats listed below | PASS with data caveats | Command output |

The command reports: Total Stock Market Index Fund holding weights sum to 0.98; two portfolios have no equity exposure; `total_aum` is 7–59 times the value of listed holdings; performance and risk tables cover 4 of 13 portfolios; and three sectors have no securities. These are dataset limitations to disclose in a demo. Do not equate AUM with the market value calculated from listed holdings.

## 6. Offline evaluation

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Original assessment | Included in `python evaluate.py --self-test --extended --min-accuracy 1.0` | All 10 scripted reference plans pass | `gt01`–`gt10`: exact; two exposure questions take the deterministic fast path | PASS, offline only | Command output and `reports/self_test_extended.md` |
| Extended set | Same command | All 40 scripted reference plans pass | 40/40 exact, no infrastructure errors; strict, lenient and tool selection each 100% | PASS, offline only | Command summary |
| No weakening from evaluator change | Full offline replay after hybrid scoring change | All 40 continue to pass | Exit 0, strict threshold 1.0 met | PASS, offline only | Command exit code |

Offline replay injects reference tool plans; it does not test Gemini's ability to select or author the plan. The 40/40 number must not be presented as live model accuracy.

## 7. Q5 audit: holding projection

The generic `required_projection()` in `portfolio_agent/semantics.py` recognizes holding/position list requests and requests identifiers, security label, quantity and a requested ranking field. For a cost-basis ranking, the required result fields are `holding_id`, `symbol`, `company_name`, `quantity`, and `cost_basis`. `validate_result()` checks the SQL result columns, and `_run_sql_step()` performs at most one model correction when an executable result violates that contract. SQL guardrails remain on the execution path. The evaluator also preserves ordering when the reference query has `LIMIT`.

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Complete projection | Agent regression fixture with required holding columns | Keep result and rank order | Accepted; output contract includes all five fields | PASS | `tests/test_agent.py::test_holding_row_projection_is_validated_and_repaired` |
| Incomplete executable projection | Fixture omits required fields, then provides corrected SQL | One bounded correction; no hardcoded answer | Corrected plan accepted; exactly one repair | PASS | Same parameterized regression test |
| Exact assessment Q5 and paraphrases | Offline reference-plan replay and parametrized test | Five required fields and top-N order | Q5 and two paraphrase variants are covered by the existing regression and replay | PASS, offline only | `tests/test_agent.py`; offline report |

This validates required columns and top-five result parity. The evaluator intentionally compares returned data by values rather than requiring identical SQL text; its column-label policy is discussed in Section 10.

## 8. Q8 audit: assessment-defined diversification ratio

`portfolio_agent/semantics.py` labels this as the **assessment-defined sector diversification ratio**, explicitly not a universal financial metric. It counts distinct sectors among Stock holdings, counts all holding records separately (including bonds), filters to more than five Stock sectors, and calculates `ROUND(CAST(sector_count AS REAL) / total_holdings, 3)`. It does not substitute Sharpe, beta or volatility.

The agent independently reads the underlying portfolio/holding/security facts and validates the generated result columns, values, filter and rows before returning it. An invalid result can trigger one bounded repair. Source facts are independently read-only; the verifier is not trusting the model's returned ratio.

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Sector count, holding count, ratio and rounding | Recompute from read-only DB holding facts, then compare generated SQL output | Formula and filter match | Implemented in `_independent_diversification()` and compared in `validate_result()` | PASS | `portfolio_agent/semantics.py` |
| Deliberately wrong ratio and valid correction | Regression fixture returns an incorrect ratio, then corrected SQL | One bounded repair; correct columns and data | Corrected result accepted | PASS | `tests/test_agent.py::test_assessment_diversification_definition_is_independently_verified` |
| Assessment wording and paraphrase | Parametrized offline scenarios | Same documented metric semantics | Covered by the test and offline replay | PASS, offline only | `tests/test_agent.py`; offline report |

## 9. X20 audit: hybrid SQL plus exposure

The agent normalizes discovery-style exposure requests into a SQL selection followed by `exposure_calculator(use_previous_sql_result=true)`. The executor extracts the selected portfolio names from the prior SQL result; empty results and unusable names stop the plan with an error/clarification rather than claiming completion. The exposure calculator derives equity sector exposure and excludes bonds. Hybrid replies are marked unsuccessful unless both successful tool types ran.

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Successful X20 flow | Script a query needing repair, then execute SQL and exposure in sequence | Select portfolio and calculate that portfolio's equity exposure | SQL repair is followed by exposure; evaluator checks expected selection and exposure | PASS, offline | `tests/test_agent.py::test_discovered_exposure_request_completes_sql_and_calculator` |
| Empty SQL result | Inspect execution branch and existing test | Do not claim exposure success | Hybrid path returns an error when no selected name is available | PASS by implementation; no separate dedicated test | `portfolio_agent/agent.py::_run_exposure_step`, `test_hybrid_with_no_matching_portfolios_is_handled` |
| Missing/malformed name | Inspect portfolio-name extraction and calculator error handling | Stop or clarify; no false success | Missing rows produce an error; unknown names are handled as unresolved/ambiguous by the tool path | PASS by implementation; no dedicated malformed-name regression | `portfolio_agent/agent.py::_portfolio_names_from`, `_run_exposure_step` |
| Failure in either required operation | Inspect `_StopPlan` handling and final hybrid completion check | Final response must not say completed | Failed SQL stops plan; failed exposure has an errored step; final status check requires both successful tools | PASS by implementation | `portfolio_agent/agent.py::_answer_with_calls` |
| Evaluator rejects right exposure for wrong SQL selection | Construct a hybrid reply with SQL selecting Balanced Portfolio and exposure for the expected X20 portfolio | Fail the mismatch | Now fails with `hybrid SQL selection failed`; new regression passes | PASS | `tests/test_scorer.py::test_hybrid_grade_checks_sql_selection_not_only_exposure` |

The success path has regression evidence, not fresh live Gemini evidence. The current X20 entry in the existing extended live report is an infrastructure error, not a pass.

## 10. Evaluator correctness audit

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| SQL column labels/order | Inspect `compare_results()` | Determine whether names are enforced | Values are matched by column contents; labels/order are intentionally not required for SQL equivalence | PASS with intentional scoring difference | `portfolio_agent/evaluation.py::_find_mapping`, `compare_results` |
| Missing fields | Mutated-result regression tests | Missing requested values cannot pass | Missing values produce `partial` (never a passing verdict); Q5/Q8 agent contracts additionally enforce schema columns | PASS | `tests/test_scorer.py::test_missing_requested_column_is_partial_not_pass` and missing-column variants |
| Extra fields/zero rows | Mutated-result regression tests | Match documented leniency | Extra columns and rows containing zero/NULL can be `equivalent`; other extra rows fail | PASS with intentional leniency | `test_extra_column_is_equivalent`, `test_extra_zero_row_is_equivalent`, `test_extra_real_row_fails` |
| Hybrid intermediate and final outputs | New test plus normal offline set | Verify selection and exposures | Previously SQL selection was unchecked; now reference SQL, selected names and exposure values are all checked | PASS after local fix | New test in `tests/test_scorer.py` |
| Tool selection | Compare used successful tool sets with case kind | Wrong tool plan fails | SQL, exposure and hybrid cases have separate tool-set checks; metric accuracy is reported among scored cases | PASS | `Evaluator._grade()` |
| Infrastructure errors and stability | Unit tests with outages mixed with scored runs | Outages excluded from accuracy but not counted as passes; stability ignores outages | Separate `infra_errors` count; stability uses non-infra verdicts only | PASS | `test_infra_errors_are_not_counted_as_wrong_answers`, stability tests |

The evaluator uses a content-based SQL equivalence policy, so a SQL result with different output labels can still compare equivalent if the values and rows match. That is a deliberate flexibility versus reference-query formatting, not proof that labels are correct. For Q5 and Q8, the application-level contracts check the named required fields before a result is returned. Q7's extra zero rows are intentionally graded equivalent because they reflect a reasonable “for each portfolio” interpretation.

## 11. Gemini quota and request-consumption audit

The API key is configured (checked as a boolean only); its value was never printed. No request was made to test the key. Fallback models are configured by default: primary `gemini-3.1-flash-lite`, then `gemini-3.5-flash` and `gemini-3.6-flash`. SDK retries are disabled (`attempts=1`), but hedging starts another configured model after the hedge delay or an earlier failure.

One logical planning operation can therefore submit up to **three provider requests**. If SQL validation requires its one allowed model repair, the repair is another planning operation, so a question can submit up to **six provider requests** in the worst case. A losing hedged request already in progress may continue to run until its timeout; cancelling the future does not stop an in-flight network request. The report's `llm_calls_per_question` counts logical plan calls, not all provider requests, and explicitly excludes hedges.

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| SDK retry count | Inspect Gemini client HTTP options | No hidden retry multiplier | `attempts=1` | PASS | `portfolio_agent/llm.py` |
| Default model fanout | Inspect model list and hedge loop | Count possible requests per plan | Three configured model slots; up to three submissions per plan call | PASS | `portfolio_agent/config.py`, `portfolio_agent/llm.py` |
| Disable fallbacks in PowerShell | Temporarily set `$env:GEMINI_FALLBACK_MODELS = ','`; read only resulting model tuple | Empty tuple and no fallback | `fallback_models=()`, `fallbacks_disabled=True`; env removed afterward | PASS | Runtime settings check |
| Requested empty-string override | Assign empty value in PowerShell | Empty value must reach Python | This PowerShell removes/omits the environment variable; config then uses defaults. A comma is the safe temporary empty-list value here. | NOT SUPPORTED BY THIS SHELL FORM | Runtime check |
| New live quota check | Would require provider request | Do not test merely for key presence | Skipped: recent live run had 24/40 infrastructure errors; earlier run history includes quota rejections. Availability is not established. | NOT TESTED | Existing live reports |

**Recommendation:** For low-quota assessment runs, temporarily set the fallback list empty (comma value in PowerShell), and set the hedge delay high or add a clearly documented single-model evaluation option if strict one-request accounting is needed. Do not change production defaults solely for this audit. A separate provider-attempt counter would make quota reporting more transparent.

## 12. Live Gemini tests

No new Gemini question was sent. The key being present does not establish available quota, and the recent extended report records 24 provider/infrastructure errors out of 40 attempts. Therefore Q4, Q5, Q8 and X20 received no new live tests during this validation.

Existing evidence from `reports/live.md` (three uncached runs): 25 scored answers passed, with five infrastructure errors. Q4 failed to obtain a model response all three times; Q5 passed once and had two outages. The 100% strict figure is conditional on 25 scored answers; it is not complete three-run coverage.

Existing evidence from `reports/live_extended.md`: 16 scored answers passed and 24 were infrastructure errors. X20 was an infrastructure error. Its live status is **not tested successfully** in that run. These reports were not overwritten.

## 13. Deployment checks

| Test | Method | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| Render site availability | HTTP HEAD to `https://portfolio-analytics-agent.onrender.com` | Response from deployed app | HTTP 200, Uvicorn/Cloudflare response | PASS, availability only | `curl.exe -I` |
| Streamlit health endpoint | GET `/_stcore/health` | Health response | HTTP 200 | PASS, health only | `curl.exe` |
| Hosted query interaction | Submit one uncached question in deployed UI | Valid response or clear model error | Not submitted; avoids Gemini quota use | NOT TESTED | No model request made |
| Evaluation tab and cached-demo UI | Browser interaction | Report visible; demo route visibly distinguishable | Not browser-automated in this run | NOT TESTED | Source inspection only |
| Cached demos | Inspect preload and route rendering | Stored plans are distinguishable from model calls | Demo plans are preloaded and route renders as `Cached`; this is visible in source, not verified in hosted UI | PASS by source inspection | `portfolio_agent/demo.py`, `streamlit_app.py` |
| Gemini connection indicator | Inspect UI source and health endpoint | Clearly communicate configuration, not provider availability | Health field is named `model_configured`; sidebar says “Gemini connected” whenever a client is configured, which can overstate actual reachability | FAIL: wording is misleading | `portfolio_agent/api.py::health`, `streamlit_app.py` |
| Deterministic exposure without Gemini | Agent fast-path test and offline replay | Named portfolio exposure should work without model | Fast path is model-free and offline exposure cases pass | PASS, local; hosted interaction not tested | Agent and offline tests |

## 14. Bugs and weaknesses discovered

1. **Hybrid evaluator gap (fixed locally, High):** It previously graded exposure values and tool presence but ignored whether SQL selected the expected portfolio. This could inflate X20-style hybrid scores. The smallest fix and a targeted regression test are included in this working tree.
2. **Quota fanout (High):** Fallback hedging can make up to three provider requests per planning call and up to six if one repair is needed. Logical call reporting excludes hedges.
3. **“Gemini connected” label (Medium):** It indicates that a client was constructed from configuration, not that Gemini is currently reachable or has quota.
4. **SQL result labels are not scored (Medium):** General SQL equivalence is based on values/rows; labels and order do not have to match. Q5/Q8 have app-level schema contracts, but a general response can still show labels different from reference labels while scoring equal.
5. **Live validation has weak coverage (High):** Existing results contain frequent outages. No new live results were obtained here; offline success does not resolve model reliability.
6. **Dataset constraints (Medium):** Risk/performance time series are incomplete and some portfolios have missing equities or weights not summing to 1.0.

## 15. Recommended improvements, ranked

| Priority | Finding | Recommendation |
|---|---|---|
| High | Limited quota and hedged fallback fanout | Add a single-model mode for evaluation and report actual provider attempts, including hedges and repairs. Keep production defaults unchanged until measured. |
| High | Live outages | Run the four requested live cases only when quota/rate-limit status is known to be healthy; publish scored answers and outages separately. |
| Medium | Misleading connection label | Change “Gemini connected” to “Gemini configured”; use a separate explicit request result to indicate availability. |
| Medium | General SQL labels not validated | Preserve value-based equivalence but expose/check labels separately, or add a schema-aware label contract for questions that demand named fields. |
| Medium | Sparse portfolio risk/performance data | State coverage limits in the UI and avoid implying every portfolio has comparable time-series metrics. |

## 16. Final submission-readiness assessment

**Technical assessment:** The core application is technically sound for a take-home project: read-only SQL execution, SQL validation, deterministic exposure computation, offline regression coverage, and bounded correction are present. Q5 and Q8 are enforced by implementation checks and regression tests. X20's agent path completes SQL then exposure; the evaluator now checks both, after this audit's local correction.

**Score trust:** Offline reference-plan results are reproducible pipeline checks, not LLM accuracy. Existing live scores are trustworthy only as conditional accuracy among scored calls; infrastructure outages are substantial and were excluded from the accuracy denominator. The former hybrid evaluator under-checked SQL selection, now covered by the local fix. General SQL labels are intentionally not part of equivalence scoring.

**Submission readiness:** Ready for code review and a controlled demo, with two material caveats: the evaluator fix remains uncommitted for review, and fresh live Gemini coverage is incomplete. Do not claim an unqualified live 10/10. Review the local evaluator diff, then decide whether to commit it. No commit or push was made.
