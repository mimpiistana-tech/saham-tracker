import unittest
from daily_paper_logic import planned_order,apply_bar

def candidate():
    return dict(ticker="BBRI",setup="Watch Pullback",score=70,trend_score=70,
                risk_score=65,volume_ratio=1.6,signal_date="2026-10-20",
                paper_plan=dict(entry=100,cut_loss=95,tp1=107,tp2=113,entry_mode="PULLBACK"))

def bar(day, lo=99, hi=104, close=102, op=101):
    return dict(date=day,open=op,high=hi,low=lo,close=close,volume=1000000)

class DailyPaperTests(unittest.TestCase):
    def test_signal_and_duplicate_never_fill(self):
        p=planned_order(candidate())
        self.assertIsNotNone(p)
        same,ev=apply_bar(p,bar("2026-10-20"))
        self.assertEqual(ev,"WAIT_NEW_SESSION")
        self.assertEqual(same["status"],"WAIT_ENTRY")
        later,ev=apply_bar(p,bar("2026-10-21"))
        self.assertEqual(ev,"PAPER_OPEN")
        again,ev=apply_bar(later,bar("2026-10-21",lo=90,hi=120))
        self.assertEqual(ev,"WAIT_NEW_SESSION")
    def test_ambiguous_entry_fails_conservative(self):
        p=planned_order(candidate())
        out,ev=apply_bar(p,bar("2026-10-21",lo=94,hi=120,close=100,op=100))
        self.assertEqual(out["status"],"CL")
        self.assertEqual(ev,"ENTRY_STOP_SAME_BAR")
    def test_stop_precedes_target_and_replay_idempotent(self):
        p,_=apply_bar(planned_order(candidate()),bar("2026-10-21"))
        out,ev=apply_bar(p,bar("2026-10-22",lo=94,hi=120,close=100,op=100))
        self.assertEqual(out["status"],"CL")
        self.assertEqual(ev,"PAPER_CL")
        out2,ev=apply_bar(out,bar("2026-10-23",lo=99,hi=120,close=100,op=100))
        self.assertEqual(out2,out)
        self.assertEqual(ev,"NO_CHANGE")
    def test_expiration(self):
        p=planned_order(candidate())
        for n in range(21,26):
            p,event=apply_bar(p,bar(f"2026-10-{n}",lo=110,hi=115,close=112,op=113))
        self.assertEqual(p["status"],"EXPIRED")
    def test_tp1_then_tp2(self):
        p,_=apply_bar(planned_order(candidate()),bar("2026-10-21"))
        p,e=apply_bar(p,bar("2026-10-22",lo=100,hi=108,close=105,op=104))
        self.assertEqual(e,"PAPER_TP1")
        p,e=apply_bar(p,bar("2026-10-23",lo=102,hi=115,close=111,op=107))
        self.assertEqual(e,"PAPER_TP2")
        self.assertGreater(p["realized_pnl_pct"],0)
    def test_invalid_data_and_risk_block(self):
        bad=candidate();bad["volume_ratio"]=.9
        self.assertIsNone(planned_order(bad))
        p=planned_order(candidate())
        same,e=apply_bar(p,bar("2026-10-21",hi=98))
        self.assertEqual(e,"WAIT_VALID_DATA")
        self.assertEqual(same,p)

if __name__=="__main__":
    unittest.main()
