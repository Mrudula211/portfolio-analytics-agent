# Evaluation report: self_test

- **date**: 2026-11-04 18:15 UTC
- **mode**: SELF-TEST: reference plans replayed, not model accuracy
- **model**: none (self-test)
- **schema_mode**: full
- **runs**: 1
- **dataset**: ground truth

| Metric | Value |
| --- | --- |
| Cases scored | 10 |
| Model/infrastructure errors (not scored) | 0 |
| Strict accuracy | 100.0% |
| Lenient accuracy (includes partial) | 100.0% |
| Tool selection accuracy | 100.0% |
| Performance-adjusted SQL score | 1.0 |
| Model calls per question | 0.8 |

| Route | Count | p50 ms | p95 ms |
| --- | --- | --- | --- |
| fast_path | 2 | 8.42 | 8.46 |
| model | 8 | 8.02 | 14.58 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 10 | 0 | 10 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | model | 6.2 | How many portfolios do we have in total? |  |
| gt02 | exact | model | 5.4 | What are the names of all active portfolios? |  |
| gt03 | exact | model | 4.8 | Which securities are in the Technology sector? |  |
| gt04 | exact | model | 9.9 | What is the total Assets Under Management (AUM) for portfolios with high target risk level? |  |
| gt05 | exact | model | 8.1 | Show me the top 5 holdings by cost basis in the Growth Equity Fund |  |
| gt06 | exact | model | 7.9 | What is the average current price of securities in each sector? |  |
| gt07 | exact | model | 15.6 | For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value |  |
| gt08 | exact | model | 12.7 | Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics |  |
| gt09 | exact | fast_path | 8.5 | What are the sector exposures for the Tech Innovation Fund? |  |
| gt10 | exact | fast_path | 8.4 | Calculate the sector exposure breakdown for international equity |  |
