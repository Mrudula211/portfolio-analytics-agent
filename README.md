# Portfolio Analytics Agent

A command-line agent that answers natural-language questions about the supplied portfolio
database. It either writes a SQL query (Gemini) or runs a deterministic sector-exposure
calculator, then **verifies** the answer before showing it. An execution-based evaluator scores
it against the 10 ground-truth questions plus 37 supplementary financial, robustness and security cases.

The original brief is preserved in [ASSIGNMENT.md](ASSIGNMENT.md). Data files, schema and ground truth are unmodified.

## Quick start (Windows, Python 3.10+)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then set GEMINI_API_KEY=...
python agent.py --build-db      # builds portfolio_database.db from data/*.csv (also automatic on first run)

python agent.py "How many portfolios do we have in total?"
python agent.py --trace "What are the sector exposures for the Tech Innovation Fund?"
python agent.py                 # interactive mode
python evaluate.py              # official 10 questions -> evaluation/reports/latest.md
python evaluate.py --suite all  # + financial, robustness and security suites
python -m pytest -q             # 50 offline tests, no API key needed
```

Model: `GEMINI_MODEL` (default `gemini-3.8-flash`; `gemini-2.5-*` models are deprecated). Without
a key the agent runs in **offline mode**: exposure questions still work through a keyword
router, and SQL questions return a clear "AI service unavailable" message.

## Architecture

```
question ─► input validation ─► portfolio resolver (deterministic) ──────────────┐
                                        │ hint: "Resolved portfolio: X (id N)"   │
                                        ▼                                        │
                     Gemini: ONE forced function call (schema + business rules,  │
                     never data rows)                                            │
          ┌──────────────────────────────┼─────────────────────────┐             │
   query_database(sql)       calculate_sector_exposure(name)   cannot_answer     │
          │                              │                    (unsupported/      │
   sql_guard (sqlglot) ─┐         resolver on argument ◄──────refused/clarify) ◄─┘
   literal grounding    │ fixable error: repair, max 2       │
   read-only SQLite ────┘ (only error text + SQL go back)   parameterised SQL,
   authorizer + step budget                                 reconciliation check
          │                                                  │
          └────────► verification ─► status + table + warnings + JSONL trace
```

| Module | Responsibility |
|---|---|
| `portfolio_agent/db.py` | Builds the SQLite file from the CSVs (FK-checked). Read-only connection with authorizer, VM-step budget and row cap |
| `semantic.py` | Schema card + business rules for the prompt; categorical value domains for grounding |
| `resolver.py` | Portfolio name → id (exact, id, alias, distinctive-token + fuzzy score). Asks rather than guesses |
| `llm.py` | The only Gemini code: forced function calling, temperature 0, retry with backoff on 429/5xx |
| `sql_guard.py` | Static policy (single read-only statement, table allow-list) + literal grounding |
| `exposure.py` | Sector Exposure Calculator |
| `agent.py` | Orchestration, bounded repair, verification, decision cache, trace |
| `evaluate.py` | Execution-based evaluator, exposure oracle, metrics, reports |

### Key decisions

| Decision | Why |
|---|---|
| **One plain-Python orchestrator** (no LangGraph or multi-agent) | The flow is linear with one bounded loop. A framework adds dependencies and failure modes without adding capability. |
| **Gemini function calling, `mode=ANY`, automatic calling disabled** | Tool choice and SQL arrive in one structured call. The model can only *propose*; our code decides what runs. |
| **The model never sees query results** | Privacy (holdings never leave the process), and summaries cannot contain invented numbers. Answers are rendered from the actual result set. |
| **Calculations are deterministic code** | Exposure is a tested function, not LLM arithmetic. |
| **Full schema in the prompt (no RAG)** | 9 tables fit easily, so retrieval would only add a way to miss context. |
| **Decision cache stores the tool call, never results** | Repeated questions cost 0 API calls, and results are always re-executed against current data. |

## The two differentiators

### 1. Verified answers: the agent checks its own output before answering
Text-to-SQL systems typically fail *silently*: the SQL runs and returns a plausible but wrong
(often empty) result. This agent detects those cases:

* **Literal grounding.** Every string literal compared with a categorical column must exist in the data.
  `target_risk_level = 'high'` returns an empty set in SQLite (values are `'High'`). The guard
  rejects it with `did you mean 'High'?`, and the error alone (no data) is fed back for a repair.
  Tested in `test_agent_routes_and_repairs_ungrounded_literal` and security case `S-GROUND`.
* **Entity check.** If the question names a portfolio and the SQL does not filter on it, the answer is flagged.
* **Empty-result diagnosis.** For example: "performance and risk data exist only for portfolio_id 1-4".
* **Exposure reconciliation.** Equity + bonds + unallocated = 100% for every portfolio (13 parametrised tests).
  The equity view must sum to 100%.
* **Status on every answer:** `VERIFIED`, `ANSWERED_WITH_WARNINGS`, `NEEDS_CLARIFICATION`, `REFUSED`, `FAILED`.
* **Bounded repair:** at most 2 corrections. Security violations are never retried.

### 2. Security that holds even if the model is compromised
Four independent layers. The last three are enforced by the SQLite engine, not by parsing:

1. `sqlglot` policy: exactly one statement, SELECT/UNION root, no DML/DDL/PRAGMA/ATTACH anywhere, allow-listed tables
2. `sqlite3` **authorizer**: only `SELECT`/`READ` on the 9 tables and allow-listed functions (denies `load_extension`, `ATTACH`, `PRAGMA`, recursive CTEs, `sqlite_master`)
3. **read-only connection** (`mode=ro` + `PRAGMA query_only`)
4. **VM-step budget** (deterministic timeout) + 500-row cap

The security suite feeds malicious SQL **directly** into the execution path, as if the model
itself had produced it. `test_engine_blocks_even_if_parser_is_bypassed` proves layers 2–3 stop
writes with the parser removed entirely.

## Financial calculations

**Sector exposure** (Q9/Q10). For portfolio *p*, using stored `holdings.current_weight` and equities only:

```
exposure_pct_of_equity(sector)    = 100 · Σ w(stock in sector) / Σ w(all stocks in p)   ← primary, sums to 100%
exposure_pct_of_portfolio(sector) = 100 · Σ w(stock in sector)                          ← economic exposure
```

The brief says to ignore bonds, so the primary view is normalised over the equity sleeve. Both
views are returned, because for mixed portfolios the difference matters. Conservative Income is
32% equity: Financials is 46.9% of equities but only 15% of the whole portfolio. A footer
reports the excluded bond weight and any unallocated weight. Weights are **not silently
rescaled**: Total Stock Market's weights sum to 98%, which is flagged. All-bond portfolios
(Fixed Income Plus, Total Bond Market) return an explanation, not an empty table or an error.

Q9 (Tech Innovation Fund): Technology 100%. Q10 (International Equity Fund): Energy 38%,
Technology 36%, Automotive 15%, Consumer Staples 11%. Both match the independent oracle.

**Other conventions given to the model.** Holding market value = `quantity × current_price`.
"Portfolio value" from holdings is never `total_aum`: holdings sum to only 1.7–14.7% of stated AUM.
Weights are fractions. Performance and risk values are stored in percent. Risk metrics are
looked up, not recomputed: 11 daily observations, no benchmark series and no risk-free rate cannot support them.

## Data findings that shaped the design (verified against the CSVs)

| Finding | Handling |
|---|---|
| 5 bonds have NULL sector | explicit `asset_type = 'Stock'` filter; excluded weight reported |
| Conservative Income 32% equity, Balanced Portfolio 36% | dual exposure views |
| Total Stock Market weights sum to 0.98 | warning, no rescaling |
| Stored weights ≠ quantity×price weights (31 holdings ≥ 5 pp) | equally far from cost-based weights, and all buys are dated 2023-09-25, so this is a data reconciliation gap, not drift; the calculator uses stored weights |
| Performance/risk data only for portfolios 1–4 | empty-result diagnosis instead of a fabricated answer |
| Categorical values are case-sensitive Title Case | literal grounding |
| "International"/"Emerging" funds hold only US-listed names; HD labelled Consumer Staples; TSLA "Automotive" | dataset labels kept so answers match the benchmark; documented |
| Data is synthetic, as of 2023-10-09 (e.g. GOOGL at a pre-split price; bonds "matured" only relative to today) | `DATA_AS_OF` in prompt |

## Evaluation methodology

* **Text-to-SQL: execution match, never string match.** Both queries are executed. Columns are
  matched by values (names and order ignored, extra columns allowed). Rows are compared as a
  multiset, with numeric tolerance 0.005. Order is enforced only when the reference is top-N
  (`ORDER BY … LIMIT`, i.e. Q5). Labels: `PASS`, `PASS_WITH_EXTRA_COLUMNS`, `FAIL_ROW_COUNT`,
  `FAIL_MISSING_COLUMN`, `FAIL_ORDER`, `FAIL_ROW_MISMATCH`, `FAIL_TOOL`, `FAIL_EXECUTION`.
* **Exposure:** correct tool, correct portfolio, same sector set, every value within 0.01 pp of
  an **independent oracle query**, totals = 100%.
* **Efficiency (optional enhancement "favor lower logical I/O"):** SQLite VM-step counts of the
  candidate vs the reference query, plus `EXPLAIN QUERY PLAN` scan/temp-B-tree warnings. Steps are
  deterministic, whereas wall-clock time on 95 rows is noise. The metric is reported, not scored.
* **Latency:** p50/p95 total and LLM time per question (`--no-cache` for honest numbers).
* **Benchmark caveats, reported rather than hidden:** Q7's reference inner-joins away the 5
  portfolios with no Technology holdings although the question says "for each portfolio".
  The official item is scored strictly against the reference. The 13-row business reading is a
  separate test (`F-Q7-ALL`). Q8's `> 5` threshold cannot distinguish off-by-one errors on this
  data, so `F-Q8-T3` uses `> 3`.
* Official and supplementary results are reported separately and never merged.

## Results

All numbers below come from actual runs. Reports are written to `evaluation/reports/`.

**Offline (no API key), measured 2026-11-07:**
* `pytest`: **50/50 passed**.
* Official exposure items Q9, Q10: **2/2 PASS** (oracle deviation 0.0000 pp).
* Security suite (direct malicious SQL): **17/17 PASS**, comprising 11 blocked attacks, 3 graceful
  failures (invalid SQL, hallucinated table, runaway query stopped by step budget), the grounding
  check, and **0 false blocks** on 2 benign queries (incl. a CTE + window function).
* Financial exposure cases 4/4 and resolver robustness cases 5/5 PASS.
* Exposure path latency: about 2–4 ms end to end.

**Live Gemini run (official 10 + LLM-dependent supplementary cases):** _pending: run
`python evaluate.py --suite all` with `GEMINI_API_KEY` set; results appear in `evaluation/reports/latest.md`._

## Logging and traceability

Every request appends one JSON line to `logs/agent_trace.jsonl`: request id, model, prompt version,
route, resolver decision, each SQL attempt with its validation error, row count (never row
contents), VM steps, LLM/DB/total milliseconds, token usage and cache hit. `--trace` prints a summary.

## Known limitations

* LLM output varies between runs and model versions. Temperature is 0, and `--repeat k` measures repeatability.
* Free-tier Gemini rate limits apply. The agent retries 429s with backoff and caches decisions.
* Summaries are templated (a consequence of not sending results to the model), so they are plain rather than narrative.
* Single-turn: no conversational references ("that fund"). Hybrid questions that need both tools are not implemented.
* Literal grounding covers `=`, `!=`, `IN` on categorical columns. `LIKE` patterns are not grounded.
* The decision cache is keyed by question text, model and prompt version. Rebuild it after prompt changes (`--no-cache`).
* No REST API, UI or concurrent serving. They were deliberately out of scope in favour of correctness, verification and security.

## Project layout

```
agent.py, evaluate.py          CLI entry points
portfolio_agent/               application package
evaluation/suites/*.json       supplementary financial / robustness / security cases
evaluation/reports/            generated evaluation reports
tests/test_agent.py            offline tests (scripted model)
data/, database_schema.sql, ground_truth_dataset.json   original assessment files (unmodified)
```
