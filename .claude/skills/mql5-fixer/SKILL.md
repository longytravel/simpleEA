---
name: mql5-fixer
description: Fix MQL5 compilation errors using the 7000-page official reference. Analyzes error messages, looks up correct function signatures, and applies targeted fixes.
---

# MQL5 Compilation Error Fixer

Fixes MQL5 code that fails to compile by analyzing errors against official documentation.

## When to Use

Use this skill when:
- MetaEditor compilation fails
- Code has syntax or API errors
- MT4 code needs conversion to MQL5

## Process

1. **Read** the source code and compilation errors
2. **Check patterns.md** for known error patterns
3. **Check mt4-to-mt5.md** if MT4 patterns detected
4. **Lookup** correct signatures using reference:
   ```bash
   python reference/mql5_indexer.py search "function_name"
   python reference/mql5_indexer.py get "CTrade"
   cat reference/cache/ctrade.txt  # Fastest for common topics
   ```
5. **Apply** minimal, targeted fixes using Edit tool
6. **Verify** by recompiling:
   ```bash
   python scripts/compile_ea.py "path/to/file.mq5"
   ```

## Supporting Files

- `patterns.md` - Common error patterns and quick fixes
- `mt4-to-mt5.md` - MT4 to MQL5 migration patterns
- `examples.md` - Real examples of error fixes

## Cached Reference Topics (48 files)

Located in `reference/cache/`:
- Trading: `ctrade.txt`, `trade_functions.txt`, `mqltraderequest.txt`
- Indicators: `ima.txt`, `irsi.txt`, `imacd.txt`, `ibands.txt`, `iatr.txt`
- Data: `copybuffer.txt`, `copyrates.txt`, `csymbolinfo.txt`
- Events: `oninit.txt`, `ondeinit.txt`, `ontick.txt`

## Common Error Fixes

### Missing Semicolon
```
error: ';' - semicolon expected
```
Fix: Add `;` at end of statement.

### Undeclared Identifier
```
error: 'name' - undeclared identifier
```
Fix: Check spelling, add `#include`, or declare variable.

### Wrong Parameters Count
```
error: 'FunctionName' - wrong parameters count
```
Fix: Look up function in reference, match parameter count and types.

### MT4 to MT5 Migration

**OrderSend (MT4 → MT5):**
```cpp
// MT4 (wrong)
int ticket = OrderSend(Symbol(), OP_BUY, 0.1, Ask, 3, 0, 0);

// MT5 (correct)
MqlTradeRequest request = {};
MqlTradeResult result = {};
request.action = TRADE_ACTION_DEAL;
request.symbol = _Symbol;
request.volume = 0.1;
request.type = ORDER_TYPE_BUY;
request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
OrderSend(request, result);
```

**Indicator Handles (MT4 → MT5):**
```cpp
// MT4 (wrong)
double ma = iMA(Symbol(), PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE, 0);

// MT5 (correct)
int maHandle = iMA(_Symbol, PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE);
double maBuffer[];
ArraySetAsSeries(maBuffer, true);
CopyBuffer(maHandle, 0, 0, 1, maBuffer);
double ma = maBuffer[0];
```

## Fix Rules

**DO:**
- Fix only compilation errors
- Preserve original code style
- Make minimal changes
- Consult reference docs BEFORE fixing

**DO NOT:**
- Change trading logic
- Refactor working code
- Add features
- Guess function signatures

## Max Attempts

From `settings.py`: `fixer.max_attempts = 5`

After 5 failed attempts, report to user that manual intervention is needed.
