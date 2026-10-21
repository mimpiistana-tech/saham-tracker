import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from server_scan import due

class ScheduleTests(unittest.TestCase):
    def test_weekday(self):
        now=datetime(2026,10,21,10,16,tzinfo=ZoneInfo("Asia/Jakarta"))
        self.assertTrue(due(now,None))
        self.assertFalse(due(now,"2026-10-21"))
    def test_no_weekends_or_old_hours(self):
        tz=ZoneInfo("Asia/Jakarta")
        self.assertFalse(due(datetime(2026,10,24,10,16,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,9,59,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,12,00,tzinfo=tz),None))

if __name__=="__main__":
    unittest.main()
