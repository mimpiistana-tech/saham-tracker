import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from server_scan import due, status


class ScheduleTests(unittest.TestCase):
    def test_weekday(self):
        now=datetime(2026,10,21,10,16,tzinfo=ZoneInfo("Asia/Jakarta"))
        self.assertTrue(due(now,None))
        self.assertFalse(due(now,"2026-10-21"))
    def test_status_declares_daily_bar_entry_mode(self):
        with patch.dict("os.environ", {"AUTO_SCAN_ENABLED":"1"}):
            state=status()
        self.assertEqual(state["paper_entry_mode"],"completed_daily_bar_touch")
        self.assertNotIn("intraday_entry",state)
        self.assertNotIn("intraday_entry_poll_seconds",state)

    def test_no_weekends_or_old_hours(self):
        tz=ZoneInfo("Asia/Jakarta")
        self.assertFalse(due(datetime(2026,10,24,10,16,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,9,59,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,12,00,tzinfo=tz),None))

if __name__=="__main__":
    unittest.main()
