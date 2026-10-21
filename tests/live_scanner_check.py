"""Run a real Yahoo-backed scanner against Flask on the V2 branch.

This is an opt-in integration smoke test: zero IndexAlpha requests, no trades,
no Stockbit API, no production deploy.
"""
import json
import time
from datetime import datetime, timedelta, timezone

import app as radar


def report(label, result):
    payload = result.get_json(silent=True) or {}
    safe = {k: payload.get(k) for k in (
        "success", "date", "mode", "universe_size", "scanned",
        "summary", "source", "ticker", "price", "freshness",
        "price_time_wib", "error",
    ) if k in payload}
    if "market_regime" in payload:
        regime = payload.get("market_regime") or {}
        safe["market_regime"] = {
            k: regime.get(k) for k in ("regime", "date", "error") if k in regime
        }
    if "top_picks" in payload:
        safe["top_picks"] = [
            {k: item.get(k) for k in ("ticker", "score", "signal_date",
                                       "close", "entry_mode", "entry_low", "entry_high")}
            for item in (payload.get("top_picks") or [])[:3]
        ]
    print(label, json.dumps({
        "http": result.status_code,
        "server_cache": result.headers.get("X-StockRadar-Cache"),
        **safe
    }, ensure_ascii=False, default=str), flush=True)
    return payload


def main():
    now = datetime.now(timezone(timedelta(hours=7)))
    day = now.date().isoformat()
    print("DATE_WIB", now.isoformat(), flush=True)
    radar.CACHE.clear()
    client = radar.app.test_client()

    start = time.perf_counter()
    first = client.get("/api/scanner", query_string={"mode": "quick", "to": day})
    initial = round(time.perf_counter() - start, 3)
    body = report("FIRST_SCAN", first)
    print("FIRST_SCAN_SECONDS", initial, flush=True)

    start = time.perf_counter()
    second = client.get("/api/scanner", query_string={"mode": "quick", "to": day})
    repeated = round(time.perf_counter() - start, 3)
    report("CACHE_REPEAT", second)
    print("CACHE_REPEAT_SECONDS", repeated, flush=True)

    start = time.perf_counter()
    quote = client.get("/api/live-quote", query_string={"ticker": "BBRI"})
    quote_seconds = round(time.perf_counter() - start, 3)
    report("BBRI_YAHOO_INTRADAY", quote)
    print("QUOTE_SECONDS", quote_seconds, flush=True)

    if first.status_code != 200 or second.status_code != 200:
        raise SystemExit("FAIL scanner HTTP response")
    if body.get("universe_size") != 20 or body.get("mode") != "quick":
        raise SystemExit("FAIL wrong scanner mode / universe")
    if second.headers.get("X-StockRadar-Cache") != "HIT":
        raise SystemExit("FAIL backend scan cache")
    if not body.get("scanned"):
        raise SystemExit("FAIL Yahoo did not supply any usable scanner history; do not infer live readiness")
    if quote.status_code != 200:
        raise SystemExit("FAIL BBRI quote not available")
    print("LIVE_INTEGRATION: PASS backend connectivity; Stockbit/Render deployment NOT verified", flush=True)


if __name__ == "__main__":
    main()
