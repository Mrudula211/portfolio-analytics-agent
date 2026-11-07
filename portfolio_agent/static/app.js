"use strict";

// All data reaches the page through textContent, so database values can never run as HTML.
const el = (id) => document.getElementById(id);

const ROUTE_LABELS = { cache: "Cached", fast_path: "Calculator", model: "Gemini + SQL", validation: "Not run" };

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
  const head = table.createTHead().insertRow();
  columns.forEach((column, i) => head.append(make("th", numeric[i] ? "num" : "", column.replaceAll("_", " "))));
  const body = table.createTBody();
  rows.forEach((row) => {
    const tr = body.insertRow();
    row.forEach((value, i) => tr.append(make("td", numeric[i] ? "num" : "", formatCell(value, columns[i]))));
  });
  wrap.append(table);
  return wrap;
}

function showTooltip(event, exposure) {
  const tip = el("tooltip");
  tip.replaceChildren(
    make("strong", "", exposure.sector),
    make("div", "", `${exposure.exposure_pct.toFixed(2)}% of equities`),
    make("div", "", `${exposure.portfolio_weight_pct.toFixed(2)}% of portfolio`),
    make("div", "", `${exposure.market_value_pct.toFixed(2)}% by market value`),
    make("div", "", `${exposure.holdings} holding${exposure.holdings === 1 ? "" : "s"}`),
  );
  tip.hidden = false;
  tip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 220)}px`;
  tip.style.top = `${event.clientY + 14}px`;
}

function renderExposure(data) {
  const block = make("div", "block");
  block.append(make("h3", "", `${data.portfolio_name}: sector exposure of equity holdings`));
  if (data.exposures.length === 0) {
    block.append(make("p", "message", "No equity holdings, so there is no sector exposure."));
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
  details.append(make("summary", "", "Table with portfolio weight and market value"));
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
    block.append(renderTable(step.columns, step.rows, step.truncated ? "Cut off at the row limit." : ""));
  }
  if (step.input.sql) {
    const details = make("details");
    details.append(make("summary", "", "SQL"));
    details.append(make("pre", "", step.input.sql));
    block.append(details);
  }
  return block;
}

// A single value, an empty result or a refusal reads best as one line; tables speak for themselves.
function headline(reply) {
  if (reply.status !== "ok") return [reply.answer, ""];
  const first = reply.steps[0];
  const onlySql = reply.steps.every((s) => s.tool === "run_sql");
  if (onlySql && first && first.rows) {
    if (first.rows.length === 1 && first.columns.length === 1) return [formatCell(first.rows[0][0], first.columns[0]), "value"];
    if (first.rows.length === 0) return [reply.answer, ""];
  }
  return ["", ""];
}

function setMeta(route, latency) {
  el("route").textContent = route ? ROUTE_LABELS[route] || route : "";
  el("latency").textContent = latency;
}

function showMessage(text, className = "") {
  el("message").className = `message ${className}`.trim();
  el("message").textContent = text;
}

function render(reply) {
  const t = reply.timings_ms;
  setMeta(reply.route, t.total === undefined ? "" : formatMs(t.total));
  const [text, className] = headline(reply);
  showMessage(text, className);
  el("warnings").replaceChildren(...reply.warnings.map((w) => make("li", "", w)));
  el("content").replaceChildren(...(reply.status === "ok" ? reply.steps : []).map(
    (step) => (step.exposure ? renderExposure(step.exposure) : renderSqlStep(step)),
  ));
}

function renderProblem(message) {
  setMeta("", "");
  showMessage(message);
  el("warnings").replaceChildren();
  el("content").replaceChildren();
}

// Only the latest question may update the page, so a slow earlier reply cannot overwrite a newer one.
let latest = 0;
let timer;

async function ask(question) {
  const id = ++latest;
  clearInterval(timer);
  showView("query");
  el("result-question").textContent = question;
  document.querySelectorAll("#examples button").forEach((b) => b.classList.toggle("active", b.textContent === question));
  renderProblem("");
  const started = performance.now();
  timer = setInterval(() => {
    el("latency").textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`;
    showMessage("Running...");
  }, 100);
  let reply = null;
  let problem = "Could not reach the server. Check your connection and try again.";
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (response.ok) reply = await response.json();
    else if (response.status === 429) problem = "Too many questions. Please wait a minute.";
    else problem = "That question could not be processed. Try rewording it.";
  } catch {
    // Network failure: keep the default message.
  }
  if (id !== latest) return;
  clearInterval(timer);
  if (reply) render(reply);
  else renderProblem(problem);
}

function showView(name) {
  el("view-query").hidden = name !== "query";
  el("view-evaluation").hidden = name !== "evaluation";
  document.querySelectorAll(".tab").forEach((tab) => {
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
}

function renderEvaluation(report) {
  if (!report) {
    el("eval-summary").replaceChildren(make("p", "message", "No evaluation report is bundled with this deployment."));
    return;
  }
  const s = report.summary;
  const model = s.by_route.model || {};
  const items = [
    [`${(s.strict_accuracy * 100).toFixed(1)}%`, `strict accuracy, ${s.cases_scored} questions scored`],
    [`${(s.lenient_accuracy * 100).toFixed(1)}%`, "counting partial answers"],
    [`${(s.tool_selection_accuracy * 100).toFixed(1)}%`, "correct tool chosen"],
    [model.p50_ms ? formatMs(model.p50_ms) : "-", "median, with a model call"],
    [model.p95_ms ? formatMs(model.p95_ms) : "-", "95th percentile, with a model call"],
  ];
  const grid = make("div", "kv");
  items.forEach(([value, label]) => {
    const cell = make("div");
    cell.append(make("strong", "", value), make("span", "", label));
    grid.append(cell);
  });
  el("eval-summary").replaceChildren(grid);
  const rows = Object.entries(s.by_category).map(([name, c]) => [name.replaceAll("_", " "), c.passed, c.partial, c.total]);
  el("eval-table").replaceChildren(renderTable(["category", "passed", "partial", "questions"], rows));
  el("eval-meta").textContent = report.meta.date;
}

function renderSidebar(about) {
  el("examples").replaceChildren(...about.examples.map((question) => {
    const item = make("li");
    const button = make("button", "", question);
    button.type = "button";
    button.addEventListener("click", () => {
      el("question").value = question;
      ask(question);
    });
    item.append(button);
    return item;
  }));
  const d = about.dataset;
  const facts = [["Portfolios", d.portfolios], ["Securities", d.securities], ["Holdings", d.holdings], ["Prices up to", d.as_of]];
  el("dataset").replaceChildren(...facts.flatMap(([label, value]) => [make("dt", "", label), make("dd", "", String(value))]));
  el("data-notes").replaceChildren(...about.data_notes.map((note) => make("li", "", note)));
  el("model-status").textContent = about.model_configured ? "Gemini connected" : "Gemini not configured";
  el("model-status").classList.toggle("offline", !about.model_configured);
  if (!about.model_configured) {
    el("model-note").textContent = "No Gemini API key is configured, so only sector exposure questions for a named fund and the examples will work.";
    el("model-note").hidden = false;
  }
}

el("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const question = el("question").value.trim();
  if (question) ask(question);
});

window.addEventListener("hashchange", () => showView(location.hash === "#evaluation" ? "evaluation" : "query"));
showView(location.hash === "#evaluation" ? "evaluation" : "query");

fetch("/api/about").then((r) => r.json()).then((about) => {
  renderSidebar(about);
  renderEvaluation(about.evaluation);
});
