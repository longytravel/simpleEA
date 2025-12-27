#!/usr/bin/env python3
"""
Run an Execution Stress Suite on an existing backtest report (offline).

This is an OPTIONAL module (post-Step-11).
It does not re-run MT5; it re-scores the extracted Deals table under different
spread/slippage/cost assumptions to see sensitivity.

Usage:
  python scripts/run_execution_stress.py --state runs/workflow_EA_*.json --open
  python scripts/run_execution_stress.py --report runs/backtests/.../EA_BT_....htm
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEFAULT_SYMBOL, RUNS_DIR
from parser.report import ReportParser
from parser.trade_extractor import extract_trades
from settings import get_settings
from tester.execution_stress import StressScenario, infer_pip_value_per_lot, score_scenario
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


def _read_report_text(report_path: Path) -> str:
    # MT5 reports are often UTF-16, but can be UTF-8.
    try:
        return report_path.read_text(encoding="utf-16", errors="ignore")
    except Exception:
        return report_path.read_text(encoding="utf-8", errors="ignore")


def _infer_baseline_spread_pips(report_path: Path, symbol: str) -> Optional[float]:
    """
    Infer a plausible baseline spread (pips) from the report Inputs section.

    Priority:
      1) EAStressSafety_MaxSpreadPips (if injected)
      2) Max_Spread_{SYMBOL} / Max_Spread_Default (common EA naming)
      3) MaxSpread / MaxSpreadPips / SpreadLimit / etc (heuristic)
    """
    txt = _read_report_text(report_path)
    sym = (symbol or "").upper()

    patterns = [
        r"\bEAStressSafety_MaxSpreadPips\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        rf"\bMax_Spread_{re.escape(sym)}\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\bMax_Spread_Default\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\bMaxSpreadPips\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\bMaxSpread\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\bSpreadLimitPips\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
        r"\bSpreadLimit\s*=\s*([0-9]+(?:\.[0-9]+)?)\b",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except Exception:
            continue
        if v > 0:
            return v
    return None


def _render_html(data: Dict[str, Any]) -> str:
    safe = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Execution Stress Suite - {data.get("ea_name","")}</title>
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
    .ok {{ color: var(--good); font-weight: 700; }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    .bad {{ color: var(--bad); font-weight: 700; }}
    .scroll {{ max-height: 580px; overflow:auto; border: 1px solid var(--border); border-radius: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>Execution Stress Suite: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          Symbol: <span class="tag">{data.get("symbol","")}</span>
          Report: <span class="tag">{Path(str(data.get("source_report",""))).name}</span>
          Generated: <span class="tag">{data.get("generated_at","")}</span>
        </div>
      </div>
      <div class="subtitle" style="max-width:560px">
        This is an offline re-score. Spread uses an assumed baseline (pips) and applies a multiplier; slippage is per-side (entry+exit).
      </div>
    </div>

    <div class="card">
      <div class="kpi" id="kpis"></div>
    </div>

    <div class="card">
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; margin-bottom:10px">
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Min PF</div>
          <input id="fMinPf" type="number" step="0.01" class="tag" style="background: transparent; width:120px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Min ROI%</div>
          <input id="fMinRoi" type="number" step="0.1" class="tag" style="background: transparent; width:120px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Max DD%</div>
          <input id="fMaxDd" type="number" step="0.1" class="tag" style="background: transparent; width:120px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Sort</div>
          <select id="sortSelect" class="tag" style="background: transparent;">
            <option value="pf_desc">PF ↓</option>
            <option value="roi_desc">ROI% ↓</option>
            <option value="profit_desc">Net Profit ↓</option>
            <option value="dd_asc">DD% ↑</option>
            <option value="cost_asc">Stress Cost ↑</option>
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

    function kpi(label, value, tip) {{
      return {{ label, value, tip }};
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
      return (DATA.scenarios || []).map(r => {{
        const m = r.metrics || {{}};
        const c = r.costs || {{}};
        return {{
          id: r.scenario?.id || r.id || '',
          label: r.scenario?.label || r.label || '',
          spread_mult: r.scenario?.spread_mult ?? 1.0,
          slippage_pips: r.scenario?.slippage_pips ?? 0.0,
          commission_mult: r.scenario?.commission_mult ?? 1.0,
          roi_pct: m.roi_pct ?? null,
          profit_factor: m.profit_factor ?? null,
          total_net_profit: m.total_net_profit ?? null,
          max_drawdown_pct: m.max_drawdown_pct ?? null,
          stress_cost: (c.extra_spread_cost||0) + (c.extra_slippage_cost||0) + (c.extra_commission_cost||0) + (c.extra_swap_cost||0),
          c: c,
          delta: r.delta || {{}},
          gates: r.gates || {{}},
        }};
      }});
    }}

    function applyFilters(list) {{
      const minPf = numOrNullFromInput('fMinPf');
      const minRoi = numOrNullFromInput('fMinRoi');
      const maxDd = numOrNullFromInput('fMaxDd');
      return list.filter(r => {{
        if (minPf !== null && num(r.profit_factor) !== null && r.profit_factor < minPf) return false;
        if (minRoi !== null && num(r.roi_pct) !== null && r.roi_pct < minRoi) return false;
        if (maxDd !== null && num(r.max_drawdown_pct) !== null && r.max_drawdown_pct > maxDd) return false;
        return true;
      }});
    }}

    function sortRows(list) {{
      const mode = document.getElementById('sortSelect')?.value || 'pf_desc';
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
        pf_desc: (a,b) => (num(b.profit_factor)||-1e9) - (num(a.profit_factor)||-1e9),
        roi_desc: (a,b) => (num(b.roi_pct)||-1e9) - (num(a.roi_pct)||-1e9),
        profit_desc: (a,b) => (num(b.total_net_profit)||-1e9) - (num(a.total_net_profit)||-1e9),
        dd_asc: (a,b) => (num(a.max_drawdown_pct)||1e9) - (num(b.max_drawdown_pct)||1e9),
        cost_asc: (a,b) => (num(a.stress_cost)||1e9) - (num(b.stress_cost)||1e9),
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
        {{ id:'label', label:'Scenario', tip:'Stress scenario label and assumptions.', align:'left' }},
        {{ id:'profit_factor', label:'PF', tip:'Profit Factor under this scenario.' }},
        {{ id:'roi_pct', label:'ROI%', tip:'(Net Profit / Initial Deposit) × 100.' }},
        {{ id:'total_net_profit', label:'Net Profit', tip:'Total net profit under this scenario.' }},
        {{ id:'max_drawdown_pct', label:'Max DD%', tip:'Max drawdown percentage under this scenario.' }},
        {{ id:'stress_cost', label:'Stress Cost', tip:'Total additional modeled cost vs baseline.' }},
        {{ id:'g_pf_13', label:'PF≥1.3', tip:'Soft gate (user request: 1.5 not a hard fail).' }},
        {{ id:'g_pf_15', label:'PF≥1.5', tip:'Default gate from settings.py.' }},
      ];

      const header = `<tr>${{
        cols.map(c => th(c.id, c.label, c.tip, !['g_pf_13','g_pf_15'].includes(c.id))).join('')
      }}</tr>`;

      const body = list.map(r => {{
        const g13 = r.gates?.pf_ge_1_3 ? 'YES' : 'NO';
        const g15 = r.gates?.pf_ge_1_5 ? 'YES' : 'NO';
        const g13cls = r.gates?.pf_ge_1_3 ? 'ok' : 'bad';
        const g15cls = r.gates?.pf_ge_1_5 ? 'ok' : 'warn';
        return `<tr>
          <td style="text-align:left">${{escapeHtml(r.label)}}</td>
          <td>${{fmt(r.profit_factor, 2)}}</td>
          <td>${{fmt(r.roi_pct, 2)}}</td>
          <td>${{fmt(r.total_net_profit, 2)}}</td>
          <td>${{fmt(r.max_drawdown_pct, 2)}}</td>
          <td>${{fmt(r.stress_cost, 2)}}</td>
          <td class="${{g13cls}}">${{g13}}</td>
          <td class="${{g15cls}}">${{g15}}</td>
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
      const stats = document.getElementById('tableStats');
      stats.textContent = `Showing ${{sorted.length}} / ${{all.length}} scenarios`;
      renderTable(sorted);
    }}

    function init() {{
      const base = DATA.baseline || {{}};
      const bm = base.metrics || {{}};
      const q = DATA.quality || {{}};
      const a = DATA.assumptions || {{}};
      addKpis([
        kpi('Baseline PF', fmt(bm.profit_factor,2), 'Profit factor from the original backtest (no extra stress).'),
        kpi('Baseline ROI%', fmt(bm.roi_pct,2), 'ROI% from the original backtest.'),
        kpi('Baseline DD%', fmt(bm.max_drawdown_pct,2), 'Max DD% from the original backtest.'),
        kpi('Assumed Baseline Spread (pips)', fmt(a.baseline_spread_pips,2), 'Used for spread multipliers in this stress suite.'),
        kpi('History Quality', String(q.history_quality ?? '-'), 'From MT5 report (history quality).'),
        kpi('Bars / Ticks', `${{q.bars ?? '-'}} / ${{q.ticks ?? '-'}}`, 'From MT5 report (bars and ticks).'),
      ]);

      document.getElementById('resetFilters').addEventListener('click', () => {{
        document.getElementById('fMinPf').value = '';
        document.getElementById('fMinRoi').value = '';
        document.getElementById('fMaxDd').value = '';
        document.getElementById('sortSelect').value = 'pf_desc';
        SORT_COL = null; SORT_DIR = -1;
        render();
      }});

      ['fMinPf','fMinRoi','fMaxDd','sortSelect'].forEach(id => {{
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Run an execution stress suite on an existing backtest report (offline)")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses latest workflow state in runs/)")
    ap.add_argument("--report", type=str, help="Path to an MT5 HTML report (htm/html) to stress")
    ap.add_argument("--symbol", type=str, help="Symbol (default: from state or report assumptions)")
    ap.add_argument("--baseline-spread-pips", type=float, help="Override inferred baseline spread (pips)")
    ap.add_argument("--out", type=str, help="Output directory (default: runs/stress/{EA}_YYYYMMDD_HHMMSS)")
    ap.add_argument("--open", action="store_true", help="Open the HTML report in your browser")
    args = ap.parse_args()

    state_path: Optional[Path] = Path(args.state) if args.state else None
    if state_path and not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")

    state: Optional[Dict[str, Any]] = None
    if state_path:
        state = _load_state(state_path)
    elif args.ea:
        state_path = _find_latest_workflow_state(args.ea)
        if state_path:
            state = _load_state(state_path)

    ea_name = (state or {}).get("ea_name") or args.ea
    if not ea_name:
        raise SystemExit("Provide --state or --ea (or specify --report with --ea for output naming)")

    symbol = args.symbol or (state or {}).get("symbol") or DEFAULT_SYMBOL

    report_path: Optional[Path] = _resolve_path(args.report) if args.report else None
    if not report_path and state:
        steps = state.get("steps", {}) or {}
        step9 = (steps.get("9_backtest_robust") or {}).get("output", {}) if steps.get("9_backtest_robust") else {}
        step11 = (steps.get("11_report") or {}).get("output", {}) if steps.get("11_report") else {}
        for cand in [step9.get("report_path"), step11.get("backtest_report")]:
            p = _resolve_path(str(cand)) if cand else None
            if p and p.exists():
                report_path = p
                break

    if not report_path or not report_path.exists():
        raise SystemExit("Could not find backtest report. Provide --report or ensure workflow has Step 9 report_path.")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (RUNS_DIR / "stress" / f"{ea_name}_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    post_id = start_post_step(state_path, "execution_stress", meta={"out_dir": str(out_dir), "source_report": str(report_path)})

    try:
        extraction = extract_trades(str(report_path))
        if not extraction.success:
            raise RuntimeError(extraction.error or "Failed to extract trades")
        trades = extraction.trades or []
        if not trades:
            raise RuntimeError("No trades in report (cannot run stress)")

        rp = ReportParser()
        metrics = rp.parse(report_path)

        settings = get_settings()
        min_pf = float(settings.thresholds.min_profit_factor)

        inferred_spread = args.baseline_spread_pips
        if inferred_spread is None:
            inferred_spread = _infer_baseline_spread_pips(report_path, symbol)
        if inferred_spread is None:
            inferred_spread = 2.0 if symbol.upper().endswith("JPY") else 1.0

        pv = infer_pip_value_per_lot(trades)

        scenarios: List[StressScenario] = [
            StressScenario(id="baseline", label="Baseline (no extra stress)"),
            StressScenario(id="spread_1_5x", label=f"Spread x1.5 (baseline {inferred_spread:.2f} pips)", spread_mult=1.5),
            StressScenario(id="spread_2x", label=f"Spread x2.0 (baseline {inferred_spread:.2f} pips)", spread_mult=2.0),
            StressScenario(id="slip_0_10", label="Slippage 0.10 pips/side", slippage_pips=0.10),
            StressScenario(id="slip_0_20", label="Slippage 0.20 pips/side", slippage_pips=0.20),
            StressScenario(id="comm_1_5x", label="Commission x1.5", commission_mult=1.5),
            StressScenario(id="comm_2x", label="Commission x2.0", commission_mult=2.0),
            StressScenario(
                id="combo_mid",
                label="Combo: Spread x1.5 + Slippage 0.10 + Comm x1.5",
                spread_mult=1.5,
                slippage_pips=0.10,
                commission_mult=1.5,
            ),
            StressScenario(
                id="combo_worst",
                label="Combo: Spread x2.0 + Slippage 0.20 + Comm x2.0",
                spread_mult=2.0,
                slippage_pips=0.20,
                commission_mult=2.0,
            ),
        ]

        results: List[Dict[str, Any]] = []
        baseline: Optional[Dict[str, Any]] = None
        for sc in scenarios:
            res = score_scenario(
                trades,
                initial_balance=float(extraction.initial_balance or 0.0),
                baseline_spread_pips=float(inferred_spread),
                pip_value_per_lot=pv,
                scenario=sc,
            )
            if not res.get("success"):
                results.append(res)
                continue
            if sc.id == "baseline":
                baseline = res
            results.append(res)

        if not baseline or not baseline.get("metrics"):
            raise RuntimeError("Baseline scoring failed")

        b = baseline["metrics"]
        for r in results:
            if not r.get("success") or "metrics" not in r:
                continue
            m = r["metrics"]
            r["delta"] = {
                "profit": float(m.get("total_net_profit", 0.0)) - float(b.get("total_net_profit", 0.0)),
                "roi_pct": float(m.get("roi_pct", 0.0)) - float(b.get("roi_pct", 0.0)),
                "profit_factor": float(m.get("profit_factor", 0.0)) - float(b.get("profit_factor", 0.0)),
                "max_drawdown_pct": float(m.get("max_drawdown_pct", 0.0)) - float(b.get("max_drawdown_pct", 0.0)),
            }
            pf = float(m.get("profit_factor") or 0.0)
            r["gates"] = {
                "pf_ge_1_3": pf >= 1.3,
                "pf_ge_1_5": pf >= min_pf,
            }

        data = {
            "ea_name": ea_name,
            "symbol": symbol,
            "generated_at": ts,
            "source_report": str(report_path),
            "assumptions": {
                "baseline_spread_pips": float(inferred_spread),
                "notes": "Spread multiplier uses an assumed baseline spread in pips; slippage is modeled as always adverse (cost).",
            },
            "thresholds": {
                "min_profit_factor": min_pf,
                "soft_profit_factor": 1.3,
            },
            "quality": {
                "history_quality": getattr(metrics, "history_quality", None) if metrics else None,
                "bars": getattr(metrics, "bars", None) if metrics else None,
                "ticks": getattr(metrics, "ticks", None) if metrics else None,
            },
            "baseline": baseline,
            "scenarios": results,
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
                    "state_file": str(state_path) if state_path else None,
                    "source_report": str(report_path),
                    "out_dir": str(out_dir),
                    "index": str(index_path),
                },
                indent=2,
            )
        )

    except Exception as e:
        fail_post_step(state_path, post_id, error=str(e), output={"out_dir": str(out_dir), "source_report": str(report_path)})
        raise


if __name__ == "__main__":
    main()

