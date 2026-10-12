"""Offline tests for StockRadar V2 scanner; do not call Yahoo or IndexAlpha."""
import time
import unittest
from unittest.mock import patch
import app as radar


class ScannerV2Test(unittest.TestCase):
    def setUp(self):
        radar.CACHE.clear()
        self.client = radar.app.test_client()
        self.regime = patch.object(
            radar, "get_current_market_regime",
            return_value={"regime": "Unknown", "date": None},
        )
        self.regime.start()
        self.addCleanup(self.regime.stop)
        self.scanner = patch.object(radar, "scan_one_ticker", return_value=None)
        self.scan_mock = self.scanner.start()
        self.addCleanup(self.scanner.stop)

    def test_quick_universe_has_twenty_unique_tickers(self):
        self.assertEqual(len(radar.QUICK_SCAN_UNIVERSE), 20)
        self.assertEqual(len(set(radar.QUICK_SCAN_UNIVERSE)), 20)

    def test_quick_mode_scans_twenty_and_returns_metadata(self):
        res = self.client.get("/api/scanner?to=2020-01-02&mode=quick")
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "quick")
        self.assertEqual(data["universe_size"], 20)
        self.assertEqual(self.scan_mock.call_count, 20)
        self.assertEqual(res.headers["X-StockRadar-Cache"], "MISS")

    def test_repeat_quick_uses_server_cache(self):
        first = self.client.get("/api/scanner?to=2020-01-02&mode=quick")
        before = self.scan_mock.call_count
        second = self.client.get("/api/scanner?to=2020-01-02&mode=quick")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.headers["X-StockRadar-Cache"], "HIT")
        self.assertEqual(self.scan_mock.call_count, before)

    def test_full_and_quick_do_not_share_cache(self):
        self.client.get("/api/scanner?to=2020-01-02&mode=quick")
        self.scan_mock.reset_mock()
        full = self.client.get("/api/scanner?to=2020-01-02&mode=full")
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.get_json()["mode"], "full")
        self.assertEqual(full.get_json()["universe_size"], len(radar.SCANNER_UNIVERSE))
        self.assertEqual(self.scan_mock.call_count, len(radar.SCANNER_UNIVERSE))

    def test_missing_date_rejected(self):
        self.assertEqual(self.client.get("/api/scanner?mode=quick").status_code, 400)

    def test_bad_date_rejected(self):
        self.assertEqual(self.client.get("/api/scanner?to=wrong&mode=quick").status_code, 400)

    def test_invalid_mode_rejected(self):
        self.assertEqual(self.client.get("/api/scanner?to=2020-01-02&mode=unexpected").status_code, 400)
        self.assertEqual(self.scan_mock.call_count, 0)

    def test_cache_respects_ttl(self):
        radar.cache_put("ttl-example", {"value": 1}, 200)
        radar.CACHE["ttl-example"]["time"] = time.time() - 650
        _, ten_min_state = radar.cache_get("ttl-example", max_age=600)
        _, daily_state = radar.cache_get("ttl-example", max_age=86400)
        self.assertEqual(ten_min_state, "STALE")
        self.assertEqual(daily_state, "HIT")

    def test_no_external_requests_during_scanner_smoke(self):
        with patch.object(radar.requests, "get", side_effect=AssertionError("External API called")):
            res = self.client.get("/api/scanner?to=2020-01-02&mode=quick")
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
