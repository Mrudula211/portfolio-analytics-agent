# Ground-truth audit

Source: `ground_truth_dataset.json` (read directly; unchanged). The ten cases below preserve the exact question and reference contract.

## Q1 ? How many portfolios do we have in total?

- Type: `text2sql`; expected result: `single_value`.
- Reference SQL: `SELECT COUNT(*) FROM portfolios;`
- Official explanation: Simple COUNT query on portfolios table
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q2 ? What are the names of all active portfolios?

- Type: `text2sql`; expected result: `list`.
- Reference SQL: `SELECT portfolio_name FROM portfolios WHERE status = 'Active';`
- Official explanation: Simple SELECT with WHERE clause filtering by status
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q3 ? Which securities are in the Technology sector?

- Type: `text2sql`; expected result: `table`.
- Reference SQL: `SELECT s.symbol, s.company_name FROM securities s JOIN sectors sec ON s.sector_id = sec.sector_id WHERE sec.sector_name = 'Technology';`
- Official explanation: JOIN between securities and sectors tables with simple WHERE filter
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q4 ? What is the total Assets Under Management (AUM) for portfolios with high target risk level?

- Type: `text2sql`; expected result: `single_value`.
- Reference SQL: `SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level = 'High';`
- Official explanation: Aggregation function with WHERE clause filtering by risk level
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q5 ? Show me the top 5 holdings by cost basis in the Growth Equity Fund

- Type: `text2sql`; expected result: `table`.
- Reference SQL: `SELECT h.holding_id, s.symbol, s.company_name, h.quantity, h.cost_basis FROM holdings h JOIN securities s ON h.security_id = s.security_id JOIN portfolios p ON h.portfolio_id = p.portfolio_id WHERE p.portfolio_name = 'Growth Equity Fund' ORDER BY h.cost_basis DESC LIMIT 5;`
- Official explanation: Multiple JOINs with ORDER BY and LIMIT for top N results
- Output contract: `holding_id`, `symbol`, `company_name`, `quantity`, `cost_basis`; top five by descending cost basis for the exact named portfolio.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q6 ? What is the average current price of securities in each sector?

- Type: `text2sql`; expected result: `table`.
- Reference SQL: `SELECT sec.sector_name, AVG(s.current_price) as avg_price FROM securities s JOIN sectors sec ON s.sector_id = sec.sector_id GROUP BY sec.sector_name ORDER BY avg_price DESC;`
- Official explanation: JOIN with GROUP BY aggregation and ordering
- Output contract: `sector_name`, `avg_price`; average current price grouped by sector, descending average.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q7 ? For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value

- Type: `text2sql`; expected result: `table`.
- Reference SQL: `WITH portfolio_tech_value AS (SELECT p.portfolio_id, p.portfolio_name, SUM(h.quantity * s.current_price) as tech_value FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id JOIN securities s ON h.security_id = s.security_id JOIN sectors sec ON s.sector_id = sec.sector_id WHERE sec.sector_name = 'Technology' GROUP BY p.portfolio_id, p.portfolio_name), portfolio_total_value AS (SELECT p.portfolio_id, SUM(h.quantity * s.current_price) as total_value FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id JOIN securities s ON h.security_id = s.security_id GROUP BY p.portfolio_id) SELECT ptv.portfolio_name, ptv.tech_value, ptv2.total_value, ROUND((ptv.tech_value / ptv2.total_value) * 100, 2) as tech_percentage FROM portfolio_tech_value ptv JOIN portfolio_total_value ptv2 ON ptv.portfolio_id = ptv2.portfolio_id ORDER BY tech_percentage DESC;`
- Official explanation: Complex query using CTEs, multiple JOINs, aggregations, and percentage calculations
- Reference semantics: CTEs independently aggregate Technology holding value and total holdings value (`quantity * current_price`); inner joins omit portfolios with no Technology holdings; percentage rounded to two decimals; sorted by percentage descending.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q8 ? Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics

- Type: `text2sql`; expected result: `table`.
- Reference SQL: `WITH portfolio_sector_count AS (SELECT p.portfolio_id, p.portfolio_name, COUNT(DISTINCT sec.sector_id) as sector_count FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id JOIN securities s ON h.security_id = s.security_id JOIN sectors sec ON s.sector_id = sec.sector_id WHERE s.asset_type = 'Stock' GROUP BY p.portfolio_id, p.portfolio_name HAVING COUNT(DISTINCT sec.sector_id) > 5), portfolio_holdings_count AS (SELECT p.portfolio_id, COUNT(h.holding_id) as total_holdings FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id GROUP BY p.portfolio_id) SELECT psc.portfolio_name, psc.sector_count, phc.total_holdings, ROUND(CAST(psc.sector_count AS REAL) / phc.total_holdings, 3) as diversification_ratio FROM portfolio_sector_count psc JOIN portfolio_holdings_count phc ON psc.portfolio_id = phc.portfolio_id ORDER BY diversification_ratio DESC;`
- Official explanation: Advanced query with multiple CTEs, HAVING clause, and calculated diversification metrics
- Reference semantics: count distinct sectors only for `Stock` securities; `HAVING ... > 5`; denominator counts all holdings; ratio `sector_count / total_holdings`, rounded to three decimals; descending ratio.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q9 ? What are the sector exposures for the Tech Innovation Fund?

- Type: `exposure_calculator`; expected result: `sector_exposure_breakdown`.
- Reference tool: `exposure_calculator`; exact parameters: `{"portfolio_name": "Tech Innovation Fund"}`
- Official explanation: Calculate sector exposures by combining holding weights with security sector mappings, excluding bonds
- Production expectation: dynamically calculate equity sector exposure, excluding bonds; resolve portfolio identity through database-backed entity linking.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.

## Q10 ? Calculate the sector exposure breakdown for international equity

- Type: `exposure_calculator`; expected result: `sector_exposure_breakdown`.
- Reference tool: `exposure_calculator`; exact parameters: `{"portfolio_name": "International Equity Fund"}`
- Official explanation: Calculate sector exposures using portfolio ID as identifier, focusing only on equity holdings
- Production expectation: dynamically calculate equity sector exposure, excluding bonds; resolve portfolio identity through database-backed entity linking.
- Current status: production-agent local evaluation is exact; route and evidence are recorded in `local_fallback.md`.
- Required regression coverage: intent and parameter extraction, actual guarded tool call, exact output shape/values, alias resolution where applicable, and unsupported/ambiguous wording behavior.
