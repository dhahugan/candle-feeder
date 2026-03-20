//+------------------------------------------------------------------+
//| CandleExporter.mq5 — Dedicated candlestick data exporter         |
//|                                                                    |
//| Exports candle data for ALL symbols across ALL timeframes to JSON  |
//| files in the MQL5/Files directory. Runs every 5 seconds.          |
//|                                                                    |
//| This EA does NOT trade — it only reads and exports price data.    |
//| Designed to run on a dedicated OANDA demo account.                |
//+------------------------------------------------------------------+
#property copyright "Hive Trading System"
#property version   "1.00"
#property description "Candlestick data exporter — no trading, data only"

// How many candles to export per symbol/timeframe
input int CandlesPerExport = 500;

// Export interval in seconds
input int ExportIntervalSeconds = 5;

// Symbols to export (comma-separated, empty = use predefined list)
input string CustomSymbols = "";

datetime lastExport = 0;

//+------------------------------------------------------------------+
//| Get the list of symbols to export                                 |
//+------------------------------------------------------------------+
void GetSymbols(string &symbols[])
{
   if(CustomSymbols != "")
   {
      // Use custom symbol list
      StringSplit(CustomSymbols, ',', symbols);
      for(int j = 0; j < ArraySize(symbols); j++)
      {
         StringTrimLeft(symbols[j]);
         StringTrimRight(symbols[j]);
      }
      return;
   }

   // OANDA uses .sml suffix for some symbols, standard names for others
   // Confirmed mapping from SymbolScanner:
   //   EURUSD.sml, GBPUSD.sml, USDJPY.sml, AUDUSD.sml, GBPJPY.sml, XAUUSD.sml
   //   USDCHF, USDCAD, NZDUSD, EURJPY, US30 (no suffix)
   string defaults[] = {
      "EURUSD.sml", "GBPUSD.sml", "USDJPY.sml", "USDCHF", "USDCAD",
      "AUDUSD.sml", "NZDUSD", "EURJPY", "GBPJPY.sml", "XAUUSD.sml", "US30"
   };
   ArrayResize(symbols, ArraySize(defaults));
   for(int k = 0; k < ArraySize(defaults); k++)
      symbols[k] = defaults[k];
}

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("CandleExporter EA initialized");
   Print("Export interval: ", ExportIntervalSeconds, "s");
   Print("Candles per export: ", CandlesPerExport);

   // Enable all symbols for data access
   string symbols[];
   GetSymbols(symbols);
   for(int i = 0; i < ArraySize(symbols); i++)
   {
      if(SymbolInfoInteger(symbols[i], SYMBOL_EXIST))
      {
         SymbolSelect(symbols[i], true);
         Print("Symbol enabled: ", symbols[i]);
      }
      else
         Print("Symbol NOT FOUND: ", symbols[i]);
   }

   // Do first export immediately
   ExportAllCandles();

   EventSetTimer(ExportIntervalSeconds);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("CandleExporter EA stopped");
}

//+------------------------------------------------------------------+
//| Timer event — export candles periodically                         |
//+------------------------------------------------------------------+
void OnTimer()
{
   ExportAllCandles();
}

//+------------------------------------------------------------------+
//| Export candles for all symbols and timeframes                      |
//+------------------------------------------------------------------+
void ExportAllCandles()
{
   string symbols[];
   GetSymbols(symbols);

   ENUM_TIMEFRAMES periods[] = {
      PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4, PERIOD_D1
   };
   string p_names[] = {"M5", "M15", "H1", "H4", "D1"};

   int exported = 0;
   int failed = 0;

   for(int s = 0; s < ArraySize(symbols); s++)
   {
      string symbol = symbols[s];
      if(!SymbolInfoInteger(symbol, SYMBOL_EXIST))
         continue;

      for(int p = 0; p < ArraySize(periods); p++)
      {
         MqlRates rates[];
         ArraySetAsSeries(rates, false);  // Oldest first (ascending)

         int copied = CopyRates(symbol, periods[p], 0, CandlesPerExport, rates);

         if(copied > 0)
         {
            // Strip broker suffixes (.sml, .tml, etc.) for canonical filename
            string clean_symbol = symbol;
            int dot_pos = StringFind(clean_symbol, ".");
            if(dot_pos > 0)
               clean_symbol = StringSubstr(clean_symbol, 0, dot_pos);
            string fname = clean_symbol + "_" + p_names[p] + ".json";
            int h = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI);
            if(h != INVALID_HANDLE)
            {
               // Build JSON array
               string data = "[";
               for(int i = 0; i < copied; i++)
               {
                  if(i > 0) data += ",";

                  // Format datetime as "YYYY.MM.DD HH:MM"
                  string dt = TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES);

                  // Use appropriate decimal precision
                  int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

                  data += "{";
                  data += "\"datetime\":\"" + dt + "\",";
                  data += "\"open\":" + DoubleToString(rates[i].open, digits) + ",";
                  data += "\"high\":" + DoubleToString(rates[i].high, digits) + ",";
                  data += "\"low\":" + DoubleToString(rates[i].low, digits) + ",";
                  data += "\"close\":" + DoubleToString(rates[i].close, digits) + ",";
                  data += "\"volume\":" + IntegerToString(rates[i].tick_volume);
                  data += "}";
               }
               data += "]";

               FileWriteString(h, data);
               FileClose(h);
               exported++;
            }
            else
            {
               Print("ERROR: Cannot write ", fname);
               failed++;
            }
         }
         else
         {
            // CopyRates returned 0 or error
            if(copied < 0)
               Print("ERROR: CopyRates failed for ", symbol, " ", p_names[p], ": ", GetLastError());
            failed++;
         }
      }
   }

   // Log summary (not every cycle — every 60s)
   static datetime lastLog = 0;
   if(TimeCurrent() - lastLog >= 60)
   {
      Print("CandleExporter: ", exported, " files exported, ", failed, " failed");
      lastLog = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Tick event — not used (timer-based export only)                   |
//+------------------------------------------------------------------+
void OnTick()
{
   // No-op — all work is done in OnTimer
}
//+------------------------------------------------------------------+
