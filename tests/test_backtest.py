import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest import (
    Candle,
    Funding,
    fill_missing_funding,
    next_entry_ts,
    resample,
    run_backtest,
    secretary_reject_count,
    size_contracts,
    target_price,
)

TZ = timezone(timedelta(hours=8))
QUARTER = 15 * 60 * 1000


def bj(year, month, day, hour=0, minute=0):
    moment = datetime(year, month, day, hour, minute, tzinfo=TZ)
    return int(moment.timestamp() * 1000)


def run(candles, fundings=None, **kwargs):
    params = dict(
        initial_equity=10_000,
        net_target=0.02,
        fee_rate=0.0002,
        bar_ms=QUARTER,
        ct_val=10,
        lot_sz=0.1,
        min_sz=0.1,
        tick_sz=0.001,
        mmr=0.01,
        first_entry_ts=bj(2026, 3, 13),
        entry_hour=0,
    )
    params.update(kwargs)
    return run_backtest(candles, fundings or [], **params)


class FundingFillTest(unittest.TestCase):
    def test_missing_settlement_uses_one_hundredth_of_a_percent(self):
        start = bj(2026, 3, 13)
        later = start + 8 * 3_600_000
        filled, assumed = fill_missing_funding([], start, later)
        self.assertGreaterEqual(assumed, 1)
        self.assertEqual(filled[0].ts, start)
        self.assertEqual(filled[0].rate, 0.0001)

    def test_recorded_rate_is_kept(self):
        start = bj(2026, 3, 13)
        slot = start + 8 * 3_600_000
        filled, assumed = fill_missing_funding([Funding(slot, 0.0005)], start, slot)
        rates = {item.ts: item.rate for item in filled}
        self.assertEqual(rates[slot], 0.0005)
        self.assertEqual(assumed, 1)
        self.assertEqual(rates[start], 0.0001)

    def test_default_funding_is_paid_by_the_long(self):
        start = bj(2026, 3, 13)
        funded = start + 8 * 3_600_000
        sell = funded + QUARTER
        fundings, _ = fill_missing_funding([], start, sell)
        result = run(
            [
                Candle(start, 5, 5.02, 4.98, 5.0),
                Candle(funded, 5, 5.02, 4.98, 5.0),
                Candle(sell, 5.0, 5.4, 4.99, 5.2),
            ],
            fundings,
        )
        cycle = result.cycles[0]
        self.assertLess(cycle.funding, -0.5)
        self.assertGreater(cycle.funding, -1.5)
        self.assertGreaterEqual(cycle.net_return, 0.02)


class ScheduleTest(unittest.TestCase):
    def test_second_day_keeps_the_clock_hour(self):
        self.assertEqual(next_entry_ts(bj(2026, 3, 13, 22, 45), 0), bj(2026, 3, 15))
        self.assertEqual(next_entry_ts(bj(2026, 3, 13), 0), bj(2026, 3, 15))
        self.assertEqual(next_entry_ts(bj(2026, 3, 13, 10), 15), bj(2026, 3, 15, 15))
        self.assertEqual(next_entry_ts(bj(2026, 3, 31, 10), 0), bj(2026, 4, 2))

    def test_size_and_target_price(self):
        contracts = size_contracts(10_000, 5, 0.0002, 10, 0.1, 0.1)
        self.assertEqual(contracts, 199.9)
        self.assertEqual(target_price(5, 1999, 10_000, 0.0002, 0, 0.02, 0.001), 5.103)


class BacktestTest(unittest.TestCase):
    def test_first_entry_uses_the_open_of_the_scheduled_bar(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.05, 4.98, 5.01),
                Candle(start + QUARTER, 5.01, 5.4, 5.0, 5.2),
            ]
        )
        self.assertEqual(len(result.cycles), 1)
        cycle = result.cycles[0]
        self.assertEqual(cycle.entry_ts, start)
        self.assertEqual(cycle.entry, 5)
        self.assertEqual(cycle.exit_price, cycle.target)
        self.assertGreaterEqual(cycle.net_return, 0.02)
        self.assertIsNone(result.open_cycle)

    def test_next_entry_is_two_beijing_days_later_at_the_same_hour(self):
        start = bj(2026, 3, 13)
        second = bj(2026, 3, 15)
        result = run(
            [
                Candle(start, 5, 5.05, 4.98, 5.01),
                Candle(start + QUARTER, 5.01, 5.4, 5.0, 5.2),
                Candle(bj(2026, 3, 14), 9, 9, 9, 9),
                Candle(second, 6, 6.05, 5.95, 6.01),
                Candle(second + QUARTER, 6.01, 6.5, 6.0, 6.2),
            ]
        )
        self.assertEqual(len(result.cycles), 2)
        self.assertEqual(result.cycles[1].entry_ts, second)
        self.assertEqual(result.cycles[1].entry, 6)
        self.assertAlmostEqual(
            result.cycles[1].equity_before, result.cycles[0].equity_after, places=6
        )
        self.assertGreaterEqual(result.cycles[1].net_return, 0.02)

    def test_entry_hour_selects_that_clock_time(self):
        midnight = bj(2026, 3, 13)
        at_eight = bj(2026, 3, 13, 8)
        result = run(
            [
                Candle(midnight, 9, 9.2, 8.8, 9),
                Candle(at_eight, 5, 5.05, 4.98, 5.01),
                Candle(at_eight + QUARTER, 5.01, 5.4, 5.0, 5.2),
            ],
            first_entry_ts=at_eight,
            entry_hour=8,
        )
        self.assertEqual(result.cycles[0].entry_ts, at_eight)
        self.assertEqual(result.cycles[0].entry, 5)
        self.assertEqual(result.next_entry_ts, bj(2026, 3, 15, 8))

    def test_underwater_position_is_not_replaced(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 4.9, 4.95),
                Candle(bj(2026, 3, 15), 4.4, 4.5, 4.2, 4.3),
                Candle(bj(2026, 3, 17), 4.2, 4.3, 4.0, 4.1),
            ]
        )
        self.assertEqual(result.cycles, [])
        self.assertIsNotNone(result.open_cycle)
        self.assertEqual(result.open_cycle.entry_ts, start)
        self.assertLess(result.final_equity, 10_000)
        self.assertIsNone(result.next_entry_ts)

    def test_gap_above_sell_fills_the_limit_price(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 4.98, 5.01),
                Candle(start + QUARTER, 6.0, 6.2, 5.9, 6.1),
            ]
        )
        cycle = result.cycles[0]
        self.assertLess(cycle.exit_price, 5.2)
        self.assertEqual(cycle.exit_price, cycle.target)
        self.assertGreaterEqual(cycle.net_return, 0.02)

    def test_funding_payment_raises_the_sell_and_still_nets_target(self):
        start = bj(2026, 3, 13)
        funded = start + QUARTER
        result = run(
            [
                Candle(start, 5, 5.02, 4.98, 5.01),
                Candle(funded, 5.05, 5.12, 5.0, 5.08),
                Candle(funded + QUARTER, 5.08, 5.6, 5.05, 5.4),
            ],
            [Funding(funded, 0.01)],
        )
        self.assertEqual(len(result.cycles), 1)
        cycle = result.cycles[0]
        self.assertEqual(cycle.exit_ts, funded + QUARTER)
        self.assertGreater(cycle.target, 5.12)
        self.assertLess(cycle.funding, 0)
        self.assertGreaterEqual(cycle.net_return, 0.02)

    def test_extreme_funding_can_liquidate(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 4.98, 5.01),
                Candle(start + QUARTER, 4.9, 4.95, 0.5, 4.7),
            ],
            [Funding(start + QUARTER, 0.2)],
        )
        self.assertEqual(result.liquidations, 1)
        self.assertEqual(result.cycles[0].status, "liquidated")
        self.assertLess(result.cycles[0].net_return, 0)

    def test_resample_keeps_complete_buckets(self):
        candles = [Candle(i * 3_600_000, 10, 12, 8, i + 1) for i in range(5)]
        out = resample(candles, 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].o, 10)
        self.assertEqual(out[0].c, 4)


def above_limit(ts):
    return Candle(ts, 6, 6.02, 5.5, 6)


class SecretaryTest(unittest.TestCase):
    def test_reject_count_is_about_one_over_e_of_the_day(self):
        self.assertEqual(secretary_reject_count(QUARTER), 35)

    def test_limit_fills_at_the_previous_entry_before_day_two(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 4.99, 5),
                Candle(start + QUARTER, 5.05, 5.2, 5.04, 5.1),
                Candle(start + 2 * QUARTER, 5.05, 5.06, 4.9, 4.95),
            ],
            entry_mode="secretary",
        )
        self.assertEqual(result.cycles[0].entry_kind, "clock")
        self.assertEqual(result.open_cycle.entry_ts, start + 2 * QUARTER)
        self.assertEqual(result.open_cycle.entry, 5)
        self.assertEqual(result.entries_limit, 1)

    def test_exit_bar_does_not_also_buy(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 4.99, 5),
                Candle(start + QUARTER, 5.05, 5.2, 4.5, 4.8),
                Candle(start + 2 * QUARTER, 5.1, 5.12, 5.05, 5.08),
            ],
            entry_mode="secretary",
        )
        self.assertEqual(len(result.cycles), 1)
        self.assertIsNone(result.open_cycle)
        self.assertEqual(result.entries_limit, 0)

    def test_secretary_buys_the_first_open_under_the_sample(self):
        start = bj(2026, 3, 13)
        day = bj(2026, 3, 15)
        candles = [
            Candle(start, 5, 5.02, 4.99, 5),
            Candle(start + QUARTER, 5.05, 5.2, 5.04, 5.1),
        ]
        ts = start + 2 * QUARTER
        while ts < day:
            candles.append(above_limit(ts))
            ts += QUARTER
        for slot in range(35):
            candles.append(above_limit(day + slot * QUARTER))
        signal = day + 35 * QUARTER
        candles.append(Candle(signal, 5.8, 5.9, 5.5, 5.85))
        result = run(candles, entry_mode="secretary")
        self.assertEqual(result.open_cycle.entry_ts, signal)
        self.assertEqual(result.open_cycle.entry, 5.8)
        self.assertEqual(result.entries_secretary, 1)
        self.assertEqual(result.entries_limit, 0)

    def test_limit_still_fills_inside_the_observation_window(self):
        start = bj(2026, 3, 13)
        day = bj(2026, 3, 15)
        candles = [
            Candle(start, 5, 5.02, 4.99, 5),
            Candle(start + QUARTER, 5.05, 5.2, 5.04, 5.1),
        ]
        ts = start + 2 * QUARTER
        while ts < day:
            candles.append(above_limit(ts))
            ts += QUARTER
        for slot in range(10):
            candles.append(above_limit(day + slot * QUARTER))
        touch = day + 10 * QUARTER
        candles.append(Candle(touch, 4.8, 4.9, 4.7, 4.75))
        result = run(candles, entry_mode="secretary")
        self.assertEqual(result.open_cycle.entry_ts, touch)
        self.assertEqual(result.open_cycle.entry, 4.8)
        self.assertEqual(result.entries_limit, 1)
        self.assertEqual(result.entries_secretary, 0)

    def test_last_bar_is_bought_when_no_open_beats_the_sample(self):
        start = bj(2026, 3, 13)
        day = bj(2026, 3, 15)
        candles = [
            Candle(start, 5, 5.02, 4.99, 5),
            Candle(start + QUARTER, 5.05, 5.2, 5.04, 5.1),
        ]
        ts = start + 2 * QUARTER
        while ts < day + 96 * QUARTER:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary")
        self.assertEqual(result.open_cycle.entry_ts, day + 95 * QUARTER)
        self.assertEqual(result.open_cycle.entry, 6)
        self.assertEqual(result.entries_secretary_last, 1)
        self.assertEqual(result.entries_secretary, 0)


if __name__ == "__main__":
    unittest.main()
