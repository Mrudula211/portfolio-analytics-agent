# Evaluation report: live
- **command**: python evaluate.py --runs 2 --delay 6
- **commit**: 16c9b8678e13a8e3b5f492d21d553de63bf713db
- **working_tree_clean**: True
- **prompt_sha256**: 781d7b712874fccf
- **models_configured**: ['gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.6-flash']
- **started_utc**: 2026-11-07 04:36:55
- **finished_utc**: 2026-11-07 04:39:29
- **wall_clock_s**: 154.2
- **api_requests**: {'gemini-3.1-flash-lite': 16, 'gemini-3.5-flash': 11, 'gemini-3.6-flash': 7}
- **api_succeeded**: {'gemini-3.1-flash-lite': 12}
- **api_failed**: {'gemini-3.5-flash 429': 11, 'gemini-3.6-flash 429': 7, 'gemini-3.1-flash-lite 504': 3, 'gemini-3.1-flash-lite 503': 1}
- **api_requests_total**: 34
- **prompt_tokens**: 25800
- **output_tokens**: 965

- **date**: 2026-11-07 04:39 UTC
- **mode**: live model
- **dataset**: ground truth

| Metric | Value |
| --- | --- |
| Cases scored | 16 |
| Model/infrastructure errors (not scored) | 4 |
| Strict accuracy | 75.0% |
| Lenient accuracy (includes partial) | 100.0% |
| Tool selection accuracy | 100.0% |
| Performance-adjusted SQL score | 0.991 |
| Model calls per question (excluding hedges) | 0.6 |
| Answering models | {'gemini-3.1-flash-lite': 12} |
| Same verdict on every run | 6 of 6 scored more than once; scored once (outages): gt01, gt03, gt06, gt07 |

| Route | Count | p50 ms | p95 ms |
| --- | --- | --- | --- |
| fast_path | 4 | 16.09 | 19.05 |
| model | 12 | 2827.29 | 8611.46 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 12 | 4 | 16 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | infra_error | model | 11649.7 | How many portfolios do we have in total? | model unreachable |
| gt01 | exact | model | 1839.8 | How many portfolios do we have in total? |  |
| gt02 | exact | model | 7751.6 | What are the names of all active portfolios? |  |
| gt02 | exact | model | 2157.7 | What are the names of all active portfolios? |  |
| gt03 | infra_error | model | 11271.6 | Which securities are in the Technology sector? | model unreachable |
| gt03 | exact | model | 1078.4 | Which securities are in the Technology sector? |  |
| gt04 | exact | model | 2889.1 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt04 | exact | model | 9662.4 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt05 | partial | model | 2765.5 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | missing columns: holding_id, symbol, quantity |
| gt05 | partial | model | 4400.4 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | missing columns: holding_id, symbol, quantity |
| gt06 | exact | model | 2122.0 | What is the average current price of securities in each sector? |  |
| gt06 | infra_error | model | 11273.7 | What is the average current price of securities in each sector? | model unreachable |
| gt07 | infra_error | model | 2445.3 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | model unreachable |
| gt07 | equivalent | model | 5854.6 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt08 | partial | model | 1343.1 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics | missing columns: total_holdings, diversification_ratio |
| gt08 | partial | model | 3209.0 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics | missing columns: total_holdings, diversification_ratio |
| gt09 | exact | fast_path | 14.5 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt09 | exact | fast_path | 19.3 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | fast_path | 13.2 | Calculate the sector exposure breakdown for international equity |  |
| gt10 | exact | fast_path | 17.6 | Calculate the sector exposure breakdown for international equity |  |
