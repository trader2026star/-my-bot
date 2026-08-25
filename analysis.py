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
    "User-Agent": "CryptoZeroReversal-BingX/8.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# CACHE
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 600

_TICKER_CACHE = []
_TICKER_CACHE_TIME = 0

TICKER_CACHE_SECONDS = 30

_KLINE_CACHE = {}

KLINE_CACHE_SECONDS = 60


# =========================================================
# RATE LIMIT PROTECTION
# =========================================================

_RATE_LIMIT_UNTIL = 0

_RATE_LOCK = threading.Lock()

_REQUEST_LOCK = threading.Lock()

_LAST_REQUEST_TIME = 0

MIN_REQUEST_INTERVAL = 0.35


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):

    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    with _RATE_LOCK:

        if time.time() < _RATE_LIMIT_UNTIL:

            logger.warning(
                "BingX protection active. Retry in %.0f sec",
                _RATE_LIMIT_UNTIL - time.time()
            )

            return None

    # حماية عامة بين الطلبات
    with _REQUEST_LOCK:

        now = time.time()

        wait = (
            MIN_REQUEST_INTERVAL
            - (now - _LAST_REQUEST_TIME)
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
                "BingX API/RATE error: %s",
                data
            )

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

    closes = [
        k[4]
        for k in klines
    ]

    highs = [
        k[2]
        for k in klines
    ]

    lows = [
        k[3]
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
        x for x in recent_lows
        if x < current
    ]

    resistances = [
        x for x in recent_highs
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
# DRAW DOWN
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

def detect_market_structure(
    klines,
    pivot=3
):

    if len(klines) < 30:

        return {
            "structure": "UNKNOWN",
            "bos": "NONE",
            "swing_high": None,
            "swing_low": None
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

    swing_highs = []
    swing_lows = []

    for i in range(
        pivot,
        len(klines) - pivot
    ):

        high = highs[i]
        low = lows[i]

        left_highs = highs[
            i - pivot:i
        ]

        right_highs = highs[
            i + 1:i + pivot + 1
        ]

        left_lows = lows[
            i - pivot:i
        ]

        right_lows = lows[
            i + 1:i + pivot + 1
        ]

        if (
            high > max(left_highs)
            and
            high > max(right_highs)
        ):

            swing_highs.append(high)

        if (
            low < min(left_lows)
            and
            low < min(right_lows)
        ):

            swing_lows.append(low)

    swing_high = (
        swing_highs[-1]
        if swing_highs
        else None
    )

    swing_low = (
        swing_lows[-1]
        if swing_lows
        else None
    )

    current = closes[-1]

    bos = "NONE"

    if (
        swing_high is not None
        and current > swing_high
    ):

        bos = "BULLISH"

    elif (
        swing_low is not None
        and current < swing_low
    ):

        bos = "BEARISH"

    if len(swing_highs) >= 2:

        if (
            swing_highs[-1]
            > swing_highs[-2]
        ):

            high_structure = "HH"

        else:

            high_structure = "LH"

    else:

        high_structure = "UNKNOWN"

    if len(swing_lows) >= 2:

        if (
            swing_lows[-1]
            > swing_lows[-2]
        ):

            low_structure = "HL"

        else:

            low_structure = "LL"

    else:

        low_structure = "UNKNOWN"

    if (
        high_structure == "HH"
        and low_structure == "HL"
    ):

        structure = "BULLISH"

    elif (
        high_structure == "LH"
        and low_structure == "LL"
    ):

        structure = "BEARISH"

    else:

        structure = "MIXED"

    return {

        "structure": structure,

        "bos": bos,

        "swing_high": swing_high,

        "swing_low": swing_low
    }


# =========================================================
# 4H MASTER TREND
# =========================================================

def calculate_4h_trend(
    klines
):

    if len(klines) < 60:

        return "UNKNOWN"

    closes = [
        k[4]
        for k in klines
    ]

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    if (
        ema20 is None
        or ema50 is None
    ):

        return "UNKNOWN"

    structure = detect_market_structure(
        klines
    )

    current = closes[-1]

    bullish_points = 0
    bearish_points = 0

    if ema20 > ema50:
        bullish_points += 1

    if ema20 < ema50:
        bearish_points += 1

    if current > ema20:
        bullish_points += 1

    if current < ema20:
        bearish_points += 1

    if structure["structure"] == "BULLISH":
        bullish_points += 2

    if structure["structure"] == "BEARISH":
        bearish_points += 2

    if structure["bos"] == "BULLISH":
        bullish_points += 2

    if structure["bos"] == "BEARISH":
        bearish_points += 2

    if bullish_points >= 4:
        return "LONG"

    if bearish_points >= 4:
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# LIQUIDITY PROXY
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

    reasons = []

    score = 0

    # ---------------------------------------------
    # BUYING PRESSURE
    # ---------------------------------------------

    if (
        bullish_volume
        > bearish_volume * 1.20
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أكبر من الهابطة"
        )

    if (
        recent_volume
        > previous_volume * 1.10
    ):

        score += 1

        reasons.append(
            "الحجم بدأ يرتفع"
        )

    # ---------------------------------------------
    # SELLING PRESSURE
    # ---------------------------------------------

    if (
        bearish_volume
        > bullish_volume * 1.20
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أكبر من الصاعدة"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and
        bearish_volume
        > bullish_volume
    ):

        score -= 1

        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
        )

    # ---------------------------------------------
    # FINAL
    # ---------------------------------------------

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

    if drawdown <= -8:

        score += 1

        reasons.append(
            "هبوط سابق واضح"
        )

    if recent_range <= 18:

        score += 1

        reasons.append(
            "السعر بدأ يدخل نطاق تجميع"
        )

    if (
        old_volume > 0
        and
        recent_volume
        >= old_volume * 0.75
    ):

        score += 1

        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if candle[
        "lower_wick_ratio"
    ] >= 0.30:

        score += 1

        reasons.append(
            "رفض سعري من الأسفل"
        )

    if (
        recent_high > recent_low
    ):

        position = (
            current - recent_low
        ) / (
            recent_high - recent_low
        )

        if position <= 0.70:

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
# VOLATILITY / CRASH FILTER
# =========================================================

def detect_abnormal_move(
    klines
):

    if len(klines) < 5:

        return False, 0.0, "UNKNOWN"

    changes = []

    for i in range(
        len(klines) - 2,
        len(klines)
    ):

        old = klines[i - 1][4]
        new = klines[i][4]

        changes.append(
            percentage_change(
                old,
                new
            )
        )

    two_candle_change = (
        percentage_change(
            klines[-3][4],
            klines[-1][4]
        )
    )

    # انهيار/انفجار غير طبيعي
    if (
        two_candle_change <= -12
    ):

        return (
            True,
            two_candle_change,
            "CRASH"
        )

    if (
        two_candle_change >= 15
    ):

        return (
            True,
            two_candle_change,
            "PUMP"
        )

    return (
        False,
        two_candle_change,
        "NORMAL"
    )


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

    # =====================================================
    # 4H MASTER
    # =====================================================

    klines_4h = get_bingx_klines(
        symbol,
        "4h",
        120
    )

    if not klines_4h:

        return None

    # =====================================================
    # 1H ENTRY
    # =====================================================

    klines_1h = get_bingx_klines(
        symbol,
        "1h",
        150
    )

    if not klines_1h:

        return None

    # =====================================================
    # 4H DIRECTION
    # =====================================================

    trend_4h = calculate_4h_trend(
        klines_4h
    )

    if trend_4h == "UNKNOWN":

        return None

    # =====================================================
    # 1H DATA
    # =====================================================

    closes = [
        k[4]
        for k in klines_1h
    ]

    volumes = [
        k[5]
        for k in klines_1h
    ]

    current = closes[-1]

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

    if not atr or atr <= 0:

        atr = current * 0.01

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    # =====================================================
    # STRUCTURE
    # =====================================================

    structure = detect_market_structure(
        klines_1h
    )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    liquidity_state, liquidity_score, liquidity_reasons = (
        detect_liquidity_flow(
            klines_1h
        )
    )

    # =====================================================
    # BOTTOM
    # =====================================================

    bottom_detected, bottom_score, bottom_reasons = (
        detect_bottom_accumulation(
            klines_1h
        )
    )

    # =====================================================
    # VOLATILITY
    # =====================================================

    abnormal_move, two_candle_change, move_type = (
        detect_abnormal_move(
            klines_1h
        )
    )

    drawdown = calculate_recent_drawdown(
        closes
    )

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

    analysis_lines = []

    long_score = 0
    short_score = 0

    # =====================================================
    # MASTER 4H
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
            "4H غير واضح"
        )

    # =====================================================
    # 1H STRUCTURE
    # =====================================================

    if structure["structure"] == "BULLISH":

        long_score += 15

        analysis_lines.append(
            "هيكل 1H صاعد"
        )

    elif structure["structure"] == "BEARISH":

        short_score += 15

        analysis_lines.append(
            "هيكل 1H هابط"
        )

    # =====================================================
    # BOS
    # =====================================================

    if structure["bos"] == "BULLISH":

        long_score += 15

        analysis_lines.append(
            "BOS صاعد على 1H"
        )

    elif structure["bos"] == "BEARISH":

        short_score += 15

        analysis_lines.append(
            "BOS هابط على 1H"
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

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if liquidity_state == "INFLOW":

            long_score += 8

            analysis_lines.append(
                "حجم مرتفع مع طلب"
            )

        elif liquidity_state == "OUTFLOW":

            short_score += 8

            analysis_lines.append(
                "حجم مرتفع مع ضغط بيع"
            )

    if volume_trend == "RISING":

        if liquidity_state == "INFLOW":

            long_score += 5

        elif liquidity_state == "OUTFLOW":

            short_score += 5

    # =====================================================
    # RSI
    # =====================================================

    # RSI ليس صاحب القرار.
    # لا نفتح SHORT بسبب RSI منخفض.

    if trend_4h == "LONG":

        if 40 <= rsi <= 68:

            long_score += 6

        elif rsi < 25:

            analysis_lines.append(
                "RSI منخفض جداً؛ انتظار تأكيد الارتداد"
            )

    elif trend_4h == "SHORT":

        if 35 <= rsi <= 65:

            short_score += 6

        elif rsi < 20:

            # حماية من البيع في القاع
            short_score -= 15

            analysis_lines.append(
                "RSI منخفض جداً؛ ممنوع مطاردة الشورت"
            )

        elif rsi > 75:

            short_score += 5

    # =====================================================
    # BOTTOM
    # =====================================================

    if bottom_detected:

        long_score += 10

        analysis_lines.append(
            "تجميع/قاع محتمل على 1H"
        )

    # =====================================================
    # SUPPORT
    # =====================================================

    if support_distance <= 3:

        if trend_4h == "LONG":

            long_score += 8

            analysis_lines.append(
                "السعر قريب من دعم"
            )

    # =====================================================
    # RESISTANCE
    # =====================================================

    if resistance_distance <= 3:

        if trend_4h == "SHORT":

            short_score += 8

            analysis_lines.append(
                "السعر قريب من مقاومة"
            )

    # =====================================================
    # FAST MOVE
    # =====================================================

    if two_candle_change <= -8:

        long_score -= 15

        short_score -= 20

        analysis_lines.append(
            "هبوط سريع؛ منع مطاردة الحركة"
        )

    if two_candle_change >= 8:

        long_score -= 20

        short_score -= 15

        analysis_lines.append(
            "ارتفاع سريع؛ منع مطاردة البمب"
        )

    # =====================================================
    # ABNORMAL MOVE = NO TRADE
    # =====================================================

    if abnormal_move:

        direction = "WAIT"

        score = 0

        trend = (
            "UP"
            if trend_4h == "LONG"
            else
            "DOWN"
            if trend_4h == "SHORT"
            else
            "NEUTRAL"
        )

        state = (
            "NO TRADE - حركة سعرية غير طبيعية"
        )

    # =====================================================
    # 4H NEUTRAL
    # =====================================================

    elif trend_4h == "NEUTRAL":

        direction = "WAIT"

        score = 0

        trend = "NEUTRAL"

        state = (
            "NO TRADE - اتجاه 4H غير واضح"
        )

    # =====================================================
    # 4H LONG
    # =====================================================

    elif trend_4h == "LONG":

        trend = "UP"

        # ممنوع SHORT ضد 4H
        if liquidity_state == "OUTFLOW":

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - 4H صاعد لكن السيولة خارجة"
            )

        elif structure["structure"] == "BEARISH":

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - 4H صاعد لكن هيكل 1H هابط"
            )

        elif (
            long_score >= 55
            and
            (
                liquidity_state == "INFLOW"
                or
                structure["bos"] == "BULLISH"
                or
                bottom_detected
            )
        ):

            direction = "LONG"

            score = long_score

            if (
                liquidity_state == "INFLOW"
                and
                structure["bos"] == "BULLISH"
            ):

                state = (
                    "4H صاعد + دخول سيولة + BOS صاعد"
                )

            elif liquidity_state == "INFLOW":

                state = (
                    "4H صاعد + دخول سيولة"
                )

            else:

                state = (
                    "4H صاعد + تأكيد 1H"
                )

        else:

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - لم يكتمل تأكيد LONG"
            )

    # =====================================================
    # 4H SHORT
    # =====================================================

    else:

        trend = "DOWN"

        # ممنوع LONG ضد 4H
        if liquidity_state == "INFLOW":

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - 4H هابط لكن السيولة داخلة"
            )

        elif structure["structure"] == "BULLISH":

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - 4H هابط لكن هيكل 1H صاعد"
            )

        elif rsi < 20:

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - RSI منخفض جداً وخطر البيع في القاع"
            )

        elif (
            short_score >= 55
            and
            (
                liquidity_state == "OUTFLOW"
                or
                structure["bos"] == "BEARISH"
            )
        ):

            direction = "SHORT"

            score = short_score

            if (
                liquidity_state == "OUTFLOW"
                and
                structure["bos"] == "BEARISH"
            ):

                state = (
                    "4H هابط + خروج سيولة + BOS هابط"
                )

            elif liquidity_state == "OUTFLOW":

                state = (
                    "4H هابط + خروج سيولة"
                )

            else:

                state = (
                    "4H هابط + تأكيد 1H"
                )

        else:

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - لم يكتمل تأكيد SHORT"
            )

    # =====================================================
    # SCORE
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

    if direction == "LONG":

        entry_min = max(
            support,
            current - atr * 0.50
        )

        entry_max = current

        # SL هيكلي
        structural_sl = (
            support - atr * 0.25
        )

        atr_sl = (
            current - atr * 1.30
        )

        stop_loss = min(
            structural_sl,
            atr_sl
        )

        # لا نسمح بمخاطرة بعيدة جداً
        max_sl = current * 0.96

        if stop_loss < max_sl:

            stop_loss = max_sl

            analysis_lines.append(
                "تم تقليل مسافة Stop Loss لحماية الصفقة"
            )

        risk = current - stop_loss

        if risk <= 0:

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - لا توجد منطقة SL سليمة"
            )

            entry_min = current
            entry_max = current
            stop_loss = current
            tp1 = current
            tp2 = current
            tp3 = current

        else:

            tp1 = current + risk * 1.2
            tp2 = current + risk * 2.0
            tp3 = current + risk * 3.0

            if resistance > current:

                tp1 = min(
                    tp1,
                    resistance
                )

    elif direction == "SHORT":

        entry_min = current

        entry_max = min(
            resistance,
            current + atr * 0.50
        )

        structural_sl = (
            resistance + atr * 0.25
        )

        atr_sl = (
            current + atr * 1.30
        )

        stop_loss = max(
            structural_sl,
            atr_sl
        )

        # حد أقصى للمخاطرة
        max_sl = current * 1.04

        if stop_loss > max_sl:

            stop_loss = max_sl

            analysis_lines.append(
                "تم تقليل مسافة Stop Loss لحماية الصفقة"
            )

        risk = stop_loss - current

        if risk <= 0:

            direction = "WAIT"

            score = 0

            state = (
                "NO TRADE - لا توجد منطقة SL سليمة"
            )

            entry_min = current
            entry_max = current
            stop_loss = current
            tp1 = current
            tp2 = current
            tp3 = current

        else:

            tp1 = current - risk * 1.2
            tp2 = current - risk * 2.0
            tp3 = current - risk * 3.0

            if support < current:

                tp1 = max(
                    tp1,
                    support
                )

    else:

        entry_min = current
        entry_max = current

        stop_loss = current

        tp1 = current
        tp2 = current
        tp3 = current

    # =====================================================
    # BUY / SELL PRESSURE
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

        "trend_4h":
            trend_4h,

        "structure":
            structure["structure"],

        "bos":
            structure["bos"],

        "swing_high":
            smart_round(
                structure["swing_high"]
            ),

        "swing_low":
            smart_round(
                structure["swing_low"]
            ),

        "two_candle_change":
            round(
                two_candle_change,
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
# TICKERS
# =========================================================

def get_market_tickers():

    global _TICKER_CACHE
    global _TICKER_CACHE_TIME

    now = time.time()

    if (
        _TICKER_CACHE
        and
        now - _TICKER_CACHE_TIME
        < TICKER_CACHE_SECONDS
    ):

        return list(_TICKER_CACHE)

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker"
    )

    if not data:

        return list(_TICKER_CACHE)

    rows = data.get("data")

    if not isinstance(rows, list):

        return list(_TICKER_CACHE)

    _TICKER_CACHE = rows

    _TICKER_CACHE_TIME = now

    return list(rows)


# =========================================================
# TOP / DIVERSIFIED SYMBOLS
# =========================================================

def get_top_futures_symbols(
    limit=35
):

    symbols = get_futures_symbols()

    if not symbols:

        return []

    rows = get_market_tickers()

    if not rows:

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

        symbol = (
            str(raw_symbol)
            .replace("-", "")
            .upper()
        )

        if symbol not in symbols:
            continue

        try:

            quote_volume = float(
                item.get(
                    "quoteVolume",
                    0
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

            last_price = float(
                item.get(
                    "lastPrice",
                    0
                )
            )

            if quote_volume <= 0:
                continue

            # سيولة كافية + حركة
            score = (
                quote_volume
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
                    score,
                    quote_volume,
                    change,
                    last_price
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

    # =====================================================
    # لا نريد BTC/ETH/SOL/XRP فقط
    # =====================================================

    majors = {
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "BNBUSDT",
        "DOGEUSDT",
        "ADAUSDT"
    }

    selected = []

    # أولاً: العملات البديلة
    for item in candidates:

        symbol = item[0]

        if symbol in majors:
            continue

        selected.append(symbol)

        if len(selected) >= limit - 5:
            break

    # ثم بعض العملات الرئيسية
    for item in candidates:

        symbol = item[0]

        if symbol not in majors:
            continue

        if symbol not in selected:

            selected.append(symbol)

        if len(selected) >= limit:
            break

    return selected[:limit]


# =========================================================
# SCANNER
# =========================================================

def scan_market(
    limit=5
):

    symbols = get_top_futures_symbols(
        35
    )

    if not symbols:

        return []

    results = []

    logger.info(
        "Scanner started. Candidates: %s",
        len(symbols)
    )

    for symbol in symbols:

        if time.time() < _RATE_LIMIT_UNTIL:

            logger.warning(
                "Stopping scanner because rate limit is active."
            )

            break

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:

                continue

            # =================================================
            # ONLY REAL TRADES
            # =================================================

            if data["direction"] not in (
                "LONG",
                "SHORT"
            ):

                continue

            # =================================================
            # SCORE
            # =================================================

            if data["score"] < 55:

                continue

            # =================================================
            # LONG
            # =================================================

            if data["direction"] == "LONG":

                if data["trend_4h"] != "LONG":

                    continue

                # لازم دليل سيولة أو BOS أو تجميع
                confirmation = (
                    data["liquidity_state"]
                    == "INFLOW"
                    or
                    data["bos"]
                    == "BULLISH"
                    or
                    data["bottom_detected"]
                )

                if not confirmation:

                    continue

                # ممنوع LONG بعد انهيار
                if (
                    data["two_candle_change"]
                    <= -8
                ):

                    continue

            # =================================================
            # SHORT
            # =================================================

            elif data["direction"] == "SHORT":

                if data["trend_4h"] != "SHORT":

                    continue

                confirmation = (
                    data["liquidity_state"]
                    == "OUTFLOW"
                    or
                    data["bos"]
                    == "BEARISH"
                )

                if not confirmation:

                    continue

                # ممنوع البيع في القاع
                if data["rsi"] < 20:

                    continue

                # ممنوع مطاردة انهيار
                if (
                    data["two_candle_change"]
                    <= -8
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
        time.sleep(0.80)

    # =====================================================
    # RANK
    # =====================================================

    results.sort(
        key=lambda x: (

            x["score"],

            1
            if x["liquidity_state"]
            in (
                "INFLOW",
                "OUTFLOW"
            )
            else 0,

            1
            if x["bos"]
            in (
                "BULLISH",
                "BEARISH"
            )
            else 0,

            1
            if x["structure"]
            in (
                "BULLISH",
                "BEARISH"
            )
            else 0,

            x["volume_ratio"]
        ),
        reverse=True
    )

    logger.info(
        "Scanner finished. Valid trades: %s",
        len(results)
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

        liquidity = "🟢 دخول سيولة محتمل"

    elif data["liquidity_state"] == "OUTFLOW":

        liquidity = "🔴 خروج سيولة محتمل"

    else:

        liquidity = "🟡 سيولة محايدة"

    structure = data.get(
        "structure",
        "UNKNOWN"
    )

    bos = data.get(
        "bos",
        "NONE"
    )

    lines = [

        "🤖 BingX AI Scanner",

        "",

        f"💎 العملة: {data['symbol']}",

        f"📈 الاتجاه النهائي: {emoji} {data['direction']}",

        f"⭐ Score: {data['score']}/100",

        "",

        f"🧠 الحالة: {data['state']}",

        "",

        "📊 الاتجاه الرئيسي",

        f"4H: {data['trend_4h']}",

        "",

        "🔎 تأكيد الدخول - 1H",

        f"هيكل السوق: {structure}",

        f"BOS: {bos}",

        f"💧 السيولة: {liquidity}",

        f"📊 Volume: {data['volume_ratio']}x",

        f"📈 Volume Trend: {data['volume_trend']}",

        f"💪 Buy Pressure: {data['buy_pressure']}%",

        f"📊 RSI: {data['rsi']}",

        "",

        f"🎯 القاع/التجميع: "
        f"{'🟢 نعم' if data['bottom_detected'] else '⚪ لا'}",

        f"📉 الهبوط السابق: {data['drawdown']}%",

        f"⚡ حركة آخر شمعتين: "
        f"{data['two_candle_change']}%",

        "",

        "🛡️ الدعم والمقاومة",

        f"🟢 Support: {data['support']}",

        f"🔴 Resistance: {data['resistance']}",

        f"📏 البعد عن الدعم: "
        f"{data['support_distance']}%",

        f"📏 البعد عن المقاومة: "
        f"{data['resistance_distance']}%",

        "",

        "📍 منطقة الدخول 1H",

        f"{data['entry_min']} - {data['entry_max']}",

        "",

        f"🛑 Stop Loss: {data['stop_loss']}",

        "",

        "🎯 الأهداف",

        f"TP1: {data['tp1']}",

        f"TP2: {data['tp2']}",

        f"TP3: {data['tp3']}",

        "",

        "🔍 أسباب القرار"
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
            "💧 أدلة السيولة"
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
            "🎯 أدلة التجميع"
        )

        for reason in data[
            "bottom_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    lines.extend([

        "",

        "⚠️ إشارة تحليلية وليست ضماناً للربح.",

        "⚠️ لا تدخل إذا تحرك السعر بعيداً عن منطقة الدخول.",

        "⚠️ SHORT لا يعتمد على RSI وحده، وLONG لا يعتمد على EMA وحده."

    ])

    return "\n".join(lines)
