//+------------------------------------------------------------------+
//| SymbolScanner.mq5 — Dumps ALL available broker symbols to a file |
//+------------------------------------------------------------------+
#property copyright "Hive"
#property version   "1.00"

int OnInit()
{
   int total = SymbolsTotal(false); // false = all symbols, not just Market Watch
   Print("Total symbols available: ", total);

   int h = FileOpen("all_symbols.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      for(int i = 0; i < total; i++)
      {
         string name = SymbolName(i, false);
         string desc = SymbolInfoString(name, SYMBOL_DESCRIPTION);
         FileWriteString(h, name + " | " + desc + "\n");
      }
      FileClose(h);
      Print("Symbol list written to all_symbols.txt");
   }

   // Also print to journal
   for(int j = 0; j < total; j++)
   {
      string name = SymbolName(j, false);
      if(StringFind(name, "EUR") >= 0 || StringFind(name, "GBP") >= 0 ||
         StringFind(name, "USD") >= 0 || StringFind(name, "XAU") >= 0 ||
         StringFind(name, "AUD") >= 0 || StringFind(name, "GOLD") >= 0 ||
         StringFind(name, "US30") >= 0 || StringFind(name, "JPY") >= 0)
      {
         Print("SYMBOL: ", name);
      }
   }

   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) {}
void OnTick() {}
//+------------------------------------------------------------------+
