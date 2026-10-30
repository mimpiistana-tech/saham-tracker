"""Pure, conservative daily-bar PAPER state machine. Never places broker orders.

Decisions use candles from completed IDX sessions only. Day of signal cannot
fill. On the entry day we allow an adverse stop but no optimistic target fill
because daily OHLC cannot determine intraday event order.
"""
import math
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

MAX_WAIT_SESSIONS = 5

def round_idx(value, direction):
    """Regular-market price ladder; never round a breakout trigger down."""
    value = price(value)
    if value is None:
        return None
    tick = 1 if value < 200 else 2 if value < 500 else 5 if value < 2000 else 10 if value < 5000 else 25
    rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    return float((Decimal(str(value)) / tick).to_integral_value(rounding=rounding) * tick)

def rounded_levels(plan, mode):
    return {key: round_idx(plan.get(key), "up" if key in {"tp1", "tp2"} or
                         (key == "entry" and mode == "BREAKOUT") else "down")
            for key in ("entry", "cut_loss", "tp1", "tp2")}

def candidate_decision(item):
    """Explain the unchanged admission thresholds, without creating an order."""
    reasons = []
    if item.get("setup") not in {"Momentum", "Watch Pullback"}:
        reasons.append("Setup belum Momentum / Watch Pullback")
    for key, minimum, label in (("score",65,"Skor"),("trend_score",60,"Tren"),
                                 ("risk_score",55,"Skor risiko"),("volume_ratio",1.3,"Rasio volume")):
        actual = price(item.get(key)) or 0
        if actual < minimum:
            reasons.append(f"{label} {actual:g} < {minimum:g}")
    plan = planned_order(item)
    if plan is None and not reasons:
        reasons.append("Tanggal, harga, risk/reward, mode, atau ukuran lot tidak valid setelah pembulatan")
    return {"eligible": plan is not None, "reasons": reasons,
            "reason": "; ".join(reasons) if reasons else "Lolos syarat rencana; menunggu harga entry"}

def normalize_waiting_order(order):
    """Prospective only: preserve last processed session and never enlarge risk."""
    row = dict(order)
    if row.get("status") != "WAIT_ENTRY" or row.get("price_rounding_version") == 1:
        return row
    levels = rounded_levels(row, row.get("mode"))
    entry, stop, tp1, tp2 = (levels[k] for k in ("entry","cut_loss","tp1","tp2"))
    if (any(price(v) is None for v in levels.values()) or not stop < entry < tp1 < tp2
            or (entry-stop)/entry > .15 or (tp2-entry)/(entry-stop) < 1.5):
        row.update(status="EXPIRED", exit_reason="Harga tidak valid setelah pembulatan")
        return row
    risk_budget = min(100_000, float(row.get("planned_risk") or 100_000))
    lots = min(int(row.get("lots") or 0), int(risk_budget // ((entry-stop)*100)),
               int(float(row.get("paper_value") or 0) // (entry*100)))
    if lots < 1:
        row.update(status="EXPIRED", exit_reason="Lot tidak mencukupi setelah pembulatan")
        return row
    row["original_levels"] = {key: row.get(key) for key in levels}
    row.update(levels, lots=lots, shares=lots*100, paper_value=lots*100*entry,
               planned_risk=lots*100*(entry-stop), price_rounding_version=1)
    return row

ACTIVE = {"WAIT_ENTRY", "OPEN", "TP1_HIT"}
CLOSED = {"CL", "TP2", "TIME", "EXPIRED"}

def price(v):
    try:
        v = float(v)
        return v if math.isfinite(v) and v > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None

def good_bar(bar):
    if not isinstance(bar, dict):
        return False
    try:
        date.fromisoformat(str(bar["date"]))
        high, low, op, close = (price(bar.get(k)) for k in ("high", "low", "open", "close"))
        volume = float(bar["volume"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    return (all(x is not None for x in (high, low, op, close))
            and low <= min(op, close) <= max(op, close) <= high
            and math.isfinite(volume) and volume >= 0)

def planned_order(item, *, capital=10_000_000, risk_pct=1.0, slots=3):
    if not isinstance(item, dict) or item.get("setup") not in {"Momentum","Watch Pullback"}:
        return None
    if (price(item.get("score")) or 0) < 65:
        return None
    if (price(item.get("trend_score")) or 0) < 60 or (price(item.get("risk_score")) or 0) < 55:
        return None
    if (price(item.get("volume_ratio")) or 0) < 1.3:
        return None
    try:
        signal_day = date.fromisoformat(str(item["signal_date"])).isoformat()
    except (ValueError, TypeError, KeyError):
        return None
    ticker = str(item.get("ticker") or "").upper()
    if not ticker.isascii() or not ticker.isalpha() or not (3 <= len(ticker) <= 5):
        return None
    plan = item.get("paper_plan") or {}
    mode = str(plan.get("entry_mode") or item.get("entry_mode") or "").upper()
    if mode not in {"BREAKOUT","PULLBACK"}:
        return None
    levels = rounded_levels(plan, mode)
    entry, stop, tp1, tp2 = (price(levels[k]) for k in ("entry", "cut_loss", "tp1", "tp2"))
    if any(x is None for x in (entry, stop, tp1, tp2)) or not stop < entry < tp1 < tp2:
        return None
    if (entry - stop)/entry > .15 or (tp2-entry)/(entry-stop) < 1.5:
        return None
    if capital <= 0 or not 0 < risk_pct <= 3 or slots < 1:
        return None
    lots = min(int((capital*risk_pct/100)//((entry-stop)*100)),
               int((capital/slots)//(entry*100)))
    if lots < 1:
        return None
    return dict(signal_id=ticker+":"+signal_day, ticker=ticker, signal_day=signal_day,
                status="WAIT_ENTRY", entry=entry, cut_loss=stop, tp1=tp1, tp2=tp2,
                mode=mode, lots=lots, shares=lots*100, paper_value=round(lots*100*entry,2),
                planned_risk=round(lots*100*(entry-stop),2), score=float(item["score"]),
                setup=item["setup"], last_bar_day=signal_day,
                waited=0, held=0, entry_day=None, tp1_day=None, exit_day=None,
                exit_price=None, realized_pnl_pct=None, paper_only=True,
                price_rounding_version=1,
                original_levels={key:plan.get(key) for key in levels})

def apply_bar(order, bar, *, max_wait=MAX_WAIT_SESSIONS, max_hold=20, fee_bps=20):
    """One completed subsequent candle. Returns (new_state, event).
    A partial TP1 is a flag only: the entire mock position exits at TP2/CL/TIME.
    """
    row = dict(order)
    if not good_bar(bar):
        return row, "WAIT_VALID_DATA"
    try:
        day = date.fromisoformat(bar["date"])
        if day <= date.fromisoformat(row["signal_day"]) or day <= date.fromisoformat(row["last_bar_day"]):
            return row, "WAIT_NEW_SESSION"
    except (TypeError, ValueError, KeyError):
        return row, "WAIT_NEW_SESSION"
    if row.get("status") not in ACTIVE:
        return row, "NO_CHANGE"
    high, low = float(bar["high"]), float(bar["low"])
    # Only migrate a legacy plan before an unseen session, never replay old fills.
    row = normalize_waiting_order(row)
    if row["status"] == "EXPIRED":
        row["exit_day"] = day.isoformat()
        return row, "EXPIRED"
    entry, stop, tp1, tp2 = (float(row[k]) for k in ("entry","cut_loss","tp1","tp2"))
    row["last_bar_day"] = day.isoformat()
    row.update(last_bar_low=low, last_bar_high=high)
    if row["status"] == "WAIT_ENTRY":
        if int(row.get("waited",0)) >= max_wait:
            row.update(status="EXPIRED", exit_day=day.isoformat(), exit_reason="Batas 5 sesi menunggu habis")
            return row, "EXPIRED"
        row["waited"] = int(row.get("waited",0))+1
        if not low <= entry <= high:
            if row["waited"] >= max_wait:
                row.update(status="EXPIRED", exit_day=day.isoformat(), exit_reason="Harga entry belum tersentuh dalam 5 sesi")
                return row, "EXPIRED"
            return row, "WAIT_ENTRY"
        row.update(status="OPEN",entry_day=day.isoformat())
        if low <= stop:  # Unknown ordering -> adverse assumption.
            return _close(row, "CL", stop, day, fee_bps), "ENTRY_STOP_SAME_BAR"
        # Never credit TP1 or TP2 on the entry candle.
        return row, "PAPER_OPEN"
    row["held"] = int(row.get("held",0))+1
    if low <= stop:
        return _close(row, "CL", stop, day, fee_bps), "PAPER_CL"
    if high >= tp2:
        row["tp1_day"] = row.get("tp1_day") or day.isoformat()
        return _close(row, "TP2", tp2, day, fee_bps), "PAPER_TP2"
    if high >= tp1 and row["status"] == "OPEN":
        row.update(status="TP1_HIT",tp1_day=day.isoformat())
        return row, "PAPER_TP1"
    if row["held"] >= max_hold:
        return _close(row, "TIME", float(bar["close"]), day, fee_bps), "PAPER_TIME_EXIT"
    return row, "PAPER_HELD"

def _close(row, status, exit_price, day, fee_bps):
    row.update(status=status, exit_day=day.isoformat(), exit_price=exit_price,
               realized_pnl_pct=round((exit_price/float(row["entry"])-1)*100-fee_bps/100,4))
    return row
