"""Deterministic planner: turns supported question intents into tool calls without any model.

It answers when no Gemini key is configured, and takes over when Gemini is unavailable or returns
an unusable plan. It is a bounded intent library, not general text-to-SQL: each intent has a
parameterised SQL template, and every parameter (portfolio, sector, risk level, status, a count,
a threshold) comes from the question and is validated against the database's own vocabulary.
Unsupported wording returns None, and the agent reports that instead of guessing.

The templates encode the semantics the assessment defines for each kind of question, for example
market value as quantity x current price, and the diversification ratio over stock sectors against
all holdings. The planner never reads the ground-truth file and holds no answers: results always
come from executing the plan against the database through the guarded SQL tool.
"""

from __future__ import annotations

import re
from difflib import get_close_matches
from pathlib import Path

from .db import connect_readonly
from .llm import LLMResponse, ToolCall
from .metadata import _SECTOR_ALIASES, Links
from .semantics import metric_for_question, sector_threshold

EXPOSURE_INTENT = re.compile(
    r"\b(?:sector\s+(?:exposures?|breakdown|allocations?|weights?|weightings?|mix|split)"
    r"|exposures?\s+(?:by|across|per)\s+sector|(?:money|value|holdings?)\s+.*?\bsplit\s+across\s+sectors?)\b",
    re.I,
)

# Words the intents depend on. Close misspellings of these are corrected before matching.
_KEYWORDS = (
    "portfolios portfolio securities holdings sector sectors exposure exposures breakdown average passively "
    "percentage percent diversification different cost basis market value largest smallest biggest "
    "highest lowest passive active technology managed assets management aum"
).split()
_NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
_DEFAULT_TOP = 5
_MAX_TOP = 50
_OTHER_TOPICS = re.compile(
    r"\b(?:returns?|volatility|sharpe|beta|var|cvar|drawdown|nav|price|prices|cost|holdings?|positions?|"
    r"transactions?|buy|sell|fees?|coupon|bonds?|stocks?|sectors?|securit(?:y|ies)|exposures?)\b"
)
# Words that carry no filter or meaning of their own. Any other word in a simple count, list or AUM
# question means the user asked for something the planner does not understand, so it declines.
_FILLER = set(
    "what whats is s are the of a an in do does we have has our us how many there total number count all every each "
    "names name list show me which for with and to by please give display on books manage managed under at level "
    "target risk aum assets management average avg mean sum combined overall largest biggest highest greatest "
    "smallest lowest most least portfolio portfolios fund funds across per money track we much run".split()
)
# Extra words each intent legitimately uses, on top of the filler above and the database's own names.
_INTENT_WORDS = {
    "exposure": "sector sectors exposure exposures breakdown allocation allocations weights weighting mix split money "
    "calculate",
    "diversification": "diversification metric metrics ratio ratios find holding holdings that their different "
    "distinct sector sectors than more",
    "share": "value worth percentage percent share holdings holding sector sectors that it represents",
    "top": "holdings holding positions position top bottom cost basis market value quantity shares weight current",
    "price": "price prices current share securities security stocks stock sector sectors",
    "securities": (
        "securities security stocks stock companies company symbols tickers belong belongs sector sectors track we name"
    ),
    "recorded": "latest most recent newest date available on had with net asset value nav sharpe ratio volatility "
    "maximum max drawdown sortino beta cvar var tracking error information find its calculate sector exposure "
    "exposures %",
    "day_price": "was closing close opening open high low price on date",
    "transactions": "transaction transactions trades trade buy sell there made",
    "coupon": "bond bonds coupon coupons rate rates above over greater more than higher below under less lower "
    "percent %",
    "asset_value": "market value worth bond bonds stock stocks holding holdings position positions",
    "holders": "hold holds holding holdings own owns contain contains",
}
_PORTFOLIO_WORD = re.compile(r"\b(?:portfolios?|funds?)\b")
_ALL_WORD = re.compile(r"\b(?:all|every|each)\b")
_SUPERLATIVE = re.compile(r"\b(?:largest|biggest|highest|greatest|most|smallest|lowest|least)\b")
_DESCENDING = re.compile(r"\b(?:largest|biggest|highest|greatest|most|top)\b")
_RECENT = re.compile(r"\b(?:latest|most recent|newest)\b")
_HIGHEST = re.compile(r"\b(?:highest|largest|biggest|greatest)\b")
_LOWEST = re.compile(r"\b(?:lowest|smallest)\b")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_COUPON_LIMIT = re.compile(
    r"\b(above|over|greater than|more than|higher than|below|under|less than|lower than)\s+(\d+(?:\.\d+)?)\b"
)
_PERFORMANCE = ("portfolio_performance", "performance_date")
_RISK = ("risk_metrics", "calculation_date")
# Measures recorded per portfolio over time: wording, then table, date column and value column.
# A bare "VaR" is left out on purpose, because the data holds both a 95% and a 99% figure.
_RECORDED_METRICS = (
    (r"\bnav\b|\bnet assets? value\b", *_PERFORMANCE, "nav"),
    (r"\bsharpe\b", *_PERFORMANCE, "sharpe_ratio"),
    (r"\bvolatility\b", *_PERFORMANCE, "volatility"),
    (r"\bdrawdown\b", *_PERFORMANCE, "max_drawdown"),
    (r"\bsortino\b", *_RISK, "sortino_ratio"),
    (r"\bbeta\b", *_RISK, "beta"),
    (r"\bcvar\b", *_RISK, "cvar_95"),
    (r"\b99 % var\b|\bvar 99\b", *_RISK, "var_99"),
    (r"\b95 % var\b|\bvar 95\b", *_RISK, "var_95"),
    (r"\btracking error\b", *_RISK, "tracking_error"),
    (r"\binformation ratio\b", *_RISK, "information_ratio"),
)
_PRICE_COLUMNS = (
    (r"\bclos(?:e|ing) price\b", "close_price"),
    (r"\bopen(?:ing)? price\b", "open_price"),
    (r"\bhigh price\b", "high_price"),
    (r"\blow price\b", "low_price"),
)


def _literal(value: str) -> str:
    """A SQL string literal. Values only ever come from the database's own vocabulary."""
    return "'" + value.replace("'", "''") + "'"


class Vocabulary:
    """The database's own words for portfolio filters and sectors."""

    def __init__(self, db_path: Path):
        conn = connect_readonly(db_path)
        try:
            self.status = [
                r[0] for r in conn.execute("SELECT DISTINCT status FROM portfolios WHERE status IS NOT NULL")
            ]
            self.risk = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT target_risk_level FROM portfolios WHERE target_risk_level IS NOT NULL"
                )
            ]
            self.transaction_types = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT transaction_type FROM transactions WHERE transaction_type IS NOT NULL"
                )
            ]
            self.sector_group = {r[0]: r[1] for r in conn.execute("SELECT sector_name, industry_group FROM sectors")}
            names = [r[0] for r in conn.execute("SELECT portfolio_name FROM portfolios")]
            names += list(self.sector_group) + [g for g in self.sector_group.values() if g]
            names += [v for r in conn.execute("SELECT symbol, company_name FROM securities") for v in r]
        finally:
            conn.close()
        # Every word of every portfolio, sector and security name, plus the sector nicknames the linker knows.
        self.entity_words = {w for name in names for w in re.findall(r"[a-z0-9]+", name.lower())}
        self.entity_words |= {w for alias in _SECTOR_ALIASES for w in alias.split()}


class LocalPlanner:
    def __init__(self, db_path: Path):
        self.vocabulary = Vocabulary(db_path)
        self._status_re = self._words_re(self.vocabulary.status)
        risk = self._words_re(self.vocabulary.risk, capture=True)
        self._risk_before = re.compile(rf"\b{risk}\s+(?:target\s+)?risk\b") if risk else None
        self._risk_after = re.compile(rf"\brisk(?:\s+level)?\s+(?:is\s+|of\s+|=\s*)?{risk}\b") if risk else None

    @staticmethod
    def _words_re(values: list[str], capture: bool = False) -> str | re.Pattern:
        if not values:
            return ""
        alternatives = "|".join(re.escape(v.lower()) for v in sorted(values, key=len, reverse=True))
        if capture:
            return f"({alternatives})"
        return re.compile(rf"\b({alternatives})\b")

    # Public entry point -------------------------------------------------------------------

    def plan(self, question: str, links: Links) -> LLMResponse | None:
        """Tool calls for a supported intent, or None when the wording is not supported."""
        text = self._normalise(question)
        for intent in (
            self._ranked_metric_then_exposure,
            self._exposure,
            self._diversification,
            self._sector_share,
            self._top_holdings,
            self._average_price_by_sector,
            self._securities_in_sector,
            self._recorded_metric,
            self._day_price,
            self._transaction_count,
            self._bonds_by_coupon,
            self._asset_value_in_portfolio,
            self._portfolios_holding,
            self._aum,
            self._count_portfolios,
            self._list_portfolios,
        ):
            calls = intent(question, text, links)
            if calls is not None:
                return LLMResponse(calls, "local planner")
        return None

    # Helpers ------------------------------------------------------------------------------

    @staticmethod
    def _normalise(question: str) -> str:
        words = re.findall(r"[a-z0-9]+|%", question.lower())
        fixed = []
        for word in words:
            if len(word) >= 5 and word not in _KEYWORDS:
                close = get_close_matches(word, _KEYWORDS, n=1, cutoff=0.85)
                word = close[0] if close else word
            fixed.append("passive" if word == "passively" else word)
        return " ".join(fixed)

    def _unexplained(self, text: str, intent: str = "", numbers: bool = False) -> bool:
        """True when the question holds a word this intent cannot account for.

        An unknown word usually means an extra condition ("created in 2023", "in Europe"). Dropping it
        would answer a different question, so the planner declines and lets the caller say so.
        """
        known = _FILLER | self.vocabulary.entity_words | set(_INTENT_WORDS.get(intent, "").split())
        known |= {w for v in self.vocabulary.status + self.vocabulary.risk for w in v.lower().split()}
        for word in text.split():
            if word in known or (numbers and (word.isdigit() or word in _NUMBER_WORDS)):
                continue
            if len(word) >= 5 and get_close_matches(word, self.vocabulary.entity_words, n=1, cutoff=0.8):
                continue  # A misspelt name; the entity linker has already resolved it.
            return True
        return False

    def _filters(self, text: str) -> list[str]:
        conditions = []
        status = self._status_re.search(text) if self._status_re else None
        if status:
            canonical = next(v for v in self.vocabulary.status if v.lower() == status.group(1))
            conditions.append(f"status = {_literal(canonical)}")
        risk = None
        for pattern in (self._risk_before, self._risk_after):
            risk = risk or (pattern.search(text) if pattern else None)
        if risk:
            canonical = next(v for v in self.vocabulary.risk if v.lower() == risk.group(1))
            conditions.append(f"target_risk_level = {_literal(canonical)}")
        return conditions

    @staticmethod
    def _where(conditions: list[str]) -> str:
        return " WHERE " + " AND ".join(conditions) if conditions else ""

    @staticmethod
    def _call(sql: str, title: str) -> list[ToolCall]:
        return [ToolCall("run_sql", {"sql": sql, "title": title})]

    @staticmethod
    def _count(text: str) -> int | None:
        match = re.search(r"\b(?:top|first|bottom|last|best)\s+(\d+|" + "|".join(_NUMBER_WORDS) + r")\b", text)
        match = match or re.search(
            r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+(?:largest|biggest|smallest|top)\b", text
        )
        if not match:
            return None
        token = match.group(1)
        number = int(token) if token.isdigit() else _NUMBER_WORDS[token]
        return number if 1 <= number <= _MAX_TOP else None

    # Intents ------------------------------------------------------------------------------

    def _exposure(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not EXPOSURE_INTENT.search(question) and not re.search(
            r"\bsector (?:exposures?|breakdown|allocations?)\b", text
        ):
            return None
        if links.sectors or links.securities:
            return None  # A specific sector's exposure is a different question.
        if self._unexplained(text, "exposure"):
            return None
        if links.portfolios:
            return [
                ToolCall("exposure_calculator", {"portfolio_names": links.portfolios, "use_previous_sql_result": False})
            ]
        if links.candidates:
            names = ", ".join(links.candidates)
            message = f"That could mean {names}. Which portfolio do you mean?"
            return [ToolCall("decline", {"kind": "ambiguous", "message": message})]
        filters = self._filters(text)
        superlative = _SUPERLATIVE.search(text) and re.search(r"\b(?:aum|assets)\b", text)
        if superlative:
            direction = "DESC" if _DESCENDING.search(text) else "ASC"
            sql = f"SELECT portfolio_name FROM portfolios{self._where(filters)} ORDER BY total_aum {direction} LIMIT 1"
        elif filters or _ALL_WORD.search(text):
            sql = f"SELECT portfolio_name FROM portfolios{self._where(filters)} ORDER BY portfolio_id"
        else:
            return None
        return self._call(sql, "Selected portfolios") + [
            ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True})
        ]

    def _diversification(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if metric_for_question(question) is None or links.portfolios:
            return None
        if self._unexplained(text, "diversification", numbers=True):
            return None
        threshold = sector_threshold(question)
        sql = (
            "WITH portfolio_sector_count AS (SELECT p.portfolio_id, p.portfolio_name, "
            "COUNT(DISTINCT sec.sector_id) AS sector_count FROM portfolios p "
            "JOIN holdings h ON p.portfolio_id = h.portfolio_id JOIN securities s ON h.security_id = s.security_id "
            "JOIN sectors sec ON s.sector_id = sec.sector_id WHERE s.asset_type = 'Stock' "
            f"GROUP BY p.portfolio_id, p.portfolio_name HAVING COUNT(DISTINCT sec.sector_id) > {threshold}), "
            "portfolio_holdings_count AS (SELECT p.portfolio_id, COUNT(h.holding_id) AS total_holdings "
            "FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id GROUP BY p.portfolio_id) "
            "SELECT psc.portfolio_name, psc.sector_count, phc.total_holdings, "
            "ROUND(CAST(psc.sector_count AS REAL) / phc.total_holdings, 3) AS diversification_ratio "
            "FROM portfolio_sector_count psc JOIN portfolio_holdings_count phc ON psc.portfolio_id = phc.portfolio_id "
            "ORDER BY diversification_ratio DESC"
        )
        return self._call(sql, "Diversification metrics")

    def _sector_share(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if len(links.sectors) != 1 or links.portfolios or links.securities:
            return None
        if not (re.search(r"\b(?:percentage|percent|share|%)\b", text) and re.search(r"\b(?:value|worth)\b", text)):
            return None
        if self._unexplained(text, "share"):
            return None
        sector = links.sectors[0]
        group = self.vocabulary.sector_group.get(sector) or sector
        alias = re.sub(r"[^a-z0-9]+", "_", group.lower()).strip("_") or "sector"
        sql = (
            "WITH sector_value AS (SELECT p.portfolio_id, p.portfolio_name, "
            f"SUM(h.quantity * s.current_price) AS {alias}_value "
            "FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id "
            "JOIN securities s ON h.security_id = s.security_id JOIN sectors sec ON s.sector_id = sec.sector_id "
            f"WHERE sec.sector_name = {_literal(sector)} GROUP BY p.portfolio_id, p.portfolio_name), "
            "portfolio_total_value AS (SELECT p.portfolio_id, SUM(h.quantity * s.current_price) AS total_value "
            "FROM portfolios p JOIN holdings h ON p.portfolio_id = h.portfolio_id "
            "JOIN securities s ON h.security_id = s.security_id GROUP BY p.portfolio_id) "
            f"SELECT sv.portfolio_name, sv.{alias}_value, pt.total_value, "
            f"ROUND((sv.{alias}_value / pt.total_value) * 100, 2) AS {alias}_percentage "
            "FROM sector_value sv JOIN portfolio_total_value pt ON sv.portfolio_id = pt.portfolio_id "
            f"ORDER BY {alias}_percentage DESC"
        )
        return self._call(sql, f"{sector} holdings as a share of portfolio value")

    def _top_holdings(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\b(?:holdings?|positions?)\b", text) or not re.search(
            r"\b(?:top|largest|biggest|smallest|bottom|highest|lowest)\b", text
        ):
            return None
        if len(links.portfolios) != 1 or links.sectors or self._unexplained(text, "top", numbers=True):
            return None
        if re.search(r"\bcost basis\b", text):
            metric, order = "h.cost_basis", "h.cost_basis"
        elif re.search(r"\bmarket value\b|\bvalue\b", text):
            metric, order = "h.quantity * s.current_price AS market_value", "market_value"
        elif re.search(r"\b(?:quantity|shares)\b", text):
            metric, order = None, "h.quantity"
        elif re.search(r"\bweight\b", text):
            metric, order = "h.current_weight", "h.current_weight"
        else:
            return None  # "Top holdings" with no stated measure is ambiguous.
        direction = "ASC" if re.search(r"\b(?:smallest|bottom|lowest)\b", text) else "DESC"
        columns = "h.holding_id, s.symbol, s.company_name, h.quantity" + (f", {metric}" if metric else "")
        sql = (
            f"SELECT {columns} FROM holdings h JOIN securities s ON h.security_id = s.security_id "
            "JOIN portfolios p ON h.portfolio_id = p.portfolio_id "
            f"WHERE p.portfolio_name = {_literal(links.portfolios[0])} "
            f"ORDER BY {order} {direction} LIMIT {self._count(text) or _DEFAULT_TOP}"
        )
        return self._call(sql, f"Holdings of {links.portfolios[0]}")

    def _average_price_by_sector(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\b(?:average|avg|mean)\b", text) or not re.search(r"\bprices?\b", text):
            return None
        if links.sectors or links.portfolios or links.securities or self._unexplained(text, "price"):
            return None
        if not re.search(r"\b(?:each|every|per|by)\s+sector\b|\bsector by sector\b|\bacross sectors\b", text):
            return None
        sql = (
            "SELECT sec.sector_name, AVG(s.current_price) AS avg_price FROM securities s "
            "JOIN sectors sec ON s.sector_id = sec.sector_id GROUP BY sec.sector_name ORDER BY avg_price DESC"
        )
        return self._call(sql, "Average current price by sector")

    def _securities_in_sector(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if len(links.sectors) != 1 or links.portfolios or links.securities:
            return None
        if not re.search(r"\b(?:securities|stocks|companies|names|symbols|tickers)\b", text):
            return None
        if re.search(r"\b(?:price|value|average|total|count|how many|percentage|exposure|holdings?)\b", text):
            return None
        if self._unexplained(text, "securities"):
            return None
        sql = (
            "SELECT s.symbol, s.company_name FROM securities s JOIN sectors sec ON s.sector_id = sec.sector_id "
            f"WHERE sec.sector_name = {_literal(links.sectors[0])}"
        )
        return self._call(sql, f"Securities in {links.sectors[0]}")

    def _aum(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\b(?:aum|assets under management|money\b.*\bmanaged)\b", text):
            return None
        if links.portfolios or links.sectors or links.securities or _OTHER_TOPICS.search(text):
            return None
        if self._unexplained(text):
            return None
        filters = self._filters(text)
        where = self._where(filters)
        if _SUPERLATIVE.search(text) and _PORTFOLIO_WORD.search(text):
            direction = "DESC" if _DESCENDING.search(text) else "ASC"
            sql = f"SELECT portfolio_name, total_aum FROM portfolios{where} ORDER BY total_aum {direction} LIMIT 1"
            return self._call(sql, "Portfolio by AUM")
        if re.search(r"\b(?:average|avg|mean)\b", text):
            return self._call(f"SELECT AVG(total_aum) FROM portfolios{where}", "Average AUM")
        if re.search(r"\b(?:total|sum|combined|overall)\b", text) or filters:
            return self._call(f"SELECT SUM(total_aum) FROM portfolios{where}", "Total AUM")
        return None

    @staticmethod
    def _metric(text: str) -> tuple[str, str, str] | None:
        """The table, date column and value column of the single recorded measure a question names."""
        found = [metric[1:] for metric in _RECORDED_METRICS if re.search(metric[0], text)]
        return found[0] if len(found) == 1 else None

    @staticmethod
    def _rank_direction(text: str) -> str | None:
        high, low = bool(_HIGHEST.search(text)), bool(_LOWEST.search(text))
        return None if high == low else ("DESC" if high else "ASC")

    def _ranked_on_latest_date(self, text: str) -> str | None:
        """SQL naming the portfolio that ranks first on the newest date of a recorded measure."""
        metric = self._metric(text)
        direction = self._rank_direction(text)
        if metric is None or direction is None or not _RECENT.search(text) or not _PORTFOLIO_WORD.search(text):
            return None
        table, date_column, column = metric
        return (
            f"SELECT p.portfolio_name FROM {table} m JOIN portfolios p ON p.portfolio_id = m.portfolio_id "
            f"WHERE m.{date_column} = (SELECT MAX({date_column}) FROM {table}) ORDER BY m.{column} {direction} LIMIT 1"
        )

    def _ranked_metric_then_exposure(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not EXPOSURE_INTENT.search(question) or links.portfolios or links.sectors or links.securities:
            return None
        sql = self._ranked_on_latest_date(text)
        if sql is None or self._unexplained(text, "recorded", numbers=True):
            return None
        return self._call(sql, "Selected portfolio") + [
            ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True})
        ]

    def _recorded_metric(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        metric = self._metric(text)
        if metric is None or not _RECENT.search(text) or links.sectors or links.securities:
            return None
        if self._unexplained(text, "recorded", numbers=True):
            return None
        table, date_column, column = metric
        if len(links.portfolios) == 1:
            sql = (
                f"SELECT m.{column} FROM {table} m JOIN portfolios p ON p.portfolio_id = m.portfolio_id "
                f"WHERE p.portfolio_name = {_literal(links.portfolios[0])} ORDER BY m.{date_column} DESC LIMIT 1"
            )
            return self._call(sql, f"Latest {column} of {links.portfolios[0]}")
        if links.portfolios or links.candidates:
            return None
        ranked = self._ranked_on_latest_date(text)
        if ranked:
            return self._call(ranked, f"Portfolio ranked by latest {column}")
        if not (_ALL_WORD.search(text) and _PORTFOLIO_WORD.search(text)):
            return None
        sql = (
            f"SELECT p.portfolio_name, m.{column} FROM {table} m JOIN portfolios p ON p.portfolio_id = m.portfolio_id "
            f"WHERE m.{date_column} = (SELECT MAX(x.{date_column}) FROM {table} x "
            "WHERE x.portfolio_id = m.portfolio_id) "
            "ORDER BY p.portfolio_name"
        )
        return self._call(sql, f"Latest {column} by portfolio")

    def _day_price(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        day = _ISO_DATE.search(question)
        column = next((c for pattern, c in _PRICE_COLUMNS if re.search(pattern, text)), None)
        if day is None or column is None or len(links.securities) != 1 or links.portfolios or links.sectors:
            return None
        if self._unexplained(text, "day_price", numbers=True):
            return None
        symbol = links.securities[0].split()[0]
        sql = (
            f"SELECT hp.{column} FROM historical_prices hp JOIN securities s ON s.security_id = hp.security_id "
            f"WHERE s.symbol = {_literal(symbol)} AND hp.price_date = {_literal(day.group(1))}"
        )
        return self._call(sql, f"{symbol} {column} on the requested date")

    def _transaction_count(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\b(?:transactions?|trades?)\b", text):
            return None
        if not re.search(r"\b(?:how many|number of|count)\b", text):
            return None
        if links.portfolios or links.sectors or links.securities or self._unexplained(text, "transactions"):
            return None
        kinds = [v for v in self.vocabulary.transaction_types if re.search(rf"\b{re.escape(v.lower())}\b", text)]
        if len(kinds) > 1:
            return None
        where = f" WHERE transaction_type = {_literal(kinds[0])}" if kinds else ""
        return self._call(f"SELECT COUNT(*) FROM transactions{where}", "Number of transactions")

    def _bonds_by_coupon(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\bbonds?\b", text) or not re.search(r"\bcoupons?\b", text):
            return None
        limit = _COUPON_LIMIT.search(" ".join(question.lower().split()))
        if limit is None or links.portfolios or links.sectors or links.securities:
            return None
        if self._unexplained(text, "coupon", numbers=True):
            return None
        operator = "<" if limit.group(1) in {"below", "under", "less than", "lower than"} else ">"
        sql = (
            "SELECT symbol, coupon_rate FROM securities "
            f"WHERE asset_type = 'Bond' AND coupon_rate {operator} {float(limit.group(2)):g}"
        )
        return self._call(sql, "Bonds by coupon rate")

    def _asset_value_in_portfolio(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        asset = re.search(r"\b(bond|stock)s? (?:holdings?|positions?)\b", text)
        if asset is None or not re.search(r"\bmarket value\b", text):
            return None
        if not re.search(r"\b(?:total|sum|combined)\b", text):
            return None
        if len(links.portfolios) != 1 or links.sectors or links.securities or self._unexplained(text, "asset_value"):
            return None
        sql = (
            "SELECT SUM(h.quantity * s.current_price) FROM holdings h "
            "JOIN securities s ON s.security_id = h.security_id "
            "JOIN portfolios p ON p.portfolio_id = h.portfolio_id "
            f"WHERE p.portfolio_name = {_literal(links.portfolios[0])} "
            f"AND s.asset_type = {_literal(asset.group(1).capitalize())}"
        )
        return self._call(sql, f"Market value of {asset.group(1)} holdings in {links.portfolios[0]}")

    def _portfolios_holding(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if len(links.securities) != 1 or links.portfolios or links.sectors or not _PORTFOLIO_WORD.search(text):
            return None
        if not re.search(r"\b(?:hold|holds|holding|holdings|own|owns|contain|contains)\b", text):
            return None
        if not re.search(r"\b(?:which|what|list|show|name|names|display)\b", text):
            return None
        if re.search(r"\b(?:how many|count)\b", text) or self._unexplained(text, "holders"):
            return None
        symbol = links.securities[0].split()[0]
        sql = (
            "SELECT p.portfolio_name FROM holdings h JOIN portfolios p ON p.portfolio_id = h.portfolio_id "
            f"JOIN securities s ON s.security_id = h.security_id WHERE s.symbol = {_literal(symbol)}"
        )
        return self._call(sql, f"Portfolios holding {symbol}")

    def _count_portfolios(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not re.search(r"\b(?:how many|number of|count)\b", text) or not _PORTFOLIO_WORD.search(text):
            return None
        if links.portfolios or links.sectors or links.securities or _OTHER_TOPICS.search(text):
            return None
        if self._unexplained(text):
            return None
        return self._call(f"SELECT COUNT(*) FROM portfolios{self._where(self._filters(text))}", "Number of portfolios")

    def _list_portfolios(self, question: str, text: str, links: Links) -> list[ToolCall] | None:
        if not _PORTFOLIO_WORD.search(text) or not re.search(r"\b(?:names?|list|which|what|show|display)\b", text):
            return None
        if links.portfolios or links.sectors or links.securities or _OTHER_TOPICS.search(text):
            return None
        if self._unexplained(text) or re.search(r"\b(?:aum|assets|how many|number)\b", text):
            return None
        if _SUPERLATIVE.search(text):
            return None
        filters = self._filters(text)
        if not filters and not _ALL_WORD.search(text):
            return None
        return self._call(f"SELECT portfolio_name FROM portfolios{self._where(filters)}", "Portfolio names")
