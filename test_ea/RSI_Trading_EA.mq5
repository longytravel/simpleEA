//+------------------------------------------------------------------+
//|                                               RSI_Trading_EA.mq5 |
//|                        Working RSI EA with position management   |
//+------------------------------------------------------------------+
#property copyright "Simple EA Maker"
#property version   "1.00"
#property strict

// Input parameters
input int      RSI_Period = 14;
input double   RSI_Overbought = 70.0;
input double   RSI_Oversold = 30.0;
input double   LotSize = 0.01;
input int      MagicNumber = 98765;
input int      StopLoss = 500;      // Stop loss in points
input int      TakeProfit = 500;    // Take profit in points

// Global variables
int rsiHandle = INVALID_HANDLE;
double rsiBuffer[];
datetime lastBarTime = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    // Create RSI indicator handle
    rsiHandle = iRSI(_Symbol, PERIOD_CURRENT, RSI_Period, PRICE_CLOSE);

    if(rsiHandle == INVALID_HANDLE)
    {
        Print("Failed to create RSI indicator handle: ", GetLastError());
        return(INIT_FAILED);
    }

    ArraySetAsSeries(rsiBuffer, true);

    Print("RSI Trading EA initialized. Magic: ", MagicNumber);
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    if(rsiHandle != INVALID_HANDLE)
        IndicatorRelease(rsiHandle);

    Print("RSI Trading EA stopped");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    // Only trade on new bar to avoid over-trading
    datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(currentBarTime == lastBarTime)
        return;
    lastBarTime = currentBarTime;

    // Get RSI values (current and previous bar)
    if(CopyBuffer(rsiHandle, 0, 0, 3, rsiBuffer) < 3)
    {
        Print("Failed to copy RSI buffer");
        return;
    }

    double rsiCurrent = rsiBuffer[1];   // Completed bar
    double rsiPrevious = rsiBuffer[2];  // Bar before that

    // Get current position status
    int positionType = GetPositionType();

    // Check for close signals first
    if(positionType == 1) // Have buy position
    {
        // Close buy if RSI crosses above overbought
        if(rsiPrevious < RSI_Overbought && rsiCurrent >= RSI_Overbought)
        {
            ClosePosition();
        }
    }
    else if(positionType == -1) // Have sell position
    {
        // Close sell if RSI crosses below oversold
        if(rsiPrevious > RSI_Oversold && rsiCurrent <= RSI_Oversold)
        {
            ClosePosition();
        }
    }

    // Re-check position after potential close
    positionType = GetPositionType();

    // Only open new positions if we have none
    if(positionType == 0)
    {
        // Buy signal: RSI crosses above oversold level
        if(rsiPrevious <= RSI_Oversold && rsiCurrent > RSI_Oversold)
        {
            OpenBuy();
        }
        // Sell signal: RSI crosses below overbought level
        else if(rsiPrevious >= RSI_Overbought && rsiCurrent < RSI_Overbought)
        {
            OpenSell();
        }
    }
}

//+------------------------------------------------------------------+
//| Get current position type (1=buy, -1=sell, 0=none)               |
//+------------------------------------------------------------------+
int GetPositionType()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket > 0)
        {
            if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
               PositionGetInteger(POSITION_MAGIC) == MagicNumber)
            {
                ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
                if(type == POSITION_TYPE_BUY)
                    return 1;
                else if(type == POSITION_TYPE_SELL)
                    return -1;
            }
        }
    }
    return 0;
}

//+------------------------------------------------------------------+
//| Open buy position                                                |
//+------------------------------------------------------------------+
void OpenBuy()
{
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

    double sl = NormalizeDouble(ask - StopLoss * point, digits);
    double tp = NormalizeDouble(ask + TakeProfit * point, digits);

    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_DEAL;
    request.symbol = _Symbol;
    request.volume = LotSize;
    request.type = ORDER_TYPE_BUY;
    request.price = ask;
    request.sl = sl;
    request.tp = tp;
    request.deviation = 10;
    request.magic = MagicNumber;
    request.comment = "RSI Buy";
    request.type_filling = ORDER_FILLING_IOC;

    if(OrderSend(request, result))
    {
        if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED)
            Print("Buy opened: ", result.order, " at ", ask, " RSI=", rsiBuffer[1]);
        else
            Print("Buy failed: ", result.retcode, " ", result.comment);
    }
    else
    {
        Print("OrderSend error: ", GetLastError());
    }
}

//+------------------------------------------------------------------+
//| Open sell position                                               |
//+------------------------------------------------------------------+
void OpenSell()
{
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

    double sl = NormalizeDouble(bid + StopLoss * point, digits);
    double tp = NormalizeDouble(bid - TakeProfit * point, digits);

    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_DEAL;
    request.symbol = _Symbol;
    request.volume = LotSize;
    request.type = ORDER_TYPE_SELL;
    request.price = bid;
    request.sl = sl;
    request.tp = tp;
    request.deviation = 10;
    request.magic = MagicNumber;
    request.comment = "RSI Sell";
    request.type_filling = ORDER_FILLING_IOC;

    if(OrderSend(request, result))
    {
        if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED)
            Print("Sell opened: ", result.order, " at ", bid, " RSI=", rsiBuffer[1]);
        else
            Print("Sell failed: ", result.retcode, " ", result.comment);
    }
    else
    {
        Print("OrderSend error: ", GetLastError());
    }
}

//+------------------------------------------------------------------+
//| Close current position                                           |
//+------------------------------------------------------------------+
void ClosePosition()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket > 0)
        {
            if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
               PositionGetInteger(POSITION_MAGIC) == MagicNumber)
            {
                ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
                double volume = PositionGetDouble(POSITION_VOLUME);

                MqlTradeRequest request = {};
                MqlTradeResult result = {};

                request.action = TRADE_ACTION_DEAL;
                request.symbol = _Symbol;
                request.volume = volume;
                request.deviation = 10;
                request.magic = MagicNumber;
                request.position = ticket;
                request.type_filling = ORDER_FILLING_IOC;

                if(type == POSITION_TYPE_BUY)
                {
                    request.type = ORDER_TYPE_SELL;
                    request.price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
                }
                else
                {
                    request.type = ORDER_TYPE_BUY;
                    request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
                }

                if(OrderSend(request, result))
                {
                    if(result.retcode == TRADE_RETCODE_DONE)
                        Print("Position closed: ", ticket);
                    else
                        Print("Close failed: ", result.retcode);
                }
            }
        }
    }
}
