#!/usr/bin/env python3
"""
Run the core stress-test workflow (Steps 1-11) with state tracking.

This is designed to be callable from:
- CLI (manual runs)
- Local web UI (scripts/web_app.py) as a background job
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from compiler import Compiler
from config import (
    BACKTEST_FROM,
    BACKTEST_TO,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    MT5_DATA_PATH,
    MT5_EXPERTS_PATH,
    PROJECT_ROOT,
    RUNS_DIR,
)
from optimizer.ini_builder import create_optimization_from_ea
from optimizer.param_extractor import ParameterExtractor
from optimizer.param_intelligence import analyze_ea, generate_opt_inputs, generate_wide_params_json
from optimizer.result_parser import OptimizationResultParser
from parser.report import ReportParser
from scripts.inject_ontester import process_ea as inject_ontester
from scripts.inject_safety import process_ea as inject_safety
from scripts.run_optimization import run_optimization as run_mt5_optimization
from settings import get_settings
from tester.backtest import BacktestRunner
from tester.montecarlo import run_montecarlo
from workflow.state_manager import STEP_DEPENDENCIES, WORKFLOW_STEPS, WorkflowStateManager


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _expand_deps(selected: Set[str]) -> Set[str]:
    changed = True
    while changed:
        changed = False
        for s in list(selected):
            for dep in STEP_DEPENDENCIES.get(s, []):
                if dep not in selected:
                    selected.add(dep)
                    changed = True
    return selected


def _parse_jsonish_stdout(stdout: str) -> Dict[str, Any]:
    txt = (stdout or "").strip()
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        # Best-effort: take last JSON object in the output.
        start = txt.rfind("{")
        if start >= 0:
            try:
                return json.loads(txt[start:])
            except Exception:
                pass
    raise ValueError("Could not parse JSON from stdout")


def _run_script_json(args: List[str]) -> Dict[str, Any]:
    import subprocess

    res = subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError((res.stdout + "\n" + res.stderr).strip() or f"Script failed: {args}")
    return _parse_jsonish_stdout(res.stdout)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _import_ea_to_test_terminal(source_mq5: Path) -> Dict[str, Any]:
    """
    Ensure the EA lives in the configured test terminal Experts folder.

    If it is already there: no copy.
    Otherwise: copy with a unique suffix to avoid clobbering existing files.
    """
    source_mq5 = source_mq5.resolve()
    if not source_mq5.exists():
        raise FileNotFoundError(str(source_mq5))
    if source_mq5.suffix.lower() != ".mq5":
        raise ValueError(f"EA must be a .mq5 file: {source_mq5}")

    MT5_EXPERTS_PATH.mkdir(parents=True, exist_ok=True)
    if _is_under(source_mq5, MT5_EXPERTS_PATH):
        return {"ea_path": str(source_mq5), "ea_name": source_mq5.stem, "imported": False}

    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = MT5_EXPERTS_PATH / f"{source_mq5.stem}_IMPORTED_{ts}.mq5"
    shutil.copy2(source_mq5, dest)
    return {"ea_path": str(dest), "ea_name": dest.stem, "imported": True, "source_path": str(source_mq5)}


def _enabled_steps_from_options(opts: Dict[str, Any]) -> Set[str]:
    enabled: Set[str] = set(opts.get("enabled_steps") or [])
    if enabled:
        enabled.add("1_load")
        return _expand_deps(enabled)

    run_optimization = bool(opts.get("run_optimization", True))
    run_monte_carlo_flag = bool(opts.get("run_monte_carlo", True))
    run_report = bool(opts.get("run_report", True))

    enabled |= {"1_load", "2_compile", "3_extract_params", "4_create_wide_ini", "5_validate_trades"}
    if run_optimization:
        enabled |= {"6_create_opt_ini", "7_run_optimization", "8_parse_results", "9_backtest_robust"}
    if run_optimization and run_monte_carlo_flag:
        enabled |= {"10_monte_carlo"}
    if run_optimization and run_monte_carlo_flag and run_report:
        enabled |= {"11_report"}
    return _expand_deps(enabled)


def _last_step(enabled: Set[str]) -> str:
    idx = max((WORKFLOW_STEPS.index(s) for s in enabled if s in WORKFLOW_STEPS), default=0)
    return WORKFLOW_STEPS[idx]


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run the core workflow with state tracking")
    ap.add_argument("--config", type=str, help="JSON config file (recommended)")
    ap.add_argument("--ea-path", type=str, help="Path to EA .mq5 (if not using --config)")
    ap.add_argument("--symbol", type=str, default=DEFAULT_SYMBOL)
    ap.add_argument("--timeframe", type=str, default=DEFAULT_TIMEFRAME)
    ap.add_argument("--no-ontester", action="store_true", help="Do not inject OnTester()")
    ap.add_argument("--no-safety", action="store_true", help="Do not inject safety guards")
    ap.add_argument("--no-opt", action="store_true", help="Stop after validation backtest (skip optimization+report)")
    ap.add_argument("--passes", type=int, default=20, help="Dashboard passes (default: 20)")
    ap.add_argument("--optimization-timeout", type=int, default=3600, help="Optimization timeout seconds (default: 3600)")
    ap.add_argument("--backtest-timeout", type=int, default=600, help="Backtest timeout seconds (default: 600)")
    return ap.parse_args()


def main() -> None:
    args = _args()

    cfg: Dict[str, Any] = {}
    if args.config:
        cfg = _load_json(Path(args.config))

    ea_path = Path((cfg.get("ea_path") or args.ea_path or "")).expanduser()
    if not ea_path:
        raise SystemExit("Provide --ea-path or --config with ea_path")

    symbol = str(cfg.get("symbol") or args.symbol or DEFAULT_SYMBOL)
    timeframe = str(cfg.get("timeframe") or args.timeframe or DEFAULT_TIMEFRAME)

    options = dict(cfg.get("options") or {})
    if args.no_opt:
        options["run_optimization"] = False
        options["run_monte_carlo"] = False
        options["run_report"] = False
    options.setdefault("inject_ontester", not bool(args.no_ontester))
    options.setdefault("inject_safety", not bool(args.no_safety))
    options.setdefault("passes", int(cfg.get("passes") or args.passes))
    options.setdefault("optimization_timeout", int(cfg.get("optimization_timeout") or args.optimization_timeout))
    options.setdefault("backtest_timeout", int(cfg.get("backtest_timeout") or args.backtest_timeout))

    enabled = _enabled_steps_from_options(options)
    last_step = _last_step(enabled)

    imported = _import_ea_to_test_terminal(ea_path)
    test_ea_path = Path(imported["ea_path"])
    ea_name = str(imported["ea_name"])

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    manager = WorkflowStateManager(state_dir=RUNS_DIR)
    manager.create_workflow(ea_name, str(test_ea_path), symbol=symbol, timeframe=timeframe)
    assert manager.state_file is not None
    state_path = manager.state_file

    print(f"[workflow] state: {state_path}")
    print(f"[workflow] ea: {ea_name} ({test_ea_path})")
    print(f"[workflow] symbol/timeframe: {symbol} {timeframe}")
    print(f"[workflow] enabled: {sorted(enabled)}")
    print(f"[workflow] will stop after: {last_step}")

    rp = ReportParser()
    s = get_settings()

    # Step 1: load + injections
    if "1_load" in enabled:
        ok, msg = manager.start_step("1_load")
        if not ok:
            raise RuntimeError(msg)

        out: Dict[str, Any] = {"path": str(test_ea_path)}
        if imported.get("imported"):
            out["imported"] = {"source_path": imported.get("source_path"), "dest_path": imported.get("ea_path")}

        if bool(options.get("inject_ontester")):
            inj = inject_ontester(test_ea_path)
            inj["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            out["ontester_injection"] = inj

        if bool(options.get("inject_safety")):
            safe = inject_safety(test_ea_path, force=False)
            safe["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            out["safety_injection"] = safe

        manager.complete_step("1_load", out)

    # Step 2: compile
    if "2_compile" in enabled:
        ok, msg = manager.start_step("2_compile")
        if not ok:
            raise RuntimeError(msg)

        comp = Compiler()
        cres = comp.compile(test_ea_path)
        out = {
            "mq5_path": str(test_ea_path),
            "ex5_path": str(cres.ex5_path) if cres.ex5_path else None,
            "errors": len(cres.errors),
            "warnings": len(cres.warnings),
        }

        if not cres.success:
            err = cres.errors[0].message if cres.errors else "Compilation failed"
            manager.fail_step("2_compile", err, output=out)
            raise SystemExit(err)
        manager.complete_step("2_compile", out)

    # Step 3: extract params
    if "3_extract_params" in enabled:
        ok, msg = manager.start_step("3_extract_params")
        if not ok:
            raise RuntimeError(msg)

        extractor = ParameterExtractor()
        ex = extractor.extract(test_ea_path)
        if not ex.success:
            manager.fail_step("3_extract_params", ex.error or "Param extraction failed")
            raise SystemExit(ex.error or "Param extraction failed")

        out = {
            "param_count": len(ex.parameters),
            "optimize_count": sum(1 for p in ex.parameters if p.optimize),
            "source": "optimizer/param_extractor.py",
        }
        manager.complete_step("3_extract_params", out)

    # Step 4: wide params + opt inputs
    wide_params_path = RUNS_DIR / f"{ea_name}_wide_params.json"
    opt_inputs_path = RUNS_DIR / f"{ea_name}_opt_inputs.json"

    if "4_create_wide_ini" in enabled:
        ok, msg = manager.start_step("4_create_wide_ini")
        if not ok:
            raise RuntimeError(msg)

        analysis = analyze_ea(test_ea_path)
        wide_params = generate_wide_params_json(analysis)
        opt_inputs = generate_opt_inputs(analysis)
        _write_json(wide_params_path, wide_params)
        _write_json(opt_inputs_path, opt_inputs)

        out = {
            "wide_params_path": str(wide_params_path),
            "opt_inputs_path": str(opt_inputs_path),
            "wide_param_count": len(wide_params),
            "optimizable_count": sum(1 for p in analysis if getattr(p, "should_optimize", False)),
        }
        manager.complete_step("4_create_wide_ini", out)

    # Step 5: validate trades (wide)
    validation_report: Optional[Path] = None
    if "5_validate_trades" in enabled:
        ok, msg = manager.start_step("5_validate_trades")
        if not ok:
            raise RuntimeError(msg)

        inputs = _load_json(wide_params_path) if wide_params_path.exists() else None
        runner = BacktestRunner(timeout=int(options["backtest_timeout"]))
        bt = runner.run(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            from_date=BACKTEST_FROM,
            to_date=BACKTEST_TO,
            inputs=inputs,
        )
        if not bt.success or not bt.report_path:
            manager.fail_step("5_validate_trades", bt.error or "Validation backtest failed")
            raise SystemExit(bt.error or "Validation backtest failed")

        validation_report = bt.report_path
        metrics = rp.parse(bt.report_path)
        trades = int(metrics.total_trades) if metrics else 0
        if trades <= 0:
            manager.fail_step("5_validate_trades", "No trades in validation backtest", output={"report_path": str(bt.report_path)})
            raise SystemExit("No trades in validation backtest")

        out = {
            "report_path": str(bt.report_path),
            "metrics": metrics.to_dict() if metrics else {},
            "trades": trades,
        }
        manager.complete_step("5_validate_trades", out)

    # Step 6: create opt ini
    ini_path: Optional[Path] = None
    if "6_create_opt_ini" in enabled:
        ok, msg = manager.start_step("6_create_opt_ini")
        if not ok:
            raise RuntimeError(msg)

        criterion = 6 if bool(options.get("inject_ontester")) else None
        ini_res = create_optimization_from_ea(
            ea_path=test_ea_path,
            output_dir=RUNS_DIR,
            use_cloud=None,  # respect settings.py default
            symbol=symbol,
            timeframe=timeframe,
            criterion=criterion,
        )
        if not ini_res.get("success"):
            manager.fail_step("6_create_opt_ini", ini_res.get("error") or "INI creation failed", output=ini_res)
            raise SystemExit(ini_res.get("error") or "INI creation failed")

        ini_path = Path(str(ini_res["ini_path"]))
        out = {"ini_path": str(ini_path), "criterion": int(criterion or ini_res.get("criterion") or 0), "cloud": bool(ini_res.get("settings", {}).get("cloud_agents", True))}
        # Preserve useful context if present
        if "settings" in ini_res:
            out.update(ini_res["settings"])
        manager.complete_step("6_create_opt_ini", out)

    # Step 7: run optimization
    if "7_run_optimization" in enabled:
        ok, msg = manager.start_step("7_run_optimization")
        if not ok:
            raise RuntimeError(msg)
        if not ini_path:
            ini_path = RUNS_DIR / f"{ea_name}_optimize.ini"
        opt = run_mt5_optimization(ini_path=ini_path, timeout=int(options["optimization_timeout"]))
        if not opt.get("success"):
            manager.fail_step("7_run_optimization", opt.get("error") or "Optimization failed", output=opt)
            raise SystemExit(opt.get("error") or "Optimization failed")
        manager.complete_step("7_run_optimization", opt)

    # Step 8: parse results -> best params json
    best_params_path = RUNS_DIR / f"{ea_name}_best_params.json"
    if "8_parse_results" in enabled:
        ok, msg = manager.start_step("8_parse_results")
        if not ok:
            raise RuntimeError(msg)

        parser = OptimizationResultParser(ea_name, MT5_DATA_PATH, symbol=symbol)
        parsed = parser.parse()
        if not parsed.get("success"):
            manager.fail_step("8_parse_results", parsed.get("error") or "Result parsing failed", output=parsed)
            raise SystemExit(parsed.get("error") or "Result parsing failed")

        best = parsed.get("best")
        if not best or not isinstance(best, dict) or not isinstance(best.get("parameters"), dict):
            manager.fail_step("8_parse_results", "No robust passes found", output=parsed)
            raise SystemExit("No robust passes found")

        _write_json(best_params_path, best["parameters"])

        total = int(parsed.get("total_passes") or 0)
        robust = int(parsed.get("robust_passes") or 0)
        rr = (robust / total * 100.0) if total else 0.0

        out = {
            "total_passes": total,
            "robust_passes": robust,
            "robustness_rate": f"{rr:.1f}%",
            "best_pass": best.get("pass"),
            "in_sample_profit": (best.get("in_sample") or {}).get("profit"),
            "in_sample_pf": (best.get("in_sample") or {}).get("profit_factor"),
            "in_sample_dd": (best.get("in_sample") or {}).get("max_dd_pct"),
            "forward_profit": (best.get("forward") or {}).get("profit"),
            "total_profit": best.get("total_profit"),
            "params_file": str(best_params_path),
        }
        manager.complete_step("8_parse_results", out)

    # Step 9: robust backtest with best params
    robust_report: Optional[Path] = None
    robust_metrics = None
    if "9_backtest_robust" in enabled:
        ok, msg = manager.start_step("9_backtest_robust")
        if not ok:
            raise RuntimeError(msg)

        if not best_params_path.exists():
            manager.fail_step("9_backtest_robust", f"Missing best params file: {best_params_path}")
            raise SystemExit(f"Missing best params file: {best_params_path}")
        best_params = _load_json(best_params_path)

        runner = BacktestRunner(timeout=int(options["backtest_timeout"]))
        bt = runner.run(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            from_date=BACKTEST_FROM,
            to_date=BACKTEST_TO,
            inputs=best_params,
        )
        if not bt.success or not bt.report_path:
            manager.fail_step("9_backtest_robust", bt.error or "Robust backtest failed")
            raise SystemExit(bt.error or "Robust backtest failed")

        robust_report = bt.report_path
        robust_metrics = rp.parse(bt.report_path)
        out = {"report_path": str(bt.report_path)}
        if robust_metrics:
            out.update(robust_metrics.to_dict())
        manager.complete_step("9_backtest_robust", out)

    # Step 10: Monte Carlo
    if "10_monte_carlo" in enabled:
        ok, msg = manager.start_step("10_monte_carlo")
        if not ok:
            raise RuntimeError(msg)
        if not robust_report:
            manager.fail_step("10_monte_carlo", "Missing robust backtest report")
            raise SystemExit("Missing robust backtest report")

        mc = run_montecarlo(str(robust_report), iterations=int(s.monte_carlo.iterations), ruin_threshold_pct=float(s.monte_carlo.ruin_threshold_pct))
        out = mc.to_dict()
        out["confidence_min"] = float(s.monte_carlo.confidence_min)
        out["max_ruin_probability"] = float(s.monte_carlo.max_ruin_probability)
        out["is_robust"] = bool(mc.is_robust)
        out["report_path"] = str(robust_report)
        manager.complete_step("10_monte_carlo", out)

    # Step 11: dashboard + text report
    if "11_report" in enabled:
        ok, msg = manager.start_step("11_report")
        if not ok:
            raise RuntimeError(msg)

        # Dashboard (prints JSON)
        dash = _run_script_json(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "generate_dashboard.py"),
                "--state",
                str(state_path),
                "--passes",
                str(int(options["passes"])),
            ]
        )

        # Text report (prints JSON, also updates state file in-place)
        txt = _run_script_json(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "generate_text_report.py"),
                "--state",
                str(state_path),
            ]
        )

        # Reload state after generate_text_report.py modifies Step 11 output.
        manager.load_workflow(state_path)

        # Merge Step 11 output
        existing = {}
        try:
            existing = dict(manager.state.steps["11_report"].output) if manager.state else {}
        except Exception:
            existing = {}

        if dash.get("index"):
            existing["dashboard_index"] = dash.get("index")
        if robust_report:
            existing["backtest_report"] = str(robust_report)
        if robust_metrics:
            existing["history_quality"] = f"{robust_metrics.history_quality:.0f}%" if robust_metrics.history_quality else None
            existing["bars"] = str(robust_metrics.bars) if robust_metrics.bars else None
            existing["ticks"] = str(robust_metrics.ticks) if robust_metrics.ticks else None
        if txt.get("overall_result"):
            existing["overall_result"] = txt.get("overall_result")

        manager.complete_step("11_report", existing)

    print(
        json.dumps(
            {
                "success": True,
                "ea_name": ea_name,
                "state_file": str(state_path),
                "stopped_after": last_step,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
