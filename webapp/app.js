const STEP_ORDER = [
  "1_load",
  "2_compile",
  "2b_fix_errors",
  "3_extract_params",
  "4_create_wide_ini",
  "5_validate_trades",
  "6_create_opt_ini",
  "7_run_optimization",
  "8_parse_results",
  "9_backtest_robust",
  "10_monte_carlo",
  "11_report",
];

let allStates = [];
let allModules = [];
let allTerminals = [];
let allEas = [];
let selectedPath = null;
let selectedState = null;
let lastJobsById = {};

function $(sel) {
  return document.querySelector(sel);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children || []) node.appendChild(c);
  return node;
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: "Invalid JSON response", raw: text };
  }
  if (!res.ok) {
    const msg = (data && data.error) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "passed" || s === "completed") return "good";
  if (s === "failed") return "bad";
  if (s === "running") return "warn";
  return "warn";
}

function fmt(s) {
  if (!s) return "—";
  return String(s);
}

function linkButton(label, href) {
  return el(
    "a",
    { class: "btn", href, target: "_blank", rel: "noopener", text: label },
    []
  );
}

function renderStatesList() {
  const list = $("#statesList");
  list.innerHTML = "";

  const q = String($("#searchInput").value || "").trim().toLowerCase();
  const states = (allStates || []).filter((s) => {
    const name = String(s.ea_name || "");
    if (!q) return true;
    return name.toLowerCase().includes(q);
  });

  if (!states.length) {
    list.appendChild(el("div", { class: "muted", text: "No runs found." }));
    return;
  }

  for (const s of states) {
    const isSelected = selectedPath && s.path === selectedPath;
    const title = String(s.ea_name || s.filename || "Unknown");
    const sub = `${fmt(s.symbol)} • ${fmt(s.timeframe)} • ${fmt(s.updated_at || s.created_at)}`;
    const progress = `${s.steps_passed || 0}/${s.steps_total || 0} steps`;
    const result = s.overall_result ? `Result: ${s.overall_result}` : "Result: —";

    const item = el(
      "div",
      {
        class: `state-item ${isSelected ? "selected" : ""}`,
        onClick: () => selectState(s.path),
      },
      [
        el("div", { class: "state-name", text: title }),
        el("div", { class: "state-sub", text: sub }),
        el("div", { class: "pill", text: progress }),
        el("div", { class: "pill", text: result }),
      ]
    );
    list.appendChild(item);
  }
}

async function refreshStates() {
  const data = await fetchJson("/api/states?limit=200");
  allStates = data.states || [];
  renderStatesList();
}

function renderTerminalSelect() {
  const sel = $("#terminalSelect");
  if (!sel) return;
  sel.innerHTML = "";
  for (const t of allTerminals) {
    const label = `${t.is_running ? "● " : ""}${t.id}${t.is_default ? " (default)" : ""}${
      t.origin_path ? ` — ${t.origin_path}` : ""
    }`;
    const opt = el("option", { value: t.id, text: label }, []);
    sel.appendChild(opt);
  }
}

function renderEaSelect() {
  const sel = $("#eaSelect");
  if (!sel) return;
  sel.innerHTML = "";

  const q = String($("#eaSearchInput").value || "").trim().toLowerCase();
  const filtered = (allEas || []).filter((e) => {
    if (!q) return true;
    return String(e.name || "").toLowerCase().includes(q) || String(e.rel_path || "").toLowerCase().includes(q);
  });

  for (const e of filtered) {
    const opt = el("option", { value: e.rel_path, text: `${e.name} — ${e.rel_path}` }, []);
    sel.appendChild(opt);
  }
}

async function refreshTerminals() {
  const data = await fetchJson("/api/terminals");
  allTerminals = data.terminals || [];
  renderTerminalSelect();

  const sel = $("#terminalSelect");
  if (sel && sel.value) {
    await refreshEas(sel.value);
  } else if (sel && allTerminals.length) {
    sel.value = allTerminals[0].id;
    await refreshEas(sel.value);
  }
}

async function refreshEas(terminalId) {
  if (!terminalId) return;
  const data = await fetchJson(`/api/eas?terminal_id=${encodeURIComponent(terminalId)}`);
  allEas = data.eas || [];
  renderEaSelect();
}

async function refreshModules() {
  const data = await fetchJson("/api/modules");
  allModules = data.modules || [];
  renderModulesTable();
}

async function selectState(path) {
  selectedPath = path;
  renderStatesList();

  $("#stateTitle").textContent = "Loading…";
  $("#stateMeta").textContent = "";
  $("#stateKpis").innerHTML = "";
  $("#stateLinks").innerHTML = "";
  $("#stepsTable").innerHTML = "";

  const data = await fetchJson(`/api/state?path=${encodeURIComponent(path)}`);
  selectedState = data.state || null;
  renderState(data.summary || {});
  renderStepsTable();
  renderModulesTable();
}

function renderState(summary) {
  $("#stateTitle").textContent = fmt(summary.ea_name);
  $("#stateMeta").textContent = `${fmt(summary.symbol)} • ${fmt(summary.timeframe)} • Updated: ${fmt(
    summary.updated_at || summary.created_at
  )} • Current: ${fmt(summary.current_step)}`;

  const kpis = $("#stateKpis");
  kpis.innerHTML = "";
  kpis.appendChild(
    el("div", { class: "kpi", title: "Final verdict from Step 11 report." }, [
      el("div", { class: "label", text: "Overall Result" }),
      el("div", { class: "value", text: fmt(summary.overall_result) }),
    ])
  );
  kpis.appendChild(
    el("div", { class: "kpi", title: "MT5 history quality from report (e.g. 100%)." }, [
      el("div", { class: "label", text: "History Quality" }),
      el("div", { class: "value", text: fmt(summary.history_quality) }),
    ])
  );
  kpis.appendChild(
    el("div", { class: "kpi", title: "Steps passed / total steps." }, [
      el("div", { class: "label", text: "Progress" }),
      el("div", {
        class: "value",
        text: `${summary.steps_passed || 0}/${summary.steps_total || 0}`,
      }),
    ])
  );
  kpis.appendChild(
    el("div", { class: "kpi", title: "Bars/ticks in MT5 report." }, [
      el("div", { class: "label", text: "Bars / Ticks" }),
      el("div", { class: "value", text: `${fmt(summary.bars)} / ${fmt(summary.ticks)}` }),
    ])
  );

  const links = $("#stateLinks");
  links.innerHTML = "";
  links.appendChild(linkButton("State JSON", `/${summary.path}`));
  if (summary.dashboard_rel) links.appendChild(linkButton("Dashboard", `/${summary.dashboard_rel}`));
  if (summary.report_rel) links.appendChild(linkButton("Text Report", `/${summary.report_rel}`));
  if (summary.backtest_report_rel) links.appendChild(linkButton("Backtest Report", `/${summary.backtest_report_rel}`));

  const postSteps = (selectedState && selectedState.post_steps) || [];
  for (const ps of postSteps) {
    const out = ps.output || {};
    if (out && out.index) {
      const rel = guessRel(out.index);
      if (rel) links.appendChild(linkButton(`${ps.name} report`, `/${rel}`));
    }
  }
}

function guessRel(pathStr) {
  if (!pathStr) return null;
  const p = String(pathStr).replace(/\\/g, "/");
  const idx = p.indexOf("/runs/");
  if (idx >= 0) return p.slice(idx + 1);
  if (p.startsWith("runs/")) return p;
  return null;
}

function orderedStepKeys(stepsObj) {
  const keys = Object.keys(stepsObj || {});
  const known = [];
  const unknown = [];
  for (const k of keys) {
    if (STEP_ORDER.includes(k)) known.push(k);
    else unknown.push(k);
  }
  known.sort((a, b) => STEP_ORDER.indexOf(a) - STEP_ORDER.indexOf(b));
  unknown.sort();
  return [...known, ...unknown];
}

function renderStepsTable() {
  const mount = $("#stepsTable");
  mount.innerHTML = "";

  if (!selectedState) {
    mount.appendChild(el("div", { class: "muted", text: "No run selected." }));
    return;
  }

  const steps = selectedState.steps || {};
  const keys = orderedStepKeys(steps);

  const table = el("table", {}, []);
  const thead = el("thead", {}, [
    el("tr", {}, [
      el("th", { text: "Step" }),
      el("th", { text: "Status" }),
      el("th", { text: "Started" }),
      el("th", { text: "Completed" }),
      el("th", { text: "Error" }),
    ]),
  ]);
  table.appendChild(thead);

  const tbody = el("tbody", {}, []);
  for (const k of keys) {
    const s = steps[k] || {};
    const st = s.status || "pending";
    const err = s.error || "";
    const tr = el("tr", {}, [
      el("td", { text: k }),
      el("td", {}, [el("span", { class: `status ${statusClass(st)}`, text: st })]),
      el("td", { text: fmt(s.started_at) }),
      el("td", { text: fmt(s.completed_at) }),
      el("td", { text: fmt(err) }),
    ]);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  mount.appendChild(table);
}

function findLastPostStep(stateKey) {
  const postSteps = (selectedState && selectedState.post_steps) || [];
  const matching = postSteps.filter((p) => String(p.name || "") === String(stateKey || ""));
  if (!matching.length) return null;
  matching.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
  return matching[0];
}

function renderModulesTable() {
  const mount = $("#modulesTable");
  mount.innerHTML = "";

  if (!selectedState) {
    mount.appendChild(el("div", { class: "muted", text: "Select a run to view modules." }));
    return;
  }

  if (!allModules.length) {
    mount.appendChild(el("div", { class: "muted", text: "No module catalog loaded." }));
    return;
  }

  const table = el("table", {}, []);
  table.appendChild(
    el("thead", {}, [
      el("tr", {}, [
        el("th", { text: "Module" }),
        el("th", { text: "Status" }),
        el("th", { text: "Action" }),
      ]),
    ])
  );

  const tbody = el("tbody", {}, []);

  for (const m of allModules) {
    const last = findLastPostStep(m.state_key || m.id);
    const status = last ? last.status : "not run";
    const statusEl = el("span", { class: `status ${statusClass(status)}`, text: status });

    const info = el("div", {}, [
      el("div", { text: m.title || m.id }),
      el("div", { class: "muted", text: m.description || "" }),
    ]);

    const actionCell = el("td", {}, []);
    if (m.implemented) {
      const btn = el(
        "button",
        {
          class: "btn",
          text: "Run",
          onClick: async (ev) => {
            ev.preventDefault();
            btn.disabled = true;
            btn.textContent = "Running…";
            try {
              await fetchJson("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ module_id: m.id, state_path: selectedPath }),
              });
              await refreshJobs();
            } catch (e) {
              alert(String(e.message || e));
            } finally {
              btn.disabled = false;
              btn.textContent = "Run";
            }
          },
        },
        []
      );
      actionCell.appendChild(btn);
    } else {
      actionCell.appendChild(el("span", { class: "muted", text: "Planned" }));
    }

    tbody.appendChild(el("tr", {}, [el("td", {}, [info]), el("td", {}, [statusEl]), actionCell]));
  }

  table.appendChild(tbody);
  mount.appendChild(table);
}

function renderJobsPanel(jobs) {
  const mount = $("#jobsPanel");
  mount.innerHTML = "";

  if (!jobs.length) {
    mount.appendChild(el("div", { class: "muted", text: "No jobs yet." }));
    return;
  }

  for (const j of jobs) {
    const head = el("div", { class: "job-head" }, [
      el("div", { class: "job-title", text: `${j.module_id} • ${j.status}` }),
      el("div", { class: "muted", text: `rc=${j.returncode ?? "—"}` }),
    ]);
    const cmd = el("div", { class: "muted", text: (j.command || []).join(" ") });
    const log = el("div", { class: "job-log", text: j.log_tail || "" });

    mount.appendChild(el("div", { class: "job" }, [head, cmd, log]));
  }
}

async function refreshJobs() {
  const data = await fetchJson("/api/jobs");
  const jobs = data.jobs || [];
  renderJobsPanel(jobs);

  const currentById = {};
  for (const j of jobs) currentById[j.id] = j;

  // If any running -> completed/failed, refresh selected state + states list.
  let shouldRefresh = false;
  for (const [id, prev] of Object.entries(lastJobsById)) {
    const cur = currentById[id];
    if (!cur) continue;
    if (String(prev.status) === "running" && String(cur.status) !== "running") {
      shouldRefresh = true;
      break;
    }
  }
  lastJobsById = currentById;

  if (shouldRefresh) {
    try {
      await refreshStates();
      if (selectedPath) await selectState(selectedPath);
    } catch {
      // ignore UI refresh errors
    }
  }
}

function attachEvents() {
  $("#searchInput").addEventListener("input", renderStatesList);
  $("#refreshBtn").addEventListener("click", async () => {
    await refreshStates();
    if (selectedPath) await selectState(selectedPath);
  });

  const termSel = $("#terminalSelect");
  if (termSel) {
    termSel.addEventListener("change", async () => {
      await refreshEas(termSel.value);
    });
  }

  const eaSearch = $("#eaSearchInput");
  if (eaSearch) {
    eaSearch.addEventListener("input", renderEaSelect);
  }

  const optCheck = $("#optCheck");
  const mcCheck = $("#mcCheck");
  const reportCheck = $("#reportCheck");
  function syncDeps() {
    const optOn = optCheck && optCheck.checked;
    if (mcCheck) {
      mcCheck.disabled = !optOn;
      if (!optOn) mcCheck.checked = false;
    }
    const mcOn = mcCheck && mcCheck.checked;
    if (reportCheck) {
      reportCheck.disabled = !(optOn && mcOn);
      if (!(optOn && mcOn)) reportCheck.checked = false;
    }
  }
  if (optCheck) optCheck.addEventListener("change", syncDeps);
  if (mcCheck) mcCheck.addEventListener("change", syncDeps);
  syncDeps();

  const startBtn = $("#startWorkflowBtn");
  if (startBtn) {
    startBtn.addEventListener("click", async () => {
      const terminalId = termSel ? termSel.value : "";
      const eaRel = $("#eaSelect") ? $("#eaSelect").value : "";
      const symbol = String($("#symbolInput").value || "EURUSD").trim();
      const timeframe = String($("#timeframeInput").value || "H1").trim();

      const opts = {
        inject_ontester: $("#ontesterCheck") ? $("#ontesterCheck").checked : true,
        inject_safety: $("#safetyCheck") ? $("#safetyCheck").checked : true,
        run_optimization: $("#optCheck") ? $("#optCheck").checked : true,
        run_monte_carlo: $("#mcCheck") ? $("#mcCheck").checked : true,
        run_report: $("#reportCheck") ? $("#reportCheck").checked : true,
      };

      if (!terminalId || !eaRel) {
        alert("Select a terminal and an EA first.");
        return;
      }

      startBtn.disabled = true;
      startBtn.textContent = "Starting…";
      try {
        await fetchJson("/api/workflow/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            terminal_id: terminalId,
            ea_rel_path: eaRel,
            symbol,
            timeframe,
            options: opts,
          }),
        });
        await refreshJobs();
        await refreshStates();
      } catch (e) {
        alert(String(e.message || e));
      } finally {
        startBtn.disabled = false;
        startBtn.textContent = "Start workflow";
      }
    });
  }
}

async function boot() {
  attachEvents();
  await refreshTerminals();
  await refreshStates();
  await refreshModules();
  await refreshJobs();

  setInterval(() => refreshStates().catch(() => {}), 15000);
  setInterval(() => refreshJobs().catch(() => {}), 2000);
}

boot().catch((e) => {
  console.error(e);
  $("#stateTitle").textContent = `Error: ${String(e.message || e)}`;
});
