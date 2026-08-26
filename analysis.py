import time
import logging
import threading
import requests
import math


# =========================================================
# SETTINGS
# =========================================================

BINGX_URL = "https://open-api.bingx.com"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal-BingX/5.0",
    "Accept": "application/json",
})

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 12


# =========================================================
# CACHE
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 600

_KLINE_CACHE = {}
_KLINE_CACHE_TIME = {}

KLINE_CACHE_SECONDS = 30


# =========================================================
# RATE LIMIT PROTECTION
# =========================================================

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

MIN_REQUEST_INTERVAL = 0.45

_RATE_LIMIT_UNTIL = 0


# =========================================================
# REQUEST
# =========================================================

def _throttle():

    global _LAST_REQUEST_TIME

    with _REQUEST_LOCK:

        now = time.time()

        wait = (
            MIN_REQUEST_INTERVAL
            - (now - _LAST_REQUEST_TIME)
        )

        if wait > 0:
            time.sleep(wait)

        _LAST_REQUEST_TIME = time.time()


def bingx_get(path, params=None):

    global _RATE_LIMIT_UNTIL

    now = time.time()

    if now < _RATE_LIMIT_UNTIL:
        return None

    _throttle()

    url = BINGX_URL + path

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            logger.warning(
                "BingX HTTP error %s: %s",
                response.status_code,
                response.text[:300],
            )

            return None

        data = response.json()

        code = data.get("code")

        if code in (109429, 109400):

            _RATE_LIMIT_UNTIL = (
                time.time() + 60
            )

            logger.warning(
                "BingX rate limit. Cooling down."
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
            "BingX request error: %s",
            exc
        )

        return None

    except Exception as exc:

        logger.exception(
            "Unexpected BingX error: %s",
            exc
        )

        return None


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(symbol):

    if not symbol:
        return ""

    symbol = str(symbol).upper().strip()

    symbol = symbol.replace(" ", "")
    symbol = symbol.replace("/", "")
    symbol = symbol.replace("-", "")

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    return symbol


def bingx_symbol(symbol):

    return normalize_symbol(symbol)


# =========================================================
# SYMBOLS
# =========================================================

def get_futures_symbols():

    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    now = time.time()

    if (
        _SYMBOL_CACHE
        and now - _SYMBOL_CACHE_TIME
        < SYMBOL_CACHE_SECONDS
    ):
        return list(_SYMBOL_CACHE)

    data = bingx_get(
        "/openApi/swap/v2/quote/contracts"
    )

    symbols = set()

    if data:

        rows = data.get("data")

        if isinstance(rows, list):

            for item in rows:

                if not isinstance(item, dict):
                    continue

                symbol = (
                    item.get("symbol")
                    or item.get("pair")
                )

                if not symbol:
                    continue

                symbol = str(symbol).upper()
                symbol = symbol.replace("-", "")

                if symbol.endswith("USDT"):
                    symbols.add(symbol)

    if not symbols:

        fallback = [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "DOGEUSDT",
            "ADAUSDT",
            "SUIUSDT",
            "LINKUSDT",
            "ENAUSDT",
            "AVAXUSDT",
            "LTCUSDT",
            "DOTUSDT",
            "TRXUSDT",
            "PEPEUSDT",
        ]

        symbols = set(fallback)

    _SYMBOL_CACHE = symbols
    _SYMBOL_CACHE_TIME = time.time()

    return list(_SYMBOL_CACHE)


# =========================================================
# INTERVAL
# =========================================================

def _interval_to_bingx(interval):

    mapping = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1d",
        "3d": "3d",
        "1w": "1w",
    }

    return mapping.get(
        interval,
        interval
    )


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval="1h",
    limit=120,
):

    symbol = bingx_symbol(symbol)

    interval = _interval_to_bingx(
        interval
    )

    cache_key = (
        symbol,
        interval,
        int(limit)
    )

    now = time.time()

    if (
        cache_key in _KLINE_CACHE
        and now - _KLINE_CACHE_TIME.get(
            cache_key,
            0
        ) < KLINE_CACHE_SECONDS
    ):

        return _KLINE_CACHE[cache_key]

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": int(limit),
    }

    data = bingx_get(
        "/openApi/swap/v2/quote/klines",
        params
    )

    if not data:
        return []

    rows = data.get("data")

    if not isinstance(rows, list):
        return []

    result = []

    for row in rows:

        try:

            if isinstance(row, dict):

                timestamp = (
                    row.get("time")
                    or row.get("timestamp")
                )

                open_price = (
                    row.get("open")
                    or row.get("o")
                )

                high = (
                    row.get("high")
                    or row.get("h")
                )

                low = (
                    row.get("low")
                    or row.get("l")
                )

                close = (
                    row.get("close")
                    or row.get("c")
                )

                volume = (
                    row.get("volume")
                    or row.get("v")
                    or 0
                )

            else:

                if len(row) < 6:
                    continue

                timestamp = row[0]
                open_price = row[1]
                high = row[2]
                low = row[3]
                close = row[4]
                volume = row[5]

            candle = {
                "time": float(timestamp or 0),
                "open": float(open_price),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }

            result.append(candle)

        except Exception:
            continue

    result.sort(
        key=lambda x: x["time"]
    )

    if result:

        _KLINE_CACHE[cache_key] = result
        _KLINE_CACHE_TIME[cache_key] = time.time()

    return result


# =========================================================
# CURRENT PRICE
# =========================================================

def get_current_price(symbol):

    symbol = bingx_symbol(symbol)

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker",
        {
            "symbol": symbol
        }
    )

    if data:

        rows = data.get("data")

        if isinstance(rows, list):

            for item in rows:

                if not isinstance(item, dict):
                    continue

                try:

                    price = (
                        item.get("lastPrice")
                        or item.get("last")
                        or item.get("price")
                    )

                    if price is not None:
                        return float(price)

                except Exception:
                    continue

        elif isinstance(rows, dict):

            try:

                price = (
                    rows.get("lastPrice")
                    or rows.get("last")
                    or rows.get("price")
                )

                if price is not None:
                    return float(price)

            except Exception:
                pass

    candles = get_klines(
        symbol,
        "1m",
        3
    )

    if candles:
        return candles[-1]["close"]

    return None


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if not values:
        return []

    period = max(
        1,
        int(period)
    )

    if len(values) < period:
        return [None] * len(values)

    result = [None] * (
        period - 1
    )

    sma = (
        sum(values[:period])
        / period
    )

    result.append(sma)

    multiplier = 2 / (
        period + 1
    )

    previous = sma

    for value in values[period:]:

        current = (
            previous
            + multiplier
            * (value - previous)
        )

        result.append(current)

        previous = current

    return result


# =========================================================
# RSI
# =========================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

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
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
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

        current = klines[i]
        previous = klines[i - 1]

        high = current["high"]
        low = current["low"]
        prev_close = previous["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        trs.append(tr)

    if not trs:
        return None

    return (
        sum(trs[-period:])
        / min(period, len(trs))
    )


# =========================================================
# VOLUME RATIO
# =========================================================

def calculate_volume_ratio(
    klines,
    period=20
):

    if len(klines) < 2:
        return 0

    recent = klines[-1]["volume"]

    previous = [
        x["volume"]
        for x in klines[
            -(period + 1):-1
        ]
    ]

    if not previous:
        return 0

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 0

    return recent / average


# =========================================================
# VOLUME TREND
# =========================================================

def calculate_volume_trend(
    klines,
    period=5
):

    if len(klines) < period * 2:
        return "NEUTRAL"

    recent = [
        x["volume"]
        for x in klines[-period:]
    ]

    previous = [
        x["volume"]
        for x in klines[
            -(period * 2):-period
        ]
    ]

    if not previous:
        return "NEUTRAL"

    recent_avg = (
        sum(recent)
        / len(recent)
    )

    previous_avg = (
        sum(previous)
        / len(previous)
    )

    if previous_avg <= 0:
        return "NEUTRAL"

    ratio = (
        recent_avg
        / previous_avg
    )

    if ratio >= 1.05:
        return "RISING"

    if ratio <= 0.95:
        return "FALLING"

    return "STABLE"


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    klines,
    lookback=80
):

    if not klines:
        return None, None

    data = klines[
        -min(
            lookback,
            len(klines)
        ):
    ]

    support = min(
        x["low"]
        for x in data
    )

    resistance = max(
        x["high"]
        for x in data
    )

    return support, resistance


# =========================================================
# TIMEFRAME TREND
# =========================================================

def calculate_timeframe_trend(
    klines
):

    if len(klines) < 60:
        return "NEUTRAL"

    closes = [
        x["close"]
        for x in klines
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
        not ema9
        or not ema20
        or not ema50
    ):
        return "NEUTRAL"

    e9 = ema9[-1]
    e20 = ema20[-1]
    e50 = ema50[-1]

    price = closes[-1]

    if None in (e9, e20, e50):
        return "NEUTRAL"

    if (
        e9 > e20
        and e20 > e50
        and price > e20
    ):
        return "LONG"

    if (
        e9 < e20
        and e20 < e50
        and price < e20
    ):
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(
    klines
):

    if len(klines) < 40:
        return "MIXED", "NONE"

    recent = klines[-20:]
    previous = klines[-40:-20]

    recent_high = max(
        x["high"]
        for x in recent
    )

    recent_low = min(
        x["low"]
        for x in recent
    )

    previous_high = max(
        x["high"]
        for x in previous
    )

    previous_low = min(
        x["low"]
        for x in previous
    )

    close = klines[-1]["close"]

    # Strong BOS
    if close > previous_high:
        return "BULLISH", "BULLISH"

    if close < previous_low:
        return "BEARISH", "BEARISH"

    higher_high = (
        recent_high > previous_high
    )

    higher_low = (
        recent_low > previous_low
    )

    lower_high = (
        recent_high < previous_high
    )

    lower_low = (
        recent_low < previous_low
    )

    if higher_high and higher_low:
        return "BULLISH", "NONE"

    if lower_high and lower_low:
        return "BEARISH", "NONE"

    return "MIXED", "NONE"


# =========================================================
# LIQUIDITY
# =========================================================

def detect_liquidity_flow(
    klines
):

    if len(klines) < 20:
        return "NEUTRAL", 50

    recent = klines[-12:]

    bullish_volume = 0
    bearish_volume = 0

    for candle in recent:

        body = (
            candle["close"]
            - candle["open"]
        )

        volume = candle["volume"]

        if body > 0:
            bullish_volume += volume

        elif body < 0:
            bearish_volume += volume

    total = (
        bullish_volume
        + bearish_volume
    )

    if total <= 0:
        return "NEUTRAL", 50

    buy_pressure = (
        bullish_volume
        / total
        * 100
    )

    volume_ratio = calculate_volume_ratio(
        klines
    )

    if (
        bullish_volume
        > bearish_volume * 1.15
        and volume_ratio >= 1.00
    ):
        return (
            "INFLOW",
            round(buy_pressure)
        )

    if (
        bearish_volume
        > bullish_volume * 1.15
        and volume_ratio >= 1.00
    ):
        return (
            "OUTFLOW",
            round(buy_pressure)
        )

    return (
        "NEUTRAL",
        round(buy_pressure)
    )


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(
    klines
):

    if len(klines) < 40:

        return {
            "found": False,
            "score": 0,
            "drawdown": 0,
            "recent_range": 0,
            "volume_ratio": 0,
            "volume_trend": "NEUTRAL",
            "reason": [],
        }

    closes = [
        x["close"]
        for x in klines
    ]

    current = closes[-1]

    previous_high = max(
        closes[-40:-5]
    )

    if previous_high <= 0:

        return {
            "found": False,
            "score": 0,
            "drawdown": 0,
            "recent_range": 0,
            "volume_ratio": 0,
            "volume_trend": "NEUTRAL",
            "reason": [],
        }

    drawdown = (
        current
        / previous_high
        - 1
    ) * 100

    recent = klines[-10:]

    recent_high = max(
        x["high"]
        for x in recent
    )

    recent_low = min(
        x["low"]
        for x in recent
    )

    if recent_low <= 0:
        recent_low = 1e-12

    recent_range = (
        (
            recent_high
            - recent_low
        )
        / recent_low
    ) * 100

    volume_ratio = calculate_volume_ratio(
        klines
    )

    volume_trend = calculate_volume_trend(
        klines
    )

    score = 0
    reasons = []

    if drawdown <= -4:
        score += 1
        reasons.append(
            "هبوط سابق واضح"
        )

    if drawdown <= -8:
        score += 1

    if recent_range <= 18:
        score += 1
        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if volume_ratio >= 0.75:
        score += 1
        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if volume_trend in (
        "RISING",
        "STABLE"
    ):
        score += 1

    rejection = 0

    for candle in recent[-6:]:

        body_low = min(
            candle["open"],
            candle["close"]
        )

        lower_wick = (
            body_low
            - candle["low"]
        )

        body = abs(
            candle["close"]
            - candle["open"]
        )

        if body <= 0:
            body = (
                candle["high"]
                - candle["low"]
            ) or 1e-12

        if lower_wick >= body * 0.60:
            rejection += 1

    if rejection >= 1:
        score += 1
        reasons.append(
            "رفض سعري من الأسفل"
        )

    found = score >= 3

    return {
        "found": found,
        "score": score,
        "drawdown": drawdown,
        "recent_range": recent_range,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "reason": reasons,
    }


# =========================================================
# RECENT MOVE
# =========================================================

def calculate_recent_move(
    klines,
    candles_count
):

    if len(klines) <= candles_count:
        return 0

    old = klines[
        -candles_count - 1
    ]["close"]

    new = klines[-1]["close"]

    if old <= 0:
        return 0

    return (
        (new / old) - 1
    ) * 100


# =========================================================
# EMA STATE
# =========================================================

def ema_state(klines):

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(
        closes,
        9
    )

    ema20 = calculate_ema(
        closes,
        20
    )

    if (
        not ema9
        or not ema20
        or ema9[-1] is None
        or ema20[-1] is None
    ):
        return "MIXED"

    if ema9[-1] > ema20[-1]:
        return "BULLISH"

    if ema9[-1] < ema20[-1]:
        return "BEARISH"

    return "MIXED"


# =========================================================
# BUILD ENTRY LEVELS
# =========================================================

def build_trade_levels(
    direction,
    price,
    atr,
    support,
    resistance
):

    entry = price

    if not price or price <= 0:
        return None, None, None, None, None

    # =====================================================
    # LONG
    # =====================================================

    if direction == "LONG":

        if atr and atr > 0:

            stop_loss = (
                entry
                - atr * 1.20
            )

        elif support and support < entry:

            stop_loss = (
                support * 0.995
            )

        else:

            stop_loss = (
                entry * 0.97
            )

        # Safety
        if stop_loss >= entry:
            stop_loss = entry * 0.97

        risk = (
            entry
            - stop_loss
        )

        tp1 = entry + risk * 1.20
        tp2 = entry + risk * 2.00
        tp3 = entry + risk * 3.00

        return (
            entry,
            stop_loss,
            tp1,
            tp2,
            tp3
        )

    # =====================================================
    # SHORT
    # =====================================================

    if direction == "SHORT":

        if atr and atr > 0:

            stop_loss = (
                entry
                + atr * 1.20
            )

        elif resistance and resistance > entry:

            stop_loss = (
                resistance * 1.005
            )

        else:

            stop_loss = (
                entry * 1.03
            )

        if stop_loss <= entry:
            stop_loss = entry * 1.03

        risk = (
            stop_loss
            - entry
        )

        tp1 = entry - risk * 1.20
        tp2 = entry - risk * 2.00
        tp3 = entry - risk * 3.00

        return (
            entry,
            stop_loss,
            tp1,
            tp2,
            tp3
        )

    return (
        None,
        None,
        None,
        None,
        None
    )


# =========================================================
# ONE COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    k1d = get_klines(
        symbol,
        "1d",
        100
    )

    k4h = get_klines(
        symbol,
        "4h",
        120
    )

    k1h = get_klines(
        symbol,
        "1h",
        120
    )

    k30 = get_klines(
        symbol,
        "30m",
        100
    )

    k15 = get_klines(
        symbol,
        "15m",
        100
    )

    if (
        len(k1d) < 60
        or len(k4h) < 60
        or len(k1h) < 60
        or len(k30) < 40
        or len(k15) < 40
    ):

        logger.warning(
            "Not enough candles for %s",
            symbol
        )

        return None

    price = get_current_price(
        symbol
    )

    if price is None:
        price = k1h[-1]["close"]

    # =====================================================
    # TRENDS
    # =====================================================

    trend_1d = calculate_timeframe_trend(k1d)
    trend_4h = calculate_timeframe_trend(k4h)
    trend_1h = calculate_timeframe_trend(k1h)
    trend_30m = calculate_timeframe_trend(k30)
    trend_15m = calculate_timeframe_trend(k15)

    # =====================================================
    # STRUCTURE
    # =====================================================

    structure, bos = detect_market_structure(
        k1h
    )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    liquidity, buy_pressure = detect_liquidity_flow(
        k1h
    )

    # =====================================================
    # VOLUME
    # =====================================================

    volume_ratio = calculate_volume_ratio(
        k1h
    )

    volume_trend = calculate_volume_trend(
        k1h
    )

    # =====================================================
    # RSI
    # =====================================================

    closes_1h = [
        x["close"]
        for x in k1h
    ]

    rsi = calculate_rsi(
        closes_1h,
        14
    )

    if rsi is None:
        rsi = 50

    # =====================================================
    # EMA
    # =====================================================

    ema = ema_state(k1h)

    # =====================================================
    # BOTTOM
    # =====================================================

    bottom = detect_bottom_accumulation(
        k1h
    )

    # =====================================================
    # S/R
    # =====================================================

    support, resistance = calculate_support_resistance(
        k1h
    )

    distance_support = 0
    distance_resistance = 0

    if support and support > 0:

        distance_support = (
            (price - support)
            / price
        ) * 100

    if resistance and resistance > 0:

        distance_resistance = (
            (resistance - price)
            / price
        ) * 100

    # =====================================================
    # MOVEMENT
    # =====================================================

    move_2 = calculate_recent_move(
        k1h,
        2
    )

    move_6 = calculate_recent_move(
        k1h,
        6
    )

    # =====================================================
    # ATR
    # =====================================================

    atr = calculate_atr(
        k1h,
        14
    )

    # =====================================================
    # SCORING
    # =====================================================

    long_score = 0
    short_score = 0

    reasons_long = []
    reasons_short = []

    # 1D
    if trend_1d == "LONG":

        long_score += 15

        reasons_long.append(
            "1D يدعم الاتجاه الصاعد"
        )

    elif trend_1d == "SHORT":

        short_score += 15

        reasons_short.append(
            "1D يدعم الاتجاه الهابط"
        )

    # 4H
    if trend_4h == "LONG":

        long_score += 15

        reasons_long.append(
            "4H يدعم الاتجاه الصاعد"
        )

    elif trend_4h == "SHORT":

        short_score += 15

        reasons_short.append(
            "4H يدعم الاتجاه الهابط"
        )

    # 1H
    if trend_1h == "LONG":

        long_score += 15

        reasons_long.append(
            "1H يدعم الدخول LONG"
        )

    elif trend_1h == "SHORT":

        short_score += 15

        reasons_short.append(
            "1H يدعم الدخول SHORT"
        )

    # 30m
    if trend_30m == "LONG":
        long_score += 8

    elif trend_30m == "SHORT":
        short_score += 8

    # 15m
    if trend_15m == "LONG":
        long_score += 6

    elif trend_15m == "SHORT":
        short_score += 6

    # BOS
    if bos == "BULLISH":

        long_score += 12

        reasons_long.append(
            "BOS صاعد مؤكد"
        )

    elif bos == "BEARISH":

        short_score += 12

        reasons_short.append(
            "BOS هابط مؤكد"
        )

    # Structure
    if structure == "BULLISH":
        long_score += 8

    elif structure == "BEARISH":
        short_score += 8

    # Liquidity
    if liquidity == "INFLOW":

        long_score += 10

        reasons_long.append(
            "السيولة تدخل للسوق"
        )

    elif liquidity == "OUTFLOW":

        short_score += 10

        reasons_short.append(
            "السيولة تخرج من السوق"
        )

    # Buy pressure
    if buy_pressure >= 57:
        long_score += 6

    elif buy_pressure <= 43:
        short_score += 6

    # Volume
    if volume_ratio >= 1.10:

        if buy_pressure >= 50:
            long_score += 5
        else:
            short_score += 5

    elif volume_ratio >= 0.75:

        if buy_pressure >= 50:
            long_score += 2
        else:
            short_score += 2

    # RSI
    if 35 <= rsi <= 48:

        long_score += 5

    elif 52 <= rsi <= 65:

        short_score += 5

    elif rsi < 30:

        long_score += 7

    elif rsi > 70:

        short_score += 7

    # EMA
    if ema == "BULLISH":

        long_score += 5

        reasons_long.append(
            "EMA9 فوق EMA20"
        )

    elif ema == "BEARISH":

        short_score += 5

        reasons_short.append(
            "EMA9 تحت EMA20"
        )

    # Accumulation
    if bottom["found"]:

        long_score += 8

        reasons_long.append(
            "تم اكتشاف احتمال قاع/تجميع"
        )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    if long_score > short_score:

        direction = "LONG"
        score = long_score
        reasons = reasons_long

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score
        reasons = reasons_short

    else:

        direction = "NEUTRAL"
        score = 0
        reasons = []

    score = max(
        0,
        min(
            100,
            int(score)
        )
    )

    # =====================================================
    # ENTRY CONDITIONS
    # =====================================================

    long_confirmation_count = 0

    short_confirmation_count = 0

    if trend_30m == "LONG":
        long_confirmation_count += 1

    if trend_15m == "LONG":
        long_confirmation_count += 1

    if bos == "BULLISH":
        long_confirmation_count += 1

    if liquidity == "INFLOW":
        long_confirmation_count += 1

    if buy_pressure >= 55:
        long_confirmation_count += 1

    if trend_30m == "SHORT":
        short_confirmation_count += 1

    if trend_15m == "SHORT":
        short_confirmation_count += 1

    if bos == "BEARISH":
        short_confirmation_count += 1

    if liquidity == "OUTFLOW":
        short_confirmation_count += 1

    if buy_pressure <= 45:
        short_confirmation_count += 1

    long_confirmation = (
        trend_1h == "LONG"
        and long_confirmation_count >= 2
    )

    short_confirmation = (
        trend_1h == "SHORT"
        and short_confirmation_count >= 2
    )

    trade_type = "NO TRADE"

    decision = "انتظار تأكيد إضافي"

    entry = None
    stop_loss = None
    tp1 = None
    tp2 = None
    tp3 = None

    # =====================================================
    # ENTRY READY
    # =====================================================

    if (
        direction == "LONG"
        and score >= 50
        and long_confirmation
    ):

        trade_type = "ENTRY READY"

        decision = "صفقة LONG جاهزة"

        (
            entry,
            stop_loss,
            tp1,
            tp2,
            tp3
        ) = build_trade_levels(
            "LONG",
            price,
            atr,
            support,
            resistance
        )

    elif (
        direction == "SHORT"
        and score >= 50
        and short_confirmation
    ):

        trade_type = "ENTRY READY"

        decision = "صفقة SHORT جاهزة"

        (
            entry,
            stop_loss,
            tp1,
            tp2,
            tp3
        ) = build_trade_levels(
            "SHORT",
            price,
            atr,
            support,
            resistance
        )

    # =====================================================
    # REVERSAL WATCH
    # =====================================================

    elif (
        direction == "LONG"
        and bottom["found"]
        and score >= 25
    ):

        trade_type = "REVERSAL WATCH"

        decision = (
            "ننتظر تأكيد التحول الصاعد "
            "على 1H/BOS"
        )

    elif (
        direction == "SHORT"
        and score >= 25
        and (
            bos == "BEARISH"
            or liquidity == "OUTFLOW"
        )
    ):

        trade_type = "REVERSAL WATCH"

        decision = (
            "ننتظر تأكيد استمرار الهبوط "
            "على 1H/30m"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    elif (
        bottom["found"]
        and score >= 20
    ):

        trade_type = "ACCUMULATION WATCH"

        decision = (
            "تجميع مبكر؛ ننتظر تحول 1H/BOS"
        )

    # =====================================================
    # IMPORTANT FALLBACK
    # =====================================================
    #
    # لو فيه اتجاه واضح حتى لو لم يتحقق
    # WATCH بالكامل، لا نخفي العملة.
    #

    elif score >= 20:

        trade_type = "REVERSAL WATCH"

        if direction == "LONG":

            decision = (
                "ميل صاعد؛ ننتظر تأكيد الدخول"
            )

        elif direction == "SHORT":

            decision = (
                "ميل هابط؛ ننتظر تأكيد الدخول"
            )

        else:

            decision = (
                "السوق غير حاسم حالياً"
            )

    # =====================================================
    # DATA
    # =====================================================

    return {
        "symbol": symbol,
        "price": price,

        "direction": direction,
        "final_direction": direction,

        "score": score,
        "entry_score": score,

        "trade_type": trade_type,
        "status": trade_type,
        "decision": decision,

        "trend_1d": trend_1d,
        "trend_4h": trend_4h,
        "trend_1h": trend_1h,
        "trend_30m": trend_30m,
        "trend_15m": trend_15m,

        "structure": structure,
        "bos": bos,

        "liquidity": liquidity,
        "buy_pressure": buy_pressure,

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "rsi": rsi,
        "ema_state": ema,

        "bottom_found": bottom["found"],
        "bottom_score": bottom["score"],
        "drawdown": bottom.get(
            "drawdown",
            0
        ),

        "support": support,
        "resistance": resistance,

        "distance_support": distance_support,
        "distance_resistance": distance_resistance,

        "atr": atr,

        "entry": entry,
        "stop_loss": stop_loss,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "move_2": move_2,
        "move_6": move_6,

        "reasons": reasons,

        "long_score": long_score,
        "short_score": short_score,

        "bottom_reasons": bottom.get(
            "reason",
            []
        ),
    }


# =========================================================
# FAST SCAN
# =========================================================

def scan_market(limit=5):

    start_time = time.time()

    symbols = get_futures_symbols()

    if not symbols:
        return []

    priority = [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "SUIUSDT",
        "LINKUSDT",
        "ENAUSDT",
        "AVAXUSDT",
        "LTCUSDT",
        "DOTUSDT",
        "TRXUSDT",
        "PEPEUSDT",
    ]

    symbol_set = set(symbols)

    selected = []

    # =====================================================
    # PRIORITY
    # =====================================================

    for symbol in priority:

        if symbol in symbol_set:
            selected.append(symbol)

    # =====================================================
    # ADD OTHER SYMBOLS
    # =====================================================

    for symbol in symbols:

        if symbol not in selected:

            selected.append(symbol)

        if len(selected) >= 30:
            break

    candidates = []

    # =====================================================
    # FAST 1H SCAN
    # =====================================================

    for symbol in selected:

        try:

            klines = get_klines(
                symbol,
                "1h",
                80
            )

            if len(klines) < 50:
                continue

            closes = [
                x["close"]
                for x in klines
            ]

            trend = calculate_timeframe_trend(
                klines
            )

            volume_ratio = calculate_volume_ratio(
                klines
            )

            rsi = calculate_rsi(
                closes,
                14
            )

            if rsi is None:
                rsi = 50

            structure, bos = detect_market_structure(
                klines
            )

            liquidity, buy_pressure = detect_liquidity_flow(
                klines
            )

            bottom = detect_bottom_accumulation(
                klines
            )

            move_6 = calculate_recent_move(
                klines,
                6
            )

            fast_score = 0

            # Trend
            if trend == "LONG":
                fast_score += 12

            elif trend == "SHORT":
                fast_score += 12

            # BOS
            if bos != "NONE":
                fast_score += 15

            # Structure
            if structure != "MIXED":
                fast_score += 10

            # Liquidity
            if liquidity != "NEUTRAL":
                fast_score += 12

            # Volume
            if volume_ratio >= 0.85:
                fast_score += 8

            # Bottom
            if bottom["found"]:
                fast_score += 20

            # RSI
            if (
                rsi <= 42
                or rsi >= 58
            ):
                fast_score += 8

            # Movement
            if abs(move_6) >= 0.8:
                fast_score += 5

            # Pressure
            if (
                buy_pressure >= 55
                or buy_pressure <= 45
            ):
                fast_score += 5

            candidates.append({
                "symbol": symbol,
                "fast_score": fast_score,
            })

        except Exception as exc:

            logger.warning(
                "Fast scan error %s: %s",
                symbol,
                exc
            )

    # =====================================================
    # SORT
    # =====================================================

    candidates.sort(
        key=lambda x: x["fast_score"],
        reverse=True
    )

    # =====================================================
    # DEEP ANALYSIS
    # =====================================================

    deep_results = []

    for item in candidates[:10]:

        try:

            data = get_coin_analysis(
                item["symbol"]
            )

            if not data:
                continue

            # =================================================
            # IMPORTANT:
            # Keep all useful WATCH states.
            # Only remove truly useless NO TRADE.
            # =================================================

            if (
                data["trade_type"]
                in (
                    "ENTRY READY",
                    "REVERSAL WATCH",
                    "ACCUMULATION WATCH",
                )
            ):

                deep_results.append(data)

            elif data["score"] >= 15:

                deep_results.append(data)

        except Exception as exc:

            logger.warning(
                "Deep analysis error %s: %s",
                item["symbol"],
                exc
            )

    # =====================================================
    # FALLBACK
    # =====================================================

    #
    # لو التحليل العميق لم يعطِ نتيجة،
    # نأخذ أفضل مرشح ونحلله مرة أخرى.
    #

    if not deep_results and candidates:

        for item in candidates[:3]:

            try:

                data = get_coin_analysis(
                    item["symbol"]
                )

                if data:

                    deep_results.append(data)

            except Exception:
                continue

    # =====================================================
    # PRIORITY
    # =====================================================

    priority_map = {
        "ENTRY READY": 4,
        "REVERSAL WATCH": 3,
        "ACCUMULATION WATCH": 2,
        "NO TRADE": 1,
    }

    deep_results.sort(
        key=lambda x: (
            priority_map.get(
                x.get(
                    "trade_type",
                    "NO TRADE"
                ),
                0
            ),
            x.get(
                "score",
                0
            ),
            x.get(
                "bottom_score",
                0
            ),
        ),
        reverse=True
    )

    elapsed = (
        time.time()
        - start_time
    )

    logger.info(
        "Market scan finished: %.2f seconds | results=%s",
        elapsed,
        len(deep_results)
    )

    return deep_results[:limit]


# =========================================================
# FORMAT PRICE
# =========================================================

def _fmt_price(value):

    if value is None:
        return "غير محدد"

    try:

        value = float(value)

        if value >= 1000:
            return f"{value:.2f}"

        if value >= 1:
            return f"{value:.5f}"

        if value >= 0.01:
            return f"{value:.6f}"

        return f"{value:.8f}"

    except Exception:

        return "غير محدد"


# =========================================================
# FORMAT PERCENT
# =========================================================

def _fmt_percent(value):

    if value is None:
        return "0.00%"

    try:
        return f"{float(value):.2f}%"

    except Exception:
        return "0.00%"


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(data):

    symbol = data.get(
        "symbol",
        "UNKNOWN"
    )

    direction = data.get(
        "direction",
        "NEUTRAL"
    )

    score = data.get(
        "score",
        0
    )

    trade_type = data.get(
        "trade_type",
        "NO TRADE"
    )

    if trade_type == "ENTRY READY":

        if direction == "LONG":
            direction_text = "🟢 LONG"

        elif direction == "SHORT":
            direction_text = "🔴 SHORT"

        else:
            direction_text = "🟡 NEUTRAL"

    else:

        direction_text = "🟡 NO TRADE"

    if trade_type == "ENTRY READY":

        state = (
            "🟢 ENTRY READY - صفقة جاهزة"
        )

    elif trade_type == "REVERSAL WATCH":

        state = (
            "🟡 REVERSAL WATCH - "
            "ننتظر تأكيد الانعكاس"
        )

    elif trade_type == "ACCUMULATION WATCH":

        state = (
            "🔵 ACCUMULATION WATCH - "
            "تجميع مبكر"
        )

    else:

        state = (
            "🟡 NO TRADE - "
            "الشروط غير مكتملة"
        )

    lines = []

    lines.append(
        "🤖 BingX AI Scanner"
    )

    lines.append("")

    lines.append(
        f"💎 العملة: {symbol}"
    )

    lines.append(
        f"📈 الاتجاه النهائي: {direction_text}"
    )

    lines.append(
        f"⭐ Entry Score: {score}/100"
    )

    lines.append("")

    lines.append(
        f"🧠 الحالة: {state}"
    )

    lines.append(
        f"🧭 القرار: "
        f"{data.get('decision', 'انتظار')}"
    )

    lines.append("")

    # =====================================================
    # TREND
    # =====================================================

    lines.append(
        "📊 الاتجاه العام"
    )

    lines.append(
        f"1D: {data.get('trend_1d', 'NEUTRAL')}"
    )

    lines.append(
        f"4H: {data.get('trend_4h', 'NEUTRAL')}"
    )

    lines.append("")

    # =====================================================
    # ENTRY CONFIRMATION
    # =====================================================

    lines.append(
        "🔎 تأكيد الدخول"
    )

    lines.append(
        f"1H: {data.get('trend_1h', 'NEUTRAL')}"
    )

    lines.append(
        f"30m: {data.get('trend_30m', 'NEUTRAL')}"
    )

    lines.append(
        f"15m: {data.get('trend_15m', 'NEUTRAL')}"
    )

    lines.append(
        f"هيكل السوق: "
        f"{data.get('structure', 'MIXED')}"
    )

    bos = data.get(
        "bos",
        "NONE"
    )

    if bos == "BULLISH":
        bos_text = "🟢 BULLISH"

    elif bos == "BEARISH":
        bos_text = "🔴 BEARISH"

    else:
        bos_text = "⚪ NONE"

    lines.append(
        f"BOS: {bos_text}"
    )

    liquidity = data.get(
        "liquidity",
        "NEUTRAL"
    )

    if liquidity == "INFLOW":
        liquidity_text = "🟢 INFLOW"

    elif liquidity == "OUTFLOW":
        liquidity_text = "🔴 OUTFLOW"

    else:
        liquidity_text = "🟡 سيولة محايدة"

    lines.append(
        f"💧 السيولة: {liquidity_text}"
    )

    lines.append(
        f"📊 Volume: "
        f"{data.get('volume_ratio', 0):.2f}x"
    )

    lines.append(
        f"📈 Volume Trend: "
        f"{data.get('volume_trend', 'NEUTRAL')}"
    )

    lines.append(
        f"💪 Buy Pressure: "
        f"{data.get('buy_pressure', 50)}%"
    )

    lines.append(
        f"📊 RSI: "
        f"{data.get('rsi', 50):.2f}"
    )

    lines.append("")

    # =====================================================
    # BOTTOM
    # =====================================================

    bottom_found = data.get(
        "bottom_found",
        False
    )

    if bottom_found:

        bottom_text = (
            "🟢 نعم — تجميع مبكر"
        )

    else:

        bottom_text = (
            "⚪ لا يوجد تأكيد قوي"
        )

    lines.append(
        f"🎯 القاع/التجميع: {bottom_text}"
    )

    lines.append(
        "📉 الهبوط السابق: "
        + _fmt_percent(
            data.get(
                "drawdown",
                0
            )
        )
    )

    lines.append("")

    # =====================================================
    # S/R
    # =====================================================

    lines.append(
        "🛡️ الدعم والمقاومة"
    )

    lines.append(
        f"🟢 Support: "
        f"{_fmt_price(data.get('support'))}"
    )

    lines.append(
        f"🔴 Resistance: "
        f"{_fmt_price(data.get('resistance'))}"
    )

    lines.append(
        "📏 البعد عن الدعم: "
        + _fmt_percent(
            data.get(
                "distance_support",
                0
            )
        )
    )

    lines.append(
        "📏 البعد عن المقاومة: "
        + _fmt_percent(
            data.get(
                "distance_resistance",
                0
            )
        )
    )

    lines.append("")

    # =====================================================
    # ENTRY
    # =====================================================

    lines.append(
        "📍 منطقة الدخول"
    )

    if data.get("entry"):

        lines.append(
            f"Entry: "
            f"{_fmt_price(data.get('entry'))}"
        )

    else:

        lines.append(
            "⏳ انتظار تأكيد"
        )

    lines.append("")

    # =====================================================
    # STOP
    # =====================================================

    lines.append(
        f"🛑 Stop Loss: "
        f"{_fmt_price(data.get('stop_loss'))}"
    )

    lines.append("")

    # =====================================================
    # TARGETS
    # =====================================================

    lines.append(
        "🎯 الأهداف"
    )

    lines.append(
        f"TP1: {_fmt_price(data.get('tp1'))}"
    )

    lines.append(
        f"TP2: {_fmt_price(data.get('tp2'))}"
    )

    lines.append(
        f"TP3: {_fmt_price(data.get('tp3'))}"
    )

    lines.append("")

    # =====================================================
    # MOVEMENT
    # =====================================================

    lines.append(
        "📊 الحركة الأخيرة"
    )

    lines.append(
        "آخر شمعتين تقريباً: "
        + _fmt_percent(
            data.get(
                "move_2",
                0
            )
        )
    )

    lines.append(
        "آخر 6 شموع تقريباً: "
        + _fmt_percent(
            data.get(
                "move_6",
                0
            )
        )
    )

    lines.append("")

    # =====================================================
    # REASONS
    # =====================================================

    lines.append(
        "🔍 أسباب القرار"
    )

    reasons = data.get(
        "reasons",
        []
    )

    if reasons:

        for reason in reasons[:8]:

            lines.append(
                f"• {reason}"
            )

    else:

        lines.append(
            "• لا توجد عوامل قوية كافية حالياً"
        )

    # =====================================================
    # STRUCTURE
    # =====================================================

    lines.append("")

    lines.append(
        "🏗️ أدلة هيكل السوق"
    )

    if bos == "BULLISH":

        lines.append(
            "• تم تأكيد كسر هيكل صاعد BOS"
        )

    elif bos == "BEARISH":

        lines.append(
            "• تم تأكيد كسر هيكل هابط BOS"
        )

    else:

        lines.append(
            "• لا يوجد BOS مؤكد حالياً"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    lines.append("")

    lines.append(
        "💧 أدلة السيولة"
    )

    if liquidity == "INFLOW":

        lines.append(
            "• تدفق شرائي واضح"
        )

    elif liquidity == "OUTFLOW":

        lines.append(
            "• ضغط بيعي واضح"
        )

    else:

        lines.append(
            "• السيولة ما زالت محايدة"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    if bottom_found:

        lines.append("")

        lines.append(
            "🎯 أدلة التجميع"
        )

        bottom_reasons = data.get(
            "bottom_reasons",
            []
        )

        if bottom_reasons:

            for reason in bottom_reasons:

                lines.append(
                    f"• {reason}"
                )

        else:

            lines.append(
                "• توجد مؤشرات تجميع مبكرة"
            )

    # =====================================================
    # WHY NO ENTRY
    # =====================================================

    if trade_type != "ENTRY READY":

        lines.append("")

        lines.append(
            "🚫 لماذا لم يدخل؟"
        )

        if data.get("trend_1h") == "LONG":

            if data.get("bos") != "BULLISH":

                lines.append(
                    "• الاتجاه الصاعد موجود "
                    "لكن BOS الصاعد غير مؤكد"
                )

        elif data.get("trend_1h") == "SHORT":

            if data.get("bos") != "BEARISH":

                lines.append(
                    "• الاتجاه الهابط موجود "
                    "لكن BOS الهابط غير مؤكد"
                )

        if data.get("liquidity") == "NEUTRAL":

            lines.append(
                "• السيولة محايدة"
            )

        lines.append(
            "• لا يوجد تأكيد دخول كامل حالياً"
        )

    # =====================================================
    # FOOTER
    # =====================================================

    lines.append("")

    lines.append(
        "⚠️ إشارة تحليلية وليست ضماناً للربح."
    )

    lines.append(
        "⚠️ 1D + 4H للاتجاه العام."
    )

    lines.append(
        "⚠️ 1H + 30m + 15m لتأكيد الدخول."
    )

    lines.append(
        "⚠️ BOS + السيولة + الحجم عوامل تأكيد."
    )

    lines.append(
        "⚠️ لا تعتمد الصفقة إذا تحرك السعر "
        "عكس شروط الدخول."
    )

    return "\n".join(lines)
