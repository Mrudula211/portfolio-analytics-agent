# Evaluation report: local_fallback

- **date**: 2026-11-09 17:24 UTC
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
| direct_calculator | 2 | 4.7 | 4.73 |
| local_deterministic | 8 | 4.8 | 8.73 |

| Category | Passed | Partial | Total |
| --- | --- | --- | --- |
| ground_truth | 10 | 0 | 10 |

| ID | Verdict | Route | ms | Question | Detail |
| --- | --- | --- | --- | --- | --- |
| gt01 | exact | local_deterministic | 4.7 | [assessment question Q1] |  |
| gt02 | exact | local_deterministic | 3.1 | [assessment question Q2] |  |
| gt03 | exact | local_deterministic | 3.3 | [assessment question Q3] |  |
| gt04 | exact | local_deterministic | 6.0 | [assessment question Q4] |  |
| gt05 | exact | local_deterministic | 4.9 | [assessment question Q5] |  |
| gt06 | exact | local_deterministic | 4.7 | [assessment question Q6] |  |
| gt07 | exact | local_deterministic | 9.3 | [assessment question Q7] |  |
| gt08 | exact | local_deterministic | 7.6 | [assessment question Q8] |  |
| gt09 | exact | direct_calculator | 4.7 | [assessment question Q9] |  |
| gt10 | exact | direct_calculator | 4.7 | [assessment question Q10] |  |
