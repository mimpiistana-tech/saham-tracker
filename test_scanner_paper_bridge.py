import unittest
from scanner_paper_bridge import bridge_scanner_result, scanner_to_paper_candidate

P = {"ticker": "BBRI", "entry_low": 4000, "entry_high": 4100,
     "paper_plan": {"cut_loss": 3900, "tp1": 4200, "tp2": 4300}}
S = {"success": True, "candle_policy": "COMPLETED_DAILY_ONLY",
     "market_data_is_live": False, "top_picks": [P]}

class BridgeTests(unittest.TestCase):
    def test_valid_plan_is_watch_only(self):
        out = bridge_scanner_result(S)
        self.assertFalse(out["ready_for_entry"])
        self.assertEqual(out["candidates"][0]["ticker"], "BBRI")
    def test_no_5m_confirmation(self):
        self.assertIn("5m", bridge_scanner_result(S)["reason"])
    def test_reject_live_claim(self):
        self.assertEqual(bridge_scanner_result({**S, "market_data_is_live": True})["candidates"], [])
    def test_reject_missing_plan(self):
        self.assertIsNone(scanner_to_paper_candidate({"ticker": "BBRI"}))
    def test_reject_bad_risk(self):
        self.assertIsNone(scanner_to_paper_candidate({**P, "paper_plan": {**P["paper_plan"], "cut_loss": 4500}}))
    def test_deduplicate(self):
        self.assertEqual(len(bridge_scanner_result({**S, "top_picks": [P, P]})["candidates"]), 1)
if __name__ == "__main__":
    unittest.main()
