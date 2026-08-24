import time
import logging
import requests


# =========================================================
# SETTINGS
# =========================================================

FUTURES_URL = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/8.0"
})

logger = logging.getLogger(__name__)

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 300

# عدد العملات التي يتم تحليلها فعليًا
SCAN_UNIVERSE = 60

# عدد الفرص التي ترجع من scanner
DEFAULT_RESULTS = 5


# =========================================================
# BINANCE REQUEST
# =========================================================

def binance_get(path, params=None, timeout=12):
    try:
        response = SESSION.get(
            FUTURES_URL + path,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:
            logger.warning(
                "Binance HTTP %s | %s | %s",
                response.status_code,
                path,
                response.text[:300]
            )
            return None

        data = response.json()

        if isinstance(data, dict) and "code" in data:
            logger.warning(
                "Binance API error | %s",
                data
            )
            return None

        return data

    except requests.RequestException as exc:
        logger.warning("Binance request failed: %s", exc)
        return None

    except ValueError as exc:
        logger.warning("Invalid Binance JSON: %s", exc)
        return None


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(text):
    text = str(text).strip().upper()

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")

    if text.endswith("/USDT"):
        text = text[:-5] + "USDT"

    if not text.endswith("USDT"):
        text += "USDT"

    return text


# =========================================================
# FUTURES SYMBOLS
# =========================================================

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    now = time.time()

    if (
        not force_refresh
        and _SYMBOL_CACHE
        and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS
    ):
        return set(_SYMBOL_CACHE)

    data = binance_get(
        "/fapi/v1/exchangeInfo",
        timeout=15
    )

    if not data:
        return set(_SYMBOL_CACHE)

    symbols = set()

    for item in data.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
        ):
            symbol = item.get("symbol")

            if symbol:
                symbols.add(symbol)

    if symbols:
        _SYMBOL_CACHE = symbols
        _SYMBOL_CACHE_TIME = now

    return set(_SYMBOL_CACHE)


def symbol_exists(symbol):
    symbol = normalize_symbol(symbol)
    return symbol in get_futures_symbols()


# =========================================================
# KLINES
# =========================================================

def get_binance_futures_klines(
    symbol,
    interval="1h",
    limit=200
):
    symbol = normalize_symbol(symbol)

    data = binance_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not isinstance(data, list):
        return None

    if len(data) < 20:
        return None

    return data


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return round(
        100 - (100 / (1 + rs)),
        2
    )


# =========================================================
# ATR
# =========================================================

def calculate_atr(klines, period=14):
    if len(klines) < period + 1:
        return None

    trs = []

    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        previous_close = float(klines[i - 1][4])

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period

    for value in trs[period:]:
        atr = (
            (atr * (period - 1))
            + value
        ) / period

    return atr


# =========================================================
# VOLUME RATIO
# =========================================================

def calculate_volume_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return 1.0

    previous = volumes[-period - 1:-1]

    average_volume = sum(previous) / len(previous)

    if average_volume <= 0:
        return 1.0

    return round(
        volumes[-1] / average_volume,
        2
    )


# =========================================================
# VOLUME TREND
# =========================================================

def calculate_volume_trend(
    volumes,
    short_period=5,
    long_period=20
):
    if len(volumes) < long_period:
        return "NEUTRAL"

    short_avg = (
        sum(volumes[-short_period:])
        / short_period
    )

    long_avg = (
        sum(volumes[-long_period:])
        / long_period
    )

    if long_avg <= 0:
        return "NEUTRAL"

    ratio = short_avg / long_avg

    if ratio >= 1.15:
        return "RISING"

    if ratio <= 0.85:
        return "FALLING"

    return "NEUTRAL"


# =========================================================
# PRICE CHANGE
# =========================================================

def percentage_change(old_price, new_price):
    if old_price == 0:
        return 0.0

    return (
        (new_price - old_price)
        / old_price
    ) * 100


def calculate_price_change(closes, candles):
    if len(closes) <= candles:
        return 0.0

    return percentage_change(
        closes[-candles - 1],
        closes[-1]
    )


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(klines):
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    current_price = closes[-1]

    lookback = min(80, len(klines))

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    supports = []
    resistances = []

    tolerance = 0.006

    for low in recent_lows:
        if low < current_price:
            distance = abs(current_price - low) / current_price

            if distance <= 0.15:
                supports.append(low)

    for high in recent_highs:
        if high > current_price:
            distance = abs(high - current_price) / current_price

            if distance <= 0.15:
                resistances.append(high)

    support = (
        max(supports)
        if supports
        else min(recent_lows)
    )

    resistance = (
        min(resistances)
        if resistances
        else max(recent_highs)
    )

    support_cluster = [
        x for x in recent_lows
        if abs(x - support) / current_price <= tolerance
    ]

    resistance_cluster = [
        x for x in recent_highs
        if abs(x - resistance) / current_price <= tolerance
    ]

    if support_cluster:
        support = sum(support_cluster) / len(support_cluster)

    if resistance_cluster:
        resistance = sum(resistance_cluster) / len(resistance_cluster)

    return support, resistance


# =========================================================
# CANDLE STRUCTURE
# =========================================================

def candle_information(klines):
    if len(klines) < 3:
        return {
            "body_ratio": 0,
            "lower_wick_ratio": 0,
            "upper_wick_ratio": 0,
            "bullish": False,
            "bearish": False
        }

    k = klines[-1]

    open_price = float(k[1])
    high = float(k[2])
    low = float(k[3])
    close = float(k[4])

    candle_range = high - low

    if candle_range <= 0:
        return {
            "body_ratio": 0,
            "lower_wick_ratio": 0,
            "upper_wick_ratio": 0,
            "bullish": close > open_price,
            "bearish": close < open_price
        }

    body = abs(close - open_price)

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    return {
        "body_ratio": body / candle_range,
        "lower_wick_ratio": lower_wick / candle_range,
        "upper_wick_ratio": upper_wick / candle_range,
        "bullish": close > open_price,
        "bearish": close < open_price
    }


# =========================================================
# RECENT DRAWDOWN
# =========================================================

def calculate_recent_drawdown(closes, lookback=50):
    if len(closes) < lookback:
        lookback = len(closes)

    window = closes[-lookback:]

    if not window:
        return 0.0

    highest = max(window)
    current = closes[-1]

    if highest <= 0:
        return 0.0

    return round(
        ((current - highest) / highest) * 100,
        2
    )


# =========================================================
# RECOVERY FROM LOW
# =========================================================

def calculate_recovery_from_low(closes, lookback=30):
    if len(closes) < lookback:
        lookback = len(closes)

    window = closes[-lookback:]

    if not window:
        return 0.0

    low = min(window)
    current = closes[-1]

    if low <= 0:
        return 0.0

    return round(
        ((current - low) / low) * 100,
        2
    )


# =========================================================
# RANGE COMPRESSION
# =========================================================

def detect_range_compression(klines):
    if len(klines) < 40:
        return False, 0, 0.0

    closes = [float(k[4]) for k in klines]

    old = closes[-40:-20]
    recent = closes[-20:]

    old_range = (
        (max(old) - min(old))
        / min(old)
        * 100
        if min(old) > 0
        else 999
    )

    recent_range = (
        (max(recent) - min(recent))
        / min(recent)
        * 100
        if min(recent) > 0
        else 999
    )

    if old_range <= 0:
        return False, 0, recent_range

    compression_ratio = recent_range / old_range

    if compression_ratio <= 0.65:
        return True, 2, recent_range

    if compression_ratio <= 0.80:
        return True, 1, recent_range

    return False, 0, recent_range


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(klines):
    if len(klines) < 50:
        return False, 0, []

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    current = closes[-1]

    previous_30 = closes[-50:-20]
    recent_20 = closes[-20:]

    previous_high = max(previous_30)
    recent_low = min(recent_20)
    recent_high = max(recent_20)

    if previous_high <= 0 or recent_low <= 0:
        return False, 0, []

    drawdown = (
        (recent_low - previous_high)
        / previous_high
    ) * 100

    recent_range = (
        (recent_high - recent_low)
        / recent_low
        * 100
    )

    old_volume = sum(volumes[-40:-20]) / 20
    recent_volume = sum(volumes[-10:]) / 10

    volume_holding = (
        old_volume > 0
        and recent_volume >= old_volume * 0.70
    )

    compression, compression_score, _ = (
        detect_range_compression(klines)
    )

    candle = candle_information(klines)

    conditions = 0
    reasons = []

    # -----------------------------------------------------
    # هبوط سابق
    # -----------------------------------------------------

    if drawdown <= -10:
        conditions += 2
        reasons.append("هبوط سابق قوي قبل التماسك")

    elif drawdown <= -6:
        conditions += 1
        reasons.append("هبوط سابق ثم بداية تماسك")

    # -----------------------------------------------------
    # تضييق النطاق
    # -----------------------------------------------------

    if compression:
        conditions += compression_score
        reasons.append("انكماش في نطاق الحركة")

    elif recent_range <= 18:
        conditions += 1
        reasons.append("النطاق السعري أصبح أضيق")

    # -----------------------------------------------------
    # الحجم
    # -----------------------------------------------------

    if volume_holding:
        conditions += 1
        reasons.append("الحجم لم يختفِ أثناء التماسك")

    # -----------------------------------------------------
    # رفض القاع
    # -----------------------------------------------------

    if candle["lower_wick_ratio"] >= 0.30:
        conditions += 1
        reasons.append("رفض سعري من منطقة القاع")

    # -----------------------------------------------------
    # السعر داخل الجزء السفلي من النطاق
    # -----------------------------------------------------

    if recent_high > recent_low:
        position = (
            (current - recent_low)
            / (recent_high - recent_low)
        )

        if position <= 0.65:
            conditions += 1
            reasons.append("السعر ما زال في منطقة مبكرة")

    detected = conditions >= 3

    return detected, conditions, reasons


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(klines):
    if len(klines) < 35:
        return "NEUTRAL", 0, []

    closes = [float(k[4]) for k in klines]
    opens = [float(k[1]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    reasons = []

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    recent_volume = sum(volumes[-5:]) / 5
    previous_volume = sum(volumes[-15:-5]) / 10

    recent_price_change = percentage_change(
        closes[-6],
        closes[-1]
    )

    bullish_volume = 0.0
    bearish_volume = 0.0

    for i in range(
        max(0, len(klines) - 12),
        len(klines)
    ):
        if closes[i] > opens[i]:
            bullish_volume += volumes[i]

        elif closes[i] < opens[i]:
            bearish_volume += volumes[i]

    score = 0

    # -----------------------------------------------------
    # شراء تدريجي
    # -----------------------------------------------------

    if (
        bullish_volume > bearish_volume * 1.10
        and volume_ratio >= 1.05
    ):
        score += 2
        reasons.append(
            "الحجم الصاعد أكبر من الحجم الهابط"
        )

    if (
        previous_volume > 0
        and recent_volume > previous_volume * 1.08
        and recent_price_change > -2.5
    ):
        score += 2
        reasons.append(
            "الحجم يتحسن بدون انهيار سعري"
        )

    if (
        volume_ratio >= 1.15
        and recent_price_change > 0
        and recent_price_change < 6
    ):
        score += 2
        reasons.append(
            "ارتفاع تدريجي مع تحسن الحجم"
        )

    # -----------------------------------------------------
    # ضغط بيعي
    # -----------------------------------------------------

    if (
        bearish_volume > bullish_volume * 1.15
        and volume_ratio >= 1.05
    ):
        score -= 2
        reasons.append(
            "الحجم الهابط أكبر من الحجم الصاعد"
        )

    if (
        previous_volume > 0
        and recent_volume > previous_volume * 1.10
        and recent_price_change < -3
    ):
        score -= 2
        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
        )

    if (
        volume_ratio >= 1.20
        and recent_price_change < -2
    ):
        score -= 2
        reasons.append(
            "هبوط مع حجم مرتفع"
        )

    if score >= 3:
        return "INFLOW", score, reasons

    if score <= -3:
        return "OUTFLOW", score, reasons

    return "NEUTRAL", score, reasons


# =========================================================
# PRE-PUMP DETECTION
# =========================================================

def detect_pre_pump(klines):
    if len(klines) < 40:
        return False, 0, []

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    reasons = []
    score = 0

    change_5 = calculate_price_change(closes, 5)
    change_10 = calculate_price_change(closes, 10)
    change_20 = calculate_price_change(closes, 20)

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    compression, compression_score, _ = (
        detect_range_compression(klines)
    )

    # لا نريد Pump بالفعل
    if change_5 >= 10:
        return False, -5, ["العملة انفجرت بالفعل خلال آخر 5 شموع"]

    if change_10 >= 18:
        return False, -5, ["العملة ارتفعت بقوة خلال آخر 10 شموع"]

    # -----------------------------------------------------
    # حركة صغيرة + حجم يتحسن
    # -----------------------------------------------------

    if (
        volume_ratio >= 1.10
        and -3 <= change_5 <= 6
    ):
        score += 2
        reasons.append(
            "الحجم يتحسن قبل انفجار سعري واضح"
        )

    # -----------------------------------------------------
    # تماسك
    # -----------------------------------------------------

    if compression:
        score += compression_score
        reasons.append(
            "السعر في مرحلة ضغط/تماسك"
        )

    # -----------------------------------------------------
    # اتجاه متوسط الأجل
    # -----------------------------------------------------

    if change_20 <= -5:
        score += 2
        reasons.append(
            "كانت هابطة قبل بداية التماسك"
        )

    # -----------------------------------------------------
    # بداية تحسن
    # -----------------------------------------------------

    if (
        change_10 > change_20
        and change_5 > 0
    ):
        score += 2
        reasons.append(
            "الزخم يتحسن تدريجيًا"
        )

    return score >= 4, score, reasons


# =========================================================
# DISTRIBUTION / PUMP
# =========================================================

def detect_distribution(klines):
    if len(klines) < 30:
        return False, 0, []

    closes = [float(k[4]) for k in klines]
    opens = [float(k[1]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    reasons = []
    score = 0

    change_5 = calculate_price_change(closes, 5)
    change_10 = calculate_price_change(closes, 10)

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    candle = candle_information(klines)

    bearish_volume = 0.0
    bullish_volume = 0.0

    for i in range(
        max(0, len(klines) - 10),
        len(klines)
    ):
        if closes[i] > opens[i]:
            bullish_volume += volumes[i]
        elif closes[i] < opens[i]:
            bearish_volume += volumes[i]

    # Pump
    if change_5 >= 10:
        score += 3
        reasons.append(
            "ارتفاع سريع خلال آخر 5 شموع"
        )

    if change_10 >= 18:
        score += 3
        reasons.append(
            "ارتفاع قوي خلال آخر 10 شموع"
        )

    # تصريف
    if (
        volume_ratio >= 1.30
        and bearish_volume > bullish_volume * 1.20
    ):
        score += 3
        reasons.append(
            "حجم بيع قوي بعد ارتفاع"
        )

    if candle["upper_wick_ratio"] >= 0.45:
        score += 2
        reasons.append(
            "ذيول علوية كبيرة تشير إلى رفض سعري"
        )

    detected = score >= 4

    return detected, score, reasons


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def get_timeframe_data(symbol, interval):
    klines = get_binance_futures_klines(
        symbol,
        interval,
        120
    )

    if not klines:
        return {
            "trend": "UNKNOWN",
            "rsi": 50.0,
            "change": 0.0
        }

    closes = [float(k[4]) for k in klines]

    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    rsi = calculate_rsi(closes)

    change = calculate_price_change(
        closes,
        min(10, len(closes) - 1)
    )

    if (
        ema9 is None
        or ema20 is None
        or ema50 is None
    ):
        trend = "UNKNOWN"

    elif (
        ema9 > ema20 > ema50
        and closes[-1] > ema20
    ):
        trend = "LONG"

    elif (
        ema9 < ema20 < ema50
        and closes[-1] < ema20
    ):
        trend = "SHORT"

    else:
        trend = "NEUTRAL"

    return {
        "trend": trend,
        "rsi": rsi,
        "change": change
    }


def get_timeframe_trend(symbol, interval):
    data = get_timeframe_data(
        symbol,
        interval
    )

    return data["trend"]


# =========================================================
# SMART ROUND
# =========================================================

def smart_round(value):
    if value is None:
        return 0

    value = float(value)

    if value >= 1000:
        return round(value, 2)

    if value >= 100:
        return round(value, 3)

    if value >= 1:
        return round(value, 4)

    if value >= 0.1:
        return round(value, 5)

    if value >= 0.01:
        return round(value, 6)

    return round(value, 8)


# =========================================================
# COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):
    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):
        return None

    # -----------------------------------------------------
    # 1H هو الفريم الرئيسي للتحليل
    # -----------------------------------------------------

    klines_1h = get_binance_futures_klines(
        symbol,
        "1h",
        200
    )

    if not klines_1h:
        return None

    closes = [float(k[4]) for k in klines_1h]
    volumes = [float(k[5]) for k in klines_1h]

    current_price = closes[-1]

    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    if (
        ema9 is None
        or ema20 is None
        or ema50 is None
    ):
        return None

    rsi = calculate_rsi(closes)
    volume_ratio = calculate_volume_ratio(volumes)
    volume_trend = calculate_volume_trend(volumes)
    atr = calculate_atr(klines_1h)

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    # -----------------------------------------------------
    # TIMEFRAMES
    # -----------------------------------------------------

    tf_15m = get_timeframe_data(symbol, "15m")
    tf_1h = get_timeframe_data(symbol, "1h")
    tf_4h = get_timeframe_data(symbol, "4h")
    tf_1d = get_timeframe_data(symbol, "1d")

    trend_15m = tf_15m["trend"]
    trend_1h = tf_1h["trend"]
    trend_4h = tf_4h["trend"]
    trend_1d = tf_1d["trend"]

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    bottom_detected, bottom_score, bottom_reasons = (
        detect_bottom_accumulation(
            klines_1h
        )
    )

    liquidity_state, liquidity_score, liquidity_reasons = (
        detect_liquidity_flow(
            klines_1h
        )
    )

    pre_pump, pre_pump_score, pre_pump_reasons = (
        detect_pre_pump(
            klines_1h
        )
    )

    distribution, distribution_score, distribution_reasons = (
        detect_distribution(
            klines_1h
        )
    )

    drawdown = calculate_recent_drawdown(
        closes,
        50
    )

    recovery = calculate_recovery_from_low(
        closes,
        30
    )

    change_5 = calculate_price_change(
        closes,
        5
    )

    change_10 = calculate_price_change(
        closes,
        10
    )

    change_20 = calculate_price_change(
        closes,
        20
    )

    support_distance = (
        (current_price - support)
        / current_price * 100
        if current_price > 0
        else 0
    )

    resistance_distance = (
        (resistance - current_price)
        / current_price * 100
        if current_price > 0
        else 0
    )

    # =====================================================
    # NEW OPPORTUNITY SCORE
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # =====================================================
    # LONG: PRICE STRUCTURE
    # =====================================================

    # الاتجاه المتوسط
    if ema20 > ema50:
        long_score += 6
        analysis_lines.append(
            "الاتجاه المتوسط بدأ يتحسن"
        )

    # لا نعاقب العملة بقوة لو كانت EMA ما زالت سلبية
    # لأن هدفنا اصطيادها قبل البمب
    if ema9 > ema20:
        long_score += 5
        analysis_lines.append(
            "EMA9 بدأ يتحسن فوق EMA20"
        )

    elif ema9 > ema20 * 0.995:
        long_score += 3
        analysis_lines.append(
            "EMA9 يقترب من EMA20"
        )

    # =====================================================
    # RSI
    # =====================================================

    if 38 <= rsi <= 58:
        long_score += 7
        analysis_lines.append(
            "RSI في منطقة مناسبة لبداية ارتداد"
        )

    elif 30 <= rsi < 38:
        long_score += 9
        analysis_lines.append(
            "RSI منخفض مع إمكانية ارتداد"
        )

    elif 58 < rsi <= 65:
        long_score += 4

    elif rsi > 72:
        long_score -= 8
        analysis_lines.append(
            "RSI مرتفع؛ خطر مطاردة الحركة"
        )

    # =====================================================
    # PREVIOUS DUMP
    # =====================================================

    if drawdown <= -15:
        long_score += 10
        analysis_lines.append(
            "العملة تعرضت لهبوط قوي سابقًا"
        )

    elif drawdown <= -8:
        long_score += 7
        analysis_lines.append(
            "يوجد هبوط سابق قبل التماسك"
        )

    elif drawdown <= -5:
        long_score += 3

    # =====================================================
    # RECOVERY
    # =====================================================

    if 1 <= recovery <= 8:
        long_score += 7
        analysis_lines.append(
            "بداية تعافي من القاع بدون انفجار"
        )

    elif 8 < recovery < 15:
        long_score += 3

    # =====================================================
    # BOTTOM
    # =====================================================

    if bottom_detected:
        long_score += 15

        analysis_lines.append(
            "تم اكتشاف بنية قاع/تجميع"
        )

        for reason in bottom_reasons[:3]:
            analysis_lines.append(
                f"قاع: {reason}"
            )

    # =====================================================
    # PRE-PUMP
    # =====================================================

    if pre_pump:
        long_score += 15

        analysis_lines.append(
            "احتمال مرحلة ما قبل البمب"
        )

        for reason in pre_pump_reasons[:3]:
            analysis_lines.append(
                f"Pre-Pump: {reason}"
            )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liquidity_state == "INFLOW":
        long_score += 15

        analysis_lines.append(
            "دخول سيولة تدريجي محتمل"
        )

    elif liquidity_state == "OUTFLOW":
        long_score -= 18

        analysis_lines.append(
            "خروج سيولة واضح"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.10:
        if change_5 >= -2:
            long_score += 6
            analysis_lines.append(
                "الحجم أعلى من متوسطه بدون انهيار"
            )

    if volume_trend == "RISING":
        long_score += 5
        analysis_lines.append(
            "الحجم في اتجاه صاعد"
        )

    # =====================================================
    # SUPPORT
    # =====================================================

    if 0 < support_distance <= 5:
        long_score += 8
        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if 0 < support_distance <= 2:
        long_score += 5
        analysis_lines.append(
            "السعر قريب جدًا من الدعم"
        )

    # =====================================================
    # RESISTANCE
    # =====================================================

    if 0 < resistance_distance <= 5:
        long_score -= 4

    if 0 < resistance_distance <= 2:
        long_score -= 12
        analysis_lines.append(
            "المقاومة قريبة؛ لا تطارد الدخول"
        )

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    # لا نطلب أن تكون كل الفريمات LONG
    # لأن ذلك يناقض فكرة الدخول قبل البمب.

    if trend_15m == "LONG":
        long_score += 3

    if trend_1h == "LONG":
        long_score += 5

    if trend_4h == "LONG":
        long_score += 6

    if trend_1d == "LONG":
        long_score += 4

    # بداية تحسن على الفريمات
    if (
        trend_15m == "LONG"
        and trend_1h in ("LONG", "NEUTRAL")
    ):
        long_score += 3

    if (
        trend_4h == "NEUTRAL"
        and bottom_detected
    ):
        long_score += 4
        analysis_lines.append(
            "4H لم ينفجر بعد؛ مناسب لفكرة الدخول المبكر"
        )

    # =====================================================
    # PUMP PROTECTION
    # =====================================================

    if change_5 >= 8:
        long_score -= 18
        analysis_lines.append(
            "ارتفاع سريع؛ لا تطارد البمب"
        )

    if change_5 >= 12:
        long_score -= 30

    if change_10 >= 20:
        long_score -= 25

    # =====================================================
    # DISTRIBUTION PROTECTION
    # =====================================================

    if distribution:
        long_score -= 25

        analysis_lines.append(
            "احتمال تصريف/نهاية حركة"
        )

        for reason in distribution_reasons[:3]:
            analysis_lines.append(
                f"تحذير: {reason}"
            )

    # =====================================================
    # SHORT SCORE
    # =====================================================

    if ema9 < ema20:
        short_score += 7

    if ema20 < ema50:
        short_score += 7

    if rsi > 68:
        short_score += 7

    if liquidity_state == "OUTFLOW":
        short_score += 15

    if trend_4h == "SHORT":
        short_score += 10

    if trend_1d == "SHORT":
        short_score += 10

    if 0 < resistance_distance <= 4:
        short_score += 7

    if change_5 <= -6:
        short_score += 6

    # لا نطارد الانهيار
    if change_5 <= -10:
        short_score -= 20

    if change_10 <= -18:
        short_score -= 20

    # لو فيه تجميع وقاع، امنع الشورت
    if bottom_detected:
        short_score -= 10

    # لو فيه دخول سيولة
    if liquidity_state == "INFLOW":
        short_score -= 12

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    score_difference = abs(
        long_score - short_score
    )

    # =====================================================
    # EARLY LONG
    # =====================================================

    early_long_conditions = (
        long_score >= 48
        and bottom_detected
        and (
            liquidity_state == "INFLOW"
            or pre_pump
        )
        and not distribution
        and change_5 < 10
    )

    strong_long_conditions = (
        long_score >= 60
        and long_score > short_score + 8
        and not distribution
    )

    strong_short_conditions = (
        short_score >= 55
        and short_score > long_score + 8
        and not bottom_detected
        and liquidity_state != "INFLOW"
    )

    if early_long_conditions:

        direction = "EARLY_LONG"
        score = long_score
        trend = "EARLY_UP"
        state = (
            "🟢 تجميع + تحسن سيولة + مراقبة ما قبل البمب"
        )

    elif strong_long_conditions:

        direction = "LONG"
        score = long_score
        trend = "UP"
        state = (
            "🟢 ميل صاعد + تأكيد جيد"
        )

    elif strong_short_conditions:

        direction = "SHORT"
        score = short_score
        trend = "DOWN"

        if distribution:
            state = "🔴 تصريف + مراقبة الشورت"
        else:
            state = "🔴 ضغط بيعي + مراقبة الشورت"

    else:

        direction = "WAIT"
        score = max(
            long_score,
            short_score
        )
        trend = "NEUTRAL"

        if long_score > short_score:
            state = (
                "🟡 فرصة مبكرة تحتاج تأكيد"
            )
        else:
            state = (
                "🟡 انتظار اتجاه أوضح"
            )

    score = max(
        0,
        min(100, int(score))
    )

    # =====================================================
    # INVALID / WEAK
    # =====================================================

    if (
        direction == "EARLY_LONG"
        and score < 48
    ):
        direction = "WAIT"

    if (
        direction == "LONG"
        and score < 50
    ):
        direction = "WAIT"

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    if atr is None or atr <= 0:
        atr = current_price * 0.01

    if direction in ("LONG", "EARLY_LONG"):

        # في الدخول المبكر نريد منطقة وليس سعر مطاردة
        entry_min = max(
            support,
            current_price - atr * 0.50
        )

        entry_max = current_price

        # لا نجعل الدخول أقل من الدعم بشكل غير منطقي
        if entry_min > entry_max:
            entry_min = current_price - atr * 0.30

        stop_loss = min(
            support - atr * 0.30,
            current_price - atr * 1.25
        )

        risk = current_price - stop_loss

        if risk <= 0:
            risk = atr

        tp1 = current_price + risk * 1.2
        tp2 = current_price + risk * 2.2
        tp3 = current_price + risk * 3.5

        if resistance > current_price:

            tp1 = min(
                tp1,
                resistance
            )

            # إذا كانت المقاومة قريبة جدًا
            # لا نعطيها كهدف وهمي
            if tp1 <= current_price:
                tp1 = current_price + risk

    elif direction == "SHORT":

        entry_min = current_price

        entry_max = min(
            resistance,
            current_price + atr * 0.50
        )

        stop_loss = max(
            resistance + atr * 0.30,
            current_price + atr * 1.25
        )

        risk = stop_loss - current_price

        if risk <= 0:
            risk = atr

        tp1 = current_price - risk * 1.2
        tp2 = current_price - risk * 2.2
        tp3 = current_price - risk * 3.5

        if support < current_price:
            tp1 = max(
                tp1,
                support
            )

    else:

        entry_min = max(
            support,
            current_price - atr * 0.25
        )

        entry_max = min(
            resistance,
            current_price + atr * 0.25
        )

        stop_loss = current_price - atr

        risk = atr

        tp1 = current_price + risk
        tp2 = current_price + risk * 2
        tp3 = current_price + risk * 3

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    pressure = 50

    if liquidity_state == "INFLOW":
        pressure += 15

    elif liquidity_state == "OUTFLOW":
        pressure -= 15

    if bottom_detected:
        pressure += 10

    if pre_pump:
        pressure += 10

    if distribution:
        pressure -= 20

    if volume_ratio >= 1.20:
        pressure += 5

    buy_pressure = round(
        max(5, min(95, pressure)),
        1
    )

    # =====================================================
    # OPPORTUNITY TYPE
    # =====================================================

    if direction == "EARLY_LONG":
        opportunity_type = "PRE_PUMP"

    elif direction == "LONG":
        opportunity_type = "CONFIRMED_LONG"

    elif direction == "SHORT":
        opportunity_type = "SHORT"

    else:
        opportunity_type = "WAIT"

    # =====================================================
    # RETURN
    # =====================================================

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "state": state,
        "opportunity_type": opportunity_type,

        "price": smart_round(current_price),

        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "liquidity_state": liquidity_state,
        "liquidity_score": liquidity_score,

        "bottom_detected": bottom_detected,
        "bottom_score": bottom_score,

        "pre_pump": pre_pump,
        "pre_pump_score": pre_pump_score,

        "distribution": distribution,
        "distribution_score": distribution_score,

        "drawdown": drawdown,
        "recovery": recovery,

        "change_5": round(change_5, 2),
        "change_10": round(change_10, 2),
        "change_20": round(change_20, 2),

        "buy_pressure": buy_pressure,

        "trend": trend,

        "trend_15m": trend_15m,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "trend_1d": trend_1d,

        "entry_min": smart_round(entry_min),
        "entry_max": smart_round(entry_max),

        "stop_loss": smart_round(stop_loss),

        "tp1": smart_round(tp1),
        "tp2": smart_round(tp2),
        "tp3": smart_round(tp3),

        "support": smart_round(support),
        "resistance": smart_round(resistance),

        "support_distance": round(
            support_distance,
            2
        ),

        "resistance_distance": round(
            resistance_distance,
            2
        ),

        "analysis_lines": analysis_lines,

        "liquidity_reasons": liquidity_reasons,

        "bottom_reasons": bottom_reasons,

        "pre_pump_reasons": pre_pump_reasons,

        "distribution_reasons": distribution_reasons
    }


# =========================================================
# MARKET SYMBOL RANKING
# =========================================================

def get_top_futures_symbols(limit=60):
    symbols = get_futures_symbols()

    if not symbols:
        return []

    ticker_data = binance_get(
        "/fapi/v1/ticker/24hr"
    )

    if not ticker_data:
        return list(symbols)[:limit]

    candidates = []

    for item in ticker_data:

        symbol = item.get("symbol")

        if symbol not in symbols:
            continue

        try:
            quote_volume = float(
               
