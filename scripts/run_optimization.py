#!/usr/bin/env python
"""
Run MT5 Optimization

Launches MT5 Strategy Tester with an optimization INI file and waits for completion.
"""

import argparse
import subprocess
import sys
import time
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MT5_TERMINAL, MT5_DATA_PATH, RUNS_DIR


def find_latest_optimization_result(ea_name: str) -> Path | None:
    """Find the most recent optimization cache file for an EA."""
    tester_path = MT5_DATA_PATH / "Tester"

    # Look for optimization cache files
    pattern = f"*{ea_name}*.opt"
    opt_files = list(tester_path.glob(pattern))

    if not opt_files:
        return None

    # Return most recent
    return max(opt_files, key=lambda p: p.stat().st_mtime)


def _recent_mtime(path: Path, start_time: float, grace_seconds: int = 30) -> bool:
    try:
        return path.exists() and path.stat().st_mtime >= (start_time - grace_seconds)
    except OSError:
        return False


def _copy_outputs_to_runs(paths: list[Path]) -> list[str]:
    copied: list[str] = []
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if not p or not p.exists():
            continue
        dest = RUNS_DIR / p.name
        if dest.resolve() == p.resolve():
            copied.append(str(dest))
            continue
        import shutil

        shutil.copy2(p, dest)
        copied.append(str(dest))
    return copied


def wait_for_optimization(process: subprocess.Popen, ea_name: str, report_name: str, timeout: int, poll_interval: int = 30) -> dict:
    """
    Wait for optimization to complete.

    Monitors for:
    - Terminal process exit
    - Report file creation
    - Timeout
    """
    start_time = time.time()
    tester_path = MT5_DATA_PATH / "Tester"

    report_base = report_name or f"{ea_name}_OPT"

    # Optimization exports (these are the most reliable outputs)
    xml_insample = MT5_DATA_PATH / f"{report_base}.xml"
    xml_forward = MT5_DATA_PATH / f"{report_base}.forward.xml"

    # HTML report can land in a few places depending on the terminal setup.
    html_candidates = [
        MT5_DATA_PATH / f"{report_base}.htm",
        MT5_DATA_PATH / f"{report_base}.html",
        tester_path / f"{report_base}.htm",
        tester_path / f"{report_base}.html",
        tester_path / "reports" / f"{report_base}.htm",
        tester_path / "reports" / f"{report_base}.html",
    ]

    initial_reports = set()
    for d in (tester_path, tester_path / "reports"):
        if d.exists():
            initial_reports |= set(d.glob(f"*{report_base}*.htm*"))
            initial_reports |= set(d.glob(f"*{report_base}*.html*"))

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            return {
                "success": False,
                "error": f"Optimization timed out after {timeout}s",
                "elapsed": int(elapsed)
            }

        # Prefer XML outputs (optimization result exports).
        if _recent_mtime(xml_insample, start_time) and _recent_mtime(xml_forward, start_time):
            copied = _copy_outputs_to_runs([xml_insample, xml_forward])
            return {
                "success": True,
                "elapsed": int(elapsed),
                "xml_insample": str(xml_insample),
                "xml_forward": str(xml_forward),
                "copied_to_runs": copied,
            }

        # Fallback: detect HTML report creation.
        current_reports = set()
        for d in (tester_path, tester_path / "reports"):
            if d.exists():
                current_reports |= set(d.glob(f"*{report_base}*.htm*"))
                current_reports |= set(d.glob(f"*{report_base}*.html*"))
        new_reports = current_reports - initial_reports

        if new_reports:
            report = max(new_reports, key=lambda p: p.stat().st_mtime)
            copied = _copy_outputs_to_runs([report])
            return {
                "success": True,
                "report_path": str(report),
                "elapsed": int(elapsed),
                "copied_to_runs": copied,
            }

        # Check the process we launched (do not rely on global terminal64.exe presence;
        # users may have other MT5 instances open).
        if process.poll() is not None:
            time.sleep(5)
            elapsed = time.time() - start_time

            if _recent_mtime(xml_insample, start_time) and _recent_mtime(xml_forward, start_time):
                copied = _copy_outputs_to_runs([xml_insample, xml_forward])
                return {
                    "success": True,
                    "elapsed": int(elapsed),
                    "xml_insample": str(xml_insample),
                    "xml_forward": str(xml_forward),
                    "copied_to_runs": copied,
                }

            for cand in html_candidates:
                if _recent_mtime(cand, start_time):
                    copied = _copy_outputs_to_runs([cand])
                    return {
                        "success": True,
                        "report_path": str(cand),
                        "elapsed": int(elapsed),
                        "copied_to_runs": copied,
                    }

            return {
                "success": False,
                "error": "MT5 closed without generating report",
                "elapsed": int(elapsed),
            }

        print(f"Optimization running... {int(elapsed)}s elapsed", flush=True)
        time.sleep(poll_interval)


def save_optimization_results(ea_name: str, symbol: str) -> dict:
    """
    Save optimization XML files with symbol-specific names.

    MT5 always outputs to {ea_name}_OPT.xml - this preserves results per symbol.
    """
    import shutil

    base_xml = MT5_DATA_PATH / f"{ea_name}_OPT.xml"
    forward_xml = MT5_DATA_PATH / f"{ea_name}_OPT.forward.xml"

    saved_files = []

    # Save in-sample XML
    if base_xml.exists():
        dest = MT5_DATA_PATH / f"{ea_name}_{symbol}_OPT.xml"
        shutil.copy2(base_xml, dest)
        saved_files.append(str(dest))

    # Save forward XML
    if forward_xml.exists():
        dest = MT5_DATA_PATH / f"{ea_name}_{symbol}_OPT.forward.xml"
        shutil.copy2(forward_xml, dest)
        saved_files.append(str(dest))

    return {"saved": saved_files}


def run_optimization(ini_path: Path, timeout: int = 3600, wait: bool = True) -> dict:
    """
    Run MT5 optimization with an INI file.

    Args:
        ini_path: Path to optimization INI file
        timeout: Maximum time to wait (seconds)
        wait: Whether to wait for completion

    Returns:
        Dict with success status and results
    """
    if not ini_path.exists():
        return {
            "success": False,
            "error": f"INI file not found: {ini_path}"
        }

    # Extract EA name and symbol from INI
    ea_name = None
    symbol = None
    report_name = None
    with open(ini_path, 'r') as f:
        for line in f:
            if line.startswith("Expert="):
                ea_name = line.split("=")[1].strip()
            elif line.startswith("Symbol="):
                symbol = line.split("=")[1].strip()
            elif line.startswith("Report="):
                report_name = line.split("=")[1].strip()

    if not ea_name:
        return {
            "success": False,
            "error": "Could not find Expert= in INI file"
        }

    # Launch MT5 with INI
    cmd = [str(MT5_TERMINAL), f"/config:{ini_path}"]

    print(f"Launching MT5 optimization for {ea_name}...")
    print(f"Command: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(cmd)

        if not wait:
            return {
                "success": True,
                "message": "Optimization started (not waiting)",
                "pid": process.pid,
                "ea_name": ea_name
            }

        # Wait for completion
        print(f"Waiting for optimization (timeout: {timeout}s)...")
        result = wait_for_optimization(process, ea_name, report_name, timeout)

        if result["success"]:
            print(f"Optimization complete in {result['elapsed']}s")
            if "report_path" in result:
                print(f"Report: {result['report_path']}")
            if "xml_insample" in result and "xml_forward" in result:
                print(f"XML: {result['xml_insample']}")
                print(f"FWD: {result['xml_forward']}")
            if result.get("copied_to_runs"):
                print(f"Copied to runs/: {result['copied_to_runs']}")

            # Save XML files with symbol-specific names
            if symbol:
                saved = save_optimization_results(ea_name, symbol)
                print(f"Saved optimization results: {saved['saved']}")
                result["saved_xml"] = saved["saved"]
        else:
            print(f"Optimization failed: {result['error']}")

        return {
            **result,
            "ea_name": ea_name,
            "symbol": symbol,
            "ini_path": str(ini_path)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "ea_name": ea_name
        }


def main():
    parser = argparse.ArgumentParser(description="Run MT5 optimization")
    parser.add_argument("ini_path", help="Path to optimization INI file")
    parser.add_argument("--timeout", "-t", type=int, default=3600,
                        help="Timeout in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--no-wait", action="store_true",
                        help="Don't wait for completion")

    args = parser.parse_args()

    ini_path = Path(args.ini_path)
    result = run_optimization(
        ini_path=ini_path,
        timeout=args.timeout,
        wait=not args.no_wait
    )

    print(json.dumps(result, indent=2))

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
