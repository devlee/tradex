import json
import unittest
from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from okx_data import SHANGHAI
from okx_demo import HOST, LiveClient
from demo_runner import BAR_MS, BOOK_EQUITY, Runner, _book_after, fresh_state, next_entry_bar


def ms(year, month, day, hour, minute=0):
    moment = datetime(year, month, day, hour, minute, tzinfo=SHANGHAI)
    return int(moment.timestamp() * 1000)


class NextEntryTest(unittest.TestCase):
    def test_noon_waits_for_the_next_midnight(self):
        self.assertEqual(next_entry_bar(ms(2026, 10, 21, 12, 8)), ms(2026, 10, 22, 0, 0))

    def test_open_bar_is_still_the_entry(self):
        self.assertEqual(BAR_MS, 5 * 60 * 1000)
        self.assertEqual(next_entry_bar(ms(2026, 10, 22, 0, 2)), ms(2026, 10, 22, 0, 0))

    def test_finished_bar_rolls_one_day(self):
        opened = ms(2026, 10, 22, 0, 0)
        self.assertEqual(next_entry_bar(opened + BAR_MS), ms(2026, 10, 23, 0, 0))


class BookEquityTest(unittest.TestCase):
    def test_first_book_is_ten_thousand(self):
        self.assertEqual(BOOK_EQUITY, 10_000.0)

    def test_close_compounds_only_the_book(self):
        ended = _book_after({
            "equity_before": 10_000,
            "coin_qty": 100,
            "entry": 5,
            "funding_pnl": 0,
        }, 5.1)
        self.assertGreater(ended, 10_000)
        self.assertLess(ended, 10_200)


class LiveHeaderTest(unittest.TestCase):
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
        with patch("okx_demo.urllib.request.urlopen", fake_open):
            client.balance()
        request = captured[0]
        self.assertTrue(request.full_url.startswith(HOST))
        self.assertIsNone(request.get_header("X-simulated-trading"))
        self.assertEqual(request.get_header("User-agent"), "tradex-live/0.1")
        self.assertNotIn("trade/order", request.full_url)

    def test_fresh_book_waits_for_arm(self):
        state = fresh_state(ms(2026, 10, 21, 12, 0))
        self.assertEqual(state["phase"], "standby")
        self.assertEqual(state["trading"], "live")
        self.assertEqual(state["book_equity"], 10_000.0)

    def test_demo_book_is_not_adopted(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "live-state.json"
            path.write_text(json.dumps({"phase": "wait_clock", "book_equity": 10201.23}), encoding="utf-8")
            with patch("demo_runner.STATE_PATH", path), patch("demo_runner.STATUS_PATH", Path(folder) / "live-status.json"):
                runner = Runner()
                runner.save()
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(runner._block_save)
        self.assertEqual(runner.state["phase"], "live_locked")
        self.assertEqual(saved["phase"], "wait_clock")
        self.assertEqual(saved["book_equity"], 10201.23)


if __name__ == "__main__":
    unittest.main()
