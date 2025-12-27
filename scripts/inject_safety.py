#!/usr/bin/env python3
"""
Safety Injection Script

Injects basic live-safety guards into an MQL5 EA:
- Spread filter (pips)
- Rollover window avoidance (minutes around midnight server time)
- Optional Friday close avoidance

It injects:
1) A small safety block (inputs + helper functions) at global scope
2) An early guard inside OnTick()

Usage:
  python scripts/inject_safety.py "path/to/EA.mq5"
  python scripts/inject_safety.py "path/to/EA.mq5" --check-only
  python scripts/inject_safety.py "path/to/EA.mq5" --force
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Tuple


MARKER_BEGIN = "//| EAStress Safety Guards - BEGIN"
MARKER_END = "//| EAStress Safety Guards - END"

SAFETY_BLOCK = r"""
//+------------------------------------------------------------------+
//| EAStress Safety Guards - BEGIN                                   |
//| Basic live-safety filters (spread/rollover/time)                  |
//| Injected by EA Stress Test System                                 |
//+------------------------------------------------------------------+
input bool   EAStressSafety_Enable               = true;
input double EAStressSafety_MaxSpreadPips        = 2.0;   // 0 disables
input int    EAStressSafety_AvoidRolloverMinutes = 10;    // 0 disables (minutes around 00:00 server time)
input bool   EAStressSafety_AvoidFridayClose     = true;
input int    EAStressSafety_FridayCloseHour      = 21;    // server hour

int EAStressSafety_PipPoints()
{
   return (_Digits==3 || _Digits==5) ? 10 : 1;
}

double EAStressSafety_CurrentSpreadPips()
{
   long spreadPoints = 0;
   if(!SymbolInfoInteger(_Symbol, SYMBOL_SPREAD, spreadPoints))
      spreadPoints = (long)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   return (double)spreadPoints / (double)EAStressSafety_PipPoints();
}

bool EAStressSafety_IsRolloverWindow()
{
   if(EAStressSafety_AvoidRolloverMinutes <= 0) return false;
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   int m = t.hour*60 + t.min;
   int n = EAStressSafety_AvoidRolloverMinutes;
   return (m < n) || (m >= (1440 - n));
}

bool EAStressSafety_IsFridayCloseWindow()
{
   if(!EAStressSafety_AvoidFridayClose) return false;
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(t.day_of_week != 5) return false; // Friday
   return (t.hour >= EAStressSafety_FridayCloseHour);
}

bool EAStressSafety_HasOpenPositionForSymbol()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      if(sym == _Symbol)
         return true;
     }
   return false;
}

bool EAStressSafety_AllowNewEntries()
{
   if(!EAStressSafety_Enable) return true;
   if(EAStressSafety_MaxSpreadPips > 0.0)
     {
      double sp = EAStressSafety_CurrentSpreadPips();
      if(sp > EAStressSafety_MaxSpreadPips)
         return false;
     }
   if(EAStressSafety_IsRolloverWindow()) return false;
   if(EAStressSafety_IsFridayCloseWindow()) return false;
   return true;
}
//+------------------------------------------------------------------+
//| EAStress Safety Guards - END                                     |
//+------------------------------------------------------------------+
"""

ONTICK_GUARD = r"""
   // EAStress safety guard: block new entries during unsafe conditions
   if(!EAStressSafety_AllowNewEntries() && !EAStressSafety_HasOpenPositionForSymbol())
      return;
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
    enc = detect_encoding(path)
    return path.read_text(encoding=enc, errors="ignore"), enc


def has_injection(source: str) -> bool:
    return MARKER_BEGIN in source and MARKER_END in source


def _newline(source: str) -> str:
    return "\r\n" if "\r\n" in source else "\n"


def _find_first_lifecycle_func(source: str) -> int:
    candidates = []
    for pat in [
        r"\bint\s+OnInit\s*\(\s*(void)?\s*\)\s*\{",
        r"\bvoid\s+OnTick\s*\(\s*(void)?\s*\)\s*\{",
        r"\bvoid\s+OnDeinit\s*\(\s*const\s+int\s+reason\s*\)\s*\{",
    ]:
        m = re.search(pat, source)
        if m:
            candidates.append(m.start())
    return min(candidates) if candidates else -1


def _inject_global_block(source: str) -> str:
    nl = _newline(source)
    block = SAFETY_BLOCK.strip("\n").replace("\n", nl) + nl + nl

    insert_at = _find_first_lifecycle_func(source)
    if insert_at == -1:
        return source.rstrip() + nl + nl + block
    return source[:insert_at] + block + source[insert_at:]


def _inject_into_ontick(source: str) -> str:
    nl = _newline(source)
    guard = ONTICK_GUARD.strip("\n").replace("\n", nl) + nl
    pat = r"\bvoid\s+OnTick\s*\(\s*(void)?\s*\)\s*\{"
    m = re.search(pat, source)
    if not m:
        raise ValueError("Could not find OnTick() to inject safety guard")

    brace_pos = m.end() - 1  # '{'
    out = source[: brace_pos + 1]
    out += nl + guard
    out += source[brace_pos + 1 :]
    return out


def process_ea(ea_path: Path, *, force: bool) -> dict:
    if not ea_path.exists():
        return {"success": False, "error": f"File not found: {ea_path}"}

    source, enc = read_source(ea_path)
    if has_injection(source) and not force:
        return {"success": True, "changed": False, "encoding": enc, "message": "Safety guards already present"}

    if not re.search(r"\bvoid\s+OnTick\s*\(", source):
        return {"success": False, "error": "OnTick() not found (EA may not be a standard Expert Advisor)"}

    updated = source
    if not has_injection(updated) or force:
        updated = _inject_global_block(updated)
        updated = _inject_into_ontick(updated)

    backup = ea_path.with_suffix(ea_path.suffix + ".safety.bak")
    if not backup.exists():
        backup.write_bytes(ea_path.read_bytes())

    ea_path.write_text(updated, encoding=enc)
    return {"success": True, "changed": True, "encoding": enc, "backup": str(backup)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Inject basic safety guards into an MQL5 EA")
    ap.add_argument("ea", type=str, help="Path to .mq5 file")
    ap.add_argument("--check-only", action="store_true", help="Only report whether safety is already injected")
    ap.add_argument("--force", action="store_true", help="Inject even if it looks already present")
    args = ap.parse_args()

    ea_path = Path(args.ea)
    source, _ = read_source(ea_path) if ea_path.exists() else ("", "utf-8")

    if args.check_only:
        print(
            {
                "success": ea_path.exists(),
                "path": str(ea_path),
                "has_safety": has_injection(source) if ea_path.exists() else False,
                "has_ontick": bool(re.search(r"\bvoid\s+OnTick\s*\(", source)) if ea_path.exists() else False,
            }
        )
        return

    res = process_ea(ea_path, force=args.force)
    print(res)


if __name__ == "__main__":
    main()
