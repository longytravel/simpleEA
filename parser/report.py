"""
MT5 Report Parser
Extracts key metrics from HTML/XML backtest reports.
"""
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from html.parser import HTMLParser


@dataclass
class BacktestMetrics:
    """Key metrics extracted from a backtest report."""
    # Profitability
    total_net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0

    # Drawdown
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    # Trades
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # Tester data quality / volume
    history_quality: float = 0.0
    bars: int = 0
    ticks: int = 0

    # Quality metrics
    expected_payoff: float = 0.0
    sharpe_ratio: float = 0.0
    recovery_factor: float = 0.0

    # Additional info
    initial_deposit: float = 10000.0
    final_balance: float = 0.0
    roi_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class MT5ReportParser(HTMLParser):
    """Parser for MT5 HTML backtest reports."""

    def __init__(self):
        super().__init__()
        self.current_tag = None
        self.current_data = []
        self.in_table = False
        self.table_data = []
        self.current_row = []

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag == 'table':
            self.in_table = True
        elif tag == 'tr':
            self.current_row = []

    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
        elif tag == 'tr' and self.current_row:
            self.table_data.append(self.current_row)
            self.current_row = []
        self.current_tag = None

    def handle_data(self, data):
        data = data.strip()
        if data and self.in_table:
            self.current_row.append(data)


class ReportParser:
    """Parses MT5 backtest reports and extracts metrics."""

    def parse(self, report_path: Path) -> Optional[BacktestMetrics]:
        """
        Parse a backtest report file.

        Args:
            report_path: Path to the HTML or XML report

        Returns:
            BacktestMetrics or None if parsing fails
        """
        if not report_path.exists():
            return None

        suffix = report_path.suffix.lower()

        try:
            if suffix == '.html' or suffix == '.htm':
                return self._parse_html(report_path)
            elif suffix == '.xml':
                return self._parse_xml(report_path)
            else:
                # Try HTML parsing as default
                return self._parse_html(report_path)
        except Exception as e:
            print(f"Error parsing report: {e}")
            return None

    def _parse_html(self, report_path: Path) -> BacktestMetrics:
        """Parse an HTML report file."""
        # MT5 reports are often in UTF-16 encoding
        try:
            with open(report_path, 'r', encoding='utf-16', errors='ignore') as f:
                content = f.read()
        except:
            with open(report_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        metrics = BacktestMetrics()

        # Extract values using regex patterns
        # MT5 reports format: <td>Label:</td><td><b>value</b></td>
        # Values may contain spaces as thousand separators

        # MT5 HTML format: <td ...>Label:</td>\n<td ...><b>value</b></td>
        # Patterns need to handle various TD attributes like nowrap, colspan, etc.
        patterns = {
            'total_net_profit': r'Total Net Profit[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'gross_profit': r'Gross Profit[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'gross_loss': r'Gross Loss[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'profit_factor': r'Profit Factor[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'max_drawdown': r'(?:Balance|Equity) Drawdown Maximal[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'total_trades': r'Total Trades[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'expected_payoff': r'Expected Payoff[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'sharpe_ratio': r'Sharpe Ratio[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'recovery_factor': r'Recovery Factor[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'initial_deposit': r'Initial [Dd]eposit[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'winning_trades': r'Profit Trades[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            'losing_trades': r'Loss Trades[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                value_str = match.group(1).strip()
                value = self._extract_number(value_str)
                if value is not None:
                    setattr(metrics, field, value)

        # History quality / bars / ticks (MT5 report "Results" header)
        hq_match = re.search(
            r'History Quality[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>',
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if hq_match:
            hq = self._extract_number(hq_match.group(1).strip())
            if hq is not None:
                metrics.history_quality = float(hq)

        bars_match = re.search(r'Bars[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE | re.DOTALL)
        if bars_match:
            bars_val = self._extract_number(bars_match.group(1).strip())
            if bars_val is not None:
                metrics.bars = int(bars_val)

        ticks_match = re.search(r'Ticks[^<]*</td>\s*<td[^>]*><b>([^<]+)</b>', content, re.IGNORECASE | re.DOTALL)
        if ticks_match:
            ticks_val = self._extract_number(ticks_match.group(1).strip())
            if ticks_val is not None:
                metrics.ticks = int(ticks_val)

        # Calculate derived metrics
        if metrics.total_trades > 0:
            metrics.win_rate = (metrics.winning_trades / metrics.total_trades) * 100

        if metrics.max_drawdown != 0:
            metrics.recovery_factor = abs(metrics.total_net_profit / metrics.max_drawdown) if metrics.max_drawdown else 0

        # Extract drawdown percentage from "Balance Drawdown Relative:" field
        # Format: <td>Balance Drawdown Relative:</td><td><b>132.10% (7 455.84)</b></td>
        dd_pct_match = re.search(
            r'Balance Drawdown Relative[^<]*</td>\s*<td[^>]*><b>(\d+\.?\d*)%',
            content, re.IGNORECASE | re.DOTALL
        )
        if dd_pct_match:
            metrics.max_drawdown_pct = float(dd_pct_match.group(1))

        # ROI (net profit / initial deposit)
        if metrics.initial_deposit and metrics.initial_deposit > 0:
            metrics.roi_pct = (metrics.total_net_profit / metrics.initial_deposit) * 100.0

        return metrics

    def _parse_xml(self, report_path: Path) -> BacktestMetrics:
        """Parse an XML report file."""
        import xml.etree.ElementTree as ET

        tree = ET.parse(report_path)
        root = tree.getroot()

        metrics = BacktestMetrics()

        # XML structure varies, try common paths
        for elem in root.iter():
            tag = elem.tag.lower()
            text = elem.text

            if text is None:
                continue

            value = self._extract_number(text)
            if value is None:
                continue

            if 'profit' in tag and 'net' in tag:
                metrics.total_net_profit = value
            elif 'profit' in tag and 'gross' in tag:
                metrics.gross_profit = value
            elif 'loss' in tag and 'gross' in tag:
                metrics.gross_loss = value
            elif 'profitfactor' in tag or 'profit_factor' in tag:
                metrics.profit_factor = value
            elif 'drawdown' in tag and 'max' in tag:
                metrics.max_drawdown = value
            elif 'trades' in tag and 'total' in tag:
                metrics.total_trades = int(value)
            elif 'sharpe' in tag:
                metrics.sharpe_ratio = value

        return metrics

    def _extract_number(self, value_str: str) -> Optional[float]:
        """Extract a numeric value from a string."""
        if not value_str:
            return None

        # Handle formats like "122 (38.01%)" - extract just the first number
        # Also handles "7 455.84 (132.10%)"
        # First, remove any trailing parenthetical content
        if '(' in value_str:
            value_str = value_str.split('(')[0].strip()

        # Remove currency symbols and percentage signs, but keep decimal points
        # MT5 uses spaces as thousand separators (e.g., "5 257.50")
        value_str = re.sub(r'[$€£¥%,]', '', value_str)
        # Remove spaces (thousand separators)
        value_str = value_str.replace(' ', '')

        # Handle parentheses for negative numbers (already stripped if it was trailing)
        if value_str.startswith('(') and value_str.endswith(')'):
            value_str = '-' + value_str[1:-1]

        try:
            return float(value_str)
        except ValueError:
            return None


if __name__ == "__main__":
    # Test the parser
    parser = ReportParser()

    # Look for a sample report
    from pathlib import Path
    sample_reports = list(Path(r"C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\010E047102812FC0C18890992854220E").rglob("*.html"))

    if sample_reports:
        print(f"Found {len(sample_reports)} report files")
        report = sample_reports[0]
        print(f"Parsing: {report}")
        metrics = parser.parse(report)
        if metrics:
            print("\nExtracted metrics:")
            for key, value in metrics.to_dict().items():
                print(f"  {key}: {value}")
    else:
        print("No sample reports found")
