---
name: parameter-optimizer
description: Extracts EA input parameters and creates optimization INI files with intelligent ranges. Handles cloud agent configuration and forward test setup.
---

# Parameter Optimizer Skill

Creates optimization configurations by analyzing EA source code and generating intelligent parameter ranges.

## When to Use

Claude uses this skill when:
- Setting up optimization for an EA
- User wants to optimize an EA's parameters
- Creating INI files for MT5 Strategy Tester optimization

## Process

### Step 1: Extract Parameters

Use the parameter extractor to read the EA source:
```bash
python optimizer/param_extractor.py "path/to/EA.mq5"
```

This returns JSON with all input parameters:
```json
{
  "parameters": [
    {"name": "LookbackPeriod", "type": "int", "default": 20},
    {"name": "RiskPercent", "type": "double", "default": 1.0},
    {"name": "UseFilter", "type": "bool", "default": true}
  ]
}
```

### Step 2: Generate Intelligent Ranges

For each parameter, expand the default value by ~50% in each direction:

| Type | Default | Generated Range |
|------|---------|-----------------|
| int (period) | 20 | 10 → 30, step 5 |
| double (multiplier) | 1.5 | 0.75 → 2.25, step 0.25 |
| int (points) | 50 | 25 → 75, step 10 |

**Skip optimization for:**
- `LotSize`, `Lots` - Risk management, keep fixed
- `MagicNumber`, `Magic` - Identifier, keep fixed
- `Slippage` - Execution setting, keep fixed
- Any parameter with "Comment" in name

**Range expansion rules:**
- **Periods (int)**: ±50%, step = default/4, min step 1
- **Multipliers (double)**: ±50%, step = 0.25 or default/4
- **Points/Pips (int/double)**: ±50%, step = 10 or default/5
- **Booleans**: Test both true and false

### Step 3: Create Optimization INI

Use the INI builder:
```bash
python optimizer/ini_builder.py \
  --ea "Auction_Theory_Safe" \
  --params "extracted_params.json" \
  --cloud on \
  --output "optimization.ini"
```

**Fixed settings (from your setup):**
- Model: 1 (1-minute OHLC)
- Latency: 10ms
- Deposit: £3,000
- Leverage: 1:100
- Optimization: Genetic (type 2)
- Date range: 2021.12.24 → 2025.12.24
- Forward split: 3 years in-sample, 1 year forward (from 2024.12.24)

**Agent settings:**
```ini
UseLocal=1
UseRemote=0
UseCloud=1   # or 0 if --cloud off
```

### Step 4: Return Configuration

Output the INI file path and a summary:
```
Optimization INI created: runs/20251226/Auction_Theory_Safe_OPT.ini

Parameters to optimize:
  LookbackPeriod: 10 → 30 (step 5) [9 combinations]
  ATRMultiplier: 0.75 → 2.25 (step 0.25) [7 combinations]

Fixed parameters:
  LotSize: 0.01
  MagicNumber: 123456

Estimated combinations: 63 (genetic will sample subset)
Cloud agents: ENABLED
Forward test: 2024.12.24 → 2025.12.24
```

## Example: Auction_Theory_Safe

If the EA has:
```cpp
input int      AuctionLookback = 20;
input double   ATRMultiplier = 1.5;
input int      StopLossPips = 50;
input double   LotSize = 0.01;
input int      MagicNumber = 123456;
```

Generated ranges:
```ini
[TesterInputs]
AuctionLookback=20||10||5||30||Y
ATRMultiplier=1.5||0.75||0.25||2.25||Y
StopLossPips=50||25||10||75||Y
LotSize=0.01||0||0||0||N
MagicNumber=123456||0||0||0||N
```

## Cloud Agent Control

The skill controls cloud agents via INI:
- `UseCloud=1` - Enable MQL5 Cloud Network (costs money, faster)
- `UseCloud=0` - Disable (free, uses only local cores)

**IMPORTANT**: The INI setting only works if cloud agents are already enabled in MT5:
1. First time setup: Open Strategy Tester → Agents tab → Right-click → **Enable** MQL5 Cloud Network
2. Ensure MQL5.community account is configured in Tools → Options → MQL5.community tab
3. After initial setup, the INI `UseCloud=1/0` will toggle cloud agents on/off

This is a MetaQuotes security restriction - automated cloud connection requires prior manual authorization.

Default: **ON** for daytime use, suggest **OFF** for overnight runs.

## Integration

After creating the INI, the stress-test pipeline:
1. Runs optimization with the INI
2. Parses results to find best parameters
3. Runs forward test with best parameters
4. Continues to Monte Carlo and multi-pair testing

Sources:
- [MetaTrader 5 Platform Start - INI Configuration](https://www.metatrader5.com/en/terminal/help/start_advanced/start)
- [MQL5 Cloud Network Usage](https://www.metatrader5.com/en/terminal/help/mql5cloud/mql5cloud_use)
