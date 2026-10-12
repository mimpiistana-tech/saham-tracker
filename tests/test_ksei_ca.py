"""KSEI backup must never promote reminders to initial disclosure or BUY."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from ksei_ca import parse_ksei_news
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
