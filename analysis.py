import requests
import logging
import time

BINANCE_URL = "https://api.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/9.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# BINANCE
# =========================================================

def api_get(path, params=None, timeout=10):
    try:
        r = SESSION.get(
            BINANCE_URL + path,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            logger.error(
                "Binance HTTP %s: %s",
                r.status_code,
                r.text[:300]
            )
            return None

        return r.json()

    except Exception as e:
        logger.error("Binance API error: %s", e)
        return None


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(symbol):
    if not symbol:
        return None

    symbol = str(symbol).upper().strip()
    symbol = symbol.replace("/", "")
    symbol = symbol.replace("-", "")
    symbol = symbol.replace(" ", "")

    if symbol.endswith("USDT"):
        return symbol

    return symbol + "USDT"


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    value = sum(values[:period]) / period

    for price in values[period:]:
        value = price * k + value * (1 - k)

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))

    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period

    if al == 0:
        return 100.0

    return 100 - (100 / (1 + ag / al))


def fmt(x):
    if x is None:
        return "-"

    if x >= 1000:
        return f"{x:,.2f}"

    if x >= 1:
        return f"{x:.4f}"

    if x >= 0.1:
        return f"{x:.5f}"

    if x >= 0.01:
        return f"{x:.6f}"

    return f"{x:.8f}"


def pct(a, b):
    if not a:
        return 0

    return ((b - a) / a) * 100


# =========================================================
# MARKET
# =========================================================

def get_usdt_symbols():
    data = api_get("/api/v3/exchangeInfo")

    if not data:
        return []

    result = []

    for item in data.get("symbols", []):

        symbol = item.get("symbol")

        if not symbol:
            continue

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is False:
            continue

        # leveraged tokens
        if any(x in symbol for x in (
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        )):
            continue

        result.append(symbol)

    return sorted(set(result))


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval="15m", limit=120):
    symbol = normalize_symbol(symbol)

    return api_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def parse_klines(k):
    try:
        return {
            "open": [float(x[1]) for x in k],
            "high": [float(x[2]) for x in k],
            "low": [float(x[3]) for x in k],
            "close": [float(x[4]) for x in k],
            "volume": [float(x[5]) for x in k]
        }
    except Exception:
        return None


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def find_levels(highs, lows, price):

    resistance_candidates = []
    support_candidates = []

    for i in range(2, len(highs) - 2):

        # local high
        if (
            highs[i] >= highs[i - 1]
            and highs[i] >= highs[i - 2]
            and highs[i] >= highs[i + 1]
            and highs[i] >= highs[i + 2]
        ):
            resistance_candidates.append(highs[i])

        # local low
        if (
            lows[i] <= lows[i - 1]
            and lows[i] <= lows[i - 2]
            and lows[i] <= lows[i + 1]
            and lows[i] <= lows[i + 2]
        ):
            support_candidates.append(lows[i])

    supports = sorted(
        [x for x in support_candidates if x < price],
        reverse=True
    )

    resistances = sorted(
        [x for x in resistance_candidates if x > price]
    )

    return supports[:3], resistances[:3]


# =========================================================
# TIMEFRAME
# =========================================================

def analyze_timeframe(symbol, interval, limit=120):

    k = get_klines(symbol, interval, limit)

    if not k or len(k) < 60:
        return None

    d = parse_klines(k)

    if not d:
        return None

    closes = d["close"]
    highs = d["high"]
    lows = d["low"]
    volumes = d["volume"]

    price = closes[-1]

    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rr = rsi(closes)

    if None in (e9, e20, e50, rr):
        return None

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    avg_volume = sum(volumes[-21:-1]) / 20

    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume
        else 0
    )

    old_volume = sum(volumes[-20:-10]) / 10
    new_volume = sum(volumes[-10:]) / 10

    volume_improving = (
        new_volume > old_volume * 1.08
        if old_volume
        else False
    )

    # -----------------------------------------------------
    # Buy pressure
    # -----------------------------------------------------

    buy = 0
    sell = 0

    for candle in k[-20:]:

        h = float(candle[2])
        l = float(candle[3])
        c = float(candle[4])
        v = float(candle[5])

        rng = max(h - l, 1e-12)

        buy += v * max(c - l, 0) / rng
        sell += v * max(h - c, 0) / rng

    total = buy + sell

    pressure = (
        buy / total * 100
        if total
        else 50
    )

    # -----------------------------------------------------
    # Trend
    # -----------------------------------------------------

    if e9 > e20 > e50:
        trend = "BULLISH_STRONG"
    elif e9 > e20:
        trend = "BULLISH"
    elif e9 < e20 < e50:
        trend = "BEARISH_STRONG"
    elif e9 < e20:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    # -----------------------------------------------------
    # Previous dump
    # -----------------------------------------------------

    previous_high = max(closes[-60:-10])
    recent_low = min(closes[-20:])

    previous_dump = pct(
        previous_high,
        recent_low
    )

    # -----------------------------------------------------
    # Consolidation
    # -----------------------------------------------------

    recent_high = max(highs[-15:])
    recent_low_15 = min(lows[-15:])

    consolidation_range = pct(
        recent_low_15,
        recent_high
    )

    consolidation = (
        consolidation_range <= 12
    )

    # -----------------------------------------------------
    # Recovery
    # -----------------------------------------------------

    recovery = pct(
        recent_low,
        price
    )

    # -----------------------------------------------------
    # Short momentum
    # -----------------------------------------------------

    change_5 = pct(
        closes[-6],
        price
    )

    # -----------------------------------------------------
    # Levels
    # -----------------------------------------------------

    supports, resistances = find_levels(
        highs,
        lows,
        price
    )

    support = (
        supports[0]
        if supports
        else min(lows[-30:])
    )

    resistance = (
        resistances[0]
        if resistances
        else max(highs[-30:])
    )

    distance_support = pct(
        support,
        price
    )

    distance_resistance = pct(
        price,
        resistance
    )

    return {
        "price": price,
        "ema9": e9,
        "ema20": e20,
        "ema50": e50,
        "rsi": rr,
        "volume_ratio": volume_ratio,
        "volume_improving": volume_improving,
        "pressure": pressure,
        "trend": trend,
        "previous_dump": previous_dump,
        "consolidation": consolidation,
        "recovery": recovery,
        "change_5": change_5,
        "supports": supports,
        "resistances": resistances,
        "support": support,
        "resistance": resistance,
        "distance_support": distance_support,
        "distance_resistance": distance_resistance
    }


# =========================================================
# DEEP ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    tfs = {}

    for interval in (
        "15m",
        "1h",
        "4h",
        "1d"
    ):

        result = analyze_timeframe(
            symbol,
            interval,
            120
        )

        if not result:
            return None

        tfs[interval] = result

        # small delay to be gentle on Binance
        time.sleep(0.03)

    tf15 = tfs["15m"]
    tf1h = tfs["1h"]
    tf4h = tfs["4h"]
    tf1d = tfs["1d"]

    price = tf15["price"]

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # DAILY
    # =====================================================

    if tf1d["trend"] in (
        "BULLISH",
        "BULLISH_STRONG"
    ):
        long_score += 12
        long_reasons.append(
            "الاتجاه اليومي إيجابي"
        )

    elif tf1d["trend"] in (
        "BEARISH",
        "BEARISH_STRONG"
    ):
        short_score += 12
        short_reasons.append(
            "الاتجاه اليومي سلبي"
        )

    # =====================================================
    # 4H
    # =====================================================

    if tf4h["trend"] in (
        "BULLISH",
        "BULLISH_STRONG"
    ):
        long_score += 15
        long_reasons.append(
            "تأكيد الاتجاه على 4H"
        )

    elif tf4h["trend"] in (
        "BEARISH",
        "BEARISH_STRONG"
    ):
        short_score += 15
        short_reasons.append(
            "تأكيد الاتجاه الهابط على 4H"
        )

    # =====================================================
    # 1H
    # =====================================================

    if tf1h["trend"] in (
        "BULLISH",
        "BULLISH_STRONG"
    ):
        long_score += 10
        long_reasons.append(
            "تحسن 1H"
        )

    elif tf1h["trend"] in (
        "BEARISH",
        "BEARISH_STRONG"
    ):
        short_score += 10
        short_reasons.append(
            "ضعف 1H"
        )

    # =====================================================
    # 15M
    # =====================================================

    if tf15["trend"] in (
        "BULLISH",
        "BULLISH_STRONG"
    ):
        long_score += 8
        long_reasons.append(
            "إشارة 15m إيجابية"
        )

    elif tf15["trend"] in (
        "BEARISH",
        "BEARISH_STRONG"
    ):
        short_score += 8
        short_reasons.append(
            "إشارة 15m سلبية"
        )

    # =====================================================
    # RSI
    # =====================================================

    if 45 <= tf15["rsi"] <= 68:
        long_score += 7
        long_reasons.append(
            "RSI في منطقة مناسبة للصعود"
        )

    if 32 <= tf15["rsi"] <= 50:
        short_score += 7
        short_reasons.append(
            "RSI يدعم احتمالية الهبوط"
        )

    # =====================================================
    # LIQUIDITY / PRESSURE
    # =====================================================

    if tf15["pressure"] >= 55:

        long_score += 10

        long_reasons.append(
            "ضغط شراء واضح"
        )

    elif tf15["pressure"] <= 45:

        short_score += 10

        short_reasons.append(
            "ضغط بيع واضح"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.15:

        if tf15["pressure"] >= 52:

            long_score += 6

            long_reasons.append(
                "دخول حجم مع المشترين"
            )

        elif tf15["pressure"] <= 48:

            short_score += 6

            short_reasons.append(
                "زيادة حجم مع البائعين"
            )

    if tf15["volume_improving"]:

        if tf15["pressure"] >= 52:

            long_score += 6

            long_reasons.append(
                "الحجم يتحسن تدريجياً"
            )

    # =====================================================
    # DUMP + ACCUMULATION
    # =====================================================

    accumulation = (
        tf1h["previous_dump"] <= -8
        and tf1h["consolidation"]
        and tf1h["volume_improving"]
        and tf1h["pressure"] >= 52
        and tf1h["recovery"] >= 2
    )

    if accumulation:

        long_score += 15

        long_reasons.append(
            "هبوط سابق + تجميع + تحسن السيولة"
        )

    # =====================================================
    # SUPPORT
    # =====================================================

    support = tf15["support"]

    resistance = tf15["resistance"]

    support_distance = (
        abs(price - support)
        / price * 100
    )

    resistance_distance = (
        abs(resistance - price)
        / price * 100
    )

    # Near support = possible bounce
    if support_distance <= 3:

        if tf15["pressure"] >= 52:

            long_score += 10

            long_reasons.append(
                "ارتداد محتمل من الدعم"
            )

    # Break support
    if (
        price < support
        and tf15["pressure"] <= 48
        and tf15["volume_ratio"] >= 1.1
    ):

        short_score += 12

        short_reasons.append(
            "كسر دعم مع حجم وضغط بيع"
        )

    # =====================================================
    # RESISTANCE
    # =====================================================

    if resistance_distance <= 2.5:

        # Long is dangerous here
        long_score -= 10

        long_reasons.append(
            "السعر قريب من المقاومة"
        )

        if tf15["pressure"] <= 48:

            short_score += 8

            short_reasons.append(
                "رفض محتمل من المقاومة"
            )

    # Break resistance
    if (
        price > resistance
        and tf15["pressure"] >= 55
        and tf15["volume_ratio"] >= 1.15
    ):

        long_score += 12

        long_reasons.append(
            "كسر مقاومة مع حجم وضغط شراء"
        )

    # =====================================================
    # DON'T CHASE PUMP
    # =====================================================

    exploded = (
        tf15["change_5"] >= 8
        or tf1h["change_5"] >= 10
        or tf1h["recovery"] >= 18
    )

    if exploded:

        long_score -= 15

        long_reasons.append(
            "العملة تحركت بقوة بالفعل"
        )

    # =====================================================
    # SCORE
    # =====================================================

    long_score = max(
        0,
        min(long_score, 100)
    )

    short_score = max(
        0,
        min(short_score, 100)
    )

    difference = abs(
        long_score - short_score
    )

    # =====================================================
    # ACTION
    # =====================================================

    if (
        long_score >= 70
        and long_score > short_score
        and difference >= 10
    ):

        action = "🟢 LONG"
        score = long_score
        status = (
            "🟢 تجميع + مراقبة دخول السيولة"
            if accumulation
            else "🟢 تأكيد صعود"
        )

    elif (
        short_score >= 70
        and short_score > long_score
        and difference >= 10
    ):

        action = "🔴 SHORT"
        score = short_score
        status = "🔴 تصريف + ضغط بيع"

    else:

        action = "🟡 WAIT"
        score = max(
            long_score,
            short_score
        )
        status = "🟡 انتظار تأكيد"

    # =====================================================
    # TRADE LEVELS
    # =====================================================

    supports = tf15["supports"]
    resistances = tf15["resistances"]

    if action == "🟢 LONG":

        nearest_support = (
            supports[0]
            if supports
            else support
        )

        stop = nearest_support * 0.99

        entry_low = max(
            nearest_support,
            price * 0.995
        )

        entry_high = price

        # use resistance levels for targets
        target_levels = [
            r for r in resistances
            if r > price
        ]

        if len(target_levels) >= 3:

            tp1 = target_levels[0]
            tp2 = target_levels[1]
            tp3 = target_levels[2]

        else:

            risk = max(
                price - stop,
                price * 0.015
            )

            tp1 = price + risk * 1.5
            tp2 = price + risk * 2.5
            tp3 = price + risk * 3.5

    elif action == "🔴 SHORT":

        nearest_resistance = (
            resistances[0]
            if resistances
            else resistance
        )

        stop = nearest_resistance * 1.01

        entry_low = price

        entry_high = price * 1.005

        target_levels = [
            s for s in supports
            if s < price
        ]

        if len(target_levels) >= 3:

            tp1 = target_levels[0]
            tp2 = target_levels[1]
            tp3 = target_levels[2]

        else:

            risk = max(
                stop - price,
                price * 0.015
            )

            tp1 = max(
                price - risk * 1.5,
                0
            )

            tp2 = max(
                price - risk * 2.5,
                0
            )

            tp3 = max(
                price - risk * 3.5,
                0
            )

    else:

        entry_low = price * 0.995
        entry_high = price * 1.005

        stop = None
        tp1 = None
        tp2 = None
        tp3 = None

    return {
        "symbol": symbol,
        "action": action,
        "score": f"{score}/100",
        "status": status,

        "price": fmt(price),

        "rsi": f"{tf15['rsi']:.1f}",

        "volume": (
            f"{tf15['volume_ratio']:.2f}x"
        ),

        "buy_pressure": (
            f"{tf15['pressure']:.1f}%"
        ),

        "trend": tf1d["trend"],

        "support": fmt(support),
        "resistance": fmt(resistance),

        "supports": [
            fmt(x) for x in supports
        ],

        "resistances": [
            fmt(x) for x in resistances
        ],

        "entry_range": (
            f"{fmt(entry_low)} - "
            f"{fmt(entry_high)}"
        ),

        "stop_loss": fmt(stop),

        "tp1": fmt(tp1),
        "tp2": fmt(tp2),
        "tp3": fmt(tp3),

        "accumulation": accumulation,
        "exploded": exploded,

        "long_score": long_score,
        "short_score": short_score,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons,

        "timeframes": tfs
    }


# =========================================================
# DIRECT COIN
# =========================================================

def get_coin_analysis(symbol_input):

    symbol = normalize_symbol(symbol_input)

    if not symbol:
        return None

    logger.info(
        "Normalized coin: %s",
        symbol
    )

    return analyze_symbol(symbol)


# =========================================================
# FAST MARKET FILTER
# =========================================================

def quick_filter(symbol):

    k = get_klines(
        symbol,
        "1h",
        80
    )

    if not k or len(k) < 50:
        return None

    d = parse_klines(k)

    if not d:
        return None

    closes = d["close"]
    volumes = d["volume"]

    price = closes[-1]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    rr = rsi(closes)

    if None in (e20, e50, rr):
        return None

    avg_volume = sum(
        volumes[-21:-1]
    ) / 20

    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume
        else 0
    )

    change_10 = pct(
        closes[-11],
        price
    )

    # We want coins that are moving,
    # but not already exploding.
    if abs(change_10) > 20:
        return None

    potential = 0

    if price > e20:
        potential += 1

    if e20 > e50:
        potential += 1

    if 35 <= rr <= 70:
        potential += 1

    if volume_ratio >= 0.8:
        potential += 1

    if abs(change_10) >= 2:
        potential += 1

    if potential < 3:
        return None

    return symbol


# =========================================================
# FULL MARKET SCANNER
# =========================================================

def scan_market(limit=5):

    symbols = get_usdt_symbols()

    if not symbols:
        logger.error(
            "No Binance symbols found"
        )
        return []

    logger.info(
        "Scanning %s USDT pairs",
        len(symbols)
    )

    candidates = []

    # -----------------------------------------------------
    # Stage 1: quick scan
    # -----------------------------------------------------

    for index, symbol in enumerate(symbols):

        try:

            candidate = quick_filter(
                symbol
            )

            if candidate:
                candidates.append(
                    candidate
                )

        except Exception as e:

            logger.error(
                "Quick scan error %s: %s",
                symbol,
                e
            )

        # avoid hammering Binance
        if index % 10 == 0:
            time.sleep(0.05)

    logger.info(
        "Quick scan candidates: %s",
        len(candidates)
    )

    # -----------------------------------------------------
    # Stage 2: deep analysis
    # -----------------------------------------------------

    results = []

    for symbol in candidates:

        try:

            data = analyze_symbol(
                symbol
            )

            if not data:
                continue

            action = data["action"]

            score = int(
                data["score"].split("/")[0]
            )

            if action in (
                "🟢 LONG",
                "🔴 SHORT"
            ) and score >= 70:

                results.append(data)

        except Exception as e:

            logger.error(
                "Deep scan error %s: %s",
                symbol,
                e
            )

    # -----------------------------------------------------
    # Best opportunities
    # -----------------------------------------------------

    results.sort(
        key=lambda x: int(
            x["score"].split("/")[0]
        ),
        reverse=True
    )

    return results[:limit]


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(data):

    if not data:
        return (
            "❌ لم يتم العثور على بيانات."
        )

    action = data["action"]

    if action == "🟢 LONG":
        reasons = data["long_reasons"]
    elif action == "🔴 SHORT":
        reasons = data["short_reasons"]
    else:
        reasons = (
            data["long_reasons"]
            + data["short_reasons"]
        )

    reason_text = "\n".join(
        f"• {x}"
        for x in reasons[:7]
    )

    tf = data["timeframes"]

    tf_text = (
        f"15m: {tf['15m']['trend']}\n"
        f"1H: {tf['1h']['trend']}\n"
        f"4H: {tf['4h']['trend']}\n"
        f"1D: {tf['1d']['trend']}"
    )

    supports = data.get(
        "supports",
        []
    )

    resistances = data.get(
        "resistances",
        []
    )

    support_text = (
        " / ".join(supports[:3])
        if supports
        else data["support"]
    )

    resistance_text = (
        " / ".join(resistances[:3])
        if resistances
        else data["resistance"]
    )

    return (
        "🤖 Binance AI Scanner\n\n"

        f"💎 العملة: {data['symbol']}\n"

        f"📈 الاتجاه: {action}\n"

        f"⭐ Score: {data['score']}\n"

        f"🧠 الحالة: {data['status']}\n\n"

        f"💰 السعر: {data['price']}\n"

        f"📊 RSI: {data['rsi']}\n"

        f"📊 Volume: {data['volume']}\n"

        f"💧 ضغط الشراء: "
        f"{data['buy_pressure']}\n\n"

        f"📍 Multi-Timeframe:\n"
        f"{tf_text}\n\n"

        f"🟢 الدعم:\n"
        f"{support_text}\n\n"

        f"🔴 المقاومة:\n"
        f"{resistance_text}\n\n"

        f"🎯 منطقة الدخول:\n"
        f"{data['entry_range']}\n\n"

        f"🛑 Stop Loss:\n"
        f"{data['stop_loss']}\n\n"

        f"🎯 TP1: {data['tp1']}\n"
        f"🎯 TP2: {data['tp2']}\n"
        f"🎯 TP3: {data['tp3']}\n\n"

        f"🧠 أسباب التحليل:\n"
        f"{reason_text}"
    )
