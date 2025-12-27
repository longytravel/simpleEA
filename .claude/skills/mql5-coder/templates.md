# MQL5 Code Templates

Common patterns for EA development. Always verify against official docs before using.

## EA Skeleton

```cpp
//+------------------------------------------------------------------+
//|                                                    MyEA.mq5      |
//+------------------------------------------------------------------+
#property copyright "Your Name"
#property link      ""
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

// Input parameters
input double   LotSize     = 0.01;    // Lot size
input int      MagicNumber = 12345;   // Magic number
input int      Slippage    = 10;      // Slippage in points
input double   StopLoss    = 50;      // Stop loss in points
input double   TakeProfit  = 100;     // Take profit in points

// Global objects
CTrade         trade;
CPositionInfo  positionInfo;
CSymbolInfo    symbolInfo;

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   // Initialize trade object
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(Slippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   // Initialize symbol info
   if(!symbolInfo.Name(_Symbol))
   {
      Print("Failed to set symbol name");
      return INIT_FAILED;
   }

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Cleanup code here
}

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
{
   // Update symbol info
   symbolInfo.RefreshRates();

   // Your trading logic here
}
```

## Opening a Buy Position

```cpp
void OpenBuy()
{
   symbolInfo.RefreshRates();

   double price = symbolInfo.Ask();
   double sl = price - StopLoss * symbolInfo.Point();
   double tp = price + TakeProfit * symbolInfo.Point();

   // Normalize prices
   sl = NormalizeDouble(sl, symbolInfo.Digits());
   tp = NormalizeDouble(tp, symbolInfo.Digits());

   if(!trade.Buy(LotSize, _Symbol, price, sl, tp, "Buy signal"))
   {
      Print("Buy failed. Error: ", GetLastError());
   }
}
```

## Opening a Sell Position

```cpp
void OpenSell()
{
   symbolInfo.RefreshRates();

   double price = symbolInfo.Bid();
   double sl = price + StopLoss * symbolInfo.Point();
   double tp = price - TakeProfit * symbolInfo.Point();

   // Normalize prices
   sl = NormalizeDouble(sl, symbolInfo.Digits());
   tp = NormalizeDouble(tp, symbolInfo.Digits());

   if(!trade.Sell(LotSize, _Symbol, price, sl, tp, "Sell signal"))
   {
      Print("Sell failed. Error: ", GetLastError());
   }
}
```

## Closing All Positions

```cpp
void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(positionInfo.SelectByIndex(i))
      {
         if(positionInfo.Symbol() == _Symbol && positionInfo.Magic() == MagicNumber)
         {
            trade.PositionClose(positionInfo.Ticket());
         }
      }
   }
}
```

## Check for Existing Position

```cpp
bool HasOpenPosition(ENUM_POSITION_TYPE type)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(positionInfo.SelectByIndex(i))
      {
         if(positionInfo.Symbol() == _Symbol &&
            positionInfo.Magic() == MagicNumber &&
            positionInfo.PositionType() == type)
         {
            return true;
         }
      }
   }
   return false;
}

// Usage:
// if(!HasOpenPosition(POSITION_TYPE_BUY)) OpenBuy();
```

## Moving Average Indicator

```cpp
// Global scope
int maHandle;
double maBuffer[];

int OnInit()
{
   // Create indicator handle
   maHandle = iMA(_Symbol, PERIOD_CURRENT, 14, 0, MODE_SMA, PRICE_CLOSE);
   if(maHandle == INVALID_HANDLE)
   {
      Print("Failed to create MA handle");
      return INIT_FAILED;
   }

   // Set buffer as series (index 0 = current bar)
   ArraySetAsSeries(maBuffer, true);

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   // Release indicator handle
   IndicatorRelease(maHandle);
}

double GetMA(int shift = 0)
{
   if(CopyBuffer(maHandle, 0, shift, 1, maBuffer) > 0)
      return maBuffer[0];
   return 0;
}
```

## RSI Indicator

```cpp
// Global scope
int rsiHandle;
double rsiBuffer[];

int OnInit()
{
   rsiHandle = iRSI(_Symbol, PERIOD_CURRENT, 14, PRICE_CLOSE);
   if(rsiHandle == INVALID_HANDLE)
   {
      Print("Failed to create RSI handle");
      return INIT_FAILED;
   }
   ArraySetAsSeries(rsiBuffer, true);
   return INIT_SUCCEEDED;
}

double GetRSI(int shift = 0)
{
   if(CopyBuffer(rsiHandle, 0, shift, 1, rsiBuffer) > 0)
      return rsiBuffer[0];
   return 50;  // Neutral on error
}
```

## MA Crossover Signal

```cpp
// Global handles
int fastMAHandle, slowMAHandle;
double fastMABuffer[], slowMABuffer[];

int OnInit()
{
   fastMAHandle = iMA(_Symbol, PERIOD_CURRENT, 10, 0, MODE_SMA, PRICE_CLOSE);
   slowMAHandle = iMA(_Symbol, PERIOD_CURRENT, 50, 0, MODE_SMA, PRICE_CLOSE);

   ArraySetAsSeries(fastMABuffer, true);
   ArraySetAsSeries(slowMABuffer, true);

   return INIT_SUCCEEDED;
}

int CheckSignal()
{
   // Copy 2 bars (current and previous)
   if(CopyBuffer(fastMAHandle, 0, 0, 2, fastMABuffer) < 2) return 0;
   if(CopyBuffer(slowMAHandle, 0, 0, 2, slowMABuffer) < 2) return 0;

   // Check for crossover
   bool fastAboveNow = fastMABuffer[0] > slowMABuffer[0];
   bool fastAbovePrev = fastMABuffer[1] > slowMABuffer[1];

   if(fastAboveNow && !fastAbovePrev) return 1;   // Buy signal
   if(!fastAboveNow && fastAbovePrev) return -1;  // Sell signal

   return 0;  // No signal
}
```

## Trailing Stop

```cpp
void TrailStop(double trailPoints)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(positionInfo.SelectByIndex(i))
      {
         if(positionInfo.Symbol() != _Symbol || positionInfo.Magic() != MagicNumber)
            continue;

         double currentSL = positionInfo.StopLoss();
         double openPrice = positionInfo.PriceOpen();
         double point = symbolInfo.Point();

         symbolInfo.RefreshRates();

         if(positionInfo.PositionType() == POSITION_TYPE_BUY)
         {
            double newSL = symbolInfo.Bid() - trailPoints * point;
            newSL = NormalizeDouble(newSL, symbolInfo.Digits());

            if(newSL > currentSL && newSL > openPrice)
            {
               trade.PositionModify(positionInfo.Ticket(), newSL, positionInfo.TakeProfit());
            }
         }
         else if(positionInfo.PositionType() == POSITION_TYPE_SELL)
         {
            double newSL = symbolInfo.Ask() + trailPoints * point;
            newSL = NormalizeDouble(newSL, symbolInfo.Digits());

            if(newSL < currentSL && newSL < openPrice)
            {
               trade.PositionModify(positionInfo.Ticket(), newSL, positionInfo.TakeProfit());
            }
         }
      }
   }
}
```

## Break-Even Stop

```cpp
void MoveToBreakEven(double triggerPoints, double offsetPoints)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(positionInfo.SelectByIndex(i))
      {
         if(positionInfo.Symbol() != _Symbol || positionInfo.Magic() != MagicNumber)
            continue;

         double openPrice = positionInfo.PriceOpen();
         double currentSL = positionInfo.StopLoss();
         double point = symbolInfo.Point();

         symbolInfo.RefreshRates();

         if(positionInfo.PositionType() == POSITION_TYPE_BUY)
         {
            double profit = symbolInfo.Bid() - openPrice;
            double breakEvenSL = openPrice + offsetPoints * point;

            if(profit >= triggerPoints * point && currentSL < breakEvenSL)
            {
               trade.PositionModify(positionInfo.Ticket(), breakEvenSL, positionInfo.TakeProfit());
            }
         }
         else if(positionInfo.PositionType() == POSITION_TYPE_SELL)
         {
            double profit = openPrice - symbolInfo.Ask();
            double breakEvenSL = openPrice - offsetPoints * point;

            if(profit >= triggerPoints * point && (currentSL > breakEvenSL || currentSL == 0))
            {
               trade.PositionModify(positionInfo.Ticket(), breakEvenSL, positionInfo.TakeProfit());
            }
         }
      }
   }
}
```

## Time Filter

```cpp
input int StartHour = 8;   // Trading start hour
input int EndHour   = 20;  // Trading end hour

bool IsWithinTradingHours()
{
   MqlDateTime dt;
   TimeCurrent(dt);

   if(StartHour < EndHour)
   {
      return (dt.hour >= StartHour && dt.hour < EndHour);
   }
   else  // Overnight session
   {
      return (dt.hour >= StartHour || dt.hour < EndHour);
   }
}
```

## Position Sizing (Risk-Based)

```cpp
input double RiskPercent = 1.0;  // Risk per trade (%)

double CalculateLotSize(double stopLossPoints)
{
   double accountBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = accountBalance * (RiskPercent / 100.0);

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   double pointValue = tickValue * (point / tickSize);
   double lotSize = riskAmount / (stopLossPoints * pointValue);

   // Normalize to lot step
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   lotSize = MathFloor(lotSize / lotStep) * lotStep;
   lotSize = MathMax(minLot, MathMin(maxLot, lotSize));

   return NormalizeDouble(lotSize, 2);
}
```

## New Bar Detection

```cpp
datetime lastBarTime = 0;

bool IsNewBar()
{
   datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentBarTime != lastBarTime)
   {
      lastBarTime = currentBarTime;
      return true;
   }
   return false;
}

void OnTick()
{
   if(!IsNewBar()) return;  // Only trade on new bars

   // Trading logic here
}
```
