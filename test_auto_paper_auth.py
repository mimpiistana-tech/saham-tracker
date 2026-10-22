"""Regression tests: paper write routes must reject unauthorized requests."""
import os
import unittest
from unittest.mock import patch
from app import app

class PaperWriteAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_open_disabled(self):
        with patch.dict(os.environ, {"AUTO_PAPER_WRITE_ENABLED": "0"}):
            self.assertEqual(self.client.post("/api/auto-paper/open", json={}).status_code, 503)

    def test_advance_disabled(self):
        with patch.dict(os.environ, {"AUTO_PAPER_WRITE_ENABLED": "0"}):
            self.assertEqual(self.client.post("/api/auto-paper/advance", json={}).status_code, 503)

    def test_open_missing_token(self):
        with patch.dict(os.environ, {"AUTO_PAPER_WRITE_ENABLED": "1", "AUTO_PAPER_WRITE_TOKEN": "a"*40}):
            self.assertEqual(self.client.post("/api/auto-paper/open", json={}).status_code, 403)

    def test_advance_bad_token(self):
        with patch.dict(os.environ, {"AUTO_PAPER_WRITE_ENABLED": "1", "AUTO_PAPER_WRITE_TOKEN": "a"*40}):
            response = self.client.post("/api/auto-paper/advance", json={"ticker":"BBRI","candle":{}},
                                        headers={"X-Auto-Paper-Token":"wrong"})
            self.assertEqual(response.status_code, 403)

    def test_short_server_secret_rejected(self):
        with patch.dict(os.environ, {"AUTO_PAPER_WRITE_ENABLED": "1", "AUTO_PAPER_WRITE_TOKEN": "short"}):
            response = self.client.post("/api/auto-paper/open", json={},
                                        headers={"X-Auto-Paper-Token":"short"})
            self.assertEqual(response.status_code, 403)

if __name__ == "__main__":
    unittest.main()
