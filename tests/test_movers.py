"""Offline safeguards for movement radar, no external data or trades."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import app
from movers import build_mover


class MoverTests(unittest.TestCase):
    def setUp(self):
        self.now = int(datetime(2026,10,12,7,30,tzinfo=timezone.utc).timestamp())
        self.bar = self.now-600
        self.chart = {
            "meta":{"previousClose":100,"regularMarketPrice":110,"regularMarketTime":self.now-90},
            "timestamp":[self.bar-300,self.bar],
            "indicators":{"quote":[{"close":[108,109],"volume":[10000,20000]}]},
        }

    def test_intraday_change_is_watch_not_entry(self):
        item,error=build_mover("VIVA",self.chart,self.now)
        self.assertIsNone(error)
        self.assertEqual(item["change_pct"],10.0)
        self.assertEqual(item["decision"],"WATCH_ONLY")
        self.assertFalse(item["entry_approved"])

    def test_previous_close_is_required(self):
        self.chart["meta"].pop("previousClose")
        item,error=build_mover("VIVA",self.chart,self.now)
        self.assertIsNone(item)
        self.assertEqual(error,"NO_PREVIOUS_CLOSE")

    def test_yesterday_price_is_rejected(self):
        self.chart["meta"].pop("regularMarketPrice")
        self.chart["timestamp"]=[self.bar-86400]
        self.chart["indicators"]["quote"][0]["close"]=[109]
        item,error=build_mover("VIVA",self.chart,self.now)
        self.assertIsNone(item)
        self.assertEqual(error,"NO_SAME_SESSION_QUOTE")

    def test_endpoint_invalid_mode_cannot_scan(self):
        response=app.app.test_client().get("/api/movers?mode=invalid")
        self.assertEqual(response.status_code,400)

    def test_endpoint_watch_only_with_mock(self):
        now_dt = datetime.now(timezone(timedelta(hours=7)))
        with patch.object(app,"QUICK_SCAN_UNIVERSE",["VIVA"]), \
             patch.object(app.requests,"get") as request_mock:
            today=int(datetime.now(timezone.utc).timestamp())
            response_data=dict(self.chart)
            response_data["timestamp"]=[today-700,today-600]
            response_data["meta"]={"previousClose":100,"regularMarketPrice":110,
                                   "regularMarketTime":today-90}
            request_mock.return_value.status_code=200
            request_mock.return_value.json.return_value={"chart":{"result":[response_data]}}
            result=app.app.test_client().get("/api/movers?mode=quick").get_json()
            self.assertEqual(result["signal"],"WATCH_ONLY")
            self.assertFalse(result["market_data_is_live"])
            self.assertEqual(result["universe_size"],1)
            self.assertEqual(result["movers"][0]["ticker"],"VIVA")


if __name__ == "__main__":
    unittest.main()
