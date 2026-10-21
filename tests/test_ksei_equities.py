"""Offline safety tests: a code in a KSEI batch is a registered share only if matched."""
import unittest
from unittest.mock import patch
import app
from ksei_equities import parse_ksei_shares, annotate_reminders


class KSEIRegisteredSharesTests(unittest.TestCase):
    def setUp(self):
        app.CACHE.clear()

    def test_equity_directory_parsing(self):
        html="""<table><thead><tr><th>No</th><th>Kode</th><th>Deskripsi</th></tr></thead>
        <tbody><tr><td>1</td><td>AALI</td><td>ASTRA AGRO LESTARI Tbk</td></tr>
        <tr><td>2</td><td>BBCA</td><td>BANK CENTRAL ASIA Tbk</td></tr>
        <tr><td>3</td><td>BBRI</td><td>BANK RAKYAT INDONESIA Tbk</td></tr>
        <tr><td>4</td><td>BRPT03ACN3</td><td>OBLIGASI</td></tr></tbody></table>"""
        directory=parse_ksei_shares(html,min_rows=3)
        self.assertEqual(directory["AALI"],"ASTRA AGRO LESTARI Tbk")
        self.assertNotIn("BRPT03ACN3",directory)

    def test_incomplete_equity_directory_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_ksei_shares("<table><tr><td>1</td><td>AALI</td><td>Valid</td></tr></table>")

    def test_batch_code_cross_reference(self):
        rows=[{"ticker":None,"candidate_tickers":["AALI","GEMS","XZZZ","AALI"],
               "is_multi_instrument_notice":True,"buy_signal":False}]
        enriched=annotate_reminders(rows,{"AALI":"ASTRA","GEMS":"GOLDEN ENERGY"})
        self.assertEqual([item["ticker"] for item in enriched[0]["verified_equity_codes"]],["AALI","GEMS"])
        self.assertEqual(enriched[0]["other_unverified_codes"],["XZZZ"])
        self.assertIsNone(enriched[0]["ticker"])
        self.assertFalse(enriched[0]["buy_signal"])
        self.assertFalse(enriched[0]["detail_verified"])

    def test_no_verified_codes_when_directory_source_fails(self):
        events=[{"ticker":"NAYZ","candidate_tickers":["NAYZ"],
                 "is_multi_instrument_notice":False,"buy_signal":False}]
        with patch.object(app,"fetch_ksei_reminders",return_value={
            "source_url":"https://web.ksei.co.id/ksei_news/browse",
            "fetched_rows":2,"latest_publication":"2026-10-12","events":events,
        }), patch.object(app,"fetch_ksei_shares",side_effect=RuntimeError("KSEI shares HTTP 500")):
            res=app.app.test_client().get("/api/ca-ksei")
        self.assertEqual(res.status_code,200)
        data=res.get_json()
        self.assertEqual(data["equity_directory_status"],"UNAVAILABLE")
        self.assertFalse(data["events"][0]["ticker_verified"])
        self.assertEqual(data["verified_equity_mentions"],0)
        self.assertFalse(data["buy_signal"])

    def test_successful_crosscheck_never_becomes_buy(self):
        events=[{"ticker":None,"candidate_tickers":["AALI","BRPT"],
                 "is_multi_instrument_notice":True,"buy_signal":False}]
        with patch.object(app,"fetch_ksei_reminders",return_value={
            "source_url":"https://web.ksei.co.id/ksei_news/browse",
            "fetched_rows":2,"latest_publication":"2026-10-12","events":events,
        }), patch.object(app,"fetch_ksei_shares",return_value={"AALI":"ASTRA AGRO LESTARI","BRPT":"BARITO PACIFIC"}):
            res=app.app.test_client().get("/api/ca-ksei")
        data=res.get_json()
        self.assertEqual(res.status_code,200)
        self.assertEqual(data["verified_equity_mentions"],2)
        self.assertFalse(data["events"][0]["detail_verified"])
        self.assertFalse(data["buy_signal"])
