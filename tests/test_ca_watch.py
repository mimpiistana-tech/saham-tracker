"""Corporate action ticker watch is user-curated and NEVER verifies corporate actions."""
import unittest
from unittest.mock import patch
import app


class CorporateActionWatchTests(unittest.TestCase):
    def setUp(self):
        app.CACHE.clear()
        self.client=app.app.test_client()

    def test_empty_ca_watch_rejected(self):
        result=self.client.get("/api/movers?mode=ca")
        self.assertEqual(result.status_code,400)

    def test_bad_symbol_rejected(self):
        for value in ("../../", "VIVA;DROP", "WAYTOOLONG", "FOO.JK", "VIVA,,"):
            result=self.client.get("/api/movers",query_string={"mode":"ca","tickers":value})
            self.assertEqual(result.status_code,400,value)

    def test_large_ca_watch_rejected(self):
        tickers=",".join("T"+str(i) for i in range(16))
        result=self.client.get("/api/movers",query_string={"mode":"ca","tickers":tickers})
        self.assertEqual(result.status_code,400)

    def test_read_only_ca_mode_scans_only_selected_tickers(self):
        with patch.object(app.requests,"get") as mock:
            mock.return_value.status_code=503
            res=self.client.get("/api/movers?mode=ca&tickers=VIVA,DOOH,VIVA")
            data=res.get_json()
            self.assertEqual(res.status_code,200)
            self.assertEqual(data["mode"],"ca")
            self.assertEqual(data["universe_size"],2)
            self.assertEqual(mock.call_count,2)
            self.assertEqual(data["signal"],"WATCH_ONLY")
            self.assertFalse(data["market_data_is_live"])
            self.assertEqual(data["movers"],[])
            self.assertEqual(data["missing"],2)
            self.assertFalse("ca_verified" in data)


if __name__=="__main__":
    unittest.main()
