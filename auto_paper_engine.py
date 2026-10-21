"""PAPER ONLY deterministic state transitions; no orders, network, or scheduler.

Caller must persist state transactionally and supply verified, chronological
completed candles. Intrabar TP/SL collision is conservatively a stop.
"""
from datetime import datetime
from math import isfinite

TERMINAL = {"TP2", "CL"}

def _number(value):
    try:
        x = float(value)
        return x if isfinite(x) and x > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None

def _stamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else None
    except (ValueError, TypeError):
        return None

def advance_paper_trade(trade, candle, *, fee_bps=20):
    """Pure transition; returns new dict, unchanged if candle invalid/old.

    All fills are conservative candle-price approximations, not broker executions.
    fee_bps is total round-trip fees and slippage (basis points).
    """
    row = dict(trade)
    if row.get("status") in TERMINAL:
        return row
    if row.get("status") not in {"OPEN", "TP1_HIT"}:
        return row
    t = _stamp(candle.get("end_iso"))
    last = _stamp(row.get("last_bar_end_iso") or row.get("entry_bar_end_iso"))
    if t is None or last is None or t <= last or candle.get("completed") is not True:
        return row
    high, low = _number(candle.get("high")), _number(candle.get("low"))
    entry = _number(row.get("entry"))
    stop = _number(row.get("cut_loss"))
    tp1 = _number(row.get("tp1"))
    tp2 = _number(row.get("tp2"))
    if None in (high, low, entry, stop, tp1, tp2) or high < low or not stop < entry < tp1 < tp2:
        return row
    row["last_bar_end_iso"] = t.isoformat()
    if low <= stop:
        row.update(status="CL", exit_price=stop, closed_at=t.isoformat(),
                   exit_reason="stop_or_ambiguous_candle",
                   realized_pnl_pct=round((stop / entry - 1) * 100 - fee_bps / 100, 4))
    elif high >= tp2:
        row.update(status="TP2", exit_price=tp2, closed_at=t.isoformat(),
                   exit_reason="target_2",
                   realized_pnl_pct=round((tp2 / entry - 1) * 100 - fee_bps / 100, 4))
    elif high >= tp1 and row["status"] == "OPEN":
        row.update(status="TP1_HIT", tp1_hit_at=t.isoformat())
    return row
