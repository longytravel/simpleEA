# MQL5 Fixer Examples

Real examples of compilation errors and their fixes.

---

## Example 1: Missing Semicolon

### Input
```
Source file: MA_Simple.mq5

int OnInit()
{
    int x = 5
    int y = 10;
    return INIT_SUCCEEDED;
}
```

Errors:
```
MA_Simple.mq5(4,14): error 127: ';' - semicolon expected
```

### Output
```json
{
  "success": true,
  "fixed_code": "int OnInit()\n{\n    int x = 5;\n    int y = 10;\n    return INIT_SUCCEEDED;\n}\n",
  "fixes_applied": [
    {
      "line": 4,
      "error": "';' - semicolon expected",
      "fix": "Added missing semicolon after 'int x = 5'",
      "reference": "MQL5 syntax"
    }
  ],
  "unfixable_errors": []
}
```

---

## Example 2: Wrong OrderSend Parameters (MT4 to MT5)

### Input
```
Source file: OldStyle_EA.mq5

void OpenBuy()
{
    int ticket = OrderSend(Symbol(), OP_BUY, 0.1, Ask, 3, 0, 0, "Buy", 12345);
}
```

Errors:
```
OldStyle_EA.mq5(4,18): error 330: 'OrderSend' - wrong parameters count
OldStyle_EA.mq5(4,39): error 328: 'OP_BUY' - undeclared identifier
OldStyle_EA.mq5(4,52): error 328: 'Ask' - undeclared identifier
```

### Output
```json
{
  "success": true,
  "fixed_code": "void OpenBuy()\n{\n    MqlTradeRequest request = {};\n    MqlTradeResult result = {};\n    \n    request.action = TRADE_ACTION_DEAL;\n    request.symbol = _Symbol;\n    request.volume = 0.1;\n    request.type = ORDER_TYPE_BUY;\n    request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);\n    request.deviation = 3;\n    request.magic = 12345;\n    request.comment = \"Buy\";\n    \n    if(!OrderSend(request, result))\n    {\n        Print(\"OrderSend error: \", GetLastError());\n    }\n}\n",
  "fixes_applied": [
    {
      "line": 4,
      "error": "'OrderSend' - wrong parameters count",
      "fix": "Converted MT4-style OrderSend to MT5 MqlTradeRequest/Result pattern",
      "reference": "Trade Functions > OrderSend"
    },
    {
      "line": 4,
      "error": "'OP_BUY' - undeclared identifier",
      "fix": "Replaced OP_BUY with ORDER_TYPE_BUY enum",
      "reference": "Trade Constants > ENUM_ORDER_TYPE"
    },
    {
      "line": 4,
      "error": "'Ask' - undeclared identifier",
      "fix": "Replaced Ask with SymbolInfoDouble(_Symbol, SYMBOL_ASK)",
      "reference": "Market Info > SymbolInfoDouble"
    }
  ],
  "unfixable_errors": []
}
```

---

## Example 3: Indicator Handle Pattern

### Input
```
Source file: MA_Crossover.mq5

double GetMA(int period, int shift)
{
    return iMA(Symbol(), PERIOD_H1, period, 0, MODE_SMA, PRICE_CLOSE, shift);
}
```

Errors:
```
MA_Crossover.mq5(3,12): error 330: 'iMA' - wrong parameters count
```

### Output
```json
{
  "success": true,
  "fixed_code": "int g_maHandle = INVALID_HANDLE;\ndouble g_maBuffer[];\n\nint OnInit()\n{\n    g_maHandle = iMA(_Symbol, PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE);\n    if(g_maHandle == INVALID_HANDLE)\n        return INIT_FAILED;\n    ArraySetAsSeries(g_maBuffer, true);\n    return INIT_SUCCEEDED;\n}\n\nvoid OnDeinit(const int reason)\n{\n    if(g_maHandle != INVALID_HANDLE)\n        IndicatorRelease(g_maHandle);\n}\n\ndouble GetMA(int period, int shift)\n{\n    // Note: This now uses the global handle. For dynamic periods,\n    // you would need to create handles per period.\n    if(CopyBuffer(g_maHandle, 0, shift, 1, g_maBuffer) < 1)\n        return 0.0;\n    return g_maBuffer[0];\n}\n",
  "fixes_applied": [
    {
      "line": 3,
      "error": "'iMA' - wrong parameters count",
      "fix": "Converted to MT5 indicator handle pattern: iMA returns handle, CopyBuffer retrieves values",
      "reference": "Technical Indicators > iMA"
    }
  ],
  "unfixable_errors": []
}
```

---

## Example 4: Type Conversion

### Input
```
Source file: Calculate.mq5

void Calculate()
{
    double price = 1.23456;
    int pips = price * 10000;
    Print("Pips: ", pips);
}
```

Errors:
```
Calculate.mq5(4,16): warning 222: 'price * 10000' - implicit conversion from 'double' to 'int'
```

### Output
```json
{
  "success": true,
  "fixed_code": "void Calculate()\n{\n    double price = 1.23456;\n    int pips = (int)(price * 10000);\n    Print(\"Pips: \", pips);\n}\n",
  "fixes_applied": [
    {
      "line": 4,
      "error": "implicit conversion from 'double' to 'int'",
      "fix": "Added explicit (int) cast to silence warning and make intent clear",
      "reference": "Data Types > Type Casting"
    }
  ],
  "unfixable_errors": []
}
```

---

## Example 5: Unfixable Error

### Input
```
Source file: CustomLogic.mq5

void OnTick()
{
    double result = MyCustomFunction(1, 2, 3);
    Print(result);
}
```

Errors:
```
CustomLogic.mq5(3,21): error 328: 'MyCustomFunction' - undeclared identifier
```

### Output
```json
{
  "success": false,
  "fixed_code": null,
  "fixes_applied": [],
  "unfixable_errors": [
    {
      "line": 3,
      "error": "'MyCustomFunction' - undeclared identifier",
      "reason": "Custom function 'MyCustomFunction' is not defined anywhere in the file and is not a standard MQL5 function. This requires human intervention to either define the function or provide the correct function name."
    }
  ]
}
```

---

## Example 6: Multiple Errors in One File

### Input
```
Source file: MultiError.mq5

input double LotSize = 0.1;

void OnTick()
{
    if(CheckSignal())
    {
        LotSize = 0.2;  // Error: can't modify input
        int ticket = OrderSend(Symbol(), OP_BUY, LotSize, Ask, 3, 0, 0)
    }
}

bool CheckSignal()
{
    double ma = iMA(Symbol(), 0, 14, 0, MODE_SMA, PRICE_CLOSE, 0);
    return ma > 0;
}
```

Errors:
```
MultiError.mq5(7,9): error 117: 'LotSize' - constant cannot be modified
MultiError.mq5(8,18): error 330: 'OrderSend' - wrong parameters count
MultiError.mq5(8,39): error 328: 'OP_BUY' - undeclared identifier
MultiError.mq5(8,81): error 127: ';' - semicolon expected
MultiError.mq5(15,16): error 330: 'iMA' - wrong parameters count
```

### Output
```json
{
  "success": true,
  "fixed_code": "input double LotSize = 0.1;\n\nint g_maHandle = INVALID_HANDLE;\ndouble g_maBuffer[];\n\nint OnInit()\n{\n    g_maHandle = iMA(_Symbol, PERIOD_CURRENT, 14, 0, MODE_SMA, PRICE_CLOSE);\n    if(g_maHandle == INVALID_HANDLE)\n        return INIT_FAILED;\n    ArraySetAsSeries(g_maBuffer, true);\n    return INIT_SUCCEEDED;\n}\n\nvoid OnDeinit(const int reason)\n{\n    if(g_maHandle != INVALID_HANDLE)\n        IndicatorRelease(g_maHandle);\n}\n\nvoid OnTick()\n{\n    if(CheckSignal())\n    {\n        double currentLot = LotSize;  // Copy input to local variable\n        currentLot = 0.2;  // Now we can modify it\n        \n        MqlTradeRequest request = {};\n        MqlTradeResult result = {};\n        \n        request.action = TRADE_ACTION_DEAL;\n        request.symbol = _Symbol;\n        request.volume = currentLot;\n        request.type = ORDER_TYPE_BUY;\n        request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);\n        request.deviation = 3;\n        \n        OrderSend(request, result);\n    }\n}\n\nbool CheckSignal()\n{\n    if(CopyBuffer(g_maHandle, 0, 0, 1, g_maBuffer) < 1)\n        return false;\n    return g_maBuffer[0] > 0;\n}\n",
  "fixes_applied": [
    {
      "line": 7,
      "error": "'LotSize' - constant cannot be modified",
      "fix": "Created local variable 'currentLot' as copy of input parameter",
      "reference": "MQL5 Variables > Input Variables"
    },
    {
      "line": 8,
      "error": "'OrderSend' - wrong parameters count",
      "fix": "Converted to MT5 MqlTradeRequest/Result pattern",
      "reference": "Trade Functions > OrderSend"
    },
    {
      "line": 8,
      "error": "'OP_BUY' - undeclared identifier",
      "fix": "Replaced with ORDER_TYPE_BUY",
      "reference": "Trade Constants > ENUM_ORDER_TYPE"
    },
    {
      "line": 8,
      "error": "';' - semicolon expected",
      "fix": "Added missing semicolon",
      "reference": "MQL5 syntax"
    },
    {
      "line": 15,
      "error": "'iMA' - wrong parameters count",
      "fix": "Converted to handle pattern with CopyBuffer. Added OnInit for handle creation and OnDeinit for cleanup.",
      "reference": "Technical Indicators > iMA"
    }
  ],
  "unfixable_errors": []
}
```
