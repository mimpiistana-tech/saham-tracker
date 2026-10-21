"""SQLite-backed PAPER-ONLY journal. No brokerage orders or live scheduling."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from auto_paper_rules import evaluate_paper_candidate
from auto_paper_engine import advance_paper_trade

def _db():
    from paper_storage import storage_health
    check = storage_health()
    if not check["ready"]:
        raise RuntimeError("Durable paper storage unavailable: " + check["reason"])
    path = os.environ["AUTO_PAPER_DB_PATH"]
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise RuntimeError("database directory unavailable")
    conn = sqlite3.connect(path, timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (signal_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)")
    return conn

def paper_open(candidate, bar, now_iso=None):
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    decision = evaluate_paper_candidate(candidate, bar, now_iso=now_iso)
    if decision["decision"] != "PAPER_CANDIDATE":
        return decision
    signal_id = decision["signal_id"]
    row = dict(signal_id=signal_id, ticker=decision["ticker"], status="OPEN",
               entry=decision["reference_price"], cut_loss=float(candidate["cut_loss"]),
               tp1=float(candidate["tp1"]), tp2=float(candidate["tp2"]),
               entry_bar_end_iso=decision["bar_end_iso"],
               last_bar_end_iso=decision["bar_end_iso"], paper_only=True)
    with _db() as conn:
        active = conn.execute("SELECT 1 FROM trades WHERE ticker=? AND status IN ('OPEN','TP1_HIT') LIMIT 1", (row["ticker"],)).fetchone()
        if active:
            return {"decision": "WAIT_DATA", "reason": "active_ticker_exists", "paper_only": True}
        cur = conn.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?)",
                           (signal_id, row["ticker"], "OPEN", json.dumps(row)))
        if cur.rowcount == 0:
            return {"decision": "WAIT_DATA", "reason": "duplicate_signal", "paper_only": True}
    return {"decision": "PAPER_OPEN", "trade": row, "paper_only": True}

def paper_advance(ticker, candle):
    ticker = str(ticker).upper()
    with _db() as conn:
        rows = conn.execute("SELECT signal_id,payload FROM trades WHERE ticker=? AND status IN ('OPEN','TP1_HIT')", (ticker,)).fetchall()
        updated = []
        for signal_id, payload in rows:
            old = json.loads(payload)
            new = advance_paper_trade(old, candle)
            if new != old:
                conn.execute("UPDATE trades SET status=?,payload=? WHERE signal_id=?",
                             (new["status"], json.dumps(new), signal_id))
                updated.append(new)
    return {"paper_only": True, "updated": updated}

def paper_list():
    with _db() as conn:
        rows = conn.execute("SELECT payload FROM trades ORDER BY rowid DESC LIMIT 500").fetchall()
    return {"paper_only": True, "trades": [json.loads(row[0]) for row in rows]}
