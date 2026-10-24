"""Integration regression for scanner -> paper WATCH API; no network/orders."""
import unittest
from app import app

PLAN = {"ticker": "BBRI", "entry_low": 4000, "entry_high": 4100,
        "paper_plan": {"cut_loss": 3900, "tp1": 4200, "tp2": 4300}}
SCAN = {"success": True, "candle_policy": "COMPLETED_DAILY_ONLY",
        "market_data_is_live": False, "top_picks": [PLAN]}

class ScannerWatchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_watch_does_not_execute(self):
        res = self.client.post("/api/auto-paper/scanner-watch", json=SCAN)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["ready_for_entry"])
        self.assertFalse(data["auto_entry_enabled"])
        self.assertFalse(data["journal_persistent"])
        self.assertFalse(data["broker_order_enabled"])
        self.assertEqual(data["candidates"][0]["ticker"], "BBRI")

    def test_bad_payload_fails_closed(self):
        res = self.client.post("/api/auto-paper/scanner-watch", json=[])
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get_json()["ready_for_entry"])
        self.assertEqual(res.get_json()["candidates"], [])

if __name__ == "__main__":
    unittest.main()
