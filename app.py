from flask import Flask, request, jsonify
import requests
import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from radar_score import (
    score_from_broker_rows,
    score_from_market_data,
    score_trend_ohlcv,
    score_volume_ohlcv,
    score_risk_ohlcv,
)

app = Flask(__name__)

API_KEY = os.environ.get("INDEXALPHA_API_KEY")
BASE_URL = "https://api.indexalpha.id"
CACHE = {}
CACHE_TTL = 60 * 60 * 24

SCANNER_UNIVERSE = [
    # Banks & financials
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO", "BTPS", "BDMN", "NISP", "BTPN",
    "BBTN", "PNBN", "PNLF", "ADMF", "BFIN",
    # Telco, tech & digital
    "TLKM", "ISAT", "EXCL", "GOTO", "BUKA", "EMTK", "MTEL", "TOWR", "TBIG", "DCII",
    # Conglomerates & industrials
    "ASII", "UNTR", "AUTO", "HEXA", "IMAS", "INDY", "AKRA", "SMGR", "INTP", "WTON",
    # Energy, coal, oil & gas
    "ADRO", "ADMR", "PTBA", "ITMG", "HRUM", "BUMI", "BYAN", "PGAS", "MEDC", "ENRG",
    "ESSA", "RAJA", "ELSA", "TOBA", "SMMT",
    # Metals, mining & materials
    "ANTM", "INCO", "MDKA", "MBMA", "AMMN", "NCKL", "TINS", "BRMS", "ARCI", "PSAB",
    # Petrochemicals & basic materials
    "TPIA", "BRPT", "ESSA", "FPNI", "AGII", "AVIA", "INKP", "TKIM", "SMGR", "INTP",
    # Consumer staples & discretionary
    "ICBP", "INDF", "MYOR", "UNVR", "KLBF", "SIDO", "ULTJ", "CMRY", "GOOD", "ROTI",
    "CPIN", "JPFA", "MAIN", "MAPA", "MAPI", "ERAA", "ACES", "LPPF", "RALS", "MIDI",
    # Property & infrastructure
    "PANI", "PWON", "BSDE", "CTRA", "SMRA", "DMAS", "KIJA", "APLN", "TOTL", "ADHI",
    "WIKA", "PTPP", "JSMR", "CMNP", "META",
    # Healthcare
    "MIKA", "HEAL", "SILO", "PRDA", "TSPC", "KAEF", "INAF",
    # Transport & logistics
    "GIAA", "ASSA", "WEHA", "TMAS", "SMDR", "WINS", "HATM",
    # Media, tourism, lifestyle & newer stories
    "SCMA", "MNCN", "BMTR", "FILM", "RAAM", "RANS", "NAYZ", "PIPA", "RICY", "MEJA",
]


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
    """
    Ambil OHLCV dari Yahoo Finance supaya kuota IndexAlpha hanya
    dipakai untuk broker summary. Ini menghemat request free plan.
    """
    try:
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }, 400, "MISS"

    start_date = end_date - timedelta(days=180)
    symbol = f"{ticker}.JK"

    cache_key = f"yahoo_ohlcv_{symbol}_{start_date.isoformat()}_{end_date.isoformat()}"
    cached, cache_state = cache_get(cache_key)

    if cached and cache_state == "HIT":
        return cached["data"], cached["status"], "HIT"

    period1 = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    period2_date = end_date + timedelta(days=1)
    period2 = int(datetime.combine(period2_date, datetime.min.time()).timestamp())

    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={
                "period1": period1,
                "period2": period2,
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            },
            headers={
                "User-Agent": "Mozilla/5.0 StockRadar/1.0",
                "accept": "application/json",
            },
            timeout=25,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Yahoo OHLCV HTTP {response.status_code}",
            }, response.status_code, "MISS"

        payload = response.json()
        chart = payload.get("chart") or {}
        results = chart.get("result") or []

        if not results:
            return {
                "success": False,
                "error": "Yahoo OHLCV tidak menemukan data",
            }, 404, "MISS"

        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_list = (
            (result.get("indicators") or {}).get("quote") or [{}]
        )
        quote = quote_list[0] if quote_list else {}

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows = []

        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None

            if close is None:
                continue

            rows.append({
                "date": datetime.utcfromtimestamp(ts).date().isoformat(),
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": close,
                "volume": volumes[i] if i < len(volumes) else None,
            })

        data = {
            "success": True,
            "source": "yahoo_finance",
            "symbol": symbol,
            "data": rows,
        }

        cache_put(cache_key, data, 200)
        return data, 200, "MISS"

    except Exception as e:
        return {
            "success": False,
            "error": f"Yahoo OHLCV error: {e}",
        }, 500, "MISS"


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


def scan_one_ticker(ticker, date_to):
    data, status, cache_state = get_ohlcv(ticker, date_to)

    if status != 200:
        return None

    rows = extract_ohlcv_rows(data)

    if len(rows) < 20:
        return None

    recent20 = rows[-20:]

    active_days = sum(
        1 for row in recent20
        if float(row.get("volume") or 0) > 0
    )

    trading_values = [
        float(row.get("close") or 0) * float(row.get("volume") or 0)
        for row in recent20
        if float(row.get("close") or 0) > 0
        and float(row.get("volume") or 0) > 0
    ]

    avg_value_20 = (
        sum(trading_values) / len(trading_values)
        if trading_values else 0.0
    )

    # Filter saham yang terlalu sepi agar scanner tidak mudah terjebak false signal.
    if active_days < 15 or avg_value_20 < 2_000_000_000:
        return None

    trend = score_trend_ohlcv(rows)
    volume = score_volume_ohlcv(rows)
    risk = score_risk_ohlcv(rows)

    if not (
        trend.get("available")
        and volume.get("available")
        and risk.get("available")
    ):
        return None

    trend_score = float(trend["score"])
    volume_score = float(volume["score"])
    risk_score = float(risk["score"])

    liquidity_bonus = min(
        8.0,
        max(
            0.0,
            (avg_value_20 / 25_000_000_000) * 8.0,
        ),
    )

    scanner_score = (
        0.42 * trend_score
        + 0.30 * volume_score
        + 0.20 * risk_score
        + liquidity_bonus
    )

    trend_metrics = trend.get("metrics", {})
    volume_metrics = volume.get("metrics", {})
    risk_metrics = risk.get("metrics", {})

    close = float(trend_metrics.get("latest_close") or 0)
    ma20 = float(trend_metrics.get("ma20") or 0)
    atr14 = float(risk_metrics.get("atr14") or 0)

    if (
        trend_score >= 65
        and volume_score >= 60
        and risk_score >= 55
    ):
        setup = "Momentum"
    elif (
        trend_score >= 60
        and risk_score >= 55
    ):
        setup = "Watch Pullback"
    elif (
        trend_score >= 52
        and volume_score >= 55
    ):
        setup = "Early Watch"
    else:
        setup = "Netral"

    entry_low = max(0.0, ma20 - (0.50 * atr14))
    entry_high = max(0.0, ma20 + (0.35 * atr14))

    return {
        "ticker": ticker,
        "score": round(scanner_score, 1),
        "setup": setup,
        "close": round(close, 2),
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "trend_score": round(trend_score, 1),
        "volume_score": round(volume_score, 1),
        "risk_score": round(risk_score, 1),
        "momentum_20d": trend_metrics.get("momentum_20d"),
        "volume_ratio": volume_metrics.get("volume_ratio"),
        "atr_pct": risk_metrics.get("atr_pct"),
        "avg_value_20": round(avg_value_20, 2),
        "active_days_20": active_days,
        "cache": cache_state,
    }


def build_scanner_reason(item):
    setup = item.get("setup")
    trend = float(item.get("trend_score") or 0)
    volume = float(item.get("volume_score") or 0)
    risk = float(item.get("risk_score") or 0)

    reasons = []

    if trend >= 80:
        reasons.append("trend sangat kuat")
    elif trend >= 65:
        reasons.append("trend kuat")
    elif trend >= 55:
        reasons.append("trend mulai positif")

    if volume >= 65:
        reasons.append("volume mendukung")
    elif volume >= 55:
        reasons.append("volume mulai menguat")
    else:
        reasons.append("volume belum kuat")

    if risk >= 65:
        reasons.append("risiko relatif terkendali")
    elif risk >= 55:
        reasons.append("risiko masih layak dipantau")
    else:
        reasons.append("risiko perlu perhatian")

    if setup == "Momentum":
        action_note = "lebih cocok dipantau untuk kelanjutan momentum"
    elif setup == "Watch Pullback":
        action_note = "lebih cocok menunggu pullback ke area entry"
    elif setup == "Early Watch":
        action_note = "masih tahap awal, butuh konfirmasi tambahan"
    else:
        action_note = "belum actionable"

    return ", ".join(reasons) + "; " + action_note


@app.route("/api/scanner")
def scanner():
    date_to = request.args.get("to")

    if not date_to:
        return jsonify({
            "success": False,
            "error": "Parameter to wajib diisi",
        }), 400

    try:
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }), 400

    results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                scan_one_ticker,
                ticker,
                date_to,
            ): ticker
            for ticker in SCANNER_UNIVERSE
        }

        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None

            if item:
                results.append(item)

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    groups = {
        "momentum": [
            x for x in results
            if x["setup"] == "Momentum"
        ][:8],
        "pullback": [
            x for x in results
            if x["setup"] == "Watch Pullback"
        ][:8],
        "early": [
            x for x in results
            if x["setup"] == "Early Watch"
        ][:6],
        "neutral": [
            x for x in results
            if x["setup"] == "Netral"
        ][:5],
    }

    actionable = (
        groups["momentum"]
        + groups["pullback"]
        + groups["early"]
    )

    actionable.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    top_picks = []

    for rank, item in enumerate(actionable[:3], start=1):
        pick = dict(item)
        pick["rank"] = rank
        pick["reason"] = build_scanner_reason(item)
        pick["priority"] = (
            "A" if item["score"] >= 70
            else "B" if item["score"] >= 60
            else "C"
        )
        top_picks.append(pick)

    return jsonify({
        "success": True,
        "date": date_to,
        "source": "Yahoo Finance OHLCV",
        "universe_size": len(SCANNER_UNIVERSE),
        "scanned": len(results),
        "liquidity_filter": "avg value 20D >= Rp2B dan minimal 15 hari aktif",
        "note": "Scanner V3 menampilkan Top 3 kandidat dari setup actionable, lalu Analisa Full dipakai untuk konfirmasi broker.",
        "summary": {
            "momentum": len(groups["momentum"]),
            "pullback": len(groups["pullback"]),
            "early": len(groups["early"]),
            "neutral": len(groups["neutral"]),
            "actionable": len(actionable),
        },
        "top_picks": top_picks,
        "groups": groups,
        "results": actionable[:15],
    })


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
