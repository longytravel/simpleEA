"""
MT5 Backtest Runner
Executes backtests using terminal64.exe with INI configuration.
"""
import subprocess
import time
import psutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MT5_TERMINAL, MT5_DATA_PATH, MT5_TESTER_PATH, RUNS_DIR
from .ini_generator import BacktestConfig, create_backtest_ini, InputParam

# MT5 Tester folder is separate from Terminal data folder
MT5_TESTER_REPORTS = Path(r"C:\Users\User\AppData\Roaming\MetaQuotes\Tester\A42909ABCDDDD04324904B57BA9776B8")


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    success: bool
    report_path: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: float = 0


class BacktestRunner:
    """Runs MT5 Strategy Tester backtests."""

    def __init__(self, terminal_path: Optional[Path] = None, timeout: int = 300, *, kill_existing: bool = False):
        """
        Initialize the backtest runner.

        Args:
            terminal_path: Path to terminal64.exe
            timeout: Maximum seconds to wait for backtest completion
            kill_existing: If True, kill a running MT5 process for this terminal path before starting.
        """
        self.terminal = terminal_path or MT5_TERMINAL
        self.timeout = timeout
        self.kill_existing = kill_existing

    def run(
        self,
        ea_name: str,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        from_date: str = "2024.01.01",
        to_date: str = "2024.12.01",
        run_dir: Optional[Path] = None,
        inputs: Optional[dict] = None,
    ) -> BacktestResult:
        """
        Run a backtest for the specified EA.

        Args:
            ea_name: Name of the EA (without .ex5)
            symbol: Trading symbol
            timeframe: Timeframe (M1, M5, M15, M30, H1, H4, D1, W1, MN1)
            from_date: Start date (YYYY.MM.DD)
            to_date: End date (YYYY.MM.DD)
            run_dir: Directory to save reports
            inputs: Dict of EA input parameters {name: value}

        Returns:
            BacktestResult with success status and report path
        """
        start_time = time.time()
        ms = int((start_time - int(start_time)) * 1000)
        run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time)) + f"_{ms:03d}"

        # Setup paths
        if run_dir is None:
            run_dir = RUNS_DIR / "backtests" / f"{ea_name}_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        report_name = f"{ea_name}_BT_{run_id}"  # Report name without extension (unique per run)
        ini_path = run_dir / f"{ea_name}_backtest.ini"

        # Convert inputs dict to InputParam list
        input_params = []
        if inputs:
            for name, value in inputs.items():
                input_params.append(InputParam(name=name, default=value, optimize=False))

        # Create backtest configuration
        config = BacktestConfig(
            expert=ea_name,
            symbol=symbol,
            period=timeframe,
            from_date=from_date,
            to_date=to_date,
            report_name=report_name,
            shutdown_terminal=True,
            visual=False,
            use_local=True,
            inputs=input_params,
        )

        # Generate INI file
        create_backtest_ini(config, ini_path)

        try:
            # Check if MT5 is already running
            if self.kill_existing:
                self._kill_mt5_if_running()
                time.sleep(1)
            elif self._is_mt5_running():
                return BacktestResult(
                    success=False,
                    error="MT5 terminal is already running for this installation (close it or use kill_existing=True)",
                    duration_seconds=time.time() - start_time,
                )

            # Run terminal with config
            cmd = [str(self.terminal), f'/config:{ini_path}']

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for completion (MT5 should close itself due to ShutdownTerminal=1)
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return BacktestResult(
                    success=False,
                    error="Backtest timed out",
                    duration_seconds=time.time() - start_time,
                )

            # Check if report was generated
            # MT5 might need a moment to write the file
            time.sleep(3)

            # MT5 saves reports in the Terminal data folder (not Tester!)
            possible_locations = [
                # In the main Terminal data folder (most common)
                MT5_DATA_PATH / f"{report_name}.htm",
                MT5_DATA_PATH / f"{report_name}.html",
                MT5_DATA_PATH / f"{report_name}.xml",
                # In the Tester subfolder
                MT5_DATA_PATH / "Tester" / f"{report_name}.htm",
                MT5_DATA_PATH / "Tester" / f"{report_name}.html",
                # In the Tester reports subfolder (common in some MT5 setups)
                MT5_TESTER_PATH / "reports" / f"{report_name}.htm",
                MT5_TESTER_PATH / "reports" / f"{report_name}.html",
                # In the Tester reports folder
                MT5_TESTER_REPORTS / f"{report_name}.htm",
                MT5_TESTER_REPORTS / f"{report_name}.html",
                MT5_TESTER_REPORTS / "reports" / f"{report_name}.htm",
                MT5_TESTER_REPORTS / "reports" / f"{report_name}.html",
                # In the run directory
                run_dir / f"{report_name}.htm",
                run_dir / f"{report_name}.html",
            ]

            for loc in possible_locations:
                if loc and loc.exists():
                    dest = self._copy_report_assets(loc, run_dir)
                    return BacktestResult(
                        success=True,
                        report_path=dest,
                        duration_seconds=time.time() - start_time,
                    )

            # Try finding any recent HTML reports in the tester area
            import glob
            search_patterns = [
                str(MT5_TESTER_REPORTS / "*.htm"),
                str(MT5_TESTER_REPORTS / "*.html"),
                str(MT5_DATA_PATH / "Tester" / "*.htm"),
                str(MT5_TESTER_PATH / "reports" / "*.htm"),
                str(MT5_TESTER_PATH / "reports" / "*.html"),
                str(MT5_TESTER_REPORTS / "reports" / "*.htm"),
                str(MT5_TESTER_REPORTS / "reports" / "*.html"),
            ]

            for pattern in search_patterns:
                for found in glob.glob(pattern):
                    found_path = Path(found)
                    # Check if it was modified recently (within 60 seconds of start)
                    try:
                        if found_path.stat().st_mtime > start_time - 30:
                            dest = self._copy_report_assets(found_path, run_dir)
                            return BacktestResult(
                                success=True,
                                report_path=dest,
                                duration_seconds=time.time() - start_time,
                            )
                    except:
                        pass

            return BacktestResult(
                success=False,
                error="Report file not generated",
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return BacktestResult(
                success=False,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _kill_mt5_if_running(self):
        """Kill running MT5 terminal processes that match this runner's terminal executable path."""
        target = None
        try:
            target = Path(self.terminal).resolve()
        except Exception:
            target = None

        for proc in psutil.process_iter(['name', 'exe']):
            try:
                exe = proc.info.get('exe')
                if not exe:
                    continue
                if target and Path(exe).resolve() == target:
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _is_mt5_running(self) -> bool:
        """Return True if a running MT5 process matches this runner's terminal executable path."""
        try:
            target = Path(self.terminal).resolve()
        except Exception:
            return False

        for proc in psutil.process_iter(['exe']):
            try:
                exe = proc.info.get('exe')
                if not exe:
                    continue
                if Path(exe).resolve() == target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        return False

    def _copy_report_assets(self, report_path: Path, run_dir: Path) -> Path:
        """
        Copy the MT5 report HTML/HTM file and any associated chart images into run_dir.

        MT5 typically generates images like:
          {report_stem}.png
          {report_stem}-holding.png
          {report_stem}-mfemae.png
        """
        import shutil

        run_dir.mkdir(parents=True, exist_ok=True)
        dest_report = run_dir / report_path.name

        if report_path.resolve() != dest_report.resolve():
            shutil.copy2(report_path, dest_report)

        # MT5 sometimes writes the HTML report to one folder but chart PNGs to another.
        search_dirs = [report_path.parent, MT5_DATA_PATH]
        copied = set()
        for d in search_dirs:
            if not d.exists():
                continue
            for img in d.glob(f"{report_path.stem}*.png"):
                dest_img = run_dir / img.name
                if dest_img.name in copied or dest_img.exists():
                    continue
                shutil.copy2(img, dest_img)
                copied.add(dest_img.name)

        return dest_report


if __name__ == "__main__":
    # Test backtest runner
    runner = BacktestRunner(timeout=120)

    # Test with an existing EA
    result = runner.run(
        ea_name="RSI_Divergence_Pro",
        symbol="EURUSD",
        timeframe="H1",
        from_date="2024.01.01",
        to_date="2024.06.01",
    )

    print(f"Success: {result.success}")
    print(f"Report: {result.report_path}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.error:
        print(f"Error: {result.error}")
