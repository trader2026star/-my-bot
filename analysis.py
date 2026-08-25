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
    "User-Agent": "CryptoZeroReversal-BingX/4.0"
})

logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60

MIN_REQUEST_INTERVAL = 0.35

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

_KLINE_CACHE = {}

_RATE_LIMIT_UNTIL = 0

_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()

_LAST_REQUEST_TIME = 0


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):

    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    with _RATE_LOCK:

        if time.time() < _RATE_LIMIT_UNTIL:

            logger.warning(
                "BingX rate-limit protection active: %.0f sec",
                _RATE_LIMIT_UNTIL - time.time()
            )

            return None

    with _REQUEST_LOCK:

        wait = (
            MIN_REQUEST_INTERVAL
            - (time.time() - _LAST_REQUEST_TIME)
        )

        if wait > 0:
            time.sleep(wait)

        _LAST_REQUEST_TIME = time.time()

    try:

        response = SESSION.get(
            BINGX_URL + path,
            params=params,
            timeout=timeout
        )

        if response.status_code != 200:

            logger.warning(
                "BingX HTTP %s | %s",
                response.status_code,
                path
            )

            return None

        data = response.json()

        if not isinstance(data, dict):
            return None

        code = data.get("code")

        if code in (109429, 109400):

            logger.warning(
                "BingX rate limit: %s",
                data
            )

            retry_seconds = 180

            with _RATE_LOCK:

                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + retry_seconds
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

    text = (
        text
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )

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
        and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS
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

    return (
        normalize_symbol(symbol)
        in get_futures_symbols()
    )


# =========================================================
# KLINES
# =========================================================

def get_bingx_klines(
    symbol,
    interval="1h",
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

        if (
            now - cached_time
            < KLINE_CACHE_SECONDS
        ):
            return cached_data

    data = bingx_get(
        "/openApi/swap/v3/quote/klines",
        {
            "symbol": bingx_symbol(symbol),
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

    if len(result) < 30:
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
# PRICE
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
# CANDLE
# =========================================================

def candle_information(klines):

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
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(klines):

    if len(klines) < 40:

        return {
            "structure": "UNKNOWN",
            "bos": "NONE",
            "liquidity_zone": "NONE",
            "reasons": []
        }

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

    # Previous structure
    previous_high = max(
        highs[-30:-6]
    )

    previous_low = min(
        lows[-30:-6]
    )

    recent_high = max(
        highs[-6:]
    )

    recent_low = min(
        lows[-6:]
    )

    reasons = []

    bos = "NONE"

    structure = "MIXED"

    if current > previous_high:

        bos = "BULLISH_BOS"
        structure = "BULLISH"

        reasons.append(
            "تم كسر آخر هيكل مهم إلى الأعلى"
        )

    elif current < previous_low:

        bos = "BEARISH_BOS"
        structure = "BEARISH"

        reasons.append(
            "تم كسر آخر هيكل مهم إلى الأسفل"
        )

    else:

        # محاولة تحديد الهيكل بدون BOS
        first_half_high = max(
            highs[-20:-10]
        )

        second_half_high = max(
            highs[-10:]
        )

        first_half_low = min(
            lows[-20:-10]
        )

        second_half_low = min(
            lows[-10:]
        )

        if (
            second_half_high > first_half_high
            and
            second_half_low >= first_half_low
        ):

            structure = "BULLISH"

            reasons.append(
                "هيكل 1H يتحسن بدون BOS مؤكد"
            )

        elif (
            second_half_high <= first_half_high
            and
            second_half_low < first_half_low
        ):

            structure = "BEARISH"

            reasons.append(
                "هيكل 1H يضعف بدون BOS مؤكد"
            )

        else:

            structure = "MIXED"

            reasons.append(
                "لا يوجد هيكل اتجاهي مؤكد"
            )

    distance_low = (
        abs(current - recent_low)
        / current
        * 100
    )

    distance_high = (
        abs(recent_high - current)
        / current
        * 100
    )

    liquidity_zone = "NONE"

    if distance_low <= 1.0:

        liquidity_zone = "LOW_LIQUIDITY"

        reasons.append(
            "السعر قريب جداً من السيولة السفلية"
        )

    elif distance_high <= 1.0:

        liquidity_zone = "HIGH_LIQUIDITY"

        reasons.append(
            "السعر قريب جداً من السيولة العلوية"
        )

    return {
        "structure": structure,
        "bos": bos,
        "liquidity_zone": liquidity_zone,
        "reasons": reasons
    }


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(
    klines
):

    if len(klines) < 40:

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

    old = closes[-40:-20]

    recent = closes[-20:]

    old_high = max(old)

    recent_low = min(recent)
    recent_high = max(recent)

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
        sum(volumes[-40:-20])
        / 20
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

    if drawdown <= -5:

        score += 1

        reasons.append(
            "يوجد هبوط سابق"
        )

    if recent_range <= 18:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if (
        old_volume > 0
        and recent_volume >= old_volume * 0.70
    ):

        score += 1

        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if candle["lower_wick_ratio"] >= 0.30:

        score += 1

        reasons.append(
            "رفض سعري من الأسفل"
        )

    if recent_high > recent_low:

        position = (
            current - recent_low
        ) / (
            recent_high - recent_low
        )

        if position <= 0.75:

            score += 1

            reasons.append(
                "السعر ليس في قمة النطاق"
            )

    return (
        score >= 3,
        score,
        reasons
    )


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 30:

        return "NEUTRAL", 0, []

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
        max(0, len(klines) - 10),
        len(klines)
    ):

        if closes[i] > opens[i]:

            bullish_volume += volumes[i]

        elif closes[i] < opens[i]:

            bearish_volume += volumes[i]

    score = 0

    if (
        bullish_volume
        > bearish_volume * 1.15
        and volume_ratio >= 0.80
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أقوى"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and recent_change > -2
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن مع استقرار السعر"
        )

    if (
        bearish_volume
        > bullish_volume * 1.20
        and volume_ratio >= 0.80
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أكبر"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and recent_change < -2
    ):

        score -= 1

        reasons.append(
            "الحجم يرتفع مع ضغط بيعي"
        )

    if score >= 2:

        return "INFLOW", score, reasons

    if score <= -2:

        return "OUTFLOW", score, reasons

    return "NEUTRAL", score, reasons


# =========================================================
# TIMEFRAME TREND
# =========================================================

def calculate_timeframe_trend(
    klines
):

    if not klines:
        return "UNKNOWN"

    closes = [
        k[4]
        for k in klines
    ]

    ema9 = calculate_ema(
        closes,
        9
    )

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    if None in (
        ema9,
        ema20,
        ema50
    ):

        return "UNKNOWN"

    current = closes[-1]

    if (
        ema9 > ema20 > ema50
        and current > ema20
    ):

        return "LONG"

    if (
        ema9 < ema20 < ema50
        and current < ema20
    ):

        return "SHORT"

    return "NEUTRAL"


# =========================================================
# ROUND
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
# ENTRY VALIDATION
# =========================================================

def validate_long_entry(
    trend_4h,
    trend_1h,
    structure,
    liquidity_state,
    volume_ratio,
    volume_trend,
    rsi,
    resistance_distance,
    crash_detected
):

    reasons = []

    if trend_4h != "LONG":
        reasons.append(
            "4H ليس صاعداً"
        )

    if trend_1h == "SHORT":
        reasons.append(
            "1H هابط"
        )

    if structure["structure"] == "BEARISH":
        reasons.append(
            "هيكل 1H هابط"
        )

    if structure["bos"] == "BEARISH_BOS":
        reasons.append(
            "BOS هابط"
        )

    if liquidity_state != "INFLOW":
        reasons.append(
            "لا يوجد دخول سيولة مؤكد"
        )

    if volume_ratio < 0.80:
        reasons.append(
            "الحجم ضعيف"
        )

    if volume_trend == "FALLING":
        reasons.append(
            "الحجم يتراجع"
        )

    if rsi < 25:
        reasons.append(
            "RSI منخفض جداً"
        )

    if rsi > 72:
        reasons.append(
            "RSI مرتفع جداً"
        )

    if resistance_distance <= 0.20:
        reasons.append(
            "السعر قريب جداً من المقاومة"
        )

    if crash_detected:
        reasons.append(
            "حركة انهيار سريعة"
        )

    # -----------------------------------------------------
    # REQUIRED CORE CONDITIONS
    # -----------------------------------------------------

    core_ok = (
        trend_4h == "LONG"
        and trend_1h != "SHORT"
        and structure["structure"] != "BEARISH"
        and structure["bos"] != "BEARISH_BOS"
        and liquidity_state == "INFLOW"
        and volume_ratio >= 0.80
        and volume_trend != "FALLING"
        and not crash_detected
        and resistance_distance > 0.20
    )

    # -----------------------------------------------------
    # يجب وجود تأكيد هيكل أو BOS
    # -----------------------------------------------------

    structure_confirmation = (
        structure["bos"] == "BULLISH_BOS"
        or
        structure["structure"] == "BULLISH"
    )

    if not structure_confirmation:

        reasons.append(
            "لا يوجد تأكيد هيكل صاعد كافٍ"
        )

        core_ok = False

    return core_ok, reasons


def validate_short_entry(
    trend_4h,
    trend_1h,
    structure,
    liquidity_state,
    volume_ratio,
    volume_trend,
    rsi,
    support_distance,
    crash_detected
):

    reasons = []

    if trend_4h != "SHORT":
        reasons.append(
            "4H ليس هابطاً"
        )

    if trend_1h == "LONG":
        reasons.append(
            "1H صاعد"
        )

    if structure["structure"] == "BULLISH":
        reasons.append(
            "هيكل 1H صاعد"
        )

    if structure["bos"] == "BULLISH_BOS":
        reasons.append(
            "BOS صاعد"
        )

    if liquidity_state != "OUTFLOW":
        reasons.append(
            "لا يوجد خروج سيولة مؤكد"
        )

    if volume_ratio < 0.80:
        reasons.append(
            "الحجم ضعيف"
        )

    if volume_trend == "FALLING":
        reasons.append(
            "الحجم يتراجع"
        )

    if rsi < 30:
        reasons.append(
            "RSI منخفض — خطر البيع في القاع"
        )

    if rsi > 75:
        reasons.append(
            "RSI مرتفع جداً"
        )

    if support_distance <= 0.20:
        reasons.append(
            "السعر قريب جداً من الدعم"
        )

    if crash_detected:
        reasons.append(
            "حركة انهيار سريعة"
        )

    core_ok = (
        trend_4h == "SHORT"
        and trend_1h != "LONG"
        and structure["structure"] != "BULLISH"
        and structure["bos"] != "BULLISH_BOS"
        and liquidity_state == "OUTFLOW"
        and volume_ratio >= 0.80
        and volume_trend != "FALLING"
        and rsi >= 30
        and not crash_detected
        and support_distance > 0.20
    )

    structure_confirmation = (
        structure["bos"] == "BEARISH_BOS"
        or
        structure["structure"] == "BEARISH"
    )

    if not structure_confirmation:

        reasons.append(
            "لا يوجد تأكيد هيكل هابط كافٍ"
        )

        core_ok = False

    return core_ok, reasons


# =========================================================
# COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):

        logger.info(
            "Symbol not found: %s",
            symbol
        )

        return None

    # =====================================================
    # DATA
    # =====================================================

    klines_4h = get_bingx_klines(
        symbol,
        "4h",
        120
    )

    if not klines_4h:
        return None

    klines_1h = get_bingx_klines(
        symbol,
        "1h",
        200
    )

    if not klines_1h:
        return None

    closes = [
        k[4]
        for k in klines_1h
    ]

    volumes = [
        k[5]
        for k in klines_1h
    ]

    current = closes[-1]

    # =====================================================
    # TREND
    # =====================================================

    trend_4h = calculate_timeframe_trend(
        klines_4h
    )

    trend_1h = calculate_timeframe_trend(
        klines_1h
    )

    if trend_4h == "UNKNOWN":
        return None

    # =====================================================
    # INDICATORS
    # =====================================================

    ema9 = calculate_ema(
        closes,
        9
    )

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
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
        klines_1h
    )

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    structure = detect_market_structure(
        klines_1h
    )

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

    # =====================================================
    # DISTANCES
    # =====================================================

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

    drawdown = calculate_recent_drawdown(
        closes
    )

    recent_change_2 = percentage_change(
        closes[-3],
        current
    )

    recent_change_6 = percentage_change(
        closes[-7],
        current
    )

    # =====================================================
    # CRASH / PUMP
    # =====================================================

    crash_detected = (
        recent_change_2 <= -15
        or
        recent_change_6 <= -25
    )

    pump_detected = (
        recent_change_2 >= 15
        or
        recent_change_6 >= 25
    )

    # =====================================================
    # SCORES
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # =====================================================
    # 4H
    # =====================================================

    if trend_4h == "LONG":

        long_score += 30

        analysis_lines.append(
            "4H هو الاتجاه الرئيسي: صاعد"
        )

    elif trend_4h == "SHORT":

        short_score += 30

        analysis_lines.append(
            "4H هو الاتجاه الرئيسي: هابط"
        )

    else:

        analysis_lines.append(
            "4H محايد"
        )

    # =====================================================
    # STRUCTURE
    # =====================================================

    if structure["bos"] == "BULLISH_BOS":

        long_score += 25

        analysis_lines.append(
            "BOS صاعد على 1H"
        )

    elif structure["bos"] == "BEARISH_BOS":

        short_score += 25

        analysis_lines.append(
            "BOS هابط على 1H"
        )

    if structure["structure"] == "BULLISH":

        long_score += 10

    elif structure["structure"] == "BEARISH":

        short_score += 10

    # =====================================================
    # EMA — عامل مساعد فقط
    # =====================================================

    if ema9 > ema20:

        long_score += 5

        analysis_lines.append(
            "EMA9 فوق EMA20 على 1H"
        )

    elif ema9 < ema20:

        short_score += 5

        analysis_lines.append(
            "EMA9 أسفل EMA20 على 1H"
        )

    if ema20 > ema50:

        long_score += 3

    elif ema20 < ema50:

        short_score += 3

    # =====================================================
    # RSI — عامل مساعد فقط
    # =====================================================

    if trend_4h == "LONG":

        if 40 <= rsi <= 65:

            long_score += 5

            analysis_lines.append(
                "RSI في نطاق مناسب"
            )

        elif rsi > 75:

            long_score -= 10

            analysis_lines.append(
                "RSI مرتفع — خطر مطاردة الصعود"
            )

        elif rsi < 25:

            long_score -= 10

            analysis_lines.append(
                "RSI منخفض جداً — انتظار ارتداد"
            )

        else:

            analysis_lines.append(
                "RSI يحتاج تأكيد"
            )

    elif trend_4h == "SHORT":

        if 35 <= rsi <= 65:

            short_score += 5

        elif rsi < 30:

            short_score -= 20

            analysis_lines.append(
                "RSI منخفض — خطر البيع في القاع"
            )

        elif rsi > 75:

            short_score += 5

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if trend_4h == "LONG":

            long_score += 10

        elif trend_4h == "SHORT":

            short_score += 10

        analysis_lines.append(
            "الحجم مرتفع"
        )

    elif volume_ratio < 0.80:

        analysis_lines.append(
            "الحجم ضعيف"
        )

    if volume_trend == "RISING":

        if trend_4h == "LONG":

            long_score += 5

        elif trend_4h == "SHORT":

            short_score += 5

        analysis_lines.append(
            "الحجم يتحسن"
        )

    elif volume_trend == "FALLING":

        long_score -= 5
        short_score -= 5

        analysis_lines.append(
            "الحجم يتراجع"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liquidity_state == "INFLOW":

        long_score += 20

        analysis_lines.append(
            "دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 20

        analysis_lines.append(
            "خروج سيولة محتمل"
        )

    else:

        analysis_lines.append(
            "السيولة محايدة"
        )

    # =====================================================
    # BOTTOM
    # عامل مساعد فقط
    # =====================================================

    if bottom_detected:

        if trend_4h == "LONG":

            long_score += 5

        analysis_lines.append(
            "القاع/التجميع موجود كعامل مساعد فقط"
        )

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    if support_distance <= 1.0:

        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if resistance_distance <= 1.0:

        analysis_lines.append(
            "السعر قريب من المقاومة"
        )

    # =====================================================
    # CRASH
    # =====================================================

    if crash_detected:

        long_score -= 30
        short_score -= 30

        analysis_lines.append(
            "حركة انهيار سريعة"
        )

    if pump_detected:

        long_score -= 20

        analysis_lines.append(
            "ارتفاع سريع — لا تطارد البامب"
        )

    # =====================================================
    # STRICT ENTRY GATE
    # =====================================================

    long_ok, long_rejections = validate_long_entry(
        trend_4h,
        trend_1h,
        structure,
        liquidity_state,
        volume_ratio,
        volume_trend,
        rsi,
        resistance_distance,
        crash_detected
    )

    short_ok, short_rejections = validate_short_entry(
        trend_4h,
        trend_1h,
        structure,
        liquidity_state,
        volume_ratio,
        volume_trend,
        rsi,
        support_distance,
        crash_detected
    )

    # =====================================================
    # FINAL DECISION
    # =====================================================

    direction = "NO TRADE"

    trend = "NEUTRAL"

    state = "NO TRADE"

    score = 0

    rejection_reasons = []

    if trend_4h == "LONG":

        trend = "UP"

        if long_ok:

            direction = "LONG"

            score = max(
                0,
                min(
                    100,
                    long_score
                )
            )

            if (
                structure["bos"]
                == "BULLISH_BOS"
                and
                liquidity_state
                == "INFLOW"
            ):

                state = (
                    "4H صاعد + BOS صاعد + دخول سيولة"
                )

            else:

                state = (
                    "4H صاعد + تأكيد 1H"
                )

        else:

            direction = "NO TRADE"

            rejection_reasons = long_rejections

            if volume_ratio < 0.80:

                state = (
                    "NO TRADE - الحجم ضعيف"
                )

            elif volume_trend == "FALLING":

                state = (
                    "NO TRADE - الحجم يتراجع"
                )

            elif liquidity_state != "INFLOW":

                state = (
                    "NO TRADE - لا يوجد دخول سيولة"
                )

            elif structure["structure"] == "BEARISH":

                state = (
                    "NO TRADE - هيكل 1H هابط"
                )

            elif structure["bos"] != "BULLISH_BOS":

                state = (
                    "NO TRADE - لا يوجد تأكيد BOS صاعد"
                )

            else:

                state = (
                    "NO TRADE - شروط الدخول غير مكتملة"
                )

    elif trend_4h == "SHORT":

        trend = "DOWN"

        if short_ok:

            direction = "SHORT"

            score = max(
                0,
                min(
                    100,
                    short_score
                )
            )

            if (
                structure["bos"]
                == "BEARISH_BOS"
                and
                liquidity_state
                == "OUTFLOW"
            ):

                state = (
                    "4H هابط + BOS هابط + خروج سيولة"
                )

            else:

                state = (
                    "4H هابط + تأكيد 1H"
                )

        else:

            direction = "NO TRADE"

            rejection_reasons = short_rejections

            if rsi < 30:

                state = (
                    "NO TRADE - RSI منخفض وخطر البيع في القاع"
                )

            elif volume_ratio < 0.80:

                state = (
                    "NO TRADE - الحجم ضعيف"
                )

            elif volume_trend == "FALLING":

                state = (
                    "NO TRADE - الحجم يتراجع"
                )

            elif liquidity_state != "OUTFLOW":

                state = (
                    "NO TRADE - لا يوجد خروج سيولة"
                )

            elif structure["structure"] == "BULLISH":

                state = (
                    "NO TRADE - هيكل 1H صاعد"
                )

            elif structure["bos"] != "BEARISH_BOS":

                state = (
                    "NO TRADE - لا يوجد تأكيد BOS هابط"
                )

            else:

                state = (
                    "NO TRADE - شروط الدخول غير مكتملة"
                )

    else:

        direction = "NO TRADE"

        trend = "NEUTRAL"

        state = (
            "NO TRADE - 4H محايد"
        )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    entry_min = None
    entry_max = None
    stop_loss = None
    tp1 = None
    tp2 = None
    tp3 = None

    if not atr or atr <= 0:

        atr = current * 0.01

    # =====================================================
    # LONG LEVELS
    # =====================================================

    if direction == "LONG":

        entry_min = max(
            support,
            current - atr * 0.35
        )

        entry_max = min(
            current,
            resistance - atr * 0.10
        )

        if entry_min >= entry_max:

            direction = "NO TRADE"

            score = 0

            state = (
                "NO TRADE - منطقة الدخول غير صالحة"
            )

            rejection_reasons.append(
                "لا توجد منطقة دخول LONG صالحة"
            )

        else:

            stop_loss = min(
                support - atr * 0.35,
                current - atr * 1.10
            )

            risk = (
                current
                - stop_loss
            )

            if risk <= 0:

                direction = "NO TRADE"

                score = 0

                state = (
                    "NO TRADE - Stop Loss غير صالح"
                )

            else:

                tp1 = current + risk * 1.2
                tp2 = current + risk * 2.0
                tp3 = current + risk * 3.0

                if resistance > current:

                    tp1 = min(
                        tp1,
                        resistance
                    )

    # =====================================================
    # SHORT LEVELS
    # =====================================================

    elif direction == "SHORT":

        entry_min = max(
            current,
            support + atr * 0.10
        )

        entry_max = min(
            resistance,
            current + atr * 0.35
        )

        if entry_min >= entry_max:

            direction = "NO TRADE"

            score = 0

            state = (
                "NO TRADE - منطقة الدخول غير صالحة"
            )

            rejection_reasons.append(
                "لا توجد منطقة دخول SHORT صالحة"
            )

        else:

            stop_loss = max(
                resistance + atr * 0.35,
                current + atr * 1.10
            )

            risk = (
                stop_loss
                - current
            )

            if risk <= 0:

                direction = "NO TRADE"

                score = 0

                state = (
                    "NO TRADE - Stop Loss غير صالح"
                )

            else:

                tp1 = current - risk * 1.2
                tp2 = current - risk * 2.0
                tp3 = current - risk * 3.0

                if support < current:

                    tp1 = max(
                        tp1,
                        support
                    )

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liquidity_state == "INFLOW":

        buy_pressure = (
            60
            + min(
                volume_ratio * 6,
                30
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            40
            - min(
                volume_ratio * 4,
                25
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
    # NO TRADE SCORE MUST BE ZERO
    # =====================================================

    if direction == "NO TRADE":

        score = 0

        entry_min = None
        entry_max = None
        stop_loss = None
        tp1 = None
        tp2 = None
        tp3 = None

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "symbol": symbol,

        "direction": direction,

        "score": int(
            max(
                0,
                min(
                    100,
                    score
                )
            )
        ),

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

        "trend_4h":
            trend_4h,

        "trend_1h":
            trend_1h,

        "structure":
            structure["structure"],

        "bos":
            structure["bos"],

        "liquidity_zone":
            structure["liquidity_zone"],

        "recent_change_2":
            round(
                recent_change_2,
                2
            ),

        "recent_change_6":
            round(
                recent_change_6,
                2
            ),

        "crash_detected":
            crash_detected,

        "pump_detected":
            pump_detected,

        "entry_min":
            smart_round(entry_min)
            if entry_min is not None
            else None,

        "entry_max":
            smart_round(entry_max)
            if entry_max is not None
            else None,

        "stop_loss":
            smart_round(stop_loss)
            if stop_loss is not None
            else None,

        "tp1":
            smart_round(tp1)
            if tp1 is not None
            else None,

        "tp2":
            smart_round(tp2)
            if tp2 is not None
            else None,

        "tp3":
            smart_round(tp3)
            if tp3 is not None
            else None,

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

        "long_score":
            int(
                max(
                    0,
                    min(
                        100,
                        long_score
                    )
                )
            ),

        "short_score":
            int(
                max(
                    0,
                    min(
                        100,
                        short_score
                    )
                )
            ),

        "analysis_lines":
            analysis_lines,

        "liquidity_reasons":
            liquidity_reasons,

        "bottom_reasons":
            bottom_reasons,

        "structure_reasons":
            structure["reasons"],

        "rejection_reasons":
            rejection_reasons
    }


# =========================================================
# TOP SYMBOLS
# =========================================================

def get_top_futures_symbols(
    limit=30
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

            activity_score = (
                volume
                * (
                    1
                    + min(
                        change / 100,
                        0.30
                    )
                )
            )

            candidates.append(
                (
                    symbol,
                    activity_score
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
        for symbol, _
        in candidates[:limit]
    ]


# =========================================================
# SCANNER
# =========================================================

def scan_market(
    limit=5
):

    symbols = get_top_futures_symbols(
        30
    )

    if not symbols:
        return []

    results = []

    for symbol in symbols:

        if time.time() < _RATE_LIMIT_UNTIL:
            break

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:
                continue

            # =================================================
            # NO TRADE
            # =================================================

            if data["direction"] == "NO TRADE":
                continue

            # =================================================
            # 4H MUST MATCH
            # =================================================

            if (
                data["direction"]
                == "LONG"
                and
                data["trend_4h"]
                != "LONG"
            ):
                continue

            if (
                data["direction"]
                == "SHORT"
                and
                data["trend_4h"]
                != "SHORT"
            ):
                continue

            # =================================================
            # LONG FINAL SAFETY
            # =================================================

            if data["direction"] == "LONG":

                if data["liquidity_state"] != "INFLOW":
                    continue

                if data["volume_ratio"] < 0.80:
                    continue

                if data["volume_trend"] == "FALLING":
                    continue

                if data["trend_1h"] == "SHORT":
                    continue

                if data["structure"] == "BEARISH":
                    continue

                if data["bos"] == "BEARISH_BOS":
                    continue

                if data["resistance_distance"] <= 0.20:
                    continue

                if data["crash_detected"]:
                    continue

                if data["score"] < 60:
                    continue

            # =================================================
            # SHORT FINAL SAFETY
            # =================================================

            elif data["direction"] == "SHORT":

                if data["liquidity_state"] != "OUTFLOW":
                    continue

                if data["volume_ratio"] < 0.80:
                    continue

                if data["volume_trend"] == "FALLING":
                    continue

                if data["trend_1h"] == "LONG":
                    continue

                if data["structure"] == "BULLISH":
                    continue

                if data["bos"] == "BULLISH_BOS":
                    continue

                if data["support_distance"] <= 0.20:
                    continue

                if data["rsi"] < 30:
                    continue

                if data["crash_detected"]:
                    continue

                if data["score"] < 60:
                    continue

            else:

                continue

            results.append(data)

        except Exception as exc:

            logger.exception(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        time.sleep(0.40)

    # =====================================================
    # RANK
    # =====================================================

    results.sort(
        key=lambda x: (
            x["score"],

            1 if x["bos"]
            in (
                "BULLISH_BOS",
                "BEARISH_BOS"
            )
            else 0,

            1 if x["liquidity_state"]
            in (
                "INFLOW",
                "OUTFLOW"
            )
            else 0,

            x["buy_pressure"]
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

    direction = data["direction"]

    if direction == "LONG":
        emoji = "🟢"

    elif direction == "SHORT":
        emoji = "🔴"

    else:
        emoji = "🟡"

    if data["liquidity_state"] == "INFLOW":
        liquidity = "🟢 دخول سيولة محتمل"

    elif data["liquidity_state"] == "OUTFLOW":
        liquidity = "🔴 خروج سيولة محتمل"

    else:
        liquidity = "🟡 سيولة محايدة"

    if data["bos"] == "BULLISH_BOS":
        bos_text = "🟢 BULLISH"

    elif data["bos"] == "BEARISH_BOS":
        bos_text = "🔴 BEARISH"

    else:
        bos_text = "⚪ NONE"

    if data["bottom_detected"]:

        bottom = (
            "🟢 نعم — لكن ليس سبباً منفرداً للدخول"
        )

    else:

        bottom = (
            "🟡 تجميع/قاع محتمل — غير مؤكد"
        )

    # =====================================================
    # ENTRY
    # =====================================================

    if direction in ("LONG", "SHORT"):

        entry_text = (
            f"{data['entry_min']} - "
            f"{data['entry_max']}"
        )

        sl_text = str(
            data["stop_loss"]
        )

        tp1_text = str(
            data["tp1"]
        )

        tp2_text = str(
            data["tp2"]
        )

        tp3_text = str(
            data["tp3"]
        )

    else:

        entry_text = (
            "⏳ انتظار تأكيد 1H"
        )

        sl_text = "غير محدد"

        tp1_text = "غير محدد"
        tp2_text = "غير محدد"
        tp3_text = "غير محدد"

    # =====================================================
    # REPORT
    # =====================================================

    lines = [

        "🤖 BingX AI Scanner",

        "",

        f"💎 العملة: {data['symbol']}",

        f"📈 الاتجاه النهائي: {emoji} {direction}",

        f"⭐ Entry Score: {data['score']}/100",

        "",

        f"🧠 الحالة: {data['state']}",

        "",

        "📊 الاتجاه الرئيسي",

        f"4H: {data['trend_4h']}",

        "",

        "🔎 تأكيد الدخول - 1H",

        f"هيكل السوق: {data['structure']}",

        f"BOS: {bos_text}",

        f"💧 السيولة: {liquidity}",

        f"📊 Volume: {data['volume_ratio']}x",

        f"📈 Volume Trend: {data['volume_trend']}",

        f"💪 Buy Pressure: {data['buy_pressure']}%",

        f"📊 RSI: {data['rsi']}",

        "",

        f"🎯 القاع/التجميع: {bottom}",

        f"📉 الهبوط السابق: {data['drawdown']}%",

        f"⚡ حركة آخر شمعتين: {data['recent_change_2']}%",

        "",

        "🛡️ الدعم والمقاومة",

        f"🟢 Support: {data['support']}",

        f"🔴 Resistance: {data['resistance']}",

        f"📏 البعد عن الدعم: {data['support_distance']}%",

        f"📏 البعد عن المقاومة: {data['resistance_distance']}%",

        "",

        "📍 منطقة الدخول 1H",

        entry_text,

        "",

        f"🛑 Stop Loss: {sl_text}",

        "",

        "🎯 الأهداف",

        f"TP1: {tp1_text}",

        f"TP2: {tp2_text}",

        f"TP3: {tp3_text}",

        "",

        "📊 الحركة الأخيرة",

        f"آخر شمعتين تقريباً: {data['recent_change_2']}%",

        f"آخر 6 شموع تقريباً: {data['recent_change_6']}%",

        "",

        "🔍 أسباب القرار"
    ]

    for line in data["analysis_lines"][:10]:

        lines.append(
            f"• {line}"
        )

    if data["structure_reasons"]:

        lines.extend([
            "",
            "🏗️ أدلة هيكل السوق"
        ])

        for reason in data[
            "structure_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if data["liquidity_reasons"]:

        lines.extend([
            "",
            "💧 أدلة السيولة"
        ])

        for reason in data[
            "liquidity_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if data["bottom_reasons"]:

        lines.extend([
            "",
            "🎯 أدلة التجميع"
        ])

        for reason in data[
            "bottom_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    # =====================================================
    # REJECTION REASONS
    # =====================================================

    if (
        direction == "NO TRADE"
        and
        data.get("rejection_reasons")
    ):

        lines.extend([
            "",
            "🚫 لماذا لم يدخل؟"
        ])

        unique_reasons = []

        for reason in data[
            "rejection_reasons"
        ]:

            if reason not in unique_reasons:

                unique_reasons.append(
                    reason
                )

        for reason in unique_reasons[:5]:

            lines.append(
                f"• {reason}"
            )

    lines.extend([

        "",

        "⚠️ إشارة تحليلية وليست ضماناً للربح.",

        "⚠️ 4H يحدد الاتجاه الرئيسي.",

        "⚠️ 1H + الهيكل + السيولة + الحجم هي بوابة الدخول.",

        "⚠️ القاع وRSI وEMA عوامل مساعدة وليست أسباباً منفردة للدخول.",

        "⚠️ عند تضارب الاتجاه والهيكل والسيولة يتم رفض الصفقة."

    ])

    return "\n".join(lines)
