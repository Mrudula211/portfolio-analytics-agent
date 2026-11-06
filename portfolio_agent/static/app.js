"use strict";

// All data reaches the page through textContent, so database values can never run as HTML.
const el = (id) => document.getElementById(id);

const ROUTE_LABELS = {
  cache: "Cached",
  fast_path: "Direct calculation, no model",
  model: "Gemini plan + database",
  validation: "Not sent",
};

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatCell(value, column) {
  if (value === null || value === undefined) return "-";
  if (typeof value !== "number") return String(value);
  if (/(^|_)id$/i.test(column)) return String(value);
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 1 ? 4 : 2;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

const formatMs = (ms) => (ms < 10 ? `${ms.toFixed(1)} ms` : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`);

function renderTable(columns, rows, caption) {
  const wrap = make("div", "table-wrap");
  const table = make("table");
  if (caption) table.append(make("caption", "", caption));
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || typeof r[i] === "number"));
  const head = make("tr");
  columns.forEach((column, i) => head.append(make("th", numeric[i] ? "num" : "", column.replaceAll("_", " "))));
  const thead = make("thead");
  thead.append(head);
  const tbody = make("tbody");
  rows.forEach((row) => {
    const tr = make("tr");
    row.forEach((value, i) => tr.append(make("td", numeric[i] ? "num" : "", formatCell(value, columns[i]))));
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  return wrap;
}

function showTooltip(event, exposure) {
  const tip = el("tooltip");
  tip.replaceChildren(
    make("strong", "", exposure.sector),
    make("div", "", `Exposure ${exposure.exposure_pct.toFixed(2)}% of equities`),
    make("div", "", `Weight ${exposure.portfolio_weight_pct.toFixed(2)}% of portfolio`),
    make("div", "", `By market value ${exposure.market_value_pct.toFixed(2)}%`),
    make("div", "", `${exposure.holdings} holding${exposure.holdings === 1 ? "" : "s"}`),
  );
  tip.hidden = false;
  tip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 240)}px`;
  tip.style.top = `${event.clientY + 14}px`;
}

function renderExposure(data) {
  const block = make("div", "block");
  block.append(make("h3", "", `${data.portfolio_name}: share of equity holdings by sector`));
  if (data.exposures.length === 0) {
    block.append(make("p", "", "No equity holdings, so there is no sector exposure."));
    return block;
  }
  const bars = make("div", "bars");
  const largest = Math.max(...data.exposures.map((e) => e.exposure_pct));
  data.exposures.forEach((exposure) => {
    const hit = make("div", "bar-hit");
    const bar = make("div", "bar");
    bar.style.width = `${(exposure.exposure_pct / largest) * 100}%`;
    hit.append(bar);
    hit.addEventListener("mousemove", (event) => showTooltip(event, exposure));
    hit.addEventListener("mouseleave", () => { el("tooltip").hidden = true; });
    bars.append(make("div", "bar-label", exposure.sector), hit, make("div", "bar-value", `${exposure.exposure_pct.toFixed(1)}%`));
  });
  block.append(bars);
  const details = make("details");
  details.append(make("summary", "", "Table, including whole-portfolio weight and market value"));
  details.append(renderTable(
    ["sector", "exposure_pct", "portfolio_weight_pct", "market_value_pct", "holdings"],
    data.exposures.map((e) => [e.sector, e.exposure_pct, e.portfolio_weight_pct, e.market_value_pct, e.holdings]),
  ));
  block.append(details);
  return block;
}

function renderSqlStep(step) {
  const block = make("div", "block");
  if (step.input.title) block.append(make("h3", "", step.input.title));
  if (step.rows && step.rows.length > 0) {
    block.append(renderTable(step.columns, step.rows, step.truncated ? "Results were cut off at the row limit." : ""));
  }
  if (step.input.sql) {
    const details = make("details");
    details.append(make("summary", "", "SQL"));
    details.append(make("pre", "", step.input.sql));
    block.append(details);
  }
  return block;
}

function headline(reply) {
  if (reply.status !== "ok") return reply.answer;
  const onlySql = reply.steps.every((s) => s.tool === "run_sql");
  const sql = reply.steps[0];
  if (onlySql && sql && sql.rows && (sql.rows.length === 0 || (sql.rows.length === 1 && sql.columns.length === 1))) {
    return reply.answer;
  }
  return "";
}

function setHead(route, latency, breakdown) {
  el("route").textContent = route ? ROUTE_LABELS[route] || route : "";
  el("route").dataset.route = route || "";
  el("latency").textContent = latency;
  el("breakdown").textContent = breakdown;
}

function render(reply) {
  const t = reply.timings_ms;
  const parts = [];
  if (t.llm) parts.push(`model ${formatMs(t.llm)}`);
  if (t.tools) parts.push(`database ${formatMs(t.tools)}`);
  setHead(reply.route, t.total === undefined ? "" : formatMs(t.total), parts.join(" + "));
  el("message").className = "message";
  el("message").textContent = headline(reply);
  el("warnings").replaceChildren(...reply.warnings.map((w) => make("li", "", w)));
  el("content").replaceChildren(...(reply.status === "ok" ? reply.steps : []).map(
    (step) => (step.exposure ? renderExposure(step.exposure) : renderSqlStep(step)),
  ));
}

function renderProblem(message) {
  setHead("", "", "");
  el("message").className = "message";
  el("message").textContent = message;
  el("warnings").replaceChildren();
  el("content").replaceChildren();
}

async function ask(question) {
  const button = el("ask-button");
  button.disabled = true;
  el("result").hidden = false;
  renderProblem("");
  el("message").className = "message pending";
  const started = performance.now();
  const timer = setInterval(() => {
    el("message").textContent = `Working... ${((performance.now() - started) / 1000).toFixed(1)} s`;
  }, 100);
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    clearInterval(timer);
    if (response.status === 429) return renderProblem("Too many questions. Please wait a minute.");
    if (!response.ok) return renderProblem("That question could not be processed. Please try rewording it.");
    render(await response.json());
  } catch {
    clearInterval(timer);
    renderProblem("Could not reach the server. Please check your connection and try again.");
  } finally {
    button.disabled = false;
  }
}

function renderAbout(about) {
  el("data-notes").replaceChildren(...about.data_notes.map((note) => make("li", "", note)));
  const report = about.evaluation;
  if (report) {
    const s = report.summary;
    const model = s.by_route.model || {};
    const tiles = [
      [`${(s.strict_accuracy * 100).toFixed(1)}%`, `strict accuracy on ${s.cases_scored} questions`],
      [`${(s.tool_selection_accuracy * 100).toFixed(0)}%`, "right tool chosen"],
      [model.p50_ms ? formatMs(model.p50_ms) : "-", "median answer using the model"],
      [model.p95_ms ? formatMs(model.p95_ms) : "-", "95th percentile using the model"],
    ];
    el("tiles").replaceChildren(...tiles.map(([value, label], index) => {
      const tile = make("div", "tile");
      if (index === 0) tile.append(make("span", "tile-tag", "Live run"));
      tile.append(make("div", "tile-value", value), make("div", "tile-label", label));
      return tile;
    }));
    const rows = Object.entries(s.by_category).map(([name, c]) => [name.replaceAll("_", " "), c.passed, c.partial, c.total]);
    const table = make("div", "card");
    table.id = "eval-table";
    table.append(renderTable(["category", "passed", "partial", "questions"], rows));
    el("eval-table").replaceWith(table);
    el("eval-meta").textContent = `Live run of ${report.meta.dataset} questions, ${report.meta.date}. `
      + "Answers are compared with reference results, not SQL text; exposures are checked against an independent calculation.";
  }
  el("about").hidden = false;
}

el("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const question = el("question").value.trim();
  if (question) ask(question);
});

fetch("/api/about").then((r) => r.json()).then((about) => {
  about.examples.forEach((question) => {
    const chip = make("button", "", question);
    chip.type = "button";
    chip.title = question;
    chip.addEventListener("click", () => {
      el("question").value = question;
      ask(question);
    });
    el("examples").append(chip);
  });
  if (!about.model_configured) {
    el("model-note").textContent = "No Gemini API key is configured here, so only direct sector exposure questions can be answered.";
    el("model-note").hidden = false;
  }
  renderAbout(about);
});
