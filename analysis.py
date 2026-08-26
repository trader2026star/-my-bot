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

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 90

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
    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None

    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (
            time.time() - _LAST_REQUEST_TIME
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

    except (
        requests.RequestException,
        ValueError
    ) as exc:

        logger.warning(
            "BingX request failed: %s",
            exc
        )

        return None


# =========================================================
# SYMBOL
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

        raw = str(
            item.get("symbol", "")
        ).upper()

        if not raw.endswith("-USDT"):
            continue

        status = item.get("status")

        if status not in (
            1,
            "1",
            None
        ):
            continue

        symbols.add(
            raw.replace("-", "")
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

    key = (
        symbol,
        interval,
        limit
    )

    now = time.time()

    cached = _KLINE_CACHE.get(key)

    if cached:

        if (
            now - cached[0]
            < KLINE_CACHE_SECONDS
        ):
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

            elif (
                isinstance(row, list)
                and len(row) >= 6
            ):

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
# INDICATORS
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    ema = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


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
            (
                avg_gain
                * (period - 1)
                + gains[i]
            )
            / period
        )

        avg_loss = (
            (
                avg_loss
                * (period - 1)
                + losses[i]
            )
            / period
        )

    if avg_loss == 0:
        return 100.0

    return round(
        100 - (
            100 /
            (
                1
                + avg_gain
                / avg_loss
            )
        ),
        2
    )


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
        sum(trs[:period])
        / period
    )

    for value in trs[period:]:

        atr = (
            atr * (period - 1)
            + value
        ) / period

    return atr


def calculate_volume_ratio(
    volumes,
    period=20
):

    if len(volumes) < period + 1:
        return 1.0

    avg = (
        sum(
            volumes[-period - 1:-1]
        )
        / period
    )

    if avg <= 0:
        return 1.0

    return round(
        volumes[-1] / avg,
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

    if ratio >= 1.10:
        return "RISING"

    if ratio <= 0.90:
        return "FALLING"

    return "NEUTRAL"


def percentage_change(
    old_price,
    new_price
):

    if not old_price:
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


# =========================================================
# CANDLE
# =========================================================

def candle_information(
    klines
):

    o, h, l, c = (
        klines[-1][1:5]
    )

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
        "body_ratio":
            abs(c - o) / r,

        "lower_wick_ratio":
            (
                min(o, c) - l
            ) / r,

        "upper_wick_ratio":
            (
                h - max(o, c)
            ) / r,

        "bullish": c > o,

        "bearish": c < o
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

    high = max(window)

    if high <= 0:
        return 0.0

    return round(
        (
            (
                closes[-1]
                - high
            )
            / high
        ) * 100,
        2
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
        abs(current - rl)
        / current
        * 100
    )

    hd = (
        abs(rh - current)
        / current
        * 100
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

    drawdown = (
        (
            recent_low
            - old_high
        )
        / old_high
        * 100
    )

    recent_range = (
        (
            recent_high
            - recent_low
        )
        / recent_low
        * 100
        if recent_low
        else 0
    )

    old_volume = (
        sum(volumes[-60:-30])
        / 30
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

    if drawdown <= -4:

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
        >= old_volume * 0.65
    ):

        score += 1

        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if candle[
        "lower_wick_ratio"
    ] >= 0.25:

        score += 1

        reasons.append(
            "رفض سعري من الأسفل"
        )

    if recent_high > recent_low:

        position = (
            (
                closes[-1]
                - recent_low
            )
            / (
                recent_high
                - recent_low
            )
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
# LIQUIDITY
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 40:
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

    vr = calculate_volume_ratio(
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

    bullish_volume = sum(
        volumes[i]
        for i in range(
            len(klines) - 15,
            len(klines)
        )
        if closes[i] > opens[i]
    )

    bearish_volume = sum(
        volumes[i]
        for i in range(
            len(klines) - 15,
            len(klines)
        )
        if closes[i] < opens[i]
    )

    score = 0

    if (
        bullish_volume
        > bearish_volume * 1.15
        and vr >= 0.70
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أكبر"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and recent_change >= -2.0
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن مع استقرار السعر"
        )

    if (
        bearish_volume
        > bullish_volume * 1.15
        and vr >= 0.70
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أكبر"
        )

    if (
        recent_volume
        > previous_volume * 1.05
        and recent_change <= -2.0
    ):

        score -= 1

        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
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

    current = closes[-1]

    if (
        e9 > e20
        and e20 > e50
        and current > e20
    ):
        return "LONG"

    if (
        e9 < e20
        and e20 < e50
        and current < e20
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

    closes = [
        k[4]
        for k in k1h
    ]

    volumes = [
        k[5]
        for k in k1h
    ]

    current = closes[-1]

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
        k1h
    )

    support, resistance = (
        calculate_support_resistance(
            k1h
        )
    )

    structure = detect_market_structure(
        k1h
    )

    (
        bottom_detected,
        bottom_score,
        bottom_reasons
    ) = detect_bottom_accumulation(
        k1h
    )

    (
        liquidity_state,
        liquidity_score,
        liquidity_reasons
    ) = detect_liquidity_flow(
        k1h
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

    recent_change_2 = percentage_change(
        closes[-3],
        current
    )

    recent_change_6 = percentage_change(
        closes[-7],
        current
    )

    crash_detected = (
        recent_change_2 <= -8
        or recent_change_6 <= -15
    )

    pump_detected = (
        recent_change_2 >= 8
        or recent_change_6 >= 15
    )

    long_score = 0
    short_score = 0

    analysis_lines = []
    rejection_reasons = []

    # =====================================================
    # 1D
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

        long_score += 25

        analysis_lines.append(
            "4H هو الاتجاه الرئيسي: صاعد"
        )

    elif trend_4h == "SHORT":

        short_score += 25

        analysis_lines.append(
            "4H هو الاتجاه الرئيسي: هابط"
        )

    else:

        analysis_lines.append(
            "4H محايد"
        )

    # =====================================================
    # 1H
    # =====================================================

    if trend_1h == "LONG":

        long_score += 12

        analysis_lines.append(
            "1H يدعم الدخول"
        )

    elif trend_1h == "SHORT":

        short_score += 12

        analysis_lines.append(
            "1H يدعم الشورت"
        )

    # =====================================================
    # 30M
    # =====================================================

    if trend_30m == "LONG":

        long_score += 5

    elif trend_30m == "SHORT":

        short_score += 5

    # =====================================================
    # 15M
    # =====================================================

    if trend_15m == "LONG":

        long_score += 3

    elif trend_15m == "SHORT":

        short_score += 3

    # =====================================================
    # STRUCTURE
    # =====================================================

    if structure["bos"] == "BULLISH_BOS":

        long_score += 15

        analysis_lines.append(
            "BOS صاعد مؤكد على 1H"
        )

    elif structure["bos"] == "BEARISH_BOS":

        short_score += 15

        analysis_lines.append(
            "BOS هابط مؤكد على 1H"
        )

    elif structure["structure"] == "BULLISH":

        long_score += 6

        rejection_reasons.append(
            "لا يوجد BOS مؤكد، لكن الهيكل يميل للصعود"
        )

    elif structure["structure"] == "BEARISH":

        short_score += 6

        rejection_reasons.append(
            "لا يوجد BOS مؤكد، لكن الهيكل يميل للهبوط"
        )

    else:

        rejection_reasons.append(
            "لا يوجد BOS مؤكد"
        )

    # =====================================================
    # EMA
    # =====================================================

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

    if ema20 > ema50:

        long_score += 4

    elif ema20 < ema50:

        short_score += 4

    # =====================================================
    # RSI
    # =====================================================

    if trend_4h == "LONG":

        if 38 <= rsi <= 70:

            long_score += 8

            analysis_lines.append(
                "RSI مناسب للصعود"
            )

        elif 32 <= rsi < 38:

            long_score += 4

            analysis_lines.append(
                "RSI منخفض نسبياً وقد يدعم الارتداد"
            )

        elif rsi > 75:

            long_score -= 8

            rejection_reasons.append(
                "RSI مرتفع ولا نطارد الصعود"
            )

    elif trend_4h == "SHORT":

        if 35 <= rsi <= 72:

            short_score += 8

        elif rsi < 30:

            short_score -= 12

            rejection_reasons.append(
                "RSI منخفض؛ خطر البيع في القاع"
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

    elif volume_ratio >= 0.65:

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

        long_score += 12

        analysis_lines.append(
            "دخول سيولة محتمل"
        )

    elif liquidity_state == "OUTFLOW":

        short_score += 12

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

        if trend_4h == "LONG":
            long_score += 5

        analysis_lines.append(
            "تم اكتشاف احتمال قاع/تجميع"
        )

    # =====================================================
    # PRICE LOCATION
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
    # PUMP / CRASH
    # =====================================================

    if crash_detected:

        long_score -= 12
        short_score -= 15

        rejection_reasons.append(
            "حركة هبوط سريعة"
        )

    if pump_detected:

        long_score -= 10

        rejection_reasons.append(
            "حركة صعود سريعة؛ لا نطارد البامب"
        )

    # =====================================================
    # CONFLICT
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

    direction = "NO TRADE"

    state = (
        "NO TRADE - التأكيد غير مكتمل"
    )

    entry_score = 0

    # =====================================================
    # LONG
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
            volume_ratio >= 0.65,
            volume_trend == "RISING",
            ema9 > ema20,
            32 <= rsi <= 70
        ])

        if crash_detected:

            state = (
                "NO TRADE - حركة هبوط سريعة"
            )

        elif (
            pump_detected
            and resistance_distance <= 0.70
        ):

            state = (
                "NO TRADE - مطاردة صعود قرب المقاومة"
            )

        elif long_conflict:

            state = (
                "NO TRADE - الأطر القصيرة تعاكس الاتجاه"
            )

        elif resistance_distance <= 0.12:

            state = (
                "NO TRADE - السعر ملاصق للمقاومة"
            )

        elif (
            long_score >= 52
            and confirmations >= 3
        ):

            direction = "LONG"

            state = (
                "4H صاعد + تأكيدات دخول جيدة"
            )

        elif (
            long_score >= 48
            and confirmations >= 3
            and (
                liquidity_state == "INFLOW"
                or volume_ratio >= 0.90
                or structure["structure"] == "BULLISH"
            )
        ):

            direction = "LONG"

            state = (
                "4H صاعد + فرصة دخول مبكرة"
            )

        else:

            state = (
                "NO TRADE - نحتاج تأكيد إضافي"
            )

    # =====================================================
    # SHORT
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
            volume_ratio >= 0.65,
            volume_trend == "RISING",
            ema9 < ema20,
            32 <= rsi <= 72
        ])

        if rsi < 30:

            state = (
                "NO TRADE - RSI منخفض؛ ممنوع مطاردة الشورت"
            )

        elif crash_detected:

            state = (
                "NO TRADE - هبوط سريع؛ ممنوع مطاردة الشورت"
            )

        elif short_conflict:

            state = (
                "NO TRADE - الأطر القصيرة تعاكس الاتجاه"
            )

        elif support_distance <= 0.12:

            state = (
                "NO TRADE - السعر ملاصق للدعم"
            )

        elif (
            short_score >= 52
            and confirmations >= 3
        ):

            direction = "SHORT"

            state = (
                "4H هابط + تأكيدات دخول جيدة"
            )

        elif (
            short_score >= 48
            and confirmations >= 3
            and (
                liquidity_state == "OUTFLOW"
                or volume_ratio >= 0.90
                or structure["structure"] == "BEARISH"
            )
        ):

            direction = "SHORT"

            state = (
                "4H هابط + فرصة دخول مبكرة"
            )

        else:

            state = (
                "NO TRADE - نحتاج تأكيد إضافي"
            )

    else:

        entry_score = 0

        state = (
            "NO TRADE - 4H محايد"
        )

    # =====================================================
    # ATR
    # =====================================================

    if not atr or atr <= 0:
        atr = current * 0.01

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
                "NO TRADE - السعر قريب جداً من المقاومة"
            )

            rejection_reasons.append(
                "السعر قريب جداً من المقاومة"
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
                        current
                        + risk
                    )

    # =====================================================
    # SHORT LEVELS
    # =====================================================

    elif direction == "SHORT":

        if current <= support * 1.005:

            direction = "NO TRADE"

            state = (
                "NO TRADE - السعر قريب جداً من الدعم"
            )

            rejection_reasons.append(
                "السعر قريب جداً من الدعم"
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
                        current
                        - risk
                    )

    # =====================================================
    # CLEAR LEVELS
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
            60
            + min(
                volume_ratio * 6,
                25
            )
        )

    elif liquidity_state == "OUTFLOW":

        buy_pressure = (
            40
            - min(
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

    final_score = max(
        0,
        min(
            100,
            int(entry_score)
        )
    )

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

        "volume_ratio": volume_ratio,

        "volume_trend": volume_trend,

        "liquidity_state": liquidity_state,

        "liquidity_score": liquidity_score,

        "bottom_detected": bottom_detected,

        "bottom_score": bottom_score,

        "drawdown": drawdown,

        "buy_pressure": buy_pressure,

        "trend": (
            "UP"
            if trend_4h == "LONG"
            else
            "DOWN"
            if trend_4h == "SHORT"
            else
            "NEUTRAL"
        ),

        "trend_1d": trend_1d,

        "trend_4h": trend_4h,

        "trend_1h": trend_1h,

        "trend_30m": trend_30m,

        "trend_15m": trend_15m,

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
            (
                smart_round(entry_min)
                if entry_min is not None
                else None
            ),

        "entry_max":
            (
                smart_round(entry_max)
                if entry_max is not None
                else None
            ),

        "stop_loss":
            (
                smart_round(stop_loss)
                if stop_loss is not None
                else None
            ),

        "tp1":
            (
                smart_round(tp1)
                if tp1 is not None
                else None
            ),

        "tp2":
            (
                smart_round(tp2)
                if tp2 is not None
                else None
            ),

        "tp3":
            (
                smart_round(tp3)
                if tp3 is not None
                else None
            ),

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
            list(
                dict.fromkeys(
                    rejection_reasons
                )
            )
    }


# =========================================================
# TOP FUTURES
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

            score = (
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
        for symbol, _
        in candidates[:limit]
    ]


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market(limit=5):

    """
    يفحص مجموعة كبيرة من العملات
    ثم يرجع أفضل الفرص فقط.

    limit = عدد الفرص التي سيتم إرسالها.
    """

    # -----------------------------------------------------
    # لا نكتفي بعملة واحدة
    # -----------------------------------------------------

    symbols = get_top_futures_symbols(
        30
    )

    if not symbols:

        logger.warning(
            "SCAN: no futures symbols found"
        )

        return []

    results = []

    logger.info(
        "SCAN: checking %s symbols",
        len(symbols)
    )

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        # -------------------------------------------------
        # لو BingX دخل Rate Limit
        # -------------------------------------------------

        with _RATE_LOCK:

            rate_limited = (
                time.time()
                < _RATE_LIMIT_UNTIL
            )

        if rate_limited:

            logger.warning(
                "SCAN stopped because BingX rate limit is active"
            )

            break

        try:

            logger.info(
                "SCAN %s/%s -> %s",
                index,
                len(symbols),
                symbol
            )

            data = get_coin_analysis(
                symbol
            )

            if not data:

                continue

            direction = data.get(
                "direction"
            )

            score = data.get(
                "score",
                0
            )

            trend_4h = data.get(
                "trend_4h"
            )

            # -------------------------------------------------
            # يجب أن تكون صفقة حقيقية
            # -------------------------------------------------

            if direction not in (
                "LONG",
                "SHORT"
            ):

                continue

            # -------------------------------------------------
            # 4H MUST MATCH
            # -------------------------------------------------

            if trend_4h != direction:

                logger.info(
                    "SCAN rejected %s: 4H mismatch",
                    symbol
                )

                continue

            # -------------------------------------------------
            # SCORE
            # -------------------------------------------------

            if score < 48:

                logger.info(
                    "SCAN rejected %s: score=%s",
                    symbol,
                    score
                )

                continue

            # -------------------------------------------------
            # CRASH
            # -------------------------------------------------

            if data.get(
                "crash_detected"
            ):

                continue

            # -------------------------------------------------
            # LONG
            # -------------------------------------------------

            if direction == "LONG":

                if (
                    data.get(
                        "resistance_distance",
                        999
                    )
                    < 0.20
                ):

                    continue

                if (
                    data.get(
                        "rsi",
                        50
                    )
                    > 75
                ):

                    continue

            # -------------------------------------------------
            # SHORT
            # -------------------------------------------------

            else:

                if (
                    data.get(
                        "support_distance",
                        999
                    )
                    < 0.20
                ):

                    continue

                if (
                    data.get(
                        "rsi",
                        50
                    )
                    < 30
                ):

                    continue

            # -------------------------------------------------
            # ACCEPT
            # -------------------------------------------------

            results.append(
                data
            )

            logger.info(
                "SCAN ACCEPTED %s | %s | score=%s",
                symbol,
                direction,
                score
            )

        except Exception as exc:

            logger.exception(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        # -------------------------------------------------
        # حماية إضافية للـ API
        # -------------------------------------------------

        time.sleep(0.20)

    # =====================================================
    # SORT
    # =====================================================

    results.sort(
        key=lambda x: (
            x.get(
                "score",
                0
            ),
            x.get(
                "liquidity_score",
                0
            ),
            x.get(
                "volume_ratio",
                0
            ),
            x.get(
                "buy_pressure",
                0
            )
        ),
        reverse=True
    )

    logger.info(
        "SCAN FINISHED: %s opportunities",
        len(results)
    )

    # -----------------------------------------------------
    # يرجع أكثر من عملة
    # -----------------------------------------------------

    return results[:limit]


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(
    data
):

    direction = data["direction"]

    emoji = (
        "🟢"
        if direction == "LONG"
        else
        "🔴"
        if direction == "SHORT"
        else
        "🟡"
    )

    liquidity = (
        "🟢 دخول سيولة محتمل"
        if data["liquidity_state"]
        == "INFLOW"
        else
        "🔴 خروج سيولة محتمل"
        if data["liquidity_state"]
        == "OUTFLOW"
        else
        "🟡 سيولة محايدة"
    )

    bos_text = (
        "🟢 BULLISH"
        if data["bos"]
        == "BULLISH_BOS"
        else
        "🔴 BEARISH"
        if data["bos"]
        == "BEARISH_BOS"
        else
        "⚪ NONE"
    )

    bottom = (
        "🟢 نعم — عامل مساعد"
        if data["bottom_detected"]
        else
        "🟡 غير مؤكد"
    )

    lines = [

        "🤖 BingX AI Scanner",

        "",

        f"💎 العملة: {data['symbol']}",

        f"📈 الاتجاه النهائي: {emoji} {direction}",

        f"⭐ Entry Score: {data['entry_score']}/100",

        "",

        f"🧠 الحالة: {data['state']}",

        "",

        "📊 الاتجاه العام",

        f"1D: {data['trend_1d']}",

        f"4H: {data['trend_4h']}",

        "",

        "🔎 تأكيد الدخول",

        f"1H: {data['trend_1h']}",

        f"30m: {data['trend_30m']}",

        f"15m: {data['trend_15m']}",

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

        "",

        "🛡️ الدعم والمقاومة",

        f"🟢 Support: {data['support']}",

        f"🔴 Resistance: {data['resistance']}",

        f"📏 البعد عن الدعم: {data['support_distance']}%",

        f"📏 البعد عن المقاومة: {data['resistance_distance']}%",

        ""
    ]

    if direction in (
        "LONG",
        "SHORT"
    ):

        lines += [

            "📍 منطقة الدخول",

            f"{data['entry_min']} - {data['entry_max']}",

            "",

            f"🛑 Stop Loss: {data['stop_loss']}",

            "",

            "🎯 الأهداف",

            f"TP1: {data['tp1']}",

            f"TP2: {data['tp2']}",

            f"TP3: {data['tp3']}",

            ""
        ]

    else:

        lines += [

            "📍 منطقة الدخول",

            "⏳ انتظار تأكيد",

            "",

            "🛑 Stop Loss: غير محدد",

            "",

            "🎯 الأهداف",

            "TP1: غير محدد",

            "TP2: غير محدد",

            "TP3: غير محدد",

            ""
        ]

    lines += [

        "📊 الحركة الأخيرة",

        f"آخر شمعتين تقريباً: {data['recent_change_2']}%",

        f"آخر 6 شموع تقريباً: {data['recent_change_6']}%",

        "",

        "🔍 أسباب القرار"
    ]

    for line in data[
        "analysis_lines"
    ][:8]:

        lines.append(
            f"• {line}"
        )

    if data[
        "structure_reasons"
    ]:

        lines += [
            "",
            "🏗️ أدلة هيكل السوق"
        ]

        for reason in data[
            "structure_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if data[
        "liquidity_reasons"
    ]:

        lines += [
            "",
            "💧 أدلة السيولة"
        ]

        for reason in data[
            "liquidity_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if data[
        "bottom_reasons"
    ]:

        lines += [
            "",
            "🎯 أدلة التجميع"
        ]

        for reason in data[
            "bottom_reasons"
        ][:4]:

            lines.append(
                f"• {reason}"
            )

    if (
        direction == "NO TRADE"
        and data[
            "rejection_reasons"
        ]
    ):

        lines += [
            "",
            "🚫 لماذا لم يدخل؟"
        ]

        for reason in data[
            "rejection_reasons"
        ][:6]:

            lines.append(
                f"• {reason}"
            )

    lines += [

        "",

        "⚠️ إشارة تحليلية وليست ضماناً للربح.",

        "⚠️ 1D + 4H يحددان الاتجاه العام.",

        "⚠️ 1H هو بوابة الدخول.",

        "⚠️ 30m + 15m تأكيد إضافي.",

        "⚠️ BOS + السيولة + الحجم عوامل موزونة.",

        "⚠️ لا يتم مطاردة البامب أو الانهيار.",

        "⚠️ لا يتم اعتماد الصفقة قرب الدعم/المقاومة."
    ]

    return "\n".join(lines)
