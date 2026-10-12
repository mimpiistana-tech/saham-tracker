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
            match=re.search(r":\s*([A-Z]{4})\s*$",title)
            events.append({
                "ticker":match.group(1) if match else None,
                "category":"KSEI_REMINDER","title":title[:250],
                "published_at":day.isoformat(),"source":"KSEI PUBLIC REMINDER",
                "url":url,"status":"PENGINGAT_CA_BUKAN_PENGUMUMAN_AWAL",
                "detail_verified":False,"buy_signal":False,
            })
    newest=max(seen_dates) if seen_dates else None
    return {
        "events":sorted(events,key=lambda x:x["published_at"],reverse=True)[:30],
        "fetched_rows":len(parser.items),
        "latest_publication":newest.isoformat() if newest else None,
        "source_url":KSEI_URL,
        "is_stale":not newest or (today-newest).days>max_age_days,
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
