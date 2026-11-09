"""Web UI. Run with: streamlit run streamlit_app.py

The agent is created once per server process and shared by every browser session. Answers are
rendered from the agent's structured response: tables, charts and SQL, never model-written prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.db import data_quality_findings
from portfolio_agent.demo import dataset_summary, load_report, preload_demos
from portfolio_agent.ratelimit import RateLimiter, proxy_client
from portfolio_agent.render import format_value, safe_title

st.set_page_config(page_title="Portfolio Analytics", layout="wide")
# Streamlit centres button text; the sidebar examples read better as a left-aligned list.
st.html(
    "<style>[data-testid='stSidebar'] [data-testid='stBaseButton-tertiary']"
    "{justify-content:flex-start;text-align:left} [data-testid='stSidebar'] [data-testid='stBaseButton-tertiary'] p"
    "{text-align:left}</style>"
)

ROUTES = {
    "cache": "Cached",
    "direct_calculator": "Calculator, no model call",
    "gemini": "Gemini plan + SQL",
    "local_deterministic": "Local planner, no model call",
    "local_fallback": "Local planner (Gemini unavailable)",
    "clarification": "Needs more detail",
    "validation": "Not run",
    "error": "Not answered",
}
# What the sidebar says about Gemini. A client existing proves nothing; only a real request does.
GEMINI_STATES = {
    "not_configured": ":red[●] Gemini not configured. The local planner answers what it supports.",
    "configured": ":orange[●] Gemini configured, not used yet",
    "ok": ":green[●] Gemini responding (the last request succeeded)",
    "unavailable": ":orange[●] Gemini temporarily unavailable. Using the local planner.",
    "quota_exhausted": ":orange[●] Gemini quota exhausted. Using the local planner.",
}
BAR_COLOUR = "#2a2ad0"  # Royal blue that passes contrast checks on white.


@st.cache_resource
def load_agent() -> tuple[PortfolioAgent, list[str], RateLimiter]:
    agent = PortfolioAgent()
    return agent, preload_demos(agent), RateLimiter(agent.settings.rate_limit_per_minute)


@st.cache_data
def load_facts(db_path: str) -> tuple[dict, list[str]]:
    return dataset_summary(Path(db_path)), data_quality_findings(Path(db_path))


def escape(text: str) -> str:
    """Show user and database text literally, never as Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$])", r"\\\1", str(text))


def show_table(columns: list[str], rows: list[list]) -> None:
    labels, seen = [], set()
    for column in columns:  # Model-written SQL can repeat a column name; tables need unique ones.
        label = column.replace("_", " ")
        while label in seen:
            label += " "
        seen.add(label)
        labels.append(label)
    frame = pd.DataFrame(rows, columns=labels)
    config = {
        label: st.column_config.NumberColumn(label, format="plain" if re.search(r"(^|_)id$", column) else "localized")
        for label, column in zip(labels, columns, strict=True)
        if pd.api.types.is_numeric_dtype(frame[label])
    }
    st.dataframe(frame, hide_index=True, width="stretch", column_config=config)


def show_exposure(data: dict) -> None:
    st.markdown(f"**{escape(data['portfolio_name'])}**: sector exposure of equity holdings")
    if not data["exposures"]:
        st.info("No equity holdings, so there is no sector exposure.")
        return
    frame = pd.DataFrame(data["exposures"])
    bars = alt.Chart(frame).encode(
        x=alt.X("exposure_pct:Q", title="% of equity holdings", scale=alt.Scale(domain=[0, 100])),
        y=alt.Y("sector:N", sort="-x", title=None),
        tooltip=[
            alt.Tooltip("sector:N", title="Sector"),
            alt.Tooltip("exposure_pct:Q", title="% of equities", format=".2f"),
            alt.Tooltip("portfolio_weight_pct:Q", title="% of portfolio", format=".2f"),
            alt.Tooltip("market_value_pct:Q", title="% by market value", format=".2f"),
            alt.Tooltip("holdings:Q", title="Holdings"),
        ],
    )
    labels = bars.mark_text(align="left", dx=4, color="#4b4f66").encode(text=alt.Text("exposure_pct:Q", format=".1f"))
    chart = bars.mark_bar(color=BAR_COLOUR, cornerRadiusEnd=3, height=14) + labels
    st.altair_chart(chart, width="stretch", height=34 * len(frame) + 60)
    with st.expander("Table with portfolio weight and market value"):
        columns = ["sector", "exposure_pct", "portfolio_weight_pct", "market_value_pct", "holdings"]
        show_table(columns, frame[columns].values.tolist())


def show_sql_step(step: dict, question: str) -> None:
    title = safe_title(step["input"].get("title", ""), question)
    columns, rows = step["columns"] or [], step["rows"] or []
    if len(rows) == 1 and len(columns) == 1:
        st.metric(title or columns[0].replace("_", " "), format_value(rows[0][0], columns[0]))
    else:
        if title:
            st.markdown(f"**{escape(title)}**")
        if rows:
            show_table(columns, rows)
            if step.get("truncated"):
                st.caption("Results were cut off at the row limit.")
        else:
            st.info("No matching records were found.")
    with st.expander("SQL"):
        st.code(step["input"]["sql"], language="sql")


def route_label(reply: dict) -> str:
    """Where the answer came from, stated precisely."""
    llm = reply.get("llm") or {}
    if reply["route"] == "cache" and llm.get("prepared_example"):
        return "Cached prepared example: a stored Gemini plan, run against the database"
    label = ROUTES.get(reply["route"], reply["route"])
    if reply["route"] == "local_fallback" and llm.get("fallback_reason"):
        label += f" - {llm['fallback_reason'].replace('_', ' ')}"
    return label


def show_reply(reply: dict) -> None:
    total = reply["timings_ms"].get("total")
    timing = "" if total is None else (f"{total:.1f} ms" if total < 1000 else f"{total / 1000:.2f} s")
    st.markdown(f"#### {escape(reply['question'])}")
    st.caption(" · ".join(part for part in (route_label(reply), timing) if part))
    if reply["status"] in {"declined", "clarify"}:
        st.info(reply["answer"])
        return
    if reply["status"] != "ok":
        st.error(reply["answer"])
        return
    if reply["warnings"]:
        st.warning("\n".join(f"- {escape(w)}" for w in reply["warnings"]))
    for step in reply["steps"]:
        if step["exposure"]:
            show_exposure(step["exposure"])
        else:
            show_sql_step(step, reply["question"])


def show_evaluation(report: dict | None) -> None:
    if not report:
        st.info("No evaluation report is bundled with this deployment.")
        return
    summary, meta = report["summary"], report["meta"]
    routes = summary["by_route"]  # Reports written before the route rename call it "model".
    model = routes.get("gemini") or routes.get("model", {})
    figures = [
        ("Strict accuracy", f"{summary['strict_accuracy']:.1%}", f"{summary['cases_scored']} questions scored"),
        ("Lenient accuracy", f"{summary['lenient_accuracy']:.1%}", "counting partial answers"),
        ("Correct tool", f"{summary['tool_selection_accuracy']:.1%}", "tool choice"),
        ("Median latency", f"{model.get('p50_ms', 0) / 1000:.2f} s", "with a Gemini call"),
        ("95th percentile", f"{model.get('p95_ms', 0) / 1000:.2f} s", "with a Gemini call"),
    ]
    for column, (label, value, note) in zip(st.columns(len(figures)), figures, strict=True):
        column.metric(label, value, border=True)
        column.caption(note)
    commit = meta.get("commit", "")[:7]
    st.caption(
        f"Live run {meta['date']}" + (f" on commit {commit}" if commit else "") + ", Gemini free tier, cache off."
    )

    st.markdown("**By category**")
    rows = [[k.replace("_", " "), v["passed"], v["partial"], v["total"]] for k, v in summary["by_category"].items()]
    show_table(["category", "passed", "partial", "questions"], rows)

    st.markdown("**Every question**")
    results = [[r["id"], r["question"], r["verdict"], r["route"], round(r["latency_ms"])] for r in report["results"]]
    show_table(["question_id", "question", "verdict", "route", "latency_ms"], results)

    st.markdown("**How it works**")
    st.markdown(
        "- Repeat questions come from an exact-match cache. Sector exposure for one named fund runs the calculator "
        "without the model.\n"
        "- Other questions cost one Gemini call that returns the whole plan. If a model is slow, the next one starts "
        "after 2.5 s.\n"
        "- Code formats every answer from query results, so the model never states a figure. Answers are graded "
        "against reference results, not SQL text."
    )


def queue(question: str) -> None:
    st.session_state.question_box = question
    st.session_state.pending = question


agent, examples, limiter = load_agent()
facts, notes = load_facts(str(agent.settings.db_path))

with st.sidebar:
    st.markdown(GEMINI_STATES[agent.gemini_status["state"]])
    st.markdown("**Examples**")
    for index, example in enumerate(examples):
        st.button(example, key=f"example_{index}", on_click=queue, args=(example,), type="tertiary")
    st.markdown("**Dataset**")
    st.markdown(
        f"- {facts['portfolios']} portfolios\n- {facts['securities']} securities\n"
        f"- {facts['holdings']} holdings\n- Prices up to {facts['as_of']}"
    )
    with st.expander("Data notes"):
        st.markdown("\n".join(f"- {escape(note)}" for note in notes))

st.markdown("### Portfolio Analytics")
query_tab, evaluation_tab = st.tabs(["Query", "Evaluation"])

with query_tab:
    if not agent.llm:
        st.warning(
            "Gemini is not configured. The local planner supports portfolio counts and lists, AUM, security and "
            "sector summaries, holdings rankings, diversification, sector value shares and sector exposure. "
            "Other questions may need Gemini or be declined. Local answers do not use Gemini quota."
        )
    with st.form("ask", border=False):
        left, right = st.columns([8, 1], vertical_alignment="bottom")
        typed = left.text_input(
            "Question",
            key="question_box",
            max_chars=agent.settings.max_question_chars,
            placeholder="Ask about holdings, risk, performance or sector exposure",
            label_visibility="collapsed",
        )
        submitted = right.form_submit_button("Run", type="primary", width="stretch")
    question = st.session_state.pop("pending", None) or (typed.strip() if submitted else "")
    if question:
        client = proxy_client(st.context.headers.get("X-Forwarded-For"), st.context.ip_address)
        if limiter.allow(client):
            with st.spinner("Running..."):
                st.session_state.reply = agent.answer_question(question).to_dict()
        else:
            st.error("Too many questions. Please wait a minute.")
    if "reply" in st.session_state:
        show_reply(st.session_state.reply)
    else:
        st.caption("Pick an example in the sidebar or type a question. The SQL behind every answer is shown.")

with evaluation_tab:
    show_evaluation(load_report())

st.caption("Sample dataset. Not investment advice. An independent assessment project, not a PL Capital product.")
