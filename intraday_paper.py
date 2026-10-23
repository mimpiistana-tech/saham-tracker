"""V2-style 5-minute entry confirmation for V3 PAPER-only positions.

Uses completed Yahoo candles as an indicative timing source. It never creates
broker orders. A V3 risk plan and its stored entry price remain authoritative.
"""
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

import requests

WIB = ZoneInfo("Asia/Jakarta")
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.JK"


def _positive(value):
    try:
        number = float(value)
        return number if isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def analyze_entry_candles(ticker, candles, entry_price, *, now=None):
    """Confirm a fresh completed 5m bounce that actually crosses the paper entry."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    entry = _positive(entry_price)
    if not entry:
        return {"qualified": False, "reason": "invalid_entry"}

    now_ts = now.timestamp()
    session_day = now.astimezone(WIB).date()
    completed = []
    for item in candles or []:
        try:
            start = int(item["timestamp"])
            values = {key: float(item[key]) for key in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        opened, high, low, close, volume = (
            values["open"], values["high"], values["low"], values["close"], values["volume"]
        )
        if (not all(isfinite(v) for v in values.values()) or
                min(opened, high, low, close) <= 0 or volume < 0 or
                high < low or not low <= min(opened, close) <= max(opened, close) <= high):
            continue
        if start > now_ts + 60 or start + 330 > now_ts:
            continue
        if datetime.fromtimestamp(start, WIB).date() != session_day:
            continue
        completed.append({"timestamp": start, **values})

    by_start = {bar["timestamp"]: bar for bar in completed}
    completed = [by_start[key] for key in sorted(by_start)]
    if len(completed) < 12:
        return {"qualified": False, "reason": "insufficient_completed_bars"}

    latest, previous = completed[-1], completed[-2]
    age = max(0, now_ts - (latest["timestamp"] + 300))
    if age > 15 * 60:
        return {"qualified": False, "reason": "stale_bar", "age_seconds": age}

    prior_volumes = [bar["volume"] for bar in completed[-12:-2] if bar["volume"] > 0]
    if latest["volume"] <= 0 or len(prior_volumes) < 8:
        return {"qualified": False, "reason": "volume_unavailable", "age_seconds": age}
    volume_ratio = latest["volume"] / (sum(prior_volumes) / len(prior_volumes))
    checks = {
        "green": latest["close"] > latest["open"],
        "break_previous_high": latest["close"] > previous["high"],
        "higher_low": latest["low"] >= previous["low"],
        "volume_1_3x": volume_ratio >= 1.3,
        "entry_touched": latest["low"] <= entry <= latest["high"],
        "close_at_or_above_entry": latest["close"] >= entry,
    }
    if not all(checks.values()):
        return {"qualified": False, "reason": "entry_checks_failed",
                "checks": checks, "volume_ratio": round(volume_ratio, 3),
                "age_seconds": age}

    end = datetime.fromtimestamp(latest["timestamp"] + 300, timezone.utc)
    return {
        "qualified": True,
        "reason": "v2_5m_entry_confirmed",
        "ticker": str(ticker).upper(),
        "session_date": session_day.isoformat(),
        "bar_end_iso": end.isoformat(),
        "bar": {
            "date": session_day.isoformat(),
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "close": latest["close"],
            "volume": latest["volume"],
        },
        "volume_ratio": round(volume_ratio, 3),
        "age_seconds": age,
        "checks": checks,
        "source": "YAHOO_5M_INDICATIVE",
        "paper_only": True,
    }


def fetch_entry_signal(ticker, entry_price, *, now=None, session=None):
    """Fetch one bounded Yahoo 5m chart and apply the same conservative gate."""
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    try:
        response = requests.get(
            YAHOO_URL.format(ticker=str(ticker).upper()),
            params={"period1": now_ts - 2 * 86400, "period2": now_ts + 60,
                    "interval": "5m", "events": "history"},
            headers={"User-Agent": "Mozilla/5.0 StockRadar/3.0",
                     "accept": "application/json"},
            timeout=12,
        )
        if response.status_code != 200:
            return {"qualified": False, "reason": "source_http_error"}
        results = ((response.json().get("chart") or {}).get("result") or [None])
        result = results[0]
        if not result:
            return {"qualified": False, "reason": "source_data_unavailable"}
        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
        candles = []
        for index, stamp in enumerate(timestamps):
            candles.append({"timestamp": stamp, **{
                key: (quote.get(key) or [])[index]
                if index < len(quote.get(key) or []) else None
                for key in ("open", "high", "low", "close", "volume")
            }})
        return analyze_entry_candles(ticker, candles, entry_price, now=now)
    except (requests.RequestException, ValueError, TypeError, OverflowError):
        return {"qualified": False, "reason": "source_error"}
