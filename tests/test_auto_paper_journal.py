"""Offline regression tests for the PAPER-ONLY SQLite journal.

All candles and candidates below are synthetic fixtures. No market data,
broker connection, scheduler, or real trade is used.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_paper_journal import paper_advance, paper_list, paper_open


CANDIDATE = {
    "ticker": "BBRI", "entry_low": 4000, "entry_high": 4100,
    "cut_loss": 3900, "tp1": 4200, "tp2": 4300,
}
ENTRY_BAR = {
    "end_iso": "2026-10-21T03:10:00+00:00", "completed": True,
    "higher_low": True, "volume_ratio": 1.4, "close": 4050,
}
NOW = "2026-10-21T03:15:00+00:00"
NEXT_BAR = {
    "end_iso": "2026-10-21T03:20:00+00:00", "completed": True,
    "high": 4400, "low": 3800,
}


class PaperJournalOfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "paper-test.sqlite3")
        env_patch = patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": self.db_path})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def open_fixture(self):
        return paper_open(CANDIDATE.copy(), ENTRY_BAR.copy(), now_iso=NOW)

    def test_missing_database_path_fails_closed(self):
        with patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": ""}):
            with self.assertRaises(RuntimeError):
                paper_list()
        self.assertFalse(Path(self.db_path).exists())

    def test_invalid_signal_does_not_create_trade(self):
        bad = {**CANDIDATE, "tp1": 4000}
        result = paper_open(bad, ENTRY_BAR, now_iso=NOW)
        self.assertEqual(result["decision"], "WAIT_DATA")
        self.assertEqual(paper_list()["trades"], [])

    def test_open_persists_and_rejects_duplicate(self):
        first = self.open_fixture()
        self.assertEqual(first["decision"], "PAPER_OPEN")
        self.assertTrue(first["paper_only"])
        again = self.open_fixture()
        self.assertEqual(again["decision"], "WAIT_DATA")
        self.assertEqual(again["reason"], "active_ticker_exists")
        rows = paper_list()["trades"]  # Separate SQLite connection
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "OPEN")
        self.assertEqual(rows[0]["signal_id"], first["trade"]["signal_id"])

    def test_ambiguous_tp_stop_bar_closes_at_stop_only(self):
        self.open_fixture()
        result = paper_advance("BBRI", NEXT_BAR)
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(result["updated"][0]["status"], "CL")
        self.assertEqual(result["updated"][0]["exit_price"], 3900)
        self.assertEqual(result["updated"][0]["exit_reason"], "stop_or_ambiguous_candle")
        self.assertEqual(paper_list()["trades"][0]["status"], "CL")
        self.assertEqual(paper_advance("BBRI", NEXT_BAR)["updated"], [])

    def test_unfinished_candle_cannot_trigger_exit(self):
        self.open_fixture()
        result = paper_advance("BBRI", {**NEXT_BAR, "completed": False})
        self.assertEqual(result["updated"], [])
        self.assertEqual(paper_list()["trades"][0]["status"], "OPEN")


if __name__ == "__main__":
    unittest.main()
