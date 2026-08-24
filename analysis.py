import time
import logging
import requests


# =========================================================
# SETTINGS
# =========================================================

FUTURES_URLS = [
    "https://data-api.binance.vision",
    "https://fapi.binance.com",
]

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 CryptoZeroReversal/8.0",
    "Accept": "application/json",
})

logger = logging.getLogger(__name__)

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 300


# =========================================================
# BINANCE REQUEST
# =========================================================

def binance_get(path, params=None, timeout=12):

    for base_url in FUTURES_URLS:

        try:

            response = SESSION.get(
                base_url + path,
                params=params,
                timeout=timeout
            )

            if response.status_code != 200:

                logger.warning(
                    "Binance HTTP %s | %s | %s",
                    response.status_code,
                    base_url + path,
                    response.text[:200]
                )

                continue

            data = response.json()

            if isinstance(data, dict) and "code" in data:

                logger.warning(
                    "Binance API error | %s",
                    data
                )

                continue

            return data

        except requests.RequestException as exc:

            logger.warning(
                "Binance request failed %s: %s",
                base_url,
                exc
            )

        except ValueError as exc:

            logger.warning(
                "Invalid Binance JSON %s: %s",
                base_url,
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

    # Binance Futures exchangeInfo
    data = binance_get(
        "/fapi/v1/exchangeInfo",
        timeout=15
    )

    if not data:

        logger.warning(
            "Could not load Futures exchangeInfo"
        )

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

def calculate_volume_ratio(
    volumes,
    period=20
):

    if len(volumes) < period + 1:
        return 1.0

    previous = volumes[-period - 1:-1]

    average_volume = (
        sum(previous) / len(previous)
    )

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


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(klines):

    highs = [
        float(k[2])
        for k in klines
    ]

    lows = [
        float(k[3])
        for k in klines
    ]

    closes = [
        float(k[4])
        for k in klines
    ]

    current_price = closes[-1]

    lookback = min(
        80,
        len(klines)
    )

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    supports = []
    resistances = []

    tolerance = 0.006

    for low in recent_lows:

        if low < current_price:

            distance = (
                abs(current_price - low)
                / current_price
            )

            if distance <= 0.15:

                supports.append(low)

    for high in recent_highs:

        if high > current_price:

            distance = (
                abs(high - current_price)
                / current_price
            )

            if distance <= 0.15:

                resistances.append(high)

    if supports:
        support = max(supports)
    else:
        support = min(recent_lows)

    if resistances:
        resistance = min(resistances)
    else:
        resistance = max(recent_highs)

    support_cluster = [
        x
        for x in recent_lows
        if abs(x - support)
        / current_price <= tolerance
    ]

    resistance_cluster = [
        x
        for x in recent_highs
        if abs(x - resistance)
        / current_price <= tolerance
    ]

    if support_cluster:

        support = (
            sum(support_cluster)
            / len(support_cluster)
        )

    if resistance_cluster:

        resistance = (
            sum(resistance_cluster)
            / len(resistance_cluster)
        )

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

    body = abs(
        close - open_price
    )

    upper_wick = (
        high - max(open_price, close)
    )

    lower_wick = (
        min(open_price, close) - low
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
# RECENT DRAWDOWN
# =========================================================

def calculate_recent_drawdown(
    closes,
    lookback=50
):

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
        (
            (current - highest)
            / highest
        ) * 100,
        2
    )


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(klines):

    if len(klines) < 40:

        return False, 0, []

    closes = [
        float(k[4])
        for k in klines
    ]

    volumes = [
        float(k[5])
        for k in klines
    ]

    current = closes[-1]

    recent_20 = closes[-20:]
    previous_20 = closes[-40:-20]

    previous_high = max(previous_20)

    recent_low = min(recent_20)
    recent_high = max(recent_20)

    if previous_high <= 0:

        return False, 0, []

    drawdown = (
        (recent_low - previous_high)
        / previous_high
    ) * 100

    recent_range = (
        (recent_high - recent_low)
        / recent_low * 100
        if recent_low > 0
        else 999
    )

    avg_old_volume = (
        sum(volumes[-40:-20])
        / 20
    )

    avg_recent_volume = (
        sum(volumes[-10:])
        / 10
    )

    volume_stable = (
        avg_old_volume > 0
        and
        avg_recent_volume
        >= avg_old_volume * 0.75
    )

    candle = candle_information(klines)

    conditions = 0
    reasons = []

    if drawdown <= -8:

        conditions += 1

        reasons.append(
            "هبوط سابق واضح"
        )

    if recent_range <= 18:

        conditions += 1

        reasons.append(
            "نطاق سعري بدأ يضيق"
        )

    if volume_stable:

        conditions += 1

        reasons.append(
            "الحجم ما زال حاضرًا بعد الهبوط"
        )

    if candle["lower_wick_ratio"] >= 0.30:

        conditions += 1

        reasons.append(
            "رفض سعري من الأسفل"
        )

    if recent_high != recent_low:

        position = (
            (current - recent_low)
            / (recent_high - recent_low)
        )

        if position <= 0.70:

            conditions += 1

            reasons.append(
                "السعر ما زال داخل منطقة مبكرة"
            )

    return (
        conditions >= 3,
        conditions,
        reasons
    )


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(klines):

    if len(klines) < 30:

        return "NEUTRAL", 0, []

    closes = [
        float(k[4])
        for k in klines
    ]

    opens = [
        float(k[1])
        for k in klines
    ]

    volumes = [
        float(k[5])
        for k in klines
    ]

    reasons = []

    current_close = closes[-1]
    previous_close = closes[-2]

    volume_ratio = (
        calculate_volume_ratio(
            volumes,
            20
        )
    )

    recent_volume_avg = (
        sum(volumes[-5:]) / 5
    )

    previous_volume_avg = (
        sum(volumes[-15:-5]) / 10
    )

    recent_price_change = (
        percentage_change(
            closes[-6],
            current_close
        )
    )

    bullish_volume = 0.0
    bearish_volume = 0.0

    start = max(
        0,
        len(klines) - 10
    )

    for i in range(start, len(klines)):

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
        recent_volume_avg
        > previous_volume_avg * 1.10
        and recent_price_change > -3
    ):

        score += 1

        reasons.append(
            "الحجم يتحسن بدون هبوط حاد"
        )

    if (
        current_close > previous_close
        and volume_ratio >= 1.20
    ):

        score += 1

        reasons.append(
            "ارتفاع السعر مع حجم مرتفع"
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
        recent_volume_avg
        > previous_volume_avg * 1.10
        and recent_price_change < -3
    ):

        score -= 1

        reasons.append(
            "ارتفاع الحجم مع ضغط بيعي"
        )

    if (
        current_close < previous_close
        and volume_ratio >= 1.20
    ):

        score -= 1

        reasons.append(
            "هبوط السعر مع حجم مرتفع"
        )

    if score >= 2:

        return "INFLOW", score, reasons

    if score <= -2:

        return "OUTFLOW", score, reasons

    return "NEUTRAL", score, reasons


# =========================================================
# TIMEFRAME TREND
# =========================================================

def get_timeframe_trend(
    symbol,
    interval
):

    klines = get_binance_futures_klines(
        symbol,
        interval,
        100
    )

    if not klines:

        return "UNKNOWN"

    closes = [
        float(k[4])
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

    if (
        ema9 is None
        or ema20 is None
        or ema50 is None
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
            "Symbol not found on Futures: %s",
            symbol
        )

        return None

    klines_1h = get_binance_futures_klines(
        symbol,
        "1h",
        200
    )

    if not klines_1h:

        return None

    closes = [
        float(k[4])
        for k in klines_1h
    ]

    volumes = [
        float(k[5])
        for k in klines_1h
    ]

    current_price = closes[-1]

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

    if (
        ema9 is None
        or ema20 is None
        or ema50 is None
    ):

        return None

    rsi = calculate_rsi(closes)

    volume_ratio = (
        calculate_volume_ratio(volumes)
    )

    volume_trend = (
        calculate_volume_trend(volumes)
    )

    atr = calculate_atr(
        klines_1h
    )

    support, resistance = (
        calculate_support_resistance(
            klines_1h
        )
    )

    trend_15m = get_timeframe_trend(
        symbol,
        "15m"
    )

    trend_1h = get_timeframe_trend(
        symbol,
        "1h"
    )

    trend_4h = get_timeframe_trend(
        symbol,
        "4h"
    )

    trend_1d = get_timeframe_trend(
        symbol,
        "1d"
    )

    (
        bottom_detected,
        bottom_score,
        bottom_reasons
    ) = detect_bottom_accumulation(
        klines_1h
    )

    (
        liquidity_state,
        liquidity_score,
        liquidity_reasons
    ) = detect_liquidity_flow(
        klines_1h
    )

    drawdown = (
        calculate_recent_drawdown(
            closes,
            50
        )
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
    # SCORING
    # =====================================================

    long_score = 0
    short_score = 0

    analysis_lines = []

    # EMA
    if ema9 > ema20:

        long_score += 10

        analysis_lines.append(
            "EMA9 أعلى من EMA20"
        )

    else:

        short_score += 10

        analysis_lines.append(
            "EMA9 أسفل EMA20"
        )

    if ema20 > ema50:

        long_score += 10

    else:

        short_score += 10

    # RSI
    if 42 <= rsi <= 62:

        long_score += 8

    if rsi < 35:

        long_score += 6

        analysis_lines.append(
            "RSI منخفض وقد توجد فرصة ارتداد"
        )

    if 48 <= rsi <= 58:

        short_score += 3

    if rsi > 70:

        short_score += 8

        analysis_lines.append(
            "RSI مرتفع واحتمال تصحيح"
        )

    # Volume
    if volume_ratio >= 1.20:

        if ema9 >= ema20:

            long_score += 10

            analysis_lines.append(
                "حجم تداول مرتفع مع تحسن سعري"
            )

        else:

            short_score += 10

            analysis_lines.append(
                "حجم تداول مرتفع مع ضغط بيعي"
            )

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
            "خروج سيولة/ضغط بيعي محتمل"
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

    # MTF
    timeframe_weights = {
        "15m": 5,
        "1h": 8,
        "4h": 12,
        "1d": 10
    }

    trends = [
        ("15m", trend_15m),
        ("1h", trend_1h),
        ("4h", trend_4h),
        ("1d", trend_1d)
    ]

    for timeframe, trend in trends:

        weight = timeframe_weights[timeframe]

        if trend == "LONG":

            long_score += weight

        elif trend == "SHORT":

            short_score += weight

    # Support
    if 0 < support_distance <= 4:

        long_score += 10

        analysis_lines.append(
            "السعر قريب من الدعم"
        )

    if 0 < support_distance <= 1.5:

        long_score += 5

        analysis_lines.append(
            "السعر قريب جدًا من منطقة دعم"
        )

    # Resistance
    if 0 < resistance_distance <= 4:

        short_score += 8

        analysis_lines.append(
            "السعر قريب من المقاومة"
        )

    if 0 < resistance_distance <= 1.5:

        long_score -= 15

        analysis_lines.append(
            "الشراء الآن قريب جدًا من المقاومة"
        )

    # Avoid pump
    recent_5_change = percentage_change(
        closes[-6],
        current_price
    )

    if recent_5_change >= 8:

        long_score -= 20

        analysis_lines.append(
            "ارتفاع سريع؛ تجنب مطاردة البمب"
        )

    # Avoid short after crash
    if recent_5_change <= -8:

        short_score -= 15

        analysis_lines.append(
            "هبوط سريع؛ تجنب مطاردة الشورت"
        )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    score_difference = abs(
        long_score - short_score
    )

    if score_difference < 8:

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
            and
            liquidity_state == "INFLOW"
        ):

            state = (
                "قاع + تجميع + "
                "دخول سيولة محتمل"
            )

        else:

            state = (
                "ميل صاعد + "
                "مراقبة الدخول"
            )

    else:

        direction = "SHORT"

        score = short_score

        trend = "DOWN"

        if liquidity_state == "OUTFLOW":

            state = (
                "تصريف + "
                "خروج سيولة محتمل"
            )

        else:

            state = (
                "ميل هابط + "
                "مراقبة الشورت"
            )

    score = max(
        0,
        min(
            100,
            int(score)
        )
    )

    # =====================================================
    # ENTRY / SL / TP
    # =====================================================

    if atr is None or atr <= 0:

        atr = current_price * 0.01

    if direction == "LONG":

        entry_min = max(
            support,
            current_price - atr * 0.35
        )

        entry_max = current_price

        stop_loss = min(
            support - atr * 0.35,
            current_price - atr * 1.2
        )

        risk = (
            current_price - stop_loss
        )

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

    elif direction == "SHORT":

        entry_min = current_price

        entry_max = min(
            resistance,
            current_price + atr * 0.35
        )

        stop_loss = max(
            resistance + atr * 0.35,
            current_price + atr * 1.2
        )

        risk = (
            stop_loss - current_price
        )

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

        stop_loss = (
            current_price - atr
        )

        risk = atr

        tp1 = current_price + risk
        tp2 = current_price + risk * 2
        tp3 = current_price + risk * 3

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
            current_price
        ),

        "rsi": rsi,

        "volume_ratio":
            volume_ratio,

        "volume_trend":
            volume_trend,

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
# MARKET RANKING
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

        symbol = item.get(
            "symbol"
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

            price_change = abs(
                float(
                    item.get(
                        "priceChangePercent",
                        0
                    )
                )
            )

            liquidity_score = (
                quote_volume
                *
                (
                    1
                    +
                    min(
                        price_change / 100,
                        0.25
                    )
                )
            )

            candidates.append(
                (
                    symbol,
                    liquidity_score
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
# MARKET SCANNER
# =========================================================

def scan_market(limit=5):

    symbols = get_top_futures_symbols(
        60
    )

    if not symbols:

        return []

    results = []

    for symbol in symbols:

        try:

            data = get_coin_analysis(
                symbol
            )

            if not data:

                continue

            # لا نخفي الفرص المبكرة
            # لكن نستبعد WAIT الضعيف
            if data["direction"] == "WAIT":

                if (
                    data["bottom_detected"]
                    and
                    data["liquidity_state"]
                    == "INFLOW"
                    and
                    data["score"] >= 45
                ):

                    data["state"] = (
                        "🟡 فرصة مبكرة — "
                        "تحتاج تأكيد"
                    )

                    results.append(data)

                continue

            # الحد الأدنى
            if data["score"] < 50:

                continue

            results.append(data)

        except Exception as exc:

            logger.exception(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        time.sleep(0.08)

    results.sort(
        key=lambda x: (
            x["score"],

            1
            if x["liquidity_state"]
            == "INFLOW"
            else 0,

            1
            if x["bottom_detected"]
            else 0
        ),
        reverse=True
    )

    return results[:limit]


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(data):

    if data["direction"] == "LONG":

        direction_emoji = "🟢"

    elif data["direction"] == "SHORT":

        direction_emoji = "🔴"

    else:

        direction_emoji = "🟡"

    if data["liquidity_state"] == "INFLOW":

        liquidity_text = (
            "🟢 دخول سيولة"
        )

    elif data["liquidity_state"] == "OUTFLOW":

        liquidity_text = (
            "🔴 خروج سيولة"
        )

    else:

        liquidity_text = (
            "🟡 سيولة محايدة"
        )

    bottom_text = (
        "🟢 قاع/تجميع محتمل"
        if data["bottom_detected"]
        else
        "⚪ لا يوجد تأكيد قاع كافٍ"
    )

    lines = [

        "🤖 Binance AI Scanner",

        "",

        f"💎 العملة: {data['symbol']}",

        (
            f"📈 الاتجاه: "
            f"{direction_emoji} "
            f"{data['direction']}"
        ),

        f"⭐ Score: {data['score']}/100",

        "",

        f"🧠 الحالة: {data['state']}",

        "",

        f"💰 السعر: {data['price']}",

        f"📊 RSI: {data['rsi']}",

        (
            f"📊 Volume: "
            f"{data['volume_ratio']}x"
        ),

        (
            f"📈 Volume Trend: "
            f"{data['volume_trend']}"
        ),

        (
            f"💧 السيولة: "
            f"{liquidity_text}"
        ),

        (
            f"💧 Buy Pressure: "
            f"{data['buy_pressure']}%"
        ),

        "",

        f"🎯 القاع: {bottom_text}",

        (
            f"📉 الهبوط السابق: "
            f"{data['drawdown']}%"
        ),

        "",

        "📊 تأكيد الفريمات",

        (
            f"15M: "
            f"{data['trend_15m']}"
        ),

        (
            f"1H: "
            f"{data['trend_1h']}"
        ),

        (
            f"4H: "
            f"{data['trend_4h']}"
        ),

        (
            f"1D: "
            f"{data['trend_1d']}"
        ),

        "",

        "🛡️ الدعم والمقاومة",

        (
            f"🟢 Support: "
            f"{data['support']}"
        ),

        (
            f"🔴 Resistance: "
            f"{data['resistance']}"
        ),

        (
            f"📏 البعد عن الدعم: "
            f"{data['support_distance']}%"
        ),

        (
            f"📏 البعد عن المقاومة: "
            f"{data['resistance_distance']}%"
        ),

        "",

        "📍 منطقة الدخول",

        (
            f"{data['entry_min']} "
            f"- "
            f"{data['entry_max']}"
        ),

        "",

        (
            f"🛑 Stop Loss: "
            f"{data['stop_loss']}"
        ),

        "",

        "🎯 الأهداف",

        f"TP1: {data['tp1']}",

        f"TP2: {data['tp2']}",

        f"TP3: {data['tp3']}",

        "",

        "🔍 إشارات التحليل"
    ]

    for line in data["analysis_lines"]:

        lines.append(
            f"• {line}"
        )

    if data["liquidity_reasons"]:

        lines.append("")

        lines.append(
            "💧 تفاصيل السيولة"
        )

        for reason in (
            data["liquidity_reasons"][:4]
        ):

            lines.append(
                f"• {reason}"
            )

    if data["bottom_reasons"]:

        lines.append("")

        lines.append(
            "🎯 تفاصيل القاع"
        )

        for reason in (
            data["bottom_reasons"][:4]
        ):

            lines.append(
                f"• {reason}"
            )

    lines.extend([

        "",

        (
            "⚠️ هذه إشارة تحليلية "
            "وليست ضمانًا للربح."
        ),

        (
            "⚠️ لا تطارد البمب؛ "
            "انتظر دخول منطقة الدخول "
            "والتأكيد."
        )
    ])

    return "\n".join(lines)
