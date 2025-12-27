# MQL5 Best Practices

Guidelines for writing robust, maintainable MQL5 code.

## Error Handling

### Always Check Return Values
```cpp
// BAD
trade.Buy(0.1, _Symbol);

// GOOD
if(!trade.Buy(0.1, _Symbol, 0, sl, tp, ""))
{
   Print("Buy failed: ", trade.ResultRetcode(), " - ", trade.ResultRetcodeDescription());
}
```

### Check Indicator Handles
```cpp
int handle = iMA(_Symbol, PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE);
if(handle == INVALID_HANDLE)
{
   Print("Failed to create indicator handle: ", GetLastError());
   return INIT_FAILED;
}
```

### Validate CopyBuffer Results
```cpp
if(CopyBuffer(handle, 0, 0, 3, buffer) < 3)
{
   Print("Not enough data copied");
   return;
}
```

## Memory Management

### Release Indicator Handles
```cpp
void OnDeinit(const int reason)
{
   if(maHandle != INVALID_HANDLE)
      IndicatorRelease(maHandle);
   if(rsiHandle != INVALID_HANDLE)
      IndicatorRelease(rsiHandle);
}
```

### ArraySetAsSeries for Buffers
```cpp
double buffer[];
ArraySetAsSeries(buffer, true);  // Index 0 = current bar
```

## Price Normalization

### Always Normalize Prices
```cpp
double sl = NormalizeDouble(price - 50 * _Point, _Digits);
double tp = NormalizeDouble(price + 100 * _Point, _Digits);
```

### Use SymbolInfo for Symbol Properties
```cpp
double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
```

## Position Management

### Filter by Magic Number
```cpp
for(int i = PositionsTotal() - 1; i >= 0; i--)
{
   if(positionInfo.SelectByIndex(i))
   {
      // CRITICAL: Always filter by symbol AND magic
      if(positionInfo.Symbol() != _Symbol) continue;
      if(positionInfo.Magic() != MagicNumber) continue;

      // Your logic here
   }
}
```

### Iterate Backwards When Closing
```cpp
// CORRECT: Iterate backwards when closing positions
for(int i = PositionsTotal() - 1; i >= 0; i--)

// WRONG: Forward iteration can skip positions after close
for(int i = 0; i < PositionsTotal(); i++)
```

## Input Parameters

### Use Meaningful Names and Descriptions
```cpp
input group "=== Trading Settings ==="
input double   InpLotSize      = 0.01;    // Lot Size
input int      InpMagicNumber  = 12345;   // Magic Number
input int      InpSlippage     = 10;      // Max Slippage (points)

input group "=== Strategy Parameters ==="
input int      InpFastMA       = 10;      // Fast MA Period
input int      InpSlowMA       = 50;      // Slow MA Period

input group "=== Risk Management ==="
input double   InpStopLoss     = 50;      // Stop Loss (points)
input double   InpTakeProfit   = 100;     // Take Profit (points)
```

### Use sinput for Optimization Exclusion
```cpp
sinput int MagicNumber = 12345;  // Not optimizable
```

## Order Execution

### Set Filling Mode Based on Broker
```cpp
ENUM_ORDER_TYPE_FILLING GetFillingMode()
{
   uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);

   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;

   return ORDER_FILLING_RETURN;
}

// In OnInit:
trade.SetTypeFilling(GetFillingMode());
```

### Handle Requotes
```cpp
int attempts = 3;
while(attempts > 0)
{
   if(trade.Buy(lot, _Symbol, 0, sl, tp, ""))
      break;

   if(trade.ResultRetcode() == TRADE_RETCODE_REQUOTE)
   {
      symbolInfo.RefreshRates();
      attempts--;
      Sleep(100);
   }
   else
   {
      break;
   }
}
```

## Performance

### Trade Only on New Bars (When Appropriate)
```cpp
void OnTick()
{
   if(!IsNewBar()) return;

   // Entry/exit logic that doesn't need every tick
}
```

### Cache Symbol Information
```cpp
CSymbolInfo symbolInfo;

int OnInit()
{
   symbolInfo.Name(_Symbol);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   symbolInfo.RefreshRates();  // Update once per tick
   // Use symbolInfo.Ask(), symbolInfo.Bid(), etc.
}
```

### Minimize CopyBuffer Calls
```cpp
// BAD: Calling CopyBuffer multiple times for same data
double ma1 = GetMA(0);
double ma2 = GetMA(1);
double ma3 = GetMA(2);

// GOOD: Copy once, use array
CopyBuffer(maHandle, 0, 0, 3, maBuffer);
double ma1 = maBuffer[0];
double ma2 = maBuffer[1];
double ma3 = maBuffer[2];
```

## Code Organization

### Use #define for Constants
```cpp
#define EA_VERSION    "1.00"
#define EA_COPYRIGHT  "Your Name"
```

### Separate Logic into Functions
```cpp
void OnTick()
{
   if(!IsWithinTradingHours()) return;
   if(!IsNewBar()) return;

   UpdateIndicators();

   int signal = CheckSignal();

   if(signal == 1 && !HasOpenPosition(POSITION_TYPE_BUY))
      OpenBuy();
   else if(signal == -1 && !HasOpenPosition(POSITION_TYPE_SELL))
      OpenSell();

   ManageOpenPositions();
}
```

## Debugging

### Use Print Strategically
```cpp
#ifdef _DEBUG
   Print("Signal: ", signal, " | FastMA: ", fastMA, " | SlowMA: ", slowMA);
#endif
```

### Log Trade Results
```cpp
void LogTradeResult(string action)
{
   Print(action, " | Retcode: ", trade.ResultRetcode(),
         " | Deal: ", trade.ResultDeal(),
         " | Order: ", trade.ResultOrder(),
         " | Price: ", trade.ResultPrice(),
         " | Volume: ", trade.ResultVolume());
}
```

## Common Pitfalls to Avoid

1. **Modifying input parameters** - Copy to local variable first
2. **Using Ask/Bid directly** - Use SymbolInfoDouble or CSymbolInfo
3. **MT4-style OrderSend** - Use CTrade or MqlTradeRequest
4. **Forgetting ArraySetAsSeries** - Buffers need this for index 0 = current
5. **Not checking broker support** - Verify filling modes, trade modes
6. **Infinite loops** - Always have exit conditions
7. **Not filtering by magic number** - EA will interfere with other positions
8. **Forward iteration when closing** - Use reverse iteration

## Tester Compatibility

### Check if Running in Tester
```cpp
if(MQLInfoInteger(MQL_TESTER))
{
   // Tester-specific code
}
```

### Avoid Sleep in Tester
```cpp
if(!MQLInfoInteger(MQL_TESTER))
{
   Sleep(100);
}
```
