"""Validate four-letter equity codes against KSEI's public registered-share list.

Membership verifies *the security type*, not the corporate action, announcement
timing, price move or investment opportunity.
"""
from html.parser import HTMLParser
import re
import requests

SHARES_URL = "https://web.ksei.co.id/services/registered-securities/shares?setLocale=id-ID"


class KSEISharesTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_row = False
        self.in_cell = False
        self.rows = []
        self.cells = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_row = True
            self.cells = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.parts = []

    def handle_data(self, data):
        if self.in_cell:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.cells.append(" ".join(" ".join(self.parts).split()))
            self.in_cell = False
            self.parts = []
        elif tag == "tr" and self.in_row:
            if self.cells:
                self.rows.append(self.cells)
            self.cells = []
            self.in_row = False


def parse_ksei_shares(html, min_rows=200):
    if not isinstance(html, str) or not html.strip():
        raise ValueError("KSEI daftar saham kosong")
    parser = KSEISharesTable()
    parser.feed(html)
    equities = {}
    for row in parser.rows:
        # Official list: No | Code | Description | Transfer Agent | Nominal
        if len(row) < 3:
            continue
        number, ticker, issuer = row[:3]
        if not number.isdigit() or not re.fullmatch(r"[A-Z]{4}", ticker):
            continue
        if not issuer or len(issuer) > 180:
            continue
        equities[ticker] = issuer[:180]
    # Critical guard against silent mis-parses and incomplete pages.
    if len(equities) < min_rows or not {"AALI", "BBRI", "BBCA"}.issubset(equities):
        raise ValueError("Daftar saham KSEI tidak lengkap; validasi ditolak")
    return equities


def fetch_ksei_shares():
    response = requests.get(
        SHARES_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; StockRadar/2.0; informational research)",
                 "Accept": "text/html"},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError("KSEI shares HTTP " + str(response.status_code))
    return parse_ksei_shares(response.text)


def annotate_reminders(events, equities):
    """Match candidate 4-letter tokens to registered shares, not to CA type."""
    if not isinstance(events, list) or not isinstance(equities, dict):
        raise ValueError("Data validasi saham tidak lengkap")
    results = []
    for item in events:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        tokens = item.get("candidate_tickers") or []
        codes = sorted({c for c in tokens if isinstance(c, str)
                        and re.fullmatch(r"[A-Z]{4}", c)})
        matches = [{"ticker": code, "issuer": equities[code]} for code in codes if code in equities]
        entry["verified_equity_codes"] = matches
        entry["other_unverified_codes"] = [code for code in codes if code not in equities]
        entry["ticker_directory_checked"] = True
        entry["ticker_verified"] = bool(
            len(matches) == 1 and len(codes) == 1 and not item.get("is_multi_instrument_notice")
        )
        # Avoid ambiguous parent ticker for multi-instrument recordings.
        entry["ticker"] = matches[0]["ticker"] if entry["ticker_verified"] else None
        entry["detail_verified"] = False
        entry["buy_signal"] = False
        results.append(entry)
    return results
