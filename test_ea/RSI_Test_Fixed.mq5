//+------------------------------------------------------------------+
//|                                               RSI_Test_Fixed.mq5 |
//|                        FIXED VERSION - All MT5 patterns correct  |
//+------------------------------------------------------------------+
#property copyright "Test EA"
#property version   "1.00"
#property strict

// Input parameters
input int      RSI_Period = 14;
input double   RSI_Overbought = 70.0;
input double   RSI_Oversold = 30.0;
input double   LotSize = 0.01;
input int      MagicNumber = 12345;

// Global variables for indicator handle
int rsiHandle = INVALID_HANDLE;
double rsiBuffer[];

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    Print("RSI EA Initialized");  // FIX 1: Added semicolon

    // FIX 2: Create RSI indicator handle (MT5 pattern)
    rsiHandle = iRSI(_Symbol, PERIOD_H1, RSI_Period, PRICE_CLOSE);

    if(rsiHandle == INVALID_HANDLE)
    {
        Print("Failed to create RSI indicator handle");
        return(INIT_FAILED);
    }

    // Set buffer as series (newest first)
    ArraySetAsSeries(rsiBuffer, true);

    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    // FIX 2: Get RSI value using CopyBuffer (MT5 pattern)
    if(CopyBuffer(rsiHandle, 0, 0, 1, rsiBuffer) < 1)
    {
        Print("Failed to copy RSI buffer");
        return;
    }
    double rsiValue = rsiBuffer[0];

    // FIX 3: Get Ask and Bid using SymbolInfoDouble (MT5 pattern)
    double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

    // Check for buy signal
    if(rsiValue < RSI_Oversold)
    {
        // FIX 4 & 5: MT5-style OrderSend with MqlTradeRequest/Result
        MqlTradeRequest request = {};
        MqlTradeResult result = {};

        request.action = TRADE_ACTION_DEAL;
        request.symbol = _Symbol;
        request.volume = LotSize;
        request.type = ORDER_TYPE_BUY;
        request.price = currentAsk;
        request.deviation = 3;
        request.magic = MagicNumber;
        request.comment = "RSI Buy";

        if(OrderSend(request, result))
            Print("Buy order opened: ", result.order);
        else
            Print("Buy order failed: ", GetLastError());
    }

    // Check for sell signal
    if(rsiValue > RSI_Overbought)
    {
        // FIX 4 & 5: MT5-style OrderSend with MqlTradeRequest/Result
        MqlTradeRequest request = {};
        MqlTradeResult result = {};

        request.action = TRADE_ACTION_DEAL;
        request.symbol = _Symbol;
        request.volume = LotSize;
        request.type = ORDER_TYPE_SELL;
        request.price = currentBid;
        request.deviation = 3;
        request.magic = MagicNumber;
        request.comment = "RSI Sell";

        if(OrderSend(request, result))
            Print("Sell order opened: ", result.order);
        else
            Print("Sell order failed: ", GetLastError());
    }
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    // Release the indicator handle
    if(rsiHandle != INVALID_HANDLE)
        IndicatorRelease(rsiHandle);

    Print("RSI EA Deinitialized");
}
