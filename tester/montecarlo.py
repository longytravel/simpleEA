"""
Monte Carlo Simulation for EA Robustness Testing

Shuffles trade order to test strategy robustness.
A robust strategy should maintain profitability regardless of trade sequence.
"""

import random
import math
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple
import json
import sys

# Add parent dir for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.trade_extractor import Trade, TradeExtractor, extract_trades


@dataclass
class EquityCurveStats:
    """Statistics from a single equity curve simulation."""
    final_equity: float
    max_drawdown: float
    max_drawdown_pct: float
    peak_equity: float
    lowest_equity: float
    ruin_occurred: bool  # Did equity drop below ruin threshold?


@dataclass
class MonteCarloResult:
    """Results of Monte Carlo simulation."""
    iterations: int
    initial_balance: float

    # Profit statistics
    median_profit: float
    mean_profit: float
    profit_std: float
    profit_5th_percentile: float
    profit_95th_percentile: float

    # Drawdown statistics
    median_max_drawdown: float
    mean_max_drawdown: float
    max_drawdown_95th_percentile: float

    # Confidence metrics
    confidence_level: float  # % of iterations that were profitable
    probability_of_ruin: float  # % of iterations that hit ruin threshold
    ruin_threshold_pct: float

    # Original metrics for comparison
    original_profit: float
    original_drawdown: float

    # Trade info
    trade_count: int

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @property
    def is_robust(self) -> bool:
        """Check if strategy meets robustness criteria."""
        return (
            self.confidence_level >= 70 and
            self.probability_of_ruin <= 5
        )


class MonteCarloSimulator:
    """
    Monte Carlo simulation through trade shuffling.

    Shuffles the order of trades and calculates equity curves to determine
    the robustness of a trading strategy.
    """

    def __init__(
        self,
        iterations: int = 1000,
        ruin_threshold_pct: float = 50.0,
        seed: Optional[int] = None
    ):
        """
        Initialize Monte Carlo simulator.

        Args:
            iterations: Number of shuffle iterations
            ruin_threshold_pct: Equity loss % considered "ruin"
            seed: Random seed for reproducibility
        """
        self.iterations = iterations
        self.ruin_threshold_pct = ruin_threshold_pct
        if seed is not None:
            random.seed(seed)

    def run(
        self,
        trades: List[Trade],
        initial_balance: float
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation on a list of trades.

        Args:
            trades: List of Trade objects
            initial_balance: Starting account balance

        Returns:
            MonteCarloResult with statistics
        """
        if not trades:
            return self._empty_result(initial_balance)

        # Use per-trade NET results (includes commission/swap).
        profits = [
            getattr(t, "net_profit", (t.profit + t.commission + t.swap))
            for t in trades
        ]
        original_profit = sum(profits)

        # Calculate original drawdown
        original_stats = self._calculate_equity_stats(profits, initial_balance)

        # Run simulations
        results: List[EquityCurveStats] = []
        for _ in range(self.iterations):
            shuffled = profits.copy()
            random.shuffle(shuffled)
            stats = self._calculate_equity_stats(shuffled, initial_balance)
            results.append(stats)

        # Calculate statistics
        final_equities = [r.final_equity - initial_balance for r in results]
        max_drawdowns = [r.max_drawdown for r in results]
        ruin_count = sum(1 for r in results if r.ruin_occurred)

        return MonteCarloResult(
            iterations=self.iterations,
            initial_balance=initial_balance,

            # Profit stats
            median_profit=self._percentile(final_equities, 50),
            mean_profit=sum(final_equities) / len(final_equities),
            profit_std=self._std(final_equities),
            profit_5th_percentile=self._percentile(final_equities, 5),
            profit_95th_percentile=self._percentile(final_equities, 95),

            # Drawdown stats
            median_max_drawdown=self._percentile(max_drawdowns, 50),
            mean_max_drawdown=sum(max_drawdowns) / len(max_drawdowns),
            max_drawdown_95th_percentile=self._percentile(max_drawdowns, 95),

            # Confidence
            confidence_level=sum(1 for e in final_equities if e > 0) / len(final_equities) * 100,
            probability_of_ruin=ruin_count / self.iterations * 100,
            ruin_threshold_pct=self.ruin_threshold_pct,

            # Original
            original_profit=original_profit,
            original_drawdown=original_stats.max_drawdown,

            # Trade info
            trade_count=len(trades)
        )

    def _calculate_equity_stats(
        self,
        profits: List[float],
        initial_balance: float
    ) -> EquityCurveStats:
        """Calculate equity curve statistics for a sequence of trades."""
        equity = initial_balance
        peak = initial_balance
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        lowest = initial_balance
        ruin_threshold = initial_balance * (1 - self.ruin_threshold_pct / 100)
        ruin_occurred = False

        for profit in profits:
            equity += profit

            # Track peak
            if equity > peak:
                peak = equity

            # Track lowest
            if equity < lowest:
                lowest = equity

            # Track drawdown
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = (drawdown / peak) * 100 if peak > 0 else 0

            # Check ruin
            if equity <= ruin_threshold:
                ruin_occurred = True

        return EquityCurveStats(
            final_equity=equity,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            peak_equity=peak,
            lowest_equity=lowest,
            ruin_occurred=ruin_occurred
        )

    def _percentile(self, data: List[float], p: float) -> float:
        """Calculate percentile of a list."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    def _std(self, data: List[float]) -> float:
        """Calculate standard deviation."""
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)
        return math.sqrt(variance)

    def _empty_result(self, initial_balance: float) -> MonteCarloResult:
        """Return empty result when no trades available."""
        return MonteCarloResult(
            iterations=0,
            initial_balance=initial_balance,
            median_profit=0,
            mean_profit=0,
            profit_std=0,
            profit_5th_percentile=0,
            profit_95th_percentile=0,
            median_max_drawdown=0,
            mean_max_drawdown=0,
            max_drawdown_95th_percentile=0,
            confidence_level=0,
            probability_of_ruin=100,
            ruin_threshold_pct=self.ruin_threshold_pct,
            original_profit=0,
            original_drawdown=0,
            trade_count=0
        )


def run_montecarlo(
    report_path: str,
    iterations: int = 1000,
    ruin_threshold_pct: float = 50.0
) -> MonteCarloResult:
    """
    Convenience function to run Monte Carlo on a report file.

    Args:
        report_path: Path to HTML backtest report
        iterations: Number of shuffle iterations
        ruin_threshold_pct: Equity loss % considered ruin

    Returns:
        MonteCarloResult
    """
    # Extract trades
    extraction = extract_trades(report_path)
    if not extraction.success or not extraction.trades:
        simulator = MonteCarloSimulator(iterations, ruin_threshold_pct)
        return simulator._empty_result(extraction.initial_balance or 10000)

    # Run simulation
    simulator = MonteCarloSimulator(iterations, ruin_threshold_pct)
    return simulator.run(extraction.trades, extraction.initial_balance)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Monte Carlo simulation for EA robustness testing"
    )
    parser.add_argument("report", help="Path to HTML backtest report")
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=1000,
        help="Number of shuffle iterations (default: 1000)"
    )
    parser.add_argument(
        "--ruin-threshold",
        type=float,
        default=50.0,
        help="Equity loss %% considered ruin (default: 50)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducibility"
    )

    args = parser.parse_args()

    # Extract trades
    extraction = extract_trades(args.report)
    if not extraction.success:
        print(f"Error extracting trades: {extraction.error}")
        sys.exit(1)

    if not extraction.trades:
        print("No trades found in report")
        sys.exit(1)

    print(f"Extracted {len(extraction.trades)} trades")
    print(f"Initial balance: {extraction.initial_balance:.2f}")
    print(f"Running {args.iterations} Monte Carlo iterations...")

    # Run simulation
    if args.seed:
        random.seed(args.seed)

    simulator = MonteCarloSimulator(
        iterations=args.iterations,
        ruin_threshold_pct=args.ruin_threshold
    )
    result = simulator.run(extraction.trades, extraction.initial_balance)

    # Output JSON
    print("\n" + result.to_json())

    # Summary
    print("\n--- Monte Carlo Summary ---")
    print(f"Iterations: {result.iterations}")
    print(f"Original profit: {result.original_profit:.2f}")
    print(f"Median profit (shuffled): {result.median_profit:.2f}")
    print(f"Profit 5th-95th percentile: {result.profit_5th_percentile:.2f} to {result.profit_95th_percentile:.2f}")
    print(f"Confidence level: {result.confidence_level:.1f}%")
    print(f"Probability of ruin: {result.probability_of_ruin:.1f}%")
    print(f"Max drawdown 95th pct: {result.max_drawdown_95th_percentile:.2f}")
    print(f"\nRobust: {'YES' if result.is_robust else 'NO'}")
