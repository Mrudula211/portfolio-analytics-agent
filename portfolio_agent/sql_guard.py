"""Static validation of model-generated SQL (layer before the engine-enforced controls in db.py).

* structural policy: exactly one statement, read-only root, no DML/DDL/PRAGMA/ATTACH anywhere,
  tables restricted to the allow-list (CTE names permitted)
* literal grounding: string literals compared to categorical columns must exist in the data,
  catching silent-empty bugs such as  target_risk_level = 'high'  (stored as 'High').
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .db import TABLES

FORBIDDEN = tuple(
    getattr(exp, n) for n in ("Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command",
                              "Pragma", "Attach", "Detach", "Merge", "TruncateTable", "Transaction",
                              "Commit", "Rollback", "Set", "Use", "Into")
    if hasattr(exp, n)
)


class GuardViolation(Exception):
    """Policy violation (write attempt, forbidden table...). Treated as a security event: no retry."""


class GuardFixable(Exception):
    """Problem the model can plausibly fix (parse error, ungrounded literal). Fed back for repair."""


@dataclass
class GuardReport:
    tables: set[str]
    literal_checks: int


def validate_sql(sql: str, domains: dict[str, set[str]] | None = None) -> GuardReport:
    if not sql or not sql.strip():
        raise GuardFixable("empty SQL")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        raise GuardFixable(f"SQL parse error: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise GuardViolation(f"exactly one statement allowed, got {len(statements)}")
    root = statements[0]
    if not isinstance(root, (exp.Select, exp.SetOperation)):
        raise GuardViolation(f"only SELECT queries are allowed (got {type(root).__name__.upper()})")
    bad = next(iter(root.find_all(*FORBIDDEN)), None) if FORBIDDEN else None
    if bad is not None:
        raise GuardViolation(f"forbidden construct: {type(bad).__name__.upper()}")

    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    tables = set()
    for t in root.find_all(exp.Table):
        name = t.name.lower()
        if t.args.get("db") or t.args.get("catalog"):
            raise GuardViolation(f"schema-qualified table not allowed: {t.sql()}")
        if name in cte_names:
            continue
        if name not in TABLES:
            if name.startswith("sqlite_"):
                raise GuardViolation(f"system table access denied: {name}")
            raise GuardFixable(f"unknown table '{name}'. Valid tables: {', '.join(TABLES)}")
        tables.add(name)

    checks = _check_literals(root, domains) if domains else 0
    return GuardReport(tables, checks)


def _check_literals(root: exp.Expression, domains: dict[str, set[str]]) -> int:
    checks = 0
    pairs: list[tuple[exp.Column, exp.Literal]] = []
    for node in root.find_all(exp.EQ, exp.NEQ):
        left, right = node.left, node.right
        if isinstance(left, exp.Literal) and isinstance(right, exp.Column):
            left, right = right, left
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
            pairs.append((left, right))
    for node in root.find_all(exp.In):
        if isinstance(node.this, exp.Column):
            pairs += [(node.this, v) for v in node.expressions if isinstance(v, exp.Literal) and v.is_string]

    for col, lit in pairs:
        domain = domains.get(col.name.lower())
        if not domain:
            continue
        checks += 1
        value = lit.this
        if value in domain:
            continue
        near = [d for d in domain if d.lower() == value.lower()]
        hint = f"did you mean '{near[0]}'?" if near else f"valid values: {', '.join(sorted(domain)[:15])}"
        raise GuardFixable(f"value '{value}' does not exist in column {col.name}; {hint} (values are case-sensitive)")
    return checks
