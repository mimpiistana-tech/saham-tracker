"""KSEI backup must never promote reminders to initial disclosure or BUY."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from ksei_ca import parse_ksei_news, possible_equity_codes
import app

class KSEICATests(unittest.TestCase):
    def setUp(self):
        app.CACHE.clear()
    def test_reminder_parsing(self):
        body='<ul><li>12 Oktober 2026 <a href="/some-public-file">Reminder Corporate Action: NAYZ</a></li></ul>'
        data=parse_ksei_news(body,now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=7))))
        self.assertEqual(len(data["events"]),1)
        self.assertEqual(data["events"][0]["ticker"],"NAYZ")
        self.assertFalse(data["events"][0]["buy_signal"])
        self.assertEqual(data["events"][0]["category"],"KSEI_REMINDER")
    def test_mixed_security_codes_not_assumed_to_be_stock(self):
        title="Reminder Corporate Action Recording Date : BRPT03ACN3 GEM S AALI PRNS33XXMF RDTX"
        self.assertEqual(possible_equity_codes(title),["AALI","RDTX"])
        html='<ul><li>12 Oktober 2026 <a href="/reminder">'+title+'</a></li></ul>'
        result=parse_ksei_news(html,now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=7))))
        item=result["events"][0]
        self.assertIsNone(item["ticker"])
        self.assertTrue(item["is_multi_instrument_notice"])
        self.assertFalse(item["ticker_verified"])

    def test_single_ticker_is_only_candidate(self):
        html='<ul><li>12 Oktober 2026 <a href="/item">Reminder Corporate Action: NAYZ</a></li></ul>'
        item=parse_ksei_news(html,now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=7))))["events"][0]
        self.assertEqual(item["ticker"],"NAYZ")
        self.assertFalse(item["ticker_verified"])
        self.assertFalse(item["buy_signal"])

    def test_stale_rejected(self):
        body='<ul><li>1 Januari 2020 <a href="/item">Reminder Corporate Action: NAYZ</a></li></ul>'
        data=parse_ksei_news(body,now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=7))))
        self.assertEqual(data["events"],[])
        self.assertTrue(data["is_stale"])
    def test_forged_domain_ignored(self):
        body='<ul><li>12 Oktober 2026 <a href="https://fraud.example/ca">Reminder Corporate Action: NAYZ</a></li></ul>'
        data=parse_ksei_news(body,now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=7))))
        self.assertEqual(data["events"],[])
    def test_offline_endpoint_failure(self):
        with patch.object(app,"fetch_ksei_reminders",side_effect=RuntimeError("KSEI HTTP 403")):
            result=app.app.test_client().get("/api/ca-ksei")
        self.assertEqual(result.status_code,503)
        self.assertFalse(result.get_json()["buy_signal"])
    def test_offline_endpoint_success(self):
        with patch.object(app,"fetch_ksei_reminders",return_value={
            "source_url":"https://web.ksei.co.id/ksei_news/browse",
            "fetched_rows":5,"latest_publication":"2026-10-12","events":[],
        }):
            result=app.app.test_client().get("/api/ca-ksei")
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.get_json()["initial_disclosure"])
