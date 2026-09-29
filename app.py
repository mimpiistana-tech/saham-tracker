from flask import Flask, request, jsonify
import requests
import os
import time
from radar_score import score_from_broker_rows
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

@app.route("/api/broker")
def broker():
    ticker = request.args.get("ticker", "BBRI").upper()
    date_from = request.args.get("from")
    date_to = request.args.get("to")

    if not date_from or not date_to:
        return jsonify({
            "success": False,
            "error": "Parameter from dan to wajib diisi"
        }), 400

    if not API_KEY:
        return jsonify({
            "success": False,
            "error": "INDEXALPHA_API_KEY belum dipasang di Render"
        }), 500

    # Kunci cache berdasarkan saham + tanggal
    cache_key = f"{ticker}_{date_from}_{date_to}"

    # Cek apakah data sudah pernah diambil
    stale_cached = None
    if cache_key in CACHE:
        cached = CACHE[cache_key]

        umur = time.time() - cached["time"]

        if umur < CACHE_TTL:
            result = jsonify(cached["data"])
            result.headers["X-StockRadar-Cache"] = "HIT"
            return result, cached["status"]

        else:
            stale_cached = cached

    try:
            response = requests.get(
            f"{BASE_URL}/stocks/broker-summary",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "accept": "application/json"
            },
            params={
                "ticker": ticker,
                "from": date_from,
                "to": date_to,
                "investor": "all",
                "market": "RG"
            },
            timeout=20
        )

        data = response.json()

        # Hanya simpan kalau request berhasil
        if response.status_code == 200:
            CACHE[cache_key] = {
                "time": time.time(),
                "data": data,
                "status": response.status_code
            }
                if response.status_code != 200 and stale_cached is not None:
            result = jsonify(stale_cached["data"])
            result.headers["X-StockRadar-Cache"] = "STALE"
            result.headers["X-StockRadar-Upstream-Status"] = str(response.status_code)
            return result, stale_cached["status"]

        result = jsonify(data)
        result.headers["X-StockRadar-Cache"] = "MISS"

        return result, response.status_code

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

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
                "name"
            ])

            buy = first_value(low, [
                "buy",
                "buy_value",
                "buyvalue",
                "bval",
                "total_buy"
            ])

            sell = first_value(low, [
                "sell",
                "sell_value",
                "sellvalue",
                "sval",
                "total_sell"
            ])

            net = first_value(low, [
                "net",
                "net_value",
                "netvalue",
                "nval",
                "net_buy"
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
                    "net": net
                })

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return rows


@app.route("/api/radar")
def radar():
    broker_result = broker()

    if isinstance(broker_result, tuple):
        response = broker_result[0]
        status = broker_result[1]
    else:
        response = broker_result
        status = 200

    data = response.get_json()

    if status != 200:
        return jsonify({
            "success": False,
            "stage": "broker",
            "status": status,
            "detail": data
        }), status

    rows = extract_broker_rows(data)

    if not rows:
        return jsonify({
            "success": False,
            "error": "Format broker belum dikenali",
            "raw_preview": str(data)[:1500]
        }), 422

    result = score_from_broker_rows(rows)

    return jsonify({
        "success": True,
        "ticker": request.args.get(
            "ticker", ""
        ).upper(),
        "cache": response.headers.get(
            "X-StockRadar-Cache",
            "UNKNOWN"
        ),
        "broker_rows_found": len(rows),
        "result": result
    })
@app.route("/api/radar-test")
def radar_test():
    rows = [
        {"broker": "CC", "net": 12400000},
        {"broker": "XC", "net": 9100000},
        {"broker": "YP", "net": -3000000},
        {"broker": "ZP", "net": -2000000},
    ]

    result = score_from_broker_rows(rows)

    return jsonify({
        "success": True,
        "ticker": "TEST",
        "result": result
    })
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
