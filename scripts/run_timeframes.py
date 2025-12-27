#!/usr/bin/env python3
"""
Run a post-test timeframe sweep and generate an offline HTML report.

This is an OPTIONAL module (not part of the core 1-pair pipeline).

It reuses a single parameter set (typically the best params from the workflow)
and runs the EA on the same symbol across multiple timeframes.

Usage:
  python scripts/run_timeframes.py --state runs/workflow_EA_*.json --open
  python scripts/run_timeframes.py --ea Overlap_Momentum_Shield_Safe --params runs/EA_best_params.json --timeframes M15 H1 H4 --open
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BACKTEST_FROM, BACKTEST_TO, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, RUNS_DIR
from parser.report import ReportParser
from parser.trade_extractor import extract_trades
from tester.backtest import BacktestRunner
from tester.multipair import load_params


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
  <title>Timeframe Sweep - {data.get("ea_name","")}</title>
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
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <div>
        <h1>Timeframe Sweep: {data.get("ea_name","")}</h1>
        <div class="subtitle">
          Symbol: <span class="tag">{data.get("symbol","")}</span>
          Period: <span class="tag">{data.get("from_date","")} → {data.get("to_date","")}</span>
          Generated: <span class="tag">{data.get("generated_at","")}</span>
        </div>
      </div>
      <div class="subtitle" style="max-width:520px">
        Notes: This module reuses one parameter set across timeframes. Expect differences; use this to find where the strategy behaves best.
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
            <option value="roi_desc">ROI% ↓</option>
            <option value="pf_desc">PF ↓</option>
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

    const results = DATA.results || {{}};
    const rowsAll = Object.keys(results).map(tf => {{
      const r = results[tf] || {{}};
      return {{
        timeframe: tf,
        success: !!r.success,
        profit_factor: num(r.profit_factor),
        roi_pct: num(r.roi_pct),
        total_profit: num(r.total_profit),
        max_drawdown_pct: num(r.max_drawdown_pct),
        total_trades: num(r.total_trades),
        history_quality: num(r.history_quality),
        bars: num(r.bars),
        ticks: num(r.ticks),
        commission: num(r.total_commission),
        swap: num(r.total_swap),
        report_rel: r.report_rel || null,
        error: r.error || null,
      }};
    }});

    const ok = rowsAll.filter(r => r.success);
    const bestRoi = ok.slice().sort((a,b) => (b.roi_pct ?? -1e18) - (a.roi_pct ?? -1e18))[0];
    addKpis([
      {{ label: 'Timeframes Tested', value: String(rowsAll.length), tip: 'How many timeframes were tested.' }},
      {{ label: 'Successful', value: String(ok.length), tip: 'How many backtests produced a readable report.' }},
      {{ label: 'Best ROI%', value: bestRoi ? (fmt(bestRoi.roi_pct,2) + '%') : '-', tip: 'Highest ROI% timeframe.' }},
      {{ label: 'Best ROI TF', value: bestRoi ? bestRoi.timeframe : '-', tip: 'Timeframe with highest ROI%.' }},
      {{ label: 'Total Duration', value: fmt(DATA.total_duration_seconds, 1) + 's', tip: 'Wall-clock time for this sweep.' }},
    ]);

    const COLS = [
      {{ id:'timeframe', label:'Timeframe', left:true, tip:'Timeframe tested.' }},
      {{ id:'roi_pct', label:'ROI%', tip:'(Net Profit / Initial Deposit) × 100.' }},
      {{ id:'profit_factor', label:'PF', tip:'Profit Factor = Gross Profit / |Gross Loss|.' }},
      {{ id:'total_profit', label:'Net Profit', tip:'Net profit over the full period.' }},
      {{ id:'max_drawdown_pct', label:'Max DD%', tip:'Maximum relative drawdown percent.' }},
      {{ id:'total_trades', label:'Trades', tip:'Total trades.' }},
      {{ id:'commission', label:'Commission', tip:'Total commission from Deals table (negative is cost).' }},
      {{ id:'swap', label:'Swap', tip:'Total swap from Deals table (negative is cost).' }},
      {{ id:'history_quality', label:'History Quality', tip:'History quality as reported by MT5.' }},
      {{ id:'bars', label:'Bars', tip:'Bars used (from MT5 report).' }},
      {{ id:'ticks', label:'Ticks', tip:'Ticks used (from MT5 report/model).' }},
      {{ id:'report_rel', label:'Report', tip:'Open the MT5 HTML report.' }},
    ];

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
      const mode = document.getElementById('sortSelect').value || 'roi_desc';
      const cmp = (a,b) => {{
        if (a === null && b === null) return 0;
        if (a === null) return 1;
        if (b === null) return -1;
        return a < b ? -1 : (a > b ? 1 : 0);
      }};
      const s = rows.slice();
      if (mode === 'custom' && SORT_COL) s.sort((x,y)=> SORT_DIR * cmp(x[SORT_COL], y[SORT_COL]));
      else if (mode === 'roi_desc') s.sort((x,y)=> -cmp(x.roi_pct, y.roi_pct));
      else if (mode === 'pf_desc') s.sort((x,y)=> -cmp(x.profit_factor, y.profit_factor));
      else if (mode === 'profit_desc') s.sort((x,y)=> -cmp(x.total_profit, y.total_profit));
      else if (mode === 'dd_asc') s.sort((x,y)=> cmp(x.max_drawdown_pct, y.max_drawdown_pct));
      else if (mode === 'trades_desc') s.sort((x,y)=> -cmp(x.total_trades, y.total_trades));
      return s;
    }}

    function cellText(colId, row) {{
      const v = row[colId];
      if (colId === 'timeframe') return v ?? '-';
      if (colId === 'report_rel') {{
        if (!v) return '-';
        return `<a href=\"${{escapeHtml(v)}}\">Open</a>`;
      }}
      if (['bars','ticks','total_trades'].includes(colId)) return v === null ? '-' : String(Math.trunc(Number(v)));
      if (['profit_factor','roi_pct','max_drawdown_pct','history_quality'].includes(colId)) return v === null ? '-' : fmt(v, 2);
      return v === null ? '-' : fmt(v, 2);
    }}

    function render() {{
      const rows = sortRows(applyFilters(rowsAll));
      document.getElementById('tableStats').textContent = `Showing ${{rows.length}} / ${{rowsAll.length}} timeframes`;
      let html = '<div class=\"scroll\"><table><thead><tr>';
      for (const c of COLS) {{
        const sortable = !['timeframe','report_rel'].includes(c.id);
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
      document.getElementById('sortSelect').value = 'roi_desc';
      SORT_COL = null; SORT_DIR = -1;
      render();
    }});

    render();
  </script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a timeframe sweep and generate an offline report")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses latest workflow state in runs/)")
    ap.add_argument("--symbol", type=str, help="Symbol (default: from state or config)")
    ap.add_argument("--timeframes", nargs="+", default=["M15", "H1", "H4"], help="Timeframes to test")
    ap.add_argument("--from-date", dest="from_date", type=str, help="From date YYYY.MM.DD")
    ap.add_argument("--to-date", dest="to_date", type=str, help="To date YYYY.MM.DD")
    ap.add_argument("--timeout", type=int, default=900, help="Timeout per timeframe in seconds")
    ap.add_argument("--params", type=str, help="EA parameters JSON file path or inline JSON string")
    ap.add_argument("--out", type=str, help="Output directory (default: runs/timeframes/{EA}_YYYYMMDD_HHMMSS)")
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
    out_dir = Path(args.out) if args.out else (RUNS_DIR / "timeframes" / f"{ea_name}_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    runner = BacktestRunner(timeout=int(args.timeout))
    rp = ReportParser()
    start = time.time()

    results: Dict[str, Any] = {}
    for tf in args.timeframes:
        tf_dir = out_dir / "backtests" / tf
        tf_dir.mkdir(parents=True, exist_ok=True)
        print(f"Testing {ea_name} on {symbol} {tf}...")

        bt = runner.run(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=tf,
            from_date=from_date,
            to_date=to_date,
            run_dir=tf_dir,
            inputs=inputs,
        )

        if not bt.success or not bt.report_path:
            results[tf] = {"success": False, "error": bt.error or "Backtest failed"}
            continue

        metrics = rp.parse(bt.report_path)
        extraction = extract_trades(str(bt.report_path))

        total_commission = extraction.total_commission if extraction.success else None
        total_swap = extraction.total_swap if extraction.success else None

        report_rel = bt.report_path.relative_to(out_dir).as_posix()
        results[tf] = {
            "success": True,
            "profit_factor": getattr(metrics, "profit_factor", 0.0) if metrics else 0.0,
            "total_profit": getattr(metrics, "total_net_profit", 0.0) if metrics else 0.0,
            "roi_pct": getattr(metrics, "roi_pct", 0.0) if metrics else 0.0,
            "max_drawdown_pct": getattr(metrics, "max_drawdown_pct", 0.0) if metrics else 0.0,
            "total_trades": getattr(metrics, "total_trades", 0) if metrics else 0,
            "history_quality": getattr(metrics, "history_quality", 0.0) if metrics else 0.0,
            "bars": getattr(metrics, "bars", 0) if metrics else 0,
            "ticks": getattr(metrics, "ticks", 0) if metrics else 0,
            "total_commission": total_commission,
            "total_swap": total_swap,
            "report_rel": report_rel,
        }

    data = {
        "ea_name": ea_name,
        "symbol": symbol,
        "timeframes": args.timeframes,
        "from_date": from_date,
        "to_date": to_date,
        "generated_at": ts,
        "total_duration_seconds": time.time() - start,
        "results": results,
    }

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

