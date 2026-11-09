# Evaluation report: local_fallback

- **date**: 2026-11-09 02:31 UTC
- **mode**: LOCAL FALLBACK: the production agent's deterministic planner, no model
- **dataset**: ground truth
- **gemini_client**: none (no API key, no client built)
- **network_connection_attempts**: 0
- **cache**: disabled
- **stored_demo_plans**: not loaded

| Metric | Value |
| --- | --- |
| Cases scored | 10 |
| Model/infrastructure errors (not scored) | 0 |
| Infrastructure categories | {} |
| Strict accuracy | 100.0% |
| Lenient accuracy (includes partial) | 100.0% |
| Tool selection accuracy | 100.0% |
| Performance-adjusted SQL score | 1.0 |
| Model calls per question (excluding hedges) | 0.0 |
| Answering models | {'local planner': 8} |
| Same verdict on every run | single run |

| Route | Count | p50 ms | p95 ms |
| --- | --- | --- | --- |
| direct_calculator | 2 | 8.84 | 10.2 |
| local_deterministic | 8 | 13.31 | 20.29 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 10 | 0 | 10 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | local_deterministic | 6.5 | How many portfolios do we have in total? |  |
| gt02 | exact | local_deterministic | 8.2 | What are the names of all active portfolios? |  |
| gt03 | exact | local_deterministic | 8.7 | Which securities are in the Technology sector? |  |
| gt04 | exact | local_deterministic | 14.8 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt05 | exact | local_deterministic | 12.9 | Show me the top 5 holdings by cost basis in the Growth Equity Fund |  |
| gt06 | exact | local_deterministic | 13.8 | What is the average current price of securities in each sector? |  |
| gt07 | exact | local_deterministic | 22.8 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value |  |
| gt08 | exact | local_deterministic | 15.6 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt09 | exact | direct_calculator | 10.4 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | direct_calculator | 7.3 | Calculate the sector exposure breakdown for international equity |  |
