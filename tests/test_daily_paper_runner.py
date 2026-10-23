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
    def test_v2_confirmed_intraday_entry_opens_persistent_v3_plan(self):
        daily=dict(date=self.cutoff,open=102,high=105,low=101,close=103,volume=3000000)
        result=runner.run_cycle([self.candidate],self.cutoff,lambda t,c:[daily],watch=("BBRI",))
        self.assertEqual(result["created"],1)
        self.assertEqual(len(runner.waiting_entries()),1)
        now=datetime.now(ZoneInfo("Asia/Jakarta"))
        signal={
            "qualified":True,"paper_only":True,"source":"YAHOO_5M_INDICATIVE",
            "ticker":"BBRI","session_date":now.date().isoformat(),
            "bar_end_iso":(now-timedelta(minutes=5)).isoformat(),
            "volume_ratio":1.5,
            "checks":{"green":True,"break_previous_high":True,"higher_low":True,
                      "volume_1_3x":True,"entry_touched":True,
                      "close_at_or_above_entry":True},
            "bar":{"date":now.date().isoformat(),"open":100.1,"high":101,
                   "low":99.5,"close":100.8,"volume":150},
        }
        opened=runner.open_intraday_entry("BBRI",signal,now=now)
        self.assertTrue(opened["opened"])
        self.assertEqual(opened["trade"]["status"],"OPEN")
        self.assertEqual(opened["trade"]["entry_source"],"V2_5M_BOUNCE")
        self.assertEqual(runner.summary()["counts"]["OPEN"],1)
        self.assertEqual(runner.waiting_entries(),[])

    def test_intraday_entry_rejects_unconfirmed_signal(self):
        daily=dict(date=self.cutoff,open=102,high=105,low=101,close=103,volume=3000000)
        runner.run_cycle([self.candidate],self.cutoff,lambda t,c:[daily],watch=("BBRI",))
        result=runner.open_intraday_entry("BBRI",{"qualified":False},now=datetime.now(ZoneInfo("Asia/Jakarta")))
        self.assertFalse(result["opened"])
        self.assertEqual(result["reason"],"entry_not_confirmed")
        self.assertEqual(runner.summary()["counts"]["WAIT_ENTRY"],1)

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
