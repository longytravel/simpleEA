"""
Optimization Result Parser

Parses MT5 optimization XML files and finds robust parameters
that are profitable on BOTH in-sample AND forward test periods.
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class OptimizationPass:
    """Results from a single optimization pass."""
    pass_num: int
    profit: float
    profit_factor: float
    recovery_factor: float
    sharpe_ratio: float
    max_dd_pct: float
    trades: int
    parameters: Dict[str, Any]


@dataclass
class RobustResult:
    """Combined in-sample + forward results."""
    pass_num: int

    # In-sample metrics
    in_sample_profit: float
    in_sample_pf: float
    in_sample_dd: float
    in_sample_trades: int

    # Forward metrics
    forward_profit: float
    forward_pf: float
    forward_dd: float
    forward_trades: int

    # Combined metrics
    total_profit: float
    is_robust: bool  # Profitable on BOTH periods

    # Parameters
    parameters: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "pass": self.pass_num,
            "in_sample": {
                "profit": self.in_sample_profit,
                "profit_factor": self.in_sample_pf,
                "max_dd_pct": self.in_sample_dd,
                "trades": self.in_sample_trades
            },
            "forward": {
                "profit": self.forward_profit,
                "profit_factor": self.forward_pf,
                "max_dd_pct": self.forward_dd,
                "trades": self.forward_trades
            },
            "total_profit": self.total_profit,
            "is_robust": self.is_robust,
            "parameters": self.parameters
        }


class OptimizationResultParser:
    """Parses MT5 optimization XML files."""

    # Standard column order in MT5 optimization XML
    COLUMNS = [
        'pass', 'result', 'profit', 'expected_payoff', 'profit_factor',
        'recovery_factor', 'sharpe_ratio', 'custom', 'equity_dd_pct', 'trades'
    ]

    def __init__(self, ea_name: str, terminal_path: Path, symbol: str = None):
        """
        Initialize parser.

        Args:
            ea_name: Name of the EA
            terminal_path: Path to MT5 terminal data folder
            symbol: Optional symbol for symbol-specific XML files
        """
        self.ea_name = ea_name
        self.terminal_path = terminal_path
        self.symbol = symbol

        # Find XML files - use symbol-specific if available
        if symbol:
            symbol_insample = terminal_path / f"{ea_name}_{symbol}_OPT.xml"
            symbol_forward = terminal_path / f"{ea_name}_{symbol}_OPT.forward.xml"

            if symbol_insample.exists():
                self.insample_xml = symbol_insample
                self.forward_xml = symbol_forward
            else:
                # Fall back to generic files
                self.insample_xml = terminal_path / f"{ea_name}_OPT.xml"
                self.forward_xml = terminal_path / f"{ea_name}_OPT.forward.xml"
        else:
            self.insample_xml = terminal_path / f"{ea_name}_OPT.xml"
            self.forward_xml = terminal_path / f"{ea_name}_OPT.forward.xml"

    def parse(self) -> Dict[str, Any]:
        """
        Parse optimization results and find robust parameters.

        Returns:
            Dict with robust results and best parameters
        """
        if not self.insample_xml.exists():
            return {"success": False, "error": f"In-sample XML not found: {self.insample_xml}"}

        if not self.forward_xml.exists():
            return {"success": False, "error": f"Forward XML not found: {self.forward_xml}"}

        # Parse both files
        insample_results = self._parse_xml(self.insample_xml)
        forward_results = self._parse_xml(self.forward_xml)

        # Get parameter names from XML
        param_names = self._extract_param_names(self.insample_xml)

        # Join results by pass number
        robust_results = []

        for pass_num, insample in insample_results.items():
            if pass_num in forward_results:
                forward = forward_results[pass_num]

                total_profit = insample['profit'] + forward['profit']
                is_robust = insample['profit'] > 0 and forward['profit'] > 0

                result = RobustResult(
                    pass_num=pass_num,
                    in_sample_profit=insample['profit'],
                    in_sample_pf=insample['profit_factor'],
                    in_sample_dd=insample['equity_dd_pct'],
                    in_sample_trades=insample['trades'],
                    forward_profit=forward['profit'],
                    forward_pf=forward['profit_factor'],
                    forward_dd=forward['equity_dd_pct'],
                    forward_trades=forward['trades'],
                    total_profit=total_profit,
                    is_robust=is_robust,
                    parameters=insample.get('parameters', {})
                )
                robust_results.append(result)

        # Filter to only robust results (profitable on both periods)
        robust_only = [r for r in robust_results if r.is_robust]

        # Sort by total profit
        robust_only.sort(key=lambda x: x.total_profit, reverse=True)

        # Get best result
        best = robust_only[0] if robust_only else None

        return {
            "success": True,
            "total_passes": len(robust_results),
            "robust_passes": len(robust_only),
            "best": best.to_dict() if best else None,
            "top_5": [r.to_dict() for r in robust_only[:5]],
            "param_names": param_names
        }

    def _parse_xml(self, xml_path: Path) -> Dict[int, Dict]:
        """Parse a single XML file and return results by pass number."""
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract parameter names and column indices from header row
        header_cells = self._extract_header_cells(content)
        col_index = {name: idx for idx, name in enumerate(header_cells)}

        def idx(name: str) -> Optional[int]:
            return col_index.get(name)

        pass_idx = idx("Pass")
        trades_idx = idx("Trades")
        profit_idx = idx("Profit")
        expected_payoff_idx = idx("Expected Payoff")
        profit_factor_idx = idx("Profit Factor")
        recovery_factor_idx = idx("Recovery Factor")
        sharpe_ratio_idx = idx("Sharpe Ratio")
        custom_idx = idx("Custom")
        equity_dd_pct_idx = idx("Equity DD %")

        # "Result" exists in back results; forward results use "Forward Result"/"Back Result"
        result_idx = idx("Result")
        if result_idx is None:
            result_idx = idx("Forward Result")

        back_result_idx = idx("Back Result")

        # Parameters begin after the Trades column (if present)
        param_names: List[str] = []
        if trades_idx is not None:
            param_names = header_cells[trades_idx + 1 :]

        results = {}

        # Find all data rows (skip header row)
        row_pattern = r'<Row>(.*?)</Row>'
        rows = re.findall(row_pattern, content, re.DOTALL)

        for row in rows[1:]:  # Skip header
            # Extract all cell values
            cells = re.findall(r'<Data ss:Type="(?:Number|String)">(.*?)</Data>', row)

            if not cells:
                continue

            try:
                if pass_idx is None or pass_idx >= len(cells):
                    continue

                pass_num = int(float(cells[pass_idx]))

                def get_float(i: Optional[int]) -> float:
                    if i is None or i >= len(cells) or cells[i] == "":
                        return 0.0
                    return float(cells[i])

                def get_int(i: Optional[int]) -> int:
                    if i is None or i >= len(cells) or cells[i] == "":
                        return 0
                    return int(float(cells[i]))

                result = {
                    'pass': pass_num,
                    'result': get_float(result_idx),
                    'profit': get_float(profit_idx),
                    'expected_payoff': get_float(expected_payoff_idx),
                    'profit_factor': get_float(profit_factor_idx),
                    'recovery_factor': get_float(recovery_factor_idx),
                    'sharpe_ratio': get_float(sharpe_ratio_idx),
                    'custom': get_float(custom_idx),
                    'equity_dd_pct': get_float(equity_dd_pct_idx),
                    'trades': get_int(trades_idx),
                }

                if back_result_idx is not None:
                    result["back_result"] = get_float(back_result_idx)

                # Extract parameters (cells after standard metrics)
                if param_names:
                    params = {}
                    for i, name in enumerate(param_names):
                        param_cell_idx = (trades_idx + 1 + i) if trades_idx is not None else None
                        if param_cell_idx is None or param_cell_idx >= len(cells):
                            continue

                        val = cells[param_cell_idx]
                        # Try to convert to number
                        try:
                            if '.' in val:
                                params[name] = float(val)
                            else:
                                params[name] = int(val)
                        except:
                            params[name] = val
                    result['parameters'] = params

                results[pass_num] = result

            except (ValueError, IndexError) as e:
                continue

        return results

    def _extract_param_names(self, xml_path: Path) -> List[str]:
        """Extract parameter names from XML header row."""
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        header_cells = self._extract_header_cells(content)
        if not header_cells:
            return []

        try:
            trades_idx = next(i for i, name in enumerate(header_cells) if name.strip().lower() == "trades")
        except StopIteration:
            return []

        return header_cells[trades_idx + 1 :]

    def _extract_header_cells(self, content: str) -> List[str]:
        """Extract header cell names from the first <Row> in an optimization XML."""
        header_match = re.search(r'<Row>(.*?)</Row>', content, re.DOTALL)
        if not header_match:
            return []

        header = header_match.group(1)
        return [c.strip() for c in re.findall(r'<Data ss:Type="String">(.*?)</Data>', header)]


def find_robust_parameters(ea_name: str, terminal_path: str = None, symbol: str = None) -> dict:
    """
    Convenience function to find robust optimization parameters.

    Args:
        ea_name: Name of the EA
        terminal_path: Optional path to terminal data folder
        symbol: Optional symbol for symbol-specific results

    Returns:
        Dict with best robust parameters
    """
    if terminal_path is None:
        # Default MT5 data path
        terminal_path = Path(r"C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\A42909ABCDDDD04324904B57BA9776B8")
    else:
        terminal_path = Path(terminal_path)

    parser = OptimizationResultParser(ea_name, terminal_path, symbol=symbol)
    return parser.parse()


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Parse optimization results")
    parser.add_argument("ea_name", help="Name of the EA")
    parser.add_argument("--symbol", "-s", help="Symbol for symbol-specific results")

    args = parser.parse_args()

    result = find_robust_parameters(args.ea_name, symbol=args.symbol)

    print(json.dumps(result, indent=2))

    if result["success"] and result["best"]:
        symbol_str = f" ({args.symbol})" if args.symbol else ""
        print(f"\n--- Robust Parameters Found{symbol_str} ---")
        print(f"Total passes analyzed: {result['total_passes']}")
        print(f"Robust passes (profitable on both periods): {result['robust_passes']}")

        best = result["best"]
        print(f"\nBest Result (Pass {best['pass']}):")
        print(f"  In-sample: Profit={best['in_sample']['profit']:.2f}, PF={best['in_sample']['profit_factor']:.2f}")
        print(f"  Forward:   Profit={best['forward']['profit']:.2f}, PF={best['forward']['profit_factor']:.2f}")
        print(f"  TOTAL:     Profit={best['total_profit']:.2f}")

        print(f"\nParameters:")
        for name, value in best['parameters'].items():
            print(f"  {name}={value}")
    else:
        print(f"\nNo robust parameters found!")
        if "error" in result:
            print(f"Error: {result['error']}")
