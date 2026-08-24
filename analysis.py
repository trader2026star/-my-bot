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
    "User-Agent": "CryptoZeroReversal-BingX/2.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# CACHE
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 600


# KLINE CACHE
# key = (symbol, interval)
_KLINE_CACHE = {}

KLINE_CACHE_SECONDS = 45


# عند حدوث 109429 نوقف الطلبات مؤقتاً
_RATE_LIMIT_UNTIL = 0

_RATE_LOCK = threading.Lock()


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):

    global _RATE_LIMIT_UNTIL

    now = time.time()

    with _RATE_LOCK:

        if now < _RATE_LIMIT_UNTIL:

            logger.warning(
                "BingX rate-limit protection active. "
                "Retry in %.0f seconds",
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

        # =================================================
        # RATE LIMIT / INVALID REQUEST
        # =================================================

        if code in (109429, 109400):

            logger.warning(
                "BingX rate/API error: %s",
                data
            )

            # توقف 90 ثانية على الأقل
            # حتى لا نستمر في ضرب API
            with _RATE_LOCK:

                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + 90
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

        # BingX format:
        # BTC-USDT

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

    if len(result) < 20:
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

    ema = sum(
        values[:period]
    ) / period

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
# CANDLE
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
# BOTTOM
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

    if drawdown <= -8:

        score += 1

        reasons.append(
            "هبوط سابق واضح"
        )

    if recent_range <= 18:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if (
        old_volume > 0
        and recent_volume
        >= old_volume * 0.75
    ):

        score += 1

        reasons.append(
            "الحجم ما زال حاضرًا بعد الهبوط"
        )

    if candle[
        "lower_wick_ratio"
    ] >= 0.30:

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

        if position <= 0.70:

            score += 1

            reasons.append(
                "السعر ما زال في منطقة مبكرة"
            )

    return (
        score >= 3,
        score,
        reasons
    )


# =========================================================
# LIQUIDITY
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 30:

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

    volume_ratio = (
        calculate_volume_ratio(
            volumes,
            20
        )
    )

    recent_volume = (
        sum(volumes[-5:])
        / 5
    )

    previous_volume = (
        sum(volumes[-15:-5])
        / 10
    )

    recent_change = (
        percentage_change(
            closes[-6],
            closes[-1]
        )
    )

    bullish_volume = 0
    bearish_volume = 0

    for i in range(
        max(
            0,
            len(klines) - 10
        ),
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
        and volume_ratio >= 1.05
    ):

        score += 2

        reasons.append(
            "زيادة حجم الشموع الصاعدة"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change > -3
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن بدون هبوط حاد"
        )

    if (
        bearish_volume
        > bullish_volume * 1.20
        and volume_ratio >= 1.05
    ):

        score -= 2

        reasons.append(
            "زيادة حجم الشموع الهابطة"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change < -3
    ):

        score -= 1

        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
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

        logger.info(
            "Symbol not found on BingX: %s",
            symbol
        )

        return None

    # =====================================================
    # GET 1H
    # =====================================================

    klines_1h = get_bingx_klines(
        symbol,
        "1h",
        200
    )

    if not klines_1h:
        return None

    # =====================================================
    # GET OTHER TIMEFRAMES
    # =====================================================

    klines_15m = get_bingx_klines(
        symbol,
        "15m",
        100
    )

    klines_4h = get_bingx_klines(
        symbol,
        "4h",
        100
    )

    klines_1d = get_bingx_klines(
        symbol,
        "1d",
        100
    )

    closes = [
        k[4]
        for k in klines_1h
    ]

    volumes = [
        k[5]
        for k in klines_1h
    ]

    current = closes[-1]

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

        return None

    rsi = calculate_rsi(
        closes
    )

    volume_ratio = (
        calculate_volume_ratio(
            volumes
        )
    )

    volume_trend = (
        calculate_volume_trend(
            volumes
        )
    )

    atr = calculate_atr(
        klines_1h
    )

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    trend_15m = (
        calculate_timeframe_trend(
            klines_15m
        )
    )

    trend_1h = (
        calculate_timeframe_trend(
            klines_1h
        )
    )

    trend_4h = (
        calculate_timeframe_trend(
            klines_4h
        )
    )

    trend_1d = (
        calculate_timeframe_trend(
            klines_1d
        )
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

    drawdown = calculate_recent_drawdown(
        closes
    )

    support_distance = (
        abs(current - support)
        / current * 100
    )

    resistance_distance = (
        abs(resistance - current)
        / current * 100
    )

    # =====================================================
    # SCORING
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # EMA
    if ema9 > ema20:

        long_score += 8

        analysis_lines.append(
            "EMA9 أعلى من EMA20"
        )

    else:

        short_score += 8

    if ema20 > ema50:

        long_score += 8

    else:

        short_score += 8

    # RSI
    if 40 <= rsi <= 62:

        long_score += 8

        analysis_lines.append(
            "RSI في منطقة مناسبة لبداية ارتداد"
        )

    elif rsi < 35:

        long_score += 10

        analysis_lines.append(
            "RSI منخفض وقد توجد فرصة ارتداد"
        )

    elif rsi > 70:

        short_score += 10

        analysis_lines.append(
            "RSI مرتفع واحتمال تصحيح"
        )

    # Volume
    if volume_ratio >= 1.20:

        if ema9 >= ema20:

            long_score += 8

            analysis_lines.append(
                "حجم مرتفع مع تحسن سعري"
            )

        else:

            short_score += 8

    if volume_trend == "RISING":

        if ema9 >= ema20:

            long_score += 5

        else:

            short_score += 5

    # Liquidity
    if liquidity_state == "INFLOW":

        long_score += 15

        analysis_lines.append(
            "دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 15

        analysis_lines.append(
            "خروج سيولة محتمل"
        )

    # Bottom
    if bottom_detected:

        long_score += 15

        analysis_lines.append(
            "تم رصد بنية قاع/تجميع مبكرة"
        )

        for reason in bottom_reasons[:3]:

            analysis_lines.append(
                f"قاع: {reason}"
            )

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    weights = {
        "15m": 4,
        "1h": 7,
        "4h": 10,
        "1d": 8
    }

    timeframe_data = [
        ("15m", trend_15m),
        ("1h", trend_1h),
        ("4h", trend_4h),
        ("1d", trend_1d)
    ]

    for timeframe, trend in timeframe_data:

        if trend == "LONG":

            long_score += weights[
                timeframe
            ]

        elif trend == "SHORT":

            short_score += weights[
                timeframe
            ]

    # Support
    if support_distance <= 4:

        long_score += 8

        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if support_distance <= 1.5:

        long_score += 5

        analysis_lines.append(
            "السعر قريب جدًا من الدعم"
        )

    # Resistance
    if resistance_distance <= 4:

        short_score += 6

    if resistance_distance <= 1.5:

        long_score -= 15

        analysis_lines.append(
            "السعر قريب جدًا من المقاومة"
        )

    # Recent move
    recent_change = percentage_change(
        closes[-6],
        current
    )

    if recent_change >= 8:

        long_score -= 20

        analysis_lines.append(
            "ارتفاع سريع؛ تجنب مطاردة البمب"
        )

    if recent_change <= -8:

        short_score -= 15

        analysis_lines.append(
            "هبوط سريع؛ تجنب مطاردة الشورت"
        )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    difference = abs(
        long_score - short_score
    )

    if difference < 6:

        direction = "WAIT"

        score = max(
            long_score,
            short_score
        )

        state = "انتظار تأكيد"

        trend = "NEUTRAL"

    elif long_score > short_score:

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
                "تجميع مبكر + مراقبة الدخول"
            )

        else:

            state = (
                "ميل صاعد + مراقبة الدخول"
            )

    else:

        direction = "SHORT"

        score = short_score

        trend = "DOWN"

        if liquidity_state == "OUTFLOW":

            state = (
                "تصريف + خروج سيولة محتمل"
            )

        else:

            state = (
                "ميل هابط + مراقبة الشورت"
            )

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

        if resistance > current:

            tp1 = min(
                tp1,
                resistance
            )

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

        "trend_15m":
            trend_15m,

        "trend_1h":
            trend_1h,

        "trend_4h":
            trend_4h,

        "trend_1d":
            trend_1d,

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
    limit=20
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
                        0.25
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

    # بدل 60 عملة
    # نبدأ بـ 20 فقط
    symbols = get_top_futures_symbols(
        20
    )

    if not symbols:

        return []

    results = []

    for symbol in symbols:

        # لو BingX دخل rate limit
        # نوقف الفحص فوراً
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
            # PRE-PUMP
            # =================================================

            recent_state = (
                data["bottom_detected"]
                or
                data["liquidity_state"]
                == "INFLOW"
            )

            strong_long = (
                data["direction"]
                == "LONG"
                and
                data["score"]
                >= 52
            )

            strong_short = (
                data["direction"]
                == "SHORT"
                and
                data["score"]
                >= 58
                and
                data["liquidity_state"]
                == "OUTFLOW"
            )

            early_long = (
                recent_state
                and
                data["score"]
                >= 48
                and
                data["direction"]
                == "LONG"
            )

            if not (
                strong_long
                or strong_short
                or early_long
            ):

                continue

            # منع مطاردة الانفجار

            if (
                data["direction"]
                == "LONG"
                and
                data["drawdown"]
                > -2
                and
                data["volume_ratio"]
                > 2.5
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

        # لا تضرب BingX بسرعة
        time.sleep(0.25)

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

        f"📊 RSI: {data['rsi']}",

        f"📊 Volume: {data['volume_ratio']}x",

        f"📈 Volume Trend: {data['volume_trend']}",

        f"💧 السيولة: {liquidity}",

        f"💧 Buy Pressure: {data['buy_pressure']}%",

        "",

        f"🎯 القاع: {bottom}",

        f"📉 الهبوط السابق: {data['drawdown']}%",

        "",

        "📊 تأكيد الفريمات",

        f"15M: {data['trend_15m']}",

        f"1H: {data['trend_1h']}",

        f"4H: {data['trend_4h']}",

        f"1D: {data['trend_1d']}",

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

        "⚠️ إشارة تحليلية وليست ضمانًا للربح.",

        "⚠️ لا تطارد البمب؛ انتظر منطقة الدخول والتأكيد."

    ])

    return "\n".join(lines)
