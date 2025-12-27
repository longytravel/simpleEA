"""
Execution Stress Suite (offline)

Applies simple, trade-level stress models to an MT5 backtest report:
- Spread sensitivity (assumed baseline spread in pips, multiplied)
- Slippage sensitivity (pips per side)
- Commission / swap multipliers

This does NOT re-run MT5; it re-scores the existing trade list extracted from
the report Deals table, so it is fast and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from parser.trade_extractor import Trade


def pip_size(symbol: str) -> float:
    s = (symbol or "").upper()
    if s.endswith("JPY"):
        return 0.01
    return 0.0001


def _trade_pips(trade: Trade) -> Optional[float]:
    if not trade.entry_price or not trade.exit_price or not trade.volume:
        return None
    ps = pip_size(trade.symbol)
    if ps <= 0:
        return None
    direction = 1.0 if (trade.direction or "").lower() == "buy" else -1.0
    return ((trade.exit_price - trade.entry_price) / ps) * direction


def infer_pip_value_per_lot(trades: List[Trade]) -> Dict[str, float]:
    """
    Estimate pip value per 1.0 lot from the trade list.

    Uses gross profit (excluding commission/swap) and price move in pips:
      pip_value ~= profit / (pips * volume)
    """
    values: Dict[str, List[float]] = {}
    for t in trades:
        pips = _trade_pips(t)
        if pips is None or abs(pips) < 1e-9:
            continue
        if not t.volume:
            continue
        pv = (t.profit / (pips * t.volume)) if t.volume else None
        if pv is None:
            continue
        if not (pv == pv):  # NaN
            continue
        values.setdefault(t.symbol, []).append(abs(float(pv)))

    out: Dict[str, float] = {}
    for sym, vals in values.items():
        if vals:
            out[sym] = float(median(vals))
    return out


def _max_drawdown(trades: List[Tuple[str, float]], initial_balance: float) -> Tuple[float, float, float]:
    """
    Compute max drawdown from (time, net_profit) tuples.

    Returns: (max_dd_abs, max_dd_pct, final_balance)
    """
    ordered = sorted(trades, key=lambda x: x[0])
    balance = float(initial_balance or 0.0)
    peak = balance
    max_dd = 0.0
    max_dd_pct = 0.0

    for _, pnl in ordered:
        balance += float(pnl or 0.0)
        if balance > peak:
            peak = balance
        dd = peak - balance
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            dd_pct = (dd / peak) * 100.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    return max_dd, max_dd_pct, balance


@dataclass
class StressScenario:
    id: str
    label: str
    spread_mult: float = 1.0
    slippage_pips: float = 0.0  # per side (entry + exit)
    commission_mult: float = 1.0
    swap_mult: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_scenario(
    trades: List[Trade],
    *,
    initial_balance: float,
    baseline_spread_pips: float,
    pip_value_per_lot: Dict[str, float],
    scenario: StressScenario,
) -> Dict[str, Any]:
    """
    Apply a stress scenario to the trade list and compute key metrics.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "success": False,
            "error": "No trades",
        }

    extra_spread_pips = max(0.0, (scenario.spread_mult - 1.0) * float(baseline_spread_pips or 0.0))
    slip_roundtrip_pips = max(0.0, float(scenario.slippage_pips or 0.0)) * 2.0

    # Totals
    total_net_profit = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0

    extra_spread_cost = 0.0
    extra_slippage_cost = 0.0
    extra_commission_cost = 0.0
    extra_swap_cost = 0.0

    pnl_series: List[Tuple[str, float]] = []

    for t in trades:
        sym = t.symbol
        pv = float(pip_value_per_lot.get(sym) or 0.0)
        if pv <= 0:
            # Fallback: common FX approx (per 1 lot, in quote currency). This is only a last resort.
            pv = 10.0

        vol = float(t.volume or 0.0)
        # Spread + slippage modeled as a pure cost (always adverse).
        spread_cost = extra_spread_pips * pv * vol
        slippage_cost = slip_roundtrip_pips * pv * vol

        # Commission/swap multipliers apply on the existing commission/swap already included in net_profit.
        # Commission is typically negative.
        commission_delta = float(t.commission or 0.0) * (float(scenario.commission_mult or 1.0) - 1.0)
        swap_delta = float(t.swap or 0.0) * (float(scenario.swap_mult or 1.0) - 1.0)

        new_net = float(t.net_profit or 0.0) - spread_cost - slippage_cost + commission_delta + swap_delta

        total_net_profit += new_net
        if new_net > 0:
            gross_profit += new_net
            wins += 1
        elif new_net < 0:
            gross_loss += new_net
            losses += 1

        extra_spread_cost += spread_cost
        extra_slippage_cost += slippage_cost
        extra_commission_cost += abs(commission_delta) if commission_delta < 0 else 0.0
        extra_swap_cost += abs(swap_delta) if swap_delta < 0 else 0.0

        pnl_series.append((t.time or "", new_net))

    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else float("inf")
    win_rate = (wins / total_trades) * 100.0 if total_trades else 0.0

    max_dd, max_dd_pct, final_balance = _max_drawdown(pnl_series, initial_balance)
    roi_pct = (total_net_profit / initial_balance) * 100.0 if initial_balance else 0.0
    expected_payoff = total_net_profit / total_trades if total_trades else 0.0

    return {
        "success": True,
        "scenario": scenario.to_dict(),
        "baseline_spread_pips": float(baseline_spread_pips or 0.0),
        "metrics": {
            "total_net_profit": total_net_profit,
            "roi_pct": roi_pct,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "total_trades": total_trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": win_rate,
            "expected_payoff": expected_payoff,
            "initial_balance": float(initial_balance or 0.0),
            "final_balance": float(final_balance or 0.0),
        },
        "costs": {
            "extra_spread_cost": extra_spread_cost,
            "extra_slippage_cost": extra_slippage_cost,
            "extra_commission_cost": extra_commission_cost,
            "extra_swap_cost": extra_swap_cost,
        },
    }

