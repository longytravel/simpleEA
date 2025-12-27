//+------------------------------------------------------------------+
//|                                              RSI_Test_Broken.mq5 |
//|                        TEST EA WITH DELIBERATE ERRORS            |
//|                                                                  |
//|  ERRORS INCLUDED:                                                |
//|  1. MT4-style iRSI() call (wrong parameters for MT5)             |
//|  2. Using Ask/Bid directly (doesn't exist in MT5)                |
//|  3. MT4-style OrderSend (completely different in MT5)            |
//|  4. Missing semicolon on line 35                                 |
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

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    Print("RSI EA Initialized")   // ERROR 1: Missing semicolon
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    // ERROR 2: MT4-style iRSI call - MT5 returns handle, not value!
    double rsiValue = iRSI(Symbol(), PERIOD_H1, RSI_Period, PRICE_CLOSE, 0);

    // ERROR 3: Ask and Bid don't exist as globals in MT5
    double currentAsk = Ask;
    double currentBid = Bid;

    // Check for buy signal
    if(rsiValue < RSI_Oversold)
    {
        // ERROR 4: MT4-style OrderSend - completely wrong for MT5!
        int ticket = OrderSend(Symbol(), OP_BUY, LotSize, Ask, 3, 0, 0, "RSI Buy", MagicNumber);
        if(ticket > 0)
            Print("Buy order opened: ", ticket);
    }

    // Check for sell signal
    if(rsiValue > RSI_Overbought)
    {
        // ERROR 5: Same MT4 OrderSend issue
        int ticket = OrderSend(Symbol(), OP_SELL, LotSize, Bid, 3, 0, 0, "RSI Sell", MagicNumber);
        if(ticket > 0)
            Print("Sell order opened: ", ticket);
    }
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print("RSI EA Deinitialized");
}
