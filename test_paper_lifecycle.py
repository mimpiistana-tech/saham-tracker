"""One complete synthetic PAPER lifecycle, isolated from live market and broker."""
import os
import tempfile
import unittest
from unittest.mock import patch
from auto_paper_journal import paper_open, paper_advance, paper_list

C = {"ticker": "BBRI", "entry_low": 4000, "entry_high": 4100,
     "cut_loss": 3900, "tp1": 4200, "tp2": 4300}
B = {"end_iso": "2026-10-21T03:10:00+00:00", "completed": True,
     "higher_low": True, "volume_ratio": 1.4, "close": 4050}

class PaperLifecycleTests(unittest.TestCase):
    def test_open_tp1_tp2_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": os.path.join(directory, "journal.sqlite")}):
                opened = paper_open(C, B, now_iso="2026-10-21T03:15:00+00:00")
                self.assertEqual(opened["decision"], "PAPER_OPEN")
                duplicate = paper_open(C, B, now_iso="2026-10-21T03:15:00+00:00")
                self.assertEqual(duplicate["decision"], "WAIT_DATA")
                self.assertEqual(len(paper_list()["trades"]), 1)
                first = paper_advance("BBRI", {"end_iso": "2026-10-21T03:20:00+00:00",
                                               "completed": True, "low": 4000, "high": 4210})
                self.assertEqual(first["updated"][0]["status"], "TP1_HIT")
                second = paper_advance("BBRI", {"end_iso": "2026-10-21T03:25:00+00:00",
                                                "completed": True, "low": 4100, "high": 4310})
                self.assertEqual(second["updated"][0]["status"], "TP2")
                self.assertEqual(paper_list()["trades"][0]["status"], "TP2")
                self.assertEqual(paper_advance("BBRI", {"end_iso": "2026-10-21T03:30:00+00:00",
                                                        "completed": True, "low": 3800, "high": 4400})["updated"], [])

    def test_missing_persistent_path_fails_closed(self):
        with patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": ""}):
            with self.assertRaises(RuntimeError):
                paper_list()

if __name__ == "__main__":
    unittest.main()
