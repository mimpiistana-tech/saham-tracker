import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from server_scan import due, entry_poll_due


class ScheduleTests(unittest.TestCase):
    def test_weekday(self):
        now=datetime(2026,10,21,10,16,tzinfo=ZoneInfo("Asia/Jakarta"))
        self.assertTrue(due(now,None))
        self.assertFalse(due(now,"2026-10-21"))
    def test_intraday_entry_poll_is_throttled_to_market_hours(self):
        tz=ZoneInfo("Asia/Jakarta")
        now=datetime(2026,10,21,10,16,tzinfo=tz)
        self.assertTrue(entry_poll_due(now,None))
        self.assertFalse(entry_poll_due(now,now))
        self.assertTrue(entry_poll_due(now+timedelta(minutes=5),now))
        self.assertFalse(entry_poll_due(datetime(2026,10,24,10,16,tzinfo=tz),None))
        self.assertFalse(entry_poll_due(datetime(2026,10,21,16,0,tzinfo=tz),None))

    def test_no_weekends_or_old_hours(self):
        tz=ZoneInfo("Asia/Jakarta")
        self.assertFalse(due(datetime(2026,10,24,10,16,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,9,59,tzinfo=tz),None))
        self.assertFalse(due(datetime(2026,10,21,12,00,tzinfo=tz),None))

if __name__=="__main__":
    unittest.main()
