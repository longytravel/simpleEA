"""
MT5 Strategy Tester INI File Generator
Supports backtesting, optimization, and forward testing.
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, DEFAULT_DEPOSIT, DEFAULT_CURRENCY,
    DEFAULT_LEVERAGE, DEFAULT_LATENCY, DEFAULT_MODEL, BACKTEST_FROM, BACKTEST_TO
)


@dataclass
class InputParam:
    """Represents an EA input parameter for optimization."""
    name: str
    default: float
    min_val: float = 0
    step: float = 0
    max_val: float = 0
    optimize: bool = False

    def to_ini_line(self) -> str:
        """Convert to INI format: name=default||min||step||max||Y/N"""
        opt_flag = 'Y' if self.optimize else 'N'
        return f"{self.name}={self.default}||{self.min_val}||{self.step}||{self.max_val}||{opt_flag}"


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    expert: str                          # EA name (without .ex5)
    symbol: str = DEFAULT_SYMBOL
    period: str = DEFAULT_TIMEFRAME
    model: int = DEFAULT_MODEL           # 0=Every tick, 1=OHLC, 2=Open price
    deposit: int = DEFAULT_DEPOSIT
    currency: str = DEFAULT_CURRENCY
    leverage: int = DEFAULT_LEVERAGE
    latency: int = DEFAULT_LATENCY       # ExecutionMode in ms
    from_date: str = BACKTEST_FROM
    to_date: str = BACKTEST_TO
    forward_mode: int = 0                # 0=No, 1=Half, 2=Third, 3=Quarter, 4=Custom
    forward_date: Optional[str] = None   # Custom forward start date
    optimization: int = 0                # 0=Disabled, 1=Slow, 2=Genetic
    optimization_criterion: int = 6      # 6=Custom max (profit factor)
    report_name: Optional[str] = None    # Report name (without extension)
    replace_report: bool = True
    shutdown_terminal: bool = True
    visual: bool = False
    use_local: bool = True               # UseLocal=1 for local history
    inputs: list = field(default_factory=list)  # List of InputParam


def create_backtest_ini(config: BacktestConfig, ini_path: Path) -> Path:
    """
    Create an INI file for MT5 Strategy Tester.

    Args:
        config: Backtest configuration
        ini_path: Where to save the INI file

    Returns:
        Path to the created INI file
    """
    # Convert period string to MT5 format
    period_map = {
        'M1': 'M1', 'M5': 'M5', 'M15': 'M15', 'M30': 'M30',
        'H1': 'H1', 'H4': 'H4', 'D1': 'D1', 'W1': 'W1', 'MN1': 'MN1'
    }
    period = period_map.get(config.period, config.period)

    # Build INI content
    ini_content = f"""[Tester]
Expert={config.expert}
Symbol={config.symbol}
Period={period}
Optimization={config.optimization}
Model={config.model}
FromDate={config.from_date}
ToDate={config.to_date}
ForwardMode={config.forward_mode}
Deposit={config.deposit}
Currency={config.currency}
Leverage={config.leverage}
ExecutionMode={config.latency}
"""

    # Add forward date if using custom forward mode
    if config.forward_mode == 4 and config.forward_date:
        ini_content += f"ForwardDate={config.forward_date}\n"

    # Add optimization criterion if optimizing
    if config.optimization > 0:
        ini_content += f"OptimizationCriterion={config.optimization_criterion}\n"

    if config.report_name:
        ini_content += f"Report={config.report_name}\n"
        ini_content += f"ReplaceReport={1 if config.replace_report else 0}\n"

    if config.use_local:
        ini_content += "UseLocal=1\n"

    ini_content += f"Visual={1 if config.visual else 0}\n"

    if config.shutdown_terminal:
        ini_content += "ShutdownTerminal=1\n"

    # Add TesterInputs section if we have input parameters
    if config.inputs:
        ini_content += "\n[TesterInputs]\n"
        for inp in config.inputs:
            ini_content += inp.to_ini_line() + "\n"

    # Write INI file
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ini_path, 'w', encoding='utf-8') as f:
        f.write(ini_content)

    return ini_path


def create_optimization_ini(
    config: BacktestConfig,
    ini_path: Path,
    fast_range: tuple = (5, 5, 50),    # (min, step, max)
    slow_range: tuple = (20, 10, 200),  # (min, step, max)
    optimization_type: int = 2,         # 2 = Genetic
    forward_date: str = None            # Forward test start date
) -> Path:
    """
    Create an INI file for MT5 optimization with parameter ranges.
    """
    config.optimization = optimization_type

    if forward_date:
        config.forward_mode = 4  # 4 = Custom
        config.forward_date = forward_date

    config.inputs = [
        InputParam(
            name="FastPeriod",
            default=fast_range[0],
            min_val=fast_range[0],
            step=fast_range[1],
            max_val=fast_range[2],
            optimize=True
        ),
        InputParam(
            name="SlowPeriod",
            default=slow_range[0],
            min_val=slow_range[0],
            step=slow_range[1],
            max_val=slow_range[2],
            optimize=True
        ),
        InputParam(name="LotSize", default=0.01, optimize=False),
        InputParam(name="MagicNumber", default=123456, optimize=False),
        InputParam(name="Slippage", default=10, optimize=False),
    ]

    return create_backtest_ini(config, ini_path)


def create_forward_test_ini(
    config: BacktestConfig,
    ini_path: Path,
    fast_period: int,
    slow_period: int,
) -> Path:
    """
    Create an INI file for forward testing with specific parameters.
    """
    config.optimization = 0  # No optimization, just backtest

    config.inputs = [
        InputParam(name="FastPeriod", default=fast_period, optimize=False),
        InputParam(name="SlowPeriod", default=slow_period, optimize=False),
        InputParam(name="LotSize", default=0.01, optimize=False),
        InputParam(name="MagicNumber", default=123456, optimize=False),
        InputParam(name="Slippage", default=10, optimize=False),
    ]

    return create_backtest_ini(config, ini_path)
