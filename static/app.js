// ProjectBudget dashboard frontend (phase 5).
"use strict";

const state = { range: "6mo", account: "all", anchor: "latest", start: null, end: null };
let categories = [];
let catChart = null, trendChart = null;

const PALETTE = [
  "#4f9cf9", "#3fb950", "#f0883e", "#bc8cff", "#f85149", "#56d4dd",
  "#e3b341", "#db61a2", "#7ee787", "#a5d6ff", "#ffa657", "#d2a8ff",
];

const fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const $ = (sel) => document.querySelector(sel);
// Chart colors come from the CSS theme variables so light/dark both work.
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

// ---- Loaders -------------------------------------------------------------

async function loadCategories() {
  categories = (await api("/categories")).map((c) => c.name);
}

async function loadAccounts() {
  const accounts = await api("/accounts");
  const sel = $("#accountFilter");
  sel.innerHTML = '<option value="all">All accounts</option>' +
    accounts.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("");
  sel.value = state.account;
}

async function loadReport() {
  const q = new URLSearchParams({ range: state.range, account: state.account, anchor: state.anchor });
  if (state.start && state.end) { q.set("start", state.start); q.set("end", state.end); }
  const r = await api("/report?" + q);
  renderCards(r);
  renderCategoryChart(r);
  renderTrendChart(r);
  renderCategoryTable(r);
}

async function loadRules() {
  const rules = await api("/rules");
  const body = $("#rulesTable").querySelector("tbody");
  if (!rules.length) {
    body.innerHTML = `<tr><td class="empty">No learned rules yet — assign a category on the left.</td></tr>`;
    return;
  }
  body.innerHTML = `<tr><th>Pattern</th><th>Category</th><th></th></tr>` + rules.map((r) => `
    <tr>
      <td>${esc(r.pattern)}${r.direction !== "any" ? ` <span class="pill">${esc(r.direction)}</span>` : ""}</td>
      <td>${esc(r.category)}</td>
      <td class="num"><button class="del" data-rule-id="${r.id}" title="Delete this rule">✕</button></td>
    </tr>`).join("");
}

async function loadUncategorized() {
  const rows = await api("/uncategorized?limit=25");
  const body = $("#uncatTable").querySelector("tbody");
  if (!rows.length) {
    body.innerHTML = `<tr><td class="empty">Nothing uncategorized 🎉</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((r) => `
    <tr>
      <td>${esc(r.description)}<br><span style="color:var(--muted);font-size:12px">${r.count}× · ${fmt.format(r.total)}</span></td>
      <td class="num">${catSelect(r.description)}</td>
    </tr>`).join("");
}

// ---- Renderers -----------------------------------------------------------

function renderCards(r) {
  const t = r.totals, rg = r.range;
  const floorNote = rg.clamped_to_history_start
    ? `<br><span style="font-size:11px;color:var(--accent)" title="Limited to where the selected account(s) have data — for All accounts, the period where every imported source has statements">⛏ from data start</span>`
    : "";
  $("#cards").innerHTML = `
    ${card("Total spend", fmt.format(t.spend), "bad")}
    ${card("Income", fmt.format(t.income), "good")}
    ${card("Net", fmt.format(t.net), t.net >= 0 ? "good" : "bad")}
    ${card("Transactions", t.transactions)}
    ${card("Range", `${rg.start}<br><span style="font-size:13px;color:var(--muted)">to ${rg.end}</span>${floorNote}`)}
  `;
}

function card(label, value, cls = "") {
  return `<div class="card"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`;
}

function renderCategoryChart(r) {
  const labels = r.by_category.map((c) => c.category);
  const data = r.by_category.map((c) => c.total);
  if (catChart) catChart.destroy();
  if (!labels.length) return;
  catChart = new Chart($("#catChart"), {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }] },
    options: { plugins: { legend: { position: "right", labels: { color: cssVar("--text"), boxWidth: 12 } },
      tooltip: { callbacks: { label: (c) => `${c.label}: ${fmt.format(c.parsed)}` } } } },
  });
}

function renderTrendChart(r) {
  const labels = r.monthly_trend.map((m) => m.month + (m.partial ? " *" : ""));
  const data = r.monthly_trend.map((m) => m.spend);
  // Partial months (range starts/ends mid-month) read low — draw them muted.
  const colors = r.monthly_trend.map((m) => m.partial ? cssVar("--muted") : cssVar("--accent"));
  if (trendChart) trendChart.destroy();
  if (!labels.length) return;
  trendChart = new Chart($("#trendChart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "Spend", data, backgroundColor: colors, borderRadius: 5 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: {
        label: (c) => fmt.format(c.parsed.y) + (r.monthly_trend[c.dataIndex].partial ? " (partial month)" : "") } } },
      scales: { x: { ticks: { color: cssVar("--muted") }, grid: { display: false } },
        y: { ticks: { color: cssVar("--muted"), callback: (v) => "$" + v }, grid: { color: cssVar("--border") } } } },
  });
}

function renderCategoryTable(r) {
  const body = $("#catTable").querySelector("tbody");
  if (!r.by_category.length) {
    body.innerHTML = `<tr><td class="empty">No spending in this range. Import a statement above.</td></tr>`;
    return;
  }
  let html = `<tr><th>Category</th><th class="num">Spent</th><th class="num">%</th></tr>`;
  r.by_category.forEach((c, i) => {
    const color = PALETTE[i % PALETTE.length];
    html += `<tr class="cat-row" data-cat="${esc(c.category)}">
      <td><span class="swatch" style="background:${color}"></span>${esc(c.category)} <span style="color:var(--muted)">(${c.txns})</span></td>
      <td class="num">${fmt.format(c.total)}</td><td class="num">${c.pct}%</td></tr>`;
    const top = r.top_per_category[c.category] || [];
    const inner = top.map((t) => `<tr><td>${esc(t.txn_date)} · ${esc(t.description)}
        <span style="color:var(--muted)">(${esc(t.source_account)})</span></td>
        <td class="num">${fmt.format(t.amount)}</td><td></td></tr>`).join("");
    html += `<tr class="top5 hidden" data-for="${esc(c.category)}"><td colspan="3" style="padding:0">
        <table style="margin:0"><tbody>${inner || '<tr><td>No items</td></tr>'}</tbody></table></td></tr>`;
  });
  body.innerHTML = html;
  body.querySelectorAll(".cat-row").forEach((row) => {
    row.addEventListener("click", () => {
      const t = body.querySelector(`.top5[data-for="${cssEsc(row.dataset.cat)}"]`);
      if (t) t.classList.toggle("hidden");
    });
  });
}

// ---- Interactions --------------------------------------------------------

function catSelect(description) {
  const opts = categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  return `<select class="recat" data-desc="${esc(description)}">
    <option value="">Assign…</option>${opts}</select>`;
}

async function uploadFiles() {
  const input = $("#fileInput");
  if (!input.files.length) { setMsg("Choose CSV file(s) first."); return; }
  const fd = new FormData();
  for (const f of input.files) fd.append("files", f);
  setMsg("Uploading…");
  try {
    const r = await api("/upload", { method: "POST", body: fd });
    const parts = r.files.map((f) => f.error
      ? `${f.file}: ⚠️ ${f.error}`
      : `${f.file} → ${f.detected_account}: ${f.inserted} new, ${f.duplicates_skipped} dupes`);
    setMsg(`Imported ${r.total_inserted} new transaction(s). ` + parts.join(" | "));
    input.value = "";
    await refresh();
  } catch (e) {
    setMsg("Upload failed: " + e.message);
  }
}

async function recategorize(description, category) {
  // Teach a rule from the full description; the backend re-applies it everywhere.
  const fd = new FormData();
  fd.append("pattern", description);
  fd.append("category", category);
  await api("/rules", { method: "POST", body: fd });
  await refresh();
}

function setMsg(s) { $("#uploadMsg").textContent = s; }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/["\\]/g, "\\$&");

// ---- Wiring --------------------------------------------------------------

$("#ranges").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-range]");
  if (!btn) return;
  state.range = btn.dataset.range;
  state.start = state.end = null;               // presets clear the custom range
  $("#startDate").value = $("#endDate").value = "";
  $("#ranges").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  loadReport();
});

function applyCustomDates() {
  const start = $("#startDate").value, end = $("#endDate").value;
  if (!start || !end) return;                   // wait until both are picked
  state.start = start;
  state.end = end;
  $("#ranges").querySelectorAll("button").forEach((b) => b.classList.remove("active"));
  loadReport();
}
$("#startDate").addEventListener("change", applyCustomDates);
$("#endDate").addEventListener("change", applyCustomDates);

$("#accountFilter").addEventListener("change", (e) => { state.account = e.target.value; loadReport(); });
$("#anchorFilter").addEventListener("change", (e) => { state.anchor = e.target.value; loadReport(); });
$("#uploadBtn").addEventListener("click", uploadFiles);
document.addEventListener("change", (e) => {
  const sel = e.target.closest("select.recat");
  if (sel && sel.value) recategorize(sel.dataset.desc, sel.value);
});
document.addEventListener("click", async (e) => {
  const del = e.target.closest("button[data-rule-id]");
  if (!del) return;
  const r = await api(`/rules/${del.dataset.ruleId}`, { method: "DELETE" });
  setToolsMsg(`Rule deleted; ${r.transactions_recategorized} transaction(s) re-categorized.`);
  await refresh();
});

$("#addCatBtn").addEventListener("click", async () => {
  const name = $("#newCatName").value.trim();
  if (!name) return;
  const fd = new FormData();
  fd.append("name", name);
  try {
    await api("/categories", { method: "POST", body: fd });
    $("#newCatName").value = "";
    await loadCategories();
    await loadUncategorized();                  // rebuild dropdowns with the new option
    setToolsMsg(`Category "${name}" added.`);
  } catch (err) {
    setToolsMsg("Could not add category: " + err.message);
  }
});

$("#resetBtn").addEventListener("click", async () => {
  const typed = prompt("This deletes ALL transactions and learned rules. Type DELETE to confirm:");
  if (typed !== "DELETE") { setToolsMsg("Reset cancelled."); return; }
  const fd = new FormData();
  fd.append("confirm", "DELETE");
  const r = await api("/reset", { method: "POST", body: fd });
  setToolsMsg(`Deleted ${r.transactions_deleted} transaction(s) and ${r.rules_deleted} rule(s).`);
  await refresh();
});

function setToolsMsg(s) { $("#toolsMsg").textContent = s; }

// Re-render charts when the OS theme flips so colors track the CSS variables.
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => loadReport());

async function refresh() {
  await Promise.all([loadAccounts(), loadReport(), loadUncategorized(), loadRules()]);
}

(async function init() {
  await loadCategories();
  await refresh();
})();
