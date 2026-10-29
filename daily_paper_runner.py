"""StockRadar daily PAPER-only runner on the mounted SQLite disk.

Invoked from the existing daily WATCH scanner. No broker API or live orders.
All DB changes are transactional; unique ids prevent double simulation fills.
Runs on completed Yahoo daily bars, never on today's unclosed candle.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from daily_paper_logic import apply_bar, good_bar, planned_order
from paper_storage import storage_health

WIB = ZoneInfo("Asia/Jakarta")
STATUSES = ("WAIT_ENTRY", "OPEN", "TP1_HIT")
LAST = {"last_success": None, "last_error": None, "created": 0, "advanced": 0, "valid_tickers": 0}

def enabled():
    return os.environ.get("AUTO_PAPER_ENABLED", "").strip() == "1"

def _connection():
    h = storage_health()
    if not h["ready"]:
        raise RuntimeError("durable_disk_" + h["reason"])
    db = sqlite3.connect(os.environ["AUTO_PAPER_DB_PATH"], timeout=15)
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_paper_trades (
        id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
        status TEXT NOT NULL, payload TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_paper_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT NOT NULL,
        session_date TEXT NOT NULL, event TEXT NOT NULL,
        payload TEXT NOT NULL, UNIQUE(signal_id,session_date,event))""")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_paper_cycles (
        session_cutoff TEXT PRIMARY KEY, finished_at TEXT NOT NULL,
        valid_tickers INTEGER NOT NULL, created INTEGER NOT NULL,
        advanced INTEGER NOT NULL)""")
    db.commit()
    return db

def _safe_bars(raw, cutoff, ticker):
    """Keep only complete historical candles, dedupe by date, require fresh data."""
    if not isinstance(raw, list):
        return []
    cutoff_day = date.fromisoformat(cutoff)
    unique = {}
    for candle in raw:
        if not good_bar(candle):
            continue
        day = date.fromisoformat(candle["date"])
        if day <= cutoff_day and cutoff_day - day <= timedelta(days=180):
            unique[day.isoformat()] = {
                "date":day.isoformat(), "open":float(candle["open"]),
                "high":float(candle["high"]), "low":float(candle["low"]),
                "close":float(candle["close"]), "volume":float(candle["volume"])}
    result = [unique[k] for k in sorted(unique)]
    if not result or (cutoff_day - date.fromisoformat(result[-1]["date"])).days > 7:
        return []
    return result

def run_cycle(items, cutoff, load_bars, *, watch):
    """Run on a weekday after 10:15 WIB; skipped entirely when disabled.

    No backfilling imaginary orders from a signal day. Existing positions
    replay ONLY subsequent known daily candles, in chronological order.
    """
    if not enabled():
        return {"ran":False,"reason":"disabled"}
    cutoff_day = date.fromisoformat(cutoff)
    local_today = datetime.now(timezone.utc).astimezone(WIB).date()
    if not local_today > cutoff_day or (local_today-cutoff_day).days > 7:
        return {"ran":False,"reason":"invalid_cutoff"}
    try:
        if not storage_health()["ready"]:
            return {"ran":False,"reason":"durable_disk_unavailable"}
        candidates = {c["ticker"]:c for c in items if isinstance(c,dict) and c.get("ticker") in watch}
        bars_by_ticker = {}
        for ticker in watch:
            try:
                bars = _safe_bars(load_bars(ticker, cutoff),cutoff,ticker)
                if bars:
                    bars_by_ticker[ticker] = bars
            except Exception:
                # Unavailable market data must never produce a simulated fill.
                continue
        if not bars_by_ticker:
            return {"ran":False,"reason":"no_verified_daily_bars"}
        with closing(_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM daily_paper_cycles WHERE session_cutoff=?", (cutoff,)).fetchone():
                conn.rollback()
                return {"ran":False,"reason":"already_processed"}
            created, advanced = 0, 0
            for ticker, candles in bars_by_ticker.items():
                old_rows = conn.execute(
                    "SELECT id,payload FROM daily_paper_trades WHERE ticker=? AND status IN (?,?,?)",
                    (ticker,*STATUSES)).fetchall()
                for sid,payload in old_rows:
                    order = json.loads(payload)
                    for bar in candles:
                        next_order, event = apply_bar(order,bar)
                        if next_order == order:
                            continue
                        order = next_order
                        advanced += 1
                        conn.execute(
                            "INSERT OR IGNORE INTO daily_paper_events "
                            "(signal_id,session_date,event,payload) VALUES (?,?,?,?)",
                            (sid,bar["date"],event,json.dumps(order)))
                    conn.execute("UPDATE daily_paper_trades SET status=?,payload=? WHERE id=?",
                                 (order["status"],json.dumps(order),sid))
                item = candidates.get(ticker)
                if item is None:
                    continue
                # Ensure timestamp exactly matches the last usable closed session.
                if item.get("signal_date") != candles[-1]["date"]:
                    continue
                plan = planned_order(item)
                if plan is None:
                    continue
                if conn.execute("SELECT 1 FROM daily_paper_trades WHERE id=?", (plan["signal_id"],)).fetchone():
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM daily_paper_trades WHERE ticker=? AND status IN (?,?,?)",
                    (ticker,*STATUSES)).fetchone()
                if existing:
                    continue
                opened = conn.execute(
                    "SELECT payload FROM daily_paper_trades WHERE status IN (?,?,?)",
                    STATUSES).fetchall()
                if len(opened) >= 3:
                    continue
                committed_value = sum(
                    float(json.loads(x[0]).get("paper_value") or 0) for x in opened)
                if committed_value + plan["paper_value"] > 10_000_000:
                    continue
                conn.execute(
                    "INSERT INTO daily_paper_trades (id,ticker,status,payload) VALUES (?,?,?,?)",
                    (plan["signal_id"],ticker,plan["status"],json.dumps(plan)))
                conn.execute(
                    "INSERT OR IGNORE INTO daily_paper_events "
                    "(signal_id,session_date,event,payload) VALUES (?,?,?,?)",
                    (plan["signal_id"],plan["signal_day"],"PAPER_PLAN",json.dumps(plan)))
                created += 1
            conn.execute(
                "INSERT INTO daily_paper_cycles VALUES (?,?,?,?,?)",
                (cutoff,datetime.now(timezone.utc).isoformat(),len(bars_by_ticker),created,advanced))
            conn.commit()
        LAST.update(last_success=datetime.now(timezone.utc).isoformat(),
                    last_error=None,created=created,advanced=advanced,valid_tickers=len(bars_by_ticker))
        print("[StockRadar Auto Paper] cycle completed (simulation only)",flush=True)
        return {"ran":True,"created":created,"advanced":advanced,"verified_tickers":len(bars_by_ticker)}
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as e:
        LAST["last_error"] = type(e).__name__
        print("[StockRadar Auto Paper] cycle failed: "+type(e).__name__,flush=True)
        return {"ran":False,"reason":"storage_or_validation_failure"}


def waiting_entries():
    """Return bounded active WAIT_ENTRY plans from the persistent paper journal."""
    if not enabled() or not storage_health()["ready"]:
        return []
    try:
        with closing(_connection()) as conn:
            rows = conn.execute(
                "SELECT ticker,payload FROM daily_paper_trades WHERE status='WAIT_ENTRY' ORDER BY rowid LIMIT 3"
            ).fetchall()
        return [json.loads(payload) for _, payload in rows]
    except (sqlite3.Error, OSError, RuntimeError, ValueError):
        return []


def open_intraday_entry(ticker, signal, *, now=None):
    """Open a stored paper plan only after a fresh V2-style 5m trigger confirms it."""
    if not enabled() or not storage_health()["ready"]:
        return {"opened": False, "reason": "paper_disabled_or_storage_unavailable"}
    ticker = str(ticker or "").upper()
    if not isinstance(signal, dict) or signal.get("qualified") is not True:
        return {"opened": False, "reason": "entry_not_confirmed"}
    if (signal.get("paper_only") is not True or
            signal.get("source") != "YAHOO_5M_INDICATIVE" or
            str(signal.get("ticker", "")).upper() != ticker):
        return {"opened": False, "reason": "untrusted_entry_source"}
    checks = signal.get("checks")
    required_checks = ("green", "break_previous_high", "higher_low",
                       "volume_1_3x", "entry_touched", "close_at_or_above_entry")
    try:
        volume_ratio = float(signal.get("volume_ratio"))
    except (TypeError, ValueError, OverflowError):
        volume_ratio = 0.0
    if (not isinstance(checks, dict) or
            any(checks.get(name) is not True for name in required_checks) or
            volume_ratio < 1.3 or volume_ratio != volume_ratio or volume_ratio == float("inf")):
        return {"opened": False, "reason": "entry_checks_not_confirmed"}
    bar = signal.get("bar")
    if not good_bar(bar):
        return {"opened": False, "reason": "invalid_entry_bar"}
    try:
        now = now or datetime.now(timezone.utc)
        end = datetime.fromisoformat(str(signal.get("bar_end_iso", "")).replace("Z", "+00:00"))
        if now.tzinfo is None or end.tzinfo is None:
            return {"opened": False, "reason": "timezone_required"}
        age = (now.astimezone(timezone.utc) - end.astimezone(timezone.utc)).total_seconds()
        session = date.fromisoformat(str(signal.get("session_date", "")))
        bar_day = date.fromisoformat(str(bar.get("date", "")))
        if (age < 0 or age > 15 * 60 or session != bar_day or
                end.astimezone(WIB).date() != session):
            return {"opened": False, "reason": "stale_or_mismatched_entry"}
    except (ValueError, TypeError, AttributeError):
        return {"opened": False, "reason": "invalid_entry_timestamp"}

    with closing(_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id,payload FROM daily_paper_trades WHERE ticker=? AND status='WAIT_ENTRY'",
            (ticker,),
        ).fetchall()
        for signal_id, payload in rows:
            order = json.loads(payload)
            entry = float(order["entry"])
            stop = float(order["cut_loss"])
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            if (bar_day <= date.fromisoformat(order["signal_day"]) or
                    not low <= entry <= high or close < entry):
                continue
            order.update(
                entry_day=bar_day.isoformat(),
                last_bar_day=bar_day.isoformat(),
                entry_source="V2_5M_BOUNCE",
                entry_bar_end_iso=end.astimezone(timezone.utc).isoformat(),
                entry_bar_volume_ratio=signal.get("volume_ratio"),
            )
            if low <= stop:
                order.update(
                    status="CL", exit_day=bar_day.isoformat(), exit_price=stop,
                    exit_reason="stop_or_ambiguous_entry_bar",
                    realized_pnl_pct=round((stop/entry-1)*100-0.20, 4),
                )
                event = "PAPER_CL_INTRADAY"
            else:
                order["status"] = "OPEN"
                event = "PAPER_OPEN_INTRADAY"
            conn.execute(
                "UPDATE daily_paper_trades SET status=?,payload=? WHERE id=? AND status='WAIT_ENTRY'",
                (order["status"], json.dumps(order), signal_id),
            )
            if conn.total_changes == 0:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO daily_paper_events "
                "(signal_id,session_date,event,payload) VALUES (?,?,?,?)",
                (signal_id, bar_day.isoformat(), event, json.dumps(order)),
            )
            conn.commit()
            return {"opened": order["status"] == "OPEN", "event": event,
                    "trade": order, "paper_only": True}
        conn.rollback()
    return {"opened": False, "reason": "no_waiting_plan_or_entry_not_touched"}

def summary():
    info = {"configured":enabled(), "last_success":LAST["last_success"],
            "last_error":LAST["last_error"], "mode":"daily_completed_bars_only",
            "entry_mode":"completed_daily_bar_touch",
            "no_live_orders":True,"positions_on_server":False,
            "counts":{key:0 for key in ("WAIT_ENTRY","OPEN","TP1_HIT","CL","TP2","TIME","EXPIRED")}}
    if not storage_health()["ready"]:
        return info
    try:
        with closing(_connection()) as conn:
            for status,count in conn.execute("SELECT status,COUNT(*) FROM daily_paper_trades GROUP BY status"):
                if status in info["counts"]:
                    info["counts"][status] = count
            latest = conn.execute(
                "SELECT session_cutoff,finished_at,valid_tickers,created,advanced "
                "FROM daily_paper_cycles ORDER BY session_cutoff DESC LIMIT 1").fetchone()
            if latest:
                info.update(last_cycle_date=latest[0],last_success=latest[1],
                            last_valid_tickers=latest[2],last_new_plans=latest[3],
                            last_transitions=latest[4])
            info["positions_on_server"] = True
    except (sqlite3.Error, OSError, RuntimeError):
        info["last_error"] = "database_unavailable"
    return info
