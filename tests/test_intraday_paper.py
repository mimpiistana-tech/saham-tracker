import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from intraday_paper import analyze_entry_candles

WIB = ZoneInfo("Asia/Jakarta")


def sample_candles(now):
    last_start = int((now - timedelta(minutes=10)).timestamp())
    bars = []
    for index in range(12):
        start = last_start - (11-index)*300
        bars.append({"timestamp": start, "open": 99.0, "high": 100.0,
                     "low": 98.5, "close": 99.5, "volume": 100})
    bars[-2].update(open=99.5, high=100.2, low=99.0, close=100.0, volume=100)
    bars[-1].update(open=100.1, high=101.0, low=99.5, close=100.8, volume=150)
    return bars


class IntradayPaperTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 10, 36, tzinfo=WIB)

    def test_confirmed_v2_bounce_crossing_v3_entry(self):
        result = analyze_entry_candles("BBRI", sample_candles(self.now), 100,
                                       now=self.now)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["session_date"], "2026-10-23")
        self.assertTrue(result["paper_only"])
        self.assertTrue(result["checks"]["higher_low"])
        self.assertEqual(result["source"], "YAHOO_5M_INDICATIVE")

    def test_no_entry_when_price_does_not_touch_plan(self):
        result = analyze_entry_candles("BBRI", sample_candles(self.now), 102,
                                       now=self.now)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "entry_checks_failed")
        self.assertFalse(result["checks"]["entry_touched"])

    def test_stale_bar_is_rejected(self):
        old = self.now - timedelta(minutes=40)
        result = analyze_entry_candles("BBRI", sample_candles(old), 100,
                                       now=self.now)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "stale_bar")

    def test_incomplete_bar_is_not_used(self):
        bars = sample_candles(self.now)
        bars[-1]["timestamp"] = int(self.now.timestamp()) - 60
        result = analyze_entry_candles("BBRI", bars, 100, now=self.now)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "insufficient_completed_bars")

    def test_naive_clock_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze_entry_candles("BBRI", sample_candles(self.now), 100,
                                  now=datetime(2026, 10, 23, 10, 36))


if __name__ == "__main__":
    unittest.main()
