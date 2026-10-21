import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import daily_paper_runner as runner

class DailyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"AUTO_PAPER_DB_PATH":self.temp.name+"/paper.db",
                                        "AUTO_PAPER_ENABLED":"1"})
        self.env.start()
        self.mount=patch("daily_paper_runner.storage_health",return_value={"ready":True})
        self.mount.start()
        self.cutoff=(datetime.now(ZoneInfo("Asia/Jakarta")).date()-timedelta(days=1)).isoformat()
        self.signal=self.cutoff
        self.candidate=dict(ticker="BBRI",setup="Watch Pullback",score=75,
                trend_score=75,risk_score=70,volume_ratio=1.6,signal_date=self.signal,
                paper_plan=dict(entry=100,cut_loss=95,tp1=108,tp2=114,entry_mode="PULLBACK"))
    def tearDown(self):
        self.mount.stop()
        self.env.stop()
        self.temp.cleanup()
    def test_cycle_is_idempotent_and_writes_waiting_plan(self):
        b=dict(date=self.cutoff,open=102,high=105,low=101,close=103,volume=3000000)
        run=lambda:runner.run_cycle([self.candidate],self.cutoff,lambda t,c:[b],watch=("BBRI",))
        first=run()
        self.assertTrue(first["ran"])
        self.assertEqual(first["created"],1)
        second=run()
        self.assertFalse(second["ran"])
        self.assertEqual(second["reason"],"already_processed")
        summary=runner.summary()
        self.assertEqual(summary["counts"]["WAIT_ENTRY"],1)
    def test_no_fake_fill_on_invalid_bars(self):
        b=dict(date=self.cutoff,open=105,high=90,low=99,close=100,volume=1)
        result=runner.run_cycle([self.candidate],self.cutoff,lambda t,c:[b],watch=("BBRI",))
        self.assertFalse(result["ran"])
        self.assertEqual(result["reason"],"no_verified_daily_bars")
    def test_disabled_never_writes(self):
        with patch.dict(os.environ,{"AUTO_PAPER_ENABLED":"0"}):
            result=runner.run_cycle([self.candidate],self.cutoff,lambda t,c:[],watch=("BBRI",))
            self.assertFalse(result["ran"])
            self.assertEqual(result["reason"],"disabled")

if __name__=="__main__":
    unittest.main()
