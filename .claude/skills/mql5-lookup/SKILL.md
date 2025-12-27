---
name: mql5-lookup
description: Look up MQL5 documentation from the 7000-page official reference. Use when you need function signatures, parameter details, return types, or usage examples for any MQL5 function, class, or structure. Essential for fixing compilation errors.
---

# MQL5 Documentation Lookup

Access the complete 7000-page MQL5 reference documentation indexed for fast lookup.

## How to Use

The reference system is available via Python scripts in the `reference/` directory.

### Quick Lookup Commands

```bash
# Search for topics
python reference/mql5_indexer.py search "OrderSend"

# Get full documentation for a topic
python reference/mql5_indexer.py get "CTrade"

# List major sections
python reference/mql5_indexer.py sections
```

### Python API

```python
from reference.lookup import mql5_lookup, mql5_search, quick_lookup

# Search for matching topics
results = mql5_search("order send", max_results=5)

# Get full documentation
docs = mql5_lookup("OrderSend")

# Quick shortcuts for common topics
trade_docs = quick_lookup("trade")    # Trade Functions
ctrade_docs = quick_lookup("ctrade")  # CTrade class
```

## Pre-Cached Topics

These commonly needed sections are pre-extracted in `reference/cache/`:

### Trading
- `trade_functions.txt` - Core trading functions
- `ctrade.txt` - CTrade wrapper class
- `cpositioninfo.txt` - Position management
- `corderinfo.txt` - Order information
- `mqltraderequest.txt` - Trade request structure
- `mqltraderesult.txt` - Trade result structure

### Market Data
- `copyrates.txt` - Price data access
- `copybuffer.txt` - Indicator buffer access
- `timeseries_and_indicators_access.txt` - Full timeseries docs

### Indicators
- `ima.txt` - Moving Average
- `irsi.txt` - RSI
- `imacd.txt` - MACD
- `ibands.txt` - Bollinger Bands
- `iatr.txt` - ATR
- `istochastic.txt` - Stochastic

### Events
- `oninit.txt` - Initialization
- `ondeinit.txt` - Deinitialization
- `ontick.txt` - Tick handling
- `ontimer.txt` - Timer events

### Utilities
- `array_functions.txt` - Array operations
- `math_functions.txt` - Math functions
- `account_information.txt` - Account data

## Usage in Code Fixing

When fixing compilation errors:

1. **Identify the problematic function/type** from the error message
2. **Search the reference**: `mql5_search("function_name")`
3. **Extract documentation**: `mql5_lookup("function_name")`
4. **Apply correct signature** based on official docs

### Example: Fixing OrderSend Error

```
Error: 'OrderSend' - wrong parameters count
```

Lookup response shows OrderSend requires:
- `MqlTradeRequest& request` - trade request structure
- `MqlTradeResult& result` - trade result structure

The old MT4-style `OrderSend(symbol, cmd, volume, price, slippage, sl, tp)` is obsolete.

## Index Statistics

- **Total Pages**: 7,040
- **Indexed Entries**: 4,028
- **Searchable Keywords**: 3,057
- **Pre-cached Sections**: 48
