import unittest

import telegram_notice as tg


class LedgerTest(unittest.TestCase):
    def test_event_is_sent_once(self):
        sent = []

        def deliver(text):
            sent.append(text)
            return True

        ledger = tg.Ledger([])
        self.assertTrue(ledger.once("place:1", "挂单", deliver))
        self.assertFalse(ledger.once("place:1", "挂单", deliver))
        self.assertEqual(sent, ["挂单"])

    def test_failed_send_can_retry(self):
        ledger = tg.Ledger([])
        self.assertFalse(ledger.once("place:1", "挂单", lambda _text: False))
        self.assertTrue(ledger.once("place:1", "挂单", lambda _text: True))

    def test_alert_clears_when_the_condition_ends(self):
        sent = []

        def deliver(text):
            sent.append(text)
            return True

        ledger = tg.Ledger([])
        ledger.latch("alert:leverage", True, "杠杆", deliver)
        ledger.latch("alert:leverage", True, "杠杆", deliver)
        ledger.latch("alert:leverage", False, "杠杆", deliver)
        ledger.latch("alert:leverage", True, "杠杆", deliver)
        self.assertEqual(sent, ["杠杆", "杠杆"])


class ClassifyTest(unittest.TestCase):
    def test_short_and_leverage(self):
        self.assertTrue(tg.is_short({"pos": "1", "posSide": "short"}))
        self.assertTrue(tg.is_short({"pos": "-0.2", "posSide": "net"}))
        self.assertFalse(tg.is_short({"pos": "1", "posSide": "long"}))
        self.assertEqual(tg.lever_above_one({"lever": "2"}), 2)
        self.assertIsNone(tg.lever_above_one({"lever": "1"}))

    def test_partial_and_full_fill(self):
        partial = {"side": "buy", "sz": "10", "accFillSz": "2", "state": "partially_filled"}
        self.assertEqual(tg.partial_fill(partial), (2, 10))
        self.assertIn("部分成交", tg.partial_text(partial, 2, 10))
        full = {"side": "sell", "sz": "10", "accFillSz": "10", "state": "filled", "avgPx": "5.1"}
        self.assertTrue(tg.is_full_fill(full))
        self.assertIsNone(tg.partial_fill(full))
        self.assertIn("全部成交", tg.filled_text(full))

    def test_status_command(self):
        self.assertEqual(tg.command_of("/status@TradexBot"), "/status")
        self.assertEqual(tg.command_of("  /help 一下"), "/help")
        text = tg.status_text(
            "空仓。买单挂着。",
            10201.23,
            5.21,
            None,
            {"side": "buy", "px": "5.025", "sz": "202.9"},
        )
        self.assertIn("当前没有持仓", text)
        self.assertIn("买入 202.9 张 @ 5.025", text)
        self.assertIn("10201.23", text)

    def test_notice_labels(self):
        self.assertTrue(tg.placed_text({"side": "buy", "sz": "1", "px": "5"}).startswith("【通知】挂单"))
        self.assertTrue(tg.open_text(1, 5, 10000).startswith("【通知】开仓"))
        self.assertTrue(tg.close_text(1, 5, 5.1, 10200).startswith("【通知】平仓"))
        self.assertTrue(tg.leverage_text(3).startswith("【告警】"))
        self.assertTrue(tg.short_text(0.1).startswith("【告警】出现空单"))


if __name__ == "__main__":
    unittest.main()
