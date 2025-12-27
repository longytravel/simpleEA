# MQL5 Error Patterns & Fixes

Quick reference for common compilation errors and their fixes.

## Syntax Errors

### Error 127: ';' - semicolon expected
**Pattern:** Statement missing semicolon
```cpp
// WRONG
int x = 5
int y = 10;

// FIX
int x = 5;
int y = 10;
```

### Error 117: constant cannot be modified
**Pattern:** Trying to modify an input variable
```cpp
// WRONG
input double LotSize = 0.1;
void OnTick() {
    LotSize = 0.2;  // Error!
}

// FIX
input double LotSize = 0.1;
void OnTick() {
    double currentLot = LotSize;
    currentLot = 0.2;  // OK
}
```

### Error 150: 'return' - 'void' function returns a value
**Pattern:** Returning value from void function
```cpp
// WRONG
void DoSomething() {
    return true;  // Error!
}

// FIX (change return type)
bool DoSomething() {
    return true;
}
// OR (remove return value)
void DoSomething() {
    return;
}
```

## Identifier Errors

### Error 328: 'X' - undeclared identifier
**Pattern:** Variable or function not declared

**Common cases:**
1. **Typo:** Check spelling
2. **Missing include:** Add `#include <...>`
3. **Wrong scope:** Declare in correct scope
4. **MT4 identifier:** See mt4-to-mt5.md

### Error 327: 'X' - identifier already defined
**Pattern:** Duplicate declaration
```cpp
// WRONG
int value = 10;
int value = 20;  // Error!

// FIX
int value = 10;
value = 20;  // Assignment, not declaration
```

## Type Errors

### Warning 222: implicit conversion
**Pattern:** Losing precision in conversion
```cpp
// WARNING
int x = 1.5 * 100;  // double to int

// FIX
int x = (int)(1.5 * 100);  // Explicit cast
```

### Error 228: 'X' - cannot be applied to object
**Pattern:** Wrong operator for type
```cpp
// WRONG
string s = "hello";
int len = s.Length();  // string has no Length method

// FIX
string s = "hello";
int len = StringLen(s);  // Use function
```

### Error 284: ambiguous call to overloaded function
**Pattern:** Compiler can't decide which overload
```cpp
// WRONG
Print(NULL);  // Which Print?

// FIX
Print((string)NULL);  // Explicit type
```

## Function Errors

### Error 330: 'X' - wrong parameters count
**Pattern:** Too few or too many arguments

**Lookup the function:**
```bash
python reference/mql5_indexer.py get "FunctionName"
```

### Error 131: 'X' - undeclared identifier (for function)
**Pattern:** Function not defined
- Check if it's an MT4 function (see mt4-to-mt5.md)
- Check if it needs an include file
- Check spelling

### Error 144: 'X' - function not defined
**Pattern:** Function declared but not implemented
```cpp
// WRONG
void MyFunc();  // Declaration only

// FIX
void MyFunc() {
    // Implementation
}
```

## Trade Errors

### Error 330: 'OrderSend' - wrong parameters count
**Pattern:** MT4-style OrderSend

See mt4-to-mt5.md for full conversion.

**Quick fix:**
```cpp
#include <Trade\Trade.mqh>
CTrade trade;
trade.Buy(0.1, _Symbol, 0, sl, tp);
```

### Error 328: 'OP_BUY' - undeclared identifier
**Pattern:** MT4 order type constant

| MT4 | MQL5 |
|-----|------|
| OP_BUY | ORDER_TYPE_BUY |
| OP_SELL | ORDER_TYPE_SELL |
| OP_BUYLIMIT | ORDER_TYPE_BUY_LIMIT |
| OP_SELLLIMIT | ORDER_TYPE_SELL_LIMIT |
| OP_BUYSTOP | ORDER_TYPE_BUY_STOP |
| OP_SELLSTOP | ORDER_TYPE_SELL_STOP |

### Error 328: 'Ask' or 'Bid' - undeclared identifier
**Pattern:** MT4 price access

```cpp
// MT4 (WRONG)
double ask = Ask;
double bid = Bid;

// MQL5 (FIX)
double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
```

## Indicator Errors

### Error 330: 'iMA' - wrong parameters count
**Pattern:** MT4-style indicator call

MT4 iMA has 8 params, MQL5 iMA has 6 params and returns a handle.

See mt4-to-mt5.md for full conversion.

### Error 303: access to invalid array element
**Pattern:** Array index out of bounds
```cpp
// WRONG
double buffer[10];
double val = buffer[10];  // Index 10 doesn't exist (0-9)

// FIX
double val = buffer[9];  // Last element is index 9
```

### Error 307: ArraySetAsSeries not applied
**Pattern:** Indicator buffer not set as series
```cpp
// WRONG
double buffer[];
CopyBuffer(handle, 0, 0, 10, buffer);
double current = buffer[0];  // May not be current bar!

// FIX
double buffer[];
ArraySetAsSeries(buffer, true);  // Add this!
CopyBuffer(handle, 0, 0, 10, buffer);
double current = buffer[0];  // Now index 0 is current bar
```

## Include/Library Errors

### Error 300: file not found
**Pattern:** Include file doesn't exist
```cpp
// Check path is correct
#include <Trade\Trade.mqh>     // Standard library
#include "MyFile.mqh"          // Local file
```

### Error 156: array passed by reference only
**Pattern:** Array must be passed by reference
```cpp
// WRONG
void Process(double arr[]) { }

// FIX
void Process(double &arr[]) { }  // Add &
```

## Lookup Commands

When you encounter an unfamiliar error:

```bash
# Search for function documentation
python C:\Users\User\Projects\simpleEA\reference\mql5_indexer.py search "FunctionName"

# Get full documentation
python C:\Users\User\Projects\simpleEA\reference\mql5_indexer.py get "FunctionName"

# Check cached docs (fastest)
cat C:\Users\User\Projects\simpleEA\reference\cache\trade_functions.txt
cat C:\Users\User\Projects\simpleEA\reference\cache\ctrade.txt
```
