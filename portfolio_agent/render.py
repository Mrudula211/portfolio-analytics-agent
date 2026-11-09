"""Turn tool results into text with plain code.

No model sees or restates the results, so a figure in an answer is always the figure the
database returned. That removes hallucinated numbers and a second model round trip.
"""

from __future__ import annotations

import re

from .semantics import superlative_interpretation
from .sql_guard import QueryResult
from .tools import ExposureResult

_PERCENT = re.compile(r"pct|percent|percentage|exposure", re.I)
_RAW_ID = re.compile(r"(^|_)id$", re.I)
_MAX_TEXT_ROWS = 20
_MAX_LIST_ITEMS = 30


def format_value(value, column: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value) if _RAW_ID.search(column) else f"{value:,}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            text = f"{int(value):,}"
        elif abs(value) < 1:
            text = f"{value:.4f}".rstrip("0").rstrip(".")
        else:
            text = f"{value:,.2f}"
        return f"{text}%" if _PERCENT.search(column) else text
    return str(value)


def _table(columns: list[str], rows: list[list]) -> str:
    cells = [[format_value(v, c) for v, c in zip(row, columns, strict=False)] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]

    def line(parts):
        return "  ".join(p.ljust(w) for p, w in zip(parts, widths, strict=False)).rstrip()

    return "\n".join([line(columns), line(["-" * w for w in widths]), *(line(r) for r in cells)])


def safe_title(title: str, question: str) -> str:
    """Drop a model-written label that contains a figure the user did not state."""
    title = " ".join((title or "").split())[:120]
    if set(re.findall(r"\d+(?:\.\d+)?", title)) - set(re.findall(r"\d+(?:\.\d+)?", question)):
        return ""
    return title


def render_sql(result: QueryResult, title: str, question: str) -> str:
    label = safe_title(title, question)
    interpretation = superlative_interpretation(question)
    header = f"{interpretation}\n" if interpretation else ""
    prefix = header + (f"{label}\n" if label else "")
    if not result.rows:
        return f"{prefix}No matching records were found."
    if len(result.rows) == 1 and len(result.columns) == 1:
        value = format_value(result.rows[0][0], result.columns[0])
        return f"{prefix}{label + ': ' if label else ''}{value}"
    if len(result.columns) == 1:
        items = [format_value(row[0], result.columns[0]) for row in result.rows]
        shown = ", ".join(items[:_MAX_LIST_ITEMS])
        rest = len(items) - _MAX_LIST_ITEMS
        more = f", and {rest} more" if rest > 0 else ""
        return f"{prefix}{len(items)} result{'s' if len(items) != 1 else ''}: {shown}{more}"
    body = _table(result.columns, result.rows[:_MAX_TEXT_ROWS])
    rest = len(result.rows) - _MAX_TEXT_ROWS
    if rest > 0:
        body += f"\n... and {rest} more rows"
    if result.truncated:
        body += "\nResults were cut off at the row limit."
    return f"{prefix}{body}"


def render_exposure(result: ExposureResult) -> str:
    heading = f"Sector exposure: {result.portfolio_name}"
    if not result.exposures:
        return f"{heading}\nNo equity holdings, so there is no sector exposure."
    columns = ["sector", "exposure_pct", "portfolio_weight_pct", "market_value_pct", "holdings"]
    rows = [
        [e.sector, e.exposure_pct, e.portfolio_weight_pct, e.market_value_pct, e.holdings] for e in result.exposures
    ]
    return f"{heading}\n{_table(columns, rows)}"
