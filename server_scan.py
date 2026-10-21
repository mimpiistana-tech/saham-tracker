"""Lightweight WATCHLIST scan daemon for an existing single-instance Render web app.

Runs a once-per-weekday 10:15 WIB preview, never sends broker orders or opens
paper trades. This preview uses daily OHLCV and is not an intraday entry signal.
Snapshots live in RAM and are explicitly NOT durable across restarts.
"""
import os
import threading
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
RUN_AFTER = time(10, 15)
RUN_BEFORE = time(11, 15)
WATCH = ("BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII",
         "UNTR", "ADRO", "PTBA", "ANTM", "INCO", "BRIS")
_lock = threading.RLock()
_worker = None
_stop = threading.Event()
_last_date = None
_state = {
    "last_attempt_at": None,
    "last_complete_at": None,
    "last_error": None,
    "scan_count": 0,
    "success_count": 0,
    "candidates": [],
}

def due(now, last_date):
    """Only one first-hour preview on Indonesian weekdays."""
    local = now.astimezone(WIB)
    return (local.weekday() < 5 and RUN_AFTER <= local.time().replace(tzinfo=None) < RUN_BEFORE
            and local.date().isoformat() != last_date)

def _run_once(scan_one, now):
    """Execute a bounded snapshot outside the HTTP request thread."""
    global _last_date
    today = now.astimezone(WIB).date().isoformat()
    with _lock:
        if not due(now, _last_date):
            return False
        _last_date = today
        _state["last_attempt_at"] = now.isoformat()
        _state["last_error"] = None
    ranked = []
    failures = 0
    for ticker in WATCH:
        try:
            item = scan_one(ticker, today)
            if isinstance(item, dict) and item.get("ticker") == ticker:
                ranked.append(item)
            else:
                failures += 1
        except Exception:
            failures += 1
    ranked.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    watch = [
        {"ticker": row["ticker"],
         "score": round(float(row.get("score") or 0), 1),
         "setup": str(row.get("setup") or "N/A"),
         "data_asof": today,
         "signal_type": "DAILY_PREVIEW_NOT_ENTRY"}
        for row in ranked[:3]
    ]
    with _lock:
        _state.update(
            last_complete_at=datetime.now(timezone.utc).isoformat(),
            scan_count=len(WATCH),
            success_count=len(ranked),
            candidates=watch,
            last_error=("Data tidak lengkap untuk " + str(failures) + " ticker")
                if failures else None,
        )
    return True

def _loop(scan_one):
    while not _stop.wait(30):
        try:
            _run_once(scan_one, datetime.now(timezone.utc))
        except Exception as exc:
            with _lock:
                _state["last_error"] = "Scan preview gagal: " + type(exc).__name__

def start(scan_one):
    """Must be called once from the Gunicorn worker after app import."""
    global _worker
    if os.environ.get("AUTO_SCAN_ENABLED") != "1":
        return False
    with _lock:
        if _worker and _worker.is_alive():
            return True
        if _stop.is_set():
            _stop.clear()
        _worker = threading.Thread(target=_loop, args=(scan_one,),
                                   name="stockradar-watch-scan", daemon=True)
        _worker.start()
        return True

def status():
    with _lock:
        enabled = os.environ.get("AUTO_SCAN_ENABLED") == "1"
        running = bool(enabled and _worker and _worker.is_alive())
        return {
            "enabled": running,
            "schedule_wib": "Senin–Jumat 10:15–11:15 (satu kali per hari)",
            "universe_size": len(WATCH),
            "watch_only": True,
            "durable": False,
            **dict(_state),
        }
