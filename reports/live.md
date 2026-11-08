# Evaluation report: live

- **date**: 2026-11-08 10:42 UTC
- **mode**: live model
- **dataset**: ground truth

| Metric | Value |
| --- | --- |
| Cases scored | 25 |
| Model/infrastructure errors (not scored) | 5 |
| Strict accuracy | 100.0% |
| Lenient accuracy (includes partial) | 100.0% |
| Tool selection accuracy | 100.0% |
| Performance-adjusted SQL score | 0.9882 |
| Model calls per question (excluding hedges) | 0.633 |
| Answering models | {'gemini-3.1-flash-lite': 19} |
| Same verdict on every run | 8 of 8 scored more than once; scored once (outages): gt05 |

| Route | Count | p50 ms | p95 ms |
| --- | --- | --- | --- |
| fast_path | 6 | 12.52 | 13.23 |
| model | 19 | 4559.24 | 11376.44 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 25 | 0 | 25 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | model | 4129.5 | How many portfolios do we have in total? |  |
| gt01 | exact | model | 2627.1 | How many portfolios do we have in total? |  |
| gt01 | exact | model | 11993.3 | How many portfolios do we have in total? |  |
| gt02 | exact | model | 2339.1 | What are the names of all active portfolios? |  |
| gt02 | exact | model | 1454.6 | What are the names of all active portfolios? |  |
| gt02 | exact | model | 5296.3 | What are the names of all active portfolios? |  |
| gt03 | exact | model | 3743.3 | Which securities are in the Technology sector? |  |
| gt03 | exact | model | 2390.7 | Which securities are in the Technology sector? |  |
| gt03 | exact | model | 3479.5 | Which securities are in the Technology sector? |  |
| gt04 | infra_error | model | 12021.6 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? | model unreachable |
| gt04 | infra_error | model | 12016.5 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? | model unreachable |
| gt04 | infra_error | model | 12019.7 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? | model unreachable |
| gt05 | exact | model | 4213.1 | Show me the top 5 holdings by cost basis in the Growth Equity Fund |  |
| gt05 | infra_error | model | 12013.5 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | model unreachable |
| gt05 | infra_error | model | 12025.7 | Show me the top 5 holdings by cost basis in the Growth Equity Fund | model unreachable |
| gt06 | exact | model | 2690.9 | What is the average current price of securities in each sector? |  |
| gt06 | exact | model | 7246.2 | What is the average current price of securities in each sector? |  |
| gt06 | exact | model | 4782.1 | What is the average current price of securities in each sector? |  |
| gt07 | equivalent | model | 5438.8 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt07 | equivalent | model | 11307.9 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt07 | equivalent | model | 4559.2 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value | 5 extra zero rows |
| gt08 | exact | model | 9555.6 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt08 | exact | model | 6897.8 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt08 | exact | model | 4674.3 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt09 | exact | fast_path | 12.0 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt09 | exact | fast_path | 12.7 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt09 | exact | fast_path | 13.3 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | fast_path | 10.0 | Calculate the sector exposure breakdown for international equity |  |
| gt10 | exact | fast_path | 12.9 | Calculate the sector exposure breakdown for international equity |  |
| gt10 | exact | fast_path | 12.3 | Calculate the sector exposure breakdown for international equity |  |
