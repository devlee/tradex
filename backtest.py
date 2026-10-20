"""NEAR 永续 1 倍周期的回测。

进场有两种。钟点：第一笔用起点日期的进场钟点，之后每笔用上一笔平仓日
（北京时间）之后第 2 天的同一个钟点，成交价是该钟点这根 K 线的开盘价。
秘书：第一笔仍用起点钟点。一笔结束后立刻在该笔买价挂限价单，价格回到
这个买价或更低就成交。到平仓日之后第 2 个北京日仍未成交时，把这一天的
15 分钟开盘价当作秘书问题的候选人：先看前 1/e 根，只记最低开盘价；
其后第一根开盘价低于这个最低价就买入；到最后一根还没有，就买最后一根。
限价单在这一天仍然有效，先碰到买价就按限价成交。
秘书问题2相同，但候选人只有北京时间 8:00 到 20:00 的 K 线，20:00 那根是末根。
限价单不受这个时段限制。

出场：卖出价让整笔账户在扣掉开平手续费和已发生资金费之后，净收益达到目标。
价格向上取到最小报价单位。持仓期间不因下跌卖出。资金费结算后重算卖价。
最高价触及卖价就按卖价成交。平仓后的现金是下一笔本金。

同一根 K 线不既买又卖。同一根里如果既碰到强平价又碰到卖价，按强平处理。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SHANGHAI_OFFSET_MS = 8 * 3_600_000
DAY_MS = 86_400_000
ENTRY_DELAY_DAYS = 2
FUNDING_INTERVAL_MS = 8 * 3_600_000
DEFAULT_FUNDING_RATE = 0.0001


@dataclass(frozen=True)
class Candle:
    ts: int
    o: float
    h: float
    l: float
    c: float


@dataclass(frozen=True)
class Funding:
    ts: int
    rate: float


@dataclass
class Cycle:
    status: str
    entry_ts: int
    exit_ts: int
    entry: float
    target: float
    initial_target: float
    exit_price: float
    contracts: float
    coin_qty: float
    equity_before: float
    equity_after: float
    fees: float
    funding: float
    net_pnl: float
    net_return: float
    hold_hours: float
    mae_return: float
    entry_kind: str = "clock"


@dataclass
class OpenCycle:
    entry_ts: int
    entry: float
    target: float
    initial_target: float
    contracts: float
    coin_qty: float
    equity_before: float
    last_price: float
    equity: float
    upl: float
    fees: float
    funding: float
    hold_hours: float
    mae_return: float


@dataclass
class EquityPoint:
    ts: int
    equity: float
    cash: float


@dataclass
class BacktestResult:
    cycles: list[Cycle] = field(default_factory=list)
    open_cycle: OpenCycle | None = None
    curve: list[EquityPoint] = field(default_factory=list)
    final_equity: float = 0.0
    final_cash: float = 0.0
    compounded_equity: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_ts: int | None = None
    worst_mae: float = 0.0
    total_fees: float = 0.0
    total_funding: float = 0.0
    liquidations: int = 0
    note: str | None = None
    next_entry_ts: int | None = None
    entries_limit: int = 0
    entries_secretary: int = 0
    entries_secretary_last: int = 0


@dataclass
class _Position:
    entry_ts: int
    entry: float
    contracts: float
    coin_qty: float
    equity_before: float
    fee_in: float
    funding_pnl: float
    initial_target: float
    target: float
    worst_equity: float
    entry_kind: str = "clock"


def ceil_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    steps = math.ceil(price / tick - 1e-9)
    return round(steps * tick, 8)


def size_contracts(
    equity: float,
    price: float,
    fee_rate: float,
    ct_val: float,
    lot_sz: float,
    min_sz: float,
) -> float:
    """1 倍下，合约张数向下取整，并留出开仓手续费。"""
    if equity <= 0 or price <= 0 or ct_val <= 0 or lot_sz <= 0:
        return 0.0
    raw = equity / (ct_val * price * (1 + fee_rate))
    steps = math.floor(raw / lot_sz + 1e-9)
    contracts = round(steps * lot_sz, 8)
    if contracts + 1e-12 < min_sz:
        return 0.0
    return contracts


def target_price(
    entry: float,
    coin_qty: float,
    equity_before: float,
    fee_rate: float,
    funding_pnl: float,
    net_target: float,
    tick: float,
) -> float:
    """反推卖出价，使平仓后的现金不少于开仓前权益 × (1 + 净目标)。

    资金费收支 funding_pnl 为正表示已经收到，为负表示已经付出。
    """
    raw = (
        entry * (1 + fee_rate) + (net_target * equity_before - funding_pnl) / coin_qty
    ) / (1 - fee_rate)
    price = ceil_tick(raw, tick)
    fee_in = coin_qty * entry * fee_rate
    for _ in range(6):
        cash_end = (
            equity_before
            - fee_in
            + funding_pnl
            + coin_qty * (price - entry)
            - coin_qty * price * fee_rate
        )
        if cash_end >= equity_before * (1 + net_target) - 1e-6:
            return price
        price = round(price + tick, 8)
    return price


def liquidation_price(cash: float, coin_qty: float, entry: float, mmr: float) -> float:
    """权益降到维持保证金时的价格。结果小于等于 0 表示当前保证金下到不了强平。"""
    denom = coin_qty * (mmr - 1)
    if denom == 0:
        return 0.0
    return (cash - coin_qty * entry) / denom


def beijing_day_start(ts_ms: int) -> int:
    """ts 所在北京时间日期的 0 点，返回 UTC 毫秒。"""
    shifted = ts_ms + SHANGHAI_OFFSET_MS
    return shifted - (shifted % DAY_MS) - SHANGHAI_OFFSET_MS


def scheduled_entry(day_start_ms: int, hour: int) -> int:
    return day_start_ms + hour * 3_600_000


def next_entry_ts(exit_ts: int, hour: int, delay_days: int = ENTRY_DELAY_DAYS) -> int:
    """平仓日之后第 delay_days 天的进场钟点。"""
    return scheduled_entry(beijing_day_start(exit_ts) + delay_days * DAY_MS, hour)


def secretary_reject_count(bar_ms: int, bars: int | None = None) -> int:
    """先观察、不买的 K 线数，约为候选根数 / e。"""
    count = DAY_MS // bar_ms if bars is None else bars
    return max(1, round(count / math.e))


def secretary_window(bar_ms: int, entry_mode: str) -> tuple[int, int, int]:
    """返回窗口起点偏移、候选根数、最后一根的开盘偏移。秘书问题2是北京时间 8:00 到 20:00。"""
    if entry_mode == "secretary2":
        start = 8 * 3_600_000
        last = 20 * 3_600_000
        bars = (last - start) // bar_ms + 1
        return start, bars, last
    bars = DAY_MS // bar_ms
    return 0, bars, (bars - 1) * bar_ms


def fill_missing_funding(
    fundings: list[Funding],
    start_ms: int,
    end_ms: int,
    default_rate: float = DEFAULT_FUNDING_RATE,
) -> tuple[list[Funding], int]:
    """没有记录的 8 小时结算用 default_rate。返回补全后的序列和补上的次数。"""
    known = {item.ts: item.rate for item in fundings}
    slot = start_ms - (start_ms % FUNDING_INTERVAL_MS)
    if slot < start_ms:
        slot += FUNDING_INTERVAL_MS
    assumed = 0
    while slot <= end_ms:
        if slot not in known:
            known[slot] = default_rate
            assumed += 1
        slot += FUNDING_INTERVAL_MS
    filled = [
        Funding(ts, rate)
        for ts, rate in sorted(known.items())
        if start_ms <= ts <= end_ms
    ]
    return filled, assumed


def resample(candles: list[Candle], hours: int) -> list[Candle]:
    if hours <= 1:
        return list(candles)
    bucket_ms = hours * 3_600_000
    groups: dict[int, list[Candle]] = {}
    for candle in candles:
        bucket = candle.ts - (candle.ts % bucket_ms)
        groups.setdefault(bucket, []).append(candle)
    out: list[Candle] = []
    need = hours
    for bucket, rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda item: item.ts)
        if len(rows) != need:
            continue
        if rows[-1].ts - rows[0].ts != (need - 1) * 3_600_000:
            continue
        out.append(
            Candle(
                ts=bucket,
                o=rows[0].o,
                h=max(row.h for row in rows),
                l=min(row.l for row in rows),
                c=rows[-1].c,
            )
        )
    return out


def _equity(cash: float, position: _Position | None, price: float) -> float:
    if position is None:
        return cash
    return cash + position.coin_qty * (price - position.entry)


def _close_cycle(
    position: _Position,
    cash: float,
    fill: float,
    exit_ts: int,
    fee_rate: float,
    status: str,
) -> tuple[float, Cycle]:
    exit_fee = position.coin_qty * fill * fee_rate
    cash = round(cash + position.coin_qty * (fill - position.entry) - exit_fee, 8)
    if status == "liquidated" and cash < 0:
        cash = 0.0
    equity_after = cash
    net_pnl = equity_after - position.equity_before
    cycle = Cycle(
        status=status,
        entry_ts=position.entry_ts,
        exit_ts=exit_ts,
        entry=position.entry,
        target=position.target,
        initial_target=position.initial_target,
        exit_price=fill,
        contracts=position.contracts,
        coin_qty=position.coin_qty,
        equity_before=position.equity_before,
        equity_after=equity_after,
        fees=position.fee_in + exit_fee,
        funding=position.funding_pnl,
        net_pnl=net_pnl,
        net_return=net_pnl / position.equity_before if position.equity_before else 0.0,
        hold_hours=(exit_ts - position.entry_ts) / 3_600_000,
        mae_return=(position.worst_equity - position.equity_before) / position.equity_before,
        entry_kind=position.entry_kind,
    )
    return cash, cycle


def run_backtest(
    candles: list[Candle],
    fundings: list[Funding],
    *,
    initial_equity: float,
    net_target: float,
    fee_rate: float,
    bar_ms: int,
    ct_val: float,
    lot_sz: float,
    min_sz: float,
    tick_sz: float,
    mmr: float,
    first_entry_ts: int,
    entry_hour: int,
    entry_delay_days: int = ENTRY_DELAY_DAYS,
    tiers: list[tuple[float, float, float]] | None = None,
    record_curve: bool = True,
    entry_mode: str = "clock",
) -> BacktestResult:
    candles = sorted(
        (c for c in candles if c.o > 0 and c.h > 0 and c.l > 0 and c.c > 0),
        key=lambda c: c.ts,
    )
    fundings = sorted(fundings, key=lambda f: f.ts)
    result = BacktestResult(
        final_equity=initial_equity,
        final_cash=initial_equity,
        compounded_equity=initial_equity,
    )
    if len(candles) < 2:
        result.note = "K 线不足，无法完成一次开仓和平仓。"
        return result
    if not 0 <= fee_rate < 1:
        result.note = "手续费率需要在 0 和 1 之间。"
        return result
    if net_target <= 0:
        result.note = "净目标需要大于 0。"
        return result
    if not 0 <= entry_hour <= 23:
        result.note = "进场钟点需要在 0 到 23 之间。"
        return result
    if entry_mode not in ("clock", "secretary", "secretary2"):
        result.note = "进场方式只能是钟点或秘书问题。"
        return result

    cash = float(initial_equity)
    position: _Position | None = None
    scheduled: int | None = first_entry_ts
    limit_price: float | None = None
    secretary_day: int | None = None
    sample_min: float | None = None
    window_from, window_bars, window_last = secretary_window(bar_ms, entry_mode)
    reject_bars = secretary_reject_count(bar_ms, window_bars)
    funding_index = 0
    peak = cash
    blocked = False
    last_close = candles[0].c

    def maintenance(contracts: float) -> float:
        if not tiers:
            return mmr
        for min_sz, max_sz, rate in tiers:
            if min_sz <= contracts <= max_sz + 1e-9:
                return rate
        return tiers[-1][2]

    def take_fundings(bar: Candle) -> list[Funding]:
        nonlocal funding_index
        events: list[Funding] = []
        bar_end = bar.ts + bar_ms
        while funding_index < len(fundings) and fundings[funding_index].ts < bar_end:
            events.append(fundings[funding_index])
            funding_index += 1
        return events

    def arm_after_exit(exit_ts: int, entry_price: float) -> None:
        nonlocal scheduled, limit_price, secretary_day, sample_min
        if entry_mode in ("secretary", "secretary2"):
            scheduled = None
            limit_price = entry_price
            secretary_day = beijing_day_start(exit_ts) + entry_delay_days * DAY_MS
            sample_min = None
        else:
            limit_price = None
            secretary_day = None
            scheduled = next_entry_ts(exit_ts, entry_hour, entry_delay_days)

    def open_position(price: float, kind: str) -> None:
        nonlocal cash, position, scheduled, limit_price, blocked
        contracts = size_contracts(cash, price, fee_rate, ct_val, lot_sz, min_sz)
        if contracts <= 0:
            result.note = "余额不够最小下单量，后面不再开新仓。"
            blocked = True
            scheduled = None
            limit_price = None
            return
        coin_qty = round(contracts * ct_val, 8)
        fee_in = round(coin_qty * price * fee_rate, 8)
        equity_before = cash
        cash = round(cash - fee_in, 8)
        target = target_price(
            price, coin_qty, equity_before, fee_rate, 0.0, net_target, tick_sz
        )
        position = _Position(
            entry_ts=bar.ts,
            entry=price,
            contracts=contracts,
            coin_qty=coin_qty,
            equity_before=equity_before,
            fee_in=fee_in,
            funding_pnl=0.0,
            initial_target=target,
            target=target,
            worst_equity=cash,
            entry_kind=kind,
        )
        if bar.l < price:
            position.worst_equity = min(
                position.worst_equity, _equity(cash, position, bar.l)
            )
        scheduled = None
        limit_price = None
        if kind == "limit":
            result.entries_limit += 1
        elif kind == "secretary":
            result.entries_secretary += 1
        elif kind == "secretary_last":
            result.entries_secretary_last += 1

    def consider_secretary(candle: Candle) -> None:
        nonlocal sample_min
        if limit_price is None or secretary_day is None:
            return
        if candle.l <= limit_price:
            fill = candle.o if candle.o <= limit_price else limit_price
            open_position(fill, "limit")
            return
        day = beijing_day_start(candle.ts)
        if day < secretary_day:
            return
        if day > secretary_day:
            open_position(candle.o, "secretary_last")
            return
        if candle.ts < day + window_from:
            return
        if candle.ts > day + window_last:
            open_position(candle.o, "secretary_last")
            return
        slot = (candle.ts - day - window_from) // bar_ms
        if slot < reject_bars:
            sample_min = candle.o if sample_min is None else min(sample_min, candle.o)
            return
        if slot < window_bars - 1 and sample_min is not None and candle.o < sample_min:
            open_position(candle.o, "secretary")
            return
        if slot >= window_bars - 1:
            open_position(candle.o, "secretary_last")

    for bar in candles:
        just_closed = False
        if position is not None:
            for event in take_fundings(bar):
                if position.entry_ts < event.ts:
                    mark = bar.o if event.ts >= bar.ts else last_close
                    payment = round(-position.coin_qty * mark * event.rate, 8)
                    cash = round(cash + payment, 8)
                    position.funding_pnl = round(position.funding_pnl + payment, 8)
                    position.target = target_price(
                        position.entry,
                        position.coin_qty,
                        position.equity_before,
                        fee_rate,
                        position.funding_pnl,
                        net_target,
                        tick_sz,
                    )
            if bar.ts != position.entry_ts:
                liq = liquidation_price(
                    cash,
                    position.coin_qty,
                    position.entry,
                    maintenance(position.contracts),
                )
                if liq > 0 and bar.l <= liq:
                    fill = bar.o if liq >= bar.o else liq
                    position.worst_equity = min(
                        position.worst_equity,
                        _equity(cash, position, fill),
                    )
                    bought = position.entry
                    cash, cycle = _close_cycle(
                        position, cash, fill, bar.ts, fee_rate, "liquidated"
                    )
                    result.cycles.append(cycle)
                    result.liquidations += 1
                    position = None
                    just_closed = True
                    arm_after_exit(bar.ts, bought)
                else:
                    position.worst_equity = min(
                        position.worst_equity,
                        _equity(cash, position, bar.l),
                    )
                    if bar.h + 1e-9 >= position.target:
                        bought = position.entry
                        cash, cycle = _close_cycle(
                            position, cash, position.target, bar.ts, fee_rate, "target"
                        )
                        result.cycles.append(cycle)
                        position = None
                        just_closed = True
                        arm_after_exit(bar.ts, bought)
        else:
            take_fundings(bar)

        if position is None and not just_closed and not blocked:
            if entry_mode in ("secretary", "secretary2") and limit_price is not None:
                consider_secretary(bar)
            elif scheduled is not None:
                if bar.ts > scheduled:
                    late = bar.ts - scheduled
                    scheduled += ((late + DAY_MS - 1) // DAY_MS) * DAY_MS
                if bar.ts == scheduled:
                    open_position(bar.o, "clock")

        last_close = bar.c
        mark = _equity(cash, position, bar.c)
        if record_curve:
            result.curve.append(EquityPoint(bar.ts, mark, cash))
        if mark > peak:
            peak = mark
        if peak > 0:
            drawdown = (peak - mark) / peak
            if drawdown > result.max_drawdown:
                result.max_drawdown = drawdown
                result.max_drawdown_ts = bar.ts

    last = candles[-1]
    result.final_cash = cash
    result.final_equity = _equity(cash, position, last.c)
    result.total_fees = sum(cycle.fees for cycle in result.cycles)
    result.total_funding = sum(cycle.funding for cycle in result.cycles)
    if position is not None:
        result.total_fees += position.fee_in
        result.total_funding += position.funding_pnl
        result.compounded_equity = position.equity_before
        result.open_cycle = OpenCycle(
            entry_ts=position.entry_ts,
            entry=position.entry,
            target=position.target,
            initial_target=position.initial_target,
            contracts=position.contracts,
            coin_qty=position.coin_qty,
            equity_before=position.equity_before,
            last_price=last.c,
            equity=result.final_equity,
            upl=position.coin_qty * (last.c - position.entry),
            fees=position.fee_in,
            funding=position.funding_pnl,
            hold_hours=(last.ts + bar_ms - position.entry_ts) / 3_600_000,
            mae_return=(position.worst_equity - position.equity_before)
            / position.equity_before,
        )
        result.worst_mae = result.open_cycle.mae_return
    else:
        result.compounded_equity = cash
        result.next_entry_ts = secretary_day if limit_price is not None else scheduled

    mae_values = [cycle.mae_return for cycle in result.cycles]
    if result.open_cycle is not None:
        mae_values.append(result.open_cycle.mae_return)
    if mae_values:
        result.worst_mae = min(mae_values)
    return result
