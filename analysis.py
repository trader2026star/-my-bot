import requests
import logging
import time

BINANCE_URL = "https://api.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/8.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# BINANCE API
# =========================================================

def api_get(path, params=None, timeout=10):
    try:
        response = SESSION.get(
            BINANCE_URL + path,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:
            logger.error(
                "Binance API error %s: %s",
                response.status_code,
                response.text[:300]
            )
            return None

        data = response.json()

        if isinstance(data, dict) and data.get("code", 0) < 0:
            logger.error("Binance returned error: %s", data)
            return None

        return data

    except requests.RequestException as e:
        logger.error("Binance connection error: %s", e)
        return None

    except Exception as e:
        logger.exception("Unexpected Binance error: %s", e)
        return None


# =========================================================
# SYMBOL NORMALIZATION
# =========================================================

def normalize_symbol(symbol):
    if not symbol:
        return None

    symbol = str(symbol).upper().strip()

    # Remove common separators
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
    if not values or len(values) < period:
        return None

    k = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:
        value = price * k + value * (1 - k)

    return value


def rsi(values, period=14):
    if not values or len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

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

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


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


def percent_change(old, new):
    if old == 0:
        return 0

    return ((new - old) / old) * 100


# =========================================================
# BINANCE MARKET DATA
# =========================================================

def get_klines(symbol, interval="15m", limit=200):
    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    return api_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def get_exchange_symbols():
    data = api_get("/api/v3/exchangeInfo")

    if not data:
        return set()

    symbols = set()

    for item in data.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
        ):
            symbols.add(item.get("symbol"))

    return symbols


def get_usdt_symbols():
    """
    Primary scanner universe.

    We keep a reliable fallback list so the scanner
    can still work if exchangeInfo temporarily fails.
    """

    fallback = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "TAOUSDT",
        "SEIUSDT",
        "ETCUSDT",
        "AVAXUSDT",
        "SUIUSDT",
        "ADAUSDT",
        "XRPUSDT",
        "PEPEUSDT",
        "RENDERUSDT",
        "NEARUSDT",
        "LINKUSDT",
        "DOGEUSDT",
        "FETUSDT",
        "ARBUSDT",
        "OPUSDT",
        "CAKEUSDT",
        "FILUSDT",
        "ZROUSDT",
        "FLOWUSDT",
        "GPSUSDT",
        "BANKUSDT"
    ]

    exchange_symbols = get_exchange_symbols()

    if not exchange_symbols:
        return fallback

    preferred = [
        symbol
        for symbol in fallback
        if symbol in exchange_symbols
    ]

    return preferred


# =========================================================
# CANDLE PARSING
# =========================================================

def parse_klines(k):
    if not k:
        return None

    try:
        return {
            "open": [float(x[1]) for x in k],
            "high": [float(x[2]) for x in k],
            "low": [float(x[3]) for x in k],
            "close": [float(x[4]) for x in k],
            "volume": [float(x[5]) for x in k]
        }

    except Exception as e:
        logger.error("Kline parsing error: %s", e)
        return None


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(symbol, interval, limit=200):

    k = get_klines(symbol, interval, limit)

    if not k or len(k) < 80:
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

    if None in (e9, e20, e50, rr):
        return None

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    previous_volumes = volumes[-21:-1]

    avg_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes
        else 0
    )

    current_volume = volumes[-1]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume
        else 0
    )

    # -----------------------------------------------------
    # Volume trend
    # -----------------------------------------------------

    old_volume_window = volumes[-20:-10]
    new_volume_window = volumes[-10:]

    old_avg_volume = (
        sum(old_volume_window) / len(old_volume_window)
        if old_volume_window
        else 0
    )

    new_avg_volume = (
        sum(new_volume_window) / len(new_volume_window)
        if new_volume_window
        else 0
    )

    volume_improving = (
        new_avg_volume > old_avg_volume * 1.08
        if old_avg_volume
        else False
    )

    # -----------------------------------------------------
    # Buy / Sell Pressure
    # -----------------------------------------------------

    buy_pressure = 0
    sell_pressure = 0

    for candle in k[-20:]:
        o = float(candle[1])
        h = float(candle[2])
        l = float(candle[3])
        c = float(candle[4])
        v = float(candle[5])

        candle_range = max(h - l, 1e-12)

        buy_pressure += (
            v * max(c - l, 0) / candle_range
        )

        sell_pressure += (
            v * max(h - c, 0) / candle_range
        )

    total_pressure = buy_pressure + sell_pressure

    pressure = (
        buy_pressure / total_pressure * 100
        if total_pressure
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
    # Recent momentum
    # -----------------------------------------------------

    change_5 = percent_change(closes[-6], closes[-1])

    change_10 = percent_change(closes[-11], closes[-1])

    # -----------------------------------------------------
    # Previous dump
    # -----------------------------------------------------

    lookback_price = max(closes[-61:-10])

    previous_dump = percent_change(
        lookback_price,
        min(closes[-10:])
    )

    # -----------------------------------------------------
    # Consolidation
    # -----------------------------------------------------

    recent_high = max(highs[-15:])
    recent_low = min(lows[-15:])

    range_percent = percent_change(
        recent_low,
        recent_high
    )

    consolidation = (
        range_percent <= 12
        and abs(change_5) <= 7
    )

    # -----------------------------------------------------
    # Support / resistance
    # -----------------------------------------------------

    support = min(lows[-40:])
    resistance = max(highs[-40:])

    distance_to_resistance = (
        percent_change(price, resistance)
    )

    distance_from_support = (
        percent_change(support, price)
    )

    # -----------------------------------------------------
    # Recovery from local low
    # -----------------------------------------------------

    local_low = min(lows[-20:])

    recovery = percent_change(
        local_low,
        price
    )

    return {
        "interval": interval,
        "price": price,
        "ema9": e9,
        "ema20": e20,
        "ema50": e50,
        "rsi": rr,
        "volume_ratio": volume_ratio,
        "volume_improving": volume_improving,
        "pressure": pressure,
        "trend": trend,
        "change_5": change_5,
        "change_10": change_10,
        "previous_dump": previous_dump,
        "consolidation": consolidation,
        "range_percent": range_percent,
        "support": support,
        "resistance": resistance,
        "distance_to_resistance": distance_to_resistance,
        "distance_from_support": distance_from_support,
        "recovery": recovery
    }


# =========================================================
# MULTI TIMEFRAME ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    timeframes = {}

    for interval in ["15m", "1h", "4h", "1d"]:

        result = analyze_timeframe(
            symbol,
            interval,
            200
        )

        if result is None:
            logger.warning(
                "Failed timeframe %s for %s",
                interval,
                symbol
            )
            return None

        timeframes[interval] = result

    tf15 = timeframes["15m"]
    tf1h = timeframes["1h"]
    tf4h = timeframes["4h"]
    tf1d = timeframes["1d"]

    price = tf15["price"]

    # =====================================================
    # LONG SCORE
    # =====================================================

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # -----------------------------------------------------
    # Daily direction
    # -----------------------------------------------------

    if tf1d["trend"] in ("BULLISH", "BULLISH_STRONG"):
        long_score += 15
        long_reasons.append("اتجاه يومي إيجابي")

    elif tf1d["trend"] in ("BEARISH", "BEARISH_STRONG"):
        short_score += 15
        short_reasons.append("اتجاه يومي سلبي")

    # -----------------------------------------------------
    # 4H direction
    # -----------------------------------------------------

    if tf4h["trend"] in ("BULLISH", "BULLISH_STRONG"):
        long_score += 15
        long_reasons.append("تأكيد 4H صاعد")

    elif tf4h["trend"] in ("BEARISH", "BEARISH_STRONG"):
        short_score += 15
        short_reasons.append("تأكيد 4H هابط")

    # -----------------------------------------------------
    # 1H
    # -----------------------------------------------------

    if tf1h["trend"] in ("BULLISH", "BULLISH_STRONG"):
        long_score += 10
        long_reasons.append("1H يتحسن")

    elif tf1h["trend"] in ("BEARISH", "BEARISH_STRONG"):
        short_score += 10
        short_reasons.append("1H ضعيف")

    # -----------------------------------------------------
    # 15m
    # -----------------------------------------------------

    if tf15["trend"] in ("BULLISH", "BULLISH_STRONG"):
        long_score += 8
        long_reasons.append("15m إيجابي")

    elif tf15["trend"] in ("BEARISH", "BEARISH_STRONG"):
        short_score += 8
        short_reasons.append("15m سلبي")

    # =====================================================
    # RSI
    # =====================================================

    if 45 <= tf15["rsi"] <= 68:
        long_score += 7
        long_reasons.append("RSI مناسب للصعود")

    if 32 <= tf15["rsi"] <= 50:
        short_score += 7
        short_reasons.append("RSI مناسب للهبوط")

    # =====================================================
    # BUY / SELL PRESSURE
    # =====================================================

    if tf15["pressure"] >= 55:
        long_score += 10
        long_reasons.append("ضغط شراء واضح")

    elif tf15["pressure"] <= 45:
        short_score += 10
        short_reasons.append("ضغط بيع واضح")

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.15:
        if tf15["pressure"] >= 52:
            long_score += 8
            long_reasons.append("دخول حجم مع شراء")

        elif tf15["pressure"] <= 48:
            short_score += 8
            short_reasons.append("زيادة حجم مع بيع")

    if tf15["volume_improving"]:
        if tf15["pressure"] >= 52:
            long_score += 7
            long_reasons.append("الحجم يتحسن تدريجياً")

    # =====================================================
    # ACCUMULATION / DUMP RECOVERY
    # =====================================================

    accumulation = False

    if (
        tf1h["previous_dump"] <= -8
        and tf1h["consolidation"]
        and tf1h["volume_improving"]
        and tf1h["pressure"] >= 52
        and tf1h["recovery"] > 2
    ):
        accumulation = True

        long_score += 15

        long_reasons.append(
            "هبوط سابق + تجميع + تحسن السيولة"
        )

    # =====================================================
    # AVOID CHASING PUMP
    # =====================================================

    exploded = False

    if (
        tf15["change_5"] >= 8
        or tf1h["change_5"] >= 10
        or tf1h["recovery"] >= 18
    ):
        exploded = True

        long_score -= 12

        long_reasons.append(
            "ارتفاع سريع؛ تجنب مطاردة السعر"
        )

    # =====================================================
    # RESISTANCE FILTER
    # =====================================================

    near_resistance = (
        tf15["distance_to_resistance"] <= 2.0
    )

    if near_resistance:
        long_score -= 10
        long_reasons.append("السعر قريب من مقاومة")

    # =====================================================
    # SUPPORT FOR SHORT
    # =====================================================

    near_support = (
        tf15["distance_from_support"] <= 2.0
    )

    if near_support:
        short_score -= 10
        short_reasons.append("السعر قريب من دعم")

    # =====================================================
    # SCORE NORMALIZATION
    # =====================================================

    long_score = max(0, min(long_score, 100))
    short_score = max(0, min(short_score, 100))

    # =====================================================
    # FINAL DECISION
    # =====================================================

    difference = abs(long_score - short_score)

    if long_score >= 70 and long_score > short_score and difference >= 10:

        action = "صعود (LONG)"
        score = long_score
        status = "🟢 فرصة LONG"

    elif short_score >= 70 and short_score > long_score and difference >= 10:

        action = "هبوط (SHORT)"
        score = short_score
        status = "🔴 فرصة SHORT"

    else:

        action = "انتظار (WAIT)"
        score = max(long_score, short_score)
        status = "🟡 لا يوجد تأكيد كافٍ"

    # =====================================================
    # ENTRY / RISK
    # =====================================================

    support = tf15["support"]
    resistance = tf15["resistance"]

    if action == "صعود (LONG)":

        risk = max(
            price - support,
            price * 0.015
        )

        stop = min(
            support * 0.99,
            price - risk
        )

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 3.5

        entry_low = price * 0.995
        entry_high = price

    elif action == "هبوط (SHORT)":

        risk = max(
            resistance - price,
            price * 0.015
        )

        stop = max(
            resistance * 1.01,
            price + risk
        )

        tp1 = max(price - risk * 1.5, 0)
        tp2 = max(price - risk * 2.5, 0)
        tp3 = max(price - risk * 3.5, 0)

        entry_low = price
        entry_high = price * 1.005

    else:

        entry_low = price * 0.995
        entry_high = price * 1.005

        stop = None
        tp1 = None
        tp2 = None
        tp3 = None

    # =====================================================
    # STATUS DETAILS
    # =====================================================

    if accumulation and not exploded:

        detailed_status = (
            "🟢 تجميع + تحسن السيولة + مراقبة دخول"
        )

    elif exploded:

        detailed_status = (
            "🟠 الحركة بدأت بالفعل؛ لا تطارد السعر"
        )

    elif action == "صعود (LONG)":

        detailed_status = "🟢 ميل صاعد مع تأكيدات"

    elif action == "هبوط (SHORT)":

        detailed_status = "🔴 ميل هابط مع تأكيدات"

    else:

        detailed_status = "🟡 انتظار تأكيد"

    # =====================================================
    # OUTPUT
    # =====================================================

    return {
        "symbol": symbol,
        "action": action,
        "score": f"{score}/100",
        "long_score": long_score,
        "short_score": short_score,

        "status": detailed_status,

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

        "entry_range": (
            f"{fmt(entry_low)} - {fmt(entry_high)}"
        ),

        "stop_loss": fmt(stop),

        "tp1": fmt(tp1),

        "tp2": fmt(tp2),

        "tp3": fmt(tp3),

        "accumulation": accumulation,

        "exploded": exploded,

        "long_reasons": long_reasons,

        "short_reasons": short_reasons,

        "timeframes": timeframes
    }


# =========================================================
# COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol_input):

    symbol = normalize_symbol(symbol_input)

    if not symbol:
        return None

    logger.info(
        "Analyzing normalized symbol: %s",
        symbol
    )

    return analyze_symbol(symbol)


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market(limit=5):

    results = []

    symbols = get_usdt_symbols()

    logger.info(
        "Scanner started. Symbols: %s",
        len(symbols)
    )

    for symbol in symbols:

        try:

            data = analyze_symbol(symbol)

            if not data:
                continue

            action = data["action"]

            score = int(
                data["score"].split("/")[0]
            )

            # Only real confirmed opportunities
            if action in (
                "صعود (LONG)",
                "هبوط (SHORT)"
            ) and score >= 70:

                results.append(data)

        except Exception as e:

            logger.exception(
                "Scanner error for %s: %s",
                symbol,
                e
            )

    results.sort(
        key=lambda x: int(
            x["score"].split("/")[0]
        ),
        reverse=True
    )

    logger.info(
        "Scanner completed. Valid opportunities: %s",
        len(results)
    )

    return results[:limit]


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(data):

    if not data:
        return (
            "عذراً، لم يتم العثور على بيانات لهذه العملة."
        )

    long_reasons = data.get(
        "long_reasons",
        []
    )

    short_reasons = data.get(
        "short_reasons",
        []
    )

    if data["action"] == "صعود (LONG)":

        reasons = long_reasons

    elif data["action"] == "هبوط (SHORT)":

        reasons = short_reasons

    else:

        reasons = (
            long_reasons[:3]
            + short_reasons[:3]
        )

    reason_text = "\n".join(
        f"• {reason}"
        for reason in reasons[:6]
    )

    report = (
        f"🤖 Binance AI Scanner\n\n"

        f"💎 العملة: {data['symbol']}\n"

        f"📈 الاتجاه: {data['action']}\n"

        f"⭐ Score: {data['score']}\n"

        f"🧠 الحالة: {data['status']}\n\n"

        f"💰 السعر: {data['price']}\n"

        f"📊 RSI: {data['rsi']}\n"

        f"📊 Volume: {data['volume']}\n"

        f"💧 ضغط الشراء: {data['buy_pressure']}\n"

        f"📍 الاتجاه اليومي: {data['trend']}\n\n"

        f"🎯 منطقة الدخول:\n"
        f"{data['entry_range']}\n\n"

        f"🛑 Stop Loss:\n"
        f"{data['stop_loss']}\n\n"

        f"🎯 TP1: {data['tp1']}\n"
        f"🎯 TP2: {data['tp2']}\n"
        f"🎯 TP3: {data['tp3']}\n\n"

        f"🟢 الدعم: {data['support']}\n"
        f"🔴 المقاومة: {data['resistance']}\n\n"

        f"🧠 أسباب التحليل:\n"
        f"{reason_text if reason_text else 'لا توجد إشارات كافية'}"
    )

    return report
