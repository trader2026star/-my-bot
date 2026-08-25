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
    "User-Agent": "CryptoZeroReversal-BingX-Final/5.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# CACHE
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0
SYMBOL_CACHE_SECONDS = 600

_KLINE_CACHE = {}
KLINE_CACHE_SECONDS = 60

_RATE_LIMIT_UNTIL = 0
_RATE_LOCK = threading.Lock()

_REQUEST_LOCK = threading.Lock()
MIN_REQUEST_INTERVAL = 0.45
_LAST_REQUEST_TIME = 0


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None

    with _REQUEST_LOCK:
        now = time.time()

        wait = MIN_REQUEST_INTERVAL - (
            now - _LAST_REQUEST_TIME
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

        clean = symbol.replace("-", "")

        if clean.endswith("USDT"):
            symbols.add(clean)

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

    for i in range(
        1,
        len(closes)
    ):

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

    for i in range(
        1,
        len(klines)
    ):

        high = klines[i][2]
        low = klines[i][3]

        previous_close = (
            klines[i - 1][4]
        )

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            )
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

    previous = (
        volumes[
            -period - 1:
            -1
        ]
    )

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 1.0

    return round(
        volumes[-1]
        / average,
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
        sum(
            volumes[-short_period:]
        )
        / short_period
    )

    long_avg = (
        sum(
            volumes[-long_period:]
        )
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
        (
            new_price
            - old_price
        )
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

    candle_range = (
        high - low
    )

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
            (
                closes[-1]
                - highest
            )
            / highest
        ) * 100,
        2
    )


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(
    klines
):

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

    reference_high = max(
        highs[-25:-5]
    )

    reference_low = min(
        lows[-25:-5]
    )

    previous_close = closes[-2]

    bos = "NONE"
    structure = "MIXED"

    reasons = []

    if (
        current > reference_high
        and previous_close <= reference_high
    ):

        bos = "BULLISH_BOS"
        structure = "BULLISH"

        reasons.append(
            "تم تأكيد كسر هيكل صاعد BOS"
        )

    elif (
        current < reference_low
        and previous_close >= reference_low
    ):

        bos = "BEARISH_BOS"
        structure = "BEARISH"

        reasons.append(
            "تم تأكيد كسر هيكل هابط BOS"
        )

    else:

        recent_highs = highs[-8:]
        recent_lows = lows[-8:]

        if (
            current < max(recent_highs)
            and current > min(recent_lows)
        ):

            structure = "MIXED"

        reasons.append(
            "لا يوجد BOS مؤكد"
        )

    recent_high = max(
        highs[-8:]
    )

    recent_low = min(
        lows[-8:]
    )

    distance_from_low = (
        abs(
            current
            - recent_low
        )
        / current
        * 100
    )

    distance_from_high = (
        abs(
            recent_high
            - current
        )
        / current
        * 100
    )

    liquidity_zone = "NONE"

    if distance_from_low <= 0.50:

        liquidity_zone = "LOW_LIQUIDITY"

        reasons.append(
            "السعر قريب جداً من السيولة السفلية"
        )

    elif distance_from_high <= 0.50:

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

    if len(klines) < 50:
        return False, 0, []

    closes = [
        k[4]
        for k in klines
    ]

    volumes = [
        k[5]
        for k in klines
    ]

    old = closes[-50:-25]
    recent = closes[-25:]

    old_high = max(old)
    recent_low = min(recent)
    recent_high = max(recent)

    if old_high <= 0:
        return False, 0, []

    drawdown = (
        (
            recent_low
            - old_high
        )
        / old_high
    ) * 100

    recent_range = (
        (
            recent_high
            - recent_low
        )
        / recent_low
    ) * 100

    old_volume = (
        sum(
            volumes[-50:-25]
        )
        / 25
    )

    recent_volume = (
        sum(
            volumes[-10:]
        )
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
            "هبوط سابق واضح"
        )

    if recent_range <= 15:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if (
        old_volume > 0
        and recent_volume
        >= old_volume * 0.70
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

    if recent_high > recent_low:

        position = (
            closes[-1]
            - recent_low
        ) / (
            recent_high
            - recent_low
        )

        if position <= 0.70:

            score += 1

            reasons.append(
                "السعر ليس في قمة النطاق"
            )

    detected = score >= 3

    return (
        detected,
        score,
        reasons
    )


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 35:

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
        max(
            0,
            len(klines) - 12
        ),
        len(klines)
    ):

        if closes[i] > opens[i]:

            bullish_volume += (
                volumes[i]
            )

        elif closes[i] < opens[i]:

            bearish_volume += (
                volumes[i]
            )

    score = 0

    # =====================================================
    # INFLOW
    # =====================================================

    if (
        bullish_volume
        > bearish_volume * 1.20
        and volume_ratio >= 1.05
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أكبر بوضوح"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change >= -1.5
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن بدون ضغط هابط قوي"
        )

    # =====================================================
    # OUTFLOW
    # =====================================================

    if (
        bearish_volume
        > bullish_volume * 1.20
        and volume_ratio >= 1.05
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أكبر بوضوح"
        )

    if (
        recent_volume
        > previous_volume * 1.10
        and recent_change <= -1.5
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
# EARLY REVERSAL
# =========================================================

def detect_early_reversal(
    klines,
    trend_4h,
    support,
    resistance,
    current,
    ema9,
    ema20,
    ema50,
    rsi,
    volume_ratio,
    volume_trend,
    liquidity_state,
    bottom_detected,
    bottom_score,
    structure
):

    score = 0
    reasons = []

    if trend_4h == "LONG":

        score += 20

        reasons.append(
            "4H صاعد"
        )

    elif trend_4h == "SHORT":

        score += 20

        reasons.append(
            "4H هابط"
        )

    else:

        return (
            0,
            "NONE",
            reasons
        )

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    support_distance = (
        abs(
            current
            - support
        )
        / current
        * 100
    )

    resistance_distance = (
        abs(
            resistance
            - current
        )
        / current
        * 100
    )

    if (
        trend_4h == "LONG"
        and support_distance <= 1.0
    ):

        score += 8

        reasons.append(
            "السعر قريب من الدعم"
        )

    if (
        trend_4h == "SHORT"
        and resistance_distance <= 1.0
    ):

        score += 8

        reasons.append(
            "السعر قريب من المقاومة"
        )

    # =====================================================
    # BOTTOM / ACCUMULATION
    # =====================================================

    if bottom_detected:

        score += min(
            bottom_score * 4,
            16
        )

        reasons.append(
            f"تجميع/قاع مكتشف ({bottom_score}/5)"
        )

    # =====================================================
    # RSI
    # =====================================================

    if trend_4h == "LONG":

        if 40 <= rsi <= 60:

            score += 8

            reasons.append(
                "RSI مناسب لبداية انعكاس صاعد"
            )

        elif 60 < rsi <= 68:

            score += 5

    elif trend_4h == "SHORT":

        if 40 <= rsi <= 60:

            score += 8

            reasons.append(
                "RSI مناسب لبداية انعكاس هابط"
            )

        elif 32 <= rsi < 40:

            score += 5

    # =====================================================
    # EMA
    # =====================================================

    if trend_4h == "LONG":

        if ema20 > ema50:

            score += 5

            reasons.append(
                "EMA20 فوق EMA50"
            )

        if ema20 > 0:

            ema_gap = (
                abs(
                    ema9 - ema20
                )
                / ema20
            ) * 100

            if ema_gap <= 1.0:

                score += 5

                reasons.append(
                    "EMA9 قريب من EMA20 وبداية تحول محتملة"
                )

    elif trend_4h == "SHORT":

        if ema20 < ema50:

            score += 5

            reasons.append(
                "EMA20 تحت EMA50"
            )

        if ema20 > 0:

            ema_gap = (
                abs(
                    ema9 - ema20
                )
                / ema20
            ) * 100

            if ema_gap <= 1.0:

                score += 5

                reasons.append(
                    "EMA9 قريب من EMA20 وبداية تحول محتملة"
                )

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 0.80:

        score += 8

        reasons.append(
            "الحجم مقبول"
        )

    elif volume_ratio >= 0.60:

        score += 4

        reasons.append(
            "الحجم متوسط"
        )

    # =====================================================
    # VOLUME TREND
    # =====================================================

    if volume_trend == "RISING":

        score += 8

        reasons.append(
            "الحجم يبدأ في التحسن"
        )

    elif volume_trend == "NEUTRAL":

        score += 3

        reasons.append(
            "الحجم مستقر"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if trend_4h == "LONG":

        if liquidity_state == "INFLOW":

            score += 10

            reasons.append(
                "بدأ دخول السيولة"
            )

        elif liquidity_state == "NEUTRAL":

            score += 2

            reasons.append(
                "السيولة لم تتحول للخروج"
            )

    elif trend_4h == "SHORT":

        if liquidity_state == "OUTFLOW":

            score += 10

            reasons.append(
                "بدأ خروج السيولة"
            )

        elif liquidity_state == "NEUTRAL":

            score += 2

            reasons.append(
                "السيولة لم تتحول للدخول"
            )

    # =====================================================
    # BOS
    # =====================================================

    if trend_4h == "LONG":

        if structure["bos"] == "BULLISH_BOS":

            score += 10

            reasons.append(
                "BOS صاعد مؤكد"
            )

        elif structure["bos"] == "BEARISH_BOS":

            score -= 15

            reasons.append(
                "BOS هابط ضد الاتجاه"
            )

    elif trend_4h == "SHORT":

        if structure["bos"] == "BEARISH_BOS":

            score += 10

            reasons.append(
                "BOS هابط مؤكد"
            )

        elif structure["bos"] == "BULLISH_BOS":

            score -= 15

            reasons.append(
                "BOS صاعد ضد الاتجاه"
            )

    score = max(
        0,
        min(
            100,
            int(score)
        )
    )

    if trend_4h == "LONG":

        early_direction = "LONG"

    elif trend_4h == "SHORT":

        early_direction = "SHORT"

    else:

        early_direction = "NONE"

    return (
        score,
        early_direction,
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

    symbol = normalize_symbol(
        symbol
    )

    if not symbol_exists(symbol):

        logger.info(
            "Symbol not found: %s",
            symbol
        )

        return None

    # =====================================================
    # 4H
    # =====================================================

    klines_4h = get_bingx_klines(
        symbol,
        "4h",
        120
    )

    if not klines_4h:
        return None

    # =====================================================
    # 1H
    # =====================================================

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
    # TRENDS
    # =====================================================

    trend_4h = calculate_timeframe_trend(
        klines_4h
    )

    if trend_4h == "UNKNOWN":
        return None

    trend_1h = calculate_timeframe_trend(
        klines_1h
    )

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
        volumes,
        20
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

    # =====================================================
    # STRUCTURE
    # =====================================================

    structure = detect_market_structure(
        klines_1h
    )

    # =====================================================
    # BOTTOM
    # =====================================================

    (
        bottom_detected,
        bottom_score,
        bottom_reasons
    ) = detect_bottom_accumulation(
        klines_1h
    )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    (
        liquidity_state,
        liquidity_score,
        liquidity_reasons
    ) = detect_liquidity_flow(
        klines_1h
    )

    # =====================================================
    # EARLY REVERSAL
    # =====================================================

    (
        early_score,
        early_direction,
        early_reasons
    ) = detect_early_reversal(
        klines_1h,
        trend_4h,
        support,
        resistance,
        current,
        ema9,
        ema20,
        ema50,
        rsi,
        volume_ratio,
        volume_trend,
        liquidity_state,
        bottom_detected,
        bottom_score,
        structure
    )

    # =====================================================
    # PRICE DATA
    # =====================================================

    drawdown = calculate_recent_drawdown(
        closes
    )

    support_distance = (
        abs(
            current
            - support
        )
        / current
    ) * 100

    resistance_distance = (
        abs(
            resistance
            - current
        )
        / current
    ) * 100

    recent_change_2 = percentage_change(
        closes[-3],
        current
    )

    recent_change_6 = percentage_change(
        closes[-7],
        current
    )

    # =====================================================
    # FAST MOVE PROTECTION
    # =====================================================

    crash_detected = (
        recent_change_2 <= -8
        or recent_change_6 <= -15
    )

    pump_detected = (
        recent_change_2 >= 8
        or recent_change_6 >= 15
    )

    # =====================================================
    # SCORES
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []
    rejection_reasons = []

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
    # 1H STRUCTURE / BOS
    # =====================================================

    if structure["bos"] == "BULLISH_BOS":

        long_score += 20

        analysis_lines.append(
            "BOS صاعد مؤكد على 1H"
        )

    elif structure["bos"] == "BEARISH_BOS":

        short_score += 20

        analysis_lines.append(
            "BOS هابط مؤكد على 1H"
        )

    else:

        rejection_reasons.append(
            "لا يوجد BOS مؤكد"
        )

    # =====================================================
    # EMA
    # =====================================================

    if ema9 > ema20:

        long_score += 8

        analysis_lines.append(
            "EMA9 فوق EMA20 على 1H"
        )

    elif ema9 < ema20:

        short_score += 8

        analysis_lines.append(
            "EMA9 تحت EMA20 على 1H"
        )

    if ema20 > ema50:

        long_score += 5

    elif ema20 < ema50:

        short_score += 5

    # =====================================================
    # RSI
    # =====================================================

    if trend_4h == "LONG":

        if 42 <= rsi <= 68:

            long_score += 8

            analysis_lines.append(
                "RSI في نطاق مناسب للصعود"
            )

        elif rsi < 30:

            long_score -= 5

            rejection_reasons.append(
                "RSI منخفض ويحتاج ارتداد"
            )

        elif rsi > 75:

            long_score -= 8

            rejection_reasons.append(
                "RSI مرتفع ولا نطارد الصعود"
            )

    elif trend_4h == "SHORT":

        if 35 <= rsi <= 65:

            short_score += 8

        elif rsi < 30:

            short_score -= 15

            rejection_reasons.append(
                "RSI منخفض؛ خطر البيع في القاع"
            )

        elif rsi > 70:

            short_score += 8

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if trend_4h == "LONG":
            long_score += 10

        elif trend_4h == "SHORT":
            short_score += 10

        analysis_lines.append(
            "الحجم قوي"
        )

    elif volume_ratio < 0.60:

        rejection_reasons.append(
            "الحجم ضعيف"
        )

    # =====================================================
    # VOLUME TREND
    # =====================================================

    if volume_trend == "RISING":

        if trend_4h == "LONG":
            long_score += 5

        elif trend_4h == "SHORT":
            short_score += 5

        analysis_lines.append(
            "الحجم يتزايد"
        )

    elif volume_trend == "FALLING":

        rejection_reasons.append(
            "الحجم يتراجع"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

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

    else:

        rejection_reasons.append(
            "السيولة محايدة"
        )

    # =====================================================
    # BOTTOM
    # =====================================================

    if bottom_detected:

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
    # FAST MOVE
    # =====================================================

    if crash_detected:

        long_score -= 20
        short_score -= 20

        rejection_reasons.append(
            "حركة هبوط سريعة"
        )

    if pump_detected:

        long_score -= 15

        rejection_reasons.append(
            "حركة صعود سريعة"
        )

    # =====================================================
    # FINAL DECISION
    # =====================================================

    entry_score = 0
    direction = "NO TRADE"
    state = "NO TRADE"

    # =====================================================
    # LONG
    # =====================================================

    if trend_4h == "LONG":

        entry_score = long_score

        long_confirmations = 0

        if structure["bos"] == "BULLISH_BOS":
            long_confirmations += 1

        if liquidity_state == "INFLOW":
            long_confirmations += 1

        if volume_ratio >= 1.00:
            long_confirmations += 1

        if volume_trend == "RISING":
            long_confirmations += 1

        if ema9 > ema20:
            long_confirmations += 1

        if 42 <= rsi <= 68:
            long_confirmations += 1

        # -------------------------------------------------
        # خطر قوي
        # -------------------------------------------------

        if (
            structure["bos"]
            == "BEARISH_BOS"
            and liquidity_state
            == "OUTFLOW"
        ):

            direction = "NO TRADE"

            state = (
                "NO TRADE - "
                "1H هابط والسيولة خارجة"
            )

            rejection_reasons.extend([
                "هيكل 1H هابط",
                "السيولة خارجة"
            ])

        elif crash_detected:

            direction = "NO TRADE"

            state = (
                "NO TRADE - "
                "حركة هبوط سريعة"
            )

        # -------------------------------------------------
        # حجم منهار فعلاً
        # -------------------------------------------------

        elif (
            volume_ratio < 0.45
            and volume_trend == "FALLING"
        ):

            direction = "NO TRADE"

            state = (
                "NO TRADE - "
                "الحجم منهار"
            )

        # -------------------------------------------------
        # CONFIRMED LONG
        # -------------------------------------------------

        elif (
            long_score >= 65
            and long_confirmations >= 4
        ):

            direction = "LONG"

            state = (
                "🟢 CONFIRMED LONG - "
                "4H صاعد + تأكيد 1H قوي
