import inspect
import json
import unittest
from io import BytesIO
from unittest.mock import patch

from live import runner, strategy
from live.client import HOST, LiveClient
from live.strategy import (
    BAR_MS,
    accept_birth,
    cash_shortfall,
    close_position,
    decide,
    fresh_book,
)


def candle(ts, open_px, low=None, high=None, close=None):
    low = open_px if low is None else low
    high = open_px if high is None else high
    close = open_px if close is None else close
    return {"ts": ts, "o": open_px, "h": high, "l": low, "c": close}


def view(ts, open_px, available=10_000, contracts=0, **extra):
    payload = {
        "now_ms": ts,
        "candle": candle(ts, open_px),
        "available": available,
        "contracts": contracts,
        "orders": {},
        "last": open_px,
    }
    payload.update(extra)
    return payload


class StartupTest(unittest.TestCase):
    def test_first_limit_uses_the_current_open(self):
        book = fresh_book(1)
        actions = decide(book, view(1_000, 5))
        self.assertFalse(book["awaiting_first"])
        self.assertEqual(book["signals"][0]["price"], 5)
        self.assertEqual(actions[0]["op"], "place_limit")
        self.assertEqual(actions[0]["contracts"], 199.9)
        book["signals"][0]["cl_id"] = "b1"
        again = decide(book, view(1_000 + BAR_MS, 5.2))
        self.assertEqual(len(book["signals"]), 1)
        self.assertEqual(again, [])

    def test_short_balance_keeps_the_signal(self):
        book = fresh_book(1)
        actions = decide(book, view(1_000, 5, available=9_999))
        self.assertEqual(actions, [])
        self.assertEqual(book["signals"][0]["price"], 5)
        self.assertIsNone(book["signals"][0]["cl_id"])
        self.assertEqual(cash_shortfall(book, view(1_000, 5, available=1_000)), 9_000)


class PartialTest(unittest.TestCase):
    def test_market_remainder_waits_one_extra_bar(self):
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["signals"] = [{
            "id": "startup:0:5",
            "kind": "startup",
            "price": 5,
            "bar_ts": 0,
            "equity": 10_000,
            "cl_id": "b1",
            "partial_bar": None,
        }]
        order = {"side": "buy", "accFillSz": "1", "sz": "2", "px": "5"}
        first = decide(book, view(0, 5, orders={"b1": order}, last=5))
        self.assertEqual(book["signals"][0]["partial_bar"], 0)
        self.assertFalse(any(item["op"] == "market_remainder" for item in first))
        mid = decide(book, view(BAR_MS, 5, orders={"b1": order}, last=5))
        self.assertFalse(any(item["op"] == "market_remainder" for item in mid))
        ready = decide(book, view(2 * BAR_MS, 5, orders={"b1": order}, last=5))
        market = next(item for item in ready if item["op"] == "market_remainder")
        self.assertEqual(market["contracts"], 1)
        self.assertEqual(market["cancel_id"], "b1")

    def test_remainder_waits_for_cash(self):
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["signals"] = [{
            "id": "startup:0:5",
            "kind": "startup",
            "price": 5,
            "bar_ts": 0,
            "equity": 10_000,
            "cl_id": "b1",
            "partial_bar": 0,
        }]
        order = {"side": "buy", "accFillSz": "1", "sz": "2", "px": "5"}
        actions = decide(book, view(2 * BAR_MS, 5, available=1, orders={"b1": order}, last=5))
        self.assertFalse(any(item["op"] == "market_remainder" for item in actions))
        self.assertEqual(book["signals"][0]["cl_id"], "b1")


class WindowTest(unittest.TestCase):
    def test_close_arms_thirty_two_bars_and_keeps_the_entry_limit(self):
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["position"] = {
            "entry": 5,
            "contracts": 100,
            "coin_qty": 100,
            "equity_before": 10_000,
            "funding_pnl": 0,
            "target": 5.2,
            "sell_id": "s1",
            "entry_ts": 0,
        }
        ended = close_position(book, 0, 5.1)
        self.assertGreater(ended, 10_000)
        self.assertLess(ended, 10_200)
        self.assertEqual(book["secretary_start"], BAR_MS)
        self.assertEqual(book["window_bars"], 32)
        self.assertEqual(book["reject_bars"], 12)
        self.assertEqual(book["signals"][0]["kind"], "limit")
        self.assertEqual(book["signals"][0]["price"], 5)
        actions = decide(book, view(0, 5.1, available=20_000))
        self.assertEqual(actions[0]["op"], "place_limit")
        self.assertEqual(actions[0]["kind"], "limit")
        self.assertEqual(actions[0]["price"], 5)

    def test_observation_does_not_buy_and_the_next_window_starts_on_the_following_bar(self):
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["position"] = {
            "entry": 5, "contracts": 1, "coin_qty": 10, "equity_before": 10_000,
            "funding_pnl": 0, "target": 5.2, "sell_id": None, "entry_ts": 0,
        }
        close_position(book, 0, 5.1)
        start = book["secretary_start"]
        decide(book, view(start + 11 * BAR_MS, 5, available=0))
        self.assertEqual([item["kind"] for item in book["signals"]], ["limit"])
        decide(book, view(start + 12 * BAR_MS, 4, available=0))
        self.assertIn("secretary", [item["kind"] for item in book["signals"]])
        last = start + 31 * BAR_MS
        decide(book, view(last, 4.5, available=0))
        self.assertIn("secretary_last", [item["kind"] for item in book["signals"]])
        kept = list(book["signals"])
        decide(book, view(last + BAR_MS, 4.8, available=0))
        self.assertEqual(book["secretary_start"], last + BAR_MS)
        self.assertEqual(book["signals"], kept)

    def test_secretary_order_cancels_the_previous_open_when_margin_conflicts(self):
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["position"] = {
            "entry": 5, "contracts": 1, "coin_qty": 10, "equity_before": 10_000,
            "funding_pnl": 0, "target": 5.2, "sell_id": None, "entry_ts": 0,
        }
        close_position(book, 0, 5.1)
        book["signals"][0]["cl_id"] = "old"
        book["sample_min"] = 5
        start = book["secretary_start"]
        resting = {"old": {"side": "buy", "accFillSz": "0", "sz": "10", "px": "5"}}
        watching = decide(book, view(start, 6, available=10, orders=resting))
        self.assertFalse(any(item["op"] == "cancel" for item in watching))
        self.assertEqual(book["signals"][0]["cl_id"], "old")
        slot = start + 12 * BAR_MS
        middle = decide(book, view(slot, 4.4, available=10, orders=resting))
        self.assertEqual(middle[0]["op"], "cancel")
        self.assertEqual(middle[0]["cl_id"], "old")
        self.assertEqual(next(item for item in middle if item["op"] == "place_limit")["kind"], "secretary")
        book = fresh_book(1)
        book["awaiting_first"] = False
        book["position"] = {
            "entry": 5, "contracts": 1, "coin_qty": 10, "equity_before": 10_000,
            "funding_pnl": 0, "target": 5.2, "sell_id": None, "entry_ts": 0,
        }
        close_position(book, 0, 5.1)
        book["signals"][0]["cl_id"] = "old"
        book["sample_min"] = 5
        start = book["secretary_start"]
        last = start + 31 * BAR_MS
        actions = decide(book, view(last, 4.2, available=10, orders=resting))
        self.assertEqual(actions[0]["op"], "cancel")
        self.assertEqual(actions[0]["cl_id"], "old")
        placed = next(item for item in actions if item["op"] == "place_limit")
        self.assertEqual(placed["kind"], "secretary_last")
        self.assertEqual(placed["price"], 4.2)
        self.assertNotIn("limit", [item["kind"] for item in book["signals"]])


class AddonTest(unittest.TestCase):
    def test_primary_spawns_nine_levels_and_an_addon_does_not(self):
        book = _long_book(5)
        actions = decide(book, _long_view(5, 4.6, 4.5))
        spawn = [item for item in actions if item["op"] == "spawn"]
        self.assertEqual(spawn[0]["level"], 1)
        self.assertEqual(spawn[0]["price"], 4.5)
        again = decide(book, _long_view(5, 4.6, 4.5))
        self.assertFalse(any(item["op"] == "spawn" for item in again))

        gapped = _long_book(5)
        gap = [item for item in decide(gapped, _long_view(5, 4.4, 4.4)) if item["op"] == "spawn"]
        self.assertEqual(gap[0]["price"], 4.4)

        deep = _long_book(5)
        levels = [item["level"] for item in decide(deep, _long_view(5, 0.2, 0.2)) if item["op"] == "spawn"]
        self.assertEqual(levels, list(range(1, 10)))

        addon = fresh_book(2)
        addon["born"] = True
        addon["position"] = book["position"]
        addon_actions = decide(addon, _long_view(5, 1, 1))
        self.assertFalse(any(item["op"] == "spawn" for item in addon_actions))

    def test_birth_happens_once(self):
        addon = fresh_book(2)
        self.assertTrue(accept_birth(addon, 4.5, 50))
        self.assertFalse(accept_birth(addon, 4.0, 80))
        self.assertEqual(len(addon["signals"]), 1)
        self.assertEqual(addon["book_equity"], 10_000)


class SeparationTest(unittest.TestCase):
    def test_live_modules_do_not_call_the_demo_program(self):
        self.assertNotIn("okx_demo", inspect.getsource(runner))
        self.assertNotIn("demo_runner", inspect.getsource(runner))
        self.assertNotIn("okx_demo", inspect.getsource(strategy))
        self.assertNotIn("demo_runner", inspect.getsource(strategy))

    def test_private_request_has_no_simulated_header(self):
        captured = []

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(request, timeout=0):
            captured.append(request)
            return Response(b'{"code":"0","data":[]}')

        client = LiveClient("key", "secret", "phrase")
        with patch("live.client.urllib.request.urlopen", fake_open):
            client.balance()
        request = captured[0]
        self.assertTrue(request.full_url.startswith(HOST))
        self.assertIsNone(request.get_header("X-simulated-trading"))
        self.assertEqual(request.get_header("User-agent"), "tradex-live/0.1")
        json.loads(b"{}")


def _long_book(entry):
    book = fresh_book(1)
    book["awaiting_first"] = False
    book["position"] = {
        "entry": entry,
        "contracts": 10,
        "coin_qty": 100,
        "equity_before": 10_000,
        "funding_pnl": 0,
        "target": entry,
        "sell_id": None,
        "entry_ts": 0,
    }
    return book


def _long_view(entry, open_px, low):
    return view(
        5_000,
        open_px,
        contracts=10,
        avg_px=entry,
        candle=candle(5_000, open_px, low=low, high=entry, close=open_px),
        orders={},
    )


if __name__ == "__main__":
    unittest.main()
