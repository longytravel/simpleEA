#!/usr/bin/env python3
"""
Run a post-test multi-pair follow-up and generate an offline HTML report.

This is an OPTIONAL module (not part of the core 1-pair pipeline).

Modes:
  - Generalization check (default): reuse the best parameters from the 1-pair workflow
    and backtest them across a basket of pairs.

Usage:
  python scripts/run_multipair.py --state runs/workflow_EA_*.json
  python scripts/run_multipair.py --ea Overlap_Momentum_Shield_Safe
  python scripts/run_multipair.py --ea EA --params runs/EA_best_params.json --pairs EURUSD GBPUSD USDJPY
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BACKTEST_FROM, BACKTEST_TO, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, RUNS_DIR
from parser.trade_extractor import extract_trades
from tester.multipair import MultiPairTester, load_params


def _find_latest_workflow_state(ea_name: str) -> Optional[Path]:
    candidates = sorted(RUNS_DIR.glob(f"workflow_{ea_name}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_state(state_path: Path) -> Dict[str, Any]:
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_date_pair(s: str) -> Optional[Tuple[str, str]]:
    if not s:
        return None
    import re

    m = re.search(r"(\d{4}\.\d{2}\.\d{2}).*?(\d{4}\.\d{2}\.\d{2})", s)
    if not m:
        return None
    return m.group(1), m.group(2)


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


def _extract_date(s: str) -> Optional[str]:
    if not s:
        return None
    m = re.search(r"\b(\d{4}\.\d{2}\.\d{2})\b", s)
    return m.group(1) if m else None


def _daily_net_profit(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    daily: Dict[str, float] = {}
    for t in trades:
        dt = _extract_date(str(t.get("time", "")))
        if not dt:
            continue
        daily[dt] = daily.get(dt, 0.0) + float(t.get("net_profit", 0.0) or 0.0)
    return daily


def _align_daily_series(series_by_symbol: Dict[str, Dict[str, float]]) -> Tuple[List[str], Dict[str, List[float]]]:
    dates: List[str] = sorted({d for s in series_by_symbol.values() for d in s.keys()})
    vectors: Dict[str, List[float]] = {}
    for sym, series in series_by_symbol.items():
        vectors[sym] = [float(series.get(d, 0.0)) for d in dates]
    return dates, vectors


def _pearson_corr(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) != len(y) or len(x) < 2:
        return None
    n = float(len(x))
    mx = sum(x) / n
    my = sum(y) / n
    sx = sum((xi - mx) ** 2 for xi in x)
    sy = sum((yi - my) ** 2 for yi in y)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    return cov / math.sqrt(sx * sy)


def _drawdown_flags(daily_pnl: List[float], initial_balance: float) -> List[bool]:
    equity = float(initial_balance or 0.0)
    peak = equity
    flags: List[bool] = []
    for r in daily_pnl:
        equity += float(r or 0.0)
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
        flags.append(dd_pct >= 1.0)  # ignore tiny dips; focus on meaningful drawdowns
    return flags


def _dd_overlap_pct(a: List[bool], b: List[bool]) -> Optional[float]:
    if len(a) != len(b) or not a:
        return None
    both = sum(1 for x, y in zip(a, b) if x and y)
    return (both / len(a)) * 100.0


def _currency_exposure(symbols: List[str]) -> Dict[str, int]:
    exposure: Dict[str, int] = {}
    for sym in symbols:
        s = (sym or "").upper().strip()
        if len(s) < 6:
            continue
        base = s[:3]
        quote = s[-3:]
        exposure[base] = exposure.get(base, 0) + 1
        exposure[quote] = exposure.get(quote, 0) + 1
    return dict(sorted(exposure.items(), key=lambda kv: (-kv[1], kv[0])))


def _pair_score(r: Dict[str, Any]) -> float:
    """
    Heuristic per-pair score for portfolio selection.
    Uses ROI% (normalized), PF, DD%, and trades. Higher is better.
    """
    if not isinstance(r, dict) or not r.get("success"):
        return float("-inf")
    roi = float(r.get("roi_pct") or 0.0)
    pf = float(r.get("profit_factor") or 0.0)
    dd = float(r.get("max_drawdown_pct") or 0.0)
    trades = float(r.get("total_trades") or 0.0)

    if roi <= 0 or pf <= 1.0 or trades <= 0:
        return float("-inf")

    pf_cap = min(max(pf, 0.0), 3.0)
    dd_factor = max(0.0, 1.0 - (dd / 30.0))  # 0 at 30% DD
    trade_factor = min(1.0, math.sqrt(trades / 200.0))  # saturates around ~200 trades
    return roi * pf_cap * dd_factor * trade_factor


def _build_lookup(pairs: List[str], matrix: List[List[Optional[float]]]) -> Dict[Tuple[str, str], Optional[float]]:
    idx = {p: i for i, p in enumerate(pairs)}
    out: Dict[Tuple[str, str], Optional[float]] = {}
    for a in pairs:
        for b in pairs:
            ia = idx.get(a)
            ib = idx.get(b)
            if ia is None or ib is None:
                out[(a, b)] = None
                continue
            out[(a, b)] = matrix[ia][ib] if ia < len(matrix) and ib < len(matrix[ia]) else None
    return out


def _suggest_portfolios(results: Dict[str, Any], analysis: Dict[str, Any], *, max_size: int = 4) -> Dict[str, Any]:
    """
    Recommend a subset of pairs that balances performance vs concentration risk.

    This is intentionally heuristic and transparent:
    - Candidate pairs must be profitable (ROI>0, PF>1) and have trades.
    - Portfolio objective = sum(pair_scores) * (1 - 0.5*maxAbsCorr - 0.5*maxDDOverlap)
    """
    if not analysis.get("success"):
        return {"success": False, "error": "analysis not available"}

    pairs = analysis.get("pairs") or []
    corr = (analysis.get("correlation") or {}).get("matrix") or []
    dd = (analysis.get("drawdown_overlap") or {}).get("matrix") or []
    if not pairs or not corr or not dd:
        return {"success": False, "error": "missing correlation/overlap matrices"}

    corr_lu = _build_lookup(pairs, corr)
    dd_lu = _build_lookup(pairs, dd)

    candidates: List[str] = []
    scores: Dict[str, float] = {}
    for sym in pairs:
        s = _pair_score(results.get(sym, {}))
        if s == float("-inf"):
            continue
        candidates.append(sym)
        scores[sym] = s

    if not candidates:
        return {"success": False, "error": "no profitable candidates for portfolio selection"}

    candidates = sorted(candidates, key=lambda x: scores.get(x, float("-inf")), reverse=True)
    kmax = min(int(max_size), len(candidates))

    def combo_stats(combo: Tuple[str, ...]) -> Dict[str, Any]:
        sum_score = sum(scores[p] for p in combo)
        max_abs_corr = 0.0
        max_dd_overlap = 0.0
        for i in range(len(combo)):
            for j in range(i + 1, len(combo)):
                a, b = combo[i], combo[j]
                c = corr_lu.get((a, b))
                o = dd_lu.get((a, b))
                if c is not None:
                    max_abs_corr = max(max_abs_corr, abs(float(c)))
                if o is not None:
                    max_dd_overlap = max(max_dd_overlap, float(o) / 100.0)
        objective = sum_score * max(0.0, 1.0 - 0.5 * max_abs_corr - 0.5 * max_dd_overlap)
        return {
            "pairs": list(combo),
            "sum_score": sum_score,
            "objective": objective,
            "max_abs_corr": max_abs_corr,
            "max_dd_overlap_pct": max_dd_overlap * 100.0,
            "currency_exposure": _currency_exposure(list(combo)),
        }

    # brute-force combinations up to size kmax (small N for default basket; still fast)
    import itertools

    recommendations: List[Dict[str, Any]] = []
    for k in range(1, kmax + 1):
        best: Optional[Dict[str, Any]] = None
        for combo in itertools.combinations(candidates, k):
            st = combo_stats(combo)
            if best is None or st["objective"] > best["objective"]:
                best = st
        if best is not None:
            best["size"] = k
            recommendations.append(best)

    return {
        "success": True,
        "candidates": candidates,
        "pair_scores": {k: scores[k] for k in candidates},
        "constraints": {
            "dd_flag_threshold_pct": 1.0,
            "objective_formula": "sum(pair_scores) * (1 - 0.5*maxAbsCorr - 0.5*maxDDOverlap)",
        },
        "recommendations": recommendations,
    }


def _compute_concentration_analysis(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute basic concentration-risk diagnostics from multi-pair reports:
    - Daily return correlation (based on per-day net profit)
    - Drawdown overlap (percent of days both are in drawdown)
    - Currency exposure counts
    """
    series_by_symbol: Dict[str, Dict[str, float]] = {}
    initial_by_symbol: Dict[str, float] = {}
    skipped: Dict[str, str] = {}

    for sym, r in (results or {}).items():
        if not isinstance(r, dict) or not r.get("success"):
            continue
        report_path = r.get("report_path")
        if not report_path:
            skipped[sym] = "missing report_path"
            continue

        extraction = extract_trades(str(report_path))
        if not extraction.success:
            skipped[sym] = extraction.error or "trade extraction failed"
            continue
        trades = [t.to_dict() for t in extraction.trades] if extraction.trades else []
        if not trades:
            skipped[sym] = "no trades extracted"
            continue

        series_by_symbol[sym] = _daily_net_profit(trades)
        initial = float(extraction.initial_balance or r.get("initial_deposit") or 0.0)
        initial_by_symbol[sym] = initial

    if not series_by_symbol:
        return {"success": False, "error": "No per-trade series available for correlation/overlap analysis", "skipped": skipped}

    dates, vectors = _align_daily_series(series_by_symbol)
    syms = sorted(vectors.keys())

    corr_matrix: List[List[Optional[float]]] = []
    dd_overlap_matrix: List[List[Optional[float]]] = []

    dd_flags: Dict[str, List[bool]] = {s: _drawdown_flags(vectors[s], initial_by_symbol.get(s, 0.0)) for s in syms}
    dd_freq: Dict[str, float] = {s: (sum(1 for f in dd_flags[s] if f) / len(dd_flags[s]) * 100.0) if dd_flags[s] else 0.0 for s in syms}

    for i, a in enumerate(syms):
        row_corr: List[Optional[float]] = []
        row_dd: List[Optional[float]] = []
        for j, b in enumerate(syms):
            if i == j:
                row_corr.append(1.0)
                row_dd.append(dd_freq.get(a, 0.0))
            else:
                row_corr.append(_pearson_corr(vectors[a], vectors[b]))
                row_dd.append(_dd_overlap_pct(dd_flags[a], dd_flags[b]))
        corr_matrix.append(row_corr)
        dd_overlap_matrix.append(row_dd)

    # Aggregate drawdown concurrency
    dd_counts = [sum(1 for s in syms if dd_flags[s][k]) for k in range(len(dates))] if dates else []
    avg_dd = (sum(dd_counts) / len(dd_counts)) if dd_counts else 0.0
    max_dd = max(dd_counts) if dd_counts else 0
    pct_ge_2 = (sum(1 for c in dd_counts if c >= 2) / len(dd_counts) * 100.0) if dd_counts else 0.0
    pct_ge_3 = (sum(1 for c in dd_counts if c >= 3) / len(dd_counts) * 100.0) if dd_counts else 0.0

    analysis = {
        "success": True,
        "pairs": syms,
        "dates_count": len(dates),
        "currency_exposure": _currency_exposure(syms),
        "correlation": {"pairs": syms, "matrix": corr_matrix},
        "drawdown_overlap": {"pairs": syms, "matrix": dd_overlap_matrix},
        "drawdown_flags_threshold_pct": 1.0,
        "drawdown_frequency_pct": dd_freq,
        "drawdown_concurrency": {
            "avg_pairs_in_drawdown": avg_dd,
            "max_pairs_in_drawdown": max_dd,
            "pct_days_ge_2_in_drawdown": pct_ge_2,
            "pct_days_ge_3_in_drawdown": pct_ge_3,
        },
        "skipped": skipped,
    }
    analysis["portfolio"] = _suggest_portfolios(results, analysis, max_size=4)
    return analysis


def _render_html(data: Dict[str, Any]) -> str:
    safe = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Multi-Pair Report - {data.get("ea_name","")}</title>
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
    .kpi .item {{ flex: 1 1 160px; padding: 10px; border: 1px solid var(--border); border-radius: 12px; background: rgba(255,255,255,0.02); }}
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
    .scroll {{ max-height: 520px; overflow:auto; border: 1px solid var(--border); border-radius: 12px; }}
    .matrix {{ width: auto; }}
    .matrix th, .matrix td {{ text-align: center; white-space: nowrap; }}
    .matrix th:first-child, .matrix td:first-child {{ text-align: left; }}
    .legend {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
    .swatch {{ width:14px; height:14px; border-radius:4px; border: 1px solid var(--border); display:inline-block; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>Multi-Pair Report: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          Timeframe: <span class="tag">{data.get("timeframe","")}</span>
          Period: <span class="tag">{data.get("from_date","")} → {data.get("to_date","")}</span>
          Primary: <span class="tag">{data.get("primary_pair","")}</span>
          Generated: <span class="tag">{data.get("generated_at","")}</span>
        </div>
      </div>
      <div class="subtitle" style="max-width:520px">
        Notes: This module reuses one parameter set across pairs. Don’t expect all pairs to work; use this to discover additional pairs and to assess concentration risk (currency exposure, return correlation, drawdown overlap).
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
          <div class="subtitle">Min Trades</div>
          <input id="fMinTrades" type="number" step="1" class="tag" style="background: transparent; width:120px" />
        </div>
        <div style="display:flex; flex-direction:column; gap:4px">
          <div class="subtitle">Sort</div>
          <select id="sortSelect" class="tag" style="background: transparent;">
            <option value="pf_desc">PF ↓</option>
            <option value="roi_desc">ROI% ↓</option>
            <option value="profit_desc">Net Profit ↓</option>
            <option value="dd_asc">DD% ↑</option>
            <option value="trades_desc">Trades ↓</option>
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

    <div class="card">
      <div class="subtitle">Concentration Risk (Correlation / Drawdown Overlap)</div>
      <div id="analysis"></div>
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

    const s = DATA.summary || {{}};
    addKpis([
      {{ label: 'Pairs Tested', value: String((DATA.pairs_tested || []).length), tip: 'How many symbols were tested.' }},
      {{ label: 'Pairs Profitable (PF>1)', value: String(s.pairs_profitable ?? '-'), tip: 'Count of pairs where PF > 1.0.' }},
      {{ label: 'Pairs Failed', value: String(s.pairs_failed ?? '-'), tip: 'Backtests that failed to run or parse.' }},
      {{ label: 'Avg PF', value: fmt(s.average_profit_factor, 2), tip: 'Average profit factor across successful pairs.' }},
      {{ label: 'PF Range', value: `${{fmt(s.min_profit_factor,2)}} - ${{fmt(s.max_profit_factor,2)}}`, tip: 'Min/max profit factor across successful pairs.' }},
      {{ label: 'Total Duration', value: fmt(DATA.total_duration_seconds, 1) + 's', tip: 'Wall-clock time for this multi-pair run.' }},
    ]);

    const COLS = [
      {{ id:'symbol', label:'Symbol', left:true, tip:'Trading symbol tested.' }},
      {{ id:'base', label:'Base', left:true, tip:'Base currency (first 3 letters of symbol).' }},
      {{ id:'quote', label:'Quote', left:true, tip:'Quote currency (last 3 letters of symbol).' }},
      {{ id:'profit_factor', label:'PF', tip:'Profit Factor = Gross Profit / |Gross Loss|.' }},
      {{ id:'roi_pct', label:'ROI%', tip:'(Net Profit / Initial Deposit) × 100.' }},
      {{ id:'total_profit', label:'Net Profit', tip:'Net profit for this pair/timeframe over the full period.' }},
      {{ id:'max_drawdown_pct', label:'Max DD%', tip:'Maximum relative drawdown percent.' }},
      {{ id:'total_trades', label:'Trades', tip:'Total trades.' }},
      {{ id:'history_quality', label:'History Quality', tip:'History quality as reported by MT5 for this test model.' }},
      {{ id:'bars', label:'Bars', tip:'Bars used (from MT5 report).' }},
      {{ id:'ticks', label:'Ticks', tip:'Ticks used (from MT5 report/model).' }},
      {{ id:'report_rel', label:'Report', tip:'Open the MT5 HTML report for this pair.' }},
    ];

    function buildRows() {{
      const rows = [];
      const results = DATA.results || {{}};
      for (const sym of Object.keys(results)) {{
        const r = results[sym] || {{}};
        const base = sym.slice(0,3);
        const quote = sym.slice(-3);
        rows.push({{
          symbol: sym,
          base,
          quote,
          success: !!r.success,
          profit_factor: num(r.profit_factor),
          roi_pct: num(r.roi_pct),
          total_profit: num(r.total_profit),
          max_drawdown_pct: num(r.max_drawdown_pct),
          total_trades: num(r.total_trades),
          history_quality: num(r.history_quality),
          bars: num(r.bars),
          ticks: num(r.ticks),
          report_rel: r.report_rel || null,
          error: r.error || null,
        }});
      }}
      return rows;
    }}

    function applyFilters(rows) {{
      const f = {{
        minPf: numOrNullFromInput('fMinPf'),
        minRoi: numOrNullFromInput('fMinRoi'),
        maxDd: numOrNullFromInput('fMaxDd'),
        minTrades: numOrNullFromInput('fMinTrades'),
      }};
      return rows.filter(r => {{
        if (!r.success) return false;
        if (f.minPf !== null && (r.profit_factor ?? -1e18) < f.minPf) return false;
        if (f.minRoi !== null && (r.roi_pct ?? -1e18) < f.minRoi) return false;
        if (f.maxDd !== null && (r.max_drawdown_pct ?? 1e18) > f.maxDd) return false;
        if (f.minTrades !== null && (r.total_trades ?? -1e18) < f.minTrades) return false;
        return true;
      }});
    }}

    function sortRows(rows) {{
      const mode = document.getElementById('sortSelect').value || 'pf_desc';
      const cmp = (a,b) => {{
        if (a === null && b === null) return 0;
        if (a === null) return 1;
        if (b === null) return -1;
        return a < b ? -1 : (a > b ? 1 : 0);
      }};
      const s = rows.slice();
      if (mode === 'custom' && SORT_COL) s.sort((x,y)=> SORT_DIR * cmp(x[SORT_COL], y[SORT_COL]));
      else if (mode === 'pf_desc') s.sort((x,y)=> -cmp(x.profit_factor, y.profit_factor));
      else if (mode === 'roi_desc') s.sort((x,y)=> -cmp(x.roi_pct, y.roi_pct));
      else if (mode === 'profit_desc') s.sort((x,y)=> -cmp(x.total_profit, y.total_profit));
      else if (mode === 'dd_asc') s.sort((x,y)=> cmp(x.max_drawdown_pct, y.max_drawdown_pct));
      else if (mode === 'trades_desc') s.sort((x,y)=> -cmp(x.total_trades, y.total_trades));
      return s;
    }}

    function cellText(colId, row) {{
      const v = row[colId];
      if (colId === 'symbol' || colId === 'base' || colId === 'quote') return v ?? '-';
      if (colId === 'report_rel') {{
        if (!v) return '-';
        return `<a href=\"${{escapeHtml(v)}}\">Open</a>`;
      }}
      if (['bars','ticks','total_trades'].includes(colId)) return v === null ? '-' : String(Math.trunc(Number(v)));
      if (['profit_factor','roi_pct','max_drawdown_pct','history_quality'].includes(colId)) return v === null ? '-' : fmt(v, 2);
      return v === null ? '-' : fmt(v, 2);
    }}

    function corrColor(v) {{
      if (v === null || v === undefined) return 'transparent';
      const x = Math.max(-1, Math.min(1, Number(v)));
      const a = Math.abs(x);
      const alpha = 0.08 + 0.55 * a;
      // blue for negative, red for positive
      if (x < 0) return `rgba(106,166,255,${{alpha}})`;
      return `rgba(255,107,107,${{alpha}})`;
    }}

    function overlapColor(v) {{
      if (v === null || v === undefined) return 'transparent';
      const x = Math.max(0, Math.min(100, Number(v)));
      const t = x / 100.0; // 0 good, 1 bad
      const r = Math.round(61 + (255 - 61) * t);
      const g = Math.round(220 + (107 - 220) * t);
      const b = Math.round(151 + (107 - 151) * t);
      const alpha = 0.08 + 0.55 * t;
      return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
    }}

    function renderMatrix(pairs, matrix, opts) {{
      const title = opts.title || '';
      const formatter = opts.formatter || ((v)=> v===null ? '-' : String(v));
      const colorFn = opts.colorFn || (()=>'transparent');

      if (!pairs || !matrix || pairs.length === 0) {{
        return `<div class=\"subtitle\">No ${{escapeHtml(title)}} data.</div>`;
      }}

      let html = `<div class=\"subtitle\" style=\"margin-top:12px\">${{escapeHtml(title)}}</div>`;
      if (opts.legendHtml) html += opts.legendHtml;
      html += '<div class=\"scroll\" style=\"max-height:360px\"><table class=\"matrix\"><thead><tr><th></th>';
      for (const p of pairs) html += `<th>${{escapeHtml(p)}}</th>`;
      html += '</tr></thead><tbody>';
      for (let i=0; i<pairs.length; i++) {{
        html += `<tr><td>${{escapeHtml(pairs[i])}}</td>`;
        for (let j=0; j<pairs.length; j++) {{
          const v = (matrix[i] || [])[j] ?? null;
          const bg = colorFn(v);
          const txt = formatter(v);
          const tip = (v === null || v === undefined) ? 'n/a' : String(v);
          html += `<td title=\"${{escapeHtml(tip)}}\" style=\"background:${{bg}}\">${{escapeHtml(txt)}}</td>`;
        }}
        html += '</tr>';
      }}
      html += '</tbody></table></div>';
      return html;
    }}

    function renderAnalysis() {{
      const root = document.getElementById('analysis');
      const a = DATA.analysis || {{}};
      if (!a.success) {{
        const err = a.error ? ` (${{escapeHtml(a.error)}})` : '';
        root.innerHTML = `<div class=\"subtitle\">No analysis available${{err}}.</div>`;
        return;
      }}

      let html = '';

      // Exposure
      const exp = a.currency_exposure || {{}};
      html += '<div class=\"subtitle\" style=\"margin-top:6px\">Currency Exposure</div>';
      html += '<div class=\"legend\" style=\"margin-top:6px\">';
      for (const k of Object.keys(exp)) {{
        html += `<span class=\"tag\" title=\"Number of tested pairs containing this currency\">${{escapeHtml(k)}}: ${{escapeHtml(exp[k])}}</span>`;
      }}
      html += '</div>';

      const conc = a.drawdown_concurrency || {{}};
      html += '<div class=\"subtitle\" style=\"margin-top:12px\">Drawdown Concurrency</div>';
      html += '<div class=\"legend\" style=\"margin-top:6px\">' +
        `<span class=\"tag\" title=\"Average number of pairs in drawdown on a day\">Avg in DD: ${{fmt(conc.avg_pairs_in_drawdown,2)}}</span>` +
        `<span class=\"tag\" title=\"Worst day: max pairs simultaneously in drawdown\">Max in DD: ${{escapeHtml(conc.max_pairs_in_drawdown ?? '-')}}</span>` +
        `<span class=\"tag\" title=\"Percent of days where at least 2 pairs were in drawdown\">Days ≥2 in DD: ${{fmt(conc.pct_days_ge_2_in_drawdown,1)}}%</span>` +
        `<span class=\"tag\" title=\"Percent of days where at least 3 pairs were in drawdown\">Days ≥3 in DD: ${{fmt(conc.pct_days_ge_3_in_drawdown,1)}}%</span>` +
        `<span class=\"tag\" title=\"Drawdown flag threshold used for overlap/concurrency\">DD flag: ≥${{fmt(a.drawdown_flags_threshold_pct ?? 1.0, 1)}}%</span>` +
        '</div>';

      // Portfolio suggestions (heuristic; see ROADMAP.md for improvements)
      function exposureText(exp) {{
        const e = exp || {{}};
        const ks = Object.keys(e).sort((a,b) => (e[b] - e[a]) || a.localeCompare(b));
        return ks.map(k => `${{k}}:${{e[k]}}`).join(' ');
      }}

      const port = a.portfolio || {{}};
      if (port.success && (port.recommendations || []).length) {{
        html += '<div class=\"subtitle\" style=\"margin-top:12px\">Portfolio Suggestions</div>';
        html += `<div class=\"subtitle\" style=\"margin-top:6px\">Objective: <span class=\"tag\">${{escapeHtml(port.constraints?.objective_formula ?? '')}}</span></div>`;
        html += '<div class=\"scroll\" style=\"max-height:240px\"><table><thead><tr>' +
          '<th title=\"Number of pairs in this suggested portfolio\">Size</th>' +
          '<th title=\"Suggested pairs\">Pairs</th>' +
          '<th title=\"Portfolio objective score (higher is better)\">Objective</th>' +
          '<th title=\"Sum of per-pair scores (before concentration penalty)\">SumScore</th>' +
          '<th title=\"Maximum absolute correlation between any two pairs in the set (lower is better)\">Max |Corr|</th>' +
          '<th title=\"Maximum drawdown-overlap between any two pairs in the set (lower is better)\">Max DD Overlap%</th>' +
          '<th title=\"Currency exposure counts across selected pairs\">Exposure</th>' +
          '</tr></thead><tbody>';
        for (const rec of port.recommendations) {{
          const ps = (rec.pairs || []).map(p => `<span class=\"tag\">${{escapeHtml(p)}}</span>`).join(' ');
          html += '<tr>' +
            `<td>${{escapeHtml(rec.size ?? '-')}}</td>` +
            `<td>${{ps}}</td>` +
            `<td>${{fmt(rec.objective, 2)}}</td>` +
            `<td>${{fmt(rec.sum_score, 2)}}</td>` +
            `<td>${{fmt(rec.max_abs_corr, 2)}}</td>` +
            `<td>${{fmt(rec.max_dd_overlap_pct, 1)}}</td>` +
            `<td>${{escapeHtml(exposureText(rec.currency_exposure))}}</td>` +
            '</tr>';
        }}
        html += '</tbody></table></div>';
      }} else {{
        html += '<div class=\"subtitle\" style=\"margin-top:12px\">Portfolio Suggestions</div>';
        html += '<div class=\"subtitle\" style=\"margin-top:6px\">No profitable portfolio candidates found in this run.</div>';
      }}

      const pairs = (a.correlation || {{}}).pairs || [];
      const corr = (a.correlation || {{}}).matrix || [];
      const dd = (a.drawdown_overlap || {{}}).matrix || [];

      html += renderMatrix(pairs, corr, {{
        title: 'Daily Return Correlation (Net Profit per day)',
        formatter: (v) => v===null ? '-' : fmt(v,2),
        colorFn: corrColor,
        legendHtml: '<div class=\"legend\" style=\"margin-top:6px\">' +
          '<span class=\"swatch\" style=\"background: rgba(106,166,255,0.45)\"></span><span class=\"subtitle\">negative</span>' +
          '<span class=\"swatch\" style=\"background: rgba(255,107,107,0.45)\"></span><span class=\"subtitle\">positive</span>' +
          '<span class=\"subtitle\">(zeros on no-trade days)</span>' +
          '</div>',
      }});

      html += renderMatrix(pairs, dd, {{
        title: `Drawdown Overlap (% of days both in drawdown, DD≥${{fmt(a.drawdown_flags_threshold_pct ?? 1.0, 1)}}%)`,
        formatter: (v) => v===null ? '-' : fmt(v,1),
        colorFn: overlapColor,
        legendHtml: '<div class=\"legend\" style=\"margin-top:6px\">' +
          '<span class=\"swatch\" style=\"background: rgba(61,220,151,0.45)\"></span><span class=\"subtitle\">low overlap</span>' +
          '<span class=\"swatch\" style=\"background: rgba(255,107,107,0.45)\"></span><span class=\"subtitle\">high overlap</span>' +
          '</div>',
      }});

      const skipped = a.skipped || {{}};
      const skippedKeys = Object.keys(skipped);
      if (skippedKeys.length) {{
        html += '<div class=\"subtitle\" style=\"margin-top:12px\">Skipped</div>';
        html += '<div class=\"legend\" style=\"margin-top:6px\">';
        for (const k of skippedKeys) {{
          html += `<span class=\"tag\" title=\"${{escapeHtml(skipped[k])}}\">${{escapeHtml(k)}}</span>`;
        }}
        html += '</div>';
      }}

      root.innerHTML = html;
    }}

    function render() {{
      const allRows = buildRows();
      const rows = sortRows(applyFilters(allRows));
      document.getElementById('tableStats').textContent = `Showing ${{rows.length}} / ${{allRows.length}} pairs`;

      let html = '<div class=\"scroll\"><table><thead><tr>';
      for (const c of COLS) {{
        const sortable = !['symbol','base','quote','report_rel'].includes(c.id);
        const cls = sortable ? ' class=\"sortable\"' : '';
        const data = sortable ? ` data-col=\"${{c.id}}\"` : '';
        const tip = c.tip ? ` title=\"${{escapeHtml(c.tip)}}\"` : '';
        const active = (document.getElementById('sortSelect').value === 'custom' && SORT_COL === c.id);
        const arrow = active ? (SORT_DIR < 0 ? '↓' : '↑') : '';
        const indicator = sortable ? `<span class=\"sort-indicator\">${{arrow}}</span>` : '';
        html += `<th${{cls}}${{data}}${{tip}}>${{c.label}}${{indicator}}</th>`;
      }}
      html += '</tr></thead><tbody>';
      for (const r of rows) {{
        html += '<tr>';
        for (const c of COLS) {{
          const text = cellText(c.id, r);
          const alignLeft = c.left ? ' style=\"text-align:left\"' : '';
          html += `<td${{alignLeft}}>${{text}}</td>`;
        }}
        html += '</tr>';
      }}
      html += '</tbody></table></div>';
      document.getElementById('table').innerHTML = html;
    }}

    document.getElementById('table').addEventListener('click', (ev) => {{
      const th = ev.target.closest('th[data-col]');
      if (!th) return;
      const col = th.dataset.col;
      if (!col) return;
      if (SORT_COL === col) SORT_DIR = -SORT_DIR;
      else {{
        SORT_COL = col;
        SORT_DIR = (['max_drawdown_pct'].includes(col)) ? 1 : -1;
      }}
      document.getElementById('sortSelect').value = 'custom';
      render();
    }});

    for (const id of ['fMinPf','fMinRoi','fMaxDd','fMinTrades','sortSelect']) {{
      const el = document.getElementById(id);
      el.addEventListener('change', render);
      el.addEventListener('input', render);
    }}
    document.getElementById('resetFilters').addEventListener('click', () => {{
      for (const id of ['fMinPf','fMinRoi','fMaxDd','fMinTrades']) document.getElementById(id).value = '';
      document.getElementById('sortSelect').value = 'pf_desc';
      SORT_COL = null; SORT_DIR = -1;
      render();
    }});

    render();
    renderAnalysis();
  </script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a multi-pair follow-up test and generate an offline report")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses latest workflow state in runs/)")
    ap.add_argument("--pairs", nargs="+", help="Pairs to test (default: majors basket)")
    ap.add_argument("--timeframe", type=str, help="Timeframe (default: from state or config)")
    ap.add_argument("--from-date", dest="from_date", type=str, help="From date YYYY.MM.DD")
    ap.add_argument("--to-date", dest="to_date", type=str, help="To date YYYY.MM.DD")
    ap.add_argument("--timeout", type=int, default=600, help="Timeout per pair in seconds")
    ap.add_argument("--params", type=str, help="EA parameters JSON file path or inline JSON string")
    ap.add_argument("--out", type=str, help="Output directory (default: runs/multipair/{EA}_YYYYMMDD_HHMMSS)")
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

    symbol = state.get("symbol") or DEFAULT_SYMBOL
    timeframe = args.timeframe or state.get("timeframe") or DEFAULT_TIMEFRAME

    from_date = args.from_date or BACKTEST_FROM
    to_date = args.to_date or BACKTEST_TO

    # Prefer the workflow's test window if present (from Step 6 INI)
    steps = state.get("steps", {}) or {}
    step6 = steps.get("6_create_opt_ini", {}).get("output", {}) if steps.get("6_create_opt_ini") else {}
    if isinstance(step6, dict) and (not args.from_date or not args.to_date):
        ins_pair = _parse_date_pair(step6.get("in_sample", "") or "")
        fwd_pair = _parse_date_pair(step6.get("forward_test", "") or "")
        if ins_pair and not args.from_date:
            from_date = ins_pair[0]
        if fwd_pair and not args.to_date:
            to_date = fwd_pair[1]

    # Parameters
    inputs: Optional[Dict[str, Any]] = None
    if args.params:
        inputs = load_params(args.params)
    else:
        inputs = _pick_params_from_state(state)
        if inputs is None:
            # Fallback to runs/{EA}_best_params.json
            fallback = RUNS_DIR / f"{ea_name}_best_params.json"
            if fallback.exists():
                inputs = load_params(str(fallback))

    if not inputs:
        raise SystemExit("Could not load best parameters (provide --params or ensure workflow has 8_parse_results.params_file)")

    # Output
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else (RUNS_DIR / "multipair" / f"{ea_name}_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    tester = MultiPairTester(pairs=args.pairs, timeout_per_pair=int(args.timeout), run_dir=out_dir / "backtests", inputs=inputs)
    res = tester.test(ea_name=ea_name, primary_pair=symbol, timeframe=timeframe, from_date=from_date, to_date=to_date)

    # Build report-friendly dict with relative links
    results: Dict[str, Any] = {}
    for sym, pr in (res.results or {}).items():
        d = pr.to_dict()
        rp = d.get("report_path")
        report_rel = None
        if rp:
            try:
                report_rel = Path(rp).relative_to(out_dir).as_posix()
            except Exception:
                report_rel = rp
        d["report_rel"] = report_rel
        results[sym] = d

    data = {
        "ea_name": res.ea_name,
        "primary_pair": res.primary_pair,
        "pairs_tested": res.pairs_tested,
        "timeframe": timeframe,
        "from_date": from_date,
        "to_date": to_date,
        "generated_at": ts,
        "total_duration_seconds": res.total_duration,
        "summary": res.to_dict().get("summary", {}),
        "results": results,
    }
    data["analysis"] = _compute_concentration_analysis(results)

    (out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    index_path = out_dir / "index.html"
    index_path.write_text(_render_html(data), encoding="utf-8")

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


if __name__ == "__main__":
    main()
