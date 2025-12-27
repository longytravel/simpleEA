#!/usr/bin/env python3
"""
OnTester Injection Script

Injects/replaces an EA's OnTester() with a profit-first custom optimization score.

The injected score keeps profit primary, while applying secondary penalties for:
- large drawdowns (max equity drawdown)
- very low trade counts (robustness proxy)
- jagged equity curves (small smoothness factor)

Usage:
    python scripts/inject_ontester.py "path/to/EA.mq5"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Tuple


# MQL5 OnTester function that returns a profit-first fitness score.
ONTESTER_CODE = r"""
//+------------------------------------------------------------------+
//| OnTester - Profit-first custom fitness (Custom max)               |
//| Score = (Profit - DD_weight*MaxEquityDD - LowTradePenalty)        |
//|         * small(PF factor) * small(Smoothness factor)             |
//| Injected by EA Stress Test System                                 |
//+------------------------------------------------------------------+
double OnTester()
{
   const int    MIN_TRADES             = 50;
   const double DD_PENALTY_WEIGHT      = 0.25;  // currency penalty per 1 currency DD
   const double LOW_TRADE_PENALTY_FRAC = 0.20;  // fraction of initial deposit
   const double PF_CAP                 = 10.0;
   const double PF_WEIGHT              = 0.05;  // 0..1, PF influence
   const double SMOOTH_WEIGHT          = 0.05;  // 0..1, smoothness influence

   double profit      = TesterStatistics(STAT_PROFIT);
   double equityDD    = TesterStatistics(STAT_EQUITY_DD);
   double equityDDpct = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   double pf          = TesterStatistics(STAT_PROFIT_FACTOR);
   int    trades      = (int)TesterStatistics(STAT_TRADES);
   double initial     = TesterStatistics(STAT_INITIAL_DEPOSIT);

   // Base score: profit is primary, drawdown reduces it
   double base = profit - (equityDD * DD_PENALTY_WEIGHT);

   // Penalize low trade counts (robustness proxy)
   double lowTradePenalty = 0.0;
   if(trades < MIN_TRADES && initial > 0.0)
      lowTradePenalty = initial * LOW_TRADE_PENALTY_FRAC * (double)(MIN_TRADES - trades) / (double)MIN_TRADES;
   base -= lowTradePenalty;

   // PF factor (mild; avoids PF dominating)
   if(pf < 0.0) pf = 0.0;
   if(pf > PF_CAP) pf = PF_CAP;
   double pfFactor = (1.0 - PF_WEIGHT) + PF_WEIGHT * (pf / PF_CAP);

   // Smoothness factor from equity curve R2 (very mild)
   double r2 = 0.0;
   HistorySelect(0, TimeCurrent());
   int deals = HistoryDealsTotal();

   if(deals >= 10)
     {
      double equity[];
      ArrayResize(equity, deals);
      double cumProfit = 0.0;
      int validDeals = 0;

      for(int i = 0; i < deals; i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket <= 0)
            continue;

         ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
         if(dealType != DEAL_TYPE_BUY && dealType != DEAL_TYPE_SELL)
            continue;

         double dealProfit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
         double dealSwap   = HistoryDealGetDouble(ticket, DEAL_SWAP);
         double dealComm   = HistoryDealGetDouble(ticket, DEAL_COMMISSION);

         cumProfit += dealProfit + dealSwap + dealComm;
         equity[validDeals] = cumProfit;
         validDeals++;
        }

      if(validDeals >= 20)
        {
         ArrayResize(equity, validDeals);

         double sumX = 0.0, sumY = 0.0;
         for(int i = 0; i < validDeals; i++)
           {
            sumX += i;
            sumY += equity[i];
           }

         double meanX = sumX / validDeals;
         double meanY = sumY / validDeals;

         double numerator = 0.0, denominator = 0.0;
         for(int i = 0; i < validDeals; i++)
           {
            numerator += (i - meanX) * (equity[i] - meanY);
            denominator += (i - meanX) * (i - meanX);
           }

         double slope = 0.0;
         if(denominator != 0.0)
            slope = numerator / denominator;
         double intercept = meanY - slope * meanX;

         double ssRes = 0.0, ssTot = 0.0;
         for(int i = 0; i < validDeals; i++)
           {
            double predicted = slope * i + intercept;
            ssRes += (equity[i] - predicted) * (equity[i] - predicted);
            ssTot += (equity[i] - meanY) * (equity[i] - meanY);
           }

         if(ssTot > 0.0)
            r2 = 1.0 - (ssRes / ssTot);
        }
     }

   if(r2 < 0.0) r2 = 0.0;
   if(r2 > 1.0) r2 = 1.0;
   double smoothFactor = (1.0 - SMOOTH_WEIGHT) + SMOOTH_WEIGHT * MathSqrt(r2);

   double score = base * pfFactor * smoothFactor;

   PrintFormat("OnTester: profit=%.2f equityDD=%.2f (%.2f%%) trades=%d PF=%.2f R2=%.3f base=%.2f score=%.2f",
               profit, equityDD, equityDDpct, trades, pf, r2, base, score);

   return score;
}
"""


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def read_source(path: Path) -> Tuple[str, str]:
    encoding = detect_encoding(path)
    return path.read_text(encoding=encoding), encoding


def has_ontester(source: str) -> bool:
    pattern = r"\bdouble\s+OnTester\s*\(\s*(void)?\s*\)"
    return bool(re.search(pattern, source))


def remove_ontester(source: str) -> str:
    func_start_pattern = (
        r"(//\+[-]+\+\s*\r?\n"
        r"//\|[^\r\n]*OnTester[^\r\n]*\r?\n"
        r"//\+[-]+\+\s*\r?\n)?"
        r"\s*double\s+OnTester\s*\(\s*(void)?\s*\)\s*\{"
    )

    match = re.search(func_start_pattern, source)
    if not match:
        return source

    start_pos = match.start()
    brace_pos = match.end() - 1  # Position of opening {

    brace_count = 1
    pos = brace_pos + 1

    while pos < len(source) and brace_count > 0:
        if source[pos] == "{":
            brace_count += 1
        elif source[pos] == "}":
            brace_count -= 1
        pos += 1

    end_pos = pos
    while end_pos < len(source) and source[end_pos] in "\n\r":
        end_pos += 1

    return source[:start_pos] + source[end_pos:]


def inject_ontester(source: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    source = remove_ontester(source).rstrip()
    injected = ONTESTER_CODE.strip("\n").replace("\n", newline)
    return f"{source}{newline}{injected}{newline}"


def process_ea(ea_path: Path) -> dict:
    if not ea_path.exists():
        return {"success": False, "error": f"File not found: {ea_path}"}

    source, encoding = read_source(ea_path)
    had_existing = has_ontester(source)

    backup_path = ea_path.with_suffix(ea_path.suffix + ".ontester.bak")
    backup_created = False
    if not backup_path.exists():
        backup_path.write_bytes(ea_path.read_bytes())
        backup_created = True

    modified_source = inject_ontester(source)
    ea_path.write_text(modified_source, encoding=encoding)

    message = (
        "Replaced existing OnTester() with profit-first (DD/smoothness-penalized) scoring"
        if had_existing
        else "Injected OnTester() with profit-first (DD/smoothness-penalized) scoring"
    )

    return {
        "success": True,
        "had_existing": had_existing,
        "injected": True,
        "message": message,
        "use_criterion": 6,  # Custom max
        "ea_path": str(ea_path),
        "backup_path": str(backup_path),
        "backup_created": backup_created,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject a profit-first OnTester() custom criterion into an EA (.mq5)"
    )
    parser.add_argument("ea_path", help="Path to EA .mq5 file")
    parser.add_argument(
        "--check-only", action="store_true", help="Only check if OnTester exists; do not modify"
    )
    args = parser.parse_args()

    ea_path = Path(args.ea_path)

    if args.check_only:
        source, _ = read_source(ea_path)
        result = {"has_ontester": has_ontester(source), "ea_path": str(ea_path)}
    else:
        result = process_ea(ea_path)

    print(json.dumps(result, indent=2))
    if not result.get("success", True):
        sys.exit(1)


if __name__ == "__main__":
    main()

