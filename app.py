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


def build_scanner_item_from_rows(ticker, rows, cache_state="HIST"):
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
    entry_mid = (
        (entry_low + entry_high) / 2
        if entry_high > 0
        else close
    )

    paper_cut_loss = max(
        0.0,
        entry_low - (0.75 * atr14),
    )
    paper_tp1 = entry_mid + (1.50 * atr14)
    paper_tp2 = entry_mid + (3.00 * atr14)

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
        "paper_plan": {
            "entry": round(entry_mid, 2),
            "cut_loss": round(paper_cut_loss, 2),
            "tp1": round(paper_tp1, 2),
            "tp2": round(paper_tp2, 2),
            "source": "scanner_technical_only",
            "note": "Simulasi teknikal awal tanpa broker summary",
        },
        "cache": cache_state,
    }


def scan_one_ticker(ticker, date_to):
    data, status, cache_state = get_ohlcv(ticker, date_to)

    if status != 200:
        return None

    rows = extract_ohlcv_rows(data)

    return build_scanner_item_from_rows(
        ticker,
        rows,
        cache_state,
    )


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

    market_regime = get_current_market_regime(
        date_to
    )

    return jsonify({
        "success": True,
        "date": date_to,
        "source": "Yahoo Finance OHLCV",
        "market_regime": market_regime,
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


def get_historical_ohlcv(ticker, date_to, calendar_days=1000):
    try:
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }, 400, "MISS"

    calendar_days = max(240, min(int(calendar_days), 1800))
    start_date = end_date - timedelta(days=calendar_days)
    symbol = f"{ticker}.JK"

    cache_key = (
        f"replay_ohlcv_{symbol}_"
        f"{start_date.isoformat()}_{end_date.isoformat()}"
    )

    cached, cache_state = cache_get(cache_key)

    if cached and cache_state == "HIT":
        return cached["data"], cached["status"], "HIT"

    period1 = int(
        datetime.combine(start_date, datetime.min.time()).timestamp()
    )
    period2 = int(
        datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time(),
        ).timestamp()
    )

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
                "error": f"Yahoo historical replay HTTP {response.status_code}",
            }, response.status_code, "MISS"

        payload = response.json()
        chart = payload.get("chart") or {}
        results = chart.get("result") or []

        if not results:
            return {
                "success": False,
                "error": "Yahoo historical replay tidak menemukan data",
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
            "error": f"Yahoo historical replay error: {e}",
        }, 500, "MISS"


def simulate_historical_trade(rows, signal_index, item, entry_wait, max_hold):
    plan = item.get("paper_plan") or {}

    entry = float(plan.get("entry") or 0)
    cut_loss = float(plan.get("cut_loss") or 0)
    tp1 = float(plan.get("tp1") or 0)
    tp2 = float(plan.get("tp2") or 0)

    if not (
        entry > 0
        and cut_loss > 0
        and tp1 > entry
        and tp2 > tp1
        and cut_loss < entry
    ):
        return {
            "entered": False,
            "end_index": signal_index,
            "reason": "invalid_plan",
        }

    first_future = signal_index + 1
    last_entry_index = min(
        len(rows) - 1,
        signal_index + max(1, entry_wait),
    )

    entry_index = None

    for j in range(first_future, last_entry_index + 1):
        row = rows[j]
        high = float(row.get("high") or row.get("close") or 0)
        low = float(row.get("low") or row.get("close") or 0)

        if low <= entry <= high:
            entry_index = j
            break

    if entry_index is None:
        return {
            "entered": False,
            "end_index": last_entry_index,
            "reason": "entry_not_touched",
        }

    tp1_hit = False
    exit_status = "TIME"
    exit_price = None
    exit_index = entry_index

    last_hold_index = min(
        len(rows) - 1,
        entry_index + max(1, max_hold) - 1,
    )

    for j in range(entry_index, last_hold_index + 1):
        row = rows[j]
        high = float(row.get("high") or row.get("close") or 0)
        low = float(row.get("low") or row.get("close") or 0)

        # Daily candle cannot reveal intraday ordering.
        # Conservative tie-break: CL is evaluated before TP on the same candle.
        if low <= cut_loss:
            exit_status = "CL"
            exit_price = cut_loss
            exit_index = j
            break

        if high >= tp1:
            tp1_hit = True

        if high >= tp2:
            exit_status = "TP2"
            exit_price = tp2
            exit_index = j
            break

        exit_index = j

    if exit_price is None:
        exit_price = float(
            rows[exit_index].get("close") or entry
        )

    pnl_pct = (
        ((exit_price / entry) - 1) * 100
        if entry > 0
        else 0.0
    )

    return {
        "entered": True,
        "end_index": exit_index,
        "trade": {
            "ticker": item.get("ticker"),
            "signal_date": rows[signal_index].get("date"),
            "entry_date": rows[entry_index].get("date"),
            "exit_date": rows[exit_index].get("date"),
            "setup": item.get("setup"),
            "score": float(item.get("score") or 0),
            "trend_score": float(item.get("trend_score") or 0),
            "volume_score": float(item.get("volume_score") or 0),
            "risk_score": float(item.get("risk_score") or 0),
            "entry": round(entry, 2),
            "cut_loss": round(cut_loss, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "exit_price": round(exit_price, 2),
            "status": exit_status,
            "tp1_hit": tp1_hit,
            "pnl_pct": round(pnl_pct, 4),
            "hold_sessions": (exit_index - entry_index) + 1,
        },
    }


def summarize_historical_trades(trades):
    total = len(trades)

    pnl_values = [
        float(x.get("pnl_pct") or 0)
        for x in trades
    ]

    wins = [x for x in pnl_values if x > 0]
    losses = [x for x in pnl_values if x < 0]

    win_rate = (
        (len(wins) / total) * 100
        if total else None
    )

    expectancy = (
        sum(pnl_values) / total
        if total else None
    )

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for pnl in pnl_values:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = max(
            max_drawdown,
            peak - cumulative,
        )

    tp1_hits = sum(
        1 for x in trades
        if x.get("tp1_hit")
    )

    return {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            round(win_rate, 2)
            if win_rate is not None
            else None
        ),
        "expectancy": (
            round(expectancy, 4)
            if expectancy is not None
            else None
        ),
        "profit_factor": (
            round(profit_factor, 4)
            if profit_factor is not None
            else None
        ),
        "max_drawdown": round(max_drawdown, 4),
        "cumulative_pnl": round(cumulative, 4),
        "tp1_hit_rate": (
            round((tp1_hits / total) * 100, 2)
            if total else None
        ),
    }


@app.route("/api/historical-replay")
def historical_replay():
    ticker = request.args.get("ticker", "").upper().strip()
    date_to = request.args.get("to")

    try:
        lookback_sessions = int(
            request.args.get("sessions", "300")
        )
        max_trades = int(
            request.args.get("max_trades", "50")
        )
        entry_wait = int(
            request.args.get("entry_wait", "5")
        )
        max_hold = int(
            request.args.get("max_hold", "20")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Parameter replay harus berupa angka",
        }), 400

    if not ticker or not date_to:
        return jsonify({
            "success": False,
            "error": "ticker dan to wajib diisi",
        }), 400

    try:
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }), 400

    lookback_sessions = max(
        80,
        min(lookback_sessions, 600),
    )
    max_trades = max(
        5,
        min(max_trades, 100),
    )
    entry_wait = max(
        1,
        min(entry_wait, 10),
    )
    max_hold = max(
        3,
        min(max_hold, 60),
    )

    calendar_days = min(
        1800,
        max(
            500,
            int(lookback_sessions * 2.2) + 260,
        ),
    )

    data, status, cache_state = get_historical_ohlcv(
        ticker,
        date_to,
        calendar_days,
    )

    if status != 200:
        return jsonify(data), status

    rows = extract_ohlcv_rows(data)

    if len(rows) < 80:
        return jsonify({
            "success": False,
            "error": "Data historis belum cukup untuk replay",
        }), 422

    start_index = max(
        60,
        len(rows) - lookback_sessions,
    )

    trades = []
    signals_seen = 0
    expired_signals = 0
    i = start_index

    while i < len(rows) - 1 and len(trades) < max_trades:
        history = rows[:i + 1]

        item = build_scanner_item_from_rows(
            ticker,
            history,
            "REPLAY",
        )

        if (
            not item
            or item.get("setup") not in {
                "Momentum",
                "Watch Pullback",
                "Early Watch",
            }
            or float(item.get("score") or 0) < 55
        ):
            i += 1
            continue

        signals_seen += 1

        simulation = simulate_historical_trade(
            rows,
            i,
            item,
            entry_wait,
            max_hold,
        )

        if simulation.get("entered"):
            trades.append(simulation["trade"])
        else:
            expired_signals += 1

        next_index = int(
            simulation.get("end_index", i)
        )

        i = max(
            i + 1,
            next_index + 1,
        )

    summary = summarize_historical_trades(trades)

    setup_summary = {}

    for setup in [
        "Momentum",
        "Watch Pullback",
        "Early Watch",
    ]:
        setup_trades = [
            x for x in trades
            if x.get("setup") == setup
        ]

        if setup_trades:
            setup_summary[setup] = (
                summarize_historical_trades(setup_trades)
            )

    return jsonify({
        "success": True,
        "ticker": ticker,
        "date_to": date_to,
        "source": "Yahoo Finance daily OHLCV",
        "cache": cache_state,
        "settings": {
            "lookback_sessions": lookback_sessions,
            "max_trades": max_trades,
            "entry_wait_sessions": entry_wait,
            "max_hold_sessions": max_hold,
        },
        "assumptions": [
            "Sinyal dibuat setelah candle harian selesai; entry baru boleh mulai hari berikutnya.",
            "Jika CL dan target sama-sama tersentuh pada candle harian yang sama, replay memilih CL (asumsi konservatif).",
            "Replay teknikal tidak memakai broker summary IndexAlpha.",
            "Biaya transaksi, slippage, antrean order, dan corporate action belum dimasukkan.",
            "Historical replay tidak menggantikan forward Paper Trade.",
        ],
        "signals_seen": signals_seen,
        "expired_signals": expired_signals,
        "summary": summary,
        "setup_summary": setup_summary,
        "trades": trades,
    })



def run_historical_replay_ticker(
    ticker,
    date_to,
    lookback_sessions=300,
    max_trades=30,
    entry_wait=5,
    max_hold=20,
):
    calendar_days = min(
        1800,
        max(
            500,
            int(lookback_sessions * 2.2) + 260,
        ),
    )

    data, status, cache_state = get_historical_ohlcv(
        ticker,
        date_to,
        calendar_days,
    )

    if status != 200:
        return {
            "success": False,
            "ticker": ticker,
            "error": data.get("error", "Replay gagal"),
            "status": status,
        }

    rows = extract_ohlcv_rows(data)

    if len(rows) < 80:
        return {
            "success": False,
            "ticker": ticker,
            "error": "Data historis belum cukup untuk replay",
            "status": 422,
        }

    start_index = max(
        60,
        len(rows) - lookback_sessions,
    )

    trades = []
    signals_seen = 0
    expired_signals = 0
    i = start_index

    while i < len(rows) - 1 and len(trades) < max_trades:
        history = rows[:i + 1]

        item = build_scanner_item_from_rows(
            ticker,
            history,
            "REPLAY",
        )

        if (
            not item
            or item.get("setup") not in {
                "Momentum",
                "Watch Pullback",
                "Early Watch",
            }
            or float(item.get("score") or 0) < 55
        ):
            i += 1
            continue

        signals_seen += 1

        simulation = simulate_historical_trade(
            rows,
            i,
            item,
            entry_wait,
            max_hold,
        )

        if simulation.get("entered"):
            trades.append(simulation["trade"])
        else:
            expired_signals += 1

        next_index = int(
            simulation.get("end_index", i)
        )

        i = max(
            i + 1,
            next_index + 1,
        )

    summary = summarize_historical_trades(trades)

    return {
        "success": True,
        "ticker": ticker,
        "cache": cache_state,
        "signals_seen": signals_seen,
        "expired_signals": expired_signals,
        "summary": summary,
        "trades": trades,
    }


@app.route("/api/historical-replay-batch")
def historical_replay_batch():
    raw_tickers = request.args.get("tickers", "")
    date_to = request.args.get("to")

    try:
        lookback_sessions = int(
            request.args.get("sessions", "300")
        )
        max_trades = int(
            request.args.get("max_trades", "30")
        )
        entry_wait = int(
            request.args.get("entry_wait", "5")
        )
        max_hold = int(
            request.args.get("max_hold", "20")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Parameter batch replay harus berupa angka",
        }), 400

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

    requested = []

    for part in raw_tickers.replace(";", ",").split(","):
        ticker = part.strip().upper()

        if not ticker:
            continue

        if ticker not in requested:
            requested.append(ticker)

    if not requested:
        requested = [
            "BBRI", "BBCA", "BMRI", "TLKM", "ASII",
            "UNTR", "PTBA", "ANTM", "SMDR", "PWON",
        ]

    requested = requested[:20]

    lookback_sessions = max(
        80,
        min(lookback_sessions, 600),
    )
    max_trades = max(
        5,
        min(max_trades, 50),
    )
    entry_wait = max(
        1,
        min(entry_wait, 10),
    )
    max_hold = max(
        3,
        min(max_hold, 60),
    )

    results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                run_historical_replay_ticker,
                ticker,
                date_to,
                lookback_sessions,
                max_trades,
                entry_wait,
                max_hold,
            ): ticker
            for ticker in requested
        }

        for future in as_completed(futures):
            ticker = futures[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "success": False,
                    "ticker": ticker,
                    "error": str(e),
                    "status": 500,
                }

            results.append(result)

    results.sort(
        key=lambda x: requested.index(x.get("ticker"))
        if x.get("ticker") in requested
        else 999
    )

    successful = [
        x for x in results
        if x.get("success")
    ]

    failed = [
        x for x in results
        if not x.get("success")
    ]

    all_trades = []

    for result in successful:
        all_trades.extend(
            result.get("trades") or []
        )

    all_trades.sort(
        key=lambda x: (
            x.get("exit_date") or "",
            x.get("ticker") or "",
        )
    )

    combined_summary = summarize_historical_trades(
        all_trades
    )

    setup_summary = {}

    for setup in [
        "Momentum",
        "Watch Pullback",
        "Early Watch",
    ]:
        setup_trades = [
            x for x in all_trades
            if x.get("setup") == setup
        ]

        if setup_trades:
            setup_summary[setup] = (
                summarize_historical_trades(setup_trades)
            )

    score_bands = [
        ("Score <55", lambda score: score < 55),
        ("Score 55-64.9", lambda score: 55 <= score < 65),
        ("Score 65-74.9", lambda score: 65 <= score < 75),
        ("Score 75+", lambda score: score >= 75),
    ]

    score_summary = {}

    for label, predicate in score_bands:
        band_trades = [
            x for x in all_trades
            if predicate(float(x.get("score") or 0))
        ]

        if band_trades:
            score_summary[label] = (
                summarize_historical_trades(band_trades)
            )

    per_ticker = []

    for result in successful:
        per_ticker.append({
            "ticker": result.get("ticker"),
            "signals_seen": result.get("signals_seen", 0),
            "expired_signals": result.get("expired_signals", 0),
            "summary": result.get("summary") or {},
        })

    return jsonify({
        "success": True,
        "date_to": date_to,
        "source": "Yahoo Finance daily OHLCV",
        "settings": {
            "lookback_sessions": lookback_sessions,
            "max_trades_per_ticker": max_trades,
            "entry_wait_sessions": entry_wait,
            "max_hold_sessions": max_hold,
            "ticker_count": len(requested),
        },
        "assumptions": [
            "Batch memakai aturan replay teknikal yang sama dengan Single Historical Replay.",
            "Broker summary IndexAlpha tidak dipakai.",
            "Jika CL dan target tersentuh pada candle harian yang sama, replay memilih CL.",
            "Biaya transaksi, slippage, antrean order, dan corporate action belum dimasukkan.",
            "Hasil batch tidak menggantikan forward Paper Trade.",
        ],
        "tickers": requested,
        "successful_tickers": len(successful),
        "failed_tickers": len(failed),
        "failed": failed,
        "summary": combined_summary,
        "setup_summary": setup_summary,
        "score_summary": score_summary,
        "per_ticker": per_ticker,
        "trades": all_trades[-50:],
    })



def find_historical_entry(rows, signal_index, item, entry_wait):
    plan = item.get("paper_plan") or {}
    entry = float(plan.get("entry") or 0)

    if entry <= 0:
        return None

    first_future = signal_index + 1
    last_entry_index = min(
        len(rows) - 1,
        signal_index + max(1, entry_wait),
    )

    for j in range(first_future, last_entry_index + 1):
        row = rows[j]
        high = float(row.get("high") or row.get("close") or 0)
        low = float(row.get("low") or row.get("close") or 0)

        if low <= entry <= high:
            return j

    return None


def simulate_exit_model(
    rows,
    signal_index,
    entry_index,
    item,
    max_hold,
    mode,
):
    plan = item.get("paper_plan") or {}

    entry = float(plan.get("entry") or 0)
    cut_loss = float(plan.get("cut_loss") or 0)
    tp1 = float(plan.get("tp1") or 0)
    tp2 = float(plan.get("tp2") or 0)

    if not (
        entry > 0
        and cut_loss > 0
        and tp1 > entry
        and tp2 > tp1
        and cut_loss < entry
    ):
        return None

    last_hold_index = min(
        len(rows) - 1,
        entry_index + max(1, max_hold) - 1,
    )

    tp1_hit = False
    partial_done = False
    exit_index = entry_index
    status = "TIME"

    realized_weighted_return = 0.0
    open_weight = 1.0

    def ret(price):
        return (float(price) / entry) - 1.0

    for j in range(entry_index, last_hold_index + 1):
        row = rows[j]
        high = float(row.get("high") or row.get("close") or 0)
        low = float(row.get("low") or row.get("close") or 0)

        # Daily OHLC does not reveal intraday order.
        # Conservative tie-break: stop is checked before target.
        active_stop = (
            entry
            if mode == "C" and partial_done
            else cut_loss
        )

        if low <= active_stop:
            realized_weighted_return += (
                open_weight * ret(active_stop)
            )
            open_weight = 0.0
            exit_index = j

            if partial_done:
                status = (
                    "TP1_BE"
                    if active_stop == entry
                    else "TP1_CL"
                )
            else:
                status = "CL"

            break

        if not partial_done and high >= tp1:
            tp1_hit = True

            if mode in {"B", "C"}:
                realized_weighted_return += (
                    0.5 * ret(tp1)
                )
                open_weight = 0.5
                partial_done = True

                # For model C, if TP1 and breakeven are both inside
                # the same daily candle, assume the runner exits BE.
                if mode == "C" and low <= entry:
                    realized_weighted_return += (
                        open_weight * ret(entry)
                    )
                    open_weight = 0.0
                    exit_index = j
                    status = "TP1_BE"
                    break

        if high >= tp2:
            if mode == "A":
                realized_weighted_return += ret(tp2)
                open_weight = 0.0
                status = "TP2"
            else:
                realized_weighted_return += (
                    open_weight * ret(tp2)
                )
                open_weight = 0.0
                status = "TP1_TP2"

            exit_index = j
            break

        exit_index = j

    if open_weight > 0:
        last_close = float(
            rows[exit_index].get("close") or entry
        )

        realized_weighted_return += (
            open_weight * ret(last_close)
        )

        status = (
            "TP1_TIME"
            if partial_done
            else "TIME"
        )

        open_weight = 0.0

    pnl_pct = realized_weighted_return * 100.0
    effective_exit = entry * (1.0 + realized_weighted_return)

    return {
        "ticker": item.get("ticker"),
        "signal_date": rows[signal_index].get("date"),
        "entry_date": rows[entry_index].get("date"),
        "exit_date": rows[exit_index].get("date"),
        "setup": item.get("setup"),
        "score": float(item.get("score") or 0),
        "entry": round(entry, 2),
        "cut_loss": round(cut_loss, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "effective_exit": round(effective_exit, 2),
        "status": status,
        "tp1_hit": tp1_hit,
        "pnl_pct": round(pnl_pct, 4),
        "hold_sessions": (exit_index - entry_index) + 1,
        "exit_model": mode,
    }


def collect_ab_replay_for_ticker(
    ticker,
    date_to,
    lookback_sessions,
    max_signals,
    entry_wait,
    max_hold,
):
    calendar_days = min(
        1800,
        max(
            500,
            int(lookback_sessions * 2.2) + 260,
        ),
    )

    data, status, cache_state = get_historical_ohlcv(
        ticker,
        date_to,
        calendar_days,
    )

    if status != 200:
        return {
            "success": False,
            "ticker": ticker,
            "error": data.get("error", "Replay gagal"),
        }

    rows = extract_ohlcv_rows(data)

    if len(rows) < 80:
        return {
            "success": False,
            "ticker": ticker,
            "error": "Data historis belum cukup",
        }

    start_index = max(
        60,
        len(rows) - lookback_sessions,
    )

    entries = []
    signals_seen = 0
    expired_signals = 0
    i = start_index

    while i < len(rows) - 1 and len(entries) < max_signals:
        history = rows[:i + 1]

        item = build_scanner_item_from_rows(
            ticker,
            history,
            "REPLAY_AB",
        )

        if (
            not item
            or item.get("setup") not in {
                "Momentum",
                "Watch Pullback",
                "Early Watch",
            }
            or float(item.get("score") or 0) < 55
        ):
            i += 1
            continue

        signals_seen += 1

        entry_index = find_historical_entry(
            rows,
            i,
            item,
            entry_wait,
        )

        if entry_index is None:
            expired_signals += 1
            i += max(1, entry_wait)
            continue

        entries.append({
            "signal_index": i,
            "entry_index": entry_index,
            "item": item,
        })

        # Fixed cooldown keeps the exact same signal set for A/B/C
        # and reduces repeated near-identical daily signals.
        i = entry_index + 5

    models = {
        "A": [],
        "B": [],
        "C": [],
    }

    for candidate in entries:
        for mode in models:
            trade = simulate_exit_model(
                rows,
                candidate["signal_index"],
                candidate["entry_index"],
                candidate["item"],
                max_hold,
                mode,
            )

            if trade:
                models[mode].append(trade)

    return {
        "success": True,
        "ticker": ticker,
        "cache": cache_state,
        "signals_seen": signals_seen,
        "expired_signals": expired_signals,
        "entries": len(entries),
        "models": models,
    }


@app.route("/api/historical-exit-ab")
def historical_exit_ab():
    raw_tickers = request.args.get("tickers", "")
    date_to = request.args.get("to")

    try:
        lookback_sessions = int(
            request.args.get("sessions", "300")
        )
        max_signals = int(
            request.args.get("max_signals", "30")
        )
        entry_wait = int(
            request.args.get("entry_wait", "5")
        )
        max_hold = int(
            request.args.get("max_hold", "20")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Parameter A/B replay harus berupa angka",
        }), 400

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

    requested = []

    for part in raw_tickers.replace(";", ",").split(","):
        ticker = part.strip().upper()

        if ticker and ticker not in requested:
            requested.append(ticker)

    if not requested:
        requested = [
            "BBRI", "BBCA", "BMRI", "TLKM", "ASII",
            "UNTR", "PTBA", "ANTM", "SMDR", "PWON",
        ]

    requested = requested[:20]

    lookback_sessions = max(
        80,
        min(lookback_sessions, 600),
    )
    max_signals = max(
        5,
        min(max_signals, 50),
    )
    entry_wait = max(
        1,
        min(entry_wait, 10),
    )
    max_hold = max(
        3,
        min(max_hold, 60),
    )

    results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                collect_ab_replay_for_ticker,
                ticker,
                date_to,
                lookback_sessions,
                max_signals,
                entry_wait,
                max_hold,
            ): ticker
            for ticker in requested
        }

        for future in as_completed(futures):
            ticker = futures[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "success": False,
                    "ticker": ticker,
                    "error": str(e),
                }

            results.append(result)

    successful = [
        x for x in results
        if x.get("success")
    ]

    failed = [
        x for x in results
        if not x.get("success")
    ]

    combined = {
        "A": [],
        "B": [],
        "C": [],
    }

    for result in successful:
        for mode in combined:
            combined[mode].extend(
                result.get("models", {}).get(mode, [])
            )

    labels = {
        "A": "Full position: TP2 atau CL",
        "B": "50% TP1 + 50% runner ke TP2/CL",
        "C": "50% TP1 + runner stop breakeven",
    }

    model_summary = {}
    setup_summary = {}

    for mode, trades in combined.items():
        trades.sort(
            key=lambda x: (
                x.get("exit_date") or "",
                x.get("ticker") or "",
            )
        )

        model_summary[mode] = {
            "label": labels[mode],
            "summary": summarize_historical_trades(trades),
        }

        setup_summary[mode] = {}

        for setup in [
            "Momentum",
            "Watch Pullback",
            "Early Watch",
        ]:
            subset = [
                x for x in trades
                if x.get("setup") == setup
            ]

            if subset:
                setup_summary[mode][setup] = (
                    summarize_historical_trades(subset)
                )

    per_ticker = []

    for result in successful:
        row = {
            "ticker": result.get("ticker"),
            "entries": result.get("entries", 0),
            "signals_seen": result.get("signals_seen", 0),
            "models": {},
        }

        for mode in ["A", "B", "C"]:
            row["models"][mode] = summarize_historical_trades(
                result.get("models", {}).get(mode, [])
            )

        per_ticker.append(row)

    per_ticker.sort(
        key=lambda x: requested.index(x["ticker"])
        if x["ticker"] in requested
        else 999
    )

    return jsonify({
        "success": True,
        "date_to": date_to,
        "source": "Yahoo Finance daily OHLCV",
        "settings": {
            "lookback_sessions": lookback_sessions,
            "max_signals_per_ticker": max_signals,
            "entry_wait_sessions": entry_wait,
            "max_hold_sessions": max_hold,
            "ticker_count": len(requested),
            "fixed_signal_cooldown_sessions": 5,
        },
        "models": model_summary,
        "setup_summary": setup_summary,
        "per_ticker": per_ticker,
        "failed": failed,
        "assumptions": [
            "Semua model memakai signal dan entry yang sama agar perbandingan exit lebih adil.",
            "Model A menahan seluruh posisi ke TP2/CL.",
            "Model B merealisasikan 50% di TP1 dan 50% sisanya ke TP2 atau CL awal.",
            "Model C merealisasikan 50% di TP1 lalu menaikkan stop sisa posisi ke breakeven.",
            "Jika stop dan target berada pada candle harian yang sama, stop dievaluasi lebih dulu.",
            "Biaya transaksi dan slippage belum dimasukkan.",
            "Hasil A/B tidak menggantikan forward Paper Trade.",
        ],
    })



def walk_forward_status(train_summary, test_summary):
    train_n = int(train_summary.get("trades") or 0)
    test_n = int(test_summary.get("trades") or 0)

    train_exp = train_summary.get("expectancy")
    test_exp = test_summary.get("expectancy")
    test_pf = test_summary.get("profit_factor")

    if train_n < 20 or test_n < 10:
        return {
            "level": "EARLY",
            "label": "Sampel holdout masih kecil",
            "class": "yellow",
        }

    if (
        train_exp is not None
        and test_exp is not None
        and float(train_exp) > 0
        and float(test_exp) > 0
        and (
            test_pf is None
            or float(test_pf) >= 1.0
        )
    ):
        return {
            "level": "POSITIVE",
            "label": "Holdout positif",
            "class": "green",
        }

    if (
        train_exp is not None
        and float(train_exp) > 0
        and test_exp is not None
        and float(test_exp) <= 0
    ):
        return {
            "level": "DEGRADED",
            "label": "Degradasi di holdout",
            "class": "red",
        }

    if (
        train_exp is not None
        and test_exp is not None
        and float(train_exp) <= 0
        and float(test_exp) > 0
    ):
        return {
            "level": "MIXED",
            "label": "Hasil campuran",
            "class": "yellow",
        }

    return {
        "level": "NEGATIVE",
        "label": "Belum positif lintas periode",
        "class": "red",
    }


@app.route("/api/walk-forward-cutoff")
def walk_forward_cutoff():
    date_to = request.args.get("to")
    reference = (
        request.args.get("reference", "BBCA")
        .upper()
        .strip()
    )

    try:
        lookback_sessions = int(
            request.args.get("sessions", "300")
        )
        train_pct = int(
            request.args.get("train_pct", "70")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": "sessions dan train_pct harus berupa angka",
        }), 400

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

    lookback_sessions = max(
        120,
        min(lookback_sessions, 600),
    )

    train_pct = max(
        50,
        min(train_pct, 85),
    )

    calendar_days = min(
        1800,
        max(
            500,
            int(lookback_sessions * 2.2) + 260,
        ),
    )

    data, status, cache_state = get_historical_ohlcv(
        reference,
        date_to,
        calendar_days,
    )

    if status != 200:
        return jsonify({
            "success": False,
            "error": data.get(
                "error",
                "Gagal mengambil trading calendar",
            ),
        }), status

    rows = extract_ohlcv_rows(data)
    rows = rows[-lookback_sessions:]

    if len(rows) < 20:
        return jsonify({
            "success": False,
            "error": "Trading calendar terlalu pendek",
        }), 422

    split_index = int(
        len(rows) * (train_pct / 100.0)
    )

    split_index = max(
        1,
        min(split_index, len(rows) - 1),
    )

    cutoff_date = rows[
        split_index - 1
    ].get("date")

    return jsonify({
        "success": True,
        "reference": reference,
        "source": "Yahoo Finance daily OHLCV",
        "cache": cache_state,
        "lookback_sessions_requested": lookback_sessions,
        "calendar_sessions_used": len(rows),
        "train_pct": train_pct,
        "test_pct": 100 - train_pct,
        "cutoff_signal_date": cutoff_date,
        "first_date": rows[0].get("date"),
        "last_date": rows[-1].get("date"),
        "note": (
            "Cutoff ini dipakai sama untuk semua batch "
            "agar train/holdout apple-to-apple."
        ),
    })


@app.route("/api/historical-walk-forward")
def historical_walk_forward():
    raw_tickers = request.args.get("tickers", "")
    date_to = request.args.get("to")
    cutoff_date = (
        request.args.get("cutoff_date", "")
        .strip()
    )

    try:
        lookback_sessions = int(
            request.args.get("sessions", "600")
        )
        max_signals = int(
            request.args.get("max_signals", "50")
        )
        entry_wait = int(
            request.args.get("entry_wait", "5")
        )
        max_hold = int(
            request.args.get("max_hold", "20")
        )
        train_pct = int(
            request.args.get("train_pct", "70")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Parameter walk-forward harus berupa angka",
        }), 400

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

    if cutoff_date:
        try:
            datetime.strptime(
                cutoff_date,
                "%Y-%m-%d",
            )
        except ValueError:
            return jsonify({
                "success": False,
                "error": "Format cutoff_date harus YYYY-MM-DD",
            }), 400

    requested = []

    for part in raw_tickers.replace(";", ",").split(","):
        ticker = part.strip().upper()

        if ticker and ticker not in requested:
            requested.append(ticker)

    if not requested:
        requested = [
            "BBRI", "BBCA", "BMRI", "TLKM", "ASII",
            "UNTR", "PTBA", "ANTM", "SMDR", "PWON",
        ]

    requested = requested[:20]

    lookback_sessions = max(
        120,
        min(lookback_sessions, 600),
    )
    max_signals = max(
        10,
        min(max_signals, 50),
    )
    entry_wait = max(
        1,
        min(entry_wait, 10),
    )
    max_hold = max(
        3,
        min(max_hold, 60),
    )
    train_pct = max(
        50,
        min(train_pct, 85),
    )

    results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                collect_ab_replay_for_ticker,
                ticker,
                date_to,
                lookback_sessions,
                max_signals,
                entry_wait,
                max_hold,
            ): ticker
            for ticker in requested
        }

        for future in as_completed(futures):
            ticker = futures[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "success": False,
                    "ticker": ticker,
                    "error": str(e),
                }

            results.append(result)

    successful = [
        x for x in results
        if x.get("success")
    ]

    failed = [
        x for x in results
        if not x.get("success")
    ]

    combined = {
        "A": [],
        "B": [],
        "C": [],
    }

    for result in successful:
        for mode in combined:
            combined[mode].extend(
                result.get("models", {}).get(mode, [])
            )

    for mode in combined:
        combined[mode].sort(
            key=lambda x: (
                x.get("signal_date") or "",
                x.get("ticker") or "",
            )
        )

    reference = combined["A"]

    if len(reference) < 20:
        return jsonify({
            "success": False,
            "error": (
                "Sampel replay terlalu kecil untuk walk-forward. "
                "Tambah sesi/ticker."
            ),
            "trades": len(reference),
        }), 422

    if cutoff_date:
        cutoff_signal_date = cutoff_date
        cutoff_source = "global_fixed"
    else:
        split_index = int(
            len(reference) * (train_pct / 100.0)
        )

        split_index = max(
            1,
            min(split_index, len(reference) - 1),
        )

        cutoff_signal_date = (
            reference[split_index - 1].get("signal_date")
        )
        cutoff_source = "batch_fallback"

    labels = {
        "A": "Full position: TP2 atau CL",
        "B": "50% TP1 + 50% runner ke TP2/CL",
        "C": "50% TP1 + runner stop breakeven",
    }

    models = {}

    for mode, trades in combined.items():
        train = [
            x for x in trades
            if (x.get("signal_date") or "") <= cutoff_signal_date
        ]

        test = [
            x for x in trades
            if (x.get("signal_date") or "") > cutoff_signal_date
        ]

        train_summary = summarize_historical_trades(train)
        test_summary = summarize_historical_trades(test)

        setup_split = {}

        for setup in [
            "Momentum",
            "Watch Pullback",
            "Early Watch",
        ]:
            setup_train = [
                x for x in train
                if x.get("setup") == setup
            ]

            setup_test = [
                x for x in test
                if x.get("setup") == setup
            ]

            if setup_train or setup_test:
                setup_split[setup] = {
                    "train": summarize_historical_trades(
                        setup_train
                    ),
                    "test": summarize_historical_trades(
                        setup_test
                    ),
                }

        models[mode] = {
            "label": labels[mode],
            "status": walk_forward_status(
                train_summary,
                test_summary,
            ),
            "train": train_summary,
            "test": test_summary,
            "setup_split": setup_split,
        }

    return jsonify({
        "success": True,
        "date_to": date_to,
        "source": "Yahoo Finance daily OHLCV",
        "settings": {
            "lookback_sessions": lookback_sessions,
            "max_signals_per_ticker": max_signals,
            "entry_wait_sessions": entry_wait,
            "max_hold_sessions": max_hold,
            "ticker_count": len(requested),
            "train_pct": train_pct,
            "test_pct": 100 - train_pct,
            "cutoff_signal_date": cutoff_signal_date,
            "cutoff_source": cutoff_source,
        },
        "successful_tickers": len(successful),
        "failed_tickers": len(failed),
        "failed": failed,
        "models": models,
        "assumptions": [
            "Split dibuat kronologis: periode lama untuk development, periode terbaru sebagai holdout.",
            "Jika cutoff_date dikirim, semua batch memakai tanggal cutoff global yang sama.",
            "Signal dan entry tiap model A/B/C tetap sama; yang dibandingkan hanya exit.",
            "Holdout tidak dipakai untuk mengubah aturan selama pengujian.",
            "Broker IndexAlpha tidak dipakai.",
            "Biaya transaksi dan slippage belum dimasukkan.",
            "Walk-forward historis tetap tidak menggantikan forward Paper Trade.",
        ],
    })



def get_yahoo_symbol_history(symbol, date_to, calendar_days=1000):
    try:
        end_date = datetime.strptime(
            date_to,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return {
            "success": False,
            "error": "Format tanggal harus YYYY-MM-DD",
        }, 400, "MISS"

    calendar_days = max(
        240,
        min(int(calendar_days), 1800),
    )

    start_date = end_date - timedelta(
        days=calendar_days
    )

    cache_key = (
        f"generic_ohlcv_{symbol}_"
        f"{start_date.isoformat()}_"
        f"{end_date.isoformat()}"
    )

    cached, cache_state = cache_get(cache_key)

    if cached and cache_state == "HIT":
        return (
            cached["data"],
            cached["status"],
            "HIT",
        )

    period1 = int(
        datetime.combine(
            start_date,
            datetime.min.time(),
        ).timestamp()
    )

    period2 = int(
        datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time(),
        ).timestamp()
    )

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
                "error": (
                    f"Yahoo {symbol} HTTP "
                    f"{response.status_code}"
                ),
            }, response.status_code, "MISS"

        payload = response.json()
        chart = payload.get("chart") or {}
        results = chart.get("result") or []

        if not results:
            return {
                "success": False,
                "error": (
                    f"Yahoo tidak menemukan data "
                    f"{symbol}"
                ),
            }, 404, "MISS"

        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_list = (
            (result.get("indicators") or {})
            .get("quote") or [{}]
        )
        quote = (
            quote_list[0]
            if quote_list
            else {}
        )

        closes = quote.get("close") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        opens = quote.get("open") or []
        volumes = quote.get("volume") or []

        rows = []

        for i, ts in enumerate(timestamps):
            close = (
                closes[i]
                if i < len(closes)
                else None
            )

            if close is None:
                continue

            rows.append({
                "date": (
                    datetime.utcfromtimestamp(ts)
                    .date()
                    .isoformat()
                ),
                "open": (
                    opens[i]
                    if i < len(opens)
                    else None
                ),
                "high": (
                    highs[i]
                    if i < len(highs)
                    else None
                ),
                "low": (
                    lows[i]
                    if i < len(lows)
                    else None
                ),
                "close": close,
                "volume": (
                    volumes[i]
                    if i < len(volumes)
                    else None
                ),
            })

        data = {
            "success": True,
            "source": "yahoo_finance",
            "symbol": symbol,
            "data": rows,
        }

        cache_put(
            cache_key,
            data,
            200,
        )

        return data, 200, "MISS"

    except Exception as e:
        return {
            "success": False,
            "error": (
                f"Yahoo {symbol} error: {e}"
            ),
        }, 500, "MISS"


def build_market_regime_map(rows):
    clean = [
        x for x in rows
        if x.get("date")
        and x.get("close") is not None
    ]

    closes = [
        float(x.get("close") or 0)
        for x in clean
    ]

    regimes = {}

    for i, row in enumerate(clean):
        if i < 199:
            regimes[row["date"]] = "Unknown"
            continue

        ma50 = (
            sum(closes[i - 49:i + 1])
            / 50.0
        )

        ma200 = (
            sum(closes[i - 199:i + 1])
            / 200.0
        )

        close = closes[i]

        ma50_prev = None

        if i >= 219:
            ma50_prev = (
                sum(closes[i - 69:i - 19])
                / 50.0
            )

        slope_up = (
            ma50_prev is None
            or ma50 >= ma50_prev
        )

        slope_down = (
            ma50_prev is None
            or ma50 <= ma50_prev
        )

        if (
            close > ma50
            and ma50 > ma200
            and slope_up
        ):
            regime = "Bullish"
        elif (
            close < ma50
            and ma50 < ma200
            and slope_down
        ):
            regime = "Bearish"
        else:
            regime = "Sideways"

        regimes[row["date"]] = regime

    return regimes


def annotate_trades_with_regime(
    trades,
    regime_map,
):
    output = []

    for trade in trades:
        item = dict(trade)

        signal_date = (
            item.get("signal_date") or ""
        )

        item["market_regime"] = (
            regime_map.get(
                signal_date,
                "Unknown",
            )
        )

        output.append(item)

    return output


def get_current_market_regime(date_to):
    """
    Return IHSG regime for the latest trading day on/before date_to.
    This is descriptive context for the scanner, not a forecast.
    """
    data, status, cache_state = (
        get_yahoo_symbol_history(
            "^JKSE",
            date_to,
            900,
        )
    )

    if status != 200:
        return {
            "regime": "Unknown",
            "date": None,
            "symbol": "^JKSE",
            "name": "IHSG",
            "cache": cache_state,
            "error": data.get(
                "error",
                "Gagal mengambil regime IHSG",
            ),
        }

    rows = [
        x for x in (data.get("data") or [])
        if x.get("date")
        and x.get("close") is not None
    ]

    if not rows:
        return {
            "regime": "Unknown",
            "date": None,
            "symbol": "^JKSE",
            "name": "IHSG",
            "cache": cache_state,
            "error": "Data IHSG kosong",
        }

    regime_map = build_market_regime_map(
        rows
    )

    latest_row = rows[-1]
    latest_date = latest_row.get("date")
    regime = regime_map.get(
        latest_date,
        "Unknown",
    )

    return {
        "regime": regime,
        "date": latest_date,
        "symbol": "^JKSE",
        "name": "IHSG",
        "cache": cache_state,
        "method": (
            "Bullish: close > MA50 > MA200 "
            "dan MA50 tidak menurun; "
            "Bearish: close < MA50 < MA200 "
            "dan MA50 tidak naik; "
            "selain itu Sideways."
        ),
    }


@app.route("/api/market-regime-validation")
def market_regime_validation():
    raw_tickers = request.args.get(
        "tickers",
        "",
    )
    date_to = request.args.get("to")

    try:
        lookback_sessions = int(
            request.args.get(
                "sessions",
                "300",
            )
        )
        max_signals = int(
            request.args.get(
                "max_signals",
                "30",
            )
        )
        entry_wait = int(
            request.args.get(
                "entry_wait",
                "5",
            )
        )
        max_hold = int(
            request.args.get(
                "max_hold",
                "20",
            )
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": (
                "Parameter regime validation "
                "harus berupa angka"
            ),
        }), 400

    if not date_to:
        return jsonify({
            "success": False,
            "error": "Parameter to wajib diisi",
        }), 400

    try:
        datetime.strptime(
            date_to,
            "%Y-%m-%d",
        )
    except ValueError:
        return jsonify({
            "success": False,
            "error": (
                "Format tanggal harus YYYY-MM-DD"
            ),
        }), 400

    requested = []

    for part in (
        raw_tickers
        .replace(";", ",")
        .split(",")
    ):
        ticker = part.strip().upper()

        if (
            ticker
            and ticker not in requested
        ):
            requested.append(ticker)

    if not requested:
        requested = [
            "BBRI", "BBCA", "BMRI",
            "TLKM", "ASII", "UNTR",
            "PTBA", "ANTM", "SMDR",
            "PWON",
        ]

    requested = requested[:20]

    lookback_sessions = max(
        120,
        min(lookback_sessions, 600),
    )

    max_signals = max(
        10,
        min(max_signals, 50),
    )

    entry_wait = max(
        1,
        min(entry_wait, 10),
    )

    max_hold = max(
        3,
        min(max_hold, 60),
    )

    calendar_days = min(
        1800,
        max(
            800,
            int(lookback_sessions * 2.2)
            + 500,
        ),
    )

    benchmark_data, benchmark_status, benchmark_cache = (
        get_yahoo_symbol_history(
            "^JKSE",
            date_to,
            calendar_days,
        )
    )

    if benchmark_status != 200:
        return jsonify({
            "success": False,
            "error": benchmark_data.get(
                "error",
                "Gagal mengambil benchmark IHSG",
            ),
        }), benchmark_status

    benchmark_rows = (
        benchmark_data.get("data") or []
    )

    regime_map = build_market_regime_map(
        benchmark_rows
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=4
    ) as executor:
        futures = {
            executor.submit(
                collect_ab_replay_for_ticker,
                ticker,
                date_to,
                lookback_sessions,
                max_signals,
                entry_wait,
                max_hold,
            ): ticker
            for ticker in requested
        }

        for future in as_completed(futures):
            ticker = futures[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "success": False,
                    "ticker": ticker,
                    "error": str(e),
                }

            results.append(result)

    successful = [
        x for x in results
        if x.get("success")
    ]

    failed = [
        x for x in results
        if not x.get("success")
    ]

    combined = {
        "A": [],
        "B": [],
        "C": [],
    }

    for result in successful:
        for mode in combined:
            combined[mode].extend(
                result.get(
                    "models",
                    {},
                ).get(
                    mode,
                    [],
                )
            )

    model_output = {}

    for mode, trades in combined.items():
        annotated = annotate_trades_with_regime(
            trades,
            regime_map,
        )

        regime_summary = {}
        regime_setup_summary = {}

        for regime in [
            "Bullish",
            "Sideways",
            "Bearish",
            "Unknown",
        ]:
            subset = [
                x for x in annotated
                if x.get("market_regime")
                == regime
            ]

            if not subset:
                continue

            regime_summary[regime] = (
                summarize_historical_trades(
                    subset
                )
            )

            regime_setup_summary[regime] = {}

            for setup in [
                "Watch Pullback",
                "Momentum",
                "Early Watch",
            ]:
                setup_subset = [
                    x for x in subset
                    if x.get("setup") == setup
                ]

                if setup_subset:
                    regime_setup_summary[
                        regime
                    ][setup] = (
                        summarize_historical_trades(
                            setup_subset
                        )
                    )

        model_output[mode] = {
            "summary": (
                summarize_historical_trades(
                    annotated
                )
            ),
            "regime_summary": regime_summary,
            "regime_setup_summary": (
                regime_setup_summary
            ),
        }

    benchmark_regime_counts = {
        "Bullish": 0,
        "Sideways": 0,
        "Bearish": 0,
        "Unknown": 0,
    }

    for regime in regime_map.values():
        benchmark_regime_counts[regime] = (
            benchmark_regime_counts.get(
                regime,
                0,
            ) + 1
        )

    return jsonify({
        "success": True,
        "date_to": date_to,
        "benchmark": {
            "symbol": "^JKSE",
            "name": "IHSG",
            "cache": benchmark_cache,
            "method": (
                "Bullish: close > MA50 > MA200 "
                "dan MA50 tidak menurun; "
                "Bearish: close < MA50 < MA200 "
                "dan MA50 tidak naik; "
                "selain itu Sideways."
            ),
            "regime_days": (
                benchmark_regime_counts
            ),
        },
        "settings": {
            "lookback_sessions": (
                lookback_sessions
            ),
            "max_signals_per_ticker": (
                max_signals
            ),
            "entry_wait_sessions": (
                entry_wait
            ),
            "max_hold_sessions": max_hold,
            "ticker_count": len(requested),
        },
        "successful_tickers": (
            len(successful)
        ),
        "failed_tickers": len(failed),
        "failed": failed,
        "models": model_output,
        "assumptions": [
            "Regime ditentukan dari IHSG (^JKSE) pada tanggal signal.",
            "Regime hanya label historis untuk validasi, bukan prediksi pasar berikutnya.",
            "Signal dan entry A/B/C sama; perbedaan antar model hanya exit.",
            "Broker IndexAlpha tidak dipakai.",
            "Biaya transaksi dan slippage belum dimasukkan.",
            "Market Regime Validation tidak menggantikan forward Paper Trade.",
        ],
    })


@app.route("/api/paper-check")
def paper_check():
    ticker = request.args.get("ticker", "").upper().strip()

    try:
        since = int(float(request.args.get("since", "0")))
        entry = float(request.args.get("entry", "0"))
        tp1 = float(request.args.get("tp1", "0"))
        tp2 = float(request.args.get("tp2", "0"))
        cut_loss = float(request.args.get("cl", "0"))
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Parameter paper trade tidak valid",
        }), 400

    if (
        not ticker
        or since <= 0
        or entry <= 0
        or tp1 <= 0
        or tp2 <= 0
        or cut_loss <= 0
    ):
        return jsonify({
            "success": False,
            "error": "ticker, since, entry, tp1, tp2, cl wajib diisi",
        }), 400

    now_ts = int(time.time())
    age_seconds = max(0, now_ts - since)

    interval = "5m" if age_seconds <= 55 * 24 * 3600 else "1h"
    symbol = f"{ticker}.JK"

    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={
                "period1": max(0, since - 300),
                "period2": now_ts + 60,
                "interval": interval,
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
            return jsonify({
                "success": False,
                "error": f"Yahoo paper check HTTP {response.status_code}",
            }), response.status_code

        payload = response.json()
        chart = payload.get("chart") or {}
        results = chart.get("result") or []

        if not results:
            return jsonify({
                "success": False,
                "error": "Yahoo belum mengembalikan data harga",
            }), 404

        result = results[0]
        meta = result.get("meta") or {}
        timestamps = result.get("timestamp") or []
        quote_list = (
            (result.get("indicators") or {}).get("quote") or [{}]
        )
        quote = quote_list[0] if quote_list else {}

        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []

        candles = []

        for i, ts in enumerate(timestamps):
            if ts < since:
                continue

            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            close = closes[i] if i < len(closes) else None

            if close is None and high is None and low is None:
                continue

            close_value = float(
                close
                if close is not None
                else high
                if high is not None
                else low
            )

            high_value = float(
                high if high is not None else close_value
            )
            low_value = float(
                low if low is not None else close_value
            )

            candles.append({
                "ts": int(ts),
                "high": high_value,
                "low": low_value,
                "close": close_value,
            })

        market_price = meta.get("regularMarketPrice")

        if candles:
            last_price = candles[-1]["close"]
            high_since = max(x["high"] for x in candles)
            low_since = min(x["low"] for x in candles)
        else:
            last_price = float(market_price or 0)
            high_since = last_price
            low_since = last_price

        state = "WAIT_ENTRY"
        entered = False
        tp1_hit = False
        entry_time = None
        tp1_time = None
        exit_time = None
        exit_price = None

        for candle in candles:
            high = candle["high"]
            low = candle["low"]
            ts = candle["ts"]

            if not entered:
                if low <= entry:
                    entered = True
                    entry_time = ts
                    state = "OPEN"
                else:
                    continue

            # Conservative rule when targets and stop are inside same bar:
            # assume stop happens first to avoid optimistic paper results.
            if low <= cut_loss:
                state = "CL"
                exit_time = ts
                exit_price = cut_loss
                break

            if high >= tp2:
                tp1_hit = True
                if tp1_time is None:
                    tp1_time = ts
                state = "TP2"
                exit_time = ts
                exit_price = tp2
                break

            if high >= tp1 and not tp1_hit:
                tp1_hit = True
                tp1_time = ts
                state = "TP1_HIT"

        if not candles and last_price > 0:
            if last_price <= entry:
                entered = True
                state = "OPEN"

            if entered and last_price <= cut_loss:
                state = "CL"
                exit_price = cut_loss
            elif entered and last_price >= tp2:
                tp1_hit = True
                state = "TP2"
                exit_price = tp2
            elif entered and last_price >= tp1:
                tp1_hit = True
                state = "TP1_HIT"

        pnl_pct = None

        if entered and last_price > 0:
            pnl_pct = ((last_price / entry) - 1.0) * 100.0

        distance_entry_pct = (
            ((last_price / entry) - 1.0) * 100.0
            if last_price > 0 else None
        )

        distance_tp1_pct = (
            ((tp1 / last_price) - 1.0) * 100.0
            if last_price > 0 else None
        )

        distance_tp2_pct = (
            ((tp2 / last_price) - 1.0) * 100.0
            if last_price > 0 else None
        )

        distance_cl_pct = (
            ((cut_loss / last_price) - 1.0) * 100.0
            if last_price > 0 else None
        )

        if state == "WAIT_ENTRY":
            monitor_note = "Menunggu harga masuk ke area entry."
        elif state == "OPEN":
            if (
                distance_tp1_pct is not None
                and abs(distance_tp1_pct) <= 1.5
            ):
                monitor_note = "Harga mendekati TP1."
            elif (
                distance_cl_pct is not None
                and abs(distance_cl_pct) <= 1.5
            ):
                monitor_note = "Harga mendekati cut loss."
            else:
                monitor_note = "Posisi simulasi aktif."
        elif state == "TP1_HIT":
            monitor_note = "TP1 sudah tersentuh; memantau TP2 atau invalidasi."
        elif state == "TP2":
            monitor_note = "TP2 sudah tersentuh."
        else:
            monitor_note = "Cut loss sudah tersentuh."

        return jsonify({
            "success": True,
            "ticker": ticker,
            "source": "Yahoo Finance intraday",
            "interval": interval,
            "state": state,
            "entry_triggered": entered,
            "tp1_hit": tp1_hit,
            "last_price": round(last_price, 2),
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "high_since": round(high_since, 2),
            "low_since": round(low_since, 2),
            "distance_entry_pct": (
                round(distance_entry_pct, 2)
                if distance_entry_pct is not None else None
            ),
            "distance_tp1_pct": (
                round(distance_tp1_pct, 2)
                if distance_tp1_pct is not None else None
            ),
            "distance_tp2_pct": (
                round(distance_tp2_pct, 2)
                if distance_tp2_pct is not None else None
            ),
            "distance_cl_pct": (
                round(distance_cl_pct, 2)
                if distance_cl_pct is not None else None
            ),
            "entry_time": entry_time,
            "tp1_time": tp1_time,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "note": monitor_note,
            "checked_at": now_ts,
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Paper check error: {e}",
        }), 500


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

    warnings = []

    if not broker_rows:
        warnings.append(
            "Broker summary kosong/belum tersedia; Radar lanjut dengan Trend + Volume + Risk. "
            "Trade Signal ditahan sampai data broker tersedia."
        )

    ohlcv_data, ohlcv_status, ohlcv_cache = get_ohlcv(
        ticker,
        date_to,
    )

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
