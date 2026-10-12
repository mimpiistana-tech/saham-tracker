"""CA discovery must fail closed, never fabricate announcements or signal BUY."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from idx_ca import classify, parse_feed, extract_rows
import app


class CADiscoveryTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(classify("Rencana PMTHMETD tanpa HMETD private placement"),"PRIVATE_PLACEMENT")
        self.assertEqual(classify("Rencana Penawaran Umum Terbatas HMETD"),"RIGHTS_ISSUE")
        self.assertEqual(classify("Pembagian Dividen Tunai"),"DIVIDEN")
        self.assertIsNone(classify("Pengumuman perdagangan reguler"))

    def test_parse_only_with_ticker_date_and_official_headline(self):
        payload={"Replies":[
            {"KodeEmiten":"NAYZ","JudulPengumuman":"Rencana HMETD","TglPengumuman":"2026-10-12T10:00:00+07:00"},
            {"KodeEmiten":"MEJA","JudulPengumuman":"Merger","TglPengumuman":"2020-01-01"},
            {"KodeEmiten":"","JudulPengumuman":"Dividen","TglPengumuman":"2026-10-12T10:00:00+07:00"},
        ]}
        rows=parse_feed(payload,now=datetime(2026,10,12,9,0,tzinfo=timezone.utc))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["ticker"],"NAYZ")
        self.assertFalse(rows[0]["buy_signal"])
        self.assertFalse(rows[0]["detail_verified"])

    def test_unknown_shape_rejected(self):
        with self.assertRaises(ValueError):
            extract_rows({"message":"blocked"})

    def test_endpoint_inaccessible_source_returns_error(self):
        app.CACHE.clear()
        with patch.object(app,"fetch_idx_announcements",side_effect=RuntimeError("IDX HTTP 403")):
            response=app.app.test_client().get("/api/ca-discovery")
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.get_json()["status"],"SOURCE_UNAVAILABLE")

    def test_endpoint_verified_nonempty_feed_is_watch_only(self):
        app.CACHE.clear()
        with patch.object(app,"fetch_idx_announcements",return_value={
            "fetched_rows":1,"events":[{"ticker":"NAYZ","category":"RIGHTS_ISSUE","buy_signal":False}],
        }):
            response=app.app.test_client().get("/api/ca-discovery")
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.get_json()["buy_signal"])


if __name__=="__main__":
    unittest.main()
