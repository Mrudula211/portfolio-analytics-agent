# Design decisions

The reasoning behind the main choices, what was rejected, and what is still weak.

## Retrieval (RAG) and vector databases

The brief suggests RAG "to find the right metadata related to the user question to be used in the context". The agent does this. Before each Gemini call, the entity linker finds the portfolios, sectors and securities a question mentions, including partial names and typos, and adds their exact database values to the prompt (`Links` in [metadata.py](../portfolio_agent/metadata.py)). It uses lexical matching, not embeddings. What was tested and rejected is retrieving parts of the schema, below.

**Should this use a vector database? No, and that was tested rather than assumed.** Semantic search is good at finding relevant passages in a large collection. Here, the collection is nine tables.

I compared sending the full schema with in-process retrieval (BM25 plus foreign-key graph expansion), across the 23 evaluation questions that have a reference query. The benchmark and retrieval code were then removed as unneeded, and remain in git history at commit `95db72b`:

| | Full schema | Retrieved schema |
| --- | --- | --- |
| Questions where every needed table is present | 23 of 23 | 20 of 23 (87%) |
| System prompt size | about 1,590 tokens | about 1,110 tokens |
| Added network calls | 0 | 0 |

Retrieval saves about 480 tokens but hides a needed table on three questions, including assignment Q5. A query cannot be correct if the model never saw the table. Embeddings might improve recall, but this was not measured, and they would add a network call before every question or a model and an index in the container, in exchange for those same 480 tokens.

So the agent sends the full schema.

The problems retrieval is usually brought in to solve are handled more directly:

| Problem | Solution |
| --- | --- |
| "international equity" must become `International Equity Fund` | Entity linker: exact aliases, typo tolerance, and candidates when ambiguous |
| The model must know valid values, such as `status` | Generated schema cards list short vocabularies |
| Domain definitions, such as "value" | A small glossary |

**Semantic caching was rejected for accuracy.** "AUM for high risk funds" and "AUM for low risk funds" are near neighbours in embedding space with different answers. The cache matches normalised text only, trading some hit rate for never serving another question's answer.

**When a vector database becomes right:** hundreds of tables, or the unstructured work in this role's description, such as searching research reports and financial documents. Those are real retrieval problems.

## One model plan, then code

The usual agent loop calls the model, runs a tool, sends the result back, and calls the model again to write a sentence. That costs two or more round trips and gives the model a chance to misquote a figure.

Here, Gemini is forced to reply with tool calls, and can return several in one reply. Hybrid questions become `run_sql` followed by `exposure_calculator(use_previous_sql_result=true)`, and the executor connects them with no further planning call. Code then formats the answer.

**The trade-off:** the wording is plainer than a model's prose, and a plan cannot adapt to what a query returned. For an analytics tool, being exact and fast matters more than prose. A question needing true multi-step reasoning would require a loop, which could be added as a separate route.

The one piece of model-written text shown to users is a short result title, and it is dropped if it contains a number the user did not state.

## Model choice and hedged requests

Free-tier latency is bimodal (about 1 s or over 10 s for identical requests), and failures are common. So the client turns off the SDK's retries and hedges instead: it asks the first model, starts the next after 2.5 s or on any failure, and takes the first answer. The order is `gemini-3.1-flash-lite`, then `gemini-3.5-flash`, then `gemini-3.6-flash`, chosen by measurement. All ten experiments behind these choices are in [EXPERIMENTS.md](EXPERIMENTS.md).

**The trade-offs:** a hedge uses extra quota when it fires, and which model answers can vary, so every evaluation report records the answering model. One plan can submit up to three provider requests; a SQL repair is another plan and can raise the worst case to six. The evaluation counter reports logical plan calls, not hedge requests. Free-tier latency changes from day to day, so the order is worth re-measuring before relying on it. For low-quota validation, set `GEMINI_FALLBACK_MODELS` to an empty list (`,` in PowerShell) to avoid fallback submissions.

## Portfolio ranking terms

Some financial superlatives have a documented default: strongest/best-performing uses the highest latest available one-year total return; safest uses the lowest latest available volatility; and most efficient uses the highest latest available Sharpe ratio. The answer states the selected interpretation and is checked against each portfolio's latest available performance row. Only 4 of 13 portfolios have performance history, so rankings are qualified as covering portfolios with available data. An unqualified best, healthiest or highest-quality question asks the user which measure they mean. These defaults are application semantics, not universal financial definitions.

## Deterministic fast path

A plain exposure request for one confidently matched fund skips the model, because the tool needs only a fund name. A guard sends anything more complex to the model: comparison words, several funds, or a specific sector.

**The trade-off:** a guard can misjudge. Questions it misses still reach the model and are answered correctly but slower; the risky direction is an over-eager match, so the rules are deliberately narrow and tested.

## SQL safety through SQLite's authorizer

Regular expressions over SQL text are easy to defeat. The authorizer is called for each operation in the compiled query, so what it allows is what will actually run. It is combined with a read-only file, single-statement execution and work budgets.

Testing found a real bug here: an allow-list of table names also rejected `COUNT(*)` over a CTE, because SQLite reports the CTE's name as a read. The authorizer now denies internal `sqlite_*` tables instead, and the regression is tested.

## Evaluation integrity

The worked examples in the prompt deliberately use other questions and tables than the evaluation sets, and tests enforce this, both for prompts and for the UI's stored demo questions.

The original assessment leaves Q5's projection expectations and Q8's ratio semantics underspecified in the question text, while its provided reference defines them. The current implementation adds generic holding-row projection rules and an explicitly labelled, assessment-defined sector-diversification ratio. It includes the stated formula and field meanings, but does not include the assessment question text, question IDs, reference SQL, or expected answer rows. Deterministic checks compare generated results with a separate calculation from holding facts. These two cases are now informed by the assessment requirements and should not be described as blind tests; their purpose is to check that the app follows the stated acceptance criteria and remains correct on paraphrases.

Hybrid scoring checks the SQL selection against its reference result, verifies that the exposure calculations use those selected portfolios, and checks the exposure values independently.

The 30 extra questions in `eval/extended_dataset.json` were written before any tuning, but three fixes (x06, x08 and the percentage example) were made after seeing failures there. They are therefore no longer a blind test. An honest number from here needs new questions the agent has never been tuned on.

## Web UI: Streamlit, with a separate REST API

The brief suggests Streamlit, and it replaced an earlier hand-written HTML and JavaScript page: about 550 lines of front-end code became one Python file, `streamlit_app.py`. The app calls the agent in-process, through a single shared instance per server, so the UI and the command line run exactly the same code. The REST API (`portfolio_agent/api.py`) remains for programmatic use. It is no longer what the demo serves.

The UI is laid out as a workspace rather than a landing page:
- **Sidebar:** example questions, dataset facts and the data notes.
- **Query tab:** the answer appears above the fold. It shows the route taken and the time, then tables, exposure charts with tooltips, and the SQL behind each answer.
- **Evaluation tab:** the live results, by category and for every question.

Colours follow plindia.com, and its Figtree typeface is self-hosted. Text from users or the database is escaped before display, so it can never be interpreted as Markdown or HTML.

**The trade-offs:**
- Streamlit re-runs the script on every interaction. The agent and dataset facts are cached, so a re-run is cheap.
- Its look can only be adjusted so far.
- It cannot send HTTP Basic auth challenges, so the demo password is a sign-in form instead.
- The Gemini status says “configured” when a client is constructed; it does not claim the provider is reachable.

## Stored plans for demo questions

The free tier allows 20 requests per model per day, which a few curious visitors could exhaust. The example questions in the UI therefore use plans Gemini produced once (`scripts/save_demo_plans.py`). The plan, not the answer, is stored: it runs against the database at start-up, so figures always come from the current data. These answers are labelled "Cached", and evaluation never uses them.

## SQLite file, not in-memory

The brief mentions both. A read-only file gives every request an independent connection, with no shared-cache locking to manage, and adds file-level write protection. Opening it takes well under the latency that matters here.

## Known limitations

- **Single-turn only.** "What about the second one?" has no context.
- **Live accuracy depends on the model,** and results vary as models change. Re-run the evaluation when changing `GEMINI_MODEL`.
- **Per-process cache and rate limits.** Several replicas would need shared storage such as Redis.
- **Client identity is an IP address,** which shared networks and proxies can blur.
- **Simple tolerance rules in the scorer.** Values are matched after rounding to the coarser of the two precisions, with a minimum of two decimal places, so small differences in small numbers can pass.
- **Sample data only.** Real client data would also need authentication, per-user row-level access and audit logging before any use.

## What I would do next

1. Stream a progress state to the UI so waits feel shorter.
2. Add single-flight de-duplication, so identical concurrent questions share one model call.
3. Log question, plan and outcome for review, turning real failures into new evaluation cases.
4. Add conversation state for follow-up questions.
5. Add document search over research reports, where a vector database would earn its place.

## Safety

Model-written SQL is treated as untrusted:

- The database file is opened read-only.
- An SQLite authorizer permits only `SELECT` on data tables and safe functions. It checks the compiled query, so text tricks do not get past it.
- One statement per query, with limits on time, work, rows and value size.
- Blocked queries are refused and never sent back for repair.
- Query results and stored free text never reach the model, so data cannot act as a prompt injection, and a failed query returns only the database's error message.
- The agent declines recommendations, forecasts and anything outside the data. It asks when a name could mean several funds.
- The web app and the API limit each client to 20 questions a minute. They identify clients by the address the hosting proxy recorded: the rightmost `X-Forwarded-For` entry, which a client cannot forge.
- A daily cap on questions sent to Gemini, shared by all users (`DAILY_MODEL_QUESTIONS`, 300 on Render), stops one visitor from using up the day's quota. The cached example questions keep working past the cap.
- The UI escapes text from users and the database before display.

**Data governance.** On Gemini's free tier, Google may use prompts to improve its products. Here a prompt contains only the schema, a short glossary, matched names and the user's question, never query results or holdings. A production deployment on client data would use a paid, enterprise or self-hosted model endpoint covered by a data-processing agreement.

## REST API

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the sector exposures for the Tech Innovation Fund?"}'
```

The response includes `status`, `answer`, `route`, `steps` (SQL, rows, exposures), `warnings`, `timings_ms` and `llm`. Also available: `GET /api/health` and `GET /docs`. Run it with `uvicorn portfolio_agent.api:app`.

## Deploy

The container serves the Streamlit app and contains its own database. Its health check is Streamlit's `/_stcore/health`.

- **Render (free):** in the Render dashboard choose **New > Blueprint**, select this repository, and set `GEMINI_API_KEY`. The Blueprint sets `DAILY_MODEL_QUESTIONS` to 300. Set `DEMO_PASSWORD` to show a sign-in form before anything else loads. The free plan sleeps after about 15 idle minutes, so the first visit after a pause takes up to a minute.
- **Any container host:** `docker build -t portfolio-agent . && docker run -p 7860:7860 -e GEMINI_API_KEY=... portfolio-agent`

## Project layout

```text
portfolio_agent/
  agent.py        routing and plan execution
  tools.py        exposure calculator and SQL tool
  sql_guard.py    safe execution of model-written SQL
  metadata.py     schema cards, glossary, entity linking
  prompts.py      prompt assembly
  llm.py          Gemini client
  render.py       answer formatting, no model involved
  cache.py        exact-match cache
  db.py           database build and data audit
  evaluation.py   scoring
  api.py          REST API
  demo.py         stored demo plans, dataset facts, evaluation report
  ratelimit.py    per-client rate limiting
  demo_plans.json Gemini's stored plans for the UI's example questions
streamlit_app.py web UI
.streamlit/      UI theme
static/           self-hosted font
evaluate.py       evaluation command
eval/             the 30 extra evaluation questions
scripts/          stored demo plans
reports/          live evaluation reports
tests/            unit and integration tests
```
