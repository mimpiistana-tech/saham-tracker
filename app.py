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
    return jsonify({
        "status": "ok",
        "app": "StockRadar API"
    })

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
    if cache_key in CACHE:
        cached = CACHE[cache_key]

        umur = time.time() - cached["time"]

        if umur < CACHE_TTL:
            result = jsonify(cached["data"])
            result.headers["X-StockRadar-Cache"] = "HIT"
            return result, cached["status"]

        else:
            del CACHE[cache_key]

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

        result = jsonify(data)
        result.headers["X-StockRadar-Cache"] = "MISS"

        return result, response.status_code

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
