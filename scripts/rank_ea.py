#!/usr/bin/env python3
"""
CLI wrapper for ranking EAs.
Outputs JSON for Claude Code to parse.

Usage:
    python rank_ea.py <ea_name> --metrics '{"profit_factor": 1.5, ...}'
    python rank_ea.py --show-leaderboard
"""

import sys
import json
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ranker import Ranker
from parser.report import BacktestMetrics


def main():
    parser = argparse.ArgumentParser(description='Rank an EA on the leaderboard')
    parser.add_argument('ea_name', nargs='?', help='Name of the EA')
    parser.add_argument('--metrics', help='JSON string of metrics')
    parser.add_argument('--params', help='JSON string of parameters')
    parser.add_argument('--show-leaderboard', action='store_true', help='Show current leaderboard')
    parser.add_argument('--top', type=int, default=10, help='Number of top EAs to show')
    args = parser.parse_args()

    ranker = Ranker()

    try:
        if args.show_leaderboard:
            leaderboard = ranker.get_leaderboard()
            output = {
                "success": True,
                "total_entries": len(leaderboard),
                "top_eas": leaderboard[:args.top]
            }
            print(json.dumps(output, indent=2))
            sys.exit(0)

        if not args.ea_name or not args.metrics:
            print(json.dumps({
                "success": False,
                "error": "Usage: python rank_ea.py <ea_name> --metrics '{...}' [--params '{...}']"
            }))
            sys.exit(1)

        # Parse metrics
        metrics_dict = json.loads(args.metrics)
        metrics = BacktestMetrics(**metrics_dict)

        # Parse params if provided
        params = json.loads(args.params) if args.params else {}

        # Add to ranker
        score = ranker.add_result(
            ea_name=args.ea_name,
            metrics=metrics,
            params=params
        )

        # Get rank
        leaderboard = ranker.get_leaderboard()
        rank = next(
            (i + 1 for i, entry in enumerate(leaderboard) if entry['ea_name'] == args.ea_name),
            None
        )

        output = {
            "success": True,
            "ea_name": args.ea_name,
            "score": score,
            "rank": rank,
            "total_entries": len(leaderboard)
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
