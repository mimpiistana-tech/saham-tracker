"""IDX announcement discovery: headline-level WATCH, never a trading signal.

Only official IDX origin, bounded page, explicit failure for inaccessible sources.
No bypass of website access restrictions. No background trading or price prediction.
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests

IDX_BASE = "https://www.idx.co.id"
IDX_ANNOUNCEMENTS = IDX_BASE + "/primary/NewsAnnouncement/GetAllAnnouncement"
IDX_LIST = IDX_BASE + "/id/berita/pengumuman/"

CATEGORIES = (
    ("RIGHTS_ISSUE", re.compile(r"\bhmetd\b|hak memesan efek|rights?\s+issue|penawaran umum terbatas", re.I)),
    ("PRIVATE_PLACEMENT", re.compile(r"tanpa\s+hmetd|private placement", re.I)),
    ("MERGER_AKUISISI", re.compile(r"merger|penggabungan usaha|peleburan usaha|akuisisi|pengambilalihan|perubahan\s+(?:dalam\s+)?pengendalian", re.I)),
    ("SAHAM_BONUS", re.compile(r"saham bonus|bonus shares?", re.I)),
    ("STOCK_SPLIT", re.compile(r"stock split|reverse stock|pemecahan saham|penggabungan nilai nominal saham", re.I)),
    ("DIVIDEN", re.compile(r"dividen|dividend", re.I)),
    ("BUYBACK", re.compile(r"buyback|pembelian kembali saham", re.I)),
    ("RUPS", re.compile(r"\brupst?\b|\brupslb\b|rapat umum pemegang saham", re.I)),
    ("WARAN", re.compile(r"waran|warrant", re.I)),
    ("PMTHMETD", re.compile(r"penambahan modal|penerbitan saham baru", re.I)),
)
# Order matters: tanpa HMETD must not be misclassified as rights issue.
def classify(title):
    text = str(title or "")
    if re.search(r"tanpa\s+hmetd|private placement", text, re.I):
        return "PRIVATE_PLACEMENT"
    for category, pattern in CATEGORIES:
        if pattern.search(text):
            return category
    return None

def extract_rows(payload):
    if not isinstance(payload, dict):
        raise ValueError("IDX JSON root tidak sesuai skema")
    for key in ("Replies", "replies", "data", "Data", "items", "Items", "results", "Results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ("data", "items", "Replies"):
                if isinstance(value.get(nested), list):
                    return value[nested]
    raise ValueError("IDX mengubah bentuk daftar pengumuman")

def official_link(row):
    attachments = row.get("attachments") or row.get("Attachments") or []
    for att in attachments if isinstance(attachments, list) else []:
        if not isinstance(att, dict):
            continue
        url = str(att.get("FullSavePath") or att.get("url") or att.get("Url") or "").strip()
        if not url:
            continue
        if url.startswith("/"):
            url = IDX_BASE + url
        parsed=urlparse(url)
        if parsed.scheme == "https" and parsed.hostname in ("www.idx.co.id","idx.co.id"):
            return url
    return IDX_LIST

def normalize_date(value):
    if value is None:
        return None
    text=str(value).strip()
    if not text:
        return None
    # Microsoft JSON dates may appear as /Date(1712345678000)/
    ms=re.match(r"^/Date\((\d+)", text)
    if ms:
        try:
            return datetime.fromtimestamp(int(ms.group(1))/1000,timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    iso=text.replace("Z","+00:00")
    try:
        return datetime.fromisoformat(iso).isoformat()
    except ValueError:
        return None

def parse_feed(payload, now=None, max_age_days=14):
    now = now or datetime.now(timezone.utc)
    records=[]
    seen=set()
    for row in extract_rows(payload):
        if not isinstance(row,dict):
            continue
        detail=row.get("pengumuman") if isinstance(row.get("pengumuman"),dict) else row
        title=str(detail.get("JudulPengumuman") or detail.get("Title") or detail.get("title") or detail.get("PerihalPengumuman") or detail.get("subject") or "").strip()
        category=classify(title)
        ticker=str(detail.get("Kode_Emiten") or detail.get("KodeEmiten") or detail.get("code") or detail.get("ticker") or "").strip().upper()
        if not category or not re.fullmatch(r"[A-Z]{4,5}",ticker):
            continue
        date=normalize_date(detail.get("TglPengumuman") or detail.get("publishedAt") or detail.get("PublishedDate") or detail.get("date"))
        if not date:
            continue
        try:
            published=datetime.fromisoformat(date)
            if published.tzinfo is None:
                published=published.replace(tzinfo=timezone(timedelta(hours=7)))
            age=now-published.astimezone(timezone.utc)
            if age < timedelta(hours=-2) or age > timedelta(days=max_age_days):
                continue
        except (ValueError,TypeError):
            continue
        number=str(detail.get("NoPengumuman") or detail.get("announcementNo") or detail.get("Id2") or detail.get("id") or "")
        key=(ticker,title,date,number)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "ticker":ticker,"category":category,"title":title[:250],
            "published_at":published.isoformat(),"announcement_number":number[:100],
            "source":"IDX OFFICIAL - ANNOUNCEMENT HEADLINE",
            "url":official_link(row),"status":"PENGUMUMAN_TERDETEKSI",
            "detail_verified":False,"buy_signal":False,
        })
    records.sort(key=lambda x:x["published_at"],reverse=True)
    return records

def fetch_idx_announcements():
    response=requests.get(
        IDX_ANNOUNCEMENTS,
        params={"keywords":"","pageNumber":1,"pageSize":100,"lang":"id"},
        headers={"User-Agent":"Mozilla/5.0 (compatible; StockRadar/2.0; informational research)",
                 "Accept":"application/json",
                 "Referer":IDX_LIST},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError("IDX HTTP "+str(response.status_code))
    if "html" in response.headers.get("Content-Type","").lower():
        raise RuntimeError("IDX mengembalikan HTML, bukan JSON")
    try:
        payload=response.json()
    except ValueError as exc:
        raise RuntimeError("IDX tidak mengirim JSON valid") from exc
    rows=extract_rows(payload)
    events=parse_feed(payload)
    return {"events":events,"fetched_rows":len(rows),
            "newest_in_window":len(events),"source_url":IDX_LIST}
