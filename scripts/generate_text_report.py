#!/usr/bin/env python3
"""
Generate a human-readable text report from a workflow state file.

This complements the HTML dashboard by outputting key metrics + pass/fail gates,
including ROI, backtest quality (History Quality), and trading costs (commission/swap).

Usage:
  python scripts/generate_text_report.py --state runs/workflow_EA_*.json
  python scripts/generate_text_report.py --ea EA_Name
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import RUNS_DIR
from parser.report import ReportParser
from parser.trade_extractor import extract_trades
from settings import get_settings


def _find_latest_workflow_state(ea_name: str) -> Optional[Path]:
    candidates = sorted(RUNS_DIR.glob(f"workflow_{ea_name}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_history_quality(report_path: Path) -> Optional[str]:
    try:
        txt = report_path.read_bytes().decode("utf-16", errors="ignore")
    except OSError:
        return None
    m = re.search(r"History Quality[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>", txt, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a text report for a stress-test workflow run")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses the latest workflow state in runs/)")
    ap.add_argument("--out", type=str, help="Output report path (default: runs/{EA}_REPORT.txt)")
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

    state = _load_json(state_path)
    ea_name = state.get("ea_name") or args.ea
    if not ea_name:
        raise SystemExit("Could not determine ea_name from state")

    symbol = state.get("symbol") or "EURUSD"
    timeframe = state.get("timeframe") or "H1"
    steps = state.get("steps", {}) or {}

    step5 = (steps.get("5_validate_trades") or {}).get("output", {}) or {}
    step8 = (steps.get("8_parse_results") or {}).get("output", {}) or {}
    step9 = (steps.get("9_backtest_robust") or {}).get("output", {}) or {}
    step10 = (steps.get("10_monte_carlo") or {}).get("output", {}) or {}
    step11 = (steps.get("11_report") or {}).get("output", {}) or {}

    validation_report = step5.get("report_path")
    robust_report = step9.get("report_path")
    robust_params = step8.get("params_file")
    dashboard = step11.get("dashboard_index") or step11.get("dashboard") or None

    rp = ReportParser()
    s = get_settings()

    # Robust report parsing + costs/ROI from deals
    robust_metrics = None
    extraction = None
    initial_balance = None
    net_profit = None
    roi_pct = None
    history_quality = None

    if robust_report:
        rpath = Path(robust_report)
        if rpath.exists():
            robust_metrics = rp.parse(rpath)
            extraction = extract_trades(str(rpath))
            history_quality = _extract_history_quality(rpath)

            if extraction and extraction.success:
                initial_balance = float(extraction.initial_balance or (robust_metrics.initial_deposit if robust_metrics else 0.0) or 0.0)
                net_profit = float(extraction.total_net_profit)
                roi_pct = (net_profit / initial_balance * 100.0) if initial_balance else None

    pf = float(step9.get("profit_factor") or (robust_metrics.profit_factor if robust_metrics else 0.0) or 0.0)
    dd = float(step9.get("max_drawdown_pct") or (robust_metrics.max_drawdown_pct if robust_metrics else 0.0) or 0.0)
    trades = int(step9.get("total_trades") or (robust_metrics.total_trades if robust_metrics else 0) or 0)
    win_rate = float(step9.get("win_rate") or (robust_metrics.win_rate if robust_metrics else 0.0) or 0.0)

    mc_conf = float(step10.get("confidence_level") or 0.0)
    mc_ruin = float(step10.get("probability_of_ruin") or 100.0)

    passes = []
    fails = []

    def chk(name: str, ok: bool) -> None:
        (passes if ok else fails).append(name)

    chk("profit_factor", pf >= s.thresholds.min_profit_factor)
    chk("max_drawdown", dd <= s.thresholds.max_drawdown_pct)
    chk("min_trades", trades >= s.thresholds.min_trades)
    chk("min_win_rate", win_rate >= s.thresholds.min_win_rate)
    chk("mc_confidence", mc_conf >= s.monte_carlo.confidence_min)
    chk("ruin_probability", mc_ruin <= s.monte_carlo.max_ruin_probability)

    overall = "PASS" if not fails else ("CONDITIONAL PASS" if "profit_factor" in fails and len(fails) == 1 else "FAIL")

    out_path = Path(args.out) if args.out else (RUNS_DIR / f"{ea_name}_REPORT.txt")

    lines = []
    lines.append("=" * 80)
    lines.append(f"STRESS TEST REPORT: {ea_name}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Symbol: {symbol}")
    lines.append(f"Timeframe: {timeframe}")
    lines.append(f"State: {state_path}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("--- Validation Backtest (wide params) ---")
    lines.append(f"Report: {validation_report or '-'}")
    if isinstance(step5.get("metrics"), dict):
        lines.append(f"Trades: {step5.get('trades', '-')}")
        lines.append(f"PF: {step5['metrics'].get('profit_factor', '-')}")
    lines.append("")

    lines.append("--- Optimization ---")
    lines.append(f"Total passes: {step8.get('total_passes', '-')}")
    lines.append(f"Robust passes: {step8.get('robust_passes', '-')} ({step8.get('robustness_rate', '-')})")
    lines.append(f"Best pass: {step8.get('best_pass', '-')}")
    lines.append(f"Best params: {robust_params or '-'}")
    lines.append("")

    lines.append("--- Robust Backtest (best params) ---")
    lines.append(f"Report: {robust_report or '-'}")
    if robust_metrics:
        lines.append(f"History Quality: {history_quality or (str(robust_metrics.history_quality) + '%')}")
        if robust_metrics.bars or robust_metrics.ticks:
            lines.append(f"Bars: {robust_metrics.bars} | Ticks: {robust_metrics.ticks}")
        if initial_balance is not None:
            lines.append(f"Initial Deposit: {initial_balance:.2f}")
        if net_profit is not None:
            lines.append(f"Net Profit: {net_profit:.2f}")
        if roi_pct is not None:
            lines.append(f"ROI: {roi_pct:.2f}%")
        lines.append(f"Profit Factor: {pf:.2f}")
        lines.append(f"Max Drawdown %: {dd:.2f}")
        lines.append(f"Trades: {trades}")
        lines.append(f"Win Rate %: {win_rate:.2f}")
        if extraction and extraction.success:
            lines.append(f"Commission (total): {extraction.total_commission:.2f}")
            lines.append(f"Swap (total): {extraction.total_swap:.2f}")
    lines.append("")

    lines.append("--- Monte Carlo (trade-order risk) ---")
    lines.append(f"Iterations: {step10.get('iterations', '-')}")
    lines.append(f"Confidence Level: {mc_conf:.1f}%")
    lines.append(f"Probability of Ruin: {mc_ruin:.1f}% (threshold {s.monte_carlo.max_ruin_probability}%)")
    lines.append(f"Robust: {'YES' if step10.get('is_robust') else 'NO'}")
    lines.append("")

    lines.append("--- Dashboard ---")
    lines.append(f"Dashboard: {dashboard or '-'}")
    lines.append("")

    lines.append("--- Final Assessment ---")
    lines.append(f"Overall: {overall}")
    lines.append(f"Passes: {', '.join(passes) if passes else '-'}")
    lines.append(f"Fails: {', '.join(fails) if fails else '-'}")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # Update state file Step 11 output (keeps dashboard + text report consistent)
    try:
        if isinstance(state.get("steps"), dict):
            step11_state = state["steps"].get("11_report")
            if isinstance(step11_state, dict):
                step11_state.setdefault("output", {})
                if isinstance(step11_state.get("output"), dict):
                    step11_state["output"].update(
                        {
                            "report_file": str(out_path.resolve()),
                            "overall_result": overall,
                            "passes": passes,
                            "fails": fails,
                        }
                    )
            state["updated_at"] = datetime.now().isoformat()
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        # Best-effort; report generation should still succeed even if state update fails.
        pass

    print(
        json.dumps(
            {
                "success": True,
                "ea_name": ea_name,
                "state_file": str(state_path),
                "report_file": str(out_path.resolve()),
                "overall_result": overall,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
