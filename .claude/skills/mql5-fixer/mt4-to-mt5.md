# MT4 to MT5 Migration Guide

Common MT4 patterns and their MQL5 equivalents.

## Order Execution

### OrderSend (Complete Transformation)

**MT4:**
```cpp
int ticket = OrderSend(
    Symbol(),       // symbol
    OP_BUY,         // operation
    0.1,            // volume
    Ask,            // price
    3,              // slippage
    Ask - 50*Point, // stop loss
    Ask + 100*Point,// take profit
    "comment",      // comment
    12345,          // magic
    0,              // expiration
    clrGreen        // arrow color
);
```

**MQL5 (Using CTrade - RECOMMENDED):**
```cpp
#include <Trade\Trade.mqh>
CTrade trade;

// In OnInit:
trade.SetExpertMagicNumber(12345);
trade.SetDeviationInPoints(3);

// When trading:
double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
double sl = ask - 50 * _Point;
double tp = ask + 100 * _Point;

if(!trade.Buy(0.1, _Symbol, ask, sl, tp, "comment"))
{
    Print("Error: ", trade.ResultRetcodeDescription());
}
```

**MQL5 (Using MqlTradeRequest):**
```cpp
MqlTradeRequest request = {};
MqlTradeResult result = {};

request.action = TRADE_ACTION_DEAL;
request.symbol = _Symbol;
request.volume = 0.1;
request.type = ORDER_TYPE_BUY;
request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
request.sl = request.price - 50 * _Point;
request.tp = request.price + 100 * _Point;
request.deviation = 3;
request.magic = 12345;
request.comment = "comment";

if(!OrderSend(request, result))
{
    Print("Error: ", GetLastError());
}
```

### OrderClose

**MT4:**
```cpp
OrderClose(ticket, 0.1, Bid, 3, clrRed);
```

**MQL5:**
```cpp
// Using CTrade
trade.PositionClose(ticket);

// Or close by symbol
trade.PositionClose(_Symbol);
```

### OrderModify

**MT4:**
```cpp
OrderModify(ticket, price, sl, tp, 0, clrBlue);
```

**MQL5:**
```cpp
// Modify position
trade.PositionModify(ticket, sl, tp);

// Modify pending order
trade.OrderModify(ticket, price, sl, tp, ORDER_TIME_GTC, 0);
```

## Order Type Constants

| MT4 | MQL5 |
|-----|------|
| OP_BUY | ORDER_TYPE_BUY |
| OP_SELL | ORDER_TYPE_SELL |
| OP_BUYLIMIT | ORDER_TYPE_BUY_LIMIT |
| OP_SELLLIMIT | ORDER_TYPE_SELL_LIMIT |
| OP_BUYSTOP | ORDER_TYPE_BUY_STOP |
| OP_SELLSTOP | ORDER_TYPE_SELL_STOP |

## Price Access

### Ask / Bid

**MT4:**
```cpp
double ask = Ask;
double bid = Bid;
```

**MQL5:**
```cpp
double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

// Or using MqlTick
MqlTick tick;
if(SymbolInfoTick(_Symbol, tick))
{
    double ask = tick.ask;
    double bid = tick.bid;
}

// Or using CSymbolInfo
#include <Trade\SymbolInfo.mqh>
CSymbolInfo symbolInfo;
symbolInfo.Name(_Symbol);
symbolInfo.RefreshRates();
double ask = symbolInfo.Ask();
double bid = symbolInfo.Bid();
```

### Point / Digits

**MT4:**
```cpp
double pt = Point;
int dig = Digits;
```

**MQL5:**
```cpp
double pt = _Point;  // or SymbolInfoDouble(_Symbol, SYMBOL_POINT)
int dig = _Digits;   // or (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS)
```

## Indicator Functions

### iMA (Moving Average)

**MT4:**
```cpp
double ma = iMA(Symbol(), PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE, 0);
double maPrev = iMA(Symbol(), PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE, 1);
```

**MQL5:**
```cpp
// Global scope
int maHandle;
double maBuffer[];

// OnInit
maHandle = iMA(_Symbol, PERIOD_H1, 14, 0, MODE_SMA, PRICE_CLOSE);
ArraySetAsSeries(maBuffer, true);

// OnDeinit
IndicatorRelease(maHandle);

// When needed
if(CopyBuffer(maHandle, 0, 0, 2, maBuffer) >= 2)
{
    double ma = maBuffer[0];      // Current bar
    double maPrev = maBuffer[1];  // Previous bar
}
```

### iRSI

**MT4:**
```cpp
double rsi = iRSI(Symbol(), PERIOD_H1, 14, PRICE_CLOSE, 0);
```

**MQL5:**
```cpp
// Global
int rsiHandle;
double rsiBuffer[];

// OnInit
rsiHandle = iRSI(_Symbol, PERIOD_H1, 14, PRICE_CLOSE);
ArraySetAsSeries(rsiBuffer, true);

// When needed
CopyBuffer(rsiHandle, 0, 0, 1, rsiBuffer);
double rsi = rsiBuffer[0];
```

### iMACD

**MT4:**
```cpp
double macdMain = iMACD(Symbol(), 0, 12, 26, 9, PRICE_CLOSE, MODE_MAIN, 0);
double macdSignal = iMACD(Symbol(), 0, 12, 26, 9, PRICE_CLOSE, MODE_SIGNAL, 0);
```

**MQL5:**
```cpp
// Global
int macdHandle;
double macdMainBuffer[];
double macdSignalBuffer[];

// OnInit
macdHandle = iMACD(_Symbol, PERIOD_CURRENT, 12, 26, 9, PRICE_CLOSE);
ArraySetAsSeries(macdMainBuffer, true);
ArraySetAsSeries(macdSignalBuffer, true);

// When needed
CopyBuffer(macdHandle, 0, 0, 1, macdMainBuffer);  // Main line
CopyBuffer(macdHandle, 1, 0, 1, macdSignalBuffer); // Signal line
double macdMain = macdMainBuffer[0];
double macdSignal = macdSignalBuffer[0];
```

### iBands (Bollinger Bands)

**MT4:**
```cpp
double upper = iBands(Symbol(), 0, 20, 2, 0, PRICE_CLOSE, MODE_UPPER, 0);
double lower = iBands(Symbol(), 0, 20, 2, 0, PRICE_CLOSE, MODE_LOWER, 0);
double middle = iBands(Symbol(), 0, 20, 2, 0, PRICE_CLOSE, MODE_MAIN, 0);
```

**MQL5:**
```cpp
// Global
int bandsHandle;
double upperBuffer[], lowerBuffer[], middleBuffer[];

// OnInit
bandsHandle = iBands(_Symbol, PERIOD_CURRENT, 20, 0, 2, PRICE_CLOSE);
ArraySetAsSeries(upperBuffer, true);
ArraySetAsSeries(lowerBuffer, true);
ArraySetAsSeries(middleBuffer, true);

// When needed
CopyBuffer(bandsHandle, 0, 0, 1, middleBuffer); // Middle
CopyBuffer(bandsHandle, 1, 0, 1, upperBuffer);  // Upper
CopyBuffer(bandsHandle, 2, 0, 1, lowerBuffer);  // Lower
```

## Order/Position Functions

### OrderSelect / OrdersTotal

**MT4 (selecting by position):**
```cpp
for(int i = OrdersTotal() - 1; i >= 0; i--)
{
    if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
    {
        if(OrderSymbol() == Symbol() && OrderMagicNumber() == MagicNumber)
        {
            // Process order
        }
    }
}
```

**MQL5 (positions):**
```cpp
#include <Trade\PositionInfo.mqh>
CPositionInfo positionInfo;

for(int i = PositionsTotal() - 1; i >= 0; i--)
{
    if(positionInfo.SelectByIndex(i))
    {
        if(positionInfo.Symbol() == _Symbol && positionInfo.Magic() == MagicNumber)
        {
            // Process position
        }
    }
}
```

### Order Properties

| MT4 | MQL5 (CPositionInfo) |
|-----|---------------------|
| OrderTicket() | positionInfo.Ticket() |
| OrderSymbol() | positionInfo.Symbol() |
| OrderType() | positionInfo.PositionType() |
| OrderLots() | positionInfo.Volume() |
| OrderOpenPrice() | positionInfo.PriceOpen() |
| OrderStopLoss() | positionInfo.StopLoss() |
| OrderTakeProfit() | positionInfo.TakeProfit() |
| OrderProfit() | positionInfo.Profit() |
| OrderMagicNumber() | positionInfo.Magic() |
| OrderComment() | positionInfo.Comment() |

## Account Functions

| MT4 | MQL5 |
|-----|------|
| AccountBalance() | AccountInfoDouble(ACCOUNT_BALANCE) |
| AccountEquity() | AccountInfoDouble(ACCOUNT_EQUITY) |
| AccountFreeMargin() | AccountInfoDouble(ACCOUNT_MARGIN_FREE) |
| AccountMargin() | AccountInfoDouble(ACCOUNT_MARGIN) |
| AccountProfit() | AccountInfoDouble(ACCOUNT_PROFIT) |

## Time Functions

| MT4 | MQL5 |
|-----|------|
| Time[i] | iTime(_Symbol, _Period, i) |
| Open[i] | iOpen(_Symbol, _Period, i) |
| High[i] | iHigh(_Symbol, _Period, i) |
| Low[i] | iLow(_Symbol, _Period, i) |
| Close[i] | iClose(_Symbol, _Period, i) |
| Volume[i] | iVolume(_Symbol, _Period, i) |

**Better approach for price data:**
```cpp
MqlRates rates[];
ArraySetAsSeries(rates, true);
CopyRates(_Symbol, _Period, 0, 100, rates);
// rates[0].open, rates[0].high, rates[0].low, rates[0].close, rates[0].time
```

## Timeframe Constants

| MT4 | MQL5 |
|-----|------|
| PERIOD_M1 | PERIOD_M1 (same) |
| PERIOD_M5 | PERIOD_M5 (same) |
| PERIOD_M15 | PERIOD_M15 (same) |
| PERIOD_M30 | PERIOD_M30 (same) |
| PERIOD_H1 | PERIOD_H1 (same) |
| PERIOD_H4 | PERIOD_H4 (same) |
| PERIOD_D1 | PERIOD_D1 (same) |
| PERIOD_W1 | PERIOD_W1 (same) |
| PERIOD_MN1 | PERIOD_MN1 (same) |
| 0 (current) | PERIOD_CURRENT |

## Symbol Function

| MT4 | MQL5 |
|-----|------|
| Symbol() | _Symbol |

## Miscellaneous

### MarketInfo

**MT4:**
```cpp
double spread = MarketInfo(Symbol(), MODE_SPREAD);
double point = MarketInfo(Symbol(), MODE_POINT);
```

**MQL5:**
```cpp
double spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
```

### Alert/Comment/Print
These work the same in MT4 and MQL5.

### Sleep
Same in both, but avoid in tester:
```cpp
if(!MQLInfoInteger(MQL_TESTER))
    Sleep(100);
```
