import requests
import logging
import time

FUTURES_URL = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/11.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# BINANCE API
# =========================================================

def api_get(path, params=None, timeout=10):
    try:
        r = SESSION.get(
            FUTURES_URL + path,
            params=params,
            timeout=timeout
        )
        r.raise_for_status()
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

    symbol = (
        symbol
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
    )

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

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    return 100 - (
        100 / (1 + avg_gain / avg_loss)
    )


def percentage(old, new):

    if old == 0:
        return 0

    return ((new - old) / old) * 100


# =========================================================
# FORMAT
# =========================================================

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


# =========================================================
# ALL BINANCE FUTURES USDT COINS
# =========================================================

def get_usdt_symbols():

    data = api_get(
        "/fapi/v1/exchangeInfo"
    )

    if not data:
        return []

    symbols = []

    for item in data.get("symbols", []):

        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
        ):

            symbols.append(
                item["symbol"]
            )

    return sorted(set(symbols))


# =========================================================
# 24H TICKERS
# =========================================================

def get_futures_tickers():

    data = api_get(
        "/fapi/v1/ticker/24hr"
    )

    if not isinstance(data, list):
        return {}

    result = {}

    for item in data:

        try:

            result[item["symbol"]] = {
                "price": float(
                    item["lastPrice"]
                ),

                "change": float(
                    item["priceChangePercent"]
                ),

                "quote_volume": float(
                    item["quoteVolume"]
                )
            }

        except Exception:
            pass

    return result


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval="15m",
    limit=150
):

    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    return api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# =========================================================
# PARSE KLINES
# =========================================================

def parse_klines(k):

    try:

        return {

            "open": [
                float(x[1])
                for x in k
            ],

            "high": [
                float(x[2])
                for x in k
            ],

            "low": [
                float(x[3])
                for x in k
            ],

            "close": [
                float(x[4])
                for x in k
            ],

            "volume": [
                float(x[5])
                for x in k
            ]
        }

    except Exception:
        return None


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def find_levels(
    highs,
    lows,
    price
):

    supports = []
    resistances = []

    for i in range(
        2,
        len(highs) - 2
    ):

        if (
            highs[i] >= highs[i - 1]
            and highs[i] >= highs[i - 2]
            and highs[i] >= highs[i + 1]
            and highs[i] >= highs[i + 2]
            and highs[i] > price
        ):

            resistances.append(
                highs[i]
            )

        if (
            lows[i] <= lows[i - 1]
            and lows[i] <= lows[i - 2]
            and lows[i] <= lows[i + 1]
            and lows[i] <= lows[i + 2]
            and lows[i] < price
        ):

            supports.append(
                lows[i]
            )

    supports = sorted(
        set(supports),
        reverse=True
    )[:4]

    resistances = sorted(
        set(resistances)
    )[:4]

    return supports, resistances


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(
    symbol,
    interval,
    limit=150
):

    k = get_klines(
        symbol,
        interval,
        limit
    )

    if not k or len(k) < 70:
        return None

    data = parse_klines(k)

    if not data:
        return None

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    volumes = data["volume"]

    price = closes[-1]

    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    rr = rsi(closes)

    if None in (
        e9,
        e20,
        e50,
        rr
    ):
        return None

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    old_volume = (
        sum(volumes[-30:-15]) / 15
    )

    new_volume = (
        sum(volumes[-15:]) / 15
    )

    avg_volume = (
        sum(volumes[-21:-1]) / 20
    )

    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume
        else 0
    )

    volume_improving = (
        new_volume > old_volume * 1.08
        if old_volume
        else False
    )

    # -----------------------------------------------------
    # BUY / SELL PRESSURE
    # -----------------------------------------------------

    buy = 0
    sell = 0

    for candle in k[-20:]:

        h = float(candle[2])
        l = float(candle[3])
        c = float(candle[4])
        v = float(candle[5])

        rng = max(
            h - l,
            1e-12
        )

        buy += (
            v *
            max(c - l, 0) /
            rng
        )

        sell += (
            v *
            max(h - c, 0) /
            rng
        )

    total = buy + sell

    pressure = (
        buy / total * 100
        if total
        else 50
    )

    # -----------------------------------------------------
    # TREND
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
    # PRICE MOVEMENT
    # -----------------------------------------------------

    change_5 = percentage(
        closes[-6],
        price
    )

    change_10 = percentage(
        closes[-11],
        price
    )

    previous_high = max(
        closes[-80:-15]
    )

    recent_low = min(
        closes[-15:]
    )

    previous_dump = percentage(
        previous_high,
        recent_low
    )

    recent_high = max(
        highs[-15:]
    )

    consolidation_range = percentage(
        recent_low,
        recent_high
    )

    consolidation = (
        consolidation_range <= 12
    )

    recovery = percentage(
        recent_low,
        price
    )

    # -----------------------------------------------------
    # LEVELS
    # -----------------------------------------------------

    supports, resistances = find_levels(
        highs,
        lows,
        price
    )

    support = (
        supports[0]
        if supports
        else min(lows[-40:])
    )

    resistance = (
        resistances[0]
        if resistances
        else max(highs[-40:])
    )

    return {

        "price": price,

        "ema9": e9,
        "ema20": e20,
        "ema50": e50,

        "rsi": rr,

        "volume_ratio": volume_ratio,

        "volume_improving":
            volume_improving,

        "pressure": pressure,

        "trend": trend,

        "change_5": change_5,
        "change_10": change_10,

        "previous_dump":
            previous_dump,

        "consolidation":
            consolidation,

        "recovery":
            recovery,

        "support":
            support,

        "resistance":
            resistance,

        "supports":
            supports,

        "resistances":
            resistances
    }


# =========================================================
# DEEP ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    timeframes = {}

    for interval in (
        "15m",
        "1h",
        "4h",
        "1d"
    ):

        result = analyze_timeframe(
            symbol,
            interval
        )

        if not result:
            return None

        timeframes[
            interval
        ] = result

        time.sleep(0.04)

    tf15 = timeframes["15m"]
    tf1h = timeframes["1h"]
    tf4h = timeframes["4h"]
    tf1d = timeframes["1d"]

    price = tf15["price"]

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # DAILY
    # =====================================================

    if tf1d["trend"].startswith(
        "BULLISH"
    ):

        long_score += 12

        long_reasons.append(
            "الاتجاه اليومي صاعد"
        )

    elif tf1d["trend"].startswith(
        "BEARISH"
    ):

        short_score += 12

        short_reasons.append(
            "الاتجاه اليومي هابط"
        )

    # =====================================================
    # 4H
    # =====================================================

    if tf4h["trend"].startswith(
        "BULLISH"
    ):

        long_score += 15

        long_reasons.append(
            "تأكيد صاعد على 4H"
        )

    elif tf4h["trend"].startswith(
        "BEARISH"
    ):

        short_score += 15

        short_reasons.append(
            "تأكيد هابط على 4H"
        )

    # =====================================================
    # 1H
    # =====================================================

    if tf1h["trend"].startswith(
        "BULLISH"
    ):

        long_score += 10

        long_reasons.append(
            "تحسن الاتجاه على 1H"
        )

    elif tf1h["trend"].startswith(
        "BEARISH"
    ):

        short_score += 10

        short_reasons.append(
            "ضعف الاتجاه على 1H"
        )

    # =====================================================
    # 15M
    # =====================================================

    if tf15["trend"].startswith(
        "BULLISH"
    ):

        long_score += 8

        long_reasons.append(
            "15m يدعم الصعود"
        )

    elif tf15["trend"].startswith(
        "BEARISH"
    ):

        short_score += 8

        short_reasons.append(
            "15m يدعم الهبوط"
        )

    # =====================================================
    # RSI
    # =====================================================

    if 45 <= tf15["rsi"] <= 68:

        long_score += 7

        long_reasons.append(
            "RSI مناسب للصعود"
        )

    if 32 <= tf15["rsi"] <= 50:

        short_score += 7

        short_reasons.append(
            "RSI يسمح باستمرار الهبوط"
        )

    # =====================================================
    # PRESSURE
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

            long_score += 7

            long_reasons.append(
                "الحجم يدعم المشترين"
            )

        elif tf15["pressure"] <= 48:

            short_score += 7

            short_reasons.append(
                "الحجم يدعم البائعين"
            )

    if (
        tf15["volume_improving"]
        and tf15["pressure"] >= 52
    ):

        long_score += 7

        long_reasons.append(
            "الحجم يتحسن تدريجياً"
        )

    # =====================================================
    # ACCUMULATION
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

    support_distance = (
        abs(
            price - tf15["support"]
        )
        / price
        * 100
    )

    if (
        support_distance <= 3
        and tf15["pressure"] >= 52
    ):

        long_score += 10

        long_reasons.append(
            "السعر قريب من دعم مع ضغط شراء"
        )

    # =====================================================
    # SUPPORT BREAK
    # =====================================================

    if (
        price < tf15["support"]
        and tf15["pressure"] <= 48
        and tf15["volume_ratio"] >= 1.10
    ):

        short_score += 12

        short_reasons.append(
            "كسر دعم مع حجم وضغط بيع"
        )

    # =====================================================
    # RESISTANCE
    # =====================================================

    resistance_distance = (
        abs(
            tf15["resistance"] - price
        )
        / price
        * 100
    )

    if resistance_distance <= 2.5:

        long_score -= 10

        long_reasons.append(
            "السعر قريب من مقاومة"
        )

        if tf15["pressure"] <= 48:

            short_score += 8

            short_reasons.append(
                "رفض محتمل من المقاومة"
            )

    # =====================================================
    # RESISTANCE BREAK
    # =====================================================

    if (
        price > tf15["resistance"]
        and tf15["pressure"] >= 55
        and tf15["volume_ratio"] >= 1.15
    ):

        long_score += 12

        long_reasons.append(
            "كسر مقاومة بحجم وضغط شراء"
        )

    # =====================================================
    # EXPLOSION FILTER
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
    # FINAL DECISION
    # =====================================================

    if (
        long_score >= 70
        and long_score > short_score
        and difference >= 10
    ):

        action = "🟢 LONG"

        score = long_score

        if (
            accumulation
            and not exploded
        ):

            status = (
                "🟢 تجميع + مراقبة دخول السيولة"
            )

        else:

            status = (
                "🟢 تأكيد صعود"
            )

    elif (
        short_score >= 70
        and short_score > long_score
        and difference >= 10
    ):

        action = "🔴 SHORT"

        score = short_score

        status = (
            "🔴 تصريف + ضغط بيع"
        )

    else:

        action = "🟡 WAIT"

        score = max(
            long_score,
            short_score
        )

        status = (
            "🟡 انتظار تأكيد"
        )

    # =====================================================
    # ENTRY / SL / TARGETS
    # =====================================================

    supports = tf15["supports"]
    resistances = tf15["resistances"]

    if action == "🟢 LONG":

        support_level = (
            supports[0]
            if supports
            else tf15["support"]
        )

        stop = (
            support_level * 0.99
        )

        entry_low = max(
            support_level,
            price * 0.995
        )

        entry_high = price

        future_resistance = [
            x
            for x in resistances
            if x > price
        ]

        if len(future_resistance) >= 3:

            tp1 = future_resistance[0]
            tp2 = future_resistance[1]
            tp3 = future_resistance[2]

        else:

            risk = max(
                price - stop,
                price * 0.015
            )

            tp1 = price + risk * 1.5
            tp2 = price + risk * 2.5
            tp3 = price + risk * 3.5

    elif action == "🔴 SHORT":

        resistance_level = (
            resistances[0]
            if resistances
            else tf15["resistance"]
        )

        stop = (
            resistance_level * 1.01
        )

        entry_low = price
        entry_high = price * 1.005

        lower_supports = [
            x
            for x in supports
            if x < price
        ]

        if len(lower_supports) >= 3:

            tp1 = lower_supports[0]
            tp2 = lower_supports[1]
            tp3 = lower_supports[2]

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
        entry_high = price

        stop = None
        tp1 = None
        tp2 = None
        tp3 = None

    return {

        "symbol": symbol,

        "action": action,

        "score":
            f"{score}/100",

        "status": status,

        "price":
            fmt(price),

        "rsi":
            f"{tf15['rsi']:.1f}",

        "volume":
            f"{tf15['volume_ratio']:.2f}x",

        "buy_pressure":
            f"{tf15['pressure']:.1f}%",

        "trend":
            tf1d["trend"],

        "support":
            fmt(tf15["support"]),

        "resistance":
            fmt(tf15["resistance"]),

        "supports":
            [
                fmt(x)
                for x in supports
            ],

        "resistances":
            [
                fmt(x)
                for x in resistances
            ],

        "entry_range":
            f"{fmt(entry_low)} - {fmt(entry_high)}",

        "stop_loss":
            fmt(stop),

        "tp1":
            fmt(tp1),

        "tp2":
            fmt(tp2),

        "tp3":
            fmt(tp3),

        "accumulation":
            accumulation,

        "exploded":
            exploded,

        "long_reasons":
            long_reasons,

        "short_reasons":
            short_reasons,

        "timeframes":
            timeframes
    }


# =========================================================
# SINGLE COIN
# =========================================================

def get_coin_analysis(
    symbol_input
):

    symbol = normalize_symbol(
        symbol_input
    )

    if not symbol:
        return None

    return analyze_symbol(
        symbol
    )


# =========================================================
# QUICK SCANNER FILTER
# =========================================================

def quick_filter(
    symbol,
    ticker=None
):

    k = get_klines(
        symbol,
        "1h",
        80
    )

    if not k or len(k) < 50:
        return None

    data = parse_klines(k)

    if not data:
        return None

    closes = data["close"]
    volumes = data["volume"]

    price = closes[-1]

    e20 = ema(
        closes,
        20
    )

    e50 = ema(
        closes,
        50
    )

    rr = rsi(closes)

    if None in (
        e20,
        e50,
        rr
    ):
        return None

    avg_volume = (
        sum(volumes[-21:-1])
        / 20
    )

    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume
        else 0
    )

    change = percentage(
        closes[-11],
        price
    )

    # لا نريد عملة انفجرت بالفعل
    if change > 15:
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

    if abs(change) >= 2:
        potential += 1

    if ticker:

        if ticker.get(
            "quote_volume",
            0
        ) >= 5_000_000:

            potential += 1

    return (
        symbol
        if potential >= 3
        else None
    )


# =========================================================
# MARKET SCAN
# =========================================================

def scan_market(limit=5):

    symbols = get_usdt_symbols()

    if not symbols:
        return []

    tickers = get_futures_tickers()

    candidates = []

    for symbol in symbols:

        try:

            candidate = quick_filter(
                symbol,
                tickers.get(symbol)
            )

            if candidate:

                candidates.append(
                    candidate
                )

        except Exception as e:

            logger.error(
                "Quick filter %s: %s",
                symbol,
                e
            )

    # حماية Render من الفحص العميق لكل آلاف العملات دفعة واحدة
    candidates = candidates[:40]

    results = []

    for symbol in candidates:

        try:

            data = analyze_symbol(
                symbol
            )

            if data:

                score = int(
                    data["score"].split("/")[0]
                )

                if (
                    data["action"]
                    in (
                        "🟢 LONG",
                        "🔴 SHORT"
                    )
                    and score >= 70
                ):

                    results.append(
                        data
                    )

        except Exception as e:

            logger.error(
                "Deep analysis %s: %s",
                symbol,
                e
            )

    results.sort(
        key=lambda x:
            int(
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

    if data["action"] == "🟢 LONG":

        reasons = data[
            "long_reasons"
        ]

    else:

        reasons = data[
            "short_reasons"
        ]

    tf = data["timeframes"]

    support_text = (
        " / ".join(
            data["supports"][:3]
        )
        if data["supports"]
        else data["support"]
    )

    resistance_text = (
        " / ".join(
            data["resistances"][:3]
        )
        if data["resistances"]
        else data["resistance"]
    )

    reason_text = "\n".join(
        f"• {x}"
        for x in reasons[:7]
    )

    return (

        "🤖 Binance AI Scanner\n\n"

        f"💎 العملة: {data['symbol']}\n"

        f"📈 الاتجاه: {data['action']}\n"

        f"⭐ Score: {data['score']}\n"

        f"🧠 الحالة: {data['status']}\n\n"

        f"💰 السعر: {data['price']}\n"

        f"📊 RSI: {data['rsi']}\n"

        f"📊 Volume: {data['volume']}\n"

        f"💧 ضغط الشراء: "
        f"{data['buy_pressure']}\n\n"

        "📍 Multi-Timeframe:\n"

        f"15m: "
        f"{tf['15m']['trend']}\n"

        f"1H: "
        f"{tf['1h']['trend']}\n"

        f"4H: "
        f"{tf['4h']['trend']}\n"

        f"1D: "
        f"{tf['1d']['trend']}\n\n"

        f"🟢 الدعم: "
        f"{support_text}\n"

        f"🔴 المقاومة: "
        f"{resistance_text}\n\n"

        f"🎯 منطقة الدخول: "
        f"{data['entry_range']}\n"

        f"🛑 Stop Loss: "
        f"{data['stop_loss']}\n"

        f"🎯 TP1: "
        f"{data['tp1']}\n"

        f"🎯 TP2: "
        f"{data['tp2']}\n"

        f"🎯 TP3: "
        f"{data['tp3']}\n\n"

        f"🧠 أسباب التحليل:\n"
        f"{reason_text or 'لا توجد إشارات كافية'}"
    )
