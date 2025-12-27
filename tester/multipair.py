"""
Multi-Pair Testing Module

Tests an EA across multiple currency pairs to validate robustness.
A robust strategy should work on related pairs, not just the optimized one.
"""

import time
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    MT5_TERMINAL, MT5_DATA_PATH, MT5_EXPERTS_PATH,
    DEFAULT_TIMEFRAME, BACKTEST_FROM, BACKTEST_TO
)
from parser.report import ReportParser, BacktestMetrics
from tester.backtest import BacktestRunner, BacktestResult


@dataclass
class PairResult:
    """Result of testing on a single pair."""
    symbol: str
    success: bool
    profit_factor: float = 0.0
    total_profit: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0
    recovery_factor: float = 0.0
    report_path: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_profitable(self) -> bool:
        """Check if pair was profitable."""
        return self.success and self.profit_factor > 1.0


@dataclass
class MultiPairResult:
    """Result of multi-pair testing."""
    ea_name: str
    primary_pair: str
    pairs_tested: List[str]
    results: Dict[str, PairResult]
    total_duration: float

    # Summary stats
    pairs_profitable: int = 0
    pairs_failed: int = 0
    average_profit_factor: float = 0.0
    min_profit_factor: float = 0.0
    max_profit_factor: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ea_name": self.ea_name,
            "primary_pair": self.primary_pair,
            "pairs_tested": self.pairs_tested,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "total_duration": self.total_duration,
            "summary": {
                "pairs_profitable": self.pairs_profitable,
                "pairs_failed": self.pairs_failed,
                "average_profit_factor": self.average_profit_factor,
                "min_profit_factor": self.min_profit_factor,
                "max_profit_factor": self.max_profit_factor,
            }
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @property
    def is_robust(self) -> bool:
        """Check if EA is robust across pairs."""
        # At least 3 pairs should be profitable, or 60% of pairs
        min_profitable = min(3, len(self.pairs_tested))
        pct_threshold = 0.6
        return (
            self.pairs_profitable >= min_profitable or
            self.pairs_profitable / len(self.pairs_tested) >= pct_threshold
        )


class MultiPairTester:
    """
    Tests an EA across multiple currency pairs.

    Uses sequential testing (one pair at a time) to avoid MT5 conflicts.
    Can be extended to use parallel workers with separate MT5 data folders.
    """

    def __init__(
        self,
        pairs: Optional[List[str]] = None,
        timeout_per_pair: int = 300,
        run_dir: Optional[Path] = None,
        inputs: Optional[Dict] = None
    ):
        """
        Initialize multi-pair tester.

        Args:
            pairs: List of pairs to test (default: major pairs)
            timeout_per_pair: Backtest timeout per pair in seconds
            run_dir: Directory to store results
            inputs: EA input parameters to use for all pairs
        """
        self.pairs = pairs or [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY"
        ]
        self.timeout = timeout_per_pair
        self.run_dir = run_dir
        self.inputs = inputs
        self.report_parser = ReportParser()

    def test(
        self,
        ea_name: str,
        primary_pair: Optional[str] = None,
        timeframe: str = DEFAULT_TIMEFRAME,
        from_date: str = BACKTEST_FROM,
        to_date: str = BACKTEST_TO,
    ) -> MultiPairResult:
        """
        Test EA on multiple pairs.

        Args:
            ea_name: Name of the EA to test
            primary_pair: Primary (optimized) pair (moves to front)
            timeframe: Timeframe to test
            from_date: Start date
            to_date: End date

        Returns:
            MultiPairResult with all pair results
        """
        start_time = time.time()

        # Reorder pairs to put primary first
        pairs_to_test = self.pairs.copy()
        if primary_pair and primary_pair in pairs_to_test:
            pairs_to_test.remove(primary_pair)
            pairs_to_test.insert(0, primary_pair)
        elif primary_pair:
            pairs_to_test.insert(0, primary_pair)

        # Setup run directory
        run_dir = self.run_dir or Path("runs") / "multipair"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Test each pair sequentially
        results: Dict[str, PairResult] = {}
        runner = BacktestRunner(timeout=self.timeout)

        for symbol in pairs_to_test:
            print(f"Testing {ea_name} on {symbol}...")
            pair_start = time.time()

            try:
                # Run backtest
                bt_result = runner.run(
                    ea_name=ea_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    from_date=from_date,
                    to_date=to_date,
                    run_dir=run_dir,
                    inputs=self.inputs,
                )

                if bt_result.success and bt_result.report_path:
                    # Parse metrics
                    metrics = self.report_parser.parse(bt_result.report_path)
                    if metrics:
                        results[symbol] = PairResult(
                            symbol=symbol,
                            success=True,
                            profit_factor=metrics.profit_factor,
                            total_profit=metrics.total_net_profit,
                            max_drawdown_pct=metrics.max_drawdown_pct,
                            win_rate=metrics.win_rate,
                            total_trades=metrics.total_trades,
                            sharpe_ratio=metrics.sharpe_ratio,
                            recovery_factor=metrics.recovery_factor,
                            report_path=str(bt_result.report_path),
                            duration_seconds=time.time() - pair_start
                        )
                    else:
                        results[symbol] = PairResult(
                            symbol=symbol,
                            success=False,
                            error="Failed to parse report",
                            duration_seconds=time.time() - pair_start
                        )
                else:
                    results[symbol] = PairResult(
                        symbol=symbol,
                        success=False,
                        error=bt_result.error or "Backtest failed",
                        duration_seconds=time.time() - pair_start
                    )

            except Exception as e:
                results[symbol] = PairResult(
                    symbol=symbol,
                    success=False,
                    error=str(e),
                    duration_seconds=time.time() - pair_start
                )

            # Small delay between tests
            time.sleep(2)

        # Calculate summary
        successful_pfs = [r.profit_factor for r in results.values() if r.success]
        pairs_profitable = sum(1 for r in results.values() if r.is_profitable)
        pairs_failed = sum(1 for r in results.values() if not r.success)

        result = MultiPairResult(
            ea_name=ea_name,
            primary_pair=primary_pair or pairs_to_test[0],
            pairs_tested=pairs_to_test,
            results=results,
            total_duration=time.time() - start_time,
            pairs_profitable=pairs_profitable,
            pairs_failed=pairs_failed,
            average_profit_factor=sum(successful_pfs) / len(successful_pfs) if successful_pfs else 0,
            min_profit_factor=min(successful_pfs) if successful_pfs else 0,
            max_profit_factor=max(successful_pfs) if successful_pfs else 0,
        )

        return result


def run_multipair_test(
    ea_name: str,
    pairs: Optional[List[str]] = None,
    primary_pair: Optional[str] = None,
    timeout: int = 300,
    inputs: Optional[Dict] = None
) -> MultiPairResult:
    """
    Convenience function to run multi-pair test.

    Args:
        ea_name: EA to test
        pairs: Pairs to test (optional)
        primary_pair: Primary optimization pair
        timeout: Timeout per pair
        inputs: EA input parameters

    Returns:
        MultiPairResult
    """
    tester = MultiPairTester(pairs=pairs, timeout_per_pair=timeout, inputs=inputs)
    return tester.test(ea_name, primary_pair=primary_pair)


def load_params(params_arg: str) -> Optional[Dict]:
    """Load parameters from JSON file or inline JSON string."""
    if not params_arg:
        return None

    # Check if it's a file path
    params_path = Path(params_arg)
    if params_path.exists():
        with open(params_path, 'r') as f:
            return json.load(f)

    # Try parsing as inline JSON
    try:
        return json.loads(params_arg)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid params: not a valid file path or JSON string: {params_arg}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test EA across multiple currency pairs"
    )
    parser.add_argument("ea_name", help="Name of EA to test")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY"],
        help="Pairs to test"
    )
    parser.add_argument(
        "--primary",
        help="Primary pair (tested first)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per pair in seconds"
    )
    parser.add_argument(
        "--timeframe",
        default="H1",
        help="Timeframe to test"
    )
    parser.add_argument(
        "--params",
        help="EA parameters as JSON file path or inline JSON string"
    )

    args = parser.parse_args()

    # Load parameters if provided
    inputs = load_params(args.params) if args.params else None

    print(f"Multi-pair testing: {args.ea_name}")
    print(f"Pairs: {args.pairs}")
    print(f"Timeout: {args.timeout}s per pair")
    if inputs:
        print(f"Using custom parameters from: {args.params}")

    tester = MultiPairTester(pairs=args.pairs, timeout_per_pair=args.timeout, inputs=inputs)
    result = tester.test(
        ea_name=args.ea_name,
        primary_pair=args.primary,
        timeframe=args.timeframe
    )

    print("\n" + result.to_json())

    print("\n--- Multi-Pair Summary ---")
    print(f"EA: {result.ea_name}")
    print(f"Pairs tested: {len(result.pairs_tested)}")
    print(f"Pairs profitable: {result.pairs_profitable}")
    print(f"Pairs failed: {result.pairs_failed}")
    print(f"Average PF: {result.average_profit_factor:.2f}")
    print(f"PF range: {result.min_profit_factor:.2f} - {result.max_profit_factor:.2f}")
    print(f"Total time: {result.total_duration:.1f}s")
    print(f"\nRobust: {'YES' if result.is_robust else 'NO'}")

    print("\nPer-pair results:")
    for symbol, pr in result.results.items():
        status = "OK" if pr.success else "FAIL"
        pf = f"PF={pr.profit_factor:.2f}" if pr.success else pr.error
        print(f"  {symbol}: {status} - {pf}")
