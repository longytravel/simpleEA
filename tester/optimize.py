"""
MT5 Optimization Runner
Runs genetic optimization and parses results.
"""
import subprocess
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import psutil

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MT5_TERMINAL, MT5_DATA_PATH
from .ini_generator import BacktestConfig, create_optimization_ini

# MT5 cache/results locations
MT5_TESTER_CACHE = MT5_DATA_PATH / "Tester" / "cache"


@dataclass
class OptimizationResult:
    """Single optimization result (one parameter combination)."""
    fast_period: int
    slow_period: int
    profit: float
    profit_factor: float
    expected_payoff: float
    drawdown: float
    trades: int
    recovery_factor: float = 0.0


@dataclass
class OptimizationOutput:
    """Output from optimization run."""
    success: bool
    results: list  # List of OptimizationResult
    best_result: Optional[OptimizationResult] = None
    error: Optional[str] = None
    duration_seconds: float = 0
    report_path: Optional[Path] = None


class OptimizationRunner:
    """Runs MT5 Strategy Tester optimization."""

    def __init__(self, terminal_path: Optional[Path] = None, timeout: int = 2700):
        """
        Initialize the optimization runner.

        Args:
            terminal_path: Path to terminal64.exe
            timeout: Maximum seconds to wait for optimization (default 45 min)
        """
        self.terminal = terminal_path or MT5_TERMINAL
        self.timeout = timeout

    def run(
        self,
        ea_name: str,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        from_date: str = "2024.01.01",
        to_date: str = "2024.09.01",
        forward_date: str = None,
        fast_range: tuple = (5, 5, 50),
        slow_range: tuple = (20, 10, 200),
        run_dir: Optional[Path] = None,
    ) -> OptimizationOutput:
        """
        Run genetic optimization for the EA with optional forward testing.

        Args:
            ea_name: Name of the EA (without .ex5)
            symbol: Trading symbol
            timeframe: Timeframe
            from_date: Optimization start date
            to_date: End date (optimization end if forward_date set, else total end)
            forward_date: Forward test start date (enables MT5 built-in forward test)
            fast_range: (min, step, max) for fast period
            slow_range: (min, step, max) for slow period
            run_dir: Directory to save results

        Returns:
            OptimizationOutput with best parameters
        """
        start_time = time.time()

        if run_dir is None:
            run_dir = MT5_DATA_PATH / "Tester" / "reports"
        run_dir.mkdir(parents=True, exist_ok=True)

        report_name = f"{ea_name}_OPT"
        ini_path = run_dir / f"{ea_name}_optimize.ini"

        # Create optimization configuration
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

        # Generate optimization INI (with forward test if forward_date provided)
        create_optimization_ini(config, ini_path, fast_range, slow_range, forward_date=forward_date)

        try:
            # Kill any running MT5
            self._kill_mt5_if_running()
            time.sleep(1)

            # Run terminal with optimization config
            cmd = [str(self.terminal), f'/config:{ini_path}']

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for completion
            print(f"[DEBUG] Waiting for optimization with timeout={self.timeout}s ({self.timeout/60:.1f}min)")
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return OptimizationOutput(
                    success=False,
                    results=[],
                    error="Optimization timed out",
                    duration_seconds=time.time() - start_time,
                )

            # Wait for files to be written
            time.sleep(3)

            # Find and parse optimization results from XML
            results = self._parse_optimization_results(ea_name, run_dir, report_name)

            # Also try HTML report if no XML results
            if not results:
                report_path = MT5_DATA_PATH / f"{report_name}.htm"
                if report_path.exists():
                    results = self._parse_optimization_report(report_path)

            if results:
                # Sort by profit factor descending
                results.sort(key=lambda x: x.profit_factor, reverse=True)
                best = results[0] if results else None

                return OptimizationOutput(
                    success=True,
                    results=results,
                    best_result=best,
                    duration_seconds=time.time() - start_time,
                )
            else:
                return OptimizationOutput(
                    success=False,
                    results=[],
                    error="No optimization results found",
                    duration_seconds=time.time() - start_time,
                )

        except Exception as e:
            return OptimizationOutput(
                success=False,
                results=[],
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

    def _parse_optimization_results(self, ea_name: str, run_dir: Path, report_name: str) -> list:
        """Parse optimization results from XML file."""
        results = []

        # MT5 saves optimization results as {report_name}.xml in the data path
        xml_path = MT5_DATA_PATH / f"{report_name}.xml"

        if xml_path.exists():
            results = self._parse_xml_results(xml_path)

        return results

    def _parse_xml_results(self, xml_path: Path) -> list:
        """Parse an optimization XML file (Excel SpreadsheetML format)."""
        results = []

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Define namespace for SpreadsheetML
            ns = {
                'ss': 'urn:schemas-microsoft-com:office:spreadsheet',
                'o': 'urn:schemas-microsoft-com:office:office',
            }

            # Find all rows in the worksheet
            rows = root.findall('.//ss:Row', ns)

            if not rows:
                # Try without namespace
                rows = root.findall('.//{urn:schemas-microsoft-com:office:spreadsheet}Row')

            # First row is header, skip it
            header_row = True
            header_map = {}

            for row in rows:
                cells = row.findall('ss:Cell', ns)
                if not cells:
                    cells = row.findall('{urn:schemas-microsoft-com:office:spreadsheet}Cell')

                # Extract cell values
                values = []
                for cell in cells:
                    data = cell.find('ss:Data', ns)
                    if data is None:
                        data = cell.find('{urn:schemas-microsoft-com:office:spreadsheet}Data')
                    if data is not None and data.text:
                        values.append(data.text)
                    else:
                        values.append('')

                if header_row:
                    # Map column names to indices
                    for i, val in enumerate(values):
                        header_map[val] = i
                    header_row = False
                    continue

                if len(values) < 10:
                    continue

                try:
                    # Get column indices - handle different naming conventions
                    fast_idx = header_map.get('FastMAPeriod', header_map.get('FastPeriod', -1))
                    slow_idx = header_map.get('SlowMAPeriod', header_map.get('SlowPeriod', -1))
                    profit_idx = header_map.get('Profit', 2)
                    pf_idx = header_map.get('Profit Factor', 4)
                    ep_idx = header_map.get('Expected Payoff', 3)
                    dd_idx = header_map.get('Equity DD %', 8)
                    trades_idx = header_map.get('Trades', 9)
                    rf_idx = header_map.get('Recovery Factor', 5)

                    # If parameter columns not found, try last two columns
                    if fast_idx == -1:
                        fast_idx = len(values) - 2
                    if slow_idx == -1:
                        slow_idx = len(values) - 1

                    result = OptimizationResult(
                        fast_period=int(float(values[fast_idx])),
                        slow_period=int(float(values[slow_idx])),
                        profit=float(values[profit_idx]) if values[profit_idx] else 0,
                        profit_factor=float(values[pf_idx]) if values[pf_idx] else 0,
                        expected_payoff=float(values[ep_idx]) if values[ep_idx] else 0,
                        drawdown=float(values[dd_idx]) if values[dd_idx] else 0,
                        trades=int(float(values[trades_idx])) if values[trades_idx] else 0,
                        recovery_factor=float(values[rf_idx]) if values[rf_idx] else 0,
                    )
                    results.append(result)
                except (ValueError, IndexError) as e:
                    continue

        except Exception as e:
            print(f"Error parsing XML: {e}")

        return results

    def _parse_optimization_report(self, report_path: Path) -> list:
        """Parse optimization results from HTML report."""
        results = []

        try:
            with open(report_path, 'r', encoding='utf-16', errors='ignore') as f:
                content = f.read()

            # Look for optimization result rows
            # Format varies, but typically has columns for parameters and results
            # This is a simplified parser - may need adjustment based on actual format

            # Find table rows with optimization data
            pattern = r'FastPeriod=(\d+).*?SlowPeriod=(\d+).*?Profit[:\s]*([0-9.\-\s]+).*?Factor[:\s]*([0-9.]+)'
            matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

            for match in matches:
                try:
                    result = OptimizationResult(
                        fast_period=int(match[0]),
                        slow_period=int(match[1]),
                        profit=float(match[2].replace(' ', '')),
                        profit_factor=float(match[3]),
                        expected_payoff=0,
                        drawdown=0,
                        trades=0,
                    )
                    results.append(result)
                except:
                    pass

        except Exception as e:
            print(f"Error parsing optimization report: {e}")

        return results


if __name__ == "__main__":
    # Test optimization runner
    runner = OptimizationRunner(timeout=300)

    print("Starting optimization test...")
    result = runner.run(
        ea_name="MA_10_50_EURUSD_H1_20251224_194638",
        symbol="EURUSD",
        timeframe="H1",
        from_date="2024.01.01",
        to_date="2024.06.01",
        fast_range=(5, 5, 30),
        slow_range=(20, 10, 100),
    )

    print(f"Success: {result.success}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Results found: {len(result.results)}")
    if result.best_result:
        print(f"Best: Fast={result.best_result.fast_period}, Slow={result.best_result.slow_period}")
        print(f"       Profit Factor={result.best_result.profit_factor}")
    if result.error:
        print(f"Error: {result.error}")
