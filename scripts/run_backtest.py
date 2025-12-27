#!/usr/bin/env python3
"""
CLI wrapper for running backtests.
Outputs JSON for Claude Code to parse.

Usage:
    python run_backtest.py <ea_name> [--timeout SECONDS] [--params params.json]
"""

import sys
import json
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tester import BacktestRunner
from parser import ReportParser
from config import BACKTEST_FROM, BACKTEST_TO, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME


def load_params(params_arg: str) -> dict:
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


def main():
    parser = argparse.ArgumentParser(description='Run backtest on an EA')
    parser.add_argument('ea_name', help='Name of the EA (without .ex5)')
    parser.add_argument('--timeout', type=int, default=300, help='Timeout in seconds')
    parser.add_argument('--symbol', default=DEFAULT_SYMBOL, help='Symbol to test')
    parser.add_argument('--timeframe', default=DEFAULT_TIMEFRAME, help='Timeframe')
    parser.add_argument('--params', help='EA parameters as JSON file path or inline JSON string')
    args = parser.parse_args()

    # Load parameters if provided
    inputs = load_params(args.params) if args.params else None

    tester = BacktestRunner(timeout=args.timeout)
    parser_obj = ReportParser()

    try:
        # Run backtest
        result = tester.run(
            ea_name=args.ea_name,
            symbol=args.symbol,
            timeframe=args.timeframe,
            from_date=BACKTEST_FROM,
            to_date=BACKTEST_TO,
            inputs=inputs,
        )

        if not result.success or not result.report_path:
            print(json.dumps({
                "success": False,
                "error": result.error or "Backtest failed - no report generated"
            }))
            sys.exit(1)

        report_path = result.report_path

        # Parse results
        metrics = parser_obj.parse(report_path)

        if not metrics:
            print(json.dumps({
                "success": False,
                "error": "Failed to parse backtest report"
            }))
            sys.exit(1)

        output = {
            "success": True,
            "ea_name": args.ea_name,
            "report_path": str(report_path),
            "metrics": metrics.to_dict(),
            "period": {
                "from": BACKTEST_FROM,
                "to": BACKTEST_TO,
                "symbol": args.symbol,
                "timeframe": args.timeframe
            },
            "params_used": inputs,
        }

        print(json.dumps(output, indent=2))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
