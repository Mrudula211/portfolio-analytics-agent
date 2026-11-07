"""What the web app shows besides answers: stored demo plans, dataset facts and the evaluation report."""

from __future__ import annotations

import json
from pathlib import Path

from .agent import PortfolioAgent
from .config import ROOT
from .db import connect_readonly
from .llm import ToolCall

DEMO_PLANS = Path(__file__).parent / "demo_plans.json"
EVALUATION = ROOT / "reports" / "live_extended.json"


def preload_demos(agent: PortfolioAgent) -> list[str]:
    """Answer each demo question from Gemini's stored plan, so examples cost no model call.

    The plan, not the answer, is stored: it runs against the current data. Returns the questions.
    """
    demos = json.loads(DEMO_PLANS.read_text(encoding="utf-8"))
    for demo in demos:
        agent.preload(demo["question"], [ToolCall(**c) for c in demo["calls"]])
    return [demo["question"] for demo in demos]


def dataset_summary(db_path: Path) -> dict:
    conn = connect_readonly(db_path)
    try:
        tables = ("portfolios", "securities", "holdings")
        summary = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        summary["as_of"] = conn.execute("SELECT MAX(price_date) FROM historical_prices").fetchone()[0]
        return summary
    finally:
        conn.close()


def load_report(path: Path = EVALUATION) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
