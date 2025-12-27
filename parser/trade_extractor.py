"""
Trade Extractor for Monte Carlo Simulation

Extracts individual trade results from MT5 HTML backtest reports.
Each trade is extracted with its profit/loss for shuffling.
"""

import re
import codecs
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional
import json


@dataclass
class Trade:
    """A single completed trade."""
    deal_id: int
    time: str
    symbol: str
    direction: str  # "buy" or "sell"
    volume: float
    entry_price: float
    exit_price: float
    commission: float
    swap: float
    profit: float
    net_profit: float = 0.0
    comment: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeExtractionResult:
    """Result of trade extraction."""
    success: bool
    trades: List[Trade]
    total_profit: float
    total_commission: float
    total_swap: float
    initial_balance: float
    final_balance: float
    total_net_profit: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "trades": [t.to_dict() for t in self.trades],
            "total_profit": self.total_profit,
            "total_commission": self.total_commission,
            "total_swap": self.total_swap,
            "total_net_profit": self.total_net_profit,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "trade_count": len(self.trades),
            "error": self.error
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class TradeExtractor:
    """Extracts individual trades from MT5 HTML reports."""

    def extract(self, report_path: Path) -> TradeExtractionResult:
        """
        Extract trades from an MT5 HTML report.

        Args:
            report_path: Path to the HTML report file

        Returns:
            TradeExtractionResult with list of trades
        """
        if not report_path.exists():
            return TradeExtractionResult(
                success=False,
                trades=[],
                total_profit=0,
                total_commission=0,
                total_swap=0,
                initial_balance=0,
                final_balance=0,
                error=f"Report file not found: {report_path}"
            )

        try:
            content = self._read_report(report_path)
            return self._parse_deals(content)
        except Exception as e:
            return TradeExtractionResult(
                success=False,
                trades=[],
                total_profit=0,
                total_commission=0,
                total_swap=0,
                initial_balance=0,
                final_balance=0,
                error=str(e)
            )

    def _read_report(self, report_path: Path) -> str:
        """Read HTML report, handling various encodings."""
        # MT5 reports are typically UTF-16 encoded
        try:
            with codecs.open(report_path, 'r', 'utf-16', errors='ignore') as f:
                return f.read()
        except:
            with codecs.open(report_path, 'r', 'utf-8', errors='ignore') as f:
                return f.read()

    def _parse_deals(self, content: str) -> TradeExtractionResult:
        """Parse the deals table and extract completed trades."""
        trades: List[Trade] = []
        initial_balance = 0.0
        final_balance = 0.0
        total_commission = 0.0
        total_swap = 0.0
        previous_balance: Optional[float] = None

        # Find all table rows in the deals section
        # Pattern: <tr ...><td>Time</td><td>Deal</td>...
        row_pattern = re.compile(
            r'<tr[^>]*>\s*'
            r'<td[^>]*>([^<]*)</td>\s*'  # Time
            r'<td[^>]*>([^<]*)</td>\s*'  # Deal ID
            r'<td[^>]*>([^<]*)</td>\s*'  # Symbol
            r'<td[^>]*>([^<]*)</td>\s*'  # Type (buy/sell/balance)
            r'<td[^>]*>([^<]*)</td>\s*'  # Direction (in/out)
            r'<td[^>]*>([^<]*)</td>\s*'  # Volume
            r'<td[^>]*>([^<]*)</td>\s*'  # Price
            r'<td[^>]*>([^<]*)</td>\s*'  # Order
            r'<td[^>]*>([^<]*)</td>\s*'  # Commission
            r'<td[^>]*>([^<]*)</td>\s*'  # Swap
            r'<td[^>]*>([^<]*)</td>\s*'  # Profit
            r'<td[^>]*>([^<]*)</td>\s*'  # Balance
            r'<td[^>]*>([^<]*)</td>',    # Comment
            re.IGNORECASE | re.DOTALL
        )

        # Track open deals to match with closes.
        # MT5 "Order" IDs in the Deals table are not stable between entry/exit,
        # so we use (symbol, direction) stacks and infer closes by opposite deal type.
        open_positions: dict[tuple[str, str], list[dict]] = {}

        for match in row_pattern.finditer(content):
            time = match.group(1).strip()
            deal_id = self._parse_int(match.group(2))
            symbol = match.group(3).strip()
            deal_type = match.group(4).strip().lower()
            direction = match.group(5).strip().lower()
            volume = self._parse_float(match.group(6))
            price = self._parse_float(match.group(7))
            order_id = self._parse_int(match.group(8))
            commission = self._parse_float(match.group(9))
            swap = self._parse_float(match.group(10))
            profit = self._parse_float(match.group(11))
            balance = self._parse_float(match.group(12))
            comment = match.group(13).strip()

            balance_before = previous_balance if previous_balance is not None else balance
            if balance > 0:
                if previous_balance is None:
                    previous_balance = balance
                else:
                    balance_before = previous_balance
                    previous_balance = balance

            # Track initial balance (first balance entry)
            if deal_type == "balance" and initial_balance == 0:
                initial_balance = profit  # In balance rows, profit is the deposit

            # Track final balance (last balance value)
            if balance > 0:
                final_balance = balance

            # Skip non-trading rows
            if deal_type not in ("buy", "sell"):
                continue

            # Track totals
            total_commission += commission
            total_swap += swap

            # Track positions
            if direction == "in":
                # Opening a position
                key = (symbol, deal_type)
                open_positions.setdefault(key, []).append(
                    {
                        "deal_id": deal_id,
                        "time": time,
                        "symbol": symbol,
                        "direction": deal_type,
                        "volume": volume,
                        "price": price,
                        "commission": commission,
                        "swap": swap,
                        "balance_before": balance_before,
                    }
                )
            elif direction == "out":
                # Closing a position
                open_dir = "sell" if deal_type == "buy" else "buy"
                key = (symbol, open_dir)
                entry_info = open_positions.get(key, [])
                entry = entry_info.pop() if entry_info else None

                entry_price = entry["price"] if entry else 0.0
                trade_direction = entry["direction"] if entry else open_dir
                entry_commission = entry["commission"] if entry else 0.0
                entry_swap = entry["swap"] if entry else 0.0
                entry_balance_before = entry["balance_before"] if entry else balance_before

                trade = Trade(
                    deal_id=deal_id,
                    time=time,
                    symbol=symbol,
                    direction=trade_direction,
                    volume=volume,
                    entry_price=entry_price,
                    exit_price=price,
                    commission=entry_commission + commission,
                    swap=entry_swap + swap,
                    profit=profit,
                    net_profit=(balance - entry_balance_before) if balance > 0 else (profit + entry_commission + commission + entry_swap + swap),
                    comment=comment
                )
                trades.append(trade)

        total_profit = sum(t.profit for t in trades)
        total_net_profit = sum(t.net_profit for t in trades)

        return TradeExtractionResult(
            success=True,
            trades=trades,
            total_profit=total_profit,
            total_commission=total_commission,
            total_swap=total_swap,
            total_net_profit=total_net_profit,
            initial_balance=initial_balance,
            final_balance=final_balance
        )

    def _parse_float(self, value: str) -> float:
        """Parse a float value, handling MT5 number formats."""
        if not value or not value.strip():
            return 0.0

        # Remove spaces (thousand separators) and common characters
        value = value.strip()
        value = value.replace(' ', '')
        value = value.replace(',', '')

        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parse_int(self, value: str) -> int:
        """Parse an integer value."""
        if not value or not value.strip():
            return 0

        try:
            return int(value.strip())
        except ValueError:
            return 0


def extract_trades(report_path: str) -> TradeExtractionResult:
    """
    Convenience function to extract trades from a report.

    Args:
        report_path: Path to HTML report file

    Returns:
        TradeExtractionResult
    """
    extractor = TradeExtractor()
    return extractor.extract(Path(report_path))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python trade_extractor.py <report.html>")
        print("\nExtracts individual trades from MT5 HTML report for Monte Carlo simulation.")
        sys.exit(1)

    report_path = Path(sys.argv[1])
    result = extract_trades(report_path)

    print(result.to_json())

    if result.success:
        print(f"\n--- Summary ---")
        print(f"Trades extracted: {len(result.trades)}")
        print(f"Total profit: {result.total_profit:.2f}")
        print(f"Total commission: {result.total_commission:.2f}")
        print(f"Total swap: {result.total_swap:.2f}")
        print(f"Initial balance: {result.initial_balance:.2f}")
        print(f"Final balance: {result.final_balance:.2f}")

        if result.trades:
            profits = [t.net_profit for t in result.trades]
            print(f"\nProfit distribution:")
            print(f"  Min: {min(profits):.2f}")
            print(f"  Max: {max(profits):.2f}")
            print(f"  Avg: {sum(profits)/len(profits):.2f}")
