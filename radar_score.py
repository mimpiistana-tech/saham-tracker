"""StockRadar Genius - Radar Score Engine V4."""

from dataclasses import dataclass, asdict
from math import isfinite
import re


COMPONENT_WEIGHTS = {
    "broker": 35,
    "trend": 20,
    "volume": 20,
    "catalyst": 15,
    "risk": 10,
}

_SUFFIX = {
    "K": 1_000.0,
    "M": 1_000_000.0,
    "B": 1_000_000_000.0,
    "T": 1_000_000_000_000.0,
}


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def parse_number(value):
    if value is None:
        return 0.0

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        number = float(value)
        return number if isfinite(number) else 0.0

    text = str(value).strip().upper().replace(" ", "")

    if not text:
        return 0.0

    suffix = text[-1] if text[-1:] in _SUFFIX else ""

    if suffix:
        text = text[:-1]

    text = re.sub(r"[^0-9,\.\-+]", "", text)

    if not text:
        return 0.0

    if "," in text and "." not in text:
        parts = text.split(",")

        if len(parts) == 2 and len(parts[1]) <= 2:
            text = ".".join(parts)
        else:
            text = "".join(parts)

    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        number = float(text)
    except ValueError:
        return 0.0

    if suffix:
        number *= _SUFFIX[suffix]

    return number if isfinite(number) else 0.0


@dataclass
class BrokerRow:
    broker: str
    buy: float = 0.0
    sell: float = 0.0
    net: float = 0.0

    @classmethod
    def from_mapping(cls, row):
        broker = str(
            row.get("broker")
            or row.get("code")
            or row.get("broker_code")
            or row.get("name")
            or "?"
        ).upper()

        buy = parse_number(
            row.get("buy")
            if row.get("buy") is not None
            else row.get("buy_value", row.get("bval"))
        )

        sell = parse_number(
            row.get("sell")
            if row.get("sell") is not None
            else row.get("sell_value", row.get("sval"))
        )

        raw_net = row.get("net")

        if raw_net is None:
            raw_net = row.get("net_value", row.get("nval"))

        if raw_net is None:
            net = buy - sell
        else:
            net = parse_number(raw_net)

        return cls(
            broker=broker,
            buy=buy,
            sell=sell,
            net=net,
        )


def broker_label(score):
    if score >= 75:
        return "Akumulasi Kuat"
    if score >= 60:
        return "Akumulasi"
    if score >= 45:
        return "Seimbang"
    if score >= 30:
        return "Distribusi"
    return "Distribusi Kuat"


def score_broker_flow(rows):
    normalized = []

    for row in rows:
        item = row if isinstance(row, BrokerRow) else BrokerRow.from_mapping(row)

        if item.net == 0 and item.buy == 0 and item.sell == 0:
            continue

        normalized.append(item)

    positive = [x for x in normalized if x.net > 0]
    negative = [x for x in normalized if x.net < 0]

    positive_sorted = sorted(positive, key=lambda x: x.net, reverse=True)
    negative_sorted = sorted(negative, key=lambda x: x.net)

    positive_net = sum(x.net for x in positive)
    negative_net_abs = sum(abs(x.net) for x in negative)
    total_net = positive_net - negative_net_abs
    active = len(positive) + len(negative)

    if positive_net > 0:
        top_buyer_share = (
            positive_sorted[0].net / positive_net
            if positive_sorted else 0.0
        )
        buyer_top3_share = (
            sum(x.net for x in positive_sorted[:3]) / positive_net
        )
    else:
        top_buyer_share = 0.0
        buyer_top3_share = 0.0

    if negative_net_abs > 0:
        top_seller_share = (
            abs(negative_sorted[0].net) / negative_net_abs
            if negative_sorted else 0.0
        )
        seller_top3_share = (
            sum(abs(x.net) for x in negative_sorted[:3])
            / negative_net_abs
        )
    else:
        top_seller_share = 0.0
        seller_top3_share = 0.0

    concentration_edge = buyer_top3_share - seller_top3_share

    breadth_edge = (
        (len(negative) - len(positive)) / active
        if active > 0 else 0.0
    )

    top1_edge = top_buyer_share - top_seller_share

    broker_pressure = (
        0.55 * concentration_edge
        + 0.30 * breadth_edge
        + 0.15 * top1_edge
    )

    broker_pressure = max(-1.0, min(1.0, broker_pressure))
    score = clamp(50.0 + (broker_pressure * 50.0))

    notes = []

    if score >= 70:
        notes.append(
            "Buyer broker terlihat lebih terkonsentrasi; indikasi akumulasi perlu dipantau."
        )
    elif score >= 58:
        notes.append("Tekanan broker condong ke sisi akumulasi.")
    elif score <= 30:
        notes.append(
            "Seller broker terlihat lebih terkonsentrasi; indikasi distribusi perlu diwaspadai."
        )
    elif score <= 42:
        notes.append("Tekanan broker condong ke sisi distribusi.")
    else:
        notes.append("Struktur broker masih relatif seimbang.")

    if active < 10:
        notes.append(
            "Broker aktif masih sedikit; keyakinan sinyal lebih rendah."
        )

    if buyer_top3_share >= 0.50:
        notes.append("Top 3 buyer memegang porsi besar dari total net buy.")

    if seller_top3_share >= 0.50:
        notes.append("Top 3 seller memegang porsi besar dari total net sell.")

    return {
        "score": round(score, 1),
        "label": broker_label(score),
        "metrics": {
            "total_net": total_net,
            "positive_net": positive_net,
            "negative_net_abs": negative_net_abs,
            "imbalance": round(broker_pressure, 4),
            "breadth": round(breadth_edge, 4),
            "buyers": len(positive),
            "sellers": len(negative),
            "active_brokers": active,
            "top_buyer_share": round(top_buyer_share, 4),
            "top_seller_share": round(top_seller_share, 4),
            "buyer_top3_share": round(buyer_top3_share, 4),
            "seller_top3_share": round(seller_top3_share, 4),
        },
        "top_buyers": [asdict(x) for x in positive_sorted[:5]],
        "top_sellers": [asdict(x) for x in negative_sorted[:5]],
        "notes": notes,
    }


def _clean_ohlcv_rows(rows):
    cleaned = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        close = parse_number(row.get("close"))
        volume = parse_number(row.get("volume"))

        if close <= 0:
            continue

        cleaned.append({
            "date": str(row.get("date") or ""),
            "open": parse_number(row.get("open")),
            "high": parse_number(row.get("high")),
            "low": parse_number(row.get("low")),
            "close": close,
            "volume": max(0.0, volume),
        })

    cleaned.sort(key=lambda x: x["date"])
    return cleaned


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def trend_label(score):
    if score >= 75:
        return "Uptrend Kuat"
    if score >= 60:
        return "Uptrend"
    if score >= 45:
        return "Netral"
    if score >= 30:
        return "Downtrend"
    return "Downtrend Kuat"


def score_trend_ohlcv(rows):
    data = _clean_ohlcv_rows(rows)
    closes = [x["close"] for x in data]
    n = len(closes)

    if n < 20:
        return {
            "available": False,
            "score": None,
            "label": "Data trend belum cukup",
            "metrics": {"bars": n},
            "notes": ["Butuh minimal 20 hari bursa untuk membaca trend."],
        }

    latest = closes[-1]
    ma20 = _mean(closes[-20:])
    ma50 = _mean(closes[-50:]) if n >= 50 else None

    momentum20 = (
        latest / closes[-20] - 1.0
        if closes[-20] else 0.0
    )

    momentum5 = (
        latest / closes[-5] - 1.0
        if n >= 5 and closes[-5] else 0.0
    )

    score = 50.0
    score += 8.0 if latest >= ma20 else -8.0
    score += max(-15.0, min(15.0, (momentum20 / 0.15) * 15.0))
    score += max(-7.0, min(7.0, (momentum5 / 0.07) * 7.0))

    if ma50 is not None:
        score += 8.0 if latest >= ma50 else -8.0
        score += 10.0 if ma20 >= ma50 else -10.0

    score = clamp(score)

    notes = []

    if latest > ma20:
        notes.append("Harga berada di atas MA20.")
    else:
        notes.append("Harga berada di bawah MA20.")

    if ma50 is not None:
        if ma20 > ma50:
            notes.append("MA20 berada di atas MA50; struktur menengah positif.")
        else:
            notes.append("MA20 berada di bawah MA50; struktur menengah masih lemah.")
    else:
        notes.append("MA50 belum tersedia penuh; trend menengah memakai data terbatas.")

    if momentum20 > 0.05:
        notes.append("Momentum 20 hari positif.")
    elif momentum20 < -0.05:
        notes.append("Momentum 20 hari negatif.")

    return {
        "available": True,
        "score": round(score, 1),
        "label": trend_label(score),
        "metrics": {
            "bars": n,
            "latest_close": latest,
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2) if ma50 is not None else None,
            "momentum_20d": round(momentum20, 4),
            "momentum_5d": round(momentum5, 4),
        },
        "notes": notes,
    }


def volume_label(score):
    if score >= 75:
        return "Konfirmasi Kuat"
    if score >= 60:
        return "Mendukung"
    if score >= 45:
        return "Normal"
    if score >= 30:
        return "Lemah"
    return "Distribusi Volume"


def score_volume_ohlcv(rows):
    data = _clean_ohlcv_rows(rows)
    n = len(data)

    if n < 10:
        return {
            "available": False,
            "score": None,
            "label": "Data volume belum cukup",
            "metrics": {"bars": n},
            "notes": ["Butuh minimal 10 hari bursa untuk membaca volume."],
        }

    latest = data[-1]
    previous = data[-2]

    baseline_rows = data[-21:-1] if n >= 21 else data[:-1]
    avg_volume = _mean(x["volume"] for x in baseline_rows)

    volume_ratio = (
        latest["volume"] / avg_volume
        if avg_volume > 0 else 1.0
    )

    price_change = (
        latest["close"] / previous["close"] - 1.0
        if previous["close"] else 0.0
    )

    five_rows = data[-5:]
    avg5 = _mean(x["volume"] for x in five_rows)

    score = 50.0

    if volume_ratio >= 1.0:
        volume_impact = min(30.0, (volume_ratio - 1.0) * 30.0)

        if price_change > 0.002:
            score += volume_impact
        elif price_change < -0.002:
            score -= volume_impact
    else:
        score -= min(8.0, (1.0 - volume_ratio) * 10.0)

    five_price_change = (
        five_rows[-1]["close"] / five_rows[0]["close"] - 1.0
        if len(five_rows) >= 2 and five_rows[0]["close"] else 0.0
    )

    if avg_volume > 0 and avg5 > avg_volume * 1.15:
        if five_price_change > 0:
            score += 8.0
        elif five_price_change < 0:
            score -= 8.0

    score = clamp(score)

    notes = []

    if volume_ratio >= 1.5 and price_change > 0:
        notes.append("Volume melonjak saat harga menguat; konfirmasi positif.")
    elif volume_ratio >= 1.5 and price_change < 0:
        notes.append("Volume melonjak saat harga melemah; waspadai distribusi.")
    elif volume_ratio >= 1.1:
        notes.append("Volume di atas rata-rata 20 hari.")
    elif volume_ratio < 0.8:
        notes.append("Volume di bawah rata-rata; dorongan harga belum kuat.")
    else:
        notes.append("Volume berada di sekitar rata-rata.")

    return {
        "available": True,
        "score": round(score, 1),
        "label": volume_label(score),
        "metrics": {
            "bars": n,
            "latest_volume": latest["volume"],
            "avg_volume_20": round(avg_volume, 2),
            "volume_ratio": round(volume_ratio, 4),
            "price_change_1d": round(price_change, 4),
            "avg_volume_5": round(avg5, 2),
            "price_change_5d": round(five_price_change, 4),
        },
        "notes": notes,
    }


def risk_label(score):
    if score >= 75:
        return "Risiko Terkendali"
    if score >= 60:
        return "Cukup Terkendali"
    if score >= 45:
        return "Sedang"
    if score >= 30:
        return "Tinggi"
    return "Sangat Tinggi"


def score_risk_ohlcv(rows):
    """
    Skor risk teknikal: makin tinggi = risiko harga makin terkendali.

    Dibaca dari:
    - ATR14 sebagai persentase harga
    - drawdown dari high 20 hari
    - range harian terbaru
    - perubahan harga harian ekstrem
    """
    data = _clean_ohlcv_rows(rows)
    n = len(data)

    if n < 20:
        return {
            "available": False,
            "score": None,
            "label": "Data risk belum cukup",
            "metrics": {"bars": n},
            "notes": ["Butuh minimal 20 hari bursa untuk membaca risiko teknikal."],
        }

    latest = data[-1]
    latest_close = latest["close"]

    true_ranges = []

    for i in range(1, n):
        current = data[i]
        prev_close = data[i - 1]["close"]

        high = current["high"] or current["close"]
        low = current["low"] or current["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        true_ranges.append(max(0.0, tr))

    atr14 = _mean(true_ranges[-14:])
    atr_pct = atr14 / latest_close if latest_close > 0 else 0.0

    recent20 = data[-20:]
    high20 = max(
        (x["high"] or x["close"])
        for x in recent20
    )

    drawdown20 = (
        latest_close / high20 - 1.0
        if high20 > 0 else 0.0
    )

    latest_high = latest["high"] or latest_close
    latest_low = latest["low"] or latest_close

    day_range_pct = (
        (latest_high - latest_low) / latest_close
        if latest_close > 0 else 0.0
    )

    prev_close = data[-2]["close"]
    change_1d = (
        latest_close / prev_close - 1.0
        if prev_close > 0 else 0.0
    )

    score = 80.0

    # ATR: <=2% relatif tenang, >5% mulai agresif.
    if atr_pct > 0.02:
        score -= min(30.0, ((atr_pct - 0.02) / 0.04) * 30.0)

    # Drawdown dari puncak 20 hari.
    if drawdown20 < -0.03:
        score -= min(25.0, ((abs(drawdown20) - 0.03) / 0.17) * 25.0)

    # Range harian besar menambah risiko eksekusi.
    if day_range_pct > 0.03:
        score -= min(15.0, ((day_range_pct - 0.03) / 0.07) * 15.0)

    # Gerak harian ekstrem diberi penalti.
    if abs(change_1d) > 0.04:
        score -= min(10.0, ((abs(change_1d) - 0.04) / 0.10) * 10.0)

    score = clamp(score)

    notes = []

    if atr_pct <= 0.025:
        notes.append("ATR14 relatif rendah; volatilitas harian cukup terkendali.")
    elif atr_pct <= 0.045:
        notes.append("ATR14 berada di level menengah.")
    else:
        notes.append("ATR14 tinggi; pergerakan harga lebih agresif.")

    if drawdown20 >= -0.05:
        notes.append("Harga masih dekat area high 20 hari.")
    elif drawdown20 >= -0.12:
        notes.append("Harga mengalami drawdown menengah dari high 20 hari.")
    else:
        notes.append("Drawdown dari high 20 hari cukup dalam.")

    if day_range_pct >= 0.06:
        notes.append("Range harian lebar; risiko slippage dan false break meningkat.")

    return {
        "available": True,
        "score": round(score, 1),
        "label": risk_label(score),
        "metrics": {
            "bars": n,
            "atr14": round(atr14, 2),
            "atr_pct": round(atr_pct, 4),
            "high20": round(high20, 2),
            "drawdown_20d": round(drawdown20, 4),
            "day_range_pct": round(day_range_pct, 4),
            "price_change_1d": round(change_1d, 4),
        },
        "notes": notes,
    }


def build_trade_signal(broker, trend, volume, risk, rows):
    """
    Sinyal swing harian berbasis konfirmasi, bukan auto-trading.
    BUY hanya muncul bila beberapa komponen sepakat.
    """
    data = _clean_ohlcv_rows(rows)

    if len(data) < 20:
        return {
            "action": "WAIT",
            "label": "Tunggu Data",
            "confidence": 0,
            "reason": "Data harga belum cukup.",
            "levels": {},
        }

    latest = data[-1]
    close = latest["close"]
    recent20 = data[-20:]

    support20 = min(
        (x["low"] or x["close"])
        for x in recent20
    )
    resistance20 = max(
        (x["high"] or x["close"])
        for x in recent20
    )

    trend_metrics = trend.get("metrics", {})
    risk_metrics = risk.get("metrics", {})

    ma20 = parse_number(trend_metrics.get("ma20"))
    atr14 = parse_number(risk_metrics.get("atr14"))

    if atr14 <= 0:
        atr14 = max(close * 0.02, 1.0)

    broker_score = parse_number(broker.get("score"))
    trend_score = parse_number(trend.get("score"))
    volume_score = parse_number(volume.get("score"))
    risk_score = parse_number(risk.get("score"))

    composite = (
        0.35 * broker_score
        + 0.25 * trend_score
        + 0.20 * volume_score
        + 0.20 * risk_score
    )

    above_ma20 = ma20 > 0 and close >= ma20
    near_support = (
        support20 > 0
        and close <= support20 + (1.2 * atr14)
    )

    breakout_ready = (
        close >= resistance20 - (0.5 * atr14)
        and volume_score >= 60
        and trend_score >= 60
    )

    distribution_risk = (
        broker_score <= 42
        or volume_score <= 35
        or trend_score <= 35
    )

    action = "WAIT"
    label = "Tunggu Konfirmasi"
    reason = (
        "Belum ada konfirmasi cukup kuat untuk entry baru."
    )

    if (
        trend_score >= 60
        and broker_score >= 58
        and risk_score >= 55
        and above_ma20
    ):
        if near_support:
            action = "BUY"
            label = "Buy on Pullback"
            reason = (
                "Trend, broker, dan risk mendukung; harga berada dekat area support."
            )
        elif breakout_ready:
            action = "BUY"
            label = "Buy on Breakout"
            reason = (
                "Trend kuat dan volume mengonfirmasi area breakout."
            )
        else:
            action = "WAIT"
            label = "Tunggu Pullback"
            reason = (
                "Struktur cukup positif, tetapi harga belum berada di entry yang efisien."
            )

    if distribution_risk and close < ma20:
        action = "SELL"
        label = "Reduce / Exit"
        reason = (
            "Trend melemah atau tekanan distribusi meningkat dan harga berada di bawah MA20."
        )

    invalidation = max(
        0.0,
        min(support20, ma20 if ma20 > 0 else support20)
        - (0.5 * atr14)
    )

    pullback_low = max(
        invalidation,
        (ma20 if ma20 > 0 else close) - (0.5 * atr14)
    )
    pullback_high = (
        ma20 + (0.35 * atr14)
        if ma20 > 0 else close
    )
    pullback_high = max(pullback_high, pullback_low)

    breakout_trigger = resistance20 + (0.15 * atr14)

    # Satu mode entry harus memakai satu basis risk/reward yang konsisten.
    # Sebelumnya TP dihitung dari close terakhir sehingga pada saham yang
    # berada di bawah MA20, TP1 bisa lebih rendah daripada area beli.
    entry_mode = (
        "BREAKOUT"
        if action == "BUY" and label == "Buy on Breakout"
        else "PULLBACK"
    )

    if entry_mode == "BREAKOUT":
        entry_low = breakout_trigger
        entry_high = breakout_trigger + (0.35 * atr14)
        entry_reference = breakout_trigger
        trade_invalidation = min(
            invalidation,
            max(0.0, breakout_trigger - (1.25 * atr14)),
        )
    else:
        entry_low = pullback_low
        entry_high = pullback_high
        entry_reference = (entry_low + entry_high) / 2
        trade_invalidation = invalidation

    # TP selalu berada di atas seluruh area entry.
    tp1 = max(
        entry_high + (0.50 * atr14),
        entry_reference + (1.50 * atr14),
    )
    tp2 = max(
        tp1 + (0.75 * atr14),
        entry_reference + (3.00 * atr14),
    )

    return {
        "action": action,
        "label": label,
        "confidence": round(clamp(composite), 1),
        "reason": reason,
        "entry_mode": entry_mode,
        "levels": {
            "close": round(close, 2),
            "support20": round(support20, 2),
            "resistance20": round(resistance20, 2),
            "buy_pullback_low": round(pullback_low, 2),
            "buy_pullback_high": round(pullback_high, 2),
            "buy_breakout_above": round(breakout_trigger, 2),
            "entry_mode": entry_mode,
            "entry_low": round(entry_low, 2),
            "entry_high": round(entry_high, 2),
            "entry_reference": round(entry_reference, 2),
            "invalidation": round(trade_invalidation, 2),
            "tp1_reference": round(tp1, 2),
            "tp2_reference": round(tp2, 2),
        },
    }


def overall_label(score, coverage):
    prefix = ""

    if coverage < 100:
        prefix = "Sementara - "

    if score >= 80:
        return prefix + "Sangat Menarik Dipantau"
    if score >= 65:
        return prefix + "Menarik Dipantau"
    if score >= 50:
        return prefix + "Netral / Tunggu Konfirmasi"
    if score >= 35:
        return prefix + "Lemah"
    return prefix + "Risiko Tinggi"


def build_radar_score(components):
    available = {}
    used_weight = 0.0
    weighted_sum = 0.0

    for name, weight in COMPONENT_WEIGHTS.items():
        value = components.get(name)

        if value is None:
            continue

        score = clamp(parse_number(value))
        available[name] = round(score, 1)
        used_weight += weight
        weighted_sum += score * weight

    if used_weight == 0:
        overall = 50.0
    else:
        overall = weighted_sum / used_weight

    coverage = (
        used_weight
        / sum(COMPONENT_WEIGHTS.values())
        * 100
    )

    return {
        "radar_score": round(overall, 1),
        "coverage": round(coverage, 1),
        "label": overall_label(overall, coverage),
        "components": available,
        "missing_components": [
            x for x in COMPONENT_WEIGHTS if x not in available
        ],
        "weights": COMPONENT_WEIGHTS.copy(),
        "is_full_score": coverage >= 100,
    }


def _mark_broker_unavailable(broker):
    broker = dict(broker)
    broker["available"] = False
    broker["score"] = None
    broker["label"] = "Menunggu data broker"
    broker["notes"] = [
        "Broker summary kosong/belum tersedia; komponen broker tidak dihitung ke Radar Score."
    ]
    return broker


def score_from_broker_rows(rows):
    broker = score_broker_flow(rows)
    broker_available = bool(
        broker.get("metrics", {}).get("active_brokers")
    )

    if broker_available:
        broker["available"] = True
        radar = build_radar_score({
            "broker": broker["score"]
        })
    else:
        broker = _mark_broker_unavailable(broker)
        radar = build_radar_score({})

    return {
        "radar": radar,
        "broker": broker,
    }


def score_from_market_data(broker_rows, ohlcv_rows):
    broker = score_broker_flow(broker_rows)
    broker_available = bool(
        broker.get("metrics", {}).get("active_brokers")
    )

    if broker_available:
        broker["available"] = True
    else:
        broker = _mark_broker_unavailable(broker)

    trend = score_trend_ohlcv(ohlcv_rows)
    volume = score_volume_ohlcv(ohlcv_rows)
    risk = score_risk_ohlcv(ohlcv_rows)

    components = {}

    if broker_available:
        components["broker"] = broker["score"]

    if trend.get("available"):
        components["trend"] = trend["score"]

    if volume.get("available"):
        components["volume"] = volume["score"]

    if risk.get("available"):
        components["risk"] = risk["score"]

    radar = build_radar_score(components)

    signal_broker = broker

    if not broker_available:
        signal_broker = {
            "score": 50,
            "metrics": {
                "active_brokers": 0,
            },
        }

    signal = build_trade_signal(
        signal_broker,
        trend,
        volume,
        risk,
        ohlcv_rows,
    )

    if not broker_available:
        signal["action"] = "WAIT"
        signal["label"] = "Tunggu Broker"
        signal["confidence"] = (
            round(radar["radar_score"], 1)
            if radar.get("coverage", 0) > 0
            else 0
        )
        signal["reason"] = (
            "Data broker belum tersedia; level teknikal tetap dihitung, "
            "tetapi entry ditahan sampai broker summary tersedia."
        )

    return {
        "radar": radar,
        "broker": broker,
        "trend": trend,
        "volume": volume,
        "risk": risk,
        "signal": signal,
    }
