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


# =========================================================
# CACHE / RATE LIMIT
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0
SYMBOL_CACHE_SECONDS = 600

_KLINE_CACHE = {}
KLINE_CACHE_SECONDS = 60

_RATE_LIMIT_UNTIL = 0
_RATE_LOCK = threading.Lock()

_REQUEST_LOCK = threading.Lock()
MIN_REQUEST_INTERVAL = 0.35
_LAST_REQUEST_TIME = 0


# =========================================================
# HTTP
# =========================================================

def bingx_get(path, params=None, timeout=12):

    global _RATE_LIMIT_UNTIL
    global _LAST_REQUEST_TIME

    now = time.time()

    with _RATE_LOCK:

        if now < _RATE_LIMIT_UNTIL:

            logger.warning(
                "BingX rate-limit protection active. Retry in %.0f seconds",
                _RATE_LIMIT_UNTIL - now
            )

            return None

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
                "BingX rate/API error: %s",
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

    if len(result) < 50:
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

    ratio = short_avg / long_avg

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

def calculate_support_resistance(klines):

    highs = [k[2] for k in klines]
    lows = [k[3] for k in klines]
    closes = [k[4] for k in klines]

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

    highs = [k[2] for k in klines]
    lows = [k[3] for k in klines]
    closes = [k[4] for k in klines]

    current = closes[-1]

    previous_high = max(
        highs[-25:-5]
    )

    previous_low = min(
        lows[-25:-5]
    )

    recent_high = max(
        highs[-5:]
    )

    recent_low = min(
        lows[-5:]
    )

    reasons = []

    bos = "NONE"
    structure = "MIXED"

    if current > previous_high:

        bos = "BULLISH_BOS"
        structure = "BULLISH"

        reasons.append(
            "تم كسر قمة هيكلية صعوداً"
        )

    elif current < previous_low:

        bos = "BEARISH_BOS"
        structure = "BEARISH"

        reasons.append(
            "تم كسر قاع هيكلي هبوطاً"
        )

    else:

        # =================================================
        # NO BOS:
        # نحاول معرفة الميل الداخلي بدون اعتباره BOS
        # =================================================

        mid = (
            max(klines[-12:][i][2] for i in range(12))
            +
            min(klines[-12:][i][3] for i in range(12))
        ) / 2

        if current > mid:
            structure = "MIXED"
        elif current < mid:
            structure = "MIXED"
        else:
            structure = "MIXED"

        reasons.append(
            "لا يوجد كسر هيكل مؤكد"
        )

    distance_from_low = (
        abs(current - recent_low)
        / current
        * 100
    )

    distance_from_high = (
        abs(recent_high - current)
        / current
        * 100
    )

    liquidity_zone = "NONE"

    if distance_from_low <= 1.0:

        liquidity_zone = "LOW_LIQUIDITY"

        reasons.append(
            "السعر قريب جداً من السيولة السفلية"
        )

    elif distance_from_high <= 1.0:

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

def detect_bottom_accumulation(klines):

    if len(klines) < 40:

        return False, 0, []

    closes = [k[4] for k in klines]
    volumes = [k[5] for k in klines]

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

    candle = candle_information(klines)

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
        and recent_volume >= old_volume * 0.75
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
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(klines):

    if len(klines) < 30:

        return "NEUTRAL", 0, []

    opens = [k[1] for k in klines]
    closes = [k[4] for k in klines]
    volumes = [k[5] for k in klines]

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
        bullish_volume > bearish_volume * 1.15
        and volume_ratio >= 0.90
    ):

        score += 2

        reasons.append(
            "حجم الشموع الصاعدة أقوى من الهابطة"
        )

    if (
        recent_volume > previous_volume * 1.10
        and recent_change > -2
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن بدون ضغط هابط قوي"
        )

    if (
        bearish_volume > bullish_volume * 1.20
        and volume_ratio >= 0.90
    ):

        score -= 2

        reasons.append(
            "حجم الشموع الهابطة أكبر من الصاعدة"
        )

    if (
        recent_volume > previous_volume * 1.10
        and recent_change < -2
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

def calculate_timeframe_trend(klines):

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
# ENTRY QUALITY
# =========================================================

def calculate_entry_quality(
    trend_4h,
    trend_1h,
    structure,
    liquidity_state,
    volume_ratio,
    volume_trend,
    rsi,
    current,
    support,
    resistance
):

    reasons = []

    long_ok = False
    short_ok = False

    # =====================================================
    # LONG GATE
    # =====================================================

    if trend_4h == "LONG":

        if trend_1h == "LONG":
            reasons.append(
                "1H بدأ يتوافق مع اتجاه 4H"
            )

        if structure["bos"] == "BULLISH_BOS":
            reasons.append(
                "BOS صاعد مؤكد"
            )

        if liquidity_state == "INFLOW":
            reasons.append(
                "دخول سيولة"
            )

        if volume_ratio >= 0.80:
            reasons.append(
                "الحجم مقبول"
            )

        # =================================================
        # شروط LONG الصارمة
        # =================================================

        long_ok = (
            trend_1h == "LONG"
            and
            structure["bos"] == "BULLISH_BOS"
            and
            liquidity_state == "INFLOW"
            and
            volume_ratio >= 0.80
            and
            volume_trend != "FALLING"
            and
            35 <= rsi <= 70
        )

    # =====================================================
    # SHORT GATE
    # =====================================================

    if trend_4h == "SHORT":

        if trend_1h == "SHORT":
            reasons.append(
                "1H بدأ يتوافق مع اتجاه 4H"
            )

        if structure["bos"] == "BEARISH_BOS":
            reasons.append(
                "BOS هابط مؤكد"
            )

        if liquidity_state == "OUTFLOW":
            reasons.append(
                "خروج سيولة"
            )

        if volume_ratio >= 0.80:
            reasons.append(
                "الحجم مقبول"
            )

        # =================================================
        # شروط SHORT الصارمة
        # =================================================

        short_ok = (
            trend_1h == "SHORT"
            and
            structure["bos"] == "BEARISH_BOS"
            and
            liquidity_state == "OUTFLOW"
            and
            volume_ratio >= 0.80
            and
            volume_trend != "FALLING"
            and
            30 <= rsi <= 70
        )

    return (
        long_ok,
        short_ok,
        reasons
    )


# =========================================================
# COIN ANALYSIS
# 4H = MASTER
# 1H = ENTRY
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol_exists(symbol):

        logger.info(
            "Symbol not found on BingX: %s",
            symbol
        )

        return None

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

    trend_4h = calculate_timeframe_trend(
        klines_4h
    )

    if trend_4h == "UNKNOWN":
        return None

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

    trend_1h = calculate_timeframe_trend(
        klines_1h
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
    # ENTRY GATE
    # =====================================================

    long_gate, short_gate, gate_reasons = (
        calculate_entry_quality(
            trend_4h,
            trend_1h,
            structure,
            liquidity_state,
            volume_ratio,
            volume_trend,
            rsi,
            current,
            support,
            resistance
        )
    )

    # =====================================================
    # SCORE
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

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
            "4H محايد"
        )

    # =====================================================
    # 1H STRUCTURE
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

    else:

        analysis_lines.append(
            "لا يوجد BOS مؤكد"
        )

    # =====================================================
    # 1H TREND
    # =====================================================

    if trend_1h == "LONG":

        long_score += 15

        analysis_lines.append(
            "1H متوافق مع الصعود"
        )

    elif trend_1h == "SHORT":

        short_score += 15

        analysis_lines.append(
            "1H متوافق مع الهبوط"
        )

    else:

        analysis_lines.append(
            "1H غير مؤكد"
        )

    # =====================================================
    # EMA - مساعد فقط
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

    # =====================================================
    # RSI - مساعد فقط
    # =====================================================

    if 40 <= rsi <= 65:

        analysis_lines.append(
            "RSI في نطاق متوازن"
        )

        if trend_4h == "LONG":
            long_score += 5

        elif trend_4h == "SHORT":
            short_score += 5

    elif rsi < 30:

        analysis_lines.append(
            "RSI منخفض — لا تتم مطاردة الشورت"
        )

    elif rsi > 70:

        analysis_lines.append(
            "RSI مرتفع — لا تتم مطاردة LONG"
        )

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if volume_trend == "RISING":

            analysis_lines.append(
                "الحجم قوي ويتحسن"
            )

        else:

            analysis_lines.append(
                "الحجم مرتفع"
            )

    elif volume_ratio < 0.80:

        analysis_lines.append(
            "الحجم ضعيف"
        )

    if volume_trend == "FALLING":

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
    # =====================================================

    if bottom_detected:

        analysis_lines.append(
            "القاع/التجميع محتمل لكنه ليس تأكيد دخول"
        )

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    if support_distance <= 2:

        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if resistance_distance <= 2:

        analysis_lines.append(
            "السعر قريب من المقاومة"
        )

    # =====================================================
    # CRASH / PUMP
    # =====================================================

    if crash_detected:

        analysis_lines.append(
            "حركة هبوط سريعة — ممنوع مطاردة الشورت"
        )

    if pump_detected:

        analysis_lines.append(
            "حركة صعود سريعة — ممنوع مطاردة LONG"
        )

    # =====================================================
    # FINAL DECISION
    # =====================================================

    direction = "NO TRADE"
    state = ""
    score = 0

    # =====================================================
    # HARD PROTECTION
    # =====================================================

    if trend_4h == "LONG":

        if crash_detected:

            state = (
                "NO TRADE - حركة هبوط سريعة"
            )

        elif trend_1h == "SHORT":

            state = (
                "NO TRADE - 4H صاعد لكن 1H هابط"
            )

        elif liquidity_state == "OUTFLOW":

            state = (
                "NO TRADE - 4H صاعد لكن السيولة خارجة"
            )

        elif volume_ratio < 0.80:

            state = (
                "NO TRADE - الحجم ضعيف ويتراجع"
            )

        elif volume_trend == "FALLING":

            state = (
                "NO TRADE - الحجم يتراجع"
            )

        elif structure["bos"] != "BULLISH_BOS":

            state = (
                "NO TRADE - لا يوجد BOS صاعد مؤكد"
            )

        elif liquidity_state != "INFLOW":

            state = (
                "NO TRADE - لا يوجد دخول سيولة مؤكد"
            )

        elif not long_gate:

            state = (
                "NO TRADE - بوابة LONG غير مكتملة"
            )

        else:

            direction = "LONG"
            score = long_score

            state = (
                "4H صاعد + 1H مؤكد + دخول سيولة + BOS صاعد"
            )

    elif trend_4h == "SHORT":

        if crash_detected:

            state = (
                "NO TRADE - لا نطارد الانهيار"
            )

        elif trend_1h == "LONG":

            state = (
                "NO TRADE - 4H هابط لكن 1H صاعد"
            )

        elif liquidity_state == "INFLOW":

            state = (
                "NO TRADE - 4H هابط لكن السيولة تدخل"
            )

        elif rsi < 30:

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

        elif structure["bos"] != "BEARISH_BOS":

            state = (
                "NO TRADE - لا يوجد BOS هابط مؤكد"
            )

        elif liquidity_state != "OUTFLOW":

            state = (
                "NO TRADE - لا يوجد خروج سيولة مؤكد"
            )

        elif not short_gate:

            state = (
                "NO TRADE - بوابة SHORT غير مكتملة"
            )

        else:

            direction = "SHORT"
            score = short_score

            state = (
                "4H هابط + 1H مؤكد + خروج سيولة + BOS هابط"
            )

    else:

        state = (
            "NO TRADE - 4H محايد"
        )

    # =====================================================
    # LIMIT SCORE
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

    if direction == "LONG":

        entry_min = max(
            support,
            current - atr * 0.35
        )

        entry_max = current

        stop_loss = min(
            support - atr * 0.25,
            current - atr * 1.0
        )

        risk = current - stop_loss

        if risk <= 0:
            risk = atr

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
            current + atr * 0.35
        )

        stop_loss = max(
            resistance + atr * 0.25,
            current + atr * 1.0
        )

        risk = stop_loss - current

        if risk <= 0:
            risk = atr

        tp1 = current - risk * 1.2
        tp2 = current - risk * 2.0
        tp3 = current - risk * 3.0

        if support < current:

            tp1 = max(
                tp1,
                support
            )

    else:

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

        "price": smart_round(current),

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
            "UP"
            if trend_4h == "LONG"
            else
            "DOWN"
            if trend_4h == "SHORT"
            else
            "NEUTRAL",

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

        "gate_reasons":
            gate_reasons
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

        raw_symbol = item.get("symbol")

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

            if data["direction"] == "NO TRADE":
                continue

            if data["direction"] != data["trend_4h"]:
                continue

            # =================================================
            # LONG FINAL FILTER
            # =================================================

            if data["direction"] == "LONG":

                if data["score"] < 70:
                    continue

                if data["trend_4h"] != "LONG":
                    continue

                if data["trend_1h"] != "LONG":
                    continue

                if data["bos"] != "BULLISH_BOS":
                    continue

                if data["liquidity_state"] != "INFLOW":
                    continue

                if data["volume_ratio"] < 0.80:
                    continue

                if data["volume_trend"] == "FALLING":
                    continue

                if data["rsi"] < 35 or data["rsi"] > 70:
                    continue

                if data["crash_detected"]:
                    continue

            # =================================================
            # SHORT FINAL FILTER
            # =================================================

            elif data["direction"] == "SHORT":

                if data["score"] < 70:
                    continue

                if data["trend_4h"] != "SHORT":
                    continue

                if data["trend_1h"] != "SHORT":
                    continue

                if data["bos"] != "BEARISH_BOS":
                    continue

                if data["liquidity_state"] != "OUTFLOW":
                    continue

                if data["volume_ratio"] < 0.80:
                    continue

                if data["volume_trend"] == "FALLING":
                    continue

                if data["rsi"] < 30:
                    continue

                if data["crash_detected"]:
                    continue

            else:

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

        time.sleep(0.40)

    results.sort(
        key=lambda x: (
            x["score"],
            x["buy_pressure"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    return results[:limit]


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(data):

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
            "🟡 غير مؤكد"
        )

    if data["entry_min"] is None:

        entry_text = "⏳ انتظار تأكيد 1H"

        sl_text = "غير محدد"

        tp1_text = "غير محدد"
        tp2_text = "غير محدد"
        tp3_text = "غير محدد"

    else:

        entry_text = (
            f"{data['entry_min']} - "
            f"{data['entry_max']}"
        )

        sl_text = str(
            data["stop_loss"]
        )

        tp1_text = str(data["tp1"])
        tp2_text = str(data["tp2"])
        tp3_text = str(data["tp3"])

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

    for line in data["analysis_lines"][:8]:

        lines.append(
            f"• {line}"
        )

    if data["structure_reasons"]:

        lines.extend([
            "",
            "🏗️ أدلة هيكل السوق"
        ])

        for reason in data["structure_reasons"][:4]:

            lines.append(
                f"• {reason}"
            )

    if data["liquidity_reasons"]:

        lines.extend([
            "",
            "💧 أدلة السيولة"
        ])

        for reason in data["liquidity_reasons"][:4]:

            lines.append(
                f"• {reason}"
            )

    if data["bottom_reasons"]:

        lines.extend([
            "",
            "🎯 أدلة التجميع"
        ])

        for reason in data["bottom_reasons"][:4]:

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
