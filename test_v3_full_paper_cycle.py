"""Automatic integration test of the actual V3 daily paper state machine.
No market requests, disk mutation, broker calls, or real trades.
"""
import unittest
from daily_paper_logic import planned_order, apply_bar

ITEM = {
 "ticker":"BBRI", "setup":"Momentum", "score":80, "trend_score":75,
 "risk_score":70, "volume_ratio":1.6, "signal_date":"2026-10-20",
 "paper_plan":{"entry":4000,"cut_loss":3900,"tp1":4200,"tp2":4400,"entry_mode":"PULLBACK"}
}
def candle(day, lo, hi, close=4050):
    return {"date":day,"open":4050,"high":hi,"low":lo,"close":close,"volume":100000}

class RealV3LogicTests(unittest.TestCase):
    def test_plan_entry_tp1_tp2(self):
        row=planned_order(ITEM)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"],"WAIT_ENTRY")
        row,event=apply_bar(row,candle("2026-10-21",3980,4110))
        self.assertEqual((row["status"],event),("OPEN","PAPER_OPEN"))
        row,event=apply_bar(row,candle("2026-10-22",4000,4250))
        self.assertEqual((row["status"],event),("TP1_HIT","PAPER_TP1"))
        row,event=apply_bar(row,candle("2026-10-23",4000,4450))
        self.assertEqual((row["status"],event),("TP2","PAPER_TP2"))
        self.assertGreater(row["realized_pnl_pct"],0)
        again,event=apply_bar(row,candle("2026-10-26",3800,4500))
        self.assertEqual(again,row)
    def test_stop_wins_ambiguous_entry(self):
        row=planned_order(ITEM)
        row,event=apply_bar(row,candle("2026-10-21",3850,4450))
        self.assertEqual(row["status"],"CL")
        self.assertEqual(event,"ENTRY_STOP_SAME_BAR")
    def test_same_session_cannot_fill(self):
        row=planned_order(ITEM)
        same,event=apply_bar(row,candle("2026-10-20",3900,4400))
        self.assertEqual(same,row)
    def test_invalid_signal_rejected(self):
        self.assertIsNone(planned_order({**ITEM,"volume_ratio":1.0}))
if __name__=="__main__":
    unittest.main()
