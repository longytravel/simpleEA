"""
Optimization INI Builder

Creates MT5 Strategy Tester INI files for optimization runs.
Includes support for cloud agents and forward testing.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, DEFAULT_DEPOSIT, DEFAULT_CURRENCY,
    DEFAULT_LEVERAGE, DEFAULT_LATENCY, DEFAULT_MODEL, BACKTEST_FROM, BACKTEST_TO
)
from settings import get_settings
from optimizer.param_extractor import EAParameter, extract_parameters


@dataclass
class OptimizationConfig:
    """Configuration for an optimization run."""
    # EA settings
    ea_name: str
    ea_path: Optional[Path] = None

    # Symbol/timeframe
    symbol: str = DEFAULT_SYMBOL
    timeframe: str = DEFAULT_TIMEFRAME

    # Account settings
    deposit: int = DEFAULT_DEPOSIT
    currency: str = DEFAULT_CURRENCY
    leverage: int = DEFAULT_LEVERAGE

    # Execution settings
    latency: int = DEFAULT_LATENCY  # 10ms
    model: int = DEFAULT_MODEL       # 1 = 1-minute OHLC

    # Date range (4 years total)
    from_date: str = BACKTEST_FROM   # 2021.12.24
    to_date: str = BACKTEST_TO       # 2025.12.24

    # Forward test (1 year out of 4)
    forward_date: str = "2024.12.24"  # 3yr in-sample, 1yr forward

    # Optimization settings
    optimization_type: int = 2        # 2 = Genetic
    optimization_criterion: int = 1   # 1 = Profit Factor max (6=Custom requires OnTester)

    # Agent settings
    use_local: bool = True
    use_remote: bool = False
    use_cloud: bool = True            # MQL5 Cloud Network

    # Report settings
    report_name: Optional[str] = None
    shutdown_terminal: bool = True
    visual: bool = False


def build_optimization_ini(
    config: OptimizationConfig,
    parameters: List[EAParameter],
    output_path: Path
) -> Path:
    """
    Build an optimization INI file.

    Args:
        config: Optimization configuration
        parameters: List of EA parameters with ranges
        output_path: Where to save the INI file

    Returns:
        Path to created INI file
    """
    # Build INI content
    ini_lines = [
        "[Tester]",
        f"Expert={config.ea_name}",
        f"Symbol={config.symbol}",
        f"Period={config.timeframe}",
        f"Model={config.model}",
        f"Optimization={config.optimization_type}",
        f"OptimizationCriterion={config.optimization_criterion}",
        f"FromDate={config.from_date}",
        f"ToDate={config.to_date}",
        f"ForwardMode=4",  # 4 = Custom date
        f"ForwardDate={config.forward_date}",
        f"Deposit={config.deposit}",
        f"Currency={config.currency}",
        f"Leverage={config.leverage}",
        f"ExecutionMode={config.latency}",
        f"UseLocal={1 if config.use_local else 0}",
        f"UseRemote={1 if config.use_remote else 0}",
        f"UseCloud={1 if config.use_cloud else 0}",
    ]

    if config.report_name:
        ini_lines.append(f"Report={config.report_name}")
        ini_lines.append("ReplaceReport=1")

    if config.shutdown_terminal:
        ini_lines.append("ShutdownTerminal=1")

    ini_lines.append(f"Visual={1 if config.visual else 0}")

    # Add parameters section
    ini_lines.append("")
    ini_lines.append("[TesterInputs]")

    for param in parameters:
        # Convert boolean defaults to 1/0 for MT5
        default_val = param.default
        if param.type == 'bool':
            default_val = 1 if param.default else 0

        # Only optimize if: optimize=True, has valid range, AND step > 0
        # MT5 rejects optimization with step=0
        can_optimize = (
            param.optimize and
            param.min_val is not None and
            param.step is not None and
            param.step > 0
        )

        if can_optimize:
            # Format: name=default||min||step||max||Y
            line = f"{param.name}={default_val}||{param.min_val}||{param.step}||{param.max_val}||Y"
        else:
            # Format: name=default||0||0||0||N
            line = f"{param.name}={default_val}||0||0||0||N"
        ini_lines.append(line)

    # Write INI file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(ini_lines)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return output_path


def load_intelligent_ranges(ea_name: str, output_dir: Path) -> Optional[List[dict]]:
    """
    Load intelligent optimization ranges from param_intelligence.py output.

    Returns None if file doesn't exist (falls back to param_extractor).
    """
    opt_inputs_file = output_dir / f"{ea_name}_opt_inputs.json"
    if opt_inputs_file.exists():
        with open(opt_inputs_file, 'r') as f:
            return json.load(f)
    return None


def create_optimization_from_ea(
    ea_path: Path,
    output_dir: Path,
    use_cloud: Optional[bool] = None,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    criterion: Optional[int] = None
) -> dict:
    """
    Create a complete optimization setup from an EA file.

    Uses intelligent ranges from param_intelligence.py if available,
    otherwise falls back to param_extractor.py.

    Args:
        ea_path: Path to .mq5 file
        output_dir: Directory to save INI file
        use_cloud: Enable MQL5 Cloud Network (None = use settings default)
        symbol: Trading symbol
        timeframe: Timeframe

    Returns:
        Dict with ini_path, parameters, and summary
    """
    # Get cloud setting from settings.py if not specified
    if use_cloud is None:
        use_cloud = get_settings().optimization.use_cloud

    ea_name = ea_path.stem

    # Try to load intelligent ranges first
    intelligent_ranges = load_intelligent_ranges(ea_name, output_dir)

    if intelligent_ranges:
        # Convert intelligent ranges to EAParameter objects
        parameters = []
        for p in intelligent_ranges:
            param = EAParameter(
                name=p['name'],
                type='double',  # Will be refined below
                default=p['default'],
                min_val=p['min'] if p['optimize'] else None,
                max_val=p['max'] if p['optimize'] else None,
                step=p['step'] if p['optimize'] else None,
                optimize=p['optimize']
            )
            # Infer type from default value
            if isinstance(p['default'], bool) or p['name'].lower().startswith('enable'):
                param.type = 'bool'
            elif isinstance(p['default'], int) or (isinstance(p['default'], float) and p['default'] == int(p['default'])):
                param.type = 'int'
            parameters.append(param)

        extraction_source = "param_intelligence.py (intelligent ranges)"
    else:
        # Fall back to param_extractor
        extraction = extract_parameters(str(ea_path))

        if not extraction.success:
            return {
                "success": False,
                "error": extraction.error
            }

        parameters = extraction.parameters
        extraction_source = "param_extractor.py (auto-generated ranges)"

    # Ensure we have parameters
    if not parameters:
        return {
            "success": False,
            "error": "No parameters found"
        }

    # Create config (ea_name already defined above)
    report_name = f"{ea_name}_OPT"

    config = OptimizationConfig(
        ea_name=ea_name,
        ea_path=ea_path,
        symbol=symbol,
        timeframe=timeframe,
        use_cloud=use_cloud,
        report_name=report_name
    )

    # Override criterion if specified (6 = Custom max; uses OnTester() when injected)
    if criterion is not None:
        config.optimization_criterion = criterion

    # Build INI
    ini_path = output_dir / f"{ea_name}_optimize.ini"
    build_optimization_ini(config, parameters, ini_path)

    # Calculate combinations
    optimize_params = [p for p in parameters if p.optimize]
    combinations = 1
    for p in optimize_params:
        if p.type == 'bool':
            combinations *= 2
        elif p.step and p.step > 0:
            steps = int((p.max_val - p.min_val) / p.step) + 1
            combinations *= steps

    return {
        "success": True,
        "ini_path": str(ini_path),
        "ea_name": ea_name,
        "source": extraction_source,
        "parameters": {
            "optimize": [
                {
                    "name": p.name,
                    "range": f"{p.min_val} -> {p.max_val}",
                    "step": p.step,
                    "default": p.default
                }
                for p in optimize_params
            ],
            "fixed": [
                {"name": p.name, "value": p.default}
                for p in parameters if not p.optimize
            ]
        },
        "estimated_combinations": combinations,
        "settings": {
            "symbol": symbol,
            "timeframe": timeframe,
            "in_sample": f"{config.from_date} -> {config.forward_date}",
            "forward_test": f"{config.forward_date} -> {config.to_date}",
            "cloud_agents": use_cloud,
            "optimization": "Genetic"
        }
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build optimization INI file")
    parser.add_argument("ea_path", help="Path to EA .mq5 file")
    parser.add_argument("--output", "-o", help="Output directory", default="runs")
    parser.add_argument("--cloud", choices=["on", "off"],
                        help="Enable MQL5 Cloud Network (default: from settings.py)")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--criterion", type=int, choices=[0, 1, 2, 3, 4, 5, 6],
                        help="Optimization criterion: 0=Balance, 1=PF, 2=Payoff, 3=DD, 4=Recovery, 5=Sharpe, 6=Custom")

    args = parser.parse_args()

    ea_path = Path(args.ea_path)
    output_dir = Path(args.output)

    # None = use settings default, otherwise use explicit value
    use_cloud = None if args.cloud is None else (args.cloud == "on")

    result = create_optimization_from_ea(
        ea_path=ea_path,
        output_dir=output_dir,
        use_cloud=use_cloud,
        symbol=args.symbol,
        timeframe=args.timeframe,
        criterion=args.criterion
    )

    print(json.dumps(result, indent=2))

    if result["success"]:
        print(f"\n--- Optimization INI Created ---")
        print(f"File: {result['ini_path']}")
        print(f"\nParameters to optimize ({len(result['parameters']['optimize'])}):")
        for p in result['parameters']['optimize']:
            range_str = p['range'].replace('\u2192', '->')
            print(f"  {p['name']}: {range_str} (step {p['step']})")
        print(f"\nFixed parameters ({len(result['parameters']['fixed'])}):")
        for p in result['parameters']['fixed']:
            print(f"  {p['name']}: {p['value']}")
        print(f"\nEstimated combinations: {result['estimated_combinations']}")
        print(f"Cloud agents: {'ON' if use_cloud else 'OFF'}")
