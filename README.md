# Portfolio Analytics Agent

Ask questions about portfolio data in plain English. The agent writes and safely runs SQL, calculates sector exposures, or combines the two. It never lets the language model state a number: code formats every figure straight from the database.

```text
> Calculate the sector exposure breakdown for international equity
Sector exposure: International Equity Fund
sector            exposure_pct  portfolio_weight_pct  market_value_pct  holdings
Energy            38%           38%                   30.68%            2
Technology        36%           36%                   47.20%            4
Automotive        15%           15%                   13.53%            1
Consumer Staples  11%           11%                   8.60%             1
Note: Recorded weights and market values disagree by up to 11.2 points; the recorded weights may be stale.
```

## At a glance

- **Original 10, three uncached live attempts:** 25/25 scored answers passed, with 5/30 infrastructure failures. This is not a complete live 10/10: Q4 was unavailable all three times and Q5 twice.
- **Latest 40-question live run:** 16/16 scored answers passed, with 24/40 infrastructure failures (40% end-to-end full credit counting outages as unsuccessful). This is not a complete live 40/40. See [the per-question report](reports/live_extended.md).
- **Speed:**
  - under 1 ms for repeat questions
  - about 10 ms for sector exposure, which skips the model
  - a median of 4.56 s when Gemini is needed, on the free tier
- **Every failure, cost and caveat** is in [docs/RESULTS.md](docs/RESULTS.md).

## Requirements checklist

| Brief item | Where | How to check it |
| --- | --- | --- |
| SQL query tool | `run_sql` in [tools.py](portfolio_agent/tools.py), guarded by [sql_guard.py](portfolio_agent/sql_guard.py) | `python -m portfolio_agent --trace "How many portfolios do we have?"` prints the SQL and 13 |
| Exposure calculator, bonds excluded | `exposure_calculator` in [tools.py](portfolio_agent/tools.py) | `python -m portfolio_agent "Sector exposure of Conservative Income Fund"` shows 4 bonds excluded |
| Command-line agent that chooses a tool | [agent.py](portfolio_agent/agent.py) | `--trace` shows the tool chosen |
| Evaluator against the ground truth | [evaluate.py](evaluate.py), [evaluation.py](portfolio_agent/evaluation.py) | `python evaluate.py`, or `--self-test` without an API key |
| Brief documentation and a diagram | This page and [docs/](docs/) | Diagram below |
| Clean code with error handling | 136 tests, Ruff lint and formatting, CI on every push | `pytest` |

**Optional enhancements:**
- **SQL safety:** parameterised queries, validation before execution and graceful database errors.
- **Operations:** logging, input validation and caching.
- **Interfaces:** a Streamlit web UI, a REST API and concurrent requests.
- **Evaluation:** scoring that favours efficient queries, and hybrid questions that use both tools.
- **Metadata retrieval:** names in the question are matched to exact database values and added to the prompt. Retrieving parts of the schema was measured and rejected. See [docs/DESIGN.md](docs/DESIGN.md).

## Run it

Requires Python 3.12 or newer and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # then set GEMINI_API_KEY
# Optional: set DEMO_PASSWORD to protect the Streamlit page with a sign-in form.
python -m portfolio_agent "How many portfolios do we have in total?"
```

| Task | Command |
| --- | --- |
| Interactive prompt | `python -m portfolio_agent` |
| Show SQL, route and timings | add `--trace` |
| Evaluate: brief's 10, or all 40 | `python evaluate.py`, add `--extended` |
| Check everything except the model, no key needed | `python evaluate.py --self-test --extended` |
| Web UI | `streamlit run streamlit_app.py`, then open http://localhost:8501 |
| REST API | `uvicorn portfolio_agent.api:app`, then see http://127.0.0.1:8000/docs |
| Tests and data audit | `pytest` and `python -m portfolio_agent --check-data` |

The database is built from the CSVs on the first run.

Render serves the Streamlit interface. Configure `GEMINI_API_KEY` in the Render dashboard for model questions; configure `DEMO_PASSWORD` there only if the reviewer should enter a shared password. A configured API key means the client is set up, not that Gemini is reachable or has quota. The REST API is available when run separately and is not the interface served by the Render Docker command.

## Ranking language

For portfolio rankings, “strongest” and “best-performing” mean the highest latest available one-year total return; “safest” means the lowest latest available volatility; and “most efficient” means the highest latest available Sharpe ratio. Responses state the selected interpretation. These defaults compare only portfolios with recorded data (performance data exists for 4 of 13 portfolios). An unqualified “best,” “healthiest,” or “highest-quality” portfolio prompts for a metric because the dataset does not define one universal measure.

## How it works

```mermaid
flowchart LR
    Q[Question] --> C{Exact repeat?}
    C -- yes --> A[Answer]
    C -- no --> L[Match names to database values]
    L --> F{Plain exposure request for one fund?}
    F -- yes --> E[Exposure calculator]
    F -- no --> M[Gemini returns a tool plan]
    M --> S[SQL guard, then run query]
    M --> E
    M --> D[Decline or ask to clarify]
    S -- invalid SQL --> R[One repair call]
    R --> S
    S --> T[Answer formatted by code]
    E --> T
    D --> A
    T --> A
```

- **One logical planning call per question** returns the whole plan, including both steps of a hybrid question. A repair can add another planning call; hedged model fallbacks can submit up to three provider requests per planning call.
- **Code writes the answer,** so the model cannot misquote or invent a figure.
- **Sector exposure for one named fund skips the model.**
- **Hedged requests:** if a model is slow or fails, the next one starts after 2.5 s, and the first answer wins.

How this design was reached through ten Gemini experiments is in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

## Documentation

- [docs/RESULTS.md](docs/RESULTS.md): live results, stability, how answers are graded, and what the data and ground truth revealed.
- [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md): every Gemini experiment and why the agent calls Gemini the way it does.
- [docs/DESIGN.md](docs/DESIGN.md): design decisions and trade-offs, safety, the REST API, deployment and the project layout.
- [reports/pre_submission_final_audit.md](reports/pre_submission_final_audit.md): final repository audit, verification results and remaining limitations.
