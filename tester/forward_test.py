"""
Forward Testing Module
Tests optimized parameters on out-of-sample data.
"""
import subprocess
import time
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
import psutil

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MT5_TERMINAL, MT5_DATA_PATH
from .ini_generator import BacktestConfig, create_forward_test_ini


@dataclass
class ForwardTestResult:
    """Result of a forward test."""
    success: bool
    fast_period: int
    slow_period: int
    profit: float = 0.0
    profit_factor: float = 0.0
    trades: int = 0
    drawdown: float = 0.0
    report_path: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: float = 0


def calculate_date_splits(
    full_from: str,
    full_to: str,
    optimization_ratio: float = 0.7
) -> tuple:
    """
    Calculate date splits for optimization and forward testing.

    Args:
        full_from: Start date (YYYY.MM.DD)
        full_to: End date (YYYY.MM.DD)
        optimization_ratio: Ratio of data for optimization (default 70%)

    Returns:
        (opt_from, opt_to, fwd_from, fwd_to) tuple of date strings
    """
    from_date = datetime.strptime(full_from, "%Y.%m.%d")
    to_date = datetime.strptime(full_to, "%Y.%m.%d")

    total_days = (to_date - from_date).days
    opt_days = int(total_days * optimization_ratio)

    opt_end = from_date + timedelta(days=opt_days)
    fwd_start = opt_end + timedelta(days=1)

    return (
        full_from,
        opt_end.strftime("%Y.%m.%d"),
        fwd_start.strftime("%Y.%m.%d"),
        full_to,
    )


class ForwardTestRunner:
    """Runs forward tests on optimized parameters."""

    def __init__(self, terminal_path: Optional[Path] = None, timeout: int = 300):
        """
        Initialize the forward test runner.

        Args:
            terminal_path: Path to terminal64.exe
            timeout: Maximum seconds to wait for test completion
        """
        self.terminal = terminal_path or MT5_TERMINAL
        self.timeout = timeout

    def run(
        self,
        ea_name: str,
        fast_period: int,
        slow_period: int,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        from_date: str = "2024.09.01",
        to_date: str = "2024.12.01",
        run_dir: Optional[Path] = None,
    ) -> ForwardTestResult:
        """
        Run a forward test with specific parameters.

        Args:
            ea_name: Name of the EA (without .ex5)
            fast_period: Fast MA period from optimization
            slow_period: Slow MA period from optimization
            symbol: Trading symbol
            timeframe: Timeframe
            from_date: Forward test start date
            to_date: Forward test end date
            run_dir: Directory to save results

        Returns:
            ForwardTestResult with performance metrics
        """
        start_time = time.time()

        if run_dir is None:
            run_dir = MT5_DATA_PATH / "Tester" / "reports"
        run_dir.mkdir(parents=True, exist_ok=True)

        report_name = f"{ea_name}_FWD_{fast_period}_{slow_period}"
        ini_path = run_dir / f"{ea_name}_forward.ini"

        # Create forward test configuration
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
        )

        # Generate forward test INI with specific parameters
        create_forward_test_ini(config, ini_path, fast_period, slow_period)

        try:
            # Kill any running MT5
            self._kill_mt5_if_running()
            time.sleep(1)

            # Run terminal
            cmd = [str(self.terminal), f'/config:{ini_path}']

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return ForwardTestResult(
                    success=False,
                    fast_period=fast_period,
                    slow_period=slow_period,
                    error="Forward test timed out",
                    duration_seconds=time.time() - start_time,
                )

            # Wait for report
            time.sleep(3)

            # Find the report
            report_path = MT5_DATA_PATH / f"{report_name}.htm"
            if not report_path.exists():
                report_path = MT5_DATA_PATH / f"{report_name}.html"

            if report_path.exists():
                # Copy to run directory
                dest_path = run_dir / report_path.name
                shutil.copy2(report_path, dest_path)

                # Parse the report
                metrics = self._parse_forward_report(dest_path)

                return ForwardTestResult(
                    success=True,
                    fast_period=fast_period,
                    slow_period=slow_period,
                    profit=metrics.get('profit', 0),
                    profit_factor=metrics.get('profit_factor', 0),
                    trades=metrics.get('trades', 0),
                    drawdown=metrics.get('drawdown', 0),
                    report_path=dest_path,
                    duration_seconds=time.time() - start_time,
                )
            else:
                return ForwardTestResult(
                    success=False,
                    fast_period=fast_period,
                    slow_period=slow_period,
                    error="Forward test report not found",
                    duration_seconds=time.time() - start_time,
                )

        except Exception as e:
            return ForwardTestResult(
                success=False,
                fast_period=fast_period,
                slow_period=slow_period,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _kill_mt5_if_running(self):
        """Kill any running MT5 terminal processes."""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and 'terminal64' in proc.info['name'].lower():
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _parse_forward_report(self, report_path: Path) -> dict:
        """Parse forward test report for key metrics."""
        import re

        metrics = {
            'profit': 0.0,
            'profit_factor': 0.0,
            'trades': 0,
            'drawdown': 0.0,
        }

        try:
            with open(report_path, 'r', encoding='utf-16', errors='ignore') as f:
                content = f.read()

            # Extract profit
            match = re.search(r'Total Net Profit[:\s]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE)
            if match:
                metrics['profit'] = float(match.group(1).replace(' ', ''))

            # Extract profit factor
            match = re.search(r'Profit Factor[:\s]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE)
            if match:
                metrics['profit_factor'] = float(match.group(1).replace(' ', ''))

            # Extract trades
            match = re.search(r'Total Trades[:\s]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE)
            if match:
                metrics['trades'] = int(float(match.group(1).replace(' ', '')))

            # Extract drawdown (format may be "2321.04(23.11%)")
            match = re.search(r'(?:Balance|Equity) Drawdown Maximal[:\s]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE)
            if match:
                dd_str = match.group(1).replace(' ', '')
                # Extract just the number part (before any parenthesis)
                dd_match = re.match(r'([0-9.\-]+)', dd_str)
                if dd_match:
                    metrics['drawdown'] = float(dd_match.group(1))

        except Exception as e:
            print(f"Error parsing forward report: {e}")

        return metrics


if __name__ == "__main__":
    # Test forward testing
    runner = ForwardTestRunner(timeout=120)

    # Test with an existing EA
    result = runner.run(
        ea_name="MA_10_50_EURUSD_H1_20251224_194638",
        fast_period=10,
        slow_period=50,
        symbol="EURUSD",
        timeframe="H1",
        from_date="2024.09.01",
        to_date="2024.12.01",
    )

    print(f"Success: {result.success}")
    print(f"Params: Fast={result.fast_period}, Slow={result.slow_period}")
    print(f"Profit: {result.profit}")
    print(f"Profit Factor: {result.profit_factor}")
    print(f"Trades: {result.trades}")
    if result.error:
        print(f"Error: {result.error}")
