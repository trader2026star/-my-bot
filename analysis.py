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
    "User-Agent": "CryptoZeroReversal-BingX/7.0"
})

logger = logging.getLogger(__name__)


# =========================================================
# CACHE / RATE LIMIT
# =========================================================

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

_KLINE_CACHE = {}

_RATE_LIMIT_UNTIL = 0

_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()

MIN_REQUEST_INTERVAL = 0.60
_LAST_REQUEST_TIME = 0


# =========================================================
# BINGX REQUEST
# =========================================================

def bingx_get(path, params=None, timeout=15):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME

    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None

    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)

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
            logger.warning("BingX rate limit: %s", data)

            with _RATE_LOCK:
                _RATE_LIMIT_UNTIL = max(
                    _RATE_LIMIT_UNTIL,
                    time.time() + 180
                )

            return None

        if code not in (0, None):
            logger.warning(
                "BingX API error: %s",
                data
            )
            return None

        return data

    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "BingX request failed/invalid JSON: %s",
            exc
        )
        return None


# =========================================================
# SYMBOL HELPERS
# =========================================================

def normalize_symbol(text):
    text = (
        str(text)
        .strip()
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )

    if text.endswith(("USDT", "USDC")):
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
# FUTURES SYMBOLS
# =========================================================

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME

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

        raw = str(
            item.get("symbol", "")
        ).upper()

        if not raw.endswith("-USDT"):
            continue

        status = item.get("status")

        if status not in (1, "1", None):
            continue

        symbols.add(
            raw.replace("-", "")
        )

    if symbols:
        _SYMBOL_CACHE = symbols
        _SYMBOL_CACHE_TIME = now

    return set(_SYMBOL_CACHE)


def symbol_exists(symbol):
    return normalize_symbol(symbol) in get_futures_symbols()


# =========================================================
# KLINES
# =========================================================

def get_bingx_klines(symbol, interval="1h", limit=200):
    symbol = normalize_symbol(symbol)

    key = (
        symbol,
        interval,
        limit
    )

    now = time.time()

    cached = _KLINE_CACHE.get(key)

    if cached and now - cached[0] < KLINE_CACHE_SECONDS:
        return cached[1]

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

    for row in rows:

        try:

            if isinstance(row, dict):

                result.append([
                    row.get("time"),
                    float(row.get("open")),
                    float(row.get("high")),
                    float(row.get("low")),
                    float(row.get("close")),
                    float(row.get("volume"))
                ])

            elif isinstance(row, list) and len(row) >= 6:

                result.append([
                    row[0],
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5])
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

    _KLINE_CACHE[key] = (
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

        change = (
            closes[i] -
            closes[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period]) /
        period
    )

    avg_loss = (
        sum(losses[:period]) /
        period
    )

    for i in range(period, len(gains)):

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

    return round(
        100 - (
            100 /
            (
                1 +
                avg_gain / avg_loss
            )
        ),
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

        h = klines[i][2]
        l = klines[i][3]
        pc = klines[i - 1][4]

        trs.append(
            max(
                h - l,
                abs(h - pc),
                abs(l - pc)
            )
        )

    atr = (
        sum(trs[:period]) /
        period
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

def _completed_volume_window(volumes, count):

    if len(volumes) < count + 1:
        return []

    return volumes[
        -count - 1:-1
    ]


def calculate_volume_ratio(
    volumes,
    period=20
):
    """
    آخر 3 شموع مكتملة مقابل
    متوسط 20 شمعة مكتملة قبلها.
    """

    if len(volumes) < period + 4:
        return 1.0

    recent = volumes[-4:-1]

    baseline = volumes[
        -period - 4:-4
    ]

    recent_avg = (
        sum(recent) /
        len(recent)
    )

    base_avg = (
        sum(baseline) /
        len(baseline)
    )

    if base_avg <= 0:
        return 1.0

    return round(
        max(
            0.05,
            min(
                5.0,
                recent_avg / base_avg
            )
        ),
        2
    )


def calculate_volume_trend(
    volumes,
    short_period=5,
    long_period=20
):

    if len(volumes) < (
        long_period +
        short_period +
        1
    ):
        return "NEUTRAL"

    short = volumes[
        -short_period - 1:-1
    ]

    previous = volumes[
        -long_period - short_period - 1:
        -short_period - 1
    ]

    s = sum(short) / len(short)
    p = sum(previous) / len(previous)

    if p <= 0:
        return "NEUTRAL"

    ratio = s / p

    if ratio >= 1.12:
        return "RISING"

    if ratio <= 0.88:
        return "FALLING"

    return "NEUTRAL"


# =========================================================
# BASIC HELPERS
# =========================================================

def percentage_change(
    old_price,
    new_price
):
    if not old_price:
        return 0.0

    return (
        (new_price - old_price) /
        old_price
    ) * 100


def calculate_support_resistance(
    klines
):

    current = klines[-1][4]

    lookback = min(
        80,
        len(klines)
    )

    highs = [
        k[2]
        for k in klines[-lookback:]
    ]

    lows = [
        k[3]
        for k in klines[-lookback:]
    ]

    supports = [
        x
        for x in lows
        if x < current
    ]

    resistances = [
        x
        for x in highs
        if x > current
    ]

    support = (
        max(supports)
        if supports
        else min(lows)
    )

    resistance = (
        min(resistances)
        if resistances
        else max(highs)
    )

    return support, resistance


def candle_information(klines):

    o, h, l, c = klines[-1][1:5]

    r = h - l

    if r <= 0:

        return {
            "body_ratio": 0,
            "lower_wick_ratio": 0,
            "upper_wick_ratio": 0,
            "bullish": c > o,
            "bearish": c < o
        }

    return {
        "body_ratio": abs(c - o) / r,
        "lower_wick_ratio": (
            min(o, c) - l
        ) / r,
        "upper_wick_ratio": (
            h - max(o, c)
        ) / r,
        "bullish": c > o,
        "bearish": c < o
    }


def calculate_recent_drawdown(
    closes,
    lookback=50
):

    window = closes[-lookback:]

    if not window:
        return 0.0

    high = max(window)

    if high <= 0:
        return 0.0

    return round(
        (
            (closes[-1] - high) /
            high
        ) * 100,
        2
    )


# =========================================================
# RECENT MOMENTUM
# =========================================================

def calculate_recent_range(
    klines,
    lookback=20
):

    rows = klines[-lookback:]

    if not rows:
        return 0.0

    highs = [
        x[2]
        for x in rows
    ]

    lows = [
        x[3]
        for x in rows
    ]

    low = min(lows)
    high = max(highs)

    if low <= 0:
        return 0.0

    return (
        (high - low) /
        low
    ) * 100


def calculate_price_stability(
    klines,
    lookback=10
):

    rows = klines[
        -lookback - 1:
    ]

    if len(rows) < 5:
        return 0.0

    closes = [
        x[4]
        for x in rows
    ]

    changes = []

    for i in range(
        1,
        len(closes)
    ):

        changes.append(
            abs(
                percentage_change(
                    closes[i - 1],
                    closes[i]
                )
            )
        )

    if not changes:
        return 0.0

    return round(
        sum(changes) /
        len(changes),
        3
    )


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(
    klines
):

    if len(klines) < 50:

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
    previous = closes[-2]

    ref_high = max(
        highs[-30:-5]
    )

    ref_low = min(
        lows[-30:-5]
    )

    bos = "NONE"
    structure = "MIXED"
    reasons = []

    if (
        current > ref_high
        and previous <= ref_high
    ):

        bos = "BULLISH_BOS"
        structure = "BULLISH"

        reasons.append(
            "تم تأكيد كسر هيكل صاعد BOS"
        )

    elif (
        current < ref_low
        and previous >= ref_low
    ):

        bos = "BEARISH_BOS"
        structure = "BEARISH"

        reasons.append(
            "تم تأكيد كسر هيكل هابط BOS"
        )

    else:

        rh = max(
            highs[-10:]
        )

        rl = min(
            lows[-10:]
        )

        if current >= rh * 0.997:
            structure = "BULLISH"

        elif current <= rl * 1.003:
            structure = "BEARISH"

        reasons.append(
            "لا يوجد BOS مؤكد"
        )

    rh = max(
        highs[-10:]
    )

    rl = min(
        lows[-10:]
    )

    ld = (
        abs(current - rl) /
        current *
        100
    )

    hd = (
        abs(rh - current) /
        current *
        100
    )

    zone = "NONE"

    if ld <= 0.60:

        zone = "LOW_LIQUIDITY"

        reasons.append(
            "السعر قريب من السيولة السفلية"
        )

    elif hd <= 0.60:

        zone = "HIGH_LIQUIDITY"

        reasons.append(
            "السعر قريب من السيولة العلوية"
        )

    return {
        "structure": structure,
        "bos": bos,
        "liquidity_zone": zone,
        "reasons": reasons
    }


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

    old = closes[-60:-30]
    recent = closes[-30:]

    old_high = max(old)
    recent_low = min(recent)
    recent_high = max(recent)

    if old_high <= 0:
        return False, 0, []

    drawdown = (
        (recent_low - old_high) /
        old_high
    ) * 100

    recent_range = (
        (recent_high - recent_low) /
        recent_low *
        100
    ) if recent_low else 0

    old_volume = (
        sum(volumes[-60:-30]) /
        30
    )

    recent_volume = (
        sum(volumes[-10:]) /
        10
    )

    candle = candle_information(
        klines
    )

    score = 0
    reasons = []

    # -----------------------------------------------------
    # 1. Previous decline
    # -----------------------------------------------------

    if drawdown <= -4:
        score += 2

        reasons.append(
            "هبوط سابق واضح من القمة"
        )

    elif drawdown <= -2:
        score += 1

        reasons.append(
            "هبوط سابق متوسط"
        )

    # -----------------------------------------------------
    # 2. Narrow range
    # -----------------------------------------------------

    if recent_range <= 12:

        score += 2

        reasons.append(
            "النطاق السعري ضيق"
        )

    elif recent_range <= 18:

        score += 1

        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    # -----------------------------------------------------
    # 3. Volume retention
    # -----------------------------------------------------

    if old_volume > 0:

        volume_retention = (
            recent_volume /
            old_volume
        )

        if volume_retention >= 0.85:

            score += 2

            reasons.append(
                "الحجم ثابت وقوي نسبيًا أثناء التجميع"
            )

        elif volume_retention >= 0.65:

            score += 1

            reasons.append(
                "الحجم ما زال موجودًا بعد الهبوط"
            )

    # -----------------------------------------------------
    # 4. Lower wick / rejection
    # -----------------------------------------------------

    if candle[
        "lower_wick_ratio"
    ] >= 0.30:

        score += 1

        reasons.append(
            "رفض سعري واضح من الأسفل"
        )

    # -----------------------------------------------------
    # 5. Position inside range
    # -----------------------------------------------------

    if recent_high > recent_low:

        position = (
            closes[-1] - recent_low
        ) / (
            recent_high - recent_low
        )

        if position <= 0.60:

            score += 2

            reasons.append(
                "السعر في الجزء السفلي من نطاق التجميع"
            )

        elif position <= 0.75:

            score += 1

            reasons.append(
                "السعر داخل نطاق التجميع وليس عند قمته"
            )

    # -----------------------------------------------------
    # 6. Stability
    # -----------------------------------------------------

    stability = calculate_price_stability(
        klines,
        10
    )

    if stability <= 1.50:

        score += 1

        reasons.append(
            "حركة السعر مستقرة نسبيًا"
        )

    detected = score >= 4

    return detected, score, reasons


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 40:
        return "NEUTRAL", 0, []

    rows = klines[:-1]

    opens = [
        k[1]
        for k in rows
    ]

    closes = [
        k[4]
        for k in rows
    ]

    volumes = [
        k[5]
        for k in rows
    ]

    reasons = []

    vr = calculate_volume_ratio(
        volumes,
        20
    )

    recent5 = volumes[-5:]

    previous10 = volumes[-15:-5]

    rv = sum(recent5) / 5

    pv = (
        sum(previous10) /
        10
        if previous10
        else rv
    )

    rc = percentage_change(
        closes[-6],
        closes[-1]
    )

    start = max(
        0,
        len(rows) - 15
    )

    bull = sum(
        volumes[i]
        for i in range(
            start,
            len(rows)
        )
        if closes[i] > opens[i]
    )

    bear = sum(
        volumes[i]
        for i in range(
            start,
            len(rows)
        )
        if closes[i] < opens[i]
    )

    total = bull + bear

    buy_share = (
        bull / total
        if total > 0
        else 0.5
    )

    score = 0

    if (
        buy_share >= 0.56
        and vr >= 0.85
    ):

        score += 2

        reasons.append(
            "ضغط الشراء أعلى من البيع"
        )

    if (
        rv > pv * 1.05
        and rc >= -2.0
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن مع استقرار السعر"
        )

    if (
        buy_share <= 0.44
        and vr >= 0.85
    ):

        score -= 2

        reasons.append(
            "ضغط البيع أعلى من الشراء"
        )

    if (
        rv > pv * 1.05
        and rc <= -2.0
    ):

        score -= 1

        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
        )

    if score >= 2:
        return "INFLOW", score, reasons

    if score <= -2:
        return "OUTFLOW", score, reasons

    if (
        buy_share >= 0.53
        and rc >= -2.5
    ):

        reasons.append(
            "ميل شرائي خفيف؛ لم يصل لتأكيد الدخول"
        )

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

    e9 = calculate_ema(
        closes,
        9
    )

    e20 = calculate_ema(
        closes,
        20
    )

    e50 = calculate_ema(
        closes,
        50
    )

    if None in (
        e9,
        e20,
        e50
    ):
        return "UNKNOWN"

    c = closes[-1]

    if (
        e9 > e20 > e50
        and c > e20
    ):
        return "LONG"

    if (
        e9 < e20 < e50
        and c < e20
    ):
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# TIMEFRAME DETAILS
# =========================================================

def _timeframe_snapshot(
    klines
):

    trend = calculate_timeframe_trend(
        klines
    )

    closes = [
        k[4]
        for k in klines
    ]

    return (
        trend,
        calculate_ema(closes, 9),
        calculate_ema(closes, 20),
        calculate_ema(closes, 50)
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

        logger.info(
            "Symbol not found: %s",
            symbol
        )

        return None

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    k1d = get_bingx_klines(
        symbol,
        "1d",
        120
    )

    k4h = get_bingx_klines(
        symbol,
        "4h",
        160
    )

    k1h = get_bingx_klines(
        symbol,
        "1h",
        200
    )

    k30 = get_bingx_klines(
        symbol,
        "30m",
        160
    )

    k15 = get_bingx_klines(
        symbol,
        "15m",
        160
    )

    if not all(
        (
            k1d,
            k4h,
            k1h,
            k30,
            k15
        )
    ):
        return None

    # =====================================================
    # 1H CORE DATA
    # =====================================================

    closes = [
        k[4]
        for k in k1h
    ]

    volumes = [
        k[5]
        for k in k1h
    ]

    current = closes[-1]

    # =====================================================
    # TRENDS
    # =====================================================

    trend_1d = calculate_timeframe_trend(
        k1d
    )

    trend_4h = calculate_timeframe_trend(
        k4h
    )

    trend_1h = calculate_timeframe_trend(
        k1h
    )

    trend_30m = calculate_timeframe_trend(
        k30
    )

    trend_15m = calculate_timeframe_trend(
        k15
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

    # Previous RSI for momentum direction
    previous_rsi = calculate_rsi(
        closes[:-3]
    ) if len(closes) > 30 else rsi

    rsi_improving = (
        rsi >= previous_rsi + 1.5
    )

    volume_ratio = calculate_volume_ratio(
        volumes,
        20
    )

    volume_trend = calculate_volume_trend(
        volumes
    )

    atr = calculate_atr(
        k1h
    )

    support, resistance = calculate_support_resistance(
        k1h
    )

    structure = detect_market_structure(
        k1h
    )

    bottom_detected, bottom_score, bottom_reasons = detect_bottom_accumulation(
        k1h
    )

    liquidity_state, liquidity_score, liquidity_reasons = detect_liquidity_flow(
        k1h
    )

    drawdown = calculate_recent_drawdown(
        closes
    )

    # =====================================================
    # SUPPORT / RESISTANCE DISTANCE
    # =====================================================

    support_distance = (
        abs(current - support) /
        current *
        100
    )

    resistance_distance = (
        abs(resistance - current) /
        current *
        100
    )

    # =====================================================
    # RECENT MOVEMENT
    # =====================================================

    recent_change_2 = percentage_change(
        closes[-3],
        current
    )

    recent_change_6 = percentage_change(
        closes[-7],
        current
    )

    # More realistic anti-chasing detection
    pump_detected = (
        recent_change_2 >= 8
        or recent_change_6 >= 15
    )

    crash_detected = (
        recent_change_2 <= -8
        or recent_change_6 <= -15
    )

    # =====================================================
    # NEW ANTI-CHASE CONDITIONS
    # =====================================================

    strong_recent_rally = (
        recent_change_6 >= 5.0
    )

    extreme_recent_rally = (
        recent_change_6 >= 6.0
    )

    overbought = rsi > 70

    very_overbought = rsi > 75

    # =====================================================
    # 1H REVERSAL / TURNING CONDITIONS
    # =====================================================

    one_hour_bullish_setup = (
        (
            trend_1h == "LONG"
        )
        or
        (
            ema9 is not None
            and ema20 is not None
            and ema9 > ema20
            and (
                current >= ema20 * 0.995
            )
        )
    )

    one_hour_turning_long = (
        trend_1h == "LONG"
        or
        (
            ema9 is not None
            and ema20 is not None
            and ema9 > ema20
            and rsi_improving
        )
    )

    # =====================================================
    # ACCUMULATION QUALITY
    # =====================================================

    stability = calculate_price_stability(
        k1h,
        10
    )

    recent_range = calculate_recent_range(
        k1h,
        20
    )

    accumulation_score = 0
    accumulation_reasons = []

    if bottom_detected:

        accumulation_score += 3

        accumulation_reasons.extend(
            bottom_reasons[:3]
        )

    if recent_range <= 12:

        accumulation_score += 3

        accumulation_reasons.append(
            "النطاق السعري ضيق"
        )

    elif recent_range <= 18:

        accumulation_score += 2

        accumulation_reasons.append(
            "النطاق السعري يتقلص"
        )

    if stability <= 1.50:

        accumulation_score += 2

        accumulation_reasons.append(
            "ثبات سعري جيد"
        )

    elif stability <= 2.20:

        accumulation_score += 1

        accumulation_reasons.append(
            "ثبات سعري مقبول"
        )

    if volume_ratio >= 1.05:

        accumulation_score += 2

        accumulation_reasons.append(
            "الحجم يتحسن"
        )

    elif volume_ratio >= 0.75:

        accumulation_score += 1

        accumulation_reasons.append(
            "الحجم ما زال موجودًا"
        )

    if volume_trend == "RISING":

        accumulation_score += 2

        accumulation_reasons.append(
            "اتجاه الحجم صاعد"
        )

    if support_distance <= 1.50:

        accumulation_score += 2

        accumulation_reasons.append(
            "السعر قريب من الدعم"
        )

    elif support_distance <= 2.50:

        accumulation_score += 1

        accumulation_reasons.append(
            "السعر قريب نسبيًا من الدعم"
        )

    if liquidity_state == "INFLOW":

        accumulation_score += 2

        accumulation_reasons.append(
            "هناك ميل لدخول السيولة"
        )

    elif liquidity_state == "NEUTRAL":

        accumulation_score += 1

    if rsi <= 60:

        accumulation_score += 1

        accumulation_reasons.append(
            "RSI ليس في منطقة مطاردة"
        )

    if drawdown <= -5:

        accumulation_score += 1

        accumulation_reasons.append(
            "السعر ما زال أسفل القمة السابقة"
        )

    # =====================================================
    # SCORE
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []
    rejection_reasons = []

    # =====================================================
    # 1D CONTEXT
    # =====================================================

    if trend_1d == "LONG":

        long_score += 10

        analysis_lines.append(
            "1D يدعم الاتجاه الصاعد"
        )

    elif trend_1d == "SHORT":

        short_score += 10

        analysis_lines.append(
            "1D يدعم الاتجاه الهابط"
        )

    # =====================================================
    # 4H
    # =====================================================

    if trend_4h == "LONG":

        long_score += 22

        analysis_lines.append(
            "4H صاعد"
        )

    elif trend_4h == "SHORT":

        short_score += 22

        analysis_lines.append(
            "4H هابط"
        )

    else:

        analysis_lines.append(
            "4H محايد"
        )

    # =====================================================
    # 1H
    # =====================================================

    if trend_1h == "LONG":

        long_score += 14

        analysis_lines.append(
            "1H يدعم الدخول"
        )

    elif trend_1h == "SHORT":

        short_score += 14

        analysis_lines.append(
            "1H يدعم الشورت"
        )

    else:

        if one_hour_bullish_setup:

            long_score += 5

            analysis_lines.append(
                "1H محايد لكنه بدأ يتحسن"
            )

    # =====================================================
    # 30M / 15M
    # =====================================================

    if trend_30m == "LONG":

        long_score += 5

    elif trend_30m == "SHORT":

        short_score += 5

    if trend_15m == "LONG":

        long_score += 3

    elif trend_15m == "SHORT":

        short_score += 3

    # =====================================================
    # MARKET STRUCTURE
    # =====================================================

    if structure["bos"] == "BULLISH_BOS":

        long_score += 14

        analysis_lines.append(
            "BOS صاعد مؤكد على 1H"
        )

    elif structure["bos"] == "BEARISH_BOS":

        short_score += 14

        analysis_lines.append(
            "BOS هابط مؤكد على 1H"
        )

    elif structure["structure"] == "BULLISH":

        long_score += 5

        rejection_reasons.append(
            "الهيكل يميل للصعود لكن لا يوجد BOS مؤكد"
        )

    elif structure["structure"] == "BEARISH":

        short_score += 5

        rejection_reasons.append(
            "الهيكل يميل للهبوط لكن لا يوجد BOS مؤكد"
        )

    else:

        rejection_reasons.append(
            "لا يوجد BOS مؤكد"
        )

    # =====================================================
    # EMA
    # =====================================================

    if ema9 is not None and ema20 is not None:

        if ema9 > ema20:

            long_score += 7

            analysis_lines.append(
                "EMA9 فوق EMA20"
            )

        elif ema9 < ema20:

            short_score += 7

            analysis_lines.append(
                "EMA9 تحت EMA20"
            )

    if ema20 is not None and ema50 is not None:

        if ema20 > ema50:

            long_score += 4

        elif ema20 < ema50:

            short_score += 4

    # =====================================================
    # RSI
    # =====================================================

    if trend_4h == "LONG":

        if 40 <= rsi <= 65:

            long_score += 8

            analysis_lines.append(
                "RSI مناسب للصعود"
            )

        elif 35 <= rsi < 40:

            long_score += 4

            analysis_lines.append(
                "RSI منخفض نسبيًا وقد يدعم ارتدادًا"
            )

        elif 65 < rsi <= 70:

            long_score += 2

            rejection_reasons.append(
                "RSI مرتفع نسبيًا؛ الدخول يحتاج تأكيد أقوى"
            )

        elif rsi > 70:

            long_score -= 12

            rejection_reasons.append(
                "RSI فوق 70؛ ممنوع مطاردة LONG"
            )

    elif trend_4h == "SHORT":

        if 35 <= rsi <= 70:

            short_score += 8

        elif rsi < 30:

            short_score -= 12

            rejection_reasons.append(
                "RSI منخفض؛ ممنوع مطاردة الشورت"
            )

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if trend_4h == "LONG":
            long_score += 8

        elif trend_4h == "SHORT":
            short_score += 8

        analysis_lines.append(
            "الحجم قوي"
        )

    elif volume_ratio >= 0.70:

        if trend_4h == "LONG":
            long_score += 4

        elif trend_4h == "SHORT":
            short_score += 4

        analysis_lines.append(
            "الحجم مقبول"
        )

    else:

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

        long_score += 10

        analysis_lines.append(
            "دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 10

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

        # Important:
        # accumulation is NOT automatically LONG.

        if trend_4h == "LONG":

            long_score += 5

        elif trend_1d == "LONG":

            long_score += 3

        analysis_lines.append(
            "تم اكتشاف احتمال قاع/تجميع"
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
    # CRASH / PUMP
    # =====================================================

    if crash_detected:

        long_score -= 12
        short_score -= 15

        rejection_reasons.append(
            "حركة هبوط سريعة"
        )

    if pump_detected:

        long_score -= 15

        rejection_reasons.append(
            "حركة صعود سريعة؛ لا نطارد البامب"
        )

    # =====================================================
    # NEW ANTI-CHASE LOGIC
    # =====================================================

    if strong_recent_rally:

        long_score -= 8

        rejection_reasons.append(
            "ارتفاع أكثر من 5% مؤخرًا؛ خطر مطاردة السعر"
        )

    if extreme_recent_rally:

        long_score -= 10

        rejection_reasons.append(
            "ارتفاع قوي جدًا مؤخرًا؛ انتظار Pullback أفضل"
        )

    if overbought:

        long_score -= 10

        rejection_reasons.append(
            "RSI فوق 70؛ الدخول LONG يحتاج شروطًا استثنائية"
        )

    # =====================================================
    # CONFLICTS
    # =====================================================

    long_conflict = (
        trend_1h == "SHORT"
        and trend_30m == "SHORT"
        and trend_15m == "SHORT"
    )

    short_conflict = (
        trend_1h == "LONG"
        and trend_30m == "LONG"
        and trend_15m == "LONG"
    )

    # =====================================================
    # REVERSAL WATCH
    # =====================================================

    reversal_watch = (
        trend_1d == "LONG"
        and trend_4h == "NEUTRAL"
        and one_hour_turning_long
        and not crash_detected
        and not pump_detected
        and not very_overbought
        and resistance_distance > 0.50
    )

    # Stronger reversal quality
    reversal_score = 0

    if reversal_watch:

        reversal_score += 30

        if trend_1h == "LONG":

            reversal_score += 20

        elif one_hour_bullish_setup:

            reversal_score += 10

        if rsi_improving:

            reversal_score += 10

        if ema9 > ema20:

            reversal_score += 10

        if volume_ratio >= 0.90:

            reversal_score += 10

        if liquidity_state == "INFLOW":

            reversal_score += 10

        if structure["bos"] == "BULLISH_BOS":

            reversal_score += 10

        reversal_score = min(
            100,
            reversal_score
        )

    # =====================================================
    # ACCUMULATION WATCH
    # =====================================================

    accumulation_watch = (
        accumulation_score >= 8
        and not crash_detected
        and not pump_detected
        and not very_overbought
        and resistance_distance > 0.35
        and liquidity_state != "OUTFLOW"
    )

    # If RSI is elevated, accumulation is less trustworthy.
    if rsi > 65:

        accumulation_watch = (
            accumulation_watch
            and support_distance <= 1.50
        )

    # =====================================================
    # ENTRY DECISION
    # =====================================================

    direction = "NO TRADE"

    state = (
        "NO TRADE - التأكيد غير مكتمل"
    )

    entry_score = 0

    # =====================================================
    # LONG ENTRY
    # =====================================================

    if trend_4h == "LONG":

        entry_score = max(
            0,
            long_score
        )

        confirmations = sum([
            trend_1h == "LONG",
            trend_30m == "LONG",
            trend_15m == "LONG",
            structure["bos"] == "BULLISH_BOS",
            structure["structure"] == "BULLISH",
            liquidity_state == "INFLOW",
            volume_ratio >= 0.70,
            volume_trend == "RISING",
            ema9 > ema20 if ema9 is not None and ema20 is not None else False,
            35 <= rsi <= 68
        ])

        # -------------------------------------------------
        # HARD LONG BLOCKS
        # -------------------------------------------------

        if rsi > 70:

            state = (
                "REVERSAL WATCH / WAIT - RSI مرتفع"
            )

            rejection_reasons.append(
                "RSI فوق 70 يمنع مطاردة LONG"
            )

        elif extreme_recent_rally:

            state = (
                "REVERSAL WATCH / WAIT - حركة قوية"
            )

            rejection_reasons.append(
                "انتظار Pullback بعد الحركة القوية"
            )

        elif strong_recent_rally and rsi > 65:

            state = (
                "REVERSAL WATCH / WAIT - مطاردة السعر"
            )

            rejection_reasons.append(
                "الحركة تجاوزت 5% وRSI مرتفع"
            )

        elif pump_detected:

            state = (
                "NO TRADE - حركة صعود سريعة"
            )

        elif long_conflict:

            state = (
                "NO TRADE - الأطر القصيرة تعاكس الاتجاه"
            )

        elif resistance_distance <= 0.20:

            state = (
                "NO TRADE - السعر قريب جدًا من المقاومة"
            )

            rejection_reasons.append(
                "لا يوجد مجال آمن قبل المقاومة"
            )

        elif (
            long_score >= 62
            and confirmations >= 5
            and not overbought
            and not strong_recent_rally
        ):

            direction = "LONG"

            state = (
                "ENTRY READY - تأكيدات دخول قوية"
            )

        elif (
            long_score >= 57
            and confirmations >= 5
            and (
                liquidity_state == "INFLOW"
                or volume_ratio >= 1.0
            )
            and rsi <= 68
            and not strong_recent_rally
        ):

            direction = "LONG"

            state = (
                "ENTRY READY - تأكيد جيد"
            )

        else:

            state = (
                "NO TRADE - نحتاج تأكيد إضافي"
            )

    # =====================================================
    # SHORT ENTRY
    # =====================================================

    elif trend_4h == "SHORT":

        entry_score = max(
            0,
            short_score
        )

        confirmations = sum([
            trend_1h == "SHORT",
            trend_30m == "SHORT",
            trend_15m == "SHORT",
            structure["bos"] == "BEARISH_BOS",
            structure["structure"] == "BEARISH",
            liquidity_state == "OUTFLOW",
            volume_ratio >= 0.70,
            volume_trend == "RISING",
            ema9 < ema20 if ema9 is not None and ema20 is not None else False,
            32 <= rsi <= 72
        ])

        if rsi < 30:

            state = (
                "NO TRADE - RSI منخفض"
            )

            rejection_reasons.append(
                "ممنوع مطاردة الشورت في القاع"
            )

        elif crash_detected:

            state = (
                "NO TRADE - هبوط سريع"
            )

        elif short_conflict:

            state = (
                "NO TRADE - الأطر القصيرة تعاكس الاتجاه"
            )

        elif support_distance <= 0.20:

            state = (
                "NO TRADE - السعر قريب جدًا من الدعم"
            )

            rejection_reasons.append(
                "لا يوجد مجال آمن قبل الدعم"
            )

        elif (
            short_score >= 62
            and confirmations >= 5
        ):

            direction = "SHORT"

            state = (
                "ENTRY READY - تأكيدات دخول قوية"
            )

        elif (
            short_score >= 57
            and confirmations >= 5
            and (
                liquidity_state == "OUTFLOW"
                or volume_ratio >= 1.0
            )
        ):

            direction = "SHORT"

            state = (
                "ENTRY READY - تأكيد جيد"
            )

        else:

            state = (
                "NO TRADE - نحتاج تأكيد إضافي"
            )

    # =====================================================
    # 4H NEUTRAL
    # =====================================================

    else:

        entry_score = 0

        # -------------------------------------------------
        # REVERSAL WATCH HAS PRIORITY
        # -------------------------------------------------

        if reversal_watch:

            state = (
                "REVERSAL WATCH / WAIT - "
                "1D صاعد و4H محايد و1H بدأ يتحول للصعود"
            )

            entry_score = int(
                max(
                    0,
                    reversal_score
                )
            )

            analysis_lines.append(
                "إشارة انعكاس مبكرة: 1D صاعد و4H محايد"
            )

            analysis_lines.append(
                "1H بدأ يتحسن؛ ننتظر تأكيدًا أقوى"
            )

            rejection_reasons.append(
                "لم يتم اعتماد LONG لأن 4H لم يتحول للصعود بعد"
            )

        # -------------------------------------------------
        # ACCUMULATION WATCH
        # -------------------------------------------------

        elif accumulation_watch:

            state = (
                "ACCUMULATION WATCH - "
                "تجميع جيد لكن ليس صفقة LONG"
            )

            entry_score = int(
                max(
                    0,
                    min(
                        100,
                        accumulation_score * 7
                    )
                )
            )

            analysis_lines.append(
                "تجميع مبكر: المراقبة قبل تأكيد الدخول"
            )

            rejection_reasons.append(
                "التجميع وحده لا يكفي لفتح LONG"
            )

        else:

            state = (
                "NO TRADE - 4H محايد"
            )

    # =====================================================
    # ADD ACCUMULATION INFO
    # =====================================================

    if accumulation_score >= 6:

        analysis_lines.append(
            f"قوة التجميع: {accumulation_score}/20 تقريبًا"
        )

    # =====================================================
    # ATR
    # =====================================================

    if not atr or atr <= 0:

        atr = current * 0.01

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    entry_min = None
    entry_max = None

    stop_loss = None

    tp1 = None
    tp2 = None
    tp3 = None

    # =====================================================
    # LONG LEVELS
    # =====================================================

    if direction == "LONG":

        if current >= resistance * 0.995:

            direction = "NO TRADE"

            state = (
                "NO TRADE - السعر قريب جدًا من المقاومة"
            )

            rejection_reasons.append(
                "السعر قريب جدًا من المقاومة"
            )

        else:

            entry_min = max(
                support,
                current - atr * 0.35
            )

            entry_max = current

            stop_loss = min(
                support - atr * 0.20,
                current - atr * 0.90
            )

            risk = max(
                current - stop_loss,
                atr * 0.50
            )

            tp1 = current + risk * 1.2
            tp2 = current + risk * 2.0
            tp3 = current + risk * 3.0

            if resistance > current:

                tp1 = min(
                    tp1,
                    resistance
                )

                if tp1 <= current:

                    tp1 = (
                        current +
                        risk
                    )

    # =====================================================
    # SHORT LEVELS
    # =====================================================

    elif direction == "SHORT":

        if current <= support * 1.005:

            direction = "NO TRADE"

            state = (
                "NO TRADE - السعر قريب جدًا من الدعم"
            )

            rejection_reasons.append(
                "السعر قريب جدًا من الدعم"
            )

        else:

            entry_min = current

            entry_max = min(
                resistance,
                current + atr * 0.35
            )

            stop_loss = max(
                resistance + atr * 0.20,
                current + atr * 0.90
            )

            risk = max(
                stop_loss - current,
                atr * 0.50
            )

            tp1 = current - risk * 1.2
            tp2 = current - risk * 2.0
            tp3 = current - risk * 3.0

            if support < current:

                tp1 = max(
                    tp1,
                    support
                )

                if tp1 >= current:

                    tp1 = (
                        current -
                        risk
                    )

    # =====================================================
    # NO TRADE LEVELS
    # =====================================================

    if direction == "NO TRADE":

        entry_min = None
        entry_max = None
        stop_loss = None
        tp1 = None
        tp2 = None
        tp3 = None

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if liquidity_state == "INFLOW":

        buy_pressure = (
            60 +
            min(
                volume_ratio * 6,
                25
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            40 -
            min(
                volume_ratio * 5,
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
    # FINAL SCORE
    # =====================================================

    final_score = int(
        max(
            0,
            min(
                100,
                entry_score
            )
        )
    )

    # =====================================================
    # FINAL RETURN
    # =====================================================

    return {

        "symbol": symbol,

        "direction": direction,

        "score": final_score,

        "entry_score": final_score,

        "state": state,

        "price": smart_round(
            current
        ),

        "rsi": rsi,

        "previous_rsi": previous_rsi,

        "rsi_improving": rsi_improving,

        "volume_ratio": volume_ratio,

        "volume_trend": volume_trend,

        "liquidity_state": liquidity_state,

        "liquidity_score": liquidity_score,

        "bottom_detected": bottom_detected,

        "bottom_score": bottom_score,

        "accumulation_score": accumulation_score,

        "accumulation_watch": accumulation_watch,

        "reversal_watch": reversal_watch,

        "reversal_score": int(
            reversal_score
        ),

        "drawdown": drawdown,

        "recent_range": round(
            recent_range,
            2
        ),

        "price_stability": stability,

        "buy_pressure": buy_pressure,

        "trend": (
            "UP"
            if trend_4h == "LONG"
            else "DOWN"
            if trend_4h == "SHORT"
            else "NEUTRAL"
        ),

        "trend_1d": trend_1d,

        "trend_4h": trend_4h,

        "trend_1h": trend_1h,

        "trend_30m": trend_30m,

        "trend_15m": trend_15m,

        "structure": structure["structure"],

        "bos": structure["bos"],

        "liquidity_zone": structure[
            "liquidity_zone"
        ],

        "recent_change_2": round(
            recent_change_2,
            2
        ),

        "recent_change_6": round(
            recent_change_6,
            2
        ),

        "strong_recent_rally": strong_recent_rally,

        "extreme_recent_rally": extreme_recent_rally,

        "overbought": overbought,

        "crash_detected": crash_detected,

        "pump_detected": pump_detected,

        "entry_min": (
            smart_round(entry_min)
            if entry_min is not None
            else None
        ),

        "entry_max": (
            smart_round(entry_max)
            if entry_max is not None
            else None
        ),

        "stop_loss": (
            smart_round(stop_loss)
            if stop_loss is not None
            else None
        ),

        "tp1": (
            smart_round(tp1)
            if tp1 is not None
            else None
        ),

        "tp2": (
            smart_round(tp2)
            if tp2 is not None
            else None
        ),

        "tp3": (
            smart_round(tp3)
            if tp3 is not None
            else None
        ),

        "support": smart_round(
            support
        ),

        "resistance": smart_round(
            resistance
        ),

        "support_distance": round(
            support_distance,
            2
        ),

        "resistance_distance": round(
            resistance_distance,
            2
        ),

        "long_score": int(
            max(
                0,
                min(
                    100,
                    long_score
                )
            )
        ),

        "short_score": int(
            max(
                0,
                min(
                    100,
                    short_score
                )
            )
        ),

        "analysis_lines": (
            analysis_lines
        ),

        "liquidity_reasons": (
            liquidity_reasons
        ),

        "bottom_reasons": (
            bottom_reasons
        ),

        "accumulation_reasons": (
            list(
                dict.fromkeys(
                    accumulation_reasons
                )
            )
        ),

        "structure_reasons": (
            structure["reasons"]
        ),

        "rejection_reasons": list(
            dict.fromkeys(
                rejection_reasons
            )
        )
    }


# =========================================================
# TOP FUTURES SYMBOLS
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

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).replace(
            "-",
            ""
        ).upper()

        if (
            symbol not in symbols
            or not symbol.endswith("USDT")
        ):
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

            if volume <= 0:
                continue

            # Keep liquidity first,
            # with a modest movement bonus.
            candidates.append(
                (
                    symbol,
                    volume * (
                        1 +
                        min(
                            change / 100,
                            0.30
                        )
                    )
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
        s
        for s, _ in candidates[:limit]
    ]


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market(
    limit=5
):

    # -----------------------------------------------------
    # We still analyze the top liquid 20.
    # But ranking is now by signal quality,
    # not only raw score.
    # -----------------------------------------------------

    symbols = get_top_futures_symbols(
        20
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

            state = data.get(
                "state",
                ""
            )

            direction = data.get(
                "direction",
                "NO TRADE"
            )

            # -------------------------------------------------
            # ONLY SHOW:
            # ENTRY READY
            # REVERSAL WATCH
            # ACCUMULATION WATCH
            # -------------------------------------------------

            is_entry = (
                direction in (
                    "LONG",
                    "SHORT"
                )
                and
                "ENTRY READY" in state
            )

            is_reversal = (
                "REVERSAL WATCH" in state
            )

            is_accumulation = (
                "ACCUMULATION WATCH" in state
            )

            if not (
                is_entry
                or is_reversal
                or is_accumulation
            ):
                continue

            # -------------------------------------------------
            # HARD SAFETY FILTERS
            # -------------------------------------------------

            if data.get(
                "crash_detected"
            ):
                continue

            # -------------------------------------------------
            # LONG SAFETY
            # -------------------------------------------------

            if direction == "LONG":

                if data["rsi"] > 70:

                    # A WATCH state may remain visible,
                    # but it must never pass as ENTRY READY.
                    if is_entry:
                        continue

                if (
                    data["resistance_distance"]
                    < 0.20
                    and is_entry
                ):
                    continue

                if (
                    data["recent_change_6"] >= 6
                    and is_entry
                ):
                    continue

            # -------------------------------------------------
            # SHORT SAFETY
            # -------------------------------------------------

            elif direction == "SHORT":

                if (
                    data["rsi"] < 30
                    and is_entry
                ):
                    continue

                if (
                    data["support_distance"]
                    < 0.20
                    and is_entry
                ):
                    continue

            # -------------------------------------------------
            # ACCUMULATION SAFETY
            # -------------------------------------------------

            if is_accumulation:

                if data["accumulation_score"] < 8:
                    continue

                if data["liquidity_state"] == "OUTFLOW":
                    continue

            # -------------------------------------------------
            # REVERSAL SAFETY
            # -------------------------------------------------

            if is_reversal:

                if data["trend_1d"] != "LONG":
                    continue

                if data["trend_4h"] != "NEUTRAL":
                    continue

                if data["rsi"] > 75:
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

        time.sleep(
            0.20
        )

    # =====================================================
    # CATEGORY RANK
    # =====================================================

    def category_rank(data):

        state = data.get(
            "state",
            ""
        )

        if "ENTRY READY" in state:
            return 3

        if "REVERSAL WATCH" in state:
            return 2

        if "ACCUMULATION WATCH" in state:
            return 1

        return 0

    # =====================================================
    # SORT
    # =====================================================

    results.sort(
        key=lambda x: (
            category_rank(x),

            # Entry quality
            x.get(
                "entry_score",
                0
            ),

            # Reversal quality
            x.get(
                "reversal_score",
                0
            ),

            # Accumulation quality
            x.get(
                "accumulation_score",
                0
            ),

            # Bottom
            x.get(
                "bottom_score",
                0
            ),

            # Liquidity
            x.get(
                "liquidity_score",
                0
            ),

            # Volume
            x.get(
                "volume_ratio",
                0
            )
        ),
        reverse=True
    )

    return results[:limit]


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(
    data
):

    direction = data[
        "direction"
    ]

    state = data[
        "state"
    ]

    # -----------------------------------------------------
    # Direction emoji
    # -----------------------------------------------------

    if "ENTRY READY
