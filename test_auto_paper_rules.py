import unittest
from auto_paper_rules import evaluate_paper_candidate

C = dict(ticker='BBRI', entry_low=4000, entry_high=4100, cut_loss=3900, tp1=4200, tp2=4300)
B = dict(end_iso='2026-10-21T03:10:00+00:00', completed=True, higher_low=True, volume_ratio=1.4, close=4050)
NOW = '2026-10-21T03:15:00+00:00'

class RuleTests(unittest.TestCase):
    def check(self, reason, candidate=None, bar=None, now=NOW):
        result = evaluate_paper_candidate(C if candidate is None else candidate, B if bar is None else bar, now_iso=now)
        self.assertEqual(result['reason'], reason)
        self.assertTrue(result['paper_only'])
    def test_valid(self):
        self.assertEqual(evaluate_paper_candidate(C,B,now_iso=NOW)['decision'], 'PAPER_CANDIDATE')
    def test_stale(self): self.check('stale_or_future_bar', now='2026-10-21T03:25:01+00:00')
    def test_future(self): self.check('stale_or_future_bar', now='2026-10-21T03:09:59+00:00')
    def test_incomplete(self): self.check('incomplete_bar',bar={**B,'completed':False})
    def test_hl(self): self.check('higher_low_not_confirmed',bar={**B,'higher_low':False})
    def test_volume(self): self.check('insufficient_volume',bar={**B,'volume_ratio':1.29})
    def test_empty(self):
        self.assertEqual(evaluate_paper_candidate(None,B,now_iso=NOW)['reason'],'missing_payload')
    def test_nan(self): self.check('invalid_prices',bar={**B,'close':float('nan')})
    def test_zone(self): self.check('invalid_zone_or_risk',candidate={**C,'tp1':4000})
    def test_timestamp(self): self.check('invalid_timestamp',bar={**B,'end_iso':'not-a-date'})
    def test_ticker(self): self.check('invalid_ticker',candidate={**C,'ticker':'../../'})
    def test_naive_time(self): self.check('timezone_required',now='2026-10-21T03:15:00')

if __name__ == '__main__': unittest.main()
