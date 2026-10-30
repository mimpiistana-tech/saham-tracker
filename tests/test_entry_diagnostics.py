import copy
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from daily_paper_logic import round_idx, planned_order, apply_bar, candidate_decision
import daily_paper_runner as runner


def candidate(day='2026-10-23'):
    return dict(ticker='PWON', signal_date=day, setup='Momentum', score=70,
                trend_score=72, risk_score=60, volume_ratio=1.4,
                paper_plan=dict(entry=296.08, cut_loss=278.75, tp1=316.87,
                                tp2=337.66, entry_mode='BREAKOUT'))


def candle(day, low=282, high=296):
    return dict(date=day, open=high, high=high, low=low, close=low, volume=1000)


class EntryDiagnosticsTests(unittest.TestCase):
    def test_idx_boundaries_and_conservative_breakout(self):
        for value, down, up in [(199.9,199,200),(200,200,200),(499.9,498,500),
                                (500.1,500,505),(1999.9,1995,2000),
                                (2000.1,2000,2010),(4999.9,4990,5000),
                                (5000.1,5000,5025)]:
            self.assertEqual(round_idx(value,'down'),down)
            self.assertEqual(round_idx(value,'up'),up)
        p=planned_order(candidate())
        self.assertEqual([p[k] for k in ('entry','cut_loss','tp1','tp2')],[298,278,318,338])
        self.assertLessEqual(p['planned_risk'],100_000)
        self.assertLessEqual(p['paper_value'],10_000_000/3)
        pull=candidate(); pull['paper_plan']['entry_mode']='PULLBACK'
        self.assertEqual(planned_order(pull)['entry'],296)

    def test_rounding_can_reject_invalid_risk_reward(self):
        c=candidate(); c['paper_plan'].update(entry=296.08,cut_loss=278.75,tp1=310,tp2=323)
        self.assertIsNone(planned_order(c))
        self.assertFalse(candidate_decision(c)['eligible'])

    def test_explanations_keep_score_and_volume_gates(self):
        c=candidate(); c.update(score=48.4,volume_ratio=.5121)
        result=candidate_decision(c)
        self.assertFalse(result['eligible'])
        self.assertIn('Skor 48.4 < 65',result['reason'])
        self.assertIn('Rasio volume 0.5121 < 1.3',result['reason'])

    def test_legacy_migration_never_replays_or_resets_wait(self):
        legacy=planned_order(candidate())
        legacy.pop('price_rounding_version')
        legacy.update(candidate()['paper_plan'], lots=10, shares=1000,
                      planned_risk=17330, paper_value=296080,
                      waited=4,last_bar_day='2026-10-29')
        original=copy.deepcopy(legacy)
        unchanged,_=apply_bar(legacy,candle('2026-10-29',low=278,high=300))
        self.assertEqual(unchanged,original)
        expired,event=apply_bar(legacy,candle('2026-10-30'))
        self.assertEqual(expired['entry'],298)
        self.assertEqual(expired['waited'],5)
        self.assertEqual(event,'EXPIRED')
        self.assertEqual(expired['status'],'EXPIRED')
        self.assertEqual(legacy,original)
        self.assertIsNone(expired['entry_day'])
        self.assertLessEqual(expired['planned_risk'],legacy['planned_risk'])

    def test_fifth_session_can_fill_but_sixth_cannot(self):
        p=planned_order(candidate());p['waited']=4
        opened,event=apply_bar(p,candle('2026-10-30',low=290,high=300))
        self.assertEqual(event,'PAPER_OPEN')
        p['waited']=5
        expired,event=apply_bar(p,candle('2026-10-30',low=290,high=300))
        self.assertEqual(event,'EXPIRED')

    def test_expiration_releases_ticker_and_decisions_persist(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                AUTO_PAPER_ENABLED='1',AUTO_PAPER_DB_PATH=tmp+'/paper.db'), \
                patch('daily_paper_runner.storage_health',return_value={'ready':True}), \
                patch('daily_paper_runner.datetime') as clock:
            clock.now.return_value=datetime(2026,10,24,12,tzinfo=ZoneInfo('Asia/Jakarta'))
            loader=lambda t,c:[candle('2026-10-23')]
            runner.run_cycle([candidate()],'2026-10-23',loader,watch=('PWON',))
            clock.now.return_value=datetime(2026,10,31,12,tzinfo=ZoneInfo('Asia/Jakarta'))
            bars=[candle('2026-10-'+str(n)) for n in (23,26,27,28,29,30)]
            result=runner.run_cycle([candidate('2026-10-30')],'2026-10-30',lambda t,c:bars,watch=('PWON',))
            self.assertEqual(result['created'],1)
            self.assertEqual(runner.summary()['counts']['EXPIRED'],1)
            self.assertEqual(runner.summary()['counts']['WAIT_ENTRY'],1)
            self.assertEqual(runner.waiting_entries()[0]['signal_day'],'2026-10-30')
            self.assertTrue(runner.summary()['candidate_decisions'][0]['eligible'])
            self.assertEqual(runner.summary()['recent_expired'][0]['waited'],5)
            replay=runner.run_cycle([candidate('2026-10-30')],'2026-10-30',lambda t,c:bars,watch=('PWON',))
            self.assertEqual(replay['reason'],'already_processed')

    def test_public_status_explains_legacy_plan_without_rewriting_it(self):
        from flask import Flask
        from paper_api import paper_api
        app=Flask(__name__); app.register_blueprint(paper_api)
        legacy=planned_order(candidate()); legacy.pop('price_rounding_version')
        legacy.update(candidate()['paper_plan'],waited=4,last_bar_day='2026-10-29')
        original=copy.deepcopy(legacy)
        with patch('paper_storage.storage_health',return_value={'ready':True,'reason':'test'}), \
             patch('paper_disk_probe.probe_database',return_value={
                 'write_verified':True,'retained_from_previous_process':True,
                 'retained_across_code_deploy':True,'reason':'test'}), \
             patch('server_scan.status',return_value={'enabled':True}), \
             patch('daily_paper_runner.summary',return_value={'configured':True,'positions_on_server':True}), \
             patch('daily_paper_runner.waiting_entries',return_value=[legacy]):
            result=app.test_client().get('/api/auto-paper/status').get_json()
        self.assertTrue(result['paper_only'])
        self.assertFalse(result['broker_order_enabled'])
        pending=result['pending_entries'][0]
        self.assertEqual(pending['remaining_sessions'],1)
        self.assertTrue(pending['rounding_pending'])
        self.assertEqual(pending['next_session_levels']['entry'],298)
        self.assertEqual(legacy,original)

    def test_scan_preview_reports_real_admission_instead_of_fixed_false(self):
        import server_scan
        c=candidate('2026-10-29')
        with patch.object(server_scan,'WATCH',('PWON',)), \
             patch.object(server_scan,'_last_date',None), \
             patch.object(server_scan,'_last_attempt_at',None), \
             patch.object(server_scan,'_state',{}):
            server_scan._run_once(lambda t,d:c,datetime(2026,10,30,10,16,tzinfo=ZoneInfo('Asia/Jakarta')))
            preview=server_scan.status()['candidates'][0]
            self.assertTrue(preview['paper_plan_eligible'])
            self.assertNotIn('paper_entry_signal',preview)
            self.assertIn('Lolos',preview['paper_plan_reason'])
