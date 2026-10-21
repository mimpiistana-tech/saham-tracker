"""Offline invariants: paper rules, duplicate prevention, and durable journal."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from auto_paper_rules import evaluate_paper_candidate
from auto_paper_journal import paper_open, paper_advance, paper_list

class PaperSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "paper.sqlite3")
        self.patcher = patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": self.db})
        self.patcher.start()
        self.now = datetime.now(timezone.utc)
        self.end = self.now - timedelta(seconds=30)
        self.bar = {"end_iso": self.end.isoformat(), "completed": True,
                    "higher_low": True, "volume_ratio": 1.5, "close": 100}
        self.candidate = {"ticker": "BBRI", "entry_low": 99, "entry_high": 101,
                          "cut_loss": 95, "tp1": 106, "tp2": 112}
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()
    def test_gate_rejects_stale_and_incomplete(self):
        bar = dict(self.bar, end_iso=(self.now - timedelta(hours=2)).isoformat())
        self.assertEqual(evaluate_paper_candidate(self.candidate, bar, now_iso=self.now.isoformat())["decision"], "WAIT_DATA")
        self.assertEqual(evaluate_paper_candidate(self.candidate, dict(self.bar, completed=False), now_iso=self.now.isoformat())["decision"], "WAIT_DATA")
    def test_open_once_and_persist(self):
        first = paper_open(self.candidate, self.bar, now_iso=self.now.isoformat())
        self.assertEqual(first["decision"], "PAPER_OPEN")
        second = paper_open(self.candidate, self.bar, now_iso=self.now.isoformat())
        self.assertEqual(second["decision"], "WAIT_DATA")
        self.assertEqual(len(paper_list()["trades"]), 1)
    def test_stop_first_and_idempotent(self):
        self.assertEqual(paper_open(self.candidate, self.bar, now_iso=self.now.isoformat())["decision"], "PAPER_OPEN")
        next_bar = {"end_iso": (self.end + timedelta(minutes=5)).isoformat(),
                    "completed": True, "high": 120, "low": 94}
        updated = paper_advance("BBRI", next_bar)["updated"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["status"], "CL")
        self.assertEqual(paper_advance("BBRI", next_bar)["updated"], [])
    def test_fail_closed_without_storage(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                paper_list()

if __name__ == "__main__":
    unittest.main()
