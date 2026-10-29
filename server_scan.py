"""StockRadar's daily watchlist and daily-bar paper runner.

One background daemon thread on our existing paid web instance checks a bounded
set of Indonesian stocks from the LAST COMPLETED daily session, after 10:15 WIB
on weekdays. Paper entries and exits are evaluated from completed daily bars.

Scanner state is in-memory and lost on service restart. The paper runner
persists daily-bar simulations separately. No live order or IndexAlpha quota.
"""
import math
import os
import threading
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
RUN_AFTER = time(10, 15)
RUN_BEFORE = time(11, 15)
RETRY_SECONDS = 600
# Union of the existing V3 watchlist and V2 Quick Scan (unique tickers).
WATCH = ("BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "TLKM", "ASII", "UNTR",
         "ANTM", "PTBA", "ADRO", "INCO", "BRMS", "ERAA", "PANI", "PWON",
         "GOTO", "NAYZ", "PIPA", "RANS", "MEJA", "ARCI", "ADMR")
_lock = threading.RLock()
_worker = None
_stop = threading.Event()
_last_date = None
_last_attempt_at = None
_state = {
    "last_attempt_at": None,
    "last_complete_at": None,
    "last_session_asof": None,
    "last_error": None,
    "scan_count": 0,
    "success_count": 0,
    "candidates": [],
}

def due(now, last_date):
    """Daily 10:15-11:15 WIB window, Monday-Friday. No public holidays lookup."""
    local = now.astimezone(WIB)
    clock = local.time().replace(tzinfo=None)
    return (local.weekday() < 5 and RUN_AFTER <= clock < RUN_BEFORE
            and local.date().isoformat() != last_date)

def _run_once(scan_one, now, on_scan=None):
    """One bounded watchlist scan; never creates a trading position."""
    global _last_date, _last_attempt_at
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    local = now.astimezone(WIB)
    today = local.date().isoformat()
    # Previous session as an upper bound. Monday automatically includes Friday.
    closed_until = (local.date() - timedelta(days=1)).isoformat()
    with _lock:
        if not due(now, _last_date):
            return False
        if (_last_attempt_at is not None
                and (now - _last_attempt_at).total_seconds() < RETRY_SECONDS):
            return False
        _last_attempt_at = now
        _state["last_attempt_at"] = now.astimezone(timezone.utc).isoformat()
        _state["last_error"] = None

    ranked = []
    failures = 0
    for ticker in WATCH:
        try:
            item = scan_one(ticker, closed_until)
            if not isinstance(item, dict) or item.get("ticker") != ticker:
                failures += 1
                continue
            signal_day = str(item.get("signal_date") or "")
            parsed = datetime.strptime(signal_day, "%Y-%m-%d").date()
            # Reject suspicious future or very old market data.
            if not (local.date() - timedelta(days=9) <= parsed < local.date()):
                failures += 1
                continue
            score = float(item.get("score"))
            if not math.isfinite(score):
                failures += 1
                continue
            ranked.append((score, item))
        except (ValueError, TypeError, OverflowError, OSError):
            failures += 1
        except Exception:
            failures += 1
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    if on_scan is not None:
        try:
            on_scan([item for _, item in ranked], closed_until)
        except Exception as exc:
            print("[StockRadar Auto Paper] callback error: "+type(exc).__name__, flush=True)

    watch = [
        {"ticker": row["ticker"], "score": round(score, 1),
         "setup": str(row.get("setup") or "Netral"),
         "signal_date": str(row["signal_date"]),
         "source": "PREVIOUS_COMPLETED_DAILY_BAR",
         "paper_entry_signal": False}
        for score, row in ranked[:3]
    ]
    with _lock:
        _state.update(
            last_complete_at=datetime.now(timezone.utc).isoformat(),
            last_session_asof=closed_until,
            scan_count=len(WATCH),
            success_count=len(ranked),
            candidates=watch,
            last_error=("Gagal validasi / data kosong pada " + str(failures)
                        + " ticker") if failures else None,
        )
        if ranked:
            _last_date = today
    return True

def _loop(scan_one, on_scan=None):
    # Daily scan and completed-daily-bar paper processing share one worker.
    while not _stop.is_set():
        now = datetime.now(timezone.utc)
        try:
            _run_once(scan_one, now, on_scan)
        except Exception as exc:
            with _lock:
                _state["last_error"] = "Scan preview gagal: " + type(exc).__name__
        _stop.wait(30)

def start(scan_one, on_scan=None):
    """Run once per Gunicorn worker. Render currently uses one worker."""
    global _worker
    if os.environ.get("AUTO_SCAN_ENABLED", "").strip() != "1":
        print("[StockRadar Watch] disabled: AUTO_SCAN_ENABLED not set to 1", flush=True)
        return False
    with _lock:
        if _worker and _worker.is_alive():
            return True
        _stop.clear()
        _worker = threading.Thread(target=_loop, args=(scan_one,on_scan),
                                   name="stockradar-watch-scan", daemon=True)
        _worker.start()
        print("[StockRadar Watch] worker_started=" + str(_worker.is_alive()), flush=True)
        return True

def status():
    with _lock:
        enabled = os.environ.get("AUTO_SCAN_ENABLED", "").strip() == "1"
        alive = bool(_worker and _worker.is_alive())
        running = bool(enabled and alive)
        return {
            "enabled": running,
            "configured": enabled,
            "worker_created": _worker is not None,
            "worker_alive": alive,
            "schedule_wib": "Senin-Jumat 10:15-11:15 WIB, sekali per hari",
            "universe_size": len(WATCH),
            "watch_only": True,
            "paper_entry_mode": "completed_daily_bar_touch",
            "durable": False,
            "next_check_is_not_guaranteed": True,
            **dict(_state),
        }
