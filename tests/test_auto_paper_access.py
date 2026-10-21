"""Offline safety checks: no external network, DB, or brokerage needed."""
import unittest
from auto_paper_access import paper_admin_authorized

TOKEN = "a" * 32


class PaperAccessTests(unittest.TestCase):
    def test_missing_configuration_denied(self):
        self.assertFalse(paper_admin_authorized({"Authorization": f"Bearer {TOKEN}"}, {}))

    def test_short_configuration_denied(self):
        self.assertFalse(paper_admin_authorized({"Authorization": "Bearer short"}, {"AUTO_PAPER_ADMIN_TOKEN": "short"}))

    def test_missing_header_denied(self):
        self.assertFalse(paper_admin_authorized({}, {"AUTO_PAPER_ADMIN_TOKEN": TOKEN}))

    def test_wrong_token_denied(self):
        self.assertFalse(paper_admin_authorized({"Authorization": "Bearer " + "b" * 32}, {"AUTO_PAPER_ADMIN_TOKEN": TOKEN}))

    def test_malformed_scheme_denied(self):
        self.assertFalse(paper_admin_authorized({"Authorization": "Basic " + TOKEN}, {"AUTO_PAPER_ADMIN_TOKEN": TOKEN}))

    def test_valid_token_accepted(self):
        self.assertTrue(paper_admin_authorized({"Authorization": "Bearer " + TOKEN}, {"AUTO_PAPER_ADMIN_TOKEN": TOKEN}))


if __name__ == "__main__":
    unittest.main()
