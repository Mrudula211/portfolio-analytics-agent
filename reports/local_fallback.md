# Evaluation report: local_fallback

- **date**: 2026-11-09 02:46 UTC
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
| direct_calculator | 2 | 12.53 | 12.77 |
| local_deterministic | 8 | 13.83 | 26.24 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 10 | 0 | 10 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | local_deterministic | 13.5 | How many portfolios do we have in total? |  |
| gt02 | exact | local_deterministic | 9.8 | What are the names of all active portfolios? |  |
| gt03 | exact | local_deterministic | 8.2 | Which securities are in the Technology sector? |  |
| gt04 | exact | local_deterministic | 15.5 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt05 | exact | local_deterministic | 12.8 | Show me the top 5 holdings by cost basis in the Growth Equity Fund |  |
| gt06 | exact | local_deterministic | 14.1 | What is the average current price of securities in each sector? |  |
| gt07 | exact | local_deterministic | 27.9 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value |  |
| gt08 | exact | local_deterministic | 23.2 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt09 | exact | direct_calculator | 12.8 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | direct_calculator | 12.3 | Calculate the sector exposure breakdown for international equity |  |
