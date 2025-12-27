"""
Simple EA Maker - Configuration
"""
import os
from pathlib import Path
from datetime import datetime

# Project paths
PROJECT_ROOT = Path(__file__).parent
RUNS_DIR = PROJECT_ROOT / "runs"

# MT5 Installation paths
MT5_INSTALL_PATH = Path(r"C:\Users\User\Projects")
MT5_TERMINAL = MT5_INSTALL_PATH / "terminal64.exe"
MT5_EDITOR = MT5_INSTALL_PATH / "MetaEditor64.exe"

# MT5 Data directory (where MQL5 folder lives)
# Note: A42909... is the terminal for C:\Users\User\Projects installation
MT5_DATA_PATH = Path(r"C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\A42909ABCDDDD04324904B57BA9776B8")
MT5_EXPERTS_PATH = MT5_DATA_PATH / "MQL5" / "Experts"
MT5_TESTER_PATH = MT5_DATA_PATH / "Tester"

# Backtest settings
DEFAULT_SYMBOL = "EURUSD"
DEFAULT_TIMEFRAME = "H1"
DEFAULT_DEPOSIT = 3000
DEFAULT_CURRENCY = "GBP"
DEFAULT_LEVERAGE = 100
DEFAULT_LATENCY = 10  # ExecutionMode in ms
DEFAULT_MODEL = 1  # 0=Every tick, 1=1-min OHLC (90%+ accurate for H1), 2=Open price

# Date range: 4 years total (3 years optimization + 1 year forward test)
# Hardcoded: ends today Dec 24, 2025
BACKTEST_FROM = "2021.12.24"
BACKTEST_TO = "2025.12.24"

# Fixer settings
MAX_FIX_RETRIES = 5

# Scoring weights for ranking
SCORING_WEIGHTS = {
    'profit_factor': 20,
    'win_rate': 10,
    'max_drawdown_pct': -2,  # Negative because lower is better
    'recovery_factor': 15,
    'total_trades': 0.1,     # Small bonus for more trades
}

def get_run_dir() -> Path:
    """Create and return a timestamped run directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

def ensure_dirs():
    """Ensure all required directories exist."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
