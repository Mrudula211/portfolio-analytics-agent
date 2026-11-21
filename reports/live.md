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
| gt01 | exact | model | 4129.5 | [assessment question Q1] |  |
| gt01 | exact | model | 2627.1 | [assessment question Q1] |  |
| gt01 | exact | model | 11993.3 | [assessment question Q1] |  |
| gt02 | exact | model | 2339.1 | [assessment question Q2] |  |
| gt02 | exact | model | 1454.6 | [assessment question Q2] |  |
| gt02 | exact | model | 5296.3 | [assessment question Q2] |  |
| gt03 | exact | model | 3743.3 | [assessment question Q3] |  |
| gt03 | exact | model | 2390.7 | [assessment question Q3] |  |
| gt03 | exact | model | 3479.5 | [assessment question Q3] |  |
| gt04 | infra_error | model | 12021.6 | [assessment question Q4] | model unreachable |
| gt04 | infra_error | model | 12016.5 | [assessment question Q4] | model unreachable |
| gt04 | infra_error | model | 12019.7 | [assessment question Q4] | model unreachable |
| gt05 | exact | model | 4213.1 | [assessment question Q5] |  |
| gt05 | infra_error | model | 12013.5 | [assessment question Q5] | model unreachable |
| gt05 | infra_error | model | 12025.7 | [assessment question Q5] | model unreachable |
| gt06 | exact | model | 2690.9 | [assessment question Q6] |  |
| gt06 | exact | model | 7246.2 | [assessment question Q6] |  |
| gt06 | exact | model | 4782.1 | [assessment question Q6] |  |
| gt07 | equivalent | model | 5438.8 | [assessment question Q7] | 5 extra zero rows |
| gt07 | equivalent | model | 11307.9 | [assessment question Q7] | 5 extra zero rows |
| gt07 | equivalent | model | 4559.2 | [assessment question Q7] | 5 extra zero rows |
| gt08 | exact | model | 9555.6 | [assessment question Q8] |  |
| gt08 | exact | model | 6897.8 | [assessment question Q8] |  |
| gt08 | exact | model | 4674.3 | [assessment question Q8] |  |
| gt09 | exact | fast_path | 12.0 | [assessment question Q9] |  |
| gt09 | exact | fast_path | 12.7 | [assessment question Q9] |  |
| gt09 | exact | fast_path | 13.3 | [assessment question Q9] |  |
| gt10 | exact | fast_path | 10.0 | [assessment question Q10] |  |
| gt10 | exact | fast_path | 12.9 | [assessment question Q10] |  |
| gt10 | exact | fast_path | 12.3 | [assessment question Q10] |  |
