#!/usr/bin/env python3
"""
Run a multi-fold walk-forward validation and generate an offline HTML report.

This is an OPTIONAL module (post-Step-11).

It reuses a single parameter set (typically the best params from the workflow)
and re-runs MT5 backtests across multiple IS/OOS folds to reduce reliance on a
single split.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BACKTEST_FROM, BACKTEST_TO, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, RUNS_DIR
from settings import get_settings
from tester.multipair import load_params
from tester.walk_forward import WalkForwardTester
from workflow.post_steps import complete_post_step, fail_post_step, start_post_step


def _find_latest_workflow_state(ea_name: str) -> Optional[Path]:
    candidates = sorted(RUNS_DIR.glob(f"workflow_{ea_name}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_state(state_path: Path) -> Dict[str, Any]:
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_path(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return p
    cand = Path(__file__).parent.parent / path_str
    return cand if cand.exists() else None


def _pick_params_from_state(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    steps = state.get("steps", {}) or {}
    step8 = steps.get("8_parse_results", {}) or {}
    out = step8.get("output", {}) if isinstance(step8, dict) else {}
    if isinstance(out, dict) and out.get("params_file"):
        p = _resolve_path(out.get("params_file"))
        if p and p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def _render_html(data: Dict[str, Any]) -> str:
    safe = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Walk-Forward Validation - {data.get("ea_name","")}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #121a33;
      --muted: #a8b3cf;
      --text: #e8ecf7;
      --accent: #6aa6ff;
      --good: #3ddc97;
      --warn: #ffcc66;
      --bad: #ff6b6b;
      --border: rgba(255,255,255,0.08);
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Arial;
      background: radial-gradient(1200px 800px at 10% 0%, #17234a 0%, var(--bg) 40%, var(--bg) 100%);
      color: var(--text);
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    .title {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.2px; }}
    .subtitle {{ color: var(--muted); font-size: 13px; }}
    .tag {{ display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); color: var(--muted); }}
    .card {{
      background: rgba(18,26,51,0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.25);
      margin-top: 14px;
    }}
    .kpi {{ display:flex; gap:12px; flex-wrap: wrap; }}
    .kpi .item {{ flex: 1 1 180px; padding: 10px; border: 1px solid var(--border); border-radius: 12px; background: rgba(255,255,255,0.02); }}
    .kpi .label {{ font-size: 12px; color: var(--muted); }}
    .kpi .value {{ margin-top: 4px; font-size: 16px; font-weight: 700; }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; text-align: right; }}
    th {{ color: var(--muted); font-weight: 600; }}
    td:first-child, th:first-child {{ text-align: left; }}
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable:hover {{ background: rgba(255,255,255,0.03); }}
    .sort-indicator {{ margin-left: 6px; opacity: 0.8; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .ok {{ color: var(--good); font-weight: 700; }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    .bad {{ color: var(--bad); font-weight: 700; }}
    .scroll {{ max-height: 620px; overflow:auto; border: 1px solid var(--border); border-radius: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>Walk-Forward Validation: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          Symbol: <span class="tag">{data.get("symbol","")}</span>
          Timeframe: <span class="tag">{data.get("timeframe","")}</span>
          Range: <span class="tag">{data.get("from_date","")} - {data.get("to_date","")}</span>
          Generated: <span class="tag">{data.get("generated_at","")}</span>
        </div>
      </div>
      <div class="subtitle" style="max-width:560px">
        Notes: This module reuses one fixed parameter set. The key signal is OOS fold stability (not just one good year).
      </div>
    </div>

    <div class="card">
      <div class="kpi" id="kpis"></div>
    </div>

    <div class="card">
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; margin-bottom:10px">
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Min OOS PF</div>
          <input id="fMinPf" type="number" step="0.01" class="tag" style="background: transparent; width:140px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Min OOS ROI%</div>
          <input id="fMinRoi" type="number" step="0.1" class="tag" style="background: transparent; width:140px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Max OOS DD%</div>
          <input id="fMaxDd" type="number" step="0.1" class="tag" style="background: transparent; width:140px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Min OOS Trades</div>
          <input id="fMinTrades" type="number" step="1" class="tag" style="background: transparent; width:140px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Sort</div>
          <select id="sortSelect" class="tag" style="background: transparent;">
            <option value="oos_pf_desc">OOS PF ↓</option>
            <option value="oos_roi_desc">OOS ROI% ↓</option>
            <option value="oos_profit_desc">OOS Profit ↓</option>
            <option value="oos_dd_asc">OOS DD% ↑</option>
            <option value="fold_asc">Fold ↑</option>
            <option value="custom">Header Click</option>
          </select>
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">&nbsp;</div>
          <button id="resetFilters" class="tag" style="background: transparent; cursor:pointer">Reset</button>
        </div>
      </div>
      <div class="subtitle" id="tableStats"></div>
      <div id="table"></div>
    </div>
  </div>

  <script>
    const DATA = {safe};
    let SORT_COL = null;
    let SORT_DIR = -1;

    function num(x) {{
      const n = Number(x);
      return Number.isFinite(n) ? n : null;
    }}
    function numOrNullFromInput(id) {{
      const el = document.getElementById(id);
      if (!el) return null;
      const raw = String(el.value ?? '').trim();
      if (raw === '') return null;
      const n = Number(raw);
      return Number.isFinite(n) ? n : null;
    }}
    function fmt(x, digits=2) {{
      if (x === null || x === undefined || Number.isNaN(x)) return '-';
      const n = Number(x);
      return n.toLocaleString(undefined, {{ maximumFractionDigits: digits, minimumFractionDigits: digits }});
    }}
    function escapeHtml(s) {{
      return String(s)
        .replaceAll('&','&amp;')
        .replaceAll('<','&lt;')
        .replaceAll('>','&gt;')
        .replaceAll('\"','&quot;')
        .replaceAll(\"'\",'&#039;');
    }}

    function addKpis(items) {{
      const root = document.getElementById('kpis');
      root.innerHTML = '';
      for (const it of items) {{
        const div = document.createElement('div');
        div.className = 'item';
        const label = document.createElement('div');
        label.className = 'label';
        label.textContent = it.label;
        if (it.tip) label.title = it.tip;
        const value = document.createElement('div');
        value.className = 'value';
        value.textContent = it.value;
        div.appendChild(label);
        div.appendChild(value);
        root.appendChild(div);
      }}
    }}

    function rows() {{
      return (DATA.folds || []).map(f => {{
        const o = f.oos || {{}};
        const om = o.metrics || {{}};
        const i = f.is || null;
        const im = i?.metrics || null;
        return {{
          fold_index: f.fold_index,
          is_from: i?.from_date || null,
          is_to: i?.to_date || null,
          oos_from: o.from_date,
          oos_to: o.to_date,
          oos_pf: om.profit_factor ?? null,
          oos_roi: om.roi_pct ?? null,
          oos_profit: om.total_net_profit ?? null,
          oos_dd: om.max_drawdown_pct ?? null,
          oos_trades: om.total_trades ?? null,
          oos_hq: om.history_quality ?? null,
          is_pf: im?.profit_factor ?? null,
          is_roi: im?.roi_pct ?? null,
          is_dd: im?.max_drawdown_pct ?? null,
          is_trades: im?.total_trades ?? null,
          is_link: i?.report_rel || null,
          oos_link: o.report_rel || null,
          gates: f.gates || {{}},
        }};
      }});
    }}

    function applyFilters(list) {{
      const minPf = numOrNullFromInput('fMinPf');
      const minRoi = numOrNullFromInput('fMinRoi');
      const maxDd = numOrNullFromInput('fMaxDd');
      const minTrades = numOrNullFromInput('fMinTrades');
      return list.filter(r => {{
        if (minPf !== null && num(r.oos_pf) !== null && r.oos_pf < minPf) return false;
        if (minRoi !== null && num(r.oos_roi) !== null && r.oos_roi < minRoi) return false;
        if (maxDd !== null && num(r.oos_dd) !== null && r.oos_dd > maxDd) return false;
        if (minTrades !== null && num(r.oos_trades) !== null && r.oos_trades < minTrades) return false;
        return true;
      }});
    }}

    function sortRows(list) {{
      const mode = document.getElementById('sortSelect')?.value || 'oos_pf_desc';
      if (mode === 'custom' && SORT_COL) {{
        const col = SORT_COL;
        const dir = SORT_DIR;
        return [...list].sort((a,b) => {{
          const av = a[col]; const bv = b[col];
          const an = num(av); const bn = num(bv);
          if (an !== null && bn !== null) return (an - bn) * dir;
          return String(av).localeCompare(String(bv)) * dir;
        }});
      }}

      const cmp = {{
        oos_pf_desc: (a,b) => (num(b.oos_pf)||-1e9) - (num(a.oos_pf)||-1e9),
        oos_roi_desc: (a,b) => (num(b.oos_roi)||-1e9) - (num(a.oos_roi)||-1e9),
        oos_profit_desc: (a,b) => (num(b.oos_profit)||-1e9) - (num(a.oos_profit)||-1e9),
        oos_dd_asc: (a,b) => (num(a.oos_dd)||1e9) - (num(b.oos_dd)||1e9),
        fold_asc: (a,b) => (a.fold_index||0) - (b.fold_index||0),
      }}[mode] || null;
      return cmp ? [...list].sort(cmp) : list;
    }}

    function th(colId, label, tip, sortable=true) {{
      const cls = sortable ? ' class=\"sortable\"' : '';
      const data = sortable ? ` data-col=\"${{colId}}\"` : '';
      const active = SORT_COL === colId;
      const arrow = active ? (SORT_DIR < 0 ? '↓' : '↑') : '';
      const indicator = sortable ? `<span class=\"sort-indicator\">${{arrow}}</span>` : '';
      const title = tip ? ` title=\"${{escapeHtml(tip)}}\"` : '';
      return `<th${{cls}}${{data}}${{title}}>${{label}}${{indicator}}</th>`;
    }}

    function renderTable(list) {{
      const cols = [
        {{ id:'fold_index', label:'#', tip:'Fold number (chronological order).', sortable:true }},
        {{ id:'oos_window', label:'OOS Window', tip:'Out-of-sample test window for this fold.', sortable:false }},
        {{ id:'oos_pf', label:'OOS PF', tip:'Profit Factor on the OOS window.', sortable:true }},
        {{ id:'oos_roi', label:'OOS ROI%', tip:'(OOS Net Profit / Initial Deposit) × 100.', sortable:true }},
        {{ id:'oos_profit', label:'OOS Profit', tip:'OOS Total Net Profit.', sortable:true }},
        {{ id:'oos_dd', label:'OOS DD%', tip:'OOS Max Drawdown percent.', sortable:true }},
        {{ id:'oos_trades', label:'OOS Trades', tip:'OOS total trades.', sortable:true }},
        {{ id:'is_pf', label:'IS PF', tip:'In-sample PF (context only; not used to pick params here).', sortable:true }},
        {{ id:'pf_13', label:'PF>=1.3', tip:'Soft PF gate (user request: 1.5 not a hard fail).', sortable:false }},
        {{ id:'pf_15', label:'PF>=1.5', tip:'Default PF gate from settings.py.', sortable:false }},
        {{ id:'links', label:'Reports', tip:'Open the MT5 HTML report for this fold.', sortable:false }},
      ];

      const header = `<tr>${{
        cols.map(c => {{
          if (c.id === 'oos_window') return `<th title=\"${{escapeHtml(c.tip)}}\">${{c.label}}</th>`;
          if (!c.sortable) return `<th title=\"${{escapeHtml(c.tip)}}\">${{c.label}}</th>`;
          return th(c.id, c.label, c.tip, true);
        }}).join('')
      }}</tr>`;

      const body = list.map(r => {{
        const oos_window = `${{r.oos_from}} - ${{r.oos_to}}`;
        const g13 = r.gates?.oos_pf_ge_1_3 ? 'YES' : 'NO';
        const g15 = r.gates?.oos_pf_ge_1_5 ? 'YES' : 'NO';
        const g13cls = r.gates?.oos_pf_ge_1_3 ? 'ok' : 'bad';
        const g15cls = r.gates?.oos_pf_ge_1_5 ? 'ok' : 'warn';
        const links = [
          r.is_link ? `<a href=\"${{escapeHtml(r.is_link)}}\">IS</a>` : null,
          r.oos_link ? `<a href=\"${{escapeHtml(r.oos_link)}}\">OOS</a>` : null,
        ].filter(Boolean).join(' | ');
        return `<tr>
          <td style="text-align:left">${{r.fold_index}}</td>
          <td style="text-align:left">${{escapeHtml(oos_window)}}</td>
          <td>${{fmt(r.oos_pf,2)}}</td>
          <td>${{fmt(r.oos_roi,2)}}</td>
          <td>${{fmt(r.oos_profit,2)}}</td>
          <td>${{fmt(r.oos_dd,2)}}</td>
          <td>${{fmt(r.oos_trades,0)}}</td>
          <td>${{fmt(r.is_pf,2)}}</td>
          <td class="${{g13cls}}">${{g13}}</td>
          <td class="${{g15cls}}">${{g15}}</td>
          <td style="text-align:left">${{links || '-'}}</td>
        </tr>`;
      }}).join('');

      document.getElementById('table').innerHTML = `
        <div class="scroll">
          <table>
            <thead>${{header}}</thead>
            <tbody>${{body}}</tbody>
          </table>
        </div>
      `;

      document.querySelectorAll('th.sortable').forEach(el => {{
        el.addEventListener('click', () => {{
          const col = el.getAttribute('data-col');
          if (!col) return;
          if (SORT_COL === col) SORT_DIR = -SORT_DIR;
          else {{ SORT_COL = col; SORT_DIR = -1; }}
          document.getElementById('sortSelect').value = 'custom';
          render();
        }});
      }});
    }}

    function render() {{
      const all = rows();
      const filtered = applyFilters(all);
      const sorted = sortRows(filtered);
      document.getElementById('tableStats').textContent = `Showing ${{sorted.length}} / ${{all.length}} folds`;
      renderTable(sorted);
    }}

    function init() {{
      const s = DATA.summary || {{}};
      addKpis([
        {{ label:'Folds (OOS)', value: String(s.folds_total ?? '-'), tip:'Number of OOS folds executed.' }},
        {{ label:'OOS Pass (PF>=1.5)', value: `${{s.oos_pass_pf_15 ?? '-'}} / ${{s.folds_total ?? '-'}}`, tip:'Count of folds meeting PF>=1.5.' }},
        {{ label:'Median OOS PF', value: fmt(s.oos_pf_median,2), tip:'Median OOS Profit Factor across folds.' }},
        {{ label:'Worst OOS PF', value: fmt(s.oos_pf_worst,2), tip:'Worst OOS Profit Factor across folds.' }},
        {{ label:'Median OOS ROI%', value: fmt(s.oos_roi_median,2), tip:'Median OOS ROI% across folds.' }},
        {{ label:'Worst OOS ROI%', value: fmt(s.oos_roi_worst,2), tip:'Worst OOS ROI% across folds.' }},
      ]);

      document.getElementById('resetFilters').addEventListener('click', () => {{
        document.getElementById('fMinPf').value = '';
        document.getElementById('fMinRoi').value = '';
        document.getElementById('fMaxDd').value = '';
        document.getElementById('fMinTrades').value = '';
        document.getElementById('sortSelect').value = 'oos_pf_desc';
        SORT_COL = null; SORT_DIR = -1;
        render();
      }});

      ['fMinPf','fMinRoi','fMaxDd','fMinTrades','sortSelect'].forEach(id => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', render);
        el.addEventListener('change', render);
      }});

      render();
    }}

    init();
  </script>
</body>
</html>
"""


def _median(xs: List[float]) -> Optional[float]:
    xs2 = [float(x) for x in xs if x is not None]
    if not xs2:
        return None
    xs2.sort()
    n = len(xs2)
    mid = n // 2
    if n % 2 == 1:
        return xs2[mid]
    return (xs2[mid - 1] + xs2[mid]) / 2.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Run multi-fold walk-forward validation and generate an offline report")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses latest workflow state in runs/)")
    ap.add_argument("--symbol", type=str, help="Symbol (default: from state or config)")
    ap.add_argument("--timeframe", type=str, help="Timeframe (default: from state or config)")
    ap.add_argument("--from-date", dest="from_date", type=str, help="From date YYYY.MM.DD")
    ap.add_argument("--to-date", dest="to_date", type=str, help="To date YYYY.MM.DD")
    ap.add_argument("--min-is-months", type=int, default=12, help="Minimum in-sample months before first OOS fold")
    ap.add_argument("--fold-months", type=int, default=12, help="OOS fold length in months")
    ap.add_argument("--step-months", type=int, default=12, help="Step size between folds (months)")
    ap.add_argument("--max-folds", type=int, default=12, help="Maximum folds to run")
    ap.add_argument("--oos-only", action="store_true", help="Skip IS runs (faster)")
    ap.add_argument("--timeout", type=int, default=900, help="Timeout per backtest run in seconds")
    ap.add_argument("--params", type=str, help="EA parameters JSON file path or inline JSON string")
    ap.add_argument("--out", type=str, help="Output directory (default: runs/walk_forward/{EA}_YYYYMMDD_HHMMSS)")
    ap.add_argument("--open", action="store_true", help="Open the HTML report in your browser")
    args = ap.parse_args()

    state_path: Optional[Path] = Path(args.state) if args.state else None
    if state_path and not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")

    if not state_path:
        if not args.ea:
            raise SystemExit("Provide --state or --ea")
        state_path = _find_latest_workflow_state(args.ea)
        if not state_path:
            raise SystemExit(f"No workflow state found for EA: {args.ea}")

    state = _load_state(state_path)
    ea_name = state.get("ea_name") or args.ea
    if not ea_name:
        raise SystemExit("Could not determine ea_name from state")

    symbol = args.symbol or state.get("symbol") or DEFAULT_SYMBOL
    timeframe = args.timeframe or state.get("timeframe") or DEFAULT_TIMEFRAME
    from_date = args.from_date or BACKTEST_FROM
    to_date = args.to_date or BACKTEST_TO

    # Parameters
    inputs: Optional[Dict[str, Any]] = None
    if args.params:
        inputs = load_params(args.params)
    else:
        inputs = _pick_params_from_state(state)
        if inputs is None:
            fallback = RUNS_DIR / f"{ea_name}_best_params.json"
            if fallback.exists():
                inputs = load_params(str(fallback))

    if not inputs:
        raise SystemExit("Could not load best parameters (provide --params or ensure workflow has 8_parse_results.params_file)")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (RUNS_DIR / "walk_forward" / f"{ea_name}_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    post_id = start_post_step(
        state_path,
        "walk_forward",
        meta={
            "out_dir": str(out_dir),
            "symbol": symbol,
            "timeframe": timeframe,
            "from_date": from_date,
            "to_date": to_date,
            "min_is_months": int(args.min_is_months),
            "fold_months": int(args.fold_months),
            "step_months": int(args.step_months),
            "oos_only": bool(args.oos_only),
        },
    )

    try:
        tester = WalkForwardTester(
            fold_months=int(args.fold_months),
            step_months=int(args.step_months),
            min_is_months=int(args.min_is_months),
            include_is=(not args.oos_only),
            max_folds=int(args.max_folds),
            timeout_per_run=int(args.timeout),
            run_dir=out_dir / "backtests",
            inputs=inputs,
        )

        res = tester.test(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
        )

        settings = get_settings()
        min_pf = float(settings.thresholds.min_profit_factor)

        folds: List[Dict[str, Any]] = []
        oos_pfs: List[float] = []
        oos_rois: List[float] = []
        oos_pass_pf_15 = 0

        for f in res.folds:
            d = f.to_dict()

            # Relativize reports
            for side in ["is", "oos"]:
                pr = d.get(side)
                if not isinstance(pr, dict):
                    continue
                rp = pr.get("report_path")
                if rp:
                    try:
                        pr["report_rel"] = Path(rp).relative_to(out_dir).as_posix()
                    except Exception:
                        pr["report_rel"] = rp

            oos = d.get("oos") or {}
            om = oos.get("metrics") or {}
            pf = float(om.get("profit_factor") or 0.0)
            roi = float(om.get("roi_pct") or 0.0)
            oos_pfs.append(pf)
            oos_rois.append(roi)

            gates = {
                "oos_pf_ge_1_3": pf >= 1.3,
                "oos_pf_ge_1_5": pf >= min_pf,
            }
            if gates["oos_pf_ge_1_5"]:
                oos_pass_pf_15 += 1
            d["gates"] = gates
            folds.append(d)

        summary = {
            "folds_total": len(folds),
            "oos_pass_pf_15": oos_pass_pf_15,
            "oos_pf_median": _median(oos_pfs),
            "oos_pf_worst": min(oos_pfs) if oos_pfs else None,
            "oos_roi_median": _median(oos_rois),
            "oos_roi_worst": min(oos_rois) if oos_rois else None,
        }

        data = {
            "ea_name": ea_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "from_date": from_date,
            "to_date": to_date,
            "generated_at": ts,
            "config": {
                "min_is_months": int(args.min_is_months),
                "fold_months": int(args.fold_months),
                "step_months": int(args.step_months),
                "max_folds": int(args.max_folds),
                "oos_only": bool(args.oos_only),
            },
            "thresholds": {
                "min_profit_factor": min_pf,
                "soft_profit_factor": 1.3,
            },
            "summary": summary,
            "folds": folds,
            "total_duration_seconds": res.total_duration_seconds,
        }

        (out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        index_path = out_dir / "index.html"
        index_path.write_text(_render_html(data), encoding="utf-8")

        complete_post_step(
            state_path,
            post_id,
            output={"out_dir": str(out_dir), "index": str(index_path), "data_json": str((out_dir / "data.json"))},
        )

        if args.open:
            import subprocess

            try:
                subprocess.Popen(["cmd", "/c", "start", str(index_path.resolve())], shell=False)
            except Exception:
                pass

        print(
            json.dumps(
                {
                    "success": True,
                    "ea_name": ea_name,
                    "state_file": str(state_path),
                    "out_dir": str(out_dir),
                    "index": str(index_path),
                },
                indent=2,
            )
        )

    except Exception as e:
        fail_post_step(state_path, post_id, error=str(e), output={"out_dir": str(out_dir)})
        raise


if __name__ == "__main__":
    main()

