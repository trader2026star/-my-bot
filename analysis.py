import requests
import time
from statistics import mean

# =========================================================
# BINANCE
# =========================================================

BINANCE_BASE_URL = "https://data-api.binance.vision"

TIMEFRAMES = {
    "15m":  "15m",
    "1h":   "1h",
    "4h":   "4h",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# =========================================================
# BASIC HELPERS
# =========================================================

def format_number(value):
    try:
        value = float(value)

        if value >= 1000:
            return f"{value:,.2f}"
        elif value >= 1:
            return f"{value:.4f}"
        elif value >= 0.1:
            return f"{value:.5f}"
        elif value >= 0.01:
            return f"{value:.6f}"
        elif value >= 0.001:
            return f"{value:.7f}"
        else:
            return f"{value:.10f}"

    except Exception:
        return str(value)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def get_json(url, params=None, timeout=10):
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# =========================================================
# BINANCE DATA
# =========================================================

def get_usdt_symbols():
    """
    جلب العملات USDT فقط.
    نستبعد العملات غير النشطة والـstablecoins.
    """

    url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
    data = get_json(url)

    if not data:
        return []

    stablecoins = {
        "USDT", "USDC", "FDUSD", "TUSD",
        "USDP", "DAI", "BUSD"
    }

    symbols = []

    for s in data.get("symbols", []):

        if s.get("status") != "TRADING":
            continue

        if s.get("quoteAsset") != "USDT":
            continue

        symbol = s.get("symbol", "")

        base = s.get("baseAsset", "")

        if base in stablecoins:
            continue

        # استبعاد بعض الرموز غير المناسبة للفحص
        if any(x in symbol for x in [
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        ]):
            continue

        symbols.append(symbol)

    return symbols


def get_current_price(symbol):
    """
    سعر مباشر من Binance.
    """

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"

    data = get_json(
        url,
        params={"symbol": symbol}
    )

    if not data:
        return 0.0

    return safe_float(data.get("price"))


def get_klines(symbol, interval="15m", limit=150):
    """
    جلب الشموع.
    """

    url = f"{BINANCE_BASE_URL}/api/v3/klines"

    data = get_json(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data or not isinstance(data, list):
        return []

    candles = []

    for k in data:

        if len(k) < 11:
            continue

        candles.append({
            "open_time": k[0],
            "open": safe_float(k[1]),
            "high": safe_float(k[2]),
            "low": safe_float(k[3]),
            "close": safe_float(k[4]),
            "volume": safe_float(k[5]),
            "close_time": k[6],
            "quote_volume": safe_float(k[7]),
            "trades": int(k[8]),
            "taker_buy_base": safe_float(k[9]),
            "taker_buy_quote": safe_float(k[10])
        })

    return candles


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)

    result = []

    ema_value = mean(values[:period])

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

        result.append(ema_value)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) +
            gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) <= period:
        return 0.0

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        trs.append(tr)

    return mean(trs[-period:])


# =========================================================
# MARKET STRUCTURE
# =========================================================

def highest(candles, field, count):
    if len(candles) < count:
        return 0

    return max(
        c[field]
        for c in candles[-count:]
    )


def lowest(candles, field, count):
    if len(candles) < count:
        return 0

    return min(
        c[field]
        for c in candles[-count:]
    )


def average_volume(candles, count):
    if len(candles) < count:
        return 0

    return mean(
        c["volume"]
        for c in candles[-count:]
    )


# =========================================================
# PRE-PUMP DETECTION
# =========================================================

def detect_accumulation(candles):
    """
    يبحث عن مرحلة التجميع قبل الانفجار.

    المطلوب:
    - نطاق سعري ضيق
    - انخفاض نسبي في ATR
    - السعر قريب من مقاومة
    - حجم يبدأ في التحسن
    """

    if len(candles) < 50:
        return False, 0

    recent = candles[-20:]

    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    closes = [c["close"] for c in recent]

    highest_price = max(highs)
    lowest_price = min(lows)

    if lowest_price <= 0:
        return False, 0

    range_percent = (
        (highest_price - lowest_price)
        / lowest_price
    ) * 100

    current = closes[-1]

    # قرب السعر من أعلى منطقة التجميع
    distance_from_high = (
        (highest_price - current)
        / current
    ) * 100

    atr_value = atr(candles, 14)

    atr_percent = (
        atr_value / current * 100
        if current > 0 else 100
    )

    recent_volume = average_volume(candles, 5)
    old_volume = average_volume(candles, 30)

    if old_volume <= 0:
        return False, 0

    volume_ratio = recent_volume / old_volume

    score = 0

    # ضغط سعري
    if range_percent <= 8:
        score += 20

    if range_percent <= 5:
        score += 10

    # ATR منخفض = ضغط
    if atr_percent <= 4:
        score += 15

    if atr_percent <= 2.5:
        score += 10

    # قرب المقاومة
    if distance_from_high <= 3:
        score += 20

    elif distance_from_high <= 5:
        score += 10

    # حجم يتجمع
    if volume_ratio >= 1.10:
        score += 10

    if volume_ratio >= 1.30:
        score += 10

    return score >= 45, score


def detect_volume_build_up(candles):
    """
    هل الحجم بدأ يدخل قبل الحركة؟
    """

    if len(candles) < 40:
        return False, 0

    last_5 = average_volume(candles, 5)
    last_10 = average_volume(candles, 10)
    previous_20 = average_volume(
        candles[:-10],
        20
    )

    if previous_20 <= 0:
        return False, 0

    ratio_5 = last_5 / previous_20
    ratio_10 = last_10 / previous_20

    score = 0

    if ratio_5 >= 1.10:
        score += 20

    if ratio_5 >= 1.25:
        score += 15

    if ratio_10 >= 1.10:
        score += 15

    # فحص هل آخر الشموع معظمها شراء
    positive = 0

    for c in candles[-8:]:

        if c["close"] > c["open"]:
            positive += 1

    if positive >= 5:
        score += 15

    return score >= 30, score


def detect_breakout_pressure(candles):
    """
    العملة تضغط أسفل المقاومة
    بدون أن تكون انفجرت بالفعل.
    """

    if len(candles) < 50:
        return False, 0

    current = candles[-1]["close"]

    resistance = highest(
        candles[:-3],
        "high",
        30
    )

    if resistance <= 0:
        return False, 0

    distance = (
        (resistance - current)
        / resistance
    ) * 100

    score = 0

    if 0 < distance <= 5:
        score += 25

    if 0 < distance <= 3:
        score += 15

    # آخر 5 شموع
    higher_closes = 0

    for i in range(
        len(candles) - 5,
        len(candles)
    ):

        if candles[i]["close"] >= candles[i]["open"]:
            higher_closes += 1

    if higher_closes >= 3:
        score += 15

    return score >= 30, score


# =========================================================
# AVOID LATE PUMP
# =========================================================

def is_already_pumped(candles):
    """
    يمنع الدخول بعد الانفجار.

    إذا العملة صعدت بقوة خلال آخر عدة شموع
    نرفضها حتى لو باقي المؤشرات جيدة.
    """

    if len(candles) < 30:
        return False

    closes = [
        c["close"]
        for c in candles
    ]

    current = closes[-1]

    # حركة آخر 3 شموع
    price_3 = closes[-4]

    if price_3 > 0:

        move_3 = (
            (current - price_3)
            / price_3
        ) * 100

        if move_3 >= 8:
            return True

        if move_3 >= 12:
            return True

    # حركة آخر 8 شموع
    price_8 = closes[-9]

    if price_8 > 0:

        move_8 = (
            (current - price_8)
            / price_8
        ) * 100

        if move_8 >= 15:
            return True

    # شمعة انفجار واحدة
    for c in candles[-3:]:

        candle_move = (
            (c["close"] - c["open"])
            / c["open"]
        ) * 100

        if candle_move >= 7:
            return True

    return False


# =========================================================
# TREND
# =========================================================

def trend_score(candles):
    if len(candles) < 60:
        return 0

    closes = [
        c["close"]
        for c in candles
    ]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if not e20 or not e50:
        return 0

    ema20 = e20[-1]
    ema50 = e50[-1]
    price = closes[-1]

    score = 0

    if price > ema20:
        score += 15

    if ema20 > ema50:
        score += 20

    if price > ema50:
        score += 15

    current_rsi = rsi(closes)

    # لا نريد RSI منهار ولا Overbought جداً
    if 50 <= current_rsi <= 68:
        score += 15

    elif 45 <= current_rsi < 50:
        score += 5

    return score


# =========================================================
# MAIN ANALYSIS
# =========================================================

def analyze_symbol(symbol):
    """
    التحليل الرئيسي.

    الهدف:
    اكتشاف العملة وهي:
    ACCUMULATION
    + VOLUME BUILDUP
    + BREAKOUT PRESSURE
    قبل الـPump.
    """

    candles_15m = get_klines(
        symbol,
        "15m",
        150
    )

    candles_1h = get_klines(
        symbol,
        "1h",
        150
    )

    candles_4h = get_klines(
        symbol,
        "4h",
        100
    )

    if (
        len(candles_15m) < 60 or
        len(candles_1h) < 60 or
        len(candles_4h) < 60
    ):
        return None

    current_price = candles_15m[-1]["close"]

    if current_price <= 0:
        return None

    # -----------------------------------------------------
    # منع الدخول بعد الانفجار
    # -----------------------------------------------------

    if is_already_pumped(candles_15m):
        return None

    # -----------------------------------------------------
    # التجميع
    # -----------------------------------------------------

    accumulation, accumulation_score = \
        detect_accumulation(candles_15m)

    if not accumulation:
        return None

    # -----------------------------------------------------
    # الحجم
    # -----------------------------------------------------

    volume_ready, volume_score = \
        detect_volume_build_up(candles_15m)

    if not volume_ready:
        return None

    # -----------------------------------------------------
    # ضغط الاختراق
    # -----------------------------------------------------

    breakout_ready, breakout_score = \
        detect_breakout_pressure(candles_15m)

    if not breakout_ready:
        return None

    # -----------------------------------------------------
    # اتجاه الساعة
    # -----------------------------------------------------

    trend_1h = trend_score(candles_1h)

    # -----------------------------------------------------
    # اتجاه 4 ساعات
    # -----------------------------------------------------

    trend_4h = trend_score(candles_4h)

    # -----------------------------------------------------
    # الإجمالي
    # -----------------------------------------------------

    total_score = (
        accumulation_score +
        volume_score +
        breakout_score +
        trend_1h +
        trend_4h
    )

    # الحد الأدنى
    if total_score < 125:
        return None

    # -----------------------------------------------------
    # المقاومة
    # -----------------------------------------------------

    resistance = highest(
        candles_15m[:-3],
        "high",
        30
    )

    support = lowest(
        candles_15m[-20:],
        "low",
        20
    )

    if resistance <= current_price:
        return None

    distance_to_resistance = (
        (resistance - current_price)
        / current_price
    ) * 100

    # لازم يكون قريب من المقاومة
    if distance_to_resistance > 6:
        return None

    # -----------------------------------------------------
    # ATR
    # -----------------------------------------------------

    atr_value = atr(
        candles_15m,
        14
    )

    # -----------------------------------------------------
    # ENTRY
    # -----------------------------------------------------

    entry_low = current_price

    entry_high = resistance

    # -----------------------------------------------------
    # Targets
    # -----------------------------------------------------

    risk_range = resistance - current_price

    if risk_range <= 0:
        return None

    tp1 = resistance + (
        risk_range * 0.8
    )

    tp2 = resistance + (
        risk_range * 1.6
    )

    tp3 = resistance + (
        risk_range * 2.5
    )

    # -----------------------------------------------------
    # STOP
    # -----------------------------------------------------

    stop = support - (
        atr_value * 0.30
    )

    if stop <= 0:
        stop = current_price * 0.97

    # -----------------------------------------------------
    # CONFIDENCE
    # -----------------------------------------------------

    max_score = 225

    confidence = (
        total_score / max_score
    ) * 100

    confidence = min(
        99,
        max(0, confidence)
    )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    return {
        "symbol": symbol,
        "side": "LONG",

        "price": current_price,

        "entry": current_price,

        "resistance": resistance,
        "support": support,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "stop_loss": stop,

        "score": round(total_score, 1),
        "confidence": round(confidence, 1),

        "accumulation_score":
            accumulation_score,

        "volume_score":
            volume_score,

        "breakout_score":
            breakout_score,

        "trend_1h":
            trend_1h,

        "trend_4h":
            trend_4h,

        "distance_to_breakout":
            round(
                distance_to_resistance,
                2
            ),

        "status":
            "PRE_PUMP"
    }


# =========================================================
# TELEGRAM FORMAT
# =========================================================

def format_trade_signal(result):

    if not result:
        return None

    symbol = result["symbol"]

    price = result["price"]

    entry = result["entry"]

    resistance = result["resistance"]

    tp1 = result["tp1"]
    tp2 = result["tp2"]
    tp3 = result["tp3"]

    stop = result["stop_loss"]

    score = result["score"]

    confidence = result["confidence"]

    distance = result[
        "distance_to_breakout"
    ]

    message = (
        "🚨 PRE-PUMP ALERT\n\n"

        f"🪙 {symbol}\n"
        f"📊 الاتجاه: LONG\n\n"

        f"💰 السعر: {format_number(price)}\n"

        f"🎯 منطقة الدخول: "
        f"{format_number(entry)}\n\n"

        f"🔥 المقاومة/الاختراق: "
        f"{format_number(resistance)}\n"

        f"📏 المتبقي للاختراق: "
        f"{distance}%\n\n"

        f"🎯 TP1: {format_number(tp1)}\n"
        f"🎯 TP2: {format_number(tp2)}\n"
        f"🎯 TP3: {format_number(tp3)}\n\n"

        f"🛑 SL: {format_number(stop)}\n\n"

        f"📈 Score: {score}\n"
        f"⚡ Confidence: {confidence}%\n\n"

        "🔍 سبب التنبيه:\n"
        "• تجميع سعري\n"
        "• ضغط أسفل المقاومة\n"
        "• دخول حجم تدريجي\n"
        "• لم يحدث Pump قوي بعد\n\n"

        "⚠️ التنبيه يراقب ما قبل الانفجار "
        "وليس مطاردة العملة بعد الانفجار."
    )

    return message


# =========================================================
# SCAN ONE SYMBOL
# =========================================================

def scan_market(symbol):
    """
    متوافق مع main.py الحالي.
    """

    try:

        result = analyze_symbol(symbol)

        if not result:
            return None

        return format_trade_signal(result)

    except Exception as e:

        print(
            f"[ANALYSIS ERROR] "
            f"{symbol}: {e}"
        )

        return None


# =========================================================
# FIND BEST PRE-PUMP COINS
# =========================================================

def scan_all_markets(max_symbols=100):
    """
    يفحص مجموعة من العملات ويرجع
    أفضل العملات في مرحلة ما قبل الانفجار.
    """

    symbols = get_usdt_symbols()

    if not symbols:
        return []

    results = []

    # منع ضغط زائد على Binance
    symbols = symbols[:max_symbols]

    for symbol in symbols:

        try:

            result = analyze_symbol(symbol)

            if result:
                results.append(result)

            time.sleep(0.05)

        except Exception as e:

            print(
                f"[SCAN ERROR] "
                f"{symbol}: {e}"
            )

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# =========================================================
# TOP PRE-PUMP
# =========================================================

def get_top_pre_pump(limit=10):

    results = scan_all_markets()

    return results[:limit]


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    print(
        "PRE-PUMP SCANNER STARTED"
    )

    results = get_top_pre_pump(10)

    if not results:

        print(
            "No strong PRE-PUMP setups found."
        )

    else:

        for r in results:

            print(
                "\n"
                f"{r['symbol']} | "
                f"Score={r['score']} | "
                f"Confidence={r['confidence']}% | "
                f"Price={format_number(r['price'])} | "
                f"Breakout={format_number(r['resistance'])}"
            )
