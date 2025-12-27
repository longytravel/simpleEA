#!/usr/bin/env python3
"""
Generate an offline HTML dashboard for a stress-test run.

The dashboard is designed to feel closer to MT5's reporting:
- Links to the full MT5 HTML report (with chart images)
- Final backtest summary metrics
- In-sample vs forward optimization summary + ranges
- Monte Carlo robustness summary (net-of-costs)

Usage:
  python scripts/generate_dashboard.py --state runs/workflow_EA_*.json
  python scripts/generate_dashboard.py --ea Auction_Theory_Safe
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BACKTEST_FROM, BACKTEST_TO, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, MT5_DATA_PATH, RUNS_DIR
from optimizer.result_parser import OptimizationResultParser
from parser.report import ReportParser
from parser.trade_extractor import extract_trades
from settings import get_settings
from tester.backtest import BacktestRunner
from tester.montecarlo import MonteCarloSimulator


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return float(sorted_vals[0])
    if p >= 100:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return float(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


def _find_latest_workflow_state(ea_name: str) -> Optional[Path]:
    candidates = sorted(RUNS_DIR.glob(f"workflow_{ea_name}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _resolve_path(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return p
    # Try project-relative
    proj = Path(__file__).parent.parent
    cand = proj / path_str
    if cand.exists():
        return cand
    # Try MT5 terminal data folder-relative
    cand = MT5_DATA_PATH / path_str
    if cand.exists():
        return cand
    return None


def _parse_date_pair(s: str) -> Optional[Tuple[str, str]]:
    if not s:
        return None
    m = re.search(r"(\d{4}\.\d{2}\.\d{2}).*?(\d{4}\.\d{2}\.\d{2})", s)
    if not m:
        return None
    return m.group(1), m.group(2)


def _compute_equity_curve(trades: List[Dict[str, Any]], initial_balance: float) -> List[float]:
    trades_sorted = sorted(trades, key=lambda t: t.get("time", ""))
    equity = float(initial_balance or 0.0)
    curve: List[float] = []
    for t in trades_sorted:
        equity += float(t.get("net_profit", 0.0))
        curve.append(equity)
    return curve


def _compute_drawdown(equity_curve: List[float], initial_balance: float) -> Tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0
    peak = float(initial_balance or 0.0)
    max_dd = 0.0
    max_dd_pct = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
    return max_dd, max_dd_pct


def _compute_trade_stats(trades: List[Dict[str, Any]], initial_balance: float) -> Dict[str, Any]:
    profits = [float(t.get("net_profit", 0.0)) for t in trades]
    trade_count = len(profits)
    net_profit = float(sum(profits))
    gross_profit = float(sum(p for p in profits if p > 0))
    gross_loss = float(sum(p for p in profits if p < 0))  # negative
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0.0)
    winners = sum(1 for p in profits if p > 0)
    losers = sum(1 for p in profits if p < 0)
    win_rate = (winners / trade_count) * 100.0 if trade_count else 0.0
    expected_payoff = (net_profit / trade_count) if trade_count else 0.0

    equity_curve = _compute_equity_curve(trades, initial_balance)
    max_dd, max_dd_pct = _compute_drawdown(equity_curve, initial_balance)
    recovery_factor = (net_profit / max_dd) if max_dd > 0 else 0.0

    return {
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "total_trades": trade_count,
        "winning_trades": winners,
        "losing_trades": losers,
        "win_rate": win_rate,
        "expected_payoff": expected_payoff,
        "recovery_factor": recovery_factor,
    }


def _split_trades_by_forward_date(trades: List[Dict[str, Any]], forward_date: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    split_ts = f"{forward_date} 00:00:00"
    in_sample: List[Dict[str, Any]] = []
    forward: List[Dict[str, Any]] = []
    for t in sorted(trades, key=lambda x: x.get("time", "")):
        if (t.get("time", "") or "") < split_ts:
            in_sample.append(t)
        else:
            forward.append(t)
    return in_sample, forward


def _load_state(state_path: Path) -> Dict[str, Any]:
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_artifacts_from_state(state: Dict[str, Any]) -> Dict[str, Optional[Path]]:
    steps = state.get("steps", {}) or {}

    report_path = None
    step9 = steps.get("9_backtest_robust", {}).get("output", {}) if steps.get("9_backtest_robust") else {}
    if isinstance(step9, dict):
        report_path = _resolve_path(step9.get("report_path", "")) if step9.get("report_path") else None

    step7 = steps.get("7_run_optimization", {}).get("output", {}) if steps.get("7_run_optimization") else {}
    insample_xml = _resolve_path(step7.get("in_sample_xml", "")) if isinstance(step7, dict) else None
    forward_xml = _resolve_path(step7.get("forward_xml", "")) if isinstance(step7, dict) else None

    best_params = None
    step8 = steps.get("8_parse_results", {}).get("output", {}) if steps.get("8_parse_results") else {}
    if isinstance(step8, dict) and step8.get("params_file"):
        best_params = _resolve_path(step8.get("params_file"))

    return {
        "backtest_report": report_path,
        "opt_insample_xml": insample_xml,
        "opt_forward_xml": forward_xml,
        "best_params": best_params,
    }


def _find_optimization_xml_fallback(ea_name: str) -> Tuple[Optional[Path], Optional[Path]]:
    # Prefer project runs/
    insample = RUNS_DIR / f"{ea_name}_OPT.xml"
    forward = RUNS_DIR / f"{ea_name}_OPT.forward.xml"
    if insample.exists() and forward.exists():
        return insample, forward

    # Fall back to MT5 terminal data folder
    insample = MT5_DATA_PATH / f"{ea_name}_OPT.xml"
    forward = MT5_DATA_PATH / f"{ea_name}_OPT.forward.xml"
    if insample.exists() and forward.exists():
        return insample, forward

    return None, None


def _find_backtest_report_fallback(ea_name: str) -> Optional[Path]:
    # Prefer the new backtests output folder if present
    bt_dirs = sorted((RUNS_DIR / "backtests").glob(f"{ea_name}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for d in bt_dirs:
        for ext in (".htm", ".html"):
            candidates = sorted(d.glob(f"{ea_name}_BT_*{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0]

    # Fall back to MT5 output
    for ext in (".htm", ".html"):
        p = MT5_DATA_PATH / f"{ea_name}_BT{ext}"
        if p.exists():
            return p

    return None


def _copy_report_with_assets(report_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / report_path.name
    shutil.copy2(report_path, dst)

    assets = report_path.with_name(report_path.stem + "_files")
    if assets.exists() and assets.is_dir():
        shutil.copytree(assets, dest_dir / assets.name, dirs_exist_ok=True)
    return dst


def _render_html(data: Dict[str, Any]) -> str:
    # Keep this offline + dependency-free (no external JS/CSS).
    safe = json.dumps(data).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EA Dashboard - {data.get("ea_name","")}</title>
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
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      background: radial-gradient(1200px 800px at 10% 0%, #17234a 0%, var(--bg) 40%, var(--bg) 100%);
      color: var(--text);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    .title {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.2px; }}
    .subtitle {{ color: var(--muted); font-size: 13px; }}
    .grid {{ display:grid; grid-template-columns: repeat(12, 1fr); gap: 14px; margin-top: 16px; }}
    .card {{
      background: rgba(18,26,51,0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.25);
    }}
    .card h2 {{ margin: 0 0 10px 0; font-size: 14px; color: var(--muted); font-weight: 600; }}
    .kpi {{ display:flex; gap:12px; flex-wrap: wrap; }}
    .kpi .item {{ flex: 1 1 140px; padding: 10px; border: 1px solid var(--border); border-radius: 12px; background: rgba(255,255,255,0.02); }}
    .kpi .label {{ font-size: 12px; color: var(--muted); }}
    .kpi .value {{ margin-top: 4px; font-size: 16px; font-weight: 700; }}
    .tag {{ display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); color: var(--muted); }}
    .tag.good {{ color: var(--good); border-color: rgba(61,220,151,0.4); }}
    .tag.warn {{ color: var(--warn); border-color: rgba(255,204,102,0.4); }}
    .tag.bad {{ color: var(--bad); border-color: rgba(255,107,107,0.4); }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; text-align: right; }}
    th {{ color: var(--muted); font-weight: 600; }}
    td:first-child, th:first-child {{ text-align: left; }}
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable:hover {{ background: rgba(255,255,255,0.03); }}
    .sort-indicator {{ margin-left: 6px; opacity: 0.8; }}
    tr.clickable {{ cursor: pointer; }}
    tr.clickable:hover {{ background: rgba(255,255,255,0.03); }}
    tr.selected {{ background: rgba(106,166,255,0.10); }}
    .span-12 {{ grid-column: span 12; }}
    .span-8 {{ grid-column: span 8; }}
    .span-7 {{ grid-column: span 7; }}
    .span-6 {{ grid-column: span 6; }}
    .span-5 {{ grid-column: span 5; }}
    .span-4 {{ grid-column: span 4; }}
    .span-3 {{ grid-column: span 3; }}
    canvas {{ width: 100%; height: 280px; border: 1px solid var(--border); border-radius: 12px; background: rgba(0,0,0,0.15); }}
    .links {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }}
    .scroll {{ max-height: 320px; overflow:auto; border: 1px solid var(--border); border-radius: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>EA Dashboard: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          Symbol: <span class="tag">{data.get("symbol","")}</span>
          Timeframe: <span class="tag">{data.get("timeframe","")}</span>
          Split: <span class="tag">{data.get("forward_date","")}</span>
          Generated: <span class="tag">{data.get("generated_at","")}</span>
        </div>
      </div>
      <div class="links">
        <a class="tag" href="compare.html">Compare</a>
        <a class="tag" id="reportLink" href="#" style="display:none">Open MT5 HTML report</a>
      </div>
    </div>

    <div class="grid">
      <div class="card span-12">
        <h2>Selected Pass Summary</h2>
        <div class="kpi" id="kpis"></div>
        <div class="subtitle" style="margin-top:8px">
          Click a pass in the table to update the charts and Monte Carlo.
        </div>
      </div>

      <div class="card span-7">
        <h2>Equity Curve (In-sample vs Forward)</h2>
        <canvas id="equity"></canvas>
        <div class="subtitle" style="margin-top:8px">
          Uses net-of-costs per-trade P/L from the MT5 Deals table. Line color changes at the split date.
        </div>
      </div>

      <div class="card span-5">
        <h2>Selected Pass Details</h2>
        <div id="passDetails"></div>
      </div>

      <div class="card span-12">
        <h2>Optimization (In-sample vs Forward)</h2>
        <div class="kpi" id="optkpis"></div>
        <canvas id="scatter"></canvas>
        <div class="subtitle" style="margin-top:8px">
          Points show robust passes (profit &gt; 0 in-sample and forward). Hover tooltips are not implemented yet.
        </div>
      </div>

      <div class="card span-12">
        <h2>Top Robust Passes</h2>
        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; margin-bottom:10px">
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">View</div>
            <select id="viewSelect" class="tag" style="background: transparent;">
              <option value="all">All</option>
              <option value="bt">Backtest</option>
              <option value="opt">Optimization</option>
              <option value="risk">Risk</option>
              <option value="costs">Costs/Quality</option>
            </select>
          </div>

          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Min HRM</div>
            <input id="fMinHrm" type="number" step="0.01" class="tag" style="background: transparent; width:120px" />
          </div>
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Min ROI%</div>
            <input id="fMinRoi" type="number" step="0.1" class="tag" style="background: transparent; width:120px" />
          </div>
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Min PF</div>
            <input id="fMinPf" type="number" step="0.01" class="tag" style="background: transparent; width:120px" />
          </div>
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Max DD%</div>
            <input id="fMaxDd" type="number" step="0.1" class="tag" style="background: transparent; width:120px" />
          </div>
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Max Ruin%</div>
            <input id="fMaxRuin" type="number" step="0.1" class="tag" style="background: transparent; width:120px" />
          </div>
          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Min Trades</div>
            <input id="fMinTrades" type="number" step="1" class="tag" style="background: transparent; width:120px" />
          </div>

          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">Sort</div>
            <select id="sortSelect" class="tag" style="background: transparent;">
              <option value="hrm_desc">HRM ↓</option>
              <option value="net_profit_desc">Net Profit ↓</option>
              <option value="roi_desc">ROI% ↓</option>
              <option value="pf_desc">PF ↓</option>
              <option value="dd_asc">DD% ↑</option>
              <option value="ruin_asc">Ruin% ↑</option>
              <option value="custom">Header Click</option>
            </select>
          </div>

          <div style="display:flex; flex-direction:column; gap:4px">
            <div class="subtitle">&nbsp;</div>
            <button id="resetFilters" class="tag" style="background: transparent; cursor:pointer">Reset</button>
          </div>
        </div>
        <div class="subtitle" id="tableStats"></div>
        <div id="topTable"></div>
      </div>

      <div class="card span-12">
        <h2>Monte Carlo (Trade Shuffle)</h2>
        <div class="kpi" id="mckpis"></div>
      </div>
    </div>
  </div>

  <script>
    const DATA = {safe};

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

    function tagClass(status) {{
      if (status === 'good') return 'good';
      if (status === 'warn') return 'warn';
      if (status === 'bad') return 'bad';
      return '';
    }}

    function addKpis(targetId, items) {{
      const root = document.getElementById(targetId);
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
        if (it.tag) {{
          const t = document.createElement('span');
          t.className = 'tag ' + tagClass(it.tagClass);
          t.style.marginLeft = '8px';
          t.textContent = it.tag;
          value.appendChild(t);
        }}
        div.appendChild(label);
        div.appendChild(value);
        root.appendChild(div);
      }}
    }}

    function drawEquity(canvasId, inSeries, fwdSeries) {{
      const c = document.getElementById(canvasId);
      const ctx = c.getContext('2d');
      const w = c.width = c.clientWidth * devicePixelRatio;
      const h = c.height = c.clientHeight * devicePixelRatio;
      ctx.clearRect(0,0,w,h);

      const inS = (inSeries || []).map(Number);
      const fwdS = (fwdSeries || []).map(Number);
      const totalLen = inS.length + fwdS.length;

      if (totalLen < 2) {{
        ctx.fillStyle = 'rgba(168,179,207,0.9)';
        ctx.fillText('No equity data', 20, 30);
        return;
      }}

      const pad = 28 * devicePixelRatio;
      const ys = inS.concat(fwdS);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const spanY = (maxY - minY) || 1;

      function X(i) {{
        return pad + (i / (totalLen - 1)) * (w - 2*pad);
      }}
      function Y(v) {{
        return (h - pad) - ((v - minY) / spanY) * (h - 2*pad);
      }}

      // grid
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let g=0; g<=4; g++) {{
        const yy = pad + g*(h-2*pad)/4;
        ctx.beginPath();
        ctx.moveTo(pad, yy);
        ctx.lineTo(w-pad, yy);
        ctx.stroke();
      }}

      // in-sample segment
      if (inS.length >= 2) {{
        ctx.strokeStyle = 'rgba(106,166,255,0.95)';
        ctx.lineWidth = 2 * devicePixelRatio;
        ctx.beginPath();
        ctx.moveTo(X(0), Y(inS[0]));
        for (let i=1; i<inS.length; i++) {{
          ctx.lineTo(X(i), Y(inS[i]));
        }}
        ctx.stroke();
      }}

      // forward segment
      if (fwdS.length >= 1) {{
        const startIdx = Math.max(0, inS.length - 1);
        const firstY = (inS.length > 0) ? inS[inS.length - 1] : fwdS[0];
        ctx.strokeStyle = 'rgba(61,220,151,0.95)';
        ctx.lineWidth = 2 * devicePixelRatio;
        ctx.beginPath();
        ctx.moveTo(X(startIdx), Y(firstY));
        for (let i=0; i<fwdS.length; i++) {{
          ctx.lineTo(X(inS.length + i), Y(fwdS[i]));
        }}
        ctx.stroke();
      }}

      // split marker
      if (inS.length > 0 && fwdS.length > 0) {{
        ctx.strokeStyle = 'rgba(255,255,255,0.18)';
        ctx.setLineDash([6*devicePixelRatio, 6*devicePixelRatio]);
        ctx.beginPath();
        ctx.moveTo(X(inS.length - 1), pad);
        ctx.lineTo(X(inS.length - 1), h - pad);
        ctx.stroke();
        ctx.setLineDash([]);
      }}

      // labels
      ctx.fillStyle = 'rgba(168,179,207,0.9)';
      ctx.font = `${{12*devicePixelRatio}}px system-ui`;
      ctx.fillText(`Min: ${{fmt(minY,2)}}`, pad, pad - 8*devicePixelRatio);
      ctx.fillText(`Max: ${{fmt(maxY,2)}}`, pad + 160*devicePixelRatio, pad - 8*devicePixelRatio);
    }}

    function drawScatter(canvasId, points, highlight) {{
      const c = document.getElementById(canvasId);
      const ctx = c.getContext('2d');
      const w = c.width = c.clientWidth * devicePixelRatio;
      const h = c.height = c.clientHeight * devicePixelRatio;
      ctx.clearRect(0,0,w,h);

      const pad = 28 * devicePixelRatio;
      if (!points || points.length === 0) {{
        ctx.fillStyle = 'rgba(168,179,207,0.9)';
        ctx.fillText('No robust passes found', 20, 30);
        return;
      }}

      const xs = points.map(p => Number(p.x));
      const ys = points.map(p => Number(p.y));
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const spanX = (maxX - minX) || 1;
      const spanY = (maxY - minY) || 1;

      function X(v) {{
        return pad + ((v - minX) / spanX) * (w - 2*pad);
      }}
      function Y(v) {{
        return (h - pad) - ((v - minY) / spanY) * (h - 2*pad);
      }}

      // axes
      ctx.strokeStyle = 'rgba(255,255,255,0.14)';
      ctx.lineWidth = 1 * devicePixelRatio;
      ctx.beginPath();
      ctx.moveTo(pad, h-pad);
      ctx.lineTo(w-pad, h-pad);
      ctx.lineTo(w-pad, pad);
      ctx.stroke();

      // points
      ctx.fillStyle = 'rgba(106,166,255,0.65)';
      for (const p of points) {{
        const cx = X(p.x), cy = Y(p.y);
        ctx.beginPath();
        ctx.arc(cx, cy, 3*devicePixelRatio, 0, Math.PI*2);
        ctx.fill();
      }}

      // highlight selected pass
      if (highlight && highlight.x !== undefined && highlight.y !== undefined) {{
        ctx.strokeStyle = 'rgba(61,220,151,0.95)';
        ctx.lineWidth = 2 * devicePixelRatio;
        ctx.beginPath();
        ctx.arc(X(highlight.x), Y(highlight.y), 7*devicePixelRatio, 0, Math.PI*2);
        ctx.stroke();
      }}

      // labels
      ctx.fillStyle = 'rgba(168,179,207,0.9)';
      ctx.font = `${{12*devicePixelRatio}}px system-ui`;
      ctx.fillText('In-sample profit', pad, h - 8*devicePixelRatio);
      ctx.save();
      ctx.translate(10*devicePixelRatio, h/2);
      ctx.rotate(-Math.PI/2);
      ctx.fillText('Forward profit', 0, 0);
      ctx.restore();
    }}

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

    function computeRoiPct(bt) {{
      if (!bt) return null;
      const initial = num(bt.initial_balance ?? bt.initial_deposit ?? 0);
      const profit = num(bt.total_net_profit);
      if (!initial || initial <= 0 || profit === null) return null;
      return (profit / initial) * 100.0;
    }}

    function computeHrm(row) {{
      // HRM = composite robustness score (bigger = better)
      // Uses ROI%, PF, DD%, and MC ruin% with soft caps/penalties.
      const roi = row.roi_pct ?? 0;
      const pf = row.pf ?? 0;
      const dd = row.dd_pct ?? 0;
      const ruin = row.ruin_pct ?? 0;
      const pfC = Math.max(0, Math.min(pf, 5.0));
      const ddPenalty = Math.max(0, 1.0 - (dd / 50.0));
      const ruinPenalty = Math.max(0, 1.0 - (ruin / 20.0));
      return roi * pfC * ddPenalty * ruinPenalty;
    }}

    function buildRows(passList) {{
      const rows = [];
      for (const pid of (passList || [])) {{
        const p = DATA.passes[String(pid)];
        if (!p || !p.bt || !p.bt.full) continue;
        const bt = p.bt.full || {{}};
        const split = p.bt.split || {{}};
        const mc = p.monte_carlo || {{}};
        const opt = p.opt || {{}};

        const row = {{
          pass: Number(pid),
          net_profit: num(bt.total_net_profit),
          roi_pct: computeRoiPct(bt),
          pf: num(bt.profit_factor),
          dd_pct: num(bt.max_drawdown_pct),
          trades: num(bt.total_trades),
          expected_payoff: num(bt.expected_payoff),
          recovery_factor: num(bt.recovery_factor),
          history_quality: num(bt.history_quality),
          bars: num(bt.bars),
          ticks: num(bt.ticks),
          commission: num(bt.total_commission),
          swap: num(bt.total_swap),
          is_profit: num(split.in_sample?.net_profit),
          fwd_profit: num(split.forward?.net_profit),
          is_pf: num(split.in_sample?.profit_factor),
          fwd_pf: num(split.forward?.profit_factor),
          is_dd: num(split.in_sample?.max_drawdown_pct),
          fwd_dd: num(split.forward?.max_drawdown_pct),
          is_trades: num(split.in_sample?.total_trades),
          fwd_trades: num(split.forward?.total_trades),
          opt_in_profit: num(opt.in_profit),
          opt_fwd_profit: num(opt.fwd_profit),
          opt_total_profit: num(opt.total_profit),
          opt_in_pf: num(opt.in_pf),
          opt_fwd_pf: num(opt.fwd_pf),
          opt_in_dd: num(opt.in_dd),
          opt_fwd_dd: num(opt.fwd_dd),
          opt_in_trades: num(opt.in_trades),
          opt_fwd_trades: num(opt.fwd_trades),
          ruin_pct: num(mc.probability_of_ruin),
          mc_median: num(mc.median_profit),
        }};
        row.hrm = computeHrm(row);
        rows.push(row);
      }}
      return rows;
    }}

    function applyFilters(rows, f) {{
      return rows.filter(r => {{
        if (f.minHrm !== null && r.hrm !== null && r.hrm < f.minHrm) return false;
        if (f.minRoi !== null && (r.roi_pct ?? -1e18) < f.minRoi) return false;
        if (f.minPf !== null && (r.pf ?? -1e18) < f.minPf) return false;
        if (f.maxDd !== null && (r.dd_pct ?? 1e18) > f.maxDd) return false;
        if (f.maxRuin !== null && (r.ruin_pct ?? 1e18) > f.maxRuin) return false;
        if (f.minTrades !== null && (r.trades ?? -1e18) < f.minTrades) return false;
        return true;
      }});
    }}

    function sortRows(rows, mode, customCol=null, customDir=-1) {{
      const cmp = (a,b) => {{
        if (a === null && b === null) return 0;
        if (a === null) return 1;
        if (b === null) return -1;
        return a < b ? -1 : (a > b ? 1 : 0);
      }};
      const s = rows.slice();
      if (mode === 'custom' && customCol) {{
        s.sort((x,y)=> customDir * cmp(x[customCol], y[customCol]));
      }} else if (mode === 'hrm_desc') s.sort((x,y)=> -cmp(x.hrm, y.hrm));
      else if (mode === 'net_profit_desc') s.sort((x,y)=> -cmp(x.net_profit, y.net_profit));
      else if (mode === 'roi_desc') s.sort((x,y)=> -cmp(x.roi_pct, y.roi_pct));
      else if (mode === 'pf_desc') s.sort((x,y)=> -cmp(x.pf, y.pf));
      else if (mode === 'dd_asc') s.sort((x,y)=> cmp(x.dd_pct, y.dd_pct));
      else if (mode === 'ruin_asc') s.sort((x,y)=> cmp(x.ruin_pct, y.ruin_pct));
      return s;
    }}

    const VIEW_COLUMNS = {{
      all: [
        {{ id:'pass', label:'Pass', left:true, tip:'Optimization pass number (from MT5 optimizer).' }},
        {{ id:'hrm', label:'HRM', tip:'Heuristic Robustness Metric (composite): ROI% × PF (capped) × DD penalty × Ruin penalty. Higher is better; use for ranking, not as a hard truth.' }},
        {{ id:'net_profit', label:'Net Profit', tip:'Net profit from the selected full-period backtest (includes commission + swap from Deals table where available).' }},
        {{ id:'roi_pct', label:'ROI%', tip:'Return on initial deposit: (Net Profit / Initial Balance) × 100.' }},
        {{ id:'pf', label:'PF', tip:'Profit Factor = Gross Profit / |Gross Loss|. > 1 means profitable; higher usually means more margin for costs/slippage.' }},
        {{ id:'dd_pct', label:'Max DD%', tip:'Maximum relative drawdown (percent) over the full-period backtest.' }},
        {{ id:'trades', label:'Trades', tip:'Number of trades in the full-period backtest.' }},
        {{ id:'is_profit', label:'IS Profit', tip:'In-sample net profit computed by splitting the re-run backtest at the split date.' }},
        {{ id:'fwd_profit', label:'FWD Profit', tip:'Forward/OOS net profit computed by splitting the re-run backtest at the split date (continuous equity run).' }},
        {{ id:'ruin_pct', label:'MC Ruin%', tip:'Monte Carlo probability of hitting the ruin threshold (trade-order shuffling). Lower is better.' }},
      ],
      bt: [
        {{ id:'pass', label:'Pass', left:true, tip:'Optimization pass number (from MT5 optimizer).' }},
        {{ id:'hrm', label:'HRM', tip:'Heuristic Robustness Metric (composite). Higher is better.' }},
        {{ id:'net_profit', label:'Net Profit', tip:'Net profit from the selected full-period backtest (includes commission + swap where available).' }},
        {{ id:'roi_pct', label:'ROI%', tip:'Return on initial deposit: (Net Profit / Initial Balance) × 100.' }},
        {{ id:'pf', label:'PF', tip:'Profit Factor = Gross Profit / |Gross Loss|.' }},
        {{ id:'dd_pct', label:'Max DD%', tip:'Maximum relative drawdown (percent) over the full-period backtest.' }},
        {{ id:'expected_payoff', label:'Exp Payoff', tip:'Expected payoff per trade = Net Profit / Trades.' }},
        {{ id:'recovery_factor', label:'Recovery', tip:'Recovery factor = Net Profit / Max Drawdown (higher is better).' }},
        {{ id:'trades', label:'Trades', tip:'Number of trades in the full-period backtest.' }},
        {{ id:'is_profit', label:'IS Profit', tip:'In-sample net profit from the re-run backtest split.' }},
        {{ id:'fwd_profit', label:'FWD Profit', tip:'Forward/OOS net profit from the re-run backtest split (continuous equity run).' }},
      ],
      opt: [
        {{ id:'pass', label:'Pass', left:true, tip:'Optimization pass number (from MT5 optimizer).' }},
        {{ id:'opt_total_profit', label:'Total Profit', tip:'Optimization-reported IS Profit + FWD Profit for this pass (from MT5 optimization XML).' }},
        {{ id:'opt_in_profit', label:'IS Profit', tip:'Optimization-reported in-sample profit for this pass (MT5 optimization XML).' }},
        {{ id:'opt_fwd_profit', label:'FWD Profit', tip:'Optimization-reported forward/OOS profit for this pass (MT5 optimization XML).' }},
        {{ id:'opt_in_pf', label:'IS PF', tip:'Optimization-reported in-sample Profit Factor (MT5 optimization XML).' }},
        {{ id:'opt_fwd_pf', label:'FWD PF', tip:'Optimization-reported forward Profit Factor (MT5 optimization XML).' }},
        {{ id:'opt_in_dd', label:'IS DD%', tip:'Optimization-reported in-sample Equity DD % (MT5 optimization XML).' }},
        {{ id:'opt_fwd_dd', label:'FWD DD%', tip:'Optimization-reported forward Equity DD % (MT5 optimization XML).' }},
        {{ id:'opt_in_trades', label:'IS Trades', tip:'Optimization-reported in-sample trades (MT5 optimization XML).' }},
        {{ id:'opt_fwd_trades', label:'FWD Trades', tip:'Optimization-reported forward trades (MT5 optimization XML).' }},
      ],
      risk: [
        {{ id:'pass', label:'Pass', left:true, tip:'Optimization pass number (from MT5 optimizer).' }},
        {{ id:'hrm', label:'HRM', tip:'Heuristic Robustness Metric (composite). Higher is better.' }},
        {{ id:'dd_pct', label:'Max DD%', tip:'Maximum relative drawdown (percent) over the full-period backtest.' }},
        {{ id:'ruin_pct', label:'MC Ruin%', tip:'Monte Carlo probability of hitting the ruin threshold (trade-order shuffling). Lower is better.' }},
        {{ id:'mc_median', label:'MC Median Profit', tip:'Median simulated profit across Monte Carlo shuffles.' }},
        {{ id:'pf', label:'PF', tip:'Profit Factor = Gross Profit / |Gross Loss|.' }},
        {{ id:'trades', label:'Trades', tip:'Number of trades in the full-period backtest.' }},
      ],
      costs: [
        {{ id:'pass', label:'Pass', left:true, tip:'Optimization pass number (from MT5 optimizer).' }},
        {{ id:'net_profit', label:'Net Profit', tip:'Net profit from the selected full-period backtest (includes commission + swap where available).' }},
        {{ id:'commission', label:'Commission', tip:'Total commission summed from the Deals table (negative is a cost).' }},
        {{ id:'swap', label:'Swap', tip:'Total swap summed from the Deals table (negative is a cost).' }},
        {{ id:'history_quality', label:'History Quality', tip:'History quality as reported by MT5 for this test model (not the same as “real ticks”).' }},
        {{ id:'bars', label:'Bars', tip:'Bars used in the backtest (from MT5 report).' }},
        {{ id:'ticks', label:'Ticks', tip:'Ticks used in the backtest (from MT5 report/model).' }},
      ],
    }};

    function cellValue(row, colId) {{
      return row[colId];
    }}

    function cellText(colId, v) {{
      if (v === null || v === undefined) return '-';
      if (['pass','trades','bars','ticks','is_trades','fwd_trades','opt_in_trades','opt_fwd_trades'].includes(colId)) return String(Math.trunc(Number(v)));
      if (['roi_pct','dd_pct','ruin_pct','is_dd','fwd_dd','opt_in_dd','opt_fwd_dd'].includes(colId)) return fmt(v,2);
      if (['pf','is_pf','fwd_pf','opt_in_pf','opt_fwd_pf'].includes(colId)) return fmt(v,2);
      if (['hrm'].includes(colId)) return fmt(v,2);
      return fmt(v,2);
    }}

    let CURRENT_PASS = null;
    let SORT_COL = null;
    let SORT_DIR = -1; // -1 desc, +1 asc

    function renderTopTable() {{
      const view = document.getElementById('viewSelect').value || 'all';
      const sortMode = document.getElementById('sortSelect').value || 'hrm_desc';

      const filters = {{
        minHrm: numOrNullFromInput('fMinHrm'),
        minRoi: numOrNullFromInput('fMinRoi'),
        minPf: numOrNullFromInput('fMinPf'),
        maxDd: numOrNullFromInput('fMaxDd'),
        maxRuin: numOrNullFromInput('fMaxRuin'),
        minTrades: numOrNullFromInput('fMinTrades'),
      }};

      const allRows = buildRows(DATA.pass_list || []);
      const rows = sortRows(applyFilters(allRows, filters), sortMode, SORT_COL, SORT_DIR);
      const cols = VIEW_COLUMNS[view] || VIEW_COLUMNS.all;

      document.getElementById('tableStats').textContent = `Showing ${{rows.length}} / ${{allRows.length}} passes`;

      if (rows.length === 0) {{
        document.getElementById('topTable').innerHTML = '<div class=\"subtitle\">No passes match filters.</div>';
        return;
      }}

      let html = '<div class=\"scroll\"><table><thead><tr>';
      for (const c of cols) {{
        const tip = c.tip ? ` title=\"${{escapeHtml(c.tip)}}\"` : '';
        const sortable = c.id !== 'pass';
        const cls = sortable ? ' class=\"sortable\"' : '';
        const data = sortable ? ` data-col=\"${{c.id}}\"` : '';
        const active = (sortMode === 'custom' && SORT_COL === c.id);
        const arrow = active ? (SORT_DIR < 0 ? '↓' : '↑') : '';
        const indicator = sortable ? `<span class=\"sort-indicator\">${{arrow}}</span>` : '';
        html += `<th${{cls}}${{data}}${{tip}}>${{c.label}}${{indicator}}</th>`;
      }}
      html += '</tr></thead><tbody>';
      for (const r of rows) {{
        const sel = (CURRENT_PASS !== null && Number(r.pass) === Number(CURRENT_PASS)) ? ' selected' : '';
        html += `<tr class=\"clickable${{sel}}\" data-pass=\"${{r.pass}}\">`;
        for (const c of cols) {{
          const v = cellValue(r, c.id);
          const text = cellText(c.id, v);
          if (c.left) html += `<td style=\"text-align:left\">${{text}}</td>`;
          else html += `<td>${{text}}</td>`;
        }}
        html += '</tr>';
      }}
      html += '</tbody></table></div>';
      document.getElementById('topTable').innerHTML = html;
    }}

    const opt = DATA.optimization || {{}};
    addKpis('optkpis', [
      {{ label: 'Total Passes', value: opt.total_passes ?? '-', tip: 'Total optimization passes parsed from MT5 XML (in-sample joined with forward).' }},
      {{ label: 'Robust Passes', value: opt.robust_passes ?? '-', tip: 'Passes with Profit > 0 in both in-sample and forward periods (robust filter).', tag: opt.robust_passes > 0 ? 'OK' : 'NONE', tagClass: opt.robust_passes > 0 ? 'good' : 'bad' }},
      {{ label: 'Best Total Profit', value: fmt(opt.best?.total_profit, 2), tip: 'Best robust pass by (Opt IS Profit + Opt FWD Profit), using MT5 optimization XML.' }},
      {{ label: 'Best In/Fwd Profit', value: `${{fmt(opt.best?.in_profit,2)}} / ${{fmt(opt.best?.fwd_profit,2)}}`, tip: 'Optimization-reported profits for the best pass, split IS vs forward (MT5 XML).' }},
      {{ label: 'Fwd Profit P5/P50/P95', value: `${{fmt(opt.fwd_p5,2)}} / ${{fmt(opt.fwd_p50,2)}} / ${{fmt(opt.fwd_p95,2)}}`, tip: 'Forward-profit distribution percentiles across robust passes (MT5 XML).' }},
    ]);

    function renderPassDetails(p) {{
      const root = document.getElementById('passDetails');
      if (!p) {{
        root.innerHTML = '<div class=\"subtitle\">No pass selected.</div>';
        return;
      }}

      const split = p.bt?.split || {{}};
      const inS = split.in_sample || {{}};
      const fwd = split.forward || {{}};
      const params = p.parameters || {{}};

      let html = '';
      html += `<div class=\"subtitle\">Pass <span class=\"tag good mono\">${{p.pass}}</span></div>`;
      html += '<div style=\"height:10px\"></div>';
      html += '<table><thead><tr><th></th><th>In-sample</th><th>Forward</th></tr></thead><tbody>';
      html += `<tr><td title="Net profit over the period (sum of per-trade net P/L).">Net Profit</td><td>${{fmt(inS.net_profit,2)}}</td><td>${{fmt(fwd.net_profit,2)}}</td></tr>`;
      html += `<tr><td title="Profit Factor = Gross Profit / |Gross Loss|.">Profit Factor</td><td>${{fmt(inS.profit_factor,2)}}</td><td>${{fmt(fwd.profit_factor,2)}}</td></tr>`;
      html += `<tr><td title="Maximum relative drawdown percent for that segment.">Max DD%</td><td>${{fmt(inS.max_drawdown_pct,2)}}</td><td>${{fmt(fwd.max_drawdown_pct,2)}}</td></tr>`;
      html += `<tr><td title="Number of trades in that segment.">Trades</td><td>${{inS.total_trades ?? '-'}}</td><td>${{fwd.total_trades ?? '-'}}</td></tr>`;
      html += '</tbody></table>';

      html += '<div style=\"height:12px\"></div>';
      html += '<div class=\"subtitle\">Parameters</div>';
      html += '<div class=\"scroll\"><table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>';
      for (const k of Object.keys(params).sort()) {{
        html += `<tr><td class=\"mono\">${{k}}</td><td class=\"mono\">${{String(params[k])}}</td></tr>`;
      }}
      html += '</tbody></table></div>';
      root.innerHTML = html;
    }}

    function selectPass(passNum) {{
      const p = DATA.passes[String(passNum)];
      if (!p) return;
      CURRENT_PASS = Number(passNum);
      renderTopTable();

      // report link
      const link = document.getElementById('reportLink');
      const rel = p.bt?.report_rel;
      if (rel) {{
        link.href = rel;
        link.style.display = 'inline-block';
      }} else {{
        link.style.display = 'none';
      }}

      // KPIs (selected pass full-period backtest)
      const bt = p.bt?.full || {{}};
      const split = p.bt?.split || {{}};
      const initial = (bt.initial_balance ?? bt.initial_deposit ?? 0);
      const roi = (initial && bt.total_net_profit !== undefined && bt.total_net_profit !== null)
        ? (Number(bt.total_net_profit) / Number(initial) * 100.0)
        : null;
      addKpis('kpis', [
        {{ label: 'Pass', value: String(p.pass), tip: 'Optimization pass number (from MT5 optimizer).' }},
        {{ label: 'Net Profit', value: fmt(bt.total_net_profit, 2), tip: 'Net profit from the full-period re-run backtest (sum of per-trade net P/L, includes commission + swap where available).' }},
        {{ label: 'ROI %', value: roi === null ? '-' : (fmt(roi, 2) + '%'), tip: 'Return on initial deposit: (Net Profit / Initial Balance) × 100.' }},
        {{ label: 'Profit Factor', value: fmt(bt.profit_factor, 2), tip: 'Profit Factor = Gross Profit / |Gross Loss|. PF<1.5 is a soft warning (not a hard fail).', tag: (bt.profit_factor ?? 0) >= 1.5 ? 'OK' : 'SOFT', tagClass: (bt.profit_factor ?? 0) >= 1.5 ? 'good' : 'warn' }},
        {{ label: 'Max Drawdown %', value: fmt(bt.max_drawdown_pct, 2), tip: 'Maximum relative drawdown (percent) over the full-period re-run backtest.' }},
        {{ label: 'Trades', value: bt.total_trades ?? '-', tip: 'Total number of trades in the full-period re-run backtest.' }},
        {{ label: 'History Quality', value: (bt.history_quality ?? null) === null ? '-' : (fmt(bt.history_quality, 0) + '%'), tip: 'History quality as reported by MT5 for this test model (not the same as “real ticks”).' }},
        {{ label: 'Bars / Ticks', value: `${{fmt(bt.bars,0)}} / ${{fmt(bt.ticks,0)}}`, tip: 'Bars and ticks counts from the MT5 report/model.' }},
        {{ label: 'Commission / Swap', value: `${{fmt(bt.total_commission,2)}} / ${{fmt(bt.total_swap,2)}}`, tip: 'Total commission and swap summed from the MT5 Deals table (negative is cost).' }},
        {{ label: 'IS / FWD Profit', value: `${{fmt(split.in_sample?.net_profit,2)}} / ${{fmt(split.forward?.net_profit,2)}}`, tip: 'In-sample vs forward net profit, computed by splitting the re-run backtest by the split date (continuous equity run).' }},
        {{ label: 'IS / FWD Trades', value: `${{split.in_sample?.total_trades ?? '-'}} / ${{split.forward?.total_trades ?? '-'}}`, tip: 'In-sample vs forward trade counts, computed by splitting the re-run backtest by the split date.' }},
      ]);

      // Equity
      drawEquity('equity', p.equity?.in_sample || [], p.equity?.forward || []);

      // Scatter highlight (uses optimization metrics)
      drawScatter('scatter', (opt.scatter || []), p.opt_point || null);

      // Monte Carlo
      const mc = p.monte_carlo || {{}};
      const mcTag = (mc.probability_of_ruin ?? 100) <= (mc.max_ruin_probability ?? 5) ? 'PASS' : 'RISK';
      addKpis('mckpis', [
        {{ label: 'Iterations', value: mc.iterations ?? '-', tip: 'Number of Monte Carlo shuffles performed (trade-order randomization).' }},
        {{ label: 'Confidence', value: fmt(mc.confidence_level, 1) + '%', tip: 'Confidence level from Monte Carlo summary (higher is better).', tag: (mc.confidence_level ?? 0) >= (mc.confidence_min ?? 70) ? 'PASS' : 'LOW', tagClass: (mc.confidence_level ?? 0) >= (mc.confidence_min ?? 70) ? 'good' : 'warn' }},
        {{ label: 'Ruin Probability', value: fmt(mc.probability_of_ruin, 1) + '%', tip: 'Probability (in Monte Carlo) that equity hits the ruin threshold. Lower is better.', tag: mcTag, tagClass: mcTag === 'PASS' ? 'good' : 'warn' }},
        {{ label: 'Profit P5/P50/P95', value: `${{fmt(mc.profit_5th_percentile,2)}} / ${{fmt(mc.median_profit,2)}} / ${{fmt(mc.profit_95th_percentile,2)}}`, tip: 'Profit distribution percentiles across Monte Carlo shuffles.' }},
        {{ label: 'Max DD 95th pct', value: fmt(mc.max_drawdown_95th_percentile, 2), tip: '95th percentile of maximum drawdown across Monte Carlo shuffles (worse-case-ish DD).' }},
      ]);

      renderPassDetails(p);
    }}

    const initialPass = DATA.selected_pass ?? (DATA.pass_list && DATA.pass_list[0]);
    CURRENT_PASS = initialPass;
    document.getElementById('topTable').addEventListener('click', (ev) => {{
      const th = ev.target.closest('th[data-col]');
      if (th) {{
        const col = th.dataset.col;
        if (col) {{
          if (SORT_COL === col) SORT_DIR = -SORT_DIR;
          else {{
            SORT_COL = col;
            // sensible defaults (risk metrics sort ascending, performance descending)
            SORT_DIR = (['dd_pct','ruin_pct','opt_in_dd','opt_fwd_dd','opt_in_trades','opt_fwd_trades'].includes(col)) ? 1 : -1;
          }}
          document.getElementById('sortSelect').value = 'custom';
          renderTopTable();
        }}
        return;
      }}

      const tr = ev.target.closest('tr[data-pass]');
      if (!tr) return;
      selectPass(Number(tr.dataset.pass));
    }});

    drawScatter('scatter', (opt.scatter || []), null);
    if (initialPass !== null && initialPass !== undefined) {{
      // initialize filter defaults + render table + select pass
      document.getElementById('fMinPf').value = '';
      document.getElementById('fMinRoi').value = '';
      document.getElementById('fMinHrm').value = '';
      document.getElementById('fMaxDd').value = '';
      document.getElementById('fMaxRuin').value = '';
      document.getElementById('fMinTrades').value = '';
      renderTopTable();
      selectPass(initialPass);
    }}

    for (const id of ['viewSelect','sortSelect','fMinHrm','fMinRoi','fMinPf','fMaxDd','fMaxRuin','fMinTrades']) {{
      const el = document.getElementById(id);
      el.addEventListener('change', renderTopTable);
      el.addEventListener('input', renderTopTable);
    }}
    document.getElementById('resetFilters').addEventListener('click', () => {{
      document.getElementById('viewSelect').value = 'all';
      document.getElementById('sortSelect').value = 'hrm_desc';
      SORT_COL = null;
      SORT_DIR = -1;
      for (const id of ['fMinHrm','fMinRoi','fMinPf','fMaxDd','fMaxRuin','fMinTrades']) {{
        document.getElementById(id).value = '';
      }}
      renderTopTable();
    }});
  </script>
</body>
</html>
"""


def _render_compare_html(data: Dict[str, Any]) -> str:
    safe = json.dumps(data).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EA Compare - {data.get("ea_name","")}</title>
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
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    .title {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.2px; }}
    .subtitle {{ color: var(--muted); font-size: 13px; }}
    .card {{
      background: rgba(18,26,51,0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.25);
      margin-top: 14px;
    }}
    .tag {{ display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); color: var(--muted); }}
    .tag.good {{ color: var(--good); border-color: rgba(61,220,151,0.4); }}
    .tag.warn {{ color: var(--warn); border-color: rgba(255,204,102,0.4); }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; text-align: right; }}
    th {{ color: var(--muted); font-weight: 600; }}
    td:first-child, th:first-child {{ text-align: left; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>Compare: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          <a class="tag" href="index.html">Back to dashboard</a>
          Symbol: <span class="tag">{data.get("symbol","")}</span>
          Timeframe: <span class="tag">{data.get("timeframe","")}</span>
          Split: <span class="tag">{data.get("forward_date","")}</span>
        </div>
      </div>
      <div>
        <span class="subtitle">Pass</span>
        <select id="passSelect" class="tag" style="background: transparent;"></select>
      </div>
    </div>

    <div class="card">
      <div class="subtitle">Optimization (IS/FWD) vs Re-run Backtest Split (IS/FWD)</div>
      <div id="compareTables"></div>
    </div>

    <div class="card">
      <div class="subtitle">Single Robust Backtest After Optimization</div>
      <div id="robustBlock"></div>
    </div>
  </div>

  <script>
    const DATA = {safe};

    function fmt(x, digits=2) {{
      if (x === null || x === undefined || Number.isNaN(x)) return '-';
      const n = Number(x);
      return n.toLocaleString(undefined, {{ maximumFractionDigits: digits, minimumFractionDigits: digits }});
    }}

    function renderCompare(passNum) {{
      const p = DATA.passes[String(passNum)];
      if (!p) return;

      const opt = p.opt || {{}};
      const split = p.bt?.split || {{}};
      const inS = split.in_sample || {{}};
      const fwd = split.forward || {{}};

      const rows = [
        ['Net Profit', opt.in_profit, opt.fwd_profit, inS.net_profit, fwd.net_profit],
        ['Profit Factor', opt.in_pf, opt.fwd_pf, inS.profit_factor, fwd.profit_factor],
        ['Max DD%', opt.in_dd, opt.fwd_dd, inS.max_drawdown_pct, fwd.max_drawdown_pct],
        ['Trades', opt.in_trades, opt.fwd_trades, inS.total_trades, fwd.total_trades],
      ];

      let html = '<table><thead><tr>' +
        '<th>Metric</th>' +
        '<th>Opt IS</th><th>Opt FWD</th>' +
        '<th>Re-run IS</th><th>Re-run FWD</th>' +
        '</tr></thead><tbody>';
      for (const r of rows) {{
        html += `<tr><td>${{r[0]}}</td><td>${{fmt(r[1])}}</td><td>${{fmt(r[2])}}</td><td>${{fmt(r[3])}}</td><td>${{fmt(r[4])}}</td></tr>`;
      }}
      html += '</tbody></table>';
      document.getElementById('compareTables').innerHTML = html;

      // Robust block (best-params single backtest)
      const rb = DATA.robust_backtest || {{}};
      if (!rb.success) {{
        document.getElementById('robustBlock').innerHTML = '<div class=\"subtitle\">No robust backtest artifact found in state.</div>';
        return;
      }}
      const link = rb.bt?.report_rel ? `<a class=\"tag\" href=\"${{rb.bt.report_rel}}\">Open MT5 HTML report</a>` : '';
      const full = rb.bt?.full || {{}};
      const rsplit = rb.bt?.split || {{}};
      const rin = rsplit.in_sample || {{}};
      const rfwd = rsplit.forward || {{}};

      let rbHtml = '<div style=\"display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:8px\">' +
        link +
        `<span class=\"tag\">History Quality: ${{full.history_quality===null||full.history_quality===undefined ? '-' : fmt(full.history_quality,0)+'%'}} </span>` +
        `<span class=\"tag\">Bars/Ticks: ${{fmt(full.bars,0)}} / ${{fmt(full.ticks,0)}}</span>` +
        '</div>';

      rbHtml += '<table><thead><tr><th></th><th>Full</th><th>IS</th><th>FWD</th></tr></thead><tbody>';
      rbHtml += `<tr><td>Net Profit</td><td>${{fmt(full.total_net_profit,2)}}</td><td>${{fmt(rin.net_profit,2)}}</td><td>${{fmt(rfwd.net_profit,2)}}</td></tr>`;
      rbHtml += `<tr><td>Profit Factor</td><td>${{fmt(full.profit_factor,2)}}</td><td>${{fmt(rin.profit_factor,2)}}</td><td>${{fmt(rfwd.profit_factor,2)}}</td></tr>`;
      rbHtml += `<tr><td>Max DD%</td><td>${{fmt(full.max_drawdown_pct,2)}}</td><td>${{fmt(rin.max_drawdown_pct,2)}}</td><td>${{fmt(rfwd.max_drawdown_pct,2)}}</td></tr>`;
      rbHtml += `<tr><td>Trades</td><td>${{full.total_trades ?? '-'}}</td><td>${{rin.total_trades ?? '-'}}</td><td>${{rfwd.total_trades ?? '-'}}</td></tr>`;
      rbHtml += `<tr><td>Commission/Swap</td><td>${{fmt(full.total_commission,2)}} / ${{fmt(full.total_swap,2)}}</td><td>-</td><td>-</td></tr>`;
      rbHtml += '</tbody></table>';

      document.getElementById('robustBlock').innerHTML = rbHtml;
    }}

    function init() {{
      const sel = document.getElementById('passSelect');
      for (const pid of (DATA.pass_list || [])) {{
        const opt = document.createElement('option');
        opt.value = pid;
        opt.textContent = String(pid);
        sel.appendChild(opt);
      }}

      const initial = DATA.selected_pass ?? (DATA.pass_list && DATA.pass_list[0]);
      if (initial !== null && initial !== undefined) {{
        sel.value = String(initial);
        renderCompare(Number(initial));
      }}

      sel.addEventListener('change', () => renderCompare(Number(sel.value)));
    }}

    init();
  </script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an offline HTML dashboard for a stress-test run")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses the latest workflow state in runs/)")
    ap.add_argument("--out", type=str, help="Output directory (default: runs/dashboards/{EA}_YYYYMMDD_HHMMSS)")
    ap.add_argument("--passes", type=int, default=20, help="How many top robust passes to precompute (clickable)")
    ap.add_argument("--bt-timeout", type=int, default=600, help="Per-pass backtest timeout seconds")
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

    symbol = state.get("symbol") or DEFAULT_SYMBOL
    timeframe = state.get("timeframe") or DEFAULT_TIMEFRAME

    steps = state.get("steps", {}) or {}
    from_date = BACKTEST_FROM
    to_date = BACKTEST_TO
    forward_date = ""

    step6 = steps.get("6_create_opt_ini", {}).get("output", {}) if steps.get("6_create_opt_ini") else {}
    if isinstance(step6, dict):
        ins_pair = _parse_date_pair(step6.get("in_sample", "") or "")
        fwd_pair = _parse_date_pair(step6.get("forward_test", "") or "")
        if ins_pair:
            from_date, forward_date = ins_pair
        if fwd_pair:
            forward_date = forward_date or fwd_pair[0]
            to_date = fwd_pair[1]

    if not forward_date:
        m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", to_date)
        forward_date = f"{int(m.group(1)) - 1}.{m.group(2)}.{m.group(3)}" if m else to_date

    artifacts = _extract_artifacts_from_state(state)
    insample_xml = artifacts.get("opt_insample_xml")
    forward_xml = artifacts.get("opt_forward_xml")
    if not (insample_xml and forward_xml):
        insample_xml, forward_xml = _find_optimization_xml_fallback(ea_name)

    # Output location
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (RUNS_DIR / "dashboards" / f"{ea_name}_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Optimization distribution (from XML)
    opt_summary: Dict[str, Any] = {"success": False}
    robust_rows: List[Dict[str, Any]] = []
    scatter: List[Dict[str, float]] = []

    if insample_xml and forward_xml and insample_xml.exists() and forward_xml.exists():
        optp = OptimizationResultParser(ea_name, terminal_path=Path("."))  # terminal_path unused with direct calls
        ins = optp._parse_xml(insample_xml)
        fwd = optp._parse_xml(forward_xml)

        joined: List[Dict[str, Any]] = []
        for pass_num, insr in ins.items():
            fwdr = fwd.get(pass_num)
            if not fwdr:
                continue
            joined.append(
                {
                    "pass": int(pass_num),
                    "in_profit": float(insr.get("profit", 0.0)),
                    "fwd_profit": float(fwdr.get("profit", 0.0)),
                    "in_pf": float(insr.get("profit_factor", 0.0)),
                    "fwd_pf": float(fwdr.get("profit_factor", 0.0)),
                    "in_dd": float(insr.get("equity_dd_pct", 0.0)),
                    "fwd_dd": float(fwdr.get("equity_dd_pct", 0.0)),
                    "in_trades": int(insr.get("trades", 0) or 0),
                    "fwd_trades": int(fwdr.get("trades", 0) or 0),
                    "total_profit": float(insr.get("profit", 0.0)) + float(fwdr.get("profit", 0.0)),
                    "parameters": insr.get("parameters", {}) or {},
                }
            )

        robust_rows = [r for r in joined if r["in_profit"] > 0 and r["fwd_profit"] > 0]
        robust_rows.sort(key=lambda r: r["total_profit"], reverse=True)
        best = robust_rows[0] if robust_rows else None

        for r in robust_rows:
            scatter.append({"x": float(r["in_profit"]), "y": float(r["fwd_profit"])})

        fwd_profits = sorted(float(r["fwd_profit"]) for r in robust_rows)
        opt_summary = {
            "success": True,
            "total_passes": len(joined),
            "robust_passes": len(robust_rows),
            "best": best,
            "fwd_p5": _percentile(fwd_profits, 5),
            "fwd_p50": _percentile(fwd_profits, 50),
            "fwd_p95": _percentile(fwd_profits, 95),
            "scatter": scatter,
        }

    # Precompute pass-level backtests (so dashboard can switch charts instantly)
    pass_list = [r["pass"] for r in robust_rows[: max(0, int(args.passes))]]
    selected_pass = (opt_summary.get("best") or {}).get("pass") if isinstance(opt_summary.get("best"), dict) else None
    if selected_pass not in pass_list:
        selected_pass = pass_list[0] if pass_list else None

    s = get_settings()
    runner = BacktestRunner(timeout=int(args.bt_timeout))
    rp = ReportParser()

    # Robust (single) backtest artifact from the workflow state (best params)
    robust_bt: Dict[str, Any] = {"success": False}
    robust_src = artifacts.get("backtest_report") or _find_backtest_report_fallback(ea_name)
    if robust_src and robust_src.exists():
        copied = _copy_report_with_assets(robust_src, out_dir / "robust")
        metrics = rp.parse(copied)
        extraction = extract_trades(str(copied))
        trades_dict = [t.to_dict() for t in extraction.trades] if extraction.success else []
        initial_balance = float(extraction.initial_balance or (metrics.initial_deposit if metrics else 0.0) or 0.0)
        in_trades, fwd_trades = _split_trades_by_forward_date(trades_dict, forward_date)

        equity_in = _compute_equity_curve(in_trades, initial_balance)
        start_fwd = equity_in[-1] if equity_in else initial_balance
        equity_fwd = _compute_equity_curve(fwd_trades, start_fwd)

        full = metrics.to_dict() if metrics else {}
        if extraction.success:
            full["total_net_profit"] = extraction.total_net_profit
            full["total_commission"] = extraction.total_commission
            full["total_swap"] = extraction.total_swap
            full["initial_balance"] = initial_balance
            full["final_balance"] = extraction.final_balance or full.get("final_balance", 0.0)

        robust_bt = {
            "success": True,
            "bt": {
                "report_rel": copied.relative_to(out_dir).as_posix(),
                "full": full,
                "split": {
                    "in_sample": _compute_trade_stats(in_trades, initial_balance),
                    "forward": _compute_trade_stats(fwd_trades, start_fwd),
                },
            },
            "equity": {"in_sample": equity_in, "forward": equity_fwd},
        }

    passes: Dict[str, Any] = {}
    for idx, r in enumerate(robust_rows[: max(0, int(args.passes))], start=1):
        pass_num = int(r["pass"])
        params = r.get("parameters", {}) or {}

        run_dir = out_dir / "passes" / f"pass_{pass_num}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Reuse cached report if already present (saves time when regenerating dashboards)
        existing_reports = []
        if run_dir.exists():
            existing_reports.extend(run_dir.glob("*.htm"))
            existing_reports.extend(run_dir.glob("*.html"))
        existing_report = max(existing_reports, key=lambda p: p.stat().st_mtime) if existing_reports else None

        if existing_report:
            print(f"[{idx}/{len(pass_list)}] Using cached report for pass {pass_num}: {existing_report.name}", file=sys.stderr)
            res = None
            report_path = existing_report
        else:
            print(f"[{idx}/{len(pass_list)}] Backtesting pass {pass_num}...", file=sys.stderr)
            res = runner.run(
                ea_name=ea_name,
                symbol=symbol,
                timeframe=timeframe,
                from_date=from_date,
                to_date=to_date,
                run_dir=run_dir,
                inputs=params,
            )

        opt_point = {"x": float(r.get("in_profit", 0.0)), "y": float(r.get("fwd_profit", 0.0))}

        if res is not None and (not res.success or not res.report_path):
            passes[str(pass_num)] = {
                "success": False,
                "pass": pass_num,
                "parameters": params,
                "opt_point": opt_point,
                "error": res.error or "Backtest failed",
            }
            continue

        if res is not None:
            report_path = res.report_path
        metrics = rp.parse(report_path)
        extraction = extract_trades(str(report_path))

        trades_dict = [t.to_dict() for t in extraction.trades] if extraction.success else []
        initial_balance = float(extraction.initial_balance or (metrics.initial_deposit if metrics else 0.0) or 0.0)

        in_trades, fwd_trades = _split_trades_by_forward_date(trades_dict, forward_date)

        equity_in = _compute_equity_curve(in_trades, initial_balance)
        start_fwd = equity_in[-1] if equity_in else initial_balance
        equity_fwd = _compute_equity_curve(fwd_trades, start_fwd)

        full = metrics.to_dict() if metrics else {}
        if extraction.success:
            full["total_net_profit"] = extraction.total_net_profit
            full["total_commission"] = extraction.total_commission
            full["total_swap"] = extraction.total_swap
            full["initial_balance"] = initial_balance
            full["final_balance"] = extraction.final_balance or full.get("final_balance", 0.0)

        mc = MonteCarloSimulator(
            iterations=s.monte_carlo.iterations,
            ruin_threshold_pct=s.monte_carlo.ruin_threshold_pct,
        ).run(extraction.trades if extraction.success else [], initial_balance)

        report_rel = report_path.relative_to(out_dir).as_posix()

        passes[str(pass_num)] = {
            "success": True,
            "pass": pass_num,
            "parameters": params,
            "opt_point": opt_point,
            "opt": {
                "in_profit": float(r.get("in_profit", 0.0)),
                "fwd_profit": float(r.get("fwd_profit", 0.0)),
                "total_profit": float(r.get("total_profit", 0.0)),
                "in_pf": float(r.get("in_pf", 0.0)),
                "fwd_pf": float(r.get("fwd_pf", 0.0)),
                "in_dd": float(r.get("in_dd", 0.0)),
                "fwd_dd": float(r.get("fwd_dd", 0.0)),
                "in_trades": int(r.get("in_trades", 0) or 0),
                "fwd_trades": int(r.get("fwd_trades", 0) or 0),
            },
            "bt": {
                "report_rel": report_rel,
                "full": full,
                "split": {
                    "in_sample": _compute_trade_stats(in_trades, initial_balance),
                    "forward": _compute_trade_stats(fwd_trades, start_fwd),
                },
            },
            "equity": {
                "in_sample": equity_in,
                "forward": equity_fwd,
            },
            "monte_carlo": {
                **mc.to_dict(),
                "confidence_min": s.monte_carlo.confidence_min,
                "max_ruin_probability": s.monte_carlo.max_ruin_probability,
            },
        }

    dash = {
        "ea_name": ea_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": ts,
        "from_date": from_date,
        "to_date": to_date,
        "forward_date": forward_date,
        "optimization": opt_summary,
        "pass_list": pass_list,
        "selected_pass": selected_pass,
        "passes": passes,
        "robust_backtest": robust_bt,
    }

    index_html = _render_html(dash)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    compare_path = out_dir / "compare.html"
    compare_path.write_text(_render_compare_html(dash), encoding="utf-8")

    # Persist data json for programmatic use
    (out_dir / "data.json").write_text(json.dumps(dash, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "success": True,
                "ea_name": ea_name,
                "state_file": str(state_path),
                "dashboard_dir": str(out_dir),
                "index": str(index_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
