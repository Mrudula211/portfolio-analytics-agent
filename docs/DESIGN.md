# Design decisions

The reasoning behind the main choices, what was rejected, and what is still weak.

## Should this use a vector database?

**No, and it was tested rather than assumed.** Semantic search is good at finding relevant passages in a large collection. Here, the collection is nine tables.

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

The first live run used `gemini-3.5-flash-lite` on the assumption that a Lite model would be fastest. It took about 9 s at the median and 36 s at p95. Calling models directly, with retries off, showed why (five calls each on the free tier, in one session, so treat this as indicative):

| Model | Successful calls | Failures |
| --- | --- | --- |
| `gemini-3.5-flash` | 1.3 to 1.7 s | Two fast 503s |
| `gemini-3.6-flash` | 1.9 to 3.3 s | None |
| `gemini-3.1-flash-lite` | 1.0 to 9.9 s | One 504 after 24.6 s |
| `gemini-3.5-flash-lite` | 1.2 to 13.4 s | None |
| `gemini-flash-lite-latest` | 9.2 to 14.5 s | None |
| `gemini-3.8-flash` | None | Five 503 or 504 |

Latency is bimodal and failures are common, and the SDK's automatic retries made it worse by waiting on a congested model. The client now disables them and hedges: it asks `gemini-3.5-flash`, and starts the next model after 2.5 s or on any failure, taking the first answer. In the next run, model-routed questions that got an answer took 1.7 s at the median and 2.5 s at p95.

**The trade-offs:** a hedge uses extra quota when it fires, and which model answers can vary, so the evaluation report records the answering model for every question. These numbers will change, so they are worth re-measuring before relying on a model.

**Free-tier quota is a real constraint:** 20 requests per model per day. Evaluation therefore paces itself and can resume, and outages are reported separately from accuracy.

## Deterministic fast path

A plain exposure request for one confidently matched fund skips the model, because the tool needs only a fund name. A guard sends anything more complex to the model: comparison words, several funds, or a specific sector.

**The trade-off:** a guard can misjudge. Questions it misses still reach the model and are answered correctly but slower; the risky direction is an over-eager match, so the rules are deliberately narrow and tested.

## SQL safety through SQLite's authorizer

Regular expressions over SQL text are easy to defeat. The authorizer is called for each operation in the compiled query, so what it allows is what will actually run. It is combined with a read-only file, single-statement execution and work budgets.

Testing found a real bug here: an allow-list of table names also rejected `COUNT(*)` over a CTE, because SQLite reports the CTE's name as a read. The authorizer now denies internal `sqlite_*` tables instead, and the regression is tested.

## Evaluation integrity

The worked examples in the prompt deliberately use other questions and tables than the evaluation sets, and a test enforces this. Two glossary entries were informed by reading the ground truth and are disclosed here: the definition of "diversification metrics", and the columns shown when listing holdings. They are reasonable house definitions that a real team would write down, but they do help Q5 and Q8. Removing them measures how the agent does without that help.

If prompts are tuned against `eval/extended_dataset.json`, it stops being held out. A new set of unseen questions is then needed for an honest number.

## Web UI: FastAPI with plain HTML, not Streamlit

Streamlit was suggested and would have been quicker to write. A static page on the API needs no second service, adds no per-interaction server re-run, and lets the page apply a strict Content Security Policy. The cost is more hand-written front-end code.

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
