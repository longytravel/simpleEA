"""
EA Stress Test System - Configuration Settings

All configurable thresholds and settings for the stress test pipeline.
Uses Pydantic for validation and easy JSON serialization.
"""

from pydantic import BaseModel, Field
from pathlib import Path
from typing import List, Optional
import json


class WorkerSettings(BaseModel):
    """MT5 worker pool settings."""
    max_workers: int = Field(default=4, ge=1, le=4, description="Max parallel MT5 instances")
    current_workers: int = Field(default=1, ge=1, le=4, description="Currently active workers")


class SuccessThresholds(BaseModel):
    """Success criteria for EA validation."""
    min_profit_factor: float = Field(default=1.5, ge=1.0, description="Primary pair threshold")
    min_secondary_pf: float = Field(default=1.0, ge=0.5, description="Secondary pairs threshold")
    min_pairs_profitable: int = Field(default=3, ge=1, description="Minimum profitable pairs out of tested")
    max_drawdown_pct: float = Field(default=30.0, ge=5.0, le=100.0, description="Max acceptable drawdown %")
    min_trades: int = Field(default=50, ge=10, description="Minimum trades for statistical significance")
    min_win_rate: float = Field(default=40.0, ge=0.0, le=100.0, description="Minimum win rate %")


class MonteCarloSettings(BaseModel):
    """Monte Carlo simulation settings."""
    iterations: int = Field(default=1000, ge=100, le=10000, description="Number of shuffle iterations")
    confidence_min: float = Field(default=70.0, ge=50.0, le=99.0, description="Min confidence level %")
    max_ruin_probability: float = Field(default=5.0, ge=0.0, le=50.0, description="Max probability of ruin %")
    ruin_threshold_pct: float = Field(default=50.0, ge=10.0, le=100.0, description="Equity loss % considered ruin")


class TestPairs(BaseModel):
    """Currency pairs for multi-pair testing."""
    primary: str = Field(default="EURUSD", description="Primary optimization pair")
    secondary: List[str] = Field(
        default=["GBPUSD", "USDJPY", "AUDUSD", "EURJPY"],
        description="Secondary validation pairs"
    )

    @property
    def all_pairs(self) -> List[str]:
        """Get all pairs including primary."""
        return [self.primary] + self.secondary


class OptimizationSettings(BaseModel):
    """Optimization and forward test settings."""
    use_cloud: bool = Field(default=True, description="Use MQL5 Cloud Network (faster but costs money)")
    in_sample_ratio: float = Field(default=0.75, ge=0.5, le=0.9, description="In-sample data ratio")
    out_sample_ratio: float = Field(default=0.25, ge=0.1, le=0.5, description="Out-of-sample ratio")
    genetic_population: int = Field(default=128, ge=32, le=512, description="Genetic algorithm population")
    optimization_criterion: int = Field(default=6, description="0=Balance, 6=Custom max")


class FixerSettings(BaseModel):
    """Error fixing settings."""
    max_attempts: int = Field(default=5, ge=1, le=10, description="Max fix attempts before failing")
    use_opus_for_complex: bool = Field(default=True, description="Use Opus model for complex errors")


class ApprovalSettings(BaseModel):
    """Workflow approval settings."""
    autonomous_mode: bool = Field(default=False, description="Run without user approval")
    trusted_fix_patterns: List[str] = Field(
        default=[],
        description="Fix patterns that don't need approval"
    )
    pause_on_improvement: bool = Field(default=True, description="Pause before implementing improvements")


class ScoringWeights(BaseModel):
    """Weights for EA scoring/ranking."""
    profit_factor: float = Field(default=20.0, description="Weight for profit factor")
    win_rate: float = Field(default=10.0, description="Weight for win rate")
    max_drawdown: float = Field(default=-2.0, description="Weight for max drawdown (negative=lower is better)")
    recovery_factor: float = Field(default=15.0, description="Weight for recovery factor")
    total_trades: float = Field(default=0.1, description="Weight for trade count")
    sharpe_ratio: float = Field(default=5.0, description="Weight for Sharpe ratio")
    monte_carlo_confidence: float = Field(default=10.0, description="Weight for MC confidence")


class StressTestSettings(BaseModel):
    """Complete stress test configuration."""
    workers: WorkerSettings = Field(default_factory=WorkerSettings)
    thresholds: SuccessThresholds = Field(default_factory=SuccessThresholds)
    monte_carlo: MonteCarloSettings = Field(default_factory=MonteCarloSettings)
    pairs: TestPairs = Field(default_factory=TestPairs)
    optimization: OptimizationSettings = Field(default_factory=OptimizationSettings)
    fixer: FixerSettings = Field(default_factory=FixerSettings)
    approval: ApprovalSettings = Field(default_factory=ApprovalSettings)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)

    def save(self, path: Path) -> None:
        """Save settings to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.model_dump(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "StressTestSettings":
        """Load settings from JSON file."""
        with open(path, 'r') as f:
            return cls.model_validate(json.load(f))

    @classmethod
    def load_or_default(cls, path: Path) -> "StressTestSettings":
        """Load from file if exists, otherwise return defaults."""
        if path.exists():
            return cls.load(path)
        return cls()


# Default instance for easy import
settings = StressTestSettings()

# Settings file path
SETTINGS_FILE = Path(__file__).parent / "stress_test_settings.json"


def get_settings() -> StressTestSettings:
    """Get settings, loading from file if available."""
    return StressTestSettings.load_or_default(SETTINGS_FILE)


def save_settings(s: StressTestSettings) -> None:
    """Save settings to default file."""
    s.save(SETTINGS_FILE)


if __name__ == "__main__":
    # Print default settings as JSON
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        save_settings(settings)
        print(f"Settings saved to {SETTINGS_FILE}")
    else:
        print(settings.model_dump_json(indent=2))
