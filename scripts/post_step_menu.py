#!/usr/bin/env python3
"""
Post-Step Menu / Advisor

Reads a workflow state file and prints:
- Which post-step modules exist (implemented vs planned)
- Which have already been run (from state["post_steps"])
- Recommended next modules based on the observed results

This exists to reduce "LLM forgetting" by making the system's next actions
discoverable and repeatable via a single command.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import RUNS_DIR
from settings import get_settings
from workflow.post_step_modules import POST_STEP_MODULES, PostStepModule


def _find_latest_workflow_state(ea_name: str) -> Optional[Path]:
    candidates = sorted(RUNS_DIR.glob(f"workflow_{ea_name}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_state(state_path: Path) -> Dict[str, Any]:
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _last_post_step_run(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in state.get("post_steps", []) or []:
        if not isinstance(r, dict):
            continue
        name = r.get("name")
        if not name:
            continue
        # Keep the last one in file order (append-only).
        out[str(name)] = r
    return out


def _recommendations(state: Dict[str, Any]) -> list[dict]:
    settings = get_settings()
    min_pf = float(settings.thresholds.min_profit_factor)
    max_dd = float(settings.thresholds.max_drawdown_pct)
    min_trades = int(settings.thresholds.min_trades)

    steps = state.get("steps", {}) or {}
    step11 = (steps.get("11_report") or {})
    step11_out = (step11.get("output") or {}) if isinstance(step11, dict) else {}
    overall = str(step11_out.get("overall_result") or "")
    fails = step11_out.get("fails") or []

    step9 = (steps.get("9_backtest_robust") or {})
    step9_out = (step9.get("output") or {}) if isinstance(step9, dict) else {}
    pf = float(step9_out.get("profit_factor") or 0.0)
    dd = float(step9_out.get("max_drawdown_pct") or 0.0)
    trades = int(float(step9_out.get("total_trades") or 0))

    step8 = (steps.get("8_parse_results") or {})
    step8_out = (step8.get("output") or {}) if isinstance(step8, dict) else {}
    fwd_pf = float(step8_out.get("forward_pf") or 0.0)
    fwd_profit = float(step8_out.get("forward_profit") or 0.0)

    recs: list[dict] = []

    # Execution stress is generally the first "confidence booster" once you have a candidate.
    if "profit_factor" in [str(x) for x in fails] or "CONDITIONAL" in overall.upper() or pf < min_pf:
        recs.append(
            {
                "module": "execution_stress",
                "priority": 1,
                "reason": f"PF is {pf:.2f} vs target {min_pf:.2f}; confirm it survives worse spread/slippage/commission assumptions.",
            }
        )
    else:
        recs.append(
            {
                "module": "execution_stress",
                "priority": 2,
                "reason": "Run anyway to quantify robustness to real-world execution.",
            }
        )

    # Walk-forward: recommend when forward is weak OR when results are borderline and need more confidence.
    if (fwd_profit < 0) or (fwd_pf and fwd_pf < 1.1):
        recs.append(
            {
                "module": "walk_forward",
                "priority": 1,
                "reason": f"Forward segment looks weak (FWD PF {fwd_pf:.2f}, FWD profit {fwd_profit:.2f}); multi-fold WF is the next best overfit check.",
            }
        )
    elif ("CONDITIONAL" in overall.upper()) or (pf < min_pf) or (fwd_pf and fwd_pf < 1.2):
        recs.append(
            {
                "module": "walk_forward",
                "priority": 2,
                "reason": "Run multi-fold walk-forward to reduce reliance on a single split and quantify OOS stability across regimes.",
            }
        )

    # Parameter sensitivity: recommend when DD is high-ish or PF is borderline.
    if dd > (0.8 * max_dd) or pf < (min_pf + 0.2):
        recs.append(
            {
                "module": "param_sensitivity",
                "priority": 2,
                "reason": "Check for knife-edge parameters (small tweaks causing collapse).",
            }
        )

    # Multi-pair/timeframes: always useful, but especially after single-pair success.
    recs.append(
        {
            "module": "multipair",
            "priority": 3,
            "reason": "See if the edge generalizes and measure correlation/drawdown overlap for portfolio risk.",
        }
    )
    recs.append(
        {
            "module": "timeframes",
            "priority": 3,
            "reason": "See which timeframes the strategy behaves best on (regime dependence).",
        }
    )

    # Trade count warning.
    if trades and trades < min_trades:
        recs.append(
            {
                "module": None,
                "priority": 0,
                "reason": f"Trade count is low ({trades} < {min_trades}). Consider longer date range or a lower timeframe before trusting metrics.",
            }
        )

    # Sort by priority then module id for stable output.
    recs.sort(key=lambda r: (r.get("priority", 9), str(r.get("module") or "")))
    return recs


def _fmt_run(run: Dict[str, Any]) -> str:
    status = run.get("status") or "?"
    done = run.get("completed_at") or run.get("started_at") or ""
    out = run.get("output") or {}
    index = out.get("index") or out.get("dashboard_index") or ""
    return f"{status} ({done}) {index}".strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Show post-step optional modules + recommendations for a workflow state")
    ap.add_argument("--state", type=str, help="Path to runs/workflow_*.json")
    ap.add_argument("--ea", type=str, help="EA name (uses latest workflow state in runs/)")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    ap.add_argument("--open-dashboard", action="store_true", help="Open the main dashboard from Step 11 if present")
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
    ea_name = state.get("ea_name") or args.ea or "?"

    steps = state.get("steps", {}) or {}
    step11 = steps.get("11_report", {}) or {}
    dash = None
    if isinstance(step11, dict):
        dash = (step11.get("output") or {}).get("dashboard_index")

    last_runs = _last_post_step_run(state)
    recs = _recommendations(state)

    payload = {
        "ea_name": ea_name,
        "state_file": str(state_path),
        "dashboard_index": dash,
        "modules": [
            {
                "id": m.id,
                "title": m.title,
                "description": m.description,
                "implemented": m.implemented,
                "command": (m.command_template.format(state=str(state_path)) if "{state}" in m.command_template else m.command_template),
                "last_run": last_runs.get(m.state_key or m.id),
            }
            for m in POST_STEP_MODULES
        ],
        "recommendations": recs,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"EA: {ea_name}")
    print(f"State: {state_path}")
    if dash:
        print(f"Dashboard: {dash}")
    print("")

    print("Recommended next actions:")
    for r in recs:
        mod = r.get("module")
        reason = r.get("reason") or ""
        if mod:
            print(f"  - {mod}: {reason}")
        else:
            print(f"  - NOTE: {reason}")
    print("")

    print("Available post-step modules:")
    for m in POST_STEP_MODULES:
        run = last_runs.get(m.state_key or m.id)
        status = "[PLANNED]" if not m.implemented else ("[DONE]" if run and run.get("status") == "passed" else "[READY]")
        print(f"  - {status} {m.id}: {m.title}")
        print(f"      {m.description}")
        if run:
            print(f"      last run: {_fmt_run(run)}")
        print(f"      cmd: {m.command_template.format(state=str(state_path)) if '{state}' in m.command_template else m.command_template}")
    print("")

    if args.open_dashboard and dash:
        import subprocess

        try:
            subprocess.Popen(["cmd", "/c", "start", str(Path(dash).resolve())], shell=False)
        except Exception:
            pass


if __name__ == "__main__":
    main()
