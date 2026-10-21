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
    plan_secretary3,
    plan_secretary4,
    secretary_window,
    resample,
    run_backtest,
    secretary_reject_count,
    size_contracts,
    target_price,
)
from okx_data import coin_spec
from portfolio import addon_signals, run_positions

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

    def test_spot_balance_is_not_liquidated_without_funding(self):
        start = bj(2026, 3, 13)
        result = run(
            [
                Candle(start, 5, 5.02, 0.5, 5),
                Candle(start + QUARTER, 5, 5.05, 0.4, 4.8),
            ],
            fee_rate=0.0008,
            ct_val=1,
            lot_sz=1e-8,
            min_sz=1,
            mmr=1,
        )
        self.assertEqual(result.liquidations, 0)
        self.assertEqual(result.total_funding, 0)
        self.assertGreater(result.open_cycle.coin_qty, 1900)
        self.assertLess(result.open_cycle.coin_qty, 2000)


class SecretaryDayTest(unittest.TestCase):
    def _until(self, start, day):
        candles = [
            Candle(start, 5, 5.02, 4.99, 5),
            Candle(start + QUARTER, 5.05, 5.2, 5.04, 5.1),
        ]
        ts = start + 2 * QUARTER
        while ts < day:
            candles.append(above_limit(ts))
            ts += QUARTER
        return candles

    def test_window_rejects_eighteen_of_forty_nine_bars(self):
        self.assertEqual(secretary_reject_count(QUARTER, 49), 18)

    def test_limit_still_fills_outside_the_daytime_window(self):
        start = bj(2026, 3, 13)
        candles = self._until(start, bj(2026, 3, 15, 3))
        touch = bj(2026, 3, 15, 3)
        candles.append(Candle(touch, 4.8, 4.9, 4.7, 4.75))
        result = run(candles, entry_mode="secretary2")
        self.assertEqual(result.open_cycle.entry_ts, touch)
        self.assertEqual(result.open_cycle.entry, 4.8)
        self.assertEqual(result.entries_limit, 1)

    def test_bars_before_eight_and_the_sample_do_not_buy(self):
        start = bj(2026, 3, 13)
        day = bj(2026, 3, 15)
        candles = self._until(start, day + 8 * 3_600_000)
        for slot in range(18):
            candles.append(above_limit(day + 8 * 3_600_000 + slot * QUARTER))
        result = run(candles, entry_mode="secretary2")
        self.assertIsNone(result.open_cycle)

    def test_first_open_under_the_daytime_sample_buys(self):
        start = bj(2026, 3, 13)
        day = bj(2026, 3, 15)
        candles = self._until(start, day + 8 * 3_600_000)
        for slot in range(18):
            candles.append(above_limit(day + 8 * 3_600_000 + slot * QUARTER))
        signal = day + 8 * 3_600_000 + 18 * QUARTER
        candles.append(Candle(signal, 5.8, 5.9, 5.5, 5.85))
        result = run(candles, entry_mode="secretary2")
        self.assertEqual(result.open_cycle.entry_ts, signal)
        self.assertEqual(result.open_cycle.entry, 5.8)
        self.assertEqual(result.entries_secretary, 1)

    def test_eight_pm_bar_is_bought_when_nothing_is_cheaper(self):
        start = bj(2026, 3, 13)
        end = bj(2026, 3, 15, 20)
        candles = self._until(start, end + QUARTER)
        result = run(candles, entry_mode="secretary2")
        self.assertEqual(result.open_cycle.entry_ts, end)
        self.assertEqual(result.open_cycle.entry, 6)
        self.assertEqual(result.entries_secretary_last, 1)


class SecretaryImmediateTest(unittest.TestCase):
    def _closed(self, entry, exit_ts):
        candles = [Candle(entry, 5, 5.02, 4.99, 5)]
        ts = entry + QUARTER
        while ts < exit_ts:
            candles.append(Candle(ts, 5.02, 5.05, 4.99, 5.02))
            ts += QUARTER
        candles.append(Candle(exit_ts, 5.02, 5.2, 5.0, 5.1))
        return candles

    def test_nine_am_close_uses_the_rest_of_the_same_day(self):
        exit_ts = bj(2026, 3, 13, 9)
        day, offset, bars, last, reject = plan_secretary3(exit_ts, QUARTER)
        self.assertEqual(day, bj(2026, 3, 13))
        self.assertEqual(offset, 9 * 3_600_000 + QUARTER)
        self.assertEqual(bars, 44)
        self.assertEqual(last, 20 * 3_600_000)
        self.assertEqual(reject, 16)

    def test_fewer_than_ten_bars_waits_until_the_next_morning(self):
        exit_ts = bj(2026, 3, 13, 19)
        day, offset, bars, _last, reject = plan_secretary3(exit_ts, QUARTER)
        self.assertEqual(day, bj(2026, 3, 14))
        self.assertEqual(offset, 8 * 3_600_000)
        self.assertEqual(bars, 49)
        self.assertEqual(reject, 18)
        ten = plan_secretary3(bj(2026, 3, 13, 17, 30), QUARTER)
        nine = plan_secretary3(bj(2026, 3, 13, 17, 45), QUARTER)
        self.assertEqual(ten[0], bj(2026, 3, 13))
        self.assertEqual(ten[2], 10)
        self.assertEqual(nine[0], bj(2026, 3, 14))

    def test_close_before_eight_starts_at_eight_the_same_day(self):
        day, offset, bars, _last, _reject = plan_secretary3(bj(2026, 3, 13, 1), QUARTER)
        self.assertEqual(day, bj(2026, 3, 13))
        self.assertEqual(offset, 8 * 3_600_000)
        self.assertEqual(bars, 49)

    def test_same_day_sample_does_not_buy_until_a_lower_open(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 9)
        candles = self._closed(entry, exit_ts)
        _day, offset, _bars, _last, reject = plan_secretary3(exit_ts, QUARTER)
        start = bj(2026, 3, 13) + offset
        for slot in range(reject):
            candles.append(above_limit(start + slot * QUARTER))
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertIsNone(result.open_cycle)
        signal = start + reject * QUARTER
        candles.append(Candle(signal, 5.8, 5.9, 5.5, 5.85))
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, signal)
        self.assertEqual(result.open_cycle.entry, 5.8)
        self.assertEqual(result.entries_secretary, 1)

    def test_eight_pm_of_the_same_day_is_the_last_bar(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 9)
        end = bj(2026, 3, 13, 20)
        candles = self._closed(entry, exit_ts)
        ts = exit_ts + QUARTER
        while ts <= end:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, end)
        self.assertEqual(result.entries_secretary_last, 1)

    def test_short_remainder_does_not_buy_until_the_next_day(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 19)
        candles = self._closed(entry, exit_ts)
        ts = exit_ts + QUARTER
        while ts <= bj(2026, 3, 13, 20):
            candles.append(Candle(ts, 5.7, 5.8, 5.4, 5.6))
            ts += QUARTER
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertIsNone(result.open_cycle)
        end = bj(2026, 3, 14, 20)
        while ts <= end:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, end)
        self.assertEqual(result.entries_secretary_last, 1)

    def test_limit_still_fills_before_the_daytime_window(self):
        entry = bj(2026, 3, 13)
        exit_ts = bj(2026, 3, 13, 1)
        candles = self._closed(entry, exit_ts)
        touch = bj(2026, 3, 13, 3)
        candles.append(Candle(touch, 4.8, 4.9, 4.7, 4.75))
        result = run(candles, entry_mode="secretary3", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, touch)
        self.assertEqual(result.open_cycle.entry, 4.8)
        self.assertEqual(result.entries_limit, 1)


class SecretaryRollingWindowTest(unittest.TestCase):
    def _closed(self, entry, exit_ts):
        candles = [Candle(entry, 5, 5.02, 4.99, 5)]
        ts = entry + QUARTER
        while ts < exit_ts:
            candles.append(Candle(ts, 5.02, 5.05, 4.99, 5.02))
            ts += QUARTER
        candles.append(Candle(exit_ts, 5.02, 5.2, 5.0, 5.1))
        return candles

    def test_five_minute_windows_keep_the_same_clock_span(self):
        bar = 5 * 60 * 1000
        offset, bars, last = secretary_window(bar, "secretary")
        self.assertEqual((offset, bars, last), (0, 288, 287 * bar))
        self.assertEqual(secretary_reject_count(bar, bars), 106)
        offset, bars, last = secretary_window(bar, "secretary2")
        self.assertEqual((offset, bars, last), (8 * 3_600_000, 145, 20 * 3_600_000))
        self.assertEqual(secretary_reject_count(bar, bars), 53)

    def test_secretary4_uses_thirty_two_bars_on_five_minute_candles(self):
        bar = 5 * 60 * 1000
        exit_ts = bj(2026, 3, 13, 9)
        start, window_bars, reject = plan_secretary4(exit_ts, bar)
        self.assertEqual(start, exit_ts + bar)
        self.assertEqual(window_bars, 32)
        self.assertEqual(reject, 12)
        self.assertEqual(start + (window_bars - 1) * bar, bj(2026, 3, 13, 11, 40))

    def test_window_is_thirty_two_bars_from_the_next_candle(self):
        exit_ts = bj(2026, 3, 13, 9)
        start, bars, reject = plan_secretary4(exit_ts, QUARTER)
        self.assertEqual(start, exit_ts + QUARTER)
        self.assertEqual(bars, 32)
        self.assertEqual(reject, 12)
        self.assertEqual(start + (bars - 1) * QUARTER, bj(2026, 3, 13, 17))

    def test_observation_does_not_buy_until_a_lower_open(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 9)
        candles = self._closed(entry, exit_ts)
        start, _bars, reject = plan_secretary4(exit_ts, QUARTER)
        for slot in range(reject):
            candles.append(above_limit(start + slot * QUARTER))
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertIsNone(result.open_cycle)
        signal = start + reject * QUARTER
        candles.append(Candle(signal, 5.8, 5.9, 5.5, 5.85))
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, signal)
        self.assertEqual(result.open_cycle.entry, 5.8)
        self.assertEqual(result.entries_secretary, 1)

    def test_last_bar_of_the_eight_hours_is_bought(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 9)
        candles = self._closed(entry, exit_ts)
        start, bars, _reject = plan_secretary4(exit_ts, QUARTER)
        end = start + (bars - 1) * QUARTER
        ts = start
        while ts <= end:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, end)
        self.assertEqual(result.entries_secretary_last, 1)

    def test_window_crosses_midnight_without_buying_at_midnight(self):
        entry = bj(2026, 3, 13, 18)
        exit_ts = bj(2026, 3, 13, 20)
        candles = self._closed(entry, exit_ts)
        start, bars, _reject = plan_secretary4(exit_ts, QUARTER)
        self.assertEqual(start, bj(2026, 3, 13, 20, 15))
        midnight = bj(2026, 3, 14)
        ts = start
        while ts <= midnight:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertIsNone(result.open_cycle)
        end = start + (bars - 1) * QUARTER
        self.assertEqual(end, bj(2026, 3, 14, 4))
        while ts <= end:
            candles.append(above_limit(ts))
            ts += QUARTER
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, end)
        self.assertEqual(result.entries_secretary_last, 1)

    def test_limit_fills_during_observation(self):
        entry = bj(2026, 3, 13, 8)
        exit_ts = bj(2026, 3, 13, 9)
        candles = self._closed(entry, exit_ts)
        start, _bars, _reject = plan_secretary4(exit_ts, QUARTER)
        touch = start + 3 * QUARTER
        candles.append(above_limit(start))
        candles.append(above_limit(start + QUARTER))
        candles.append(above_limit(start + 2 * QUARTER))
        candles.append(Candle(touch, 6, 6.1, 4.9, 5.5))
        result = run(candles, entry_mode="secretary4", first_entry_ts=entry)
        self.assertEqual(result.open_cycle.entry_ts, touch)
        self.assertEqual(result.open_cycle.entry, 5)
        self.assertEqual(result.entries_limit, 1)


class CoinCatalogTest(unittest.TestCase):
    def test_unknown_coin_is_rejected(self):
        with self.assertRaises(ValueError):
            coin_spec("DOGE")

    def test_pump_has_its_own_local_files(self):
        spec = coin_spec("pump")
        self.assertEqual(spec["base"], "PUMP")
        self.assertEqual(spec["swap_id"], "PUMP-USDT-SWAP")
        self.assertTrue(spec["swap_cache"].name.endswith("pump-usdt-swap-15m.json"))

    def test_hype_has_its_own_local_files(self):
        spec = coin_spec("hype")
        self.assertEqual(spec["base"], "HYPE")
        self.assertEqual(spec["swap_id"], "HYPE-USDT-SWAP")
        self.assertTrue(spec["swap_cache"].name.endswith("hype-usdt-swap-15m.json"))


class AddonTest(unittest.TestCase):
    def test_shallow_dip_does_not_open_another_book(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.2, 4.6, 5),
            Candle(start + QUARTER, 5, 5.2, 4.6, 5),
        ]
        books = run_positions(candles, [], **self._params(start))
        alone = run(candles)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0].compounded_equity, alone.compounded_equity)

    def test_ten_percent_opens_one_new_book_at_the_threshold(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.05, 4.96, 5),
            Candle(start + QUARTER, 4.6, 4.7, 4.4, 4.5),
            Candle(start + 2 * QUARTER, 4.5, 4.55, 4.45, 4.5),
        ]
        signals = addon_signals(candles, run(candles))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].level, 1)
        self.assertAlmostEqual(signals[0].price, 4.5, places=6)
        books = run_positions(candles, [], **self._params(start))
        self.assertEqual(len(books), 2)
        opened = books[1].open_cycle or books[1].cycles[0]
        self.assertAlmostEqual(opened.entry, 4.5, places=6)
        self.assertEqual(opened.equity_before, 10_000)
        self.assertEqual(books[1].cycles[0].entry_kind if books[1].cycles else "addon", "addon")

    def test_one_bar_can_open_two_books_and_a_gap_fills_at_the_open(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.05, 4.96, 5),
            Candle(start + QUARTER, 3.8, 3.9, 3.7, 3.85),
            Candle(start + 2 * QUARTER, 3.85, 3.9, 3.8, 3.85),
        ]
        signals = addon_signals(candles, run(candles))
        self.assertEqual([signal.level for signal in signals], [1, 2])
        self.assertAlmostEqual(signals[0].price, 3.8, places=6)
        self.assertAlmostEqual(signals[1].price, 3.8, places=6)
        self.assertEqual(len(run_positions(candles, [], **self._params(start))), 3)

    def test_two_thresholds_on_one_bar_keep_their_own_prices(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.05, 4.96, 5),
            Candle(start + QUARTER, 4.6, 4.65, 3.9, 4.0),
            Candle(start + 2 * QUARTER, 4.0, 4.05, 3.95, 4.0),
        ]
        signals = addon_signals(candles, run(candles))
        self.assertEqual(len(signals), 2)
        self.assertAlmostEqual(signals[0].price, 4.5, places=6)
        self.assertAlmostEqual(signals[1].price, 4.0, places=6)

    def test_entry_bar_wick_can_open_the_next_book(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.2, 4.4, 5),
            Candle(start + QUARTER, 5, 5.1, 4.9, 5),
        ]
        signals = addon_signals(candles, run(candles))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].ts, start)
        books = run_positions(candles, [], **self._params(start))
        opened = books[1].open_cycle or books[1].cycles[0]
        self.assertEqual(opened.entry_ts, start)
        self.assertAlmostEqual(opened.entry, 4.5, places=6)

    def test_new_book_uses_base_equity_after_the_first_book_compounds(self):
        start = bj(2026, 3, 13)
        reopen = bj(2026, 3, 15)
        candles = [
            Candle(start, 5, 5.05, 4.96, 5),
            Candle(start + QUARTER, 5.2, 6, 5, 5.5),
            Candle(reopen, 5, 5.05, 4.96, 5),
            Candle(reopen + QUARTER, 4.6, 4.7, 4.4, 4.5),
            Candle(reopen + 2 * QUARTER, 4.5, 4.55, 4.45, 4.5),
        ]
        books = run_positions(candles, [], **self._params(start))
        self.assertEqual(len(books), 2)
        self.assertGreater(books[0].open_cycle.equity_before, 10_000)
        self.assertEqual(books[1].open_cycle.equity_before, 10_000)
        self.assertGreater(books[1].open_cycle.contracts, 0)

    def test_drop_from_the_addon_price_does_not_open_another_book(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 10, 10.1, 9.5, 10),
            Candle(start + QUARTER, 9.2, 9.3, 8.1, 8.2),
            Candle(start + 2 * QUARTER, 8.15, 8.2, 8.1, 8.12),
        ]
        books = run_positions(candles, [], **self._params(start))
        self.assertEqual(len(books), 2)
        opened = books[1].open_cycle or books[1].cycles[0]
        self.assertAlmostEqual(opened.entry, 9, places=6)

    def test_addon_book_does_not_spawn_another_book(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.05, 4.96, 5),
            Candle(start + QUARTER, 4.6, 4.7, 4.4, 4.5),
            Candle(start + 2 * QUARTER, 5.2, 6, 5, 5.5),
            Candle(start + 3 * QUARTER, 3.2, 3.3, 3.0, 3.1),
        ]
        books = run_positions(candles, [], **self._params(start))
        self.assertEqual(len(books), 2)
        opened = books[1].open_cycle or books[1].cycles[0]
        self.assertAlmostEqual(opened.entry, 4.5, places=6)

    def test_first_fill_price_replaces_only_the_first_open(self):
        start = bj(2026, 3, 13)
        candles = [
            Candle(start, 5, 5.05, 4.9, 5),
            Candle(start + QUARTER, 4.8, 6, 4.7, 5.5),
        ]
        result = run(candles, first_fill_price=4.5)
        self.assertEqual(result.cycles[0].entry_kind, "addon")
        self.assertAlmostEqual(result.cycles[0].entry, 4.5, places=6)

    def _params(self, start):
        return dict(
            initial_equity=10_000,
            net_target=0.02,
            fee_rate=0.0002,
            bar_ms=QUARTER,
            ct_val=10,
            lot_sz=0.1,
            min_sz=0.1,
            tick_sz=0.001,
            mmr=0.01,
            first_entry_ts=start,
            entry_hour=0,
        )


if __name__ == "__main__":
    unittest.main()
