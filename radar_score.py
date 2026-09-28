"""StockRadar Genius - Radar Score Engine V1."""

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
            net=net
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

        if isinstance(row, BrokerRow):
            item = row
        else:
            item = BrokerRow.from_mapping(row)

        if item.net == 0 and item.buy == 0 and item.sell == 0:
            continue

        normalized.append(item)

    positive = [x for x in normalized if x.net > 0]
    negative = [x for x in normalized if x.net < 0]

    positive_net = sum(x.net for x in positive)
    negative_net_abs = sum(abs(x.net) for x in negative)

    gross_net_flow = positive_net + negative_net_abs
    total_net = positive_net - negative_net_abs

    active = len(positive) + len(negative)

    if gross_net_flow <= 0 or active == 0:

        imbalance = 0.0
        breadth = 0.0
        score = 50.0

    else:

        imbalance = total_net / gross_net_flow

        breadth = (
            len(positive) - len(negative)
        ) / active

        imbalance_score = 50 + (50 * imbalance)
        breadth_score = 50 + (50 * breadth)

        score = clamp(
            0.80 * imbalance_score
            + 0.20 * breadth_score
        )

    positive_sorted = sorted(
        positive,
        key=lambda x: x.net,
        reverse=True
    )

    negative_sorted = sorted(
        negative,
        key=lambda x: x.net
    )

    if positive_net > 0 and positive_sorted:

        top_buyer_share = (
            positive_sorted[0].net
            / positive_net
        )

    else:
        top_buyer_share = 0.0

    notes = []

    if score >= 60:
        notes.append(
            "Net flow broker cenderung akumulasi."
        )

    elif score < 45:
        notes.append(
            "Net flow broker cenderung distribusi."
        )

    else:
        notes.append(
            "Net flow broker relatif seimbang."
        )

    if active < 3:
        notes.append(
            "Broker aktif masih sedikit."
        )

    if top_buyer_share >= 0.70:
        notes.append(
            "Net buy terkonsentrasi pada satu broker."
        )

def score_broker_flow(rows: Iterable[Mapping[str, Any] | BrokerRow]) -> dict[str, Any]:
    """
    StockRadar Genius Broker Engine V2.

    Tidak memakai total net seluruh broker sebagai sinyal utama,
    karena total net market secara alami mendekati nol.

    V2 membaca:
    - konsentrasi Top 3 buyer vs Top 3 seller
    - jumlah broker buyer vs seller
    - dominasi broker terbesar
    """

    normalized: list[BrokerRow] = []

    for row in rows:
        item = (
            row
            if isinstance(row, BrokerRow)
            else BrokerRow.from_mapping(row)
        )

        if item.net == 0 and item.buy == 0 and item.sell == 0:
            continue

        normalized.append(item)

    positive = [x for x in normalized if x.net > 0]
    negative = [x for x in normalized if x.net < 0]

    positive_sorted = sorted(
        positive,
        key=lambda x: x.net,
        reverse=True
    )

    negative_sorted = sorted(
        negative,
        key=lambda x: x.net
    )

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
            sum(x.net for x in positive_sorted[:3])
            / positive_net
        )
    else:
        top_buyer_share = 0.0
        buyer_top3_share = 0.0

    if negative_net_abs > 0:
        top_seller_share = (
            abs(negative_sorted[0].net)
            / negative_net_abs
            if negative_sorted else 0.0
        )

        seller_top3_share = (
            sum(abs(x.net) for x in negative_sorted[:3])
            / negative_net_abs
        )
    else:
        top_seller_share = 0.0
        seller_top3_share = 0.0

    # Positif = buyer lebih terkonsentrasi
    concentration_edge = (
        buyer_top3_share - seller_top3_share
    )

    # Positif = sedikit buyer menyerap banyak seller
    breadth_edge = (
        (len(negative) - len(positive)) / active
        if active > 0 else 0.0
    )

    # Positif = broker buyer terbesar lebih dominan
    top1_edge = (
        top_buyer_share - top_seller_share
    )

    broker_pressure = (
        0.55 * concentration_edge
        + 0.30 * breadth_edge
        + 0.15 * top1_edge
    )

    broker_pressure = max(
        -1.0,
        min(1.0, broker_pressure)
    )

    score = clamp(
        50.0 + (broker_pressure * 50.0)
    )

    notes: list[str] = []

    if score >= 70:
        notes.append(
            "Buyer broker terlihat lebih terkonsentrasi; indikasi akumulasi perlu dipantau."
        )
    elif score >= 58:
        notes.append(
            "Tekanan broker condong ke sisi akumulasi."
        )
    elif score <= 30:
        notes.append(
            "Seller broker terlihat lebih terkonsentrasi; indikasi distribusi perlu diwaspadai."
        )
    elif score <= 42:
        notes.append(
            "Tekanan broker condong ke sisi distribusi."
        )
    else:
        notes.append(
            "Struktur broker masih relatif seimbang."
        )

    if active < 10:
        notes.append(
            "Broker aktif masih sedikit; keyakinan sinyal lebih rendah."
        )

    if buyer_top3_share >= 0.50:
        notes.append(
            "Top 3 buyer memegang porsi besar dari total net buy."
        )

    if seller_top3_share >= 0.50:
        notes.append(
            "Top 3 seller memegang porsi besar dari total net sell."
        )

    return {
        "score": round(score, 1),
        "label": _broker_label(score),

        "metrics": {
            "total_net": total_net,
            "positive_net": positive_net,
            "negative_net_abs": negative_net_abs,

            "imbalance": round(
                broker_pressure, 4
            ),

            "breadth": round(
                breadth_edge, 4
            ),

            "buyers": len(positive),
            "sellers": len(negative),
            "active_brokers": active,

            "top_buyer_share": round(
                top_buyer_share, 4
            ),

            "top_seller_share": round(
                top_seller_share, 4
            ),

            "buyer_top3_share": round(
                buyer_top3_share, 4
            ),

            "seller_top3_share": round(
                seller_top3_share, 4
            ),
        },

        "top_buyers": [
            asdict(x)
            for x in positive_sorted[:5]
        ],

        "top_sellers": [
            asdict(x)
            for x in negative_sorted[:5]
        ],

        "notes": notes,
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

        "label": overall_label(
            overall,
            coverage
        ),

        "components": available,

        "missing_components": [
            x
            for x in COMPONENT_WEIGHTS
            if x not in available
        ],

        "weights": COMPONENT_WEIGHTS.copy(),

        "is_full_score": coverage >= 100,
    }


def score_from_broker_rows(rows):

    broker = score_broker_flow(rows)

    radar = build_radar_score({
        "broker": broker["score"]
    })

    return {
        "radar": radar,
        "broker": broker
  }
