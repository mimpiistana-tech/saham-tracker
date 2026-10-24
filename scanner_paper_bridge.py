"""Read-only bridge: V2 daily scanner plans -> paper candidates.

Daily candles cannot confirm the required completed 5-minute bar.
No network, journal writes, orders, or scheduler.
"""
from math import isfinite

def _number(value):
    try:
        n = float(value)
        return n if isfinite(n) and n > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None

def scanner_to_paper_candidate(item):
    if not isinstance(item, dict):
        return None
    ticker = str(item.get("ticker", "")).upper()
    if not (ticker.isascii() and ticker.isalnum() and 3 <= len(ticker) <= 6):
        return None
    plan = item.get("paper_plan")
    if not isinstance(plan, dict):
        return None
    low = _number(item.get("entry_low"))
    high = _number(item.get("entry_high"))
    stop = _number(plan.get("cut_loss"))
    tp1 = _number(plan.get("tp1"))
    tp2 = _number(plan.get("tp2"))
    if any(x is None for x in (low, high, stop, tp1, tp2)):
        return None
    if not stop < low <= high < tp1 < tp2:
        return None
    return {"ticker": ticker, "entry_low": low, "entry_high": high,
            "cut_loss": stop, "tp1": tp1, "tp2": tp2}

def bridge_scanner_result(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return {"paper_only": True, "ready_for_entry": False, "candidates": [],
                "reason": "scanner_unavailable"}
    if payload.get("candle_policy") != "COMPLETED_DAILY_ONLY" or payload.get("market_data_is_live") is not False:
        return {"paper_only": True, "ready_for_entry": False, "candidates": [],
                "reason": "scanner_policy_unverified"}
    items = payload.get("top_picks")
    if not isinstance(items, list):
        return {"paper_only": True, "ready_for_entry": False, "candidates": [],
                "reason": "missing_top_picks"}
    candidates = []
    seen = set()
    for item in items[:3]:
        candidate = scanner_to_paper_candidate(item)
        if candidate and candidate["ticker"] not in seen:
            seen.add(candidate["ticker"])
            candidates.append(candidate)
    return {"paper_only": True, "ready_for_entry": False,
            "candidates": candidates,
            "reason": "await_completed_fresh_5m_bar_higher_low_and_volume"}
