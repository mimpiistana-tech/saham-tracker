"""Read-only stock movement detection from indicative Yahoo 5-minute charts.

Movement WATCH != trading ENTRY. Never place trades or create paper OPEN.
"""
from datetime import datetime, timedelta
from math import isfinite


def _positive(value):
    try:
        number = float(value)
        return number if isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _wib_date(epoch):
    return (datetime.utcfromtimestamp(epoch) + timedelta(hours=7)).date()


def build_mover(ticker, chart_result, now_ts):
    """Return a movement record only when baseline and same-session prices are verified."""
    if not isinstance(chart_result, dict):
        return None, "NO_CHART"
    meta = chart_result.get("meta") or {}
    baseline = (
        _positive(meta.get("previousClose"))
        or _positive(meta.get("regularMarketPreviousClose"))
        or _positive(meta.get("chartPreviousClose"))
    )
    if not baseline:
        return None, "NO_PREVIOUS_CLOSE"

    timestamps = chart_result.get("timestamp") or []
    quote = ((chart_result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    today = _wib_date(now_ts)
    completed = []
    for i, ts in enumerate(timestamps):
        try:
            ts = int(ts)
            close = _positive(closes[i] if i < len(closes) else None)
            if not close or ts > now_ts + 60 or _wib_date(ts) != today:
                continue
            if ts + 330 > now_ts:  # a 5m candle must actually finish
                continue
            raw_volume = volumes[i] if i < len(volumes) else None
            vol = float(raw_volume) if raw_volume is not None else None
            if vol is not None and (not isfinite(vol) or vol < 0):
                vol = None
            completed.append({"timestamp": ts, "close": close, "volume": vol})
        except (ValueError, TypeError, OverflowError, OSError, IndexError):
            continue

    completed = sorted({bar["timestamp"]: bar for bar in completed}.values(),
                       key=lambda bar: bar["timestamp"])
    candle = completed[-1] if completed else None
    market_time = meta.get("regularMarketTime")
    market_price = _positive(meta.get("regularMarketPrice"))
    try:
        market_time = int(market_time)
    except (ValueError, TypeError, OverflowError):
        market_time = 0
    market_valid = (
        market_price is not None and
        0 < market_time <= now_ts + 60 and
        _wib_date(market_time) == today and
        (not candle or market_time >= candle["timestamp"])
    )
    if market_valid:
        price, price_ts, price_type = market_price, market_time, "YAHOO_LAST"
    elif candle:
        price, price_ts, price_type = (
            candle["close"], candle["timestamp"] + 300, "COMPLETED_5M"
        )
    else:
        return None, "NO_SAME_SESSION_QUOTE"

    age = max(0, now_ts - price_ts)
    freshness = "RECENT" if age <= 15 * 60 else (
        "DELAYED" if age <= 60 * 60 else "STALE"
    )
    latest_volume = candle["volume"] if candle else None
    prior = [
        bar["volume"] for bar in completed[-11:-1]
        if bar["volume"] is not None and bar["volume"] > 0
    ]
    vol_ratio = (
        latest_volume / (sum(prior) / len(prior))
        if latest_volume is not None and latest_volume > 0 and len(prior) >= 5
        else None
    )
    change_pct = (price / baseline - 1) * 100
    move_status = (
        "UP" if change_pct >= 1.0 else
        "DOWN" if change_pct <= -1.0 else "FLAT"
    )
    return {
        "ticker": ticker,
        "price": round(price, 2),
        "previous_close": round(baseline, 2),
        "change_pct": round(change_pct, 2),
        "direction": move_status,
        "volume_ratio_5m": round(vol_ratio, 2) if vol_ratio is not None else None,
        "volume_confirmed": vol_ratio is not None and vol_ratio >= 1.3,
        "price_source": price_type,
        "quote_time_wib": (datetime.utcfromtimestamp(price_ts) + timedelta(hours=7))
            .strftime("%Y-%m-%d %H:%M:%S"),
        "quote_date": today.isoformat(),
        "age_seconds": age,
        "freshness": freshness,
        "decision": "WATCH_ONLY",
        "entry_approved": False,
    }, None
