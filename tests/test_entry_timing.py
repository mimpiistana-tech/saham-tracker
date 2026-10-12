import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app as radar

WIB=timezone(timedelta(hours=7))
def ts(h,m):
    return int(datetime(2026,10,12,h,m,tzinfo=WIB).timestamp())
def row(h,m,o,hi,lo,c,v):
    return {"timestamp":ts(h,m),"open":o,"high":hi,"low":lo,"close":c,"volume":v}

class TimingTest(unittest.TestCase):
    def setUp(self):
        self.base=[row(9,i*5,100,102,99,101,100) for i in range(10)]
        self.prev=row(9,50,101,103,100,102,100)
        self.bounce=row(9,55,102,105,101,104,250)

    def test_pass_only_completed_bounce(self):
        d=radar.analyze_5m_bounce(self.base+[self.prev,self.bounce],ts(10,2))
        self.assertEqual(d["status"],"BOUNCE_CONFIRMED")
        self.assertFalse(d["live_trade_allowed"])
        self.assertGreaterEqual(d["volume_ratio"],1.3)

    def test_unfinished_candle_excluded(self):
        d=radar.analyze_5m_bounce(self.base+[self.prev,self.bounce],ts(9,59))
        self.assertEqual(d["status"],"WAIT_DATA")

    def test_old_candle_waits(self):
        d=radar.analyze_5m_bounce(self.base+[self.prev,self.bounce],ts(10,30))
        self.assertEqual(d["status"],"WAIT_DELAYED")

    def test_weak_volume_waits(self):
        low=row(9,55,102,105,101,104,80)
        d=radar.analyze_5m_bounce(self.base+[self.prev,low],ts(10,2))
        self.assertEqual(d["status"],"WAIT_CONFIRMATION")
        self.assertFalse(d["checks"]["volume_min_1_3x"])

    def test_last_session_data_rejected(self):
        rows=[{**x,"timestamp":x["timestamp"]-86400} for x in self.base+[self.prev,self.bounce]]
        d=radar.analyze_5m_bounce(rows,ts(10,2))
        self.assertEqual(d["status"],"WAIT_DATA")

    def test_invalid_ticker_no_network(self):
        with patch.object(radar.requests,'get',side_effect=AssertionError('network')):
            res=radar.app.test_client().get('/api/entry-timing?ticker=ARCI!%20')
        self.assertEqual(res.status_code,400)
if __name__=="__main__":unittest.main()
