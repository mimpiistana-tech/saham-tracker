"""Fail-closed, side-effect-free rules for StockRadar V2 PAPER-ONLY experiments.

No market fetch, scheduling, order execution, or persistence is performed here.
"""
from datetime import datetime, timezone
from math import isfinite


def _positive(value):
    try:
        number = float(value)
        return number if isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def evaluate_paper_candidate(candidate, bar, *, now_iso, max_delay_seconds=600):
    """Return an auditable decision; never create a paper trade directly."""
    def reject(reason):
        return {"decision": "WAIT_DATA", "reason": reason, "paper_only": True}

    if not isinstance(candidate, dict) or not isinstance(bar, dict):
        return reject("missing_payload")
    try:
        now = datetime.fromisoformat(now_iso.replace('Z', '+00:00'))
        end = datetime.fromisoformat(str(bar.get('end_iso', '')).replace('Z', '+00:00'))
        if now.tzinfo is None or end.tzinfo is None:
            return reject("timezone_required")
        age = (now.astimezone(timezone.utc) - end.astimezone(timezone.utc)).total_seconds()
    except (ValueError, TypeError, AttributeError):
        return reject("invalid_timestamp")
    if age < 0 or age > max_delay_seconds:
        return reject("stale_or_future_bar")
    if bar.get('completed') is not True:
        return reject("incomplete_bar")
    if bar.get('higher_low') is not True:
        return reject("higher_low_not_confirmed")
    ratio = _positive(bar.get('volume_ratio'))
    if ratio is None or ratio < 1.3:
        return reject("insufficient_volume")
    price = _positive(bar.get('close'))
    low = _positive(candidate.get('entry_low'))
    high = _positive(candidate.get('entry_high'))
    stop = _positive(candidate.get('cut_loss'))
    tp1 = _positive(candidate.get('tp1'))
    tp2 = _positive(candidate.get('tp2'))
    if any(v is None for v in (price, low, high, stop, tp1, tp2)):
        return reject("invalid_prices")
    if not (stop < low <= price <= high < tp1 < tp2):
        return reject("invalid_zone_or_risk")
    ticker = str(candidate.get('ticker', '')).upper()
    if not ticker.isascii() or not ticker.isalnum() or not (3 <= len(ticker) <= 6):
        return reject("invalid_ticker")
    return {"decision": "PAPER_CANDIDATE", "paper_only": True,
            "ticker": ticker, "bar_end_iso": end.isoformat(),
            "signal_id": ticker + ':' + end.astimezone(timezone.utc).isoformat(),
            "reference_price": price, "volume_ratio": ratio,
            "reason": "rules_passed_not_filled"}
