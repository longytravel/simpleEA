"""
EA Ranker Module
Scores and ranks EAs based on backtest metrics.
"""
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SCORING_WEIGHTS, RUNS_DIR
from parser.report import BacktestMetrics


@dataclass
class RankedEA:
    """An EA with its score and ranking information."""
    ea_name: str
    score: float
    metrics: BacktestMetrics
    params: dict
    timestamp: str
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            'ea_name': self.ea_name,
            'score': self.score,
            'metrics': self.metrics.to_dict(),
            'params': self.params,
            'timestamp': self.timestamp,
            'rank': self.rank,
        }


class Ranker:
    """Scores and ranks EAs based on backtest performance."""

    def __init__(self, leaderboard_path: Optional[Path] = None, weights: Optional[dict] = None):
        """
        Initialize the ranker.

        Args:
            leaderboard_path: Path to the leaderboard JSON file
            weights: Custom scoring weights (uses SCORING_WEIGHTS if not provided)
        """
        self.leaderboard_path = leaderboard_path or (RUNS_DIR / "leaderboard.json")
        self.weights = weights or SCORING_WEIGHTS
        self.leaderboard: list[RankedEA] = []
        self._load_leaderboard()

    def _load_leaderboard(self):
        """Load existing leaderboard from file."""
        if self.leaderboard_path.exists():
            try:
                with open(self.leaderboard_path, 'r') as f:
                    data = json.load(f)
                    self.leaderboard = [
                        RankedEA(
                            ea_name=item['ea_name'],
                            score=item['score'],
                            metrics=BacktestMetrics(**item['metrics']),
                            params=item['params'],
                            timestamp=item['timestamp'],
                            rank=item.get('rank', 0),
                        )
                        for item in data
                    ]
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error loading leaderboard: {e}")
                self.leaderboard = []

    def _save_leaderboard(self):
        """Save leaderboard to file."""
        self.leaderboard_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.leaderboard_path, 'w') as f:
            json.dump([ea.to_dict() for ea in self.leaderboard], f, indent=2)

    def calculate_score(self, metrics: BacktestMetrics) -> float:
        """
        Calculate a composite score for an EA.

        Higher is better. The score considers:
        - Profit factor (higher is better)
        - Win rate (higher is better)
        - Max drawdown (lower is better, hence negative weight)
        - Recovery factor (higher is better)
        - Number of trades (small bonus for more trades)

        Args:
            metrics: Backtest metrics

        Returns:
            Composite score
        """
        score = 0.0

        # Profit factor contribution (capped at 5.0 to avoid outlier influence)
        pf = min(metrics.profit_factor, 5.0)
        score += pf * self.weights.get('profit_factor', 20)

        # Win rate contribution (as percentage, 0-100)
        score += metrics.win_rate * self.weights.get('win_rate', 10) / 100

        # Drawdown penalty (as percentage, higher drawdown = lower score)
        score += metrics.max_drawdown_pct * self.weights.get('max_drawdown_pct', -2)

        # Recovery factor contribution (capped at 10)
        rf = min(metrics.recovery_factor, 10.0)
        score += rf * self.weights.get('recovery_factor', 15)

        # Trade count bonus (encourages strategies with sufficient sample size)
        trade_bonus = min(metrics.total_trades, 100) * self.weights.get('total_trades', 0.1)
        score += trade_bonus

        return round(score, 2)

    def add_result(self, ea_name: str, metrics: BacktestMetrics, params: dict) -> RankedEA:
        """
        Add a new EA result to the leaderboard.

        Args:
            ea_name: Name of the EA
            metrics: Backtest metrics
            params: EA parameters

        Returns:
            The RankedEA object with score and rank
        """
        score = self.calculate_score(metrics)
        timestamp = datetime.now().isoformat()

        ranked_ea = RankedEA(
            ea_name=ea_name,
            score=score,
            metrics=metrics,
            params=params,
            timestamp=timestamp,
        )

        # Add to leaderboard and re-rank
        self.leaderboard.append(ranked_ea)
        self._update_ranks()
        self._save_leaderboard()

        return ranked_ea

    def _update_ranks(self):
        """Update rank numbers based on scores."""
        # Sort by score descending
        self.leaderboard.sort(key=lambda x: x.score, reverse=True)

        # Assign ranks
        for i, ea in enumerate(self.leaderboard):
            ea.rank = i + 1

    def get_top(self, n: int = 10) -> list[RankedEA]:
        """Get the top N EAs by score."""
        return self.leaderboard[:n]

    def get_leaderboard(self) -> list[dict]:
        """Get the full leaderboard as a list of dicts."""
        return [ea.to_dict() for ea in self.leaderboard]

    def get_leaderboard_summary(self) -> str:
        """Get a formatted summary of the leaderboard."""
        if not self.leaderboard:
            return "No EAs ranked yet."

        lines = ["=" * 80]
        lines.append("EA LEADERBOARD")
        lines.append("=" * 80)
        lines.append(f"{'Rank':<6}{'EA Name':<40}{'Score':<10}{'Profit Factor':<15}{'Win Rate':<10}")
        lines.append("-" * 80)

        for ea in self.get_top(10):
            lines.append(
                f"{ea.rank:<6}"
                f"{ea.ea_name[:38]:<40}"
                f"{ea.score:<10.2f}"
                f"{ea.metrics.profit_factor:<15.2f}"
                f"{ea.metrics.win_rate:<10.1f}%"
            )

        lines.append("=" * 80)
        lines.append(f"Total EAs ranked: {len(self.leaderboard)}")

        return "\n".join(lines)


if __name__ == "__main__":
    # Test the ranker
    ranker = Ranker()

    # Create some test metrics
    test_metrics = BacktestMetrics(
        total_net_profit=1500.0,
        profit_factor=1.85,
        max_drawdown=500.0,
        max_drawdown_pct=5.0,
        total_trades=150,
        winning_trades=90,
        losing_trades=60,
        win_rate=60.0,
        recovery_factor=3.0,
    )

    # Add to ranker
    result = ranker.add_result(
        ea_name="Test_MA_10_50",
        metrics=test_metrics,
        params={'fast_period': 10, 'slow_period': 50},
    )

    print(f"Score: {result.score}")
    print(f"Rank: {result.rank}")
    print()
    print(ranker.get_leaderboard_summary())
