"""KSEI public reminder page: secondary CA-calendar signal, not initial IDX disclosure.

Only read publicly accessible documents with normal HTTP requests. No login,
anti-bot bypass or order placement. If parsing or dates fail, report unavailable.
"""
from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re
import requests

KSEI_URL="https://web.ksei.co.id/ksei_news/browse"
MONTHS={
 "januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,
 "juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12,
 "january":1,"february":2,"march":3,"may":5,"june":6,"july":7,
 "august":8,"october":10,"december":12,
}
DATE_RE=re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")
TITLE_RE=re.compile(r"(?:Reminder\s+(?:Corporate Action|CA)|Corporate Action)",re.I)

# A recording-date notice can list shares, bonds, warrants and government paper.
# Standalone four-letter tokens are only *possible* listed equity tickers.
# Never infer a ticker from the first four letters of a bond identifier.
BATCH_RECORDING_RE=re.compile(r"Reminder\s+Corporate\s+Action\s+Recording\s+Date",re.I)
GENERIC_NOTICE_RE=re.compile(r"Reminder\s+CA\.\s+Pendistribusian",re.I)
STOCK_CODE_RE=re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}(?![A-Za-z0-9])")
NON_TICKER_WORDS={"DATE","KSEI","CASH","INFO","BEGI","HARI","AKSI","HAKJ"}

def possible_equity_codes(title):
    """Exact 4-letter words after the colon; never certify them as equities."""
    if not isinstance(title,str) or ":" not in title:
        return []
    tail=title.split(":",1)[1]
    results=[]
    for code in STOCK_CODE_RE.findall(tail):
        if code not in NON_TICKER_WORDS and code not in results:
            results.append(code)
    return results[:60]


class ListItems(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth=0
        self.current=None
        self.in_a=False
        self.link=None
        self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag=="li":
            if self.depth==0:
                self.current={"text":[],"links":[]}
            self.depth+=1
        if tag=="a" and self.depth and self.current is not None:
            self.in_a=True
            self.link={"href":dict(attrs).get("href",""),"text":[]}
    def handle_data(self,data):
        if self.depth and self.current is not None:
            self.current["text"].append(data)
            if self.in_a and self.link is not None:
                self.link["text"].append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.in_a and self.link is not None and self.current is not None:
            self.current["links"].append({"href":self.link["href"],
                                          "text":" ".join(" ".join(self.link["text"]).split())})
            self.link=None
            self.in_a=False
        if tag=="li" and self.depth:
            self.depth-=1
            if self.depth==0 and self.current is not None:
                self.current["text"]=" ".join(" ".join(self.current["text"]).split())
                self.items.append(self.current)
                self.current=None
                self.link=None
                self.in_a=False

def date_in_text(text):
    match=DATE_RE.search(text or "")
    if not match:
        return None
    month=MONTHS.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)),month,int(match.group(1)))
    except ValueError:
        return None

def parse_ksei_news(html,now=None,max_age_days=14):
    if not isinstance(html,str) or not html.strip():
        raise ValueError("KSEI mengirim dokumen kosong")
    parser=ListItems()
    parser.feed(html)
    now=now or datetime.now(timezone(timedelta(hours=7)))
    today=now.astimezone(timezone(timedelta(hours=7))).date()
    events=[]
    unique=set()
    seen_dates=[]
    for item in parser.items:
        day=date_in_text(item["text"][:150])
        if day:
            seen_dates.append(day)
        if not day or day>today or (today-day).days>max_age_days:
            continue
        for link in item["links"]:
            title=link["text"]
            if not TITLE_RE.search(title):
                continue
            url=urljoin(KSEI_URL,link["href"])
            parsed=urlparse(url)
            if parsed.scheme!="https" or parsed.hostname not in ("web.ksei.co.id","www.ksei.co.id","ksei.co.id"):
                continue
            key=(title,url,day.isoformat())
            if key in unique:
                continue
            unique.add(key)
            candidates=possible_equity_codes(title)
            is_batch=bool(BATCH_RECORDING_RE.search(title))
            is_generic=bool(GENERIC_NOTICE_RE.search(title))
            # Single-code titles are suggestions only; no evidence of share class
            # or action specifics without opening the original announcement.
            one_code=candidates[0] if len(candidates)==1 and not is_batch else None
            events.append({
                "ticker":one_code,
                "candidate_tickers":candidates,
                "ticker_verified":False,
                "is_multi_instrument_notice":is_batch,
                "category":("KSEI_RECORD_DATE_BATCH" if is_batch else
                            "KSEI_OPERATIONS" if is_generic else "KSEI_REMINDER"),
                "title":title[:600],
                "published_at":day.isoformat(),"source":"KSEI PUBLIC REMINDER",
                "url":url,"status":"PENGINGAT_CA_BUKAN_PENGUMUMAN_AWAL",
                "detail_verified":False,"buy_signal":False,
            })
    newest=max(seen_dates) if seen_dates else None
    events=sorted(events,key=lambda x:x["published_at"],reverse=True)[:30]
    candidate_tickers=sorted({
        ticker for item in events for ticker in item["candidate_tickers"]
    })
    return {
        "events":events,
        "possible_equity_codes":candidate_tickers,
        "possible_equity_count":len(candidate_tickers),
        "fetched_rows":len(parser.items),
        "latest_publication":newest.isoformat() if newest else None,
        "source_url":KSEI_URL,
        "is_stale":not newest or (today-newest).days>max_age_days,
        "coverage_note":"Kode 4 huruf hanya kandidat dari pengingat, belum validasi saham BEI.",
    }

def fetch_ksei_reminders():
    response=requests.get(
        KSEI_URL,
        headers={"User-Agent":"Mozilla/5.0 (compatible; StockRadar/2.0; public-CA-monitor)",
                 "Accept":"text/html"},
        timeout=15,
    )
    if response.status_code!=200:
        raise RuntimeError("KSEI HTTP "+str(response.status_code))
    result=parse_ksei_news(response.text)
    if result["fetched_rows"]<1 or result["is_stale"]:
        raise RuntimeError("KSEI NEWS STALE atau format tidak terbaca; "
                           "latest="+str(result["latest_publication"]))
    return result
