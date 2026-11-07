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

- **Brief's 10 questions:** 8 correct and 2 partly correct (Q5 and Q8), with the same verdicts in all three live runs.
- **All 40 questions** (the brief's 10 plus 30 I wrote): 92.3% strict accuracy. Safety and refusal cases: 10 of 10.
- **Speed:**
  - under 1 ms for repeat questions
  - about 10 ms for sector exposure, which skips the model
  - a median of 2.1 s when Gemini is needed, on the free tier
- **Every failure, cost and caveat** is in [docs/RESULTS.md](docs/RESULTS.md).

## Requirements checklist

| Brief item | Where | How to check it |
| --- | --- | --- |
| SQL query tool | `run_sql` in [tools.py](portfolio_agent/tools.py), guarded by [sql_guard.py](portfolio_agent/sql_guard.py) | `python -m portfolio_agent --trace "How many portfolios do we have?"` prints the SQL and 13 |
| Exposure calculator, bonds excluded | `exposure_calculator` in [tools.py](portfolio_agent/tools.py) | `python -m portfolio_agent "Sector exposure of Conservative Income Fund"` shows 4 bonds excluded |
| Command-line agent that chooses a tool | [agent.py](portfolio_agent/agent.py) | `--trace` shows the tool chosen |
| Evaluator against the ground truth | [evaluate.py](evaluate.py), [evaluation.py](portfolio_agent/evaluation.py) | `python evaluate.py`, or `--self-test` without an API key |
| Brief documentation and a diagram | This page and [docs/](docs/) | Diagram below |
| Clean code with error handling | 111 tests, the `ruff` linter, CI on every push | `pytest` |

**Optional enhancements:**
- **SQL safety:** parameterised queries, validation before execution and graceful database errors.
- **Operations:** logging, input validation and caching.
- **Interfaces:** a web UI (FastAPI and HTML instead of Streamlit), a REST API and concurrent requests.
- **Evaluation:** scoring that favours efficient queries, and hybrid questions that use both tools.
- **Metadata retrieval:** names in the question are matched to exact database values and added to the prompt. Retrieving parts of the schema was measured and rejected. See [docs/DESIGN.md](docs/DESIGN.md).

## Run it

Requires Python 3.12 or newer and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # then set GEMINI_API_KEY
python -m portfolio_agent "How many portfolios do we have in total?"
```

| Task | Command |
| --- | --- |
| Interactive prompt | `python -m portfolio_agent` |
| Show SQL, route and timings | add `--trace` |
| Evaluate: brief's 10, or all 40 | `python evaluate.py`, add `--extended` |
| Check everything except the model, no key needed | `python evaluate.py --self-test --extended` |
| Web UI and REST API | `uvicorn portfolio_agent.api:app`, then open http://127.0.0.1:8000 |
| Tests and data audit | `pytest` and `python -m portfolio_agent --check-data` |

The database is built from the CSVs on the first run.

## How it works

```mermaid
flowchart LR
    Q[Question] --> C{Exact repeat?}
    C -- yes --> A[Answer]
    C -- no --> L[Match names to database values]
    L --> F{Plain exposure request for one fund?}
    F -- yes --> E[Exposure calculator]
    F -- no --> M[One Gemini call returns a tool plan]
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

- **One Gemini call per question**, which returns the whole plan, including both steps of a hybrid question.
- **Code writes the answer,** so the model cannot misquote or invent a figure.
- **Sector exposure for one named fund skips the model.**
- **Hedged requests:** if a model is slow or fails, the next one starts after 2.5 s, and the first answer wins.

How this design was reached through ten Gemini experiments is in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

## Documentation

- [docs/RESULTS.md](docs/RESULTS.md): live results, stability, how answers are graded, and what the data and ground truth revealed.
- [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md): every Gemini experiment and why the agent calls Gemini the way it does.
- [docs/DESIGN.md](docs/DESIGN.md): design decisions and trade-offs, safety, the REST API, deployment and the project layout.
