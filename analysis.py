import time
import logging
import threading
import requests


# =========================================================
# SETTINGS
# =========================================================

BINGX_URL = "https://open-api.bingx.com"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal-BingX-4H/3.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# CACHE
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 600


# key = (symbol, interval, limit)
_KLINE_CACHE = {}

# 4H candles لا تحتاج تحديث كل ثانية
KLINE_CACHE_SECONDS = 120


# =========================================================
# RATE LIMIT PROTECTION
# =========================================================

_RATE_LIMIT_UNTIL = 0

_RATE_LOCK = threading.Lock()

# تأخير بسيط بين طلبات BingX
REQUEST_DELAY = 0.40


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):

    global _RATE_LIMIT_UNTIL

    now = time.time()

    with _RATE_LOCK:

        if now < _RATE_LIMIT_UNTIL:

            logger.warning(
                "BingX rate-limit protection active. Retry in %.0f seconds",
                _RATE_LIMIT_UNTIL - now
            )

            return None

    try:

        response = SESSION.get(
            BINGX_URL + path,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:

            logger.warning(
                "BingX HTTP %s | %s | %s",
                response.status_code,
                path,
                response.text[:300]
            )

            return None

        data = response.json()

        if not isinstance(data, dict):
            return None

        code = data.get("code")

        # =====================================================
        # RATE LIMIT
        # =====================================================

        if code in (109429, 109400):

            logger.warning(
                "BingX rate/API error: %s",
                data
            )

            with _RATE_LOCK:

                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + 120
                )

            return None

        if code not in (0, None):

            logger.warning(
                "BingX API error: %s",
                data
            )

            return None

        return data

    except requests.RequestException as exc:

        logger.warning(
            "BingX request failed: %s",
            exc
        )

        return None

    except ValueError as exc:

        logger.warning(
            "Invalid BingX JSON: %s",
            exc
        )

        return None


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(text):

    text = str(text).strip().upper()

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("/", "")

    if text.endswith("USDT"):
        return text

    if text.endswith("USDC"):
        return text

    return text + "USDT"


def bingx_symbol(symbol):

    symbol = normalize_symbol(symbol)

    if symbol.endswith("USDT"):

        return symbol[:-4] + "-USDT"

    if symbol.endswith("USDC"):

        return symbol[:-4] + "-USDC"

    return symbol


# =========================================================
# SYMBOLS
# =========================================================

def get_futures_symbols(force_refresh=False):

    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    now = time.time()

    if (
        not force_refresh
        and _SYMBOL_CACHE
        and now - _SYMBOL_CACHE_TIME
        < SYMBOL_CACHE_SECONDS
    ):

        return set(_SYMBOL_CACHE)

    data = bingx_get(
        "/openApi/swap/v2/quote/contracts"
    )

    if not data:

        return set(_SYMBOL_CACHE)

    rows = data.get("data")

    if not isinstance(rows, list):

        return set(_SYMBOL_CACHE)

    symbols = set()

    for item in rows:

        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol")

        if not symbol:
            continue

        symbol = str(symbol).upper()

        if not symbol.endswith("-USDT"):
            continue

        status = item.get("status")

        if status not in (1, "1", None):
            continue

        symbols.add(
            symbol.replace("-", "")
        )

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

def get_bingx_klines(
    symbol,
    interval="4h",
    limit=200
):

    symbol = normalize_symbol(symbol)

    cache_key = (
        symbol,
        interval,
        limit
    )

    now = time.time()

    cached = _KLINE_CACHE.get(cache_key)

    if cached:

        cached_time, cached_data = cached

        if now - cached_time < KLINE_CACHE_SECONDS:

            return cached_data

    api_symbol = bingx_symbol(symbol)

    data = bingx_get(
        "/openApi/swap/v3/quote/klines",
        {
            "symbol": api_symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data:

        return None

    rows = data.get("data")

    if not isinstance(rows, list):

        return None

    result = []

    for k in rows:

        try:

            if isinstance(k, dict):

                result.append([
                    k.get("time"),
                    float(k.get("open")),
                    float(k.get("high")),
                    float(k.get("low")),
                    float(k.get("close")),
                    float(k.get("volume"))
                ])

            elif isinstance(k, list):

                if len(k) < 6:
                    continue

                result.append([
                    k[0],
                    float(k[1]),
                    float(k[2]),
                    float(k[3]),
                    float(k[4]),
                    float(k[5])
                ])

        except (
            TypeError,
            ValueError,
            IndexError
        ):

            continue

    if len(result) < 60:

        return None

    result.sort(
        key=lambda x: x[0]
    )

    _KLINE_CACHE[cache_key] = (
        now,
        result
    )

    return result


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:

        return None

    multiplier = 2 / (period + 1)

    ema = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) < period + 1:

        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = (
            closes[i]
            - closes[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:

        return 100.0

    rs = avg_gain / avg_loss

    return round(
        100 - (
            100 / (1 + rs)
        ),
        2
    )


# =========================================================
# ATR
# =========================================================

def calculate_atr(
    klines,
    period=14
):

    if len(klines) < period + 1:

        return None

    trs = []

    for i in range(1, len(klines)):

        high = klines[i][2]
        low = klines[i][3]
        previous_close = klines[i - 1][4]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    atr = (
        sum(trs[:period])
        / period
    )

    for value in trs[period:]:

        atr = (
            atr * (period - 1)
            + value
        ) / period

    return atr


# =========================================================
# VOLUME
# =========================================================

def calculate_volume_ratio(
    volumes,
    period=20
):

    if len(volumes) < period + 1:

        return 1.0

    previous = volumes[
        -period - 1:-1
    ]

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:

        return 1.0

    return round(
        volumes[-1] / average,
        2
    )


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

    ratio = (
        short_avg
        / long_avg
    )

    if ratio >= 1.15:

        return "RISING"

    if ratio <= 0.85:

        return "FALLING"

    return "NEUTRAL"


# =========================================================
# PRICE CHANGE
# =========================================================

def percentage_change(
    old_price,
    new_price
):

    if old_price == 0:

        return 0.0

    return (
        (new_price - old_price)
        / old_price
    ) * 100


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    klines
):

    highs = [
        k[2]
        for k in klines
    ]

    lows = [
        k[3]
        for k in klines
    ]

    closes = [
        k[4]
        for k in klines
    ]

    current = closes[-1]

    lookback = min(
        80,
        len(klines)
    )

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    supports = [
        x
        for x in recent_lows
        if x < current
    ]

    resistances = [
        x
        for x in recent_highs
        if x > current
    ]

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

    return support, resistance


# =========================================================
# CANDLE INFORMATION
# =========================================================

def candle_information(
    klines
):

    k = klines[-1]

    open_price = k[1]
    high = k[2]
    low = k[3]
    close = k[4]

    candle_range = high - low

    if candle_range <= 0:

        return {
            "body_ratio": 0,
            "lower_wick_ratio": 0,
            "upper_wick_ratio": 0,
            "bullish": close > open_price,
            "bearish": close < open_price
        }

    body = abs(
        close - open_price
    )

    upper_wick = (
        high
        - max(
            open_price,
            close
        )
    )

    lower_wick = (
        min(
            open_price,
            close
        )
        - low
    )

    return {

        "body_ratio":
            body / candle_range,

        "lower_wick_ratio":
            lower_wick / candle_range,

        "upper_wick_ratio":
            upper_wick / candle_range,

        "bullish":
            close > open_price,

        "bearish":
            close < open_price
    }


# =========================================================
# DRAWDOWN
# =========================================================

def calculate_recent_drawdown(
    closes,
    lookback=50
):

    window = closes[-lookback:]

    if not window:

        return 0.0

    highest = max(window)

    if highest <= 0:

        return 0.0

    return round(
        (
            (closes[-1] - highest)
            / highest
        ) * 100,
        2
    )


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(
    klines
):

    if len(klines) < 60:

        return False, 0, []

    closes = [
        k[4]
        for k in klines
    ]

    volumes = [
        k[5]
        for k in klines
    ]

    current = closes[-1]

    old_window = closes[-50:-25]
    recent_window = closes[-25:]

    old_high = max(old_window)

    recent_low = min(recent_window)
    recent_high = max(recent_window)

    if old_high <= 0:

        return False, 0, []

    drawdown = (
        (recent_low - old_high)
        / old_high
    ) * 100

    recent_range = (
        (recent_high - recent_low)
        / recent_low
    ) * 100

    old_volume = (
        sum(volumes[-50:-25])
        / 25
    )

    recent_volume = (
        sum(volumes[-10:])
        / 10
    )

    candle = candle_information(
        klines
    )

    score = 0
    reasons = []

    # هبوط سابق حقيقي
    if drawdown <= -10:

        score += 2

        reasons.append(
            "هبوط سابق واضح بأكثر من 10%"
        )

    elif drawdown <= -7:

        score += 1

        reasons.append(
            "يوجد هبوط سابق"
        )

    # تضييق النطاق
    if recent_range <= 20:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    # الحجم لا يزال موجوداً
    if (
        old_volume > 0
        and recent_volume
        >= old_volume * 0.75
    ):

        score += 1

        reasons.append(
            "الحجم ما زال موجوداً أثناء التماسك"
        )

    # رفض من الأسفل
    if candle[
        "lower_wick_ratio"
    ] >= 0.30:

        score += 1

        reasons.append(
            "شمعة أخيرة تظهر رفضاً سعرياً من الأسفل"
        )

    # السعر ليس في قمة النطاق
    if recent_high > recent_low:

        position = (
            current - recent_low
        ) / (
            recent_high - recent_low
        )

        if position <= 0.70:

            score += 1

            reasons.append(
                "السعر ما زال في منطقة مبكرة"
            )

    # تأكيد بسيط أن القاع لم ينكسر
    if current >= recent_low:

        score += 1

        reasons.append(
            "السعر يحافظ على منطقة القاع الأخيرة"
        )

    return (
        score >= 4,
        score,
        reasons
    )


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 40:

        return (
            "NEUTRAL",
            0,
            []
        )

    opens = [
        k[1]
        for k in klines
    ]

    closes = [
        k[4]
        for k in klines
    ]

    volumes = [
        k[5]
        for k in klines
    ]

    reasons = []

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    recent_volume = (
        sum(volumes[-5:])
        / 5
    )

    previous_volume = (
        sum(volumes[-15:-5])
        / 10
    )

    recent_change = percentage_change(
        closes[-6],
        closes[-1]
    )

    bullish_volume = 0
    bearish_volume = 0

    for i in range(
        len(klines) - 10,
        len(klines)
    ):

        if closes[i] > opens[i]:

            bullish_volume += volumes[i]

        elif closes[i] < opens[i]:

            bearish_volume += volumes[i]

    score = 0

    # ============================================
    # BUYING PRESSURE
    # ============================================

    if (
        bullish_volume
        > bearish_volume * 1.20
        and volume_ratio >= 1.05
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أقوى من الهابطة"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change > -2
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن بدون ضغط هبوطي قوي"
        )

    # ============================================
    # SELLING PRESSURE
    # ============================================

    if (
        bearish_volume
        > bullish_volume * 1.20
        and volume_ratio >= 1.05
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أقوى"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change < -3
    ):

        score -= 1

        reasons.append(
            "الحجم يرتفع مع ضغط بيعي"
        )

    if score >= 2:

        return (
            "INFLOW",
            score,
            reasons
        )

    if score <= -2:

        return (
            "OUTFLOW",
            score,
            reasons
        )

    return (
        "NEUTRAL",
        score,
        reasons
    )


# =========================================================
# 4H TREND
# =========================================================

def calculate_4h_structure(
    klines
):

    if len(klines) < 60:

        return {
            "trend": "UNKNOWN",
            "ema20": None,
            "ema50": None,
            "ema200": None,
            "structure_score": 0,
            "reasons": []
        }

    closes = [
        k[4]
        for k in klines
    ]

    current = closes[-1]

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    # 200 قد لا تكون متاحة إذا BingX رجع أقل من 200
    if ema200 is None:

        ema200 = calculate_ema(
            closes,
            min(100, len(closes))
        )

    score = 0
    reasons = []

    # =====================================================
    # LONG STRUCTURE
    # =====================================================

    if (
        ema20
        and ema50
        and current > ema20
        and ema20 > ema50
    ):

        score += 3

        reasons.append(
            "هيكل 4H صاعد: السعر فوق EMA20 و EMA20 فوق EMA50"
        )

    elif (
        ema20
        and ema50
        and current > ema20
    ):

        score += 1

        reasons.append(
            "السعر فوق EMA20 على 4H"
        )

    # =====================================================
    # SHORT STRUCTURE
    # =====================================================

    if (
        ema20
        and ema50
        and current < ema20
        and ema20 < ema50
    ):

        score -= 3

        reasons.append(
            "هيكل 4H هابط"
        )

    elif (
        ema20
        and current < ema20
    ):

        score -= 1

        reasons.append(
            "السعر تحت EMA20 على 4H"
        )

    # =====================================================
    # TREND LABEL
    # =====================================================

    if score >= 3:

        trend = "LONG"

    elif score <= -3:

        trend = "SHORT"

    else:

        trend = "NEUTRAL"

    return {

        "trend": trend,

        "ema20": ema20,

        "ema50": ema50,

        "ema200": ema200,

        "structure_score": score,

        "reasons": reasons
    }


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
# COIN ANALYSIS - 4H ONLY
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):

        logger.info(
            "Symbol not found on BingX: %s",
            symbol
        )

        return None

    # =====================================================
    # 4H ONLY
    # =====================================================

    klines = get_bingx_klines(
        symbol,
        "4h",
        200
    )

    if not klines:

        return None

    closes = [
        k[4]
        for k in klines
    ]

    volumes = [
        k[5]
        for k in klines
    ]

    current = closes[-1]

    # =====================================================
    # INDICATORS
    # =====================================================

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    rsi = calculate_rsi(
        closes
    )

    volume_ratio = calculate_volume_ratio(
        volumes
    )

    volume_trend = calculate_volume_trend(
        volumes
    )

    atr = calculate_atr(
        klines
    )

    support, resistance = (
        calculate_support_resistance(
            klines
        )
    )

    structure = calculate_4h_structure(
        klines
    )

    trend_4h = structure["trend"]

    bottom_detected, bottom_score, bottom_reasons = (
        detect_bottom_accumulation(
            klines
        )
    )

    liquidity_state, liquidity_score, liquidity_reasons = (
        detect_liquidity_flow(
            klines
        )
    )

    drawdown = calculate_recent_drawdown(
        closes
    )

    # =====================================================
    # DISTANCES
    # =====================================================

    if current <= 0:

        return None

    support_distance = (
        abs(current - support)
        / current
        * 100
    )

    resistance_distance = (
        abs(resistance - current)
        / current
        * 100
    )

    # =====================================================
    # RECENT PRICE MOVEMENT
    # =====================================================

    change_1_candle = percentage_change(
        closes[-2],
        current
    )

    change_3_candles = percentage_change(
        closes[-4],
        current
    )

    change_6_candles = percentage_change(
        closes[-7],
        current
    )

    # =====================================================
    # SCORING
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # =====================================================
    # 1 - 4H STRUCTURE
    # =====================================================

    if trend_4h == "LONG":

        long_score += 25

        analysis_lines.extend(
            structure["reasons"]
        )

    elif trend_4h == "SHORT":

        short_score += 25

        analysis_lines.extend(
            structure["reasons"]
        )

    else:

        analysis_lines.append(
            "اتجاه 4H غير مؤكد"
        )

    # =====================================================
    # 2 - EMA200
    # =====================================================

    if ema200:

        if current > ema200:

            long_score += 8

            analysis_lines.append(
                "السعر فوق EMA200"
            )

        else:

            short_score += 8

            analysis_lines.append(
                "السعر تحت EMA200"
            )

    # =====================================================
    # 3 - RSI
    # =====================================================

    if 42 <= rsi <= 60:

        long_score += 10

        analysis_lines.append(
            "RSI 4H في منطقة مناسبة لبداية حركة صاعدة"
        )

    elif 35 <= rsi < 42:

        long_score += 6

        analysis_lines.append(
            "RSI منخفض نسبيًا مع إمكانية تحسن الزخم"
        )

    elif 60 < rsi <= 68:

        long_score += 4

        analysis_lines.append(
            "RSI إيجابي بدون تشبع واضح"
        )

    elif rsi < 30:

        # لا نعطيه LONG كبير تلقائياً
        # لأن RSI المنخفض ممكن يكون بسبب انهيار مستمر
        long_score += 2

        analysis_lines.append(
            "RSI منخفض جدًا؛ يحتاج تأكيد قبل الدخول"
        )

    elif rsi >= 72:

        short_score += 12

        analysis_lines.append(
            "RSI 4H مرتفع جدًا"
        )

    # =====================================================
    # 4 - VOLUME
    # =====================================================

    if volume_ratio >= 1.15:

        if (
            trend_4h == "LONG"
            or liquidity_state == "INFLOW"
        ):

            long_score += 10

            analysis_lines.append(
                "الحجم أعلى من متوسطه مع تحسن الطلب"
            )

        elif trend_4h == "SHORT":

            short_score += 8

            analysis_lines.append(
                "الحجم مرتفع مع اتجاه هابط"
            )

    elif volume_ratio < 0.70:

        analysis_lines.append(
            "الحجم ضعيف؛ التأكيد غير كافٍ"
        )

    if volume_trend == "RISING":

        if trend_4h == "LONG":

            long_score += 5

        elif trend_4h == "SHORT":

            short_score += 5

    # =====================================================
    # 5 - LIQUIDITY
    # =====================================================

    if liquidity_state == "INFLOW":

        long_score += 15

        analysis_lines.append(
            "هناك دلائل على دخول سيولة"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 15

        analysis_lines.append(
            "هناك دلائل على خروج سيولة"
        )

    # =====================================================
    # 6 - BOTTOM
    # =====================================================

    if bottom_detected:

        long_score += 15

        analysis_lines.append(
            "تم رصد بنية قاع/تجميع محتملة على 4H"
        )

        for reason in bottom_reasons[:3]:

            analysis_lines.append(
                f"قاع: {reason}"
            )

    # =====================================================
    # 7 - SUPPORT
    # =====================================================

    if support_distance <= 4:

        long_score += 6

        analysis_lines.append(
            "السعر قريب من منطقة دعم"
        )

    if support_distance <= 1.5:

        long_score += 5

        analysis_lines.append(
            "السعر قريب جدًا من الدعم"
        )

    # =====================================================
    # 8 - RESISTANCE
    # =====================================================

    if resistance_distance <= 5:

        short_score += 5

    if resistance_distance <= 2:

        long_score -= 12

        analysis_lines.append(
            "السعر قريب جدًا من المقاومة؛ العائد المتوقع ضعيف"
        )

    # =====================================================
    # 9 - DO NOT CHASE PUMP
    # =====================================================

    if change_3_candles >= 10:

        long_score -= 18

        analysis_lines.append(
            "ارتفاع سريع خلال آخر شموع؛ ممنوع مطاردة الحركة"
        )

    elif change_3_candles >= 6:

        long_score -= 8

        analysis_lines.append(
            "الحركة الصاعدة أصبحت ممتدة"
        )

    # =====================================================
    # 10 - AVOID FALLING KNIFE
    # =====================================================

    if change_3_candles <= -12:

        long_score -= 12

        analysis_lines.append(
            "هبوط قوي جدًا؛ لا يتم شراء السقوط مباشرة"
        )

    # =====================================================
    # 11 - WEAK LONG FILTER
    # =====================================================

    # لو الاتجاه 4H هابط بشدة ولا توجد سيولة/قاع
    # لا نسمح بإشارة LONG لمجرد RSI أو Support

    if (
        trend_4h == "SHORT"
        and not bottom_detected
        and liquidity_state != "INFLOW"
    ):

        long_score -= 15

        analysis_lines.append(
            "الهيكل 4H هابط ولا يوجد تأكيد قاع أو سيولة"
        )

    # =====================================================
    # 12 - WEAK SHORT FILTER
    # =====================================================

    if (
        trend_4h == "LONG"
        and liquidity_state == "INFLOW"
    ):

        short_score -= 12

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    difference = abs(
        long_score - short_score
    )

    # =====================================================
    # HARD CONFIRMATION
    # =====================================================

    long_confirmed = (

        long_score >= 58

        and long_score > short_score

        and difference >= 10

        and (
            trend_4h == "LONG"
            or bottom_detected
            or liquidity_state == "INFLOW"
        )

        and resistance_distance > 2
    )

    short_confirmed = (

        short_score >= 60

        and short_score > long_score

        and difference >= 10

        and trend_4h == "SHORT"

        and liquidity_state == "OUTFLOW"
    )

    if long_confirmed:

        direction = "LONG"

        score = long_score

        trend = "UP"

        if (
            bottom_detected
            and liquidity_state == "INFLOW"
        ):

            state = (
                "قاع + تجميع + دخول سيولة محتمل"
            )

        elif bottom_detected:

            state = (
                "تجميع مبكر على 4H"
            )

        elif liquidity_state == "INFLOW":

            state = (
                "تحسن الطلب ودخول سيولة"
            )

        else:

            state = (
                "اتجاه 4H صاعد مع تأكيد"
            )

    elif short_confirmed:

        direction = "SHORT"

        score = short_score

        trend = "DOWN"

        state = (
            "اتجاه 4H هابط + خروج سيولة"
        )

    else:

        direction = "WAIT"

        score = max(
            long_score,
            short_score
        )

        trend = "NEUTRAL"

        state = (
            "انتظار تأكيد 4H"
        )

    # =====================================================
    # SCORE NORMALIZATION
    # =====================================================

    score = int(
        max(
            0,
            min(
                100,
                score
            )
        )
    )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    if not atr or atr <= 0:

        atr = current * 0.01

    # =====================================================
    # LONG
    # =====================================================

    if direction == "LONG":

        entry_min = max(
            support,
            current - atr * 0.35
        )

        entry_max = current

        stop_loss = min(
            support - atr * 0.35,
            current - atr * 1.2
        )

        risk = current - stop_loss

        if risk <= 0:

            risk = atr

        tp1 = current + risk * 1.2
        tp2 = current + risk * 2.2
        tp3 = current + risk * 3.5

        # لا نضع TP1 بعد مقاومة قريبة
        if resistance > current:

            tp1 = min(
                tp1,
                resistance
            )

    # =====================================================
    # SHORT
    # =====================================================

    elif direction == "SHORT":

        entry_min = current

        entry_max = min(
            resistance,
            current + atr * 0.35
        )

        stop_loss = max(
            resistance + atr * 0.35,
            current + atr * 1.2
        )

        risk = stop_loss - current

        if risk <= 0:

            risk = atr

        tp1 = current - risk * 1.2
        tp2 = current - risk * 2.2
        tp3 = current - risk * 3.5

        if support < current:

            tp1 = max(
                tp1,
                support
            )

    # =====================================================
    # WAIT
    # =====================================================

    else:

        entry_min = max(
            support,
            current - atr * 0.25
        )

        entry_max = min(
            resistance,
            current + atr * 0.25
        )

        stop_loss = current - atr

        tp1 = current + atr
        tp2 = current + atr * 2
        tp3 = current + atr * 3

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liquidity_state == "INFLOW":

        buy_pressure = (
            65
            + min(
                volume_ratio * 5,
                20
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            35
            - min(
                volume_ratio * 3,
                15
            )
        )

    else:

        buy_pressure = 50

    buy_pressure = round(
        max(
            5,
            min(
                95,
                buy_pressure
            )
        ),
        1
    )

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "symbol": symbol,

        "direction": direction,

        "score": score,

        "state": state,

        "price": smart_round(
            current
        ),

        "rsi": rsi,

        "volume_ratio": volume_ratio,

        "volume_trend": volume_trend,

        "liquidity_state":
            liquidity_state,

        "liquidity_score":
            liquidity_score,

        "bottom_detected":
            bottom_detected,

        "bottom_score":
            bottom_score,

        "drawdown":
            drawdown,

        "buy_pressure":
            buy_pressure,

        "trend":
            trend,

        # 4H فقط
        "trend_4h":
            trend_4h,

        "ema20":
            smart_round(ema20),

        "ema50":
            smart_round(ema50),

        "ema200":
            smart_round(ema200),

        "change_1_candle":
            round(
                change_1_candle,
                2
            ),

        "change_3_candles":
            round(
                change_3_candles,
                2
            ),

        "change_6_candles":
            round(
                change_6_candles,
                2
            ),

        "entry_min":
            smart_round(entry_min),

        "entry_max":
            smart_round(entry_max),

        "stop_loss":
            smart_round(stop_loss),

        "tp1":
            smart_round(tp1),

        "tp2":
            smart_round(tp2),

        "tp3":
            smart_round(tp3),

        "support":
            smart_round(support),

        "resistance":
            smart_round(resistance),

        "support_distance":
            round(
                support_distance,
                2
            ),

        "resistance_distance":
            round(
                resistance_distance,
                2
            ),

        "analysis_lines":
            analysis_lines,

        "liquidity_reasons":
            liquidity_reasons,

        "bottom_reasons":
            bottom_reasons
    }


# =========================================================
# TOP SYMBOLS
# =========================================================

def get_top_futures_symbols(
    limit=15
):

    symbols = get_futures_symbols()

    if not symbols:

        return []

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker"
    )

    if not data:

        return list(symbols)[:limit]

    rows = data.get("data")

    if not isinstance(rows, list):

        return list(symbols)[:limit]

    candidates = []

    for item in rows:

        if not isinstance(item, dict):

            continue

        raw_symbol = item.get(
            "symbol"
        )

        if not raw_symbol:

            continue

        symbol = str(
            raw_symbol
        ).replace(
            "-",
            ""
        ).upper()

        if symbol not in symbols:

            continue

        try:

            volume = float(
                item.get(
                    "quoteVolume",
                    item.get(
                        "volume",
                        0
                    )
                )
            )

            change = abs(
                float(
                    item.get(
                        "priceChangePercent",
                        0
                    )
                )
            )

            score = (
                volume
                * (
                    1
                    + min(
                        change / 100,
                        0.20
                    )
                )
            )

            candidates.append(
                (
                    symbol,
                    score
                )
            )

        except (
            TypeError,
            ValueError
        ):

            continue

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return [
        symbol
        for symbol, _ in
        candidates[:limit]
    ]


# =========================================================
# SCANNER
# =========================================================

def scan_market(
    limit=5
):

    # =====================================================
    # فقط 15 عملة
    # =====================================================

    symbols = get_top_futures_symbols(
        15
    )

    if not symbols:

        return []

    results = []

    for symbol in symbols:

        if time.time() < _RATE_LIMIT_UNTIL:

            logger.warning(
                "Stopping scanner because BingX rate limit is active."
            )

            break

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:

                continue

            if data["direction"] == "WAIT":

                continue

            # =================================================
            # CONFIRMED LONG
            # =================================================

            strong_long = (
                data["direction"] == "LONG"
                and data["score"] >= 58
            )

            # =================================================
            # EARLY LONG
            # =================================================

            early_long = (
                data["direction"] == "LONG"
                and data["score"] >= 55
                and (
                    data["bottom_detected"]
                    or
                    data["liquidity_state"]
                    == "INFLOW"
                )
            )

            # =================================================
            # CONFIRMED SHORT
            # =================================================

            strong_short = (
                data["direction"] == "SHORT"
                and data["score"] >= 60
                and data["liquidity_state"]
                == "OUTFLOW"
            )

            if not (
                strong_long
                or early_long
                or strong_short
            ):

                continue

            # =================================================
            # DO NOT CHASE LONG
            # =================================================

            if (
                data["direction"] == "LONG"
                and data["change_3_candles"] >= 10
            ):

                continue

            # =================================================
            # DO NOT BUY TOO CLOSE TO RESISTANCE
            # =================================================

            if (
                data["direction"] == "LONG"
                and data["resistance_distance"] <= 2
            ):

                continue

            # =================================================
            # DO NOT SHORT AGAINST 4H LONG
            # =================================================

            if (
                data["direction"] == "SHORT"
                and data["trend_4h"] != "SHORT"
            ):

                continue

            results.append(
                data
            )

        except Exception as exc:

            logger.exception(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        # حماية BingX
        time.sleep(
            REQUEST_DELAY
        )

    # =====================================================
    # RANK
    # =====================================================

    results.sort(
        key=lambda x: (
            x["score"],

            1
            if x["bottom_detected"]
            else 0,

            1
            if x["liquidity_state"]
            == "INFLOW"
            else 0,

            x["buy_pressure"],

            -x["resistance_distance"]
        ),
        reverse=True
    )

    return results[:limit]


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(
    data
):

    if data["direction"] == "LONG":

        emoji = "🟢"

    elif data["direction"] == "SHORT":

        emoji = "🔴"

    else:

        emoji = "🟡"

    if data["liquidity_state"] == "INFLOW":

        liquidity = "🟢 دخول سيولة"

    elif data["liquidity_state"] == "OUTFLOW":

        liquidity = "🔴 خروج سيولة"

    else:

        liquidity = "🟡 سيولة محايدة"

    bottom = (
        "🟢 قاع/تجميع محتمل"
        if data["bottom_detected"]
        else
        "⚪ لا يوجد تأكيد قاع كافٍ"
    )

    lines = [

        "🤖 BingX AI Scanner",

        "",

        f"💎 العملة: {data['symbol']}",

        f"📈 الاتجاه: {emoji} {data['direction']}",

        f"⭐ Score: {data['score']}/100",

        "",

        f"🧠 الحالة: {data['state']}",

        "",

        f"💰 السعر: {data['price']}",

        "",

        "📊 تحليل 4H",

        f"📈 الاتجاه 4H: {data['trend_4h']}",

        f"EMA20: {data['ema20']}",

        f"EMA50: {data['ema50']}",

        f"EMA200: {data['ema200']}",

        f"📊 RSI 4H: {data['rsi']}",

        f"📊 Volume: {data['volume_ratio']}x",

        f"📈 Volume Trend: {data['volume_trend']}",

        "",

        f"💧 السيولة: {liquidity}",

        f"💧 Buy Pressure: {data['buy_pressure']}%",

        "",

        f"🎯 القاع: {bottom}",

        f"📉 الهبوط السابق: {data['drawdown']}%",

        "",

        "📊 الحركة الأخيرة",

        f"آخر شمعة 4H: {data['change_1_candle']}%",

        f"آخر 3 شموع 4H: {data['change_3_candles']}%",

        f"آخر 6 شموع 4H: {data['change_6_candles']}%",

        "",

        "🛡️ الدعم والمقاومة",

        f"🟢 Support: {data['support']}",

        f"🔴 Resistance: {data['resistance']}",

        f"📏 البعد عن الدعم: {data['support_distance']}%",

        f"📏 البعد عن المقاومة: {data['resistance_distance']}%",

        "",

        "📍 منطقة الدخول",

        f"{data['entry_min']} - {data['entry_max']}",

        "",

        f"🛑 Stop Loss: {data['stop_loss']}",

        "",

        "🎯 الأهداف",

        f"TP1: {data['tp1']}",

        f"TP2: {data['tp2']}",

        f"TP3: {data['tp3']}",

        "",

        "🔍 إشارات التحليل"
    ]

    for line in data[
        "analysis_lines"
    ]:

        lines.append(
            f"• {line}"
        )

    if data[
        "liquidity_reasons"
    ]:

        lines.append("")
        lines.append(
            "💧 تفاصيل السيولة"
        )

        for reason in data[
            "liquidity_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if data[
        "bottom_reasons"
    ]:

        lines.append("")
        lines.append(
            "🎯 تفاصيل القاع"
        )

        for reason in data[
            "bottom_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    lines.extend([

        "",

        "⚠️ الإشارة تحليلية وليست ضمانًا للربح.",

        "⚠️ لا تطارد البمب؛ انتظر منطقة الدخول والتأكيد.",

        "⏱️ القرار مبني على فريم 4H فقط."

    ])

    return "\n".join(lines)
