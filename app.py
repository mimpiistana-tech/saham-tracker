from flask import Flask, request, jsonify
import requests
import os
import time
from datetime import datetime, timedelta

from radar_score import score_from_broker_rows, score_from_market_data

app = Flask(__name__)

API_KEY = os.environ.get("INDEXALPHA_API_KEY")
BASE_URL = "https://api.indexalpha.id"
CACHE = {}
CACHE_TTL = 60 * 60 * 24


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


@app.route("/")
def home():
    with open("index.html", encoding="utf-8") as f:
        return f.read()


def cache_get(key):
    cached = CACHE.get(key)

    if not cached:
        return None, None

    age = time.time() - cached["time"]

    if age < CACHE_TTL:
        return cached, "HIT"

    return cached, "STALE"


def cache_put(key, data, status):
    CACHE[key] = {
        "time": time.time(),
        "data": data,
        "status": status,
    }


def indexalpha_get(path, params, cache_key):
    if not API_KEY:
        return {
            "success": False,
            "error": "INDEXALPHA_API_KEY belum dipasang di Render",
        }, 500, "MISS"

    cached, cache_state = cache_get(cache_key)

    if cached and cache_state == "HIT":
        return cached["data"], cached["status"], "HIT"

    stale_cached = cached if cache_state == "STALE" else None

    try:
        response = requests.get(
            f"{BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "accept": "application/json",
            },
            params=params,
            timeout=25,
        )

        try:
            data = response.json()
        except Exception:
            data = {
                "success": False,
                "error": response.text[:1000],
            }

        if response.status_code == 200:
            cache_put(cache_key, data, response.status_code)
            return data, response.status_code, "MISS"

        if stale_cached is not None:
            return (
                stale_cached["data"],
                stale_cached["status"],
                "STALE",
            )

        return data, response.status_code, "MISS"

    except Exception as e:
        if stale_cached is not None:
            return (
                stale_cached["data"],
                stale_cached["status"],
                "STALE",
            )

        return {
            "success": False,
            "error": str(e),
        }, 500, "MISS"


@app.route("/api/broker")
def broker():
    ticker = request.args.get("ticker", "BBRI").upper()
    date_from = request.args.get("from")
    date_to = request.args.get("to")

    if not date_from or not date_to:
        return jsonify({
            "success": False,
            "error": "Parameter from dan to wajib diisi",
        }), 400

    cache_key = f"broker_{ticker}_{date_from}_{date_to}"

    data, status, cache_state = indexalpha_get(
        "/stocks/broker-summary",
        {
            "ticker": ticker,
            "from": date_from,
            "to": date_to,
            "investor": "all",
            "market": "RG",
        },
        cache_key,
    )

    result = jsonify(data)
    result.headers["X-StockRadar-Cache"] = cache_state
    return result, status


def extract_broker_rows(payload):
    rows = []

    def first_value(data, keys):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return None

    def walk(obj):
        if isinstance(obj, dict):
            low = {
                str(k).lower(): v
                for k, v in obj.items()
            }

            broker_code = first_value(low, [
                "broker",
                "broker_code",
                "brokercode",
                "code",
                "name",
            ])

            buy = first_value(low, [
                "buy",
                "buy_value",
                "buyvalue",
                "bval",
                "total_buy",
            ])

            sell = first_value(low, [
                "sell",
                "sell_value",
                "sellvalue",
                "sval",
                "total_sell",
            ])

            net = first_value(low, [
                "net",
                "net_value",
                "netvalue",
                "nval",
                "net_buy",
            ])

            if broker_code is not None and (
                buy is not None
                or sell is not None
                or net is not None
            ):
                rows.append({
                    "broker": broker_code,
                    "buy": buy,
                    "sell": sell,
                    "net": net,
                })

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return rows


def get_ohlcv(ticker, date_to):
    try:
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }, 400, "MISS"

    start_date = end_date - timedelta(days=120)

    if start_date < datetime(2025, 1, 1).date():
        start_date = datetime(2025, 1, 1).date()

    date_from = start_date.isoformat()
    date_to = end_date.isoformat()

    cache_key = f"ohlcv_{ticker}_{date_from}_{date_to}"

    return indexalpha_get(
        "/stocks/ohlcv",
        {
            "ticker": ticker,
            "from": date_from,
            "to": date_to,
        },
        cache_key,
    )


@app.route("/api/ohlcv")
def ohlcv():
    ticker = request.args.get("ticker", "BBRI").upper()
    date_to = request.args.get("to")

    if not date_to:
        return jsonify({
            "success": False,
            "error": "Parameter to wajib diisi",
        }), 400

    data, status, cache_state = get_ohlcv(ticker, date_to)

    result = jsonify(data)
    result.headers["X-StockRadar-Cache"] = cache_state
    return result, status


def extract_ohlcv_rows(payload):
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")

    if not isinstance(data, list):
        return []

    rows = []

    for item in data:
        if not isinstance(item, dict):
            continue

        if item.get("close") is None:
            continue

        rows.append({
            "date": item.get("date"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": item.get("volume"),
        })

    return rows


@app.route("/api/radar")
def radar():
    ticker = request.args.get("ticker", "").upper()
    date_from = request.args.get("from")
    date_to = request.args.get("to")

    if not ticker or not date_from or not date_to:
        return jsonify({
            "success": False,
            "error": "ticker, from, dan to wajib diisi",
        }), 400

    broker_cache_key = f"broker_{ticker}_{date_from}_{date_to}"

    broker_data, broker_status, broker_cache = indexalpha_get(
        "/stocks/broker-summary",
        {
            "ticker": ticker,
            "from": date_from,
            "to": date_to,
            "investor": "all",
            "market": "RG",
        },
        broker_cache_key,
    )

    if broker_status != 200:
        return jsonify({
            "success": False,
            "stage": "broker",
            "status": broker_status,
            "detail": broker_data,
        }), broker_status

    broker_rows = extract_broker_rows(broker_data)

    if not broker_rows:
        return jsonify({
            "success": False,
            "error": "Format broker belum dikenali",
            "raw_preview": str(broker_data)[:1500],
        }), 422

    ohlcv_data, ohlcv_status, ohlcv_cache = get_ohlcv(
        ticker,
        date_to,
    )

    warnings = []

    if ohlcv_status == 200:
        ohlcv_rows = extract_ohlcv_rows(ohlcv_data)
    else:
        ohlcv_rows = []
        warnings.append(
            "OHLCV belum tersedia; Radar berjalan dengan broker saja."
        )

    if ohlcv_rows:
        result = score_from_market_data(
            broker_rows,
            ohlcv_rows,
        )
    else:
        result = score_from_broker_rows(
            broker_rows,
        )

    return jsonify({
        "success": True,
        "ticker": ticker,
        "date": date_to,
        "cache": {
            "broker": broker_cache,
            "ohlcv": ohlcv_cache,
        },
        "broker_rows_found": len(broker_rows),
        "ohlcv_rows_found": len(ohlcv_rows),
        "warnings": warnings,
        "result": result,
    })


@app.route("/api/radar-test")
def radar_test():
    broker_rows = [
        {"broker": "CC", "net": 12400000},
        {"broker": "XC", "net": 9100000},
        {"broker": "YP", "net": -3000000},
        {"broker": "ZP", "net": -2000000},
    ]

    ohlcv_rows = []

    start = datetime(2026, 7, 1).date()

    for i in range(60):
        close = 5000 + (i * 5)
        volume = 100000000 + (i * 1000000)

        ohlcv_rows.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "open": close - 5,
            "high": close + 10,
            "low": close - 10,
            "close": close,
            "volume": volume,
        })

    result = score_from_market_data(
        broker_rows,
        ohlcv_rows,
    )

    return jsonify({
        "success": True,
        "ticker": "TEST",
        "result": result,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
