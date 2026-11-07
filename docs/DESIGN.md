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

## One model call, then code

The usual agent loop calls the model, runs a tool, sends the result back, and calls the model again to write a sentence. That costs two or more round trips and gives the model a chance to misquote a figure.

Here, Gemini is forced to reply with tool calls, and can return several in one reply. Hybrid questions become `run_sql` followed by `exposure_calculator(use_previous_sql_result=true)`, and the executor connects them with no further model call. Code then formats the answer.

**The trade-off:** the wording is plainer than a model's prose, and a plan cannot adapt to what a query returned. For an analytics tool, being exact and fast matters more than prose. A question needing true multi-step reasoning would require a loop, which could be added as a separate route.

The one piece of model-written text shown to users is a short result title, and it is dropped if it contains a number the user did not state.

## Model choice and hedged requests

Free-tier latency is bimodal (about 1 s or over 10 s for identical requests), and failures are common. So the client turns off the SDK's retries and hedges instead: it asks the first model, starts the next after 2.5 s or on any failure, and takes the first answer. The order is `gemini-3.1-flash-lite`, then `gemini-3.5-flash`, then `gemini-3.6-flash`, chosen by measurement. All ten experiments behind these choices are in [EXPERIMENTS.md](EXPERIMENTS.md).

**The trade-offs:** a hedge uses extra quota when it fires, and which model answers can vary, so every evaluation report records the answering model. Free-tier latency changes from day to day, so the order is worth re-measuring before relying on it.

## Deterministic fast path

A plain exposure request for one confidently matched fund skips the model, because the tool needs only a fund name. A guard sends anything more complex to the model: comparison words, several funds, or a specific sector.

**The trade-off:** a guard can misjudge. Questions it misses still reach the model and are answered correctly but slower; the risky direction is an over-eager match, so the rules are deliberately narrow and tested.

## SQL safety through SQLite's authorizer

Regular expressions over SQL text are easy to defeat. The authorizer is called for each operation in the compiled query, so what it allows is what will actually run. It is combined with a read-only file, single-statement execution and work budgets.

Testing found a real bug here: an allow-list of table names also rejected `COUNT(*)` over a CTE, because SQLite reports the CTE's name as a read. The authorizer now denies internal `sqlite_*` tables instead, and the regression is tested.

## Evaluation integrity

The worked examples in the prompt deliberately use other questions and tables than the evaluation sets, and tests enforce this, both for prompts and for the UI's stored demo questions.

Two glossary entries were once written after reading the ground truth: the formula for "diversification metrics" (Q8) and the columns to show when listing holdings (Q5). They helped exactly those questions, which made the score partly a measure of the answer key. Both were removed, so nothing in the prompt now comes from the ground truth, even if that costs those two questions.

The 30 extra questions in `eval/extended_dataset.json` were written before any tuning, but three fixes (x06, x08 and the percentage example) were made after seeing failures there. They are therefore no longer a blind test. An honest number from here needs new questions the agent has never been tuned on.

## Web UI: FastAPI with plain HTML, not Streamlit

Streamlit was suggested and would have been quicker to write. A static page on the API needs no second service, adds no per-interaction server re-run, and lets the page apply a strict Content Security Policy. The cost is more hand-written front-end code.

The page follows plindia.com's palette (royal blue, navy, teal) and its Figtree typeface, self-hosted so the security policy can stay strict. It also shows the live evaluation results and the data findings, so a reviewer sees how the agent is tested without opening the repository.

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
- The public API has per-client rate limiting and security headers, and the UI inserts data as text only.

## REST API

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the sector exposures for the Tech Innovation Fund?"}'
```

The response includes `status`, `answer`, `route`, `steps` (SQL, rows, exposures), `warnings`, `timings_ms` and `llm`. Also available: `GET /api/health`, `GET /api/about` and `GET /docs`.

## Deploy

The container serves the UI and API from one process and contains its own database.

- **Render (free):** in the Render dashboard choose **New > Blueprint**, select this repository, and set `GEMINI_API_KEY`. Set `DEMO_PASSWORD` to require a password (any username) for everything except the health check. The free plan sleeps after about 15 idle minutes, so the first visit after a pause takes up to a minute.
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
  api.py, static/ REST API and web UI
  demo_plans.json Gemini's stored plans for the UI's example questions
evaluate.py       evaluation command
eval/             the 30 extra evaluation questions
scripts/          stored demo plans
reports/          live evaluation reports
tests/            unit and integration tests
```
