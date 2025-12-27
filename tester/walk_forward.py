"""
Walk-Forward (multi-fold) validation.

This module re-runs MT5 backtests across multiple IS/OOS folds using ONE fixed
parameter set (typically the best params from the main workflow).

It is intended as an optional "confidence booster" after Step 11 to reduce the
risk of trusting a single optimization split.
"""

from __future__ import annotations

import calendar
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from parser.report import BacktestMetrics, ReportParser
from parser.trade_extractor import extract_trades
from tester.backtest import BacktestRunner


def _parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y.%m.%d").date()


def _fmt_ymd(d: date) -> str:
    return d.strftime("%Y.%m.%d")


def _add_months(d: date, months: int) -> date:
    month = (d.month - 1) + int(months)
    year = d.year + (month // 12)
    month = (month % 12) + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass
class PeriodResult:
    success: bool
    from_date: str
    to_date: str
    report_path: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    total_commission: Optional[float] = None
    total_swap: Optional[float] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FoldResult:
    fold_index: int
    is_result: Optional[PeriodResult]
    oos_result: PeriodResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "is": self.is_result.to_dict() if self.is_result else None,
            "oos": self.oos_result.to_dict(),
        }


@dataclass
class WalkForwardResult:
    ea_name: str
    symbol: str
    timeframe: str
    from_date: str
    to_date: str
    fold_months: int
    step_months: int
    min_is_months: int
    include_is: bool
    folds: List[FoldResult]
    total_duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ea_name": self.ea_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "fold_months": self.fold_months,
            "step_months": self.step_months,
            "min_is_months": self.min_is_months,
            "include_is": self.include_is,
            "total_duration_seconds": self.total_duration_seconds,
            "folds": [f.to_dict() for f in self.folds],
        }


class WalkForwardTester:
    """
    Runs multi-fold walk-forward evaluation using fixed parameters.
    """

    def __init__(
        self,
        *,
        fold_months: int = 12,
        step_months: int = 12,
        min_is_months: int = 12,
        include_is: bool = True,
        max_folds: int = 12,
        timeout_per_run: int = 900,
        run_dir: Optional[Path] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.fold_months = int(fold_months)
        self.step_months = int(step_months)
        self.min_is_months = int(min_is_months)
        self.include_is = bool(include_is)
        self.max_folds = int(max_folds)
        self.timeout_per_run = int(timeout_per_run)
        self.run_dir = Path(run_dir) if run_dir else None
        self.inputs = inputs or {}

        self._runner = BacktestRunner(timeout=self.timeout_per_run)
        self._parser = ReportParser()

    def _run_period(
        self,
        *,
        ea_name: str,
        symbol: str,
        timeframe: str,
        from_date: str,
        to_date: str,
        run_dir: Path,
    ) -> PeriodResult:
        start = time.time()
        bt = self._runner.run(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            run_dir=run_dir,
            inputs=self.inputs,
        )

        if not bt.success or not bt.report_path:
            return PeriodResult(
                success=False,
                from_date=from_date,
                to_date=to_date,
                error=bt.error or "Backtest failed",
                duration_seconds=time.time() - start,
            )

        metrics: Optional[BacktestMetrics] = self._parser.parse(bt.report_path)
        extraction = extract_trades(str(bt.report_path))

        return PeriodResult(
            success=bool(metrics),
            from_date=from_date,
            to_date=to_date,
            report_path=str(bt.report_path),
            metrics=metrics.to_dict() if metrics else None,
            total_commission=extraction.total_commission if extraction.success else None,
            total_swap=extraction.total_swap if extraction.success else None,
            error=None if metrics else "Failed to parse report",
            duration_seconds=time.time() - start,
        )

    def _fold_windows(self, *, from_date: str, to_date: str) -> List[Tuple[str, str, str, str]]:
        start = _parse_ymd(from_date)
        end = _parse_ymd(to_date)
        if end <= start:
            return []

        folds: List[Tuple[str, str, str, str]] = []
        oos_start = _add_months(start, self.min_is_months)

        while oos_start < end and len(folds) < self.max_folds:
            is_start = start
            is_end = oos_start
            oos_end = _add_months(oos_start, self.fold_months)
            if oos_end > end:
                oos_end = end

            if is_end <= is_start or oos_end <= oos_start:
                break

            folds.append((_fmt_ymd(is_start), _fmt_ymd(is_end), _fmt_ymd(oos_start), _fmt_ymd(oos_end)))
            oos_start = _add_months(oos_start, self.step_months)

        return folds

    def test(
        self,
        *,
        ea_name: str,
        symbol: str,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> WalkForwardResult:
        start_time = time.time()
        folds = self._fold_windows(from_date=from_date, to_date=to_date)
        out: List[FoldResult] = []

        base = self.run_dir or Path.cwd()
        base.mkdir(parents=True, exist_ok=True)

        for idx, (is_from, is_to, oos_from, oos_to) in enumerate(folds, start=1):
            fold_dir = base / f"fold_{idx:02d}"
            fold_dir.mkdir(parents=True, exist_ok=True)

            is_res: Optional[PeriodResult] = None
            if self.include_is:
                is_res = self._run_period(
                    ea_name=ea_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    from_date=is_from,
                    to_date=is_to,
                    run_dir=fold_dir / "IS",
                )

            oos_res = self._run_period(
                ea_name=ea_name,
                symbol=symbol,
                timeframe=timeframe,
                from_date=oos_from,
                to_date=oos_to,
                run_dir=fold_dir / "OOS",
            )

            out.append(FoldResult(fold_index=idx, is_result=is_res, oos_result=oos_res))

        return WalkForwardResult(
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            fold_months=self.fold_months,
            step_months=self.step_months,
            min_is_months=self.min_is_months,
            include_is=self.include_is,
            folds=out,
            total_duration_seconds=time.time() - start_time,
        )

