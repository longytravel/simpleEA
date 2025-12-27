"""
Pre-extract key MQL5 reference sections to text files for quick access.
"""

from pathlib import Path
from mql5_indexer import MQL5Reference

# Key sections needed for EA development
KEY_SECTIONS = [
    # Trading
    ("Trade Functions", 50),
    ("CTrade", 30),
    ("CPositionInfo", 15),
    ("COrderInfo", 15),
    ("CDealInfo", 15),
    ("CSymbolInfo", 20),
    ("CAccountInfo", 10),

    # Timeseries & Indicators
    ("Timeseries and Indicators Access", 50),
    ("CopyRates", 10),
    ("CopyBuffer", 10),
    ("CopyTime", 5),
    ("CopyOpen", 5),
    ("CopyClose", 5),
    ("CopyHigh", 5),
    ("CopyLow", 5),

    # History
    ("HistorySelect", 10),
    ("HistoryOrderGetTicket", 10),
    ("HistoryDealGetTicket", 10),

    # Indicators
    ("Technical Indicators", 100),
    ("iMA", 5),
    ("iRSI", 5),
    ("iMACD", 5),
    ("iBands", 5),
    ("iATR", 5),
    ("iStochastic", 5),

    # Custom Indicators
    ("Custom Indicators", 50),

    # Event Handling
    ("Event Handling", 30),
    ("OnInit", 5),
    ("OnDeinit", 5),
    ("OnTick", 5),
    ("OnTimer", 5),

    # Account & Symbol
    ("Account Information", 20),
    ("SymbolInfoDouble", 10),
    ("SymbolInfoInteger", 10),

    # Arrays & Data
    ("Array Functions", 50),
    ("ArrayCopy", 5),
    ("ArrayResize", 5),
    ("ArraySetAsSeries", 5),

    # Math
    ("Math Functions", 40),
    ("MathAbs", 3),
    ("MathMax", 3),
    ("MathMin", 3),

    # File Operations
    ("File Functions", 50),

    # MQL5 Programs
    ("MQL5 programs", 30),
    ("Program Running", 10),

    # Important structures
    ("MqlRates", 5),
    ("MqlTradeRequest", 10),
    ("MqlTradeResult", 5),
]


def extract_sections():
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)

    ref = MQL5Reference()

    print(f"Extracting {len(KEY_SECTIONS)} key sections...")

    for topic, max_pages in KEY_SECTIONS:
        # Create safe filename
        safe_name = topic.lower().replace(' ', '_').replace('/', '_')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        out_path = cache_dir / f"{safe_name}.txt"

        try:
            content = ref.get_topic(topic, max_pages)
            if "No results found" not in content:
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"  [OK] {topic} -> {out_path.name}")
            else:
                print(f"  [--] {topic} - not found")
        except Exception as e:
            print(f"  [ERR] {topic} - error: {e}")

    ref.close()
    print("\nDone! Key sections cached for quick access.")


if __name__ == "__main__":
    extract_sections()
