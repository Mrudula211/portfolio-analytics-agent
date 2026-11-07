# Evaluation report: live

- **date**: 2026-11-07 04:10 UTC
- **mode**: live model
- **dataset**: ground truth
- **command**: python evaluate.py --runs 2 --delay 13
- **commit**: d13d12b3c3c27f6170b58f894d13f6fcc157237e
- **working_tree_clean**: True
- **prompt_sha256**: 781d7b712874fccf
- **models_configured**: ['gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.1-flash-lite']
- **started_utc**: 2026-11-07 04:06:11
- **finished_utc**: 2026-11-07 04:10:43
- **wall_clock_s**: 271.8
- **api_requests**: {'gemini-3.5-flash': 16, 'gemini-3.6-flash': 14, 'gemini-3.1-flash-lite': 11}
- **api_succeeded**: {'gemini-3.5-flash': 7, 'gemini-3.6-flash': 8, 'gemini-3.1-flash-lite': 9}
- **api_failed**: {'gemini-3.1-flash-lite 504': 1, 'gemini-3.5-flash 504': 3, 'gemini-3.6-flash 504': 2, 'gemini-3.5-flash 429': 5, 'gemini-3.5-flash 503': 1, 'gemini-3.6-flash 429': 4}
- **api_requests_total**: 41
- **prompt_tokens**: 51589
- **output_tokens**: 2127

| Metric | Value |
| --- | --- |
| Cases scored | 19 |
| Model/infrastructure errors (not scored) | 1 |
| Strict accuracy | 84.2% |
| Lenient accuracy (includes partial) | 94.7% |
| Tool selection accuracy | 100.0% |
| Performance-adjusted SQL score | 0.8975 |
| Model calls per question (excluding hedges) | 0.75 |
| Answering models | {'gemini-3.5-flash': 6, 'gemini-3.1-flash-lite': 8, 'gemini-3.6-flash': 1} |
| Same verdict on every run | 9 of 9 scored more than once; scored once (outages): gt08 |

| Route | Count | p50 ms | p95 ms |
| --- | --- | --- | --- |
| fast_path | 4 | 15.54 | 28.89 |
| model | 15 | 4570.81 | 7013.92 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 16 | 2 | 19 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | model | 1714.6 | How many portfolios do we have in total? |  |
| gt01 | exact | model | 8226.9 | How many portfolios do we have in total? |  |
| gt02 | exact | model | 4570.8 | What are the names of all active portfolios? |  |
| gt02 | exact | model | 2050.1 | What are the names of all active portfolios? |  |
| gt03 | exact | model | 5575.0 | Which securities are in the Technology sector? |  |
| gt03 | exact | model | 6041.2 | Which securities are in the Technology sector? |  |
| gt04 | exact | model | 6465.3 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt04 | exact | model | 6467.5 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt05 | partial | model | 6494.1 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | missing columns: holding_id, symbol, quantity |
| gt05 | partial | model | 1836.0 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | missing columns: holding_id, symbol, quantity |
| gt06 | exact | model | 2822.8 | What is the average current price of securities in each sector? |  |
| gt06 | exact | model | 1586.2 | What is the average current price of securities in each sector? |  |
| gt07 | equivalent | model | 2740.7 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt07 | equivalent | model | 2331.6 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt08 | fail | model | 5300.2 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics | rows differ from reference |
| gt08 | infra_error | model | 12025.3 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics | model unreachable |
| gt09 | exact | fast_path | 14.6 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt09 | exact | fast_path | 31.1 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | fast_path | 14.8 | Calculate the sector exposure breakdown for international equity |  |
| gt10 | exact | fast_path | 16.3 | Calculate the sector exposure breakdown for international equity |  |
