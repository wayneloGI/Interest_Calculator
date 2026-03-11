/**
 * app.js — Judgment Interest Calculator Frontend
 * ================================================
 * Vanilla JS, no build step, no framework.
 * All state lives in module-level variables; functions are pure where possible.
 *
 * Architecture
 * ------------
 *   CONFIG       — API key + base URL (set once at top)
 *   API          — thin fetch wrapper
 *   State        — mutable app state
 *   Render       — pure DOM-write functions
 *   Handlers     — event callbacks (mutate state, call render)
 *   Init         — wire up listeners, boot
 */

"use strict";

/* ═══════════════════════════════════════════════════════
   CONFIG — change API_KEY to match your APP_API_KEY env var
   ═══════════════════════════════════════════════════════ */
const CONFIG = {
  API_KEY:  window.__API_KEY__ || "dev",   // injected by server or override
  BASE_URL: "",                             // same origin
};

/* ═══════════════════════════════════════════════════════
   API
   ═══════════════════════════════════════════════════════ */
const API = {
  headers() {
    return {
      "Content-Type": "application/json",
      "X-API-Key":    CONFIG.API_KEY,
    };
  },

  async post(path, body) {
    const r = await fetch(CONFIG.BASE_URL + path, {
      method:  "POST",
      headers: this.headers(),
      body:    JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  },

  async get(path) {
    const r = await fetch(CONFIG.BASE_URL + path, {
      method:  "GET",
      headers: this.headers(),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  },

  async delete(path) {
    const r = await fetch(CONFIG.BASE_URL + path, {
      method:  "DELETE",
      headers: this.headers(),
    });
    if (!r.ok && r.status !== 204) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return true;
  },
};

/* ═══════════════════════════════════════════════════════
   STATE
   ═══════════════════════════════════════════════════════ */
const State = {
  periods:        [],      // array of period-input form state
  lastResult:     null,    // last CalculateResponse from API
  lastDiff:       null,    // last RateRefreshResponse from API
  chart:          null,    // Chart.js instance
  periodCounter:  0,       // monotonic ID for period cards
};

/* ═══════════════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════════════ */
function fmt(n, dp = 2) {
  if (n == null) return "—";
  return "HK$" + Number(n).toLocaleString("en-HK", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}
function fmtPct(r, dp = 4) {
  if (r == null) return "—";
  return (Number(r) * 100).toFixed(dp).replace(/\.?0+$/, "") + "%";
}
function fmtDate(s) {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${parseInt(d)} ${months[parseInt(m)-1]} ${y}`;
}
function toast(msg, duration = 2800) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.classList.add("hidden"), 250);
  }, duration);
}
function showError(msg) {
  const el = document.getElementById("input-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function clearError() {
  const el = document.getElementById("input-error");
  el.textContent = "";
  el.classList.add("hidden");
}

/* ═══════════════════════════════════════════════════════
   PERIOD MANAGEMENT
   ═══════════════════════════════════════════════════════ */
function defaultPeriod(id, isFirst = true) {
  return {
    id,
    end_date:         "",
    interest_type:    "Simple",
    interest_basis:   "Initial Principal",
    nominal_rate:     "",
    rate_basis:       "Per annum",
    compounding_freq: "Annual",
    include_start_day: isFirst,
    include_end_day:   true,
  };
}

function renderPeriodCard(p, index) {
  const card = document.createElement("div");
  card.className = "period-card";
  card.dataset.periodId = p.id;

  const isCompound = p.interest_type === "Compound";

  card.innerHTML = `
    <div class="period-card-header">
      <span class="period-label">Period ${index + 1}</span>
      <button class="period-remove" title="Remove period">×</button>
    </div>
    <div class="field">
      <label>End Date</label>
      <input type="date" name="end_date" value="${p.end_date}">
    </div>
    <div class="period-row">
      <div class="field">
        <label>Rate</label>
        <input type="number" name="nominal_rate" min="0" max="9999" step="0.001"
               placeholder="e.g. 8.107" value="${p.nominal_rate !== "" ? (parseFloat(p.nominal_rate)*100).toFixed(4).replace(/\.?0+$/,"") : ""}">
      </div>
      <div class="field">
        <label>Rate Basis</label>
        <select name="rate_basis">
          ${["Per annum","Per month","Per quarter","Per day"].map(v =>
            `<option value="${v}" ${p.rate_basis===v?"selected":""}>${v}</option>`
          ).join("")}
        </select>
      </div>
    </div>
    <span class="cj-rate-hint" data-period-id="${p.id}">↳ Use CJ judgment rate for end date</span>
    <div class="period-row">
      <div class="field">
        <label>Interest Type</label>
        <select name="interest_type">
          <option value="Simple"   ${p.interest_type==="Simple"?"selected":""}>Simple</option>
          <option value="Compound" ${p.interest_type==="Compound"?"selected":""}>Compound</option>
        </select>
      </div>
      <div class="field ${isCompound ? "" : "hidden"}" data-compound-field>
        <label>Compounding</label>
        <select name="compounding_freq">
          ${["Monthly","Quarterly","Semi-annual","Annual"].map(v =>
            `<option value="${v}" ${p.compounding_freq===v?"selected":""}>${v}</option>`
          ).join("")}
        </select>
      </div>
    </div>
    <div class="field">
      <label>Interest Basis</label>
      <select name="interest_basis">
        <option value="Initial Principal" ${p.interest_basis==="Initial Principal"?"selected":""}>Initial Principal</option>
        <option value="Running Sum"       ${p.interest_basis==="Running Sum"?"selected":""}>Running Sum</option>
      </select>
    </div>
    <div class="field">
      <label>Day Inclusion</label>
      <div class="field-checks">
        <label class="field-check">
          <input type="checkbox" name="include_start_day" ${p.include_start_day?"checked":""}>
          Include start
        </label>
        <label class="field-check">
          <input type="checkbox" name="include_end_day" ${p.include_end_day?"checked":""}>
          Include end
        </label>
      </div>
    </div>
  `;

  // Toggle compound field visibility
  card.querySelector("[name='interest_type']").addEventListener("change", e => {
    const cf = card.querySelector("[data-compound-field]");
    cf.classList.toggle("hidden", e.target.value !== "Compound");
  });

  // Remove button
  card.querySelector(".period-remove").addEventListener("click", () => {
    State.periods = State.periods.filter(x => x.id !== p.id);
    renderAllPeriods();
  });

  // CJ rate hint
  card.querySelector(".cj-rate-hint").addEventListener("click", async () => {
    const dateInput = card.querySelector("[name='end_date']");
    const d = dateInput.value;
    if (!d) { toast("Set an end date first"); return; }
    try {
      const res = await API.get(`/api/rate-presets/cj?query_date=${d}`);
      // Rates come back as fractions; display as pct
      card.querySelector("[name='nominal_rate']").value = res.rate_pct.toFixed(3);
      card.querySelector("[name='rate_basis']").value = "Per annum";
      toast(`CJ rate for ${fmtDate(d)}: ${res.rate_pct.toFixed(3)}% pa (effective ${fmtDate(res.effective_date)})`);
    } catch (err) {
      toast(`CJ rate lookup failed: ${err.message}`, 4000);
    }
  });

  return card;
}

function renderAllPeriods() {
  const container = document.getElementById("periods-container");
  container.innerHTML = "";
  State.periods.forEach((p, i) => {
    container.appendChild(renderPeriodCard(p, i));
  });
}

function addPeriod() {
  const id = ++State.periodCounter;
  const isFirst = State.periods.length === 0;  // true only if no periods yet
  State.periods.push(defaultPeriod(id, isFirst));
  renderAllPeriods();
  // Focus the last end-date input
  const cards = document.querySelectorAll(".period-card");
  if (cards.length) {
    const last = cards[cards.length - 1];
    last.querySelector("[name='end_date']").focus();
  }
}

function readPeriods() {
  /** Collect current form values from all period cards. */
  const cards = document.querySelectorAll(".period-card");
  return Array.from(cards).map(card => {
    const v = name => card.querySelector(`[name='${name}']`);
    const rateRaw = parseFloat(v("nominal_rate").value);
    return {
      end_date:           v("end_date").value,
      interest_type:      v("interest_type").value,
      interest_basis:     v("interest_basis").value,
      nominal_rate:       String(rateRaw / 100),       // back to fraction
      rate_basis:         v("rate_basis").value,
      compounding_freq:   v("compounding_freq").value,
      include_start_day:  v("include_start_day").checked,
      include_end_day:    v("include_end_day").checked,
    };
  });
}

/* ═══════════════════════════════════════════════════════
   BUILD REQUEST
   ═══════════════════════════════════════════════════════ */
function buildRequest() {
  const principal  = document.getElementById("principal").value;
  const start_date = document.getElementById("start-date").value;
  const day_count  = document.getElementById("day-count").value;
  const case_name  = document.getElementById("case-name").value;

  if (!principal || parseFloat(principal) <= 0)
    throw new Error("Principal must be a positive number.");
  if (!start_date)
    throw new Error("Start date is required.");

  const periods = readPeriods();
  if (!periods.length)
    throw new Error("Add at least one interest period.");

  for (let i = 0; i < periods.length; i++) {
    const p = periods[i];
    if (!p.end_date)
      throw new Error(`Period ${i+1}: end date is required.`);
    if (isNaN(parseFloat(p.nominal_rate)))
      throw new Error(`Period ${i+1}: rate is required.`);
    if (parseFloat(p.nominal_rate) < 0)
      throw new Error(`Period ${i+1}: rate must be non-negative.`);
  }

  return {
    case_name:            case_name || "",
    principal:            String(parseFloat(principal).toFixed(2)),
    start_date,
    day_count_convention: day_count,
    periods,
    include_daily_series: true,
  };
}

/* ═══════════════════════════════════════════════════════
   RENDER RESULTS
   ═══════════════════════════════════════════════════════ */
function renderResults(result) {
  State.lastResult = result;

  // Summary bar
  document.getElementById("sum-principal").textContent = fmt(result.principal);
  document.getElementById("sum-interest").textContent  = fmt(result.total_interest);
  document.getElementById("sum-total").textContent     = fmt(result.final_amount);

  // Periods table
  const tbody = document.getElementById("periods-tbody");
  tbody.innerHTML = "";
  result.periods.forEach(p => {
    const tr = document.createElement("tr");
    const ratePct = (p.annualised_rate * 100).toFixed(4).replace(/\.?0+$/,"") + "%";
    tr.innerHTML = `
      <td>${p.period_id}</td>
      <td>${fmtDate(p.start_date)}</td>
      <td>${fmtDate(p.end_date)}</td>
      <td class="num">${p.days.toLocaleString()}</td>
      <td class="num">${ratePct}</td>
      <td class="num">${p.year_fraction.toFixed(6)}</td>
      <td class="num accent">${fmt(p.interest)}</td>
      <td class="num">${fmt(p.cumulative_interest)}</td>
      <td class="num">${fmt(p.principal_end)}</td>
    `;
    tbody.appendChild(tr);
  });
  // Totals row
  const totalsRow = document.createElement("tr");
  totalsRow.innerHTML = `
    <td colspan="6" class="total-row" style="text-align:right; font-family:var(--font-mono); font-size:.65rem; letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3)">Total</td>
    <td class="num total-row accent">${fmt(result.total_interest)}</td>
    <td class="total-row"></td>
    <td class="num total-row">${fmt(result.final_amount)}</td>
  `;
  tbody.appendChild(totalsRow);

  // Explanation
  const explainEl = document.getElementById("explain-content");
  explainEl.innerHTML = "";
  result.explanation.forEach(para => {
    const p = document.createElement("p");
    p.textContent = para;
    explainEl.appendChild(p);
  });

  // Chart
  renderChart(result);

  // Show content
  document.getElementById("results-empty").classList.add("hidden");
  document.getElementById("results-content").classList.remove("hidden");
}

function renderChart(result) {
  if (State.chart) {
    State.chart.destroy();
    State.chart = null;
  }
  const canvas = document.getElementById("interest-chart");
  const series = result.daily_series;
  if (!series || !series.length) return;

  // Sample every N days to keep the chart responsive
  const MAX_POINTS = 500;
  const step = Math.max(1, Math.floor(series.length / MAX_POINTS));
  const sampled = series.filter((_, i) => i % step === 0);

  const labels     = sampled.map(pt => pt.date);
  const principal  = sampled.map(pt => pt.principal);
  const interest   = sampled.map(pt => pt.total_interest);
  const total      = sampled.map(pt => pt.total_amount);

  // Period boundary annotations
  const boundaries = result.periods.map(p => p.end_date);

  State.chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label:           "Total Amount",
          data:            total,
          borderColor:     "#1c3d5a",
          backgroundColor: "rgba(28,61,90,.07)",
          borderWidth:     2,
          pointRadius:     0,
          fill:            true,
          tension:         0.3,
        },
        {
          label:           "Cumulative Interest",
          data:            interest,
          borderColor:     "#8b1a1a",
          backgroundColor: "transparent",
          borderWidth:     1.5,
          pointRadius:     0,
          tension:         0.3,
        },
        {
          label:           "Principal",
          data:            principal,
          borderColor:     "#c8bfaf",
          backgroundColor: "transparent",
          borderWidth:     1,
          borderDash:      [4, 4],
          pointRadius:     0,
        },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: {
            font: { family: "'DM Mono', monospace", size: 11 },
            color: "#6b6458",
            boxWidth: 18,
          },
        },
        tooltip: {
          backgroundColor: "#1a1814",
          titleFont: { family: "'DM Mono', monospace", size: 11 },
          bodyFont:  { family: "'DM Mono', monospace", size: 11 },
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: HK$${ctx.raw.toLocaleString("en-HK",{minimumFractionDigits:2,maximumFractionDigits:2})}`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            font: { family: "'DM Mono', monospace", size: 10 },
            color: "#6b6458",
            maxTicksLimit: 8,
          },
          grid: { color: "#e0d9cc" },
        },
        y: {
          ticks: {
            font: { family: "'DM Mono', monospace", size: 10 },
            color: "#6b6458",
            callback: v => "HK$" + (v/1000).toFixed(0) + "k",
          },
          grid: { color: "#e0d9cc" },
        },
      },
    },
  });
}

/* ═══════════════════════════════════════════════════════
   COPY FUNCTIONS
   ═══════════════════════════════════════════════════════ */
function copyTsv() {
  const result = State.lastResult;
  if (!result) return;
  const header = ["#","Start","End","Days","Rate pa","Year Frac","Interest","Cumulative","Principal End"];
  const rows = result.periods.map(p => [
    p.period_id,
    p.start_date,
    p.end_date,
    p.days,
    (p.annualised_rate*100).toFixed(4) + "%",
    p.year_fraction.toFixed(6),
    p.interest.toFixed(2),
    p.cumulative_interest.toFixed(2),
    p.principal_end.toFixed(2),
  ]);
  const tsv = [header, ...rows].map(r => r.join("\t")).join("\n");
  navigator.clipboard.writeText(tsv).then(() => toast("Copied TSV to clipboard"));
}

function copyExplain() {
  const result = State.lastResult;
  if (!result) return;
  navigator.clipboard.writeText(result.explanation.join("\n\n"))
    .then(() => toast("Copied explanation to clipboard"));
}

/* ═══════════════════════════════════════════════════════
   CASES
   ═══════════════════════════════════════════════════════ */
async function loadCases() {
  try {
    const cases = await API.get("/api/cases");
    const sel = document.getElementById("cases-select");
    sel.innerHTML = '<option value="">— Saved cases —</option>';
    cases.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = `${c.name} (${c.start_date})`;
      sel.appendChild(opt);
    });
  } catch { /* silently ignore if cases not available */ }
}

async function loadCase(id) {
  try {
    const detail = await API.get(`/api/cases/${id}`);
    populateForm(detail.request_payload);
    toast(`Loaded: ${detail.name}`);
  } catch (err) {
    toast(`Failed to load case: ${err.message}`, 4000);
  }
}

function populateForm(payload) {
  document.getElementById("case-name").value    = payload.case_name || "";
  document.getElementById("principal").value    = payload.principal || "";
  document.getElementById("start-date").value   = payload.start_date || "";
  document.getElementById("day-count").value    = payload.day_count_convention || "Actual/365 Fixed";

  State.periods = [];
  State.periodCounter = 0;
  (payload.periods || []).forEach(p => {
    const id = ++State.periodCounter;
    State.periods.push({
      id,
      end_date:          p.end_date || "",
      interest_type:     p.interest_type || "Simple",
      interest_basis:    p.interest_basis || "Initial Principal",
      nominal_rate:      p.nominal_rate || "",
      rate_basis:        p.rate_basis || "Per annum",
      compounding_freq:  p.compounding_freq || "Annual",
      include_start_day: p.include_start_day !== false,
      include_end_day:   p.include_end_day !== false,
    });
  });
  renderAllPeriods();
}

function openSaveModal() {
  const caseName = document.getElementById("case-name").value;
  document.getElementById("save-name-input").value = caseName;
  document.getElementById("modal-save").classList.remove("hidden");
  document.getElementById("modal-backdrop").classList.remove("hidden");
  document.getElementById("save-name-input").focus();
}

function closeSaveModal() {
  document.getElementById("modal-save").classList.add("hidden");
  document.getElementById("modal-backdrop").classList.add("hidden");
}

async function confirmSave() {
  const name = document.getElementById("save-name-input").value.trim();
  if (!name) { toast("Enter a case name"); return; }
  try {
    const req = buildRequest();
    await API.post("/api/cases", { name, request_payload: req });
    toast(`Saved: ${name}`);
    closeSaveModal();
    loadCases();
  } catch (err) {
    toast(`Save failed: ${err.message}`, 4000);
  }
}

/* ═══════════════════════════════════════════════════════
   SETTINGS — rate table
   ═══════════════════════════════════════════════════════ */
async function loadRateTable() {
  try {
    const data = await API.get("/api/settings/rates");
    const tbody = document.getElementById("rates-tbody");
    tbody.innerHTML = "";
    data.entries.forEach(e => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${fmtDate(e.effective_date)}</td><td class="num">${e.rate_pct.toFixed(3)}%</td>`;
      tbody.appendChild(tr);
    });
    document.getElementById("refresh-status").textContent =
      `${data.count} entries · ${data.earliest_date} → ${data.latest_date}`;
  } catch (err) {
    document.getElementById("rates-tbody").innerHTML =
      `<tr><td colspan="2" class="loading-cell">Failed to load: ${err.message}</td></tr>`;
  }
}

async function refreshRates() {
  const btn = document.getElementById("refresh-rates-btn");
  const status = document.getElementById("refresh-status");
  btn.disabled = true;
  btn.textContent = "Checking…";
  status.textContent = "";
  try {
    const res = await API.post("/api/settings/rates/refresh", {});
    State.lastDiff = res;
    if (res.new_count === 0) {
      status.textContent = "Already up to date.";
    } else {
      // Show diff preview
      const preview = document.getElementById("diff-preview");
      const tbody   = document.getElementById("diff-tbody");
      tbody.innerHTML = "";
      res.new_entries.forEach(e => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${fmtDate(e.effective_date)}</td><td class="num">${e.rate_pct.toFixed(3)}%</td>`;
        tbody.appendChild(tr);
      });
      preview.classList.remove("hidden");
    }
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Check for Updates";
  }
}

async function applyRates() {
  if (!State.lastDiff) return;
  try {
    const res = await API.post("/api/settings/rates/apply", State.lastDiff);
    toast(res.message);
    document.getElementById("diff-preview").classList.add("hidden");
    State.lastDiff = null;
    loadRateTable();
  } catch (err) {
    toast(`Apply failed: ${err.message}`, 4000);
  }
}

/* ═══════════════════════════════════════════════════════
   NAVIGATION
   ═══════════════════════════════════════════════════════ */
function showPage(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`page-${name}`).classList.add("active");
  document.querySelector(`[data-page='${name}']`).classList.add("active");

  if (name === "settings") loadRateTable();
}

/* ═══════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════ */
function init() {

  // Navigation
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  });

  // Add first period
  addPeriod();

  // Add period button
  document.getElementById("add-period-btn").addEventListener("click", addPeriod);

  // Calculate
  document.getElementById("calculate-btn").addEventListener("click", async () => {
    clearError();
    let req;
    try {
      req = buildRequest();
    } catch (err) {
      showError(err.message);
      return;
    }
    const btn = document.getElementById("calculate-btn");
    btn.disabled = true;
    btn.textContent = "Calculating…";
    try {
      const result = await API.post("/api/calculate", req);
      renderResults(result);
      clearError();
    } catch (err) {
      showError(`Calculation failed: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Calculate";
    }
  });

  // Clear
  document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("case-name").value  = "";
    document.getElementById("principal").value  = "";
    document.getElementById("start-date").value = "";
    State.periods = [];
    State.periodCounter = 0;
    renderAllPeriods();
    addPeriod();
    document.getElementById("results-empty").classList.remove("hidden");
    document.getElementById("results-content").classList.add("hidden");
    clearError();
  });

  // Tabs
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${name}`).classList.add("active");
      // Re-render chart when switching to it (canvas sizing)
      if (name === "chart" && State.lastResult) {
        setTimeout(() => renderChart(State.lastResult), 50);
      }
    });
  });

  // Copy buttons
  document.getElementById("copy-tsv-btn").addEventListener("click", copyTsv);
  document.getElementById("copy-explain-btn").addEventListener("click", copyExplain);

  // Save modal
  document.getElementById("save-case-btn").addEventListener("click", openSaveModal);
  document.getElementById("modal-save-cancel").addEventListener("click", closeSaveModal);
  document.getElementById("modal-backdrop").addEventListener("click", closeSaveModal);
  document.getElementById("modal-save-confirm").addEventListener("click", confirmSave);
  document.getElementById("save-name-input").addEventListener("keydown", e => {
    if (e.key === "Enter") confirmSave();
    if (e.key === "Escape") closeSaveModal();
  });

  // Cases dropdown
  document.getElementById("cases-select").addEventListener("change", e => {
    if (e.target.value) {
      loadCase(parseInt(e.target.value));
      e.target.value = "";  // reset after loading
    }
  });

  // Settings
  document.getElementById("refresh-rates-btn").addEventListener("click", refreshRates);
  document.getElementById("apply-rates-btn").addEventListener("click", applyRates);
  document.getElementById("discard-diff-btn").addEventListener("click", () => {
    document.getElementById("diff-preview").classList.add("hidden");
    State.lastDiff = null;
  });

  // Load saved cases on boot
  loadCases();

  // Keyboard shortcut: Enter on calculate button
  document.addEventListener("keydown", e => {
    if (e.key === "Enter" && e.ctrlKey) {
      document.getElementById("calculate-btn").click();
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
