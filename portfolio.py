"""仓位1被套时，用起始资金另开独立账本。"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from backtest import BacktestResult, Candle, run_backtest

ADDON_STEP = 0.10
ADDON_MAX_LEVELS = 9


@dataclass(frozen=True)
class AddonSignal:
    ts: int
    price: float
    level: int


def _spans(result: BacktestResult) -> list[tuple[int, int | None, float]]:
    spans = [(cycle.entry_ts, cycle.exit_ts, cycle.entry) for cycle in result.cycles]
    if result.open_cycle is not None:
        spans.append((result.open_cycle.entry_ts, None, result.open_cycle.entry))
    return spans


def addon_signals(
    candles: list[Candle],
    result: BacktestResult,
    step: float = ADDON_STEP,
    max_levels: int = ADDON_MAX_LEVELS,
) -> list[AddonSignal]:
    """只看仓位1。档位按这笔开仓价的 10%、20% 计算，不按仓位2的价格再往下加。"""
    signals: list[AddonSignal] = []
    for entry_ts, exit_ts, entry in _spans(result):
        if entry <= 0:
            continue
        fired = 0
        for candle in candles:
            if candle.ts < entry_ts:
                continue
            if exit_ts is not None and candle.ts > exit_ts:
                break
            while fired < max_levels:
                threshold = entry * (1 - step * (fired + 1))
                if threshold <= 0:
                    fired = max_levels
                    break
                if candle.l > threshold:
                    break
                fill = candle.o if candle.o <= threshold else threshold
                signals.append(AddonSignal(candle.ts, fill, fired + 1))
                fired += 1
    return signals


def run_positions(candles: list[Candle], fundings, **kwargs) -> list[BacktestResult]:
    """先跑仓位1，再为每个信号用同一套规则和起始资金另开一笔。"""
    primary = run_backtest(candles, fundings, **kwargs)
    books = [primary]
    if not primary.cycles and primary.open_cycle is None:
        return books
    times = [candle.ts for candle in candles]
    for signal in addon_signals(candles, primary):
        start = bisect.bisect_left(times, signal.ts)
        sliced = candles[start:]
        if len(sliced) < 2:
            continue
        child_kwargs = dict(kwargs)
        child_kwargs["first_entry_ts"] = signal.ts
        child_kwargs["first_fill_price"] = signal.price
        child = run_backtest(sliced, fundings, **child_kwargs)
        if child.cycles or child.open_cycle is not None:
            books.append(child)
    return books


def combined_curve(books: list[BacktestResult]):
    """按时间把已经开出的仓位加总。还没开出的仓位在那根 K 线记 0。"""
    if not books or not books[0].curve:
        return [], 0.0, None
    maps = [{point.ts: point for point in book.curve} for book in books]
    series = []
    peak = 0.0
    worst = 0.0
    worst_ts = None
    for point in books[0].curve:
        equity = 0.0
        cash = 0.0
        for mapping in maps:
            item = mapping.get(point.ts)
            if item is None:
                continue
            equity += item.equity
            cash += item.cash
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        if drawdown > worst:
            worst = drawdown
            worst_ts = point.ts
        series.append((point.ts, equity, cash))
    return series, worst, worst_ts
