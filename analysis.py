import time
import logging
import threading
import requests

# =========================================================
# BINGX CONFIG
# =========================================================

BINGX_URL = "https://open-api.bingx.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal-BingX-Scanner/9.0",
    "Accept": "application/json"
})

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 12

# =========================================================
# CACHE / RATE LIMIT
# =========================================================

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

SYMBOL_CACHE_SECONDS = 600

_KLINE_CACHE = {}
_KLINE_CACHE_TIME = {}

KLINE_CACHE_SECONDS = 45

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

MIN_REQUEST_INTERVAL = 0.45

_RATE_LIMIT_UNTIL = 0


# =========================================================
# PRIORITY SYMBOLS
# =========================================================

PRIORITY_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "SUIUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
    "DOTUSDT",
    "TRXUSDT",
    "PEPEUSDT",
    "SHIBUSDT",
    "UNIUSDT",
    "WIFUSDT",
    "BONKUSDT",
    "FLOKIUSDT",
    "SEIUSDT",
    "NEARUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "INJUSDT",
    "TIAUSDT",
    "ATOMUSDT",
    "FILUSDT",
    "AAVEUSDT",
    "MKRUSDT",
    "CRVUSDT",
    "COMPUSDT",
    "JUPUSDT",
    "RAYUSDT",
    "WLDUSDT",
    "ONDOUSDT",
    "ENAUSDT",
    "PENDLEUSDT",
    "STXUSDT",
    "IMXUSDT",
    "GALAUSDT",
    "SANDUSDT",
    "MANAUSDT",
    "AXSUSDT",
    "APEUSDT",
    "FETUSDT",
    "TAOUSDT",
    "RENDERUSDT",
    "HBARUSDT",
    "ALGOUSDT",
    "VETUSDT",
    "ICPUSDT",
    "ETCUSDT",
    "BCHUSDT",
    "XLMUSDT",
    "KASUSDT",
    "HEIUSDT",
    "ACTUSDT",
    "CHIPUSDT",
    "MAGUSDT",
    "COLOUSDT",
    "NITUSDT",
    "STARUSDT",
}


# =========================================================
# REQUEST THROTTLE
# =========================================================

def _throttle():
    global _LAST_REQUEST_TIME

    with _REQUEST_LOCK:
        now = time.time()

        wait = MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST_TIME)

        if wait > 0:
            time.sleep(wait)

        _LAST_REQUEST_TIME = time.time()


# =========================================================
# BINGX REQUEST
# =========================================================

def bingx_get(path, params=None):
    global _RATE_LIMIT_UNTIL

    if time.time() < _RATE_LIMIT_UNTIL:
        return None

    _throttle()

    try:
        response = SESSION.get(
            BINGX_URL + path,
            params=params or {},
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            logger.warning(
                "BingX HTTP %s: %s",
                response.status_code,
                response.text[:300]
            )
            return None

        data = response.json()

        if not isinstance(data, dict):
            return None

        code = data.get("code")

        if code in (109429, 109400):
            _RATE_LIMIT_UNTIL = time.time() + 60

            logger.warning(
                "BingX rate limit detected. Cooldown 60 seconds."
            )

            return None

        if code not in (0, None):
            logger.warning(
                "BingX API error %s: %s",
                code,
                str(data)[:400]
            )

            return None

        return data

    except requests.RequestException as exc:
        logger.warning("BingX request error: %s", exc)
        return None

    except Exception as exc:
        logger.exception(
            "Unexpected BingX error: %s",
            exc
        )

        return None


# =========================================================
# SYMBOL NORMALIZATION
# =========================================================

def normalize_symbol(symbol):
    if not symbol:
        return ""

    s = str(symbol).upper().strip()

    for char in " /-_":
        s = s.replace(char, "")

    if s.endswith("USDT"):
        return s

    return s + "USDT"


def bingx_symbol(symbol):
    s = normalize_symbol(symbol)

    if s.endswith("USDT") and s[:-4]:
        return f"{s[:-4]}-USDT"

    return s


# =========================================================
# DATA EXTRACTION
# =========================================================

def _extract_rows(data):
    if not data:
        return []

    rows = data.get("data")

    if isinstance(rows, dict):
        rows = rows.get(
            "data",
            rows.get(
                "rows",
                [rows]
            )
        )

    return rows if isinstance(rows, list) else []


# =========================================================
# FUTURES SYMBOLS
# =========================================================

def get_futures_symbols():
    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    now = time.time()

    if (
        _SYMBOL_CACHE
        and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS
    ):
        return list(_SYMBOL_CACHE)

    symbols = set()

    endpoints = (
        "/openApi/swap/v2/quote/contracts",
        "/openApi/swap/v2/quote/ticker"
    )

    for endpoint in endpoints:

        rows = _extract_rows(
            bingx_get(endpoint)
        )

        for item in rows:

            if not isinstance(item, dict):
                continue

            symbol = (
                item.get("symbol")
                or item.get("pair")
                or item.get("contract")
            )

            if not symbol:
                continue

            symbol = normalize_symbol(
                str(symbol).replace("-", "")
            )

            if symbol.endswith("USDT"):
                symbols.add(symbol)

        if symbols:
            break

    if not symbols:

        logger.warning(
            "BingX symbol discovery failed; using fallback."
        )

        symbols = set(PRIORITY_SYMBOLS)

    _SYMBOL_CACHE = symbols
    _SYMBOL_CACHE_TIME = time.time()

    logger.info(
        "Loaded %s BingX USDT futures symbols",
        len(symbols)
    )

    return list(symbols)


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
        str(interval).lower(),
        interval
    )


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval="1h", limit=120):

    api_symbol = bingx_symbol(symbol)

    interval = _interval_to_bingx(interval)

    limit = int(limit)

    key = (
        api_symbol,
        interval,
        limit
    )

    now = time.time()

    if (
        key in _KLINE_CACHE
        and now - _KLINE_CACHE_TIME.get(key, 0)
        < KLINE_CACHE_SECONDS
    ):
        return _KLINE_CACHE[key]

    data = bingx_get(
        "/openApi/swap/v2/quote/klines",
        {
            "symbol": api_symbol,
            "interval": interval,
            "limit": limit
        }
    )

    rows = _extract_rows(data)

    result = []

    for row in rows:

        try:

            if isinstance(row, dict):

                ts = (
                    row.get("time")
                    or row.get("timestamp")
                    or row.get("openTime")
                )

                o = (
                    row.get("open")
                    or row.get("o")
                )

                h = (
                    row.get("high")
                    or row.get("h")
                )

                l = (
                    row.get("low")
                    or row.get("l")
                )

                c = (
                    row.get("close")
                    or row.get("c")
                )

                v = (
                    row.get("volume")
                    or row.get("v")
                    or 0
                )

            elif isinstance(row, (list, tuple)) and len(row) >= 6:

                ts, o, h, l, c, v = row[:6]

            else:
                continue

            if None in (o, h, l, c):
                continue

            result.append({
                "time": float(ts or 0),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v or 0)
            })

        except Exception:
            continue

    result.sort(
        key=lambda x: x["time"]
    )

    if result:

        _KLINE_CACHE[key] = result
        _KLINE_CACHE_TIME[key] = time.time()

    return result


# =========================================================
# CURRENT PRICE
# =========================================================

def get_current_price(symbol):

    data = bingx_get(
        "/openApi/swap/v2/quote/ticker",
        {
            "symbol": bingx_symbol(symbol)
        }
    )

    for item in _extract_rows(data):

        if not isinstance(item, dict):
            continue

        for key in (
            "lastPrice",
            "last",
            "price",
            "markPrice"
        ):

            try:

                value = float(
                    item.get(key)
                )

                if value > 0:
                    return value

            except Exception:
                pass

    klines = get_klines(
        symbol,
        "1m",
        3
    )

    if klines:
        return klines[-1]["close"]

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

    result = [None] * (period - 1)

    previous = sum(
        values[:period]
    ) / period

    result.append(previous)

    multiplier = 2 / (period + 1)

    for value in values[period:]:

        previous = (
            (value - previous)
            * multiplier
            + previous
        )

        result.append(previous)

    return result


# =========================================================
# RSI
# =========================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        diff = values[i] - values[i - 1]

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

    average_gain = (
        sum(gains[:period]) / period
    )

    average_loss = (
        sum(losses[:period]) / period
    )

    for i in range(period, len(gains)):

        average_gain = (
            (
                average_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        average_loss = (
            (
                average_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    rs = average_gain / average_loss

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# ATR
# =========================================================

def calculate_atr(klines, period=14):

    if len(klines) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(klines)):

        current = klines[i]
        previous = klines[i - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(
                current["high"]
                - previous["close"]
            ),
            abs(
                current["low"]
                - previous["close"]
            )
        )

        true_ranges.append(
            true_range
        )

    recent = true_ranges[-period:]

    if not recent:
        return None

    return sum(recent) / len(recent)


# =========================================================
# VOLUME RATIO
# =========================================================

def calculate_volume_ratio(
    klines,
    period=20
):

    if len(klines) < 2:
        return 0

    previous = [
        x["volume"]
        for x in klines[-(period + 1):-1]
    ]

    if not previous:
        return 0

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 0

    return (
        klines[-1]["volume"]
        / average
    )


# =========================================================
# VOLUME TREND
# =========================================================

def calculate_volume_trend(
    klines,
    period=5
):

    if len(klines) < period * 2:
        return "NEUTRAL"

    recent = sum(
        x["volume"]
        for x in klines[-period:]
    ) / period

    previous = sum(
        x["volume"]
        for x in klines[-period * 2:-period]
    ) / period

    if previous <= 0:
        return "NEUTRAL"

    ratio = recent / previous

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

def calculate_timeframe_trend(klines):

    if len(klines) < 60:
        return "NEUTRAL"

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(
        closes,
        9
    )[-1]

    ema20 = calculate_ema(
        closes,
        20
    )[-1]

    ema50 = calculate_ema(
        closes,
        50
    )[-1]

    price = closes[-1]

    if (
        ema9
        and ema20
        and ema50
        and ema9 > ema20
        and ema20 > ema50
        and price > ema20
    ):
        return "LONG"

    if (
        ema9
        and ema20
        and ema50
        and ema9 < ema20
        and ema20 < ema50
        and price < ema20
    ):
        return "SHORT"

    if (
        ema9
        and ema20
        and price > ema20
        and ema9 > ema20
    ):
        return "LONG"

    if (
        ema9
        and ema20
        and price < ema20
        and ema9 < ema20
    ):
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(klines):

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

    if close > previous_high:
        return "BULLISH", "BULLISH"

    if close < previous_low:
        return "BEARISH", "BEARISH"

    if (
        recent_high > previous_high
        and recent_low > previous_low
    ):
        return "BULLISH", "NONE"

    if (
        recent_high < previous_high
        and recent_low < previous_low
    ):
        return "BEARISH", "NONE"

    return "MIXED", "NONE"


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(klines):

    if len(klines) < 20:
        return "NEUTRAL", 50

    recent = klines[-12:]

    bullish_volume = sum(
        x["volume"]
        for x in recent
        if x["close"] > x["open"]
    )

    bearish_volume = sum(
        x["volume"]
        for x in recent
        if x["close"] < x["open"]
    )

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
        > bearish_volume * 1.12
        and volume_ratio >= 0.90
    ):
        return "INFLOW", round(
            buy_pressure
        )

    if (
        bearish_volume
        > bullish_volume * 1.12
        and volume_ratio >= 0.90
    ):
        return "OUTFLOW", round(
            buy_pressure
        )

    return "NEUTRAL", round(
        buy_pressure
    )


# =========================================================
# BOTTOM / ACCUMULATION
# =========================================================

def detect_bottom_accumulation(klines):

    result = {
        "found": False,
        "score": 0,
        "drawdown": 0,
        "recent_range": 0,
        "volume_ratio": 0,
        "volume_trend": "NEUTRAL",
        "reason": []
    }

    if len(klines) < 40:
        return result

    closes = [
        x["close"]
        for x in klines
    ]

    current = closes[-1]

    previous_high = max(
        closes[-40:-5]
    )

    if previous_high <= 0:
        return result

    drawdown = (
        current / previous_high
        - 1
    ) * 100

    recent = klines[-10:]

    high = max(
        x["high"]
        for x in recent
    )

    low = min(
        x["low"]
        for x in recent
    )

    recent_range = (
        (high - low)
        / low
        * 100
        if low > 0
        else 0
    )

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
        reasons.append(
            "تصحيح عميق"
        )

    if recent_range <= 18:
        score += 1
        reasons.append(
            "النطاق السعري بدأ يضيق"
        )

    if volume_ratio >= 0.80:
        score += 1
        reasons.append(
            "الحجم ما زال موجوداً بعد الهبوط"
        )

    if volume_trend in (
        "RISING",
        "STABLE"
    ):
        score += 1
        reasons.append(
            "الحجم لا يزال داعماً"
        )

    rejection_count = 0

    for candle in recent[-6:]:

        candle_range = max(
            candle["high"]
            - candle["low"],
            1e-12
        )

        lower_wick = (
            min(
                candle["open"],
                candle["close"]
            )
            - candle["low"]
        )

        if (
            lower_wick
            >= candle_range * 0.60
        ):
            rejection_count += 1

    if rejection_count >= 1:
        score += 1
        reasons.append(
            "رفض سعري من الأسفل"
        )

    result.update({
        "found": score >= 3,
        "score": score,
        "drawdown": drawdown,
        "recent_range": recent_range,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "reason": reasons
    })

    return result


# =========================================================
# RECENT MOVE
# =========================================================

def calculate_recent_move(
    klines,
    n
):

    if len(klines) <= n:
        return 0

    old_price = klines[
        -n - 1
    ]["close"]

    new_price = klines[
        -1
    ]["close"]

    if old_price <= 0:
        return 0

    return (
        new_price / old_price
        - 1
    ) * 100


# =========================================================
# EMA STATE
# =========================================================

def ema_state(klines):

    if len(klines) < 20:
        return "MIXED"

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(
        closes,
        9
    )[-1]

    ema20 = calculate_ema(
        closes,
        20
    )[-1]

    if ema9 > ema20:
        return "BULLISH"

    if ema9 < ema20:
        return "BEARISH"

    return "MIXED"


# =========================================================
# MOMENTUM DETECTOR
# =========================================================

def detect_momentum(klines):

    result = {
        "state": "NEUTRAL",
        "score": 0,
        "move_2": 0,
        "move_6": 0,
        "volume_ratio": 0,
        "volume_trend": "NEUTRAL",
        "reason": []
    }

    if len(klines) < 30:
        return result

    move_2 = calculate_recent_move(
        klines,
        2
    )

    move_6 = calculate_recent_move(
        klines,
        6
    )

    volume_ratio = calculate_volume_ratio(
        klines
    )

    volume_trend = calculate_volume_trend(
        klines
    )

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(
        closes,
        9
    )[-1]

    ema20 = calculate_ema(
        closes,
        20
    )[-1]

    score = 0
    reasons = []

    bullish = 0
    bearish = 0

    if move_2 >= 0.60:
        bullish += 1
        score += 2
        reasons.append(
            "حركة صاعدة حديثة"
        )

    elif move_2 <= -0.60:
        bearish += 1
        score += 2
        reasons.append(
            "حركة هابطة حديثة"
        )

    if move_6 >= 1.20:
        bullish += 1
        score += 2
        reasons.append(
            "Momentum صاعد على عدة شموع"
        )

    elif move_6 <= -1.20:
        bearish += 1
        score += 2
        reasons.append(
            "Momentum هابط على عدة شموع"
        )

    if volume_ratio >= 1.20:
        score += 2
        reasons.append(
            "الحجم أعلى من المتوسط"
        )

    elif volume_ratio >= 0.90:
        score += 1

    if volume_trend == "RISING":
        score += 2
        reasons.append(
            "الحجم في ارتفاع"
        )

    if (
        ema9
        and ema20
        and ema9 > ema20
    ):
        bullish += 1

    elif (
        ema9
        and ema20
        and ema9 < ema20
    ):
        bearish += 1

    if bullish >= 2 and bullish > bearish:
        result["state"] = "BULLISH"

    elif bearish >= 2 and bearish > bullish:
        result["state"] = "BEARISH"

    else:
        result["state"] = "NEUTRAL"

    result.update({
        "score": score,
        "move_2": move_2,
        "move_6": move_6,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "reason": reasons
    })

    return result


# =========================================================
# TREND START DETECTOR
# =========================================================

def detect_trend_start(klines):

    result = {
        "found": False,
        "direction": "NEUTRAL",
        "score": 0,
        "reason": []
    }

    if len(klines) < 60:
        return result

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

    current_price = closes[-1]

    score_long = 0
    score_short = 0

    reasons_long = []
    reasons_short = []

    if (
        ema9[-1]
        and ema20[-1]
        and ema9[-1] > ema20[-1]
    ):
        score_long += 2
        reasons_long.append(
            "EMA9 فوق EMA20"
        )

    if (
        ema9[-1]
        and ema20[-1]
        and ema9[-1] < ema20[-1]
    ):
        score_short += 2
        reasons_short.append(
            "EMA9 تحت EMA20"
        )

    if (
        ema20[-1]
        and ema50[-1]
        and ema20[-1] > ema50[-1]
    ):
        score_long += 2
        reasons_long.append(
            "EMA20 فوق EMA50"
        )

    if (
        ema20[-1]
        and ema50[-1]
        and ema20[-1] < ema50[-1]
    ):
        score_short += 2
        reasons_short.append(
            "EMA20 تحت EMA50"
        )

    if (
        ema20[-1]
        and current_price > ema20[-1]
    ):
        score_long += 1

    if (
        ema20[-1]
        and current_price < ema20[-1]
    ):
        score_short += 1

    recent_move = calculate_recent_move(
        klines,
        6
    )

    if recent_move >= 1.0:
        score_long += 2
        reasons_long.append(
            "السعر بدأ يتحرك صعوداً"
        )

    if recent_move <= -1.0:
        score_short += 2
        reasons_short.append(
            "السعر بدأ يتحرك هبوطاً"
        )

    volume_ratio = calculate_volume_ratio(
        klines
    )

    if volume_ratio >= 1.10:

        if score_long > score_short:
            score_long += 1
            reasons_long.append(
                "ارتفاع الحجم مع الحركة"
            )

        elif score_short > score_long:
            score_short += 1
            reasons_short.append(
                "ارتفاع الحجم مع الهبوط"
            )

    if (
        score_long >= 5
        and score_long > score_short
    ):
        result.update({
            "found": True,
            "direction": "LONG",
            "score": score_long,
            "reason": reasons_long
        })

    elif (
        score_short >= 5
        and score_short > score_long
    ):
        result.update({
            "found": True,
            "direction": "SHORT",
            "score": score_short,
            "reason": reasons_short
        })

    return result


# =========================================================
# DEEP COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    if not symbol:
        return None

    timeframes = (
        ("1d", 100),
        ("4h", 120),
        ("1h", 120),
        ("30m", 100),
        ("15m", 100)
    )

    ks = {}

    for timeframe, limit in timeframes:

        ks[timeframe] = get_klines(
            symbol,
            timeframe,
            limit
        )

    minimums = {
        "1d": 60,
        "4h": 60,
        "1h": 60,
        "30m": 40,
        "15m": 40
    }

    for timeframe, minimum in minimums.items():

        if len(ks[timeframe]) < minimum:
            return None

    k1d = ks["1d"]
    k4h = ks["4h"]
    k1h = ks["1h"]
    k30 = ks["30m"]
    k15 = ks["15m"]

    price = (
        get_current_price(symbol)
        or k1h[-1]["close"]
    )

    t1d = calculate_timeframe_trend(
        k1d
    )

    t4h = calculate_timeframe_trend(
        k4h
    )

    t1h = calculate_timeframe_trend(
        k1h
    )

    t30 = calculate_timeframe_trend(
        k30
    )

    t15 = calculate_timeframe_trend(
        k15
    )

    structure, bos = detect_market_structure(
        k1h
    )

    liquidity, buy_pressure = detect_liquidity_flow(
        k1h
    )

    volume_ratio = calculate_volume_ratio(
        k1h
    )

    volume_trend = calculate_volume_trend(
        k1h
    )

    rsi = (
        calculate_rsi(
            [x["close"] for x in k1h]
        )
        or 50
    )

    ema = ema_state(
        k1h
    )

    bottom = detect_bottom_accumulation(
        k1h
    )

    momentum = detect_momentum(
        k1h
    )

    trend_start = detect_trend_start(
        k1h
    )

    support, resistance = calculate_support_resistance(
        k1h
    )

    atr = calculate_atr(
        k1h
    )

    distance_support = (
        (price - support)
        / price
        * 100
        if support
        else 0
    )

    distance_resistance = (
        (resistance - price)
        / price
        * 100
        if resistance
        else 0
    )

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # HIGHER TIMEFRAME
    # =====================================================

    for trend, weight, label in (
        (t1d, 15, "1D"),
        (t4h, 15, "4H"),
        (t1h, 15, "1H")
    ):

        if trend == "LONG":

            long_score += weight

            long_reasons.append(
                f"{label} يدعم الاتجاه الصاعد"
            )

        elif trend == "SHORT":

            short_score += weight

            short_reasons.append(
                f"{label} يدعم الاتجاه الهابط"
            )

    # =====================================================
    # LOWER TIMEFRAMES
    # =====================================================

    if t30 == "LONG":
        long_score += 8

    elif t30 == "SHORT":
        short_score += 8

    if t15 == "LONG":
        long_score += 6

    elif t15 == "SHORT":
        short_score += 6

    # =====================================================
    # BOS
    # =====================================================

    if bos == "BULLISH":

        long_score += 12

        long_reasons.append(
            "BOS صاعد مؤكد"
        )

    elif bos == "BEARISH":

        short_score += 12

        short_reasons.append(
            "BOS هابط مؤكد"
        )

    # =====================================================
    # STRUCTURE
    # =====================================================

    if structure == "BULLISH":

        long_score += 8

        long_reasons.append(
            "هيكل السوق صاعد"
        )

    elif structure == "BEARISH":

        short_score += 8

        short_reasons.append(
            "هيكل السوق هابط"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

    if liquidity == "INFLOW":

        long_score += 10

        long_reasons.append(
            "السيولة تدخل للسوق"
        )

    elif liquidity == "OUTFLOW":

        short_score += 10

        short_reasons.append(
            "السيولة تخرج من السوق"
        )

    # =====================================================
    # BUY PRESSURE
    # =====================================================

    if buy_pressure >= 57:

        long_score += 6

    elif buy_pressure <= 43:

        short_score += 6

    # =====================================================
    # VOLUME
    # =====================================================

    if volume_ratio >= 1.20:

        if buy_pressure >= 50:

            long_score += 6

            long_reasons.append(
                "الحجم مرتفع مع ضغط شرائي"
            )

        else:

            short_score += 6

            short_reasons.append(
                "الحجم مرتفع مع ضغط بيعي"
            )

    elif volume_ratio >= 0.80:

        if buy_pressure >= 50:
            long_score += 2
        else:
            short_score += 2

    # =====================================================
    # RSI
    # =====================================================

    if 35 <= rsi <= 48:

        long_score += 5

        long_reasons.append(
            "RSI مناسب لمحاولة صعود"
        )

    elif 52 <= rsi <= 65:

        short_score += 5

        short_reasons.append(
            "RSI يميل للضغط الهابط"
        )

    elif rsi < 30:

        long_score += 7

        long_reasons.append(
            "RSI في منطقة تشبع بيعي"
        )

    elif rsi > 70:

        short_score += 7

        short_reasons.append(
            "RSI في منطقة تشبع شرائي"
        )

    # =====================================================
    # EMA
    # =====================================================

    if ema == "BULLISH":

        long_score += 5

        long_reasons.append(
            "EMA9 فوق EMA20"
        )

    elif ema == "BEARISH":

        short_score += 5

        short_reasons.append(
            "EMA9 تحت EMA20"
        )

    # =====================================================
    # BOTTOM
    # =====================================================

    if bottom["found"]:

        long_score += 8

        long_reasons.append(
            "تم اكتشاف احتمال قاع/تجميع"
        )

    # =====================================================
    # MOMENTUM
    # =====================================================

    if momentum["state"] == "BULLISH":

        long_score += 8

        long_reasons.append(
            "Momentum صاعد"
        )

    elif momentum["state"] == "BEARISH":

        short_score += 8

        short_reasons.append(
            "Momentum هابط"
        )

    # =====================================================
    # TREND START
    # =====================================================

    if trend_start["found"]:

        if trend_start["direction"] == "LONG":

            long_score += 7

            long_reasons.append(
                "بداية ترند صاعد محتملة"
            )

        elif trend_start["direction"] == "SHORT":

            short_score += 7

            short_reasons.append(
                "بداية ترند هابط محتملة"
            )

    # =====================================================
    # DIRECTION
    # =====================================================

    if long_score > short_score:

        direction = "LONG"

    elif short_score > long_score:

        direction = "SHORT"

    else:

        direction = "NEUTRAL"

    score = int(
        max(
            0,
            min(
                100,
                max(
                    long_score,
                    short_score
                )
            )
        )
    )

    # =====================================================
    # CONFIRMATION
    # =====================================================

    long_confirmation = (
        t1h == "LONG"
        and (
            t30 == "LONG"
            or t15 == "LONG"
            or bos == "BULLISH"
            or liquidity == "INFLOW"
            or momentum["state"] == "BULLISH"
        )
    )

    short_confirmation = (
        t1h == "SHORT"
        and (
            t30 == "SHORT"
            or t15 == "SHORT"
            or bos == "BEARISH"
            or liquidity == "OUTFLOW"
            or momentum["state"] == "BEARISH"
        )
    )

    # =====================================================
    # TRADE
    # =====================================================

    trade_type = "NO TRADE"

    decision = (
        "انتظار تأكيد إضافي"
    )

    entry = None
    stop_loss = None
    tp1 = None
    tp2 = None
    tp3 = None

    # =====================================================
    # LONG ENTRY
    # =====================================================

    if (
        direction == "LONG"
        and score >= 48
        and long_confirmation
    ):

        trade_type = "ENTRY READY"

        decision = (
            "صفقة LONG جاهزة"
        )

        entry = price

        if atr and atr > 0:

            stop_loss = (
                entry
                - atr * 1.25
            )

        elif support:

            stop_loss = (
                support * 0.995
            )

        else:

            stop_loss = (
                entry * 0.97
            )

        risk = (
            entry - stop_loss
        )

        if risk > 0:

            tp1 = (
                entry
                + risk * 1.2
            )

            tp2 = (
                entry
                + risk * 2
            )

            tp3 = (
                entry
                + risk * 3
            )

    # =====================================================
    # SHORT ENTRY
    # =====================================================

    elif (
        direction == "SHORT"
        and score >= 48
        and short_confirmation
    ):

        trade_type = "ENTRY READY"

        decision = (
            "صفقة SHORT جاهزة"
        )

        entry = price

        if atr and atr > 0:

            stop_loss = (
                entry
                + atr * 1.25
            )

        elif resistance:

            stop_loss = (
                resistance * 1.005
            )

        else:

            stop_loss = (
                entry * 1.03
            )

        risk = (
            stop_loss - entry
        )

        if risk > 0:

            tp1 = (
                entry
                - risk * 1.2
            )

            tp2 = (
                entry
                - risk * 2
            )

            tp3 = (
                entry
                - risk * 3
            )

    # =====================================================
    # REVERSAL WATCH LONG
    # =====================================================

    elif (
        direction == "LONG"
        and bottom["found"]
        and score >= 30
    ):

        trade_type = "REVERSAL WATCH"

        decision = (
            "ننتظر تأكيد التحول الصاعد على 1H/BOS"
        )

    # =====================================================
    # REVERSAL WATCH SHORT
    # =====================================================

    elif (
        direction == "SHORT"
        and score >= 30
        and (
            bos == "BEARISH"
            or liquidity == "OUTFLOW"
            or momentum["state"] == "BEARISH"
        )
    ):

        trade_type = "REVERSAL WATCH"

        decision = (
            "ننتظر تأكيد التحول الهابط على 1H/BOS"
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
    # RETURN
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

        "trend_1d": t1d,
        "trend_4h": t4h,
        "trend_1h": t1h,
        "trend_30m": t30,
        "trend_15m": t15,

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
        "drawdown": bottom["drawdown"],

        "momentum_state": momentum["state"],
        "momentum_score": momentum["score"],
        "momentum_move_2": momentum["move_2"],
        "momentum_move_6": momentum["move_6"],
        "momentum_reasons": momentum["reason"],

        "trend_start_found": trend_start["found"],
        "trend_start_direction": trend_start["direction"],
        "trend_start_score": trend_start["score"],
        "trend_start_reasons": trend_start["reason"],

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

        "move_2": calculate_recent_move(
            k1h,
            2
        ),

        "move_6": calculate_recent_move(
            k1h,
            6
        ),

        "reasons": (
            long_reasons
            if direction == "LONG"
            else short_reasons
        ),

        "long_score": long_score,
        "short_score": short_score,

        "bottom_reasons": bottom["reason"]
    }


# =========================================================
# TREND HUNTER
# =========================================================

def trend_hunter(
    symbols,
    max_coins=120
):

    start = time.time()

    symbols = list(
        dict.fromkeys(
            symbols
        )
    )

    priority_set = set(
        PRIORITY_SYMBOLS
    )

    priority = [
        symbol
        for symbol in symbols
        if symbol in priority_set
    ]

    others = [
        symbol
        for symbol in symbols
        if symbol not in priority_set
    ]

    ordered_symbols = (
        priority
        + others
    )

    # -----------------------------------------------------
    # HARD LIMIT
    # -----------------------------------------------------

    ordered_symbols = ordered_symbols[
        :max_coins
    ]

    candidates = []

    for symbol in ordered_symbols:

        try:

            k = get_klines(
                symbol,
                "1h",
                80
            )

            if len(k) < 50:
                continue

            closes = [
                x["close"]
                for x in k
            ]

            trend = calculate_timeframe_trend(
                k
            )

            volume_ratio = calculate_volume_ratio(
                k
            )

            volume_trend = calculate_volume_trend(
                k
            )

            rsi = (
                calculate_rsi(
                    closes
                )
                or 50
            )

            structure, bos = detect_market_structure(
                k
            )

            liquidity, buy_pressure = detect_liquidity_flow(
                k
            )

            bottom = detect_bottom_accumulation(
                k
            )

            momentum = detect_momentum(
                k
            )

            trend_start = detect_trend_start(
                k
            )

            move_2 = calculate_recent_move(
                k,
                2
            )

            move_6 = calculate_recent_move(
                k,
                6
            )

            # =================================================
            # TREND HUNTER SCORE
            # =================================================

            score = 0

            # Existing trend
            if trend in (
                "LONG",
                "SHORT"
            ):
                score += 10

            # BOS
            if bos != "NONE":
                score += 15

            # Structure
            if structure != "MIXED":
                score += 10

            # Liquidity
            if liquidity != "NEUTRAL":
                score += 15

            # Volume
            if volume_ratio >= 0.80:
                score += 8

            if volume_ratio >= 1.20:
                score += 7

            # Volume trend
            if volume_trend == "RISING":
                score += 7

            # Momentum
            score += min(
                momentum["score"],
                15
            )

            # Trend start
            if trend_start["found"]:
                score += min(
                    trend_start["score"],
                    10
                )

            # Bottom
            if bottom["found"]:
                score += 15

            # Recent movement
            if abs(move_2) >= 0.60:
                score += 4

            if abs(move_6) >= 1.20:
                score += 5

            if abs(move_6) >= 2.50:
                score += 5

            # RSI
            if (
                rsi <= 42
                or rsi >= 58
            ):
                score += 5

            # Buy pressure
            if (
                buy_pressure >= 57
                or buy_pressure <= 43
            ):
                score += 5

            # =================================================
            # DIRECTION
            # =================================================

            if (
                momentum["state"] == "BULLISH"
                or trend_start["direction"] == "LONG"
            ):

                hunter_direction = "LONG"

            elif (
                momentum["state"] == "BEARISH"
                or trend_start["direction"] == "SHORT"
            ):

                hunter_direction = "SHORT"

            elif trend in (
                "LONG",
                "SHORT"
            ):

                hunter_direction = trend

            else:

                hunter_direction = "NEUTRAL"

            candidates.append({
                "symbol": symbol,
                "fast_score": score,
                "direction": hunter_direction,
                "move_2": move_2,
                "move_6": move_6,
                "volume": volume_ratio,
                "volume_trend": volume_trend,
                "momentum": momentum["state"],
                "momentum_score": momentum["score"],
                "trend_start": trend_start["found"],
                "trend_start_score": trend_start["score"],
                "bottom": bottom["found"],
                "bottom_score": bottom["score"],
                "structure": structure,
                "bos": bos,
                "liquidity": liquidity
            })

        except Exception as exc:

            logger.warning(
                "Trend Hunter error %s: %s",
                symbol,
                exc
            )

    candidates.sort(
        key=lambda x: (
            x["fast_score"],
            x["momentum_score"],
            x["trend_start_score"],
            abs(x["move_6"]),
            x["volume"]
        ),
        reverse=True
    )

    logger.info(
        "Trend Hunter finished: %.2fs | scanned=%s | candidates=%s",
        time.time() - start,
        len(ordered_symbols),
        len(candidates)
    )

    return candidates


# =========================================================
# MARKET SCAN
# =========================================================

def scan_market(limit=5):

    start = time.time()

    symbols = get_futures_symbols()

    if not symbols:
        return []

    # =====================================================
    # TREND HUNTER
    # UP TO 120 COINS
    # =====================================================

    candidates = trend_hunter(
        symbols,
        max_coins=120
    )

    if not candidates:
        return []

    # =====================================================
    # TOP 15 DEEP ANALYSIS
    # =====================================================

    deep_candidates = candidates[:15]

    deep_results = []

    for item in deep_candidates:

        symbol = item["symbol"]

        try:

            result = get_coin_analysis(
                symbol
            )

            if result:

                result["hunter_score"] = item[
                    "fast_score"
                ]

                result["hunter_direction"] = item[
                    "direction"
                ]

                result["hunter_momentum"] = item[
                    "momentum"
                ]

                result["hunter_momentum_score"] = item[
                    "momentum_score"
                ]

                result["hunter_trend_start"] = item[
                    "trend_start"
                ]

                result["hunter_trend_start_score"] = item[
                    "trend_start_score"
                ]

                deep_results.append(
                    result
                )

        except Exception as exc:

            logger.warning(
                "Deep analysis error %s: %s",
                symbol,
                exc
            )

    # =====================================================
    # FALLBACK
    # =====================================================

    if not deep_results:

        for item in candidates[:5]:

            try:

                result = get_coin_analysis(
                    item["symbol"]
                )

                if result:
                    deep_results.append(
                        result
                    )

            except Exception:
                pass

    # =====================================================
    # FINAL RANKING
    # =====================================================

    trade_rank = {
        "ENTRY READY": 5,
        "REVERSAL WATCH": 4,
        "ACCUMULATION WATCH": 3,
        "NO TRADE": 1
    }

    def ranking(item):

        return (
            trade_rank.get(
                item.get(
                    "trade_type",
                    "NO TRADE"
                ),
                0
            ),

            item.get(
                "score",
                0
            ),

            item.get(
                "hunter_score",
                0
            ),

            item.get(
                "hunter_momentum_score",
                0
            ),

            int(
                abs(
                    item.get(
                        "move_6",
                        0
                    )
                )
            ),

            item.get(
                "bottom_score",
                0
            )
        )

    deep_results.sort(
        key=ranking,
        reverse=True
    )

    elapsed = (
        time.time()
        - start
    )

    logger.info(
        "Market scan finished: %.2fs | universe=%s | hunter=%s | deep=%s",
        elapsed,
        len(symbols),
        len(candidates),
        len(deep_results)
    )

    return deep_results[
        :max(
            1,
            int(limit)
        )
    ]


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

    try:

        return f"{float(value or 0):.2f}%"

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

    trade = data.get(
        "trade_type",
        "NO TRADE"
    )

    # =====================================================
    # DIRECTION TEXT
    # =====================================================

    if (
        trade == "ENTRY READY"
        and direction == "LONG"
    ):

        direction_text = "🟢 LONG"

    elif (
        trade == "ENTRY READY"
        and direction == "SHORT"
    ):

        direction_text = "🔴 SHORT"

    elif direction == "LONG":

        direction_text = "🟢 LONG WATCH"

    elif direction == "SHORT":

        direction_text = "🔴 SHORT WATCH"

    else:

        direction_text = "🟡 NEUTRAL"

    # =====================================================
    # STATE
    # =====================================================

    state = {
        "ENTRY READY":
            "🟢 ENTRY READY - صفقة جاهزة",

        "REVERSAL WATCH":
            "🟡 REVERSAL WATCH - ننتظر تأكيد الانعكاس",

        "ACCUMULATION WATCH":
            "🔵 ACCUMULATION WATCH - تجميع مبكر"
    }.get(
        trade,
        "🟡 NO TRADE - الشروط غير مكتملة"
    )

    lines = [
        "🤖 BingX AI Scanner",
        "",
        f"💎 العملة: {symbol}",
        f"📈 الاتجاه النهائي: {direction_text}",
        f"⭐ Entry Score: {score}/100",
        "",
        f"🧠 الحالة: {state}",
        f"🧭 القرار: {data.get('decision', 'انتظار')}",
        "",
        "📊 الاتجاه العام",
        f"1D: {data.get('trend_1d', 'NEUTRAL')}",
        f"4H: {data.get('trend_4h', 'NEUTRAL')}",
        "",
        "🔎 تأكيد الدخول",
        f"1H: {data.get('trend_1h', 'NEUTRAL')}",
        f"30m: {data.get('trend_30m', 'NEUTRAL')}",
        f"15m: {data.get('trend_15m', 'NEUTRAL')}",
        f"هيكل السوق: {data.get('structure', 'MIXED')}"
    ]

    # =====================================================
    # BOS
    # =====================================================

    bos = data.get(
        "bos",
        "NONE"
    )

    if bos == "BULLISH":

        lines.append(
            "BOS: 🟢 BULLISH"
        )

    elif bos == "BEARISH":

        lines.append(
            "BOS: 🔴 BEARISH"
        )

    else:

        lines.append(
            "BOS: ⚪ NONE"
        )

    # =====================================================
    # LIQUIDITY
    # =====================================================

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

    lines += [
        f"💧 السيولة: {liquidity_text}",
        f"📊 Volume: {float(data.get('volume_ratio', 0)):.2f}x",
        f"📈 Volume Trend: {data.get('volume_trend', 'NEUTRAL')}",
        f"💪 Buy Pressure: {data.get('buy_pressure', 50)}%",
        f"📊 RSI: {float(data.get('rsi', 50)):.2f}",
        ""
    ]

    # =====================================================
    # MOMENTUM
    # =====================================================

    momentum_state = data.get(
        "momentum_state",
        "NEUTRAL"
    )

    if momentum_state == "BULLISH":

        momentum_text = "🟢 BULLISH"

    elif momentum_state == "BEARISH":

        momentum_text = "🔴 BEARISH"

    else:

        momentum_text = "🟡 NEUTRAL"

    lines += [
        "🚀 Momentum",
        f"الحالة: {momentum_text}",
        f"Momentum Score: {data.get('momentum_score', 0)}",
        f"الحركة القصيرة: {_fmt_percent(data.get('momentum_move_2'))}",
        f"الحركة المتوسطة: {_fmt_percent(data.get('momentum_move_6'))}",
        ""
    ]

    # =====================================================
    # TREND START
    # =====================================================

    if data.get(
        "trend_start_found",
        False
    ):

        trend_start_direction = data.get(
            "trend_start_direction",
            "NEUTRAL"
        )

        lines += [
            "🔥 بداية ترند",
            f"الاتجاه: {trend_start_direction}",
            f"القوة: {data.get('trend_start_score', 0)}",
            ""
        ]

    # =====================================================
    # BOTTOM
    # =====================================================

    lines += [
        "🎯 القاع/التجميع: "
        + (
            "🟢 نعم — تجميع مبكر"
            if data.get(
                "bottom_found"
            )
            else
            "⚪ لا يوجد تأكيد قوي"
        ),
        f"📉 الهبوط السابق: {_fmt_percent(data.get('drawdown'))}",
        ""
    ]

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    lines += [
        "🛡️ الدعم والمقاومة",
        f"🟢 Support: {_fmt_price(data.get('support'))}",
        f"🔴 Resistance: {_fmt_price(data.get('resistance'))}",
        f"📏 البعد عن الدعم: {_fmt_percent(data.get('distance_support'))}",
        f"📏 البعد عن المقاومة: {_fmt_percent(data.get('distance_resistance'))}",
        ""
    ]

    # =====================================================
    # ENTRY
    # =====================================================

    entry = data.get(
        "entry"
    )

    lines += [
        "📍 منطقة الدخول",
        (
            f"Entry: {_fmt_price(entry)}"
            if entry
            else
            "Entry: ⏳ انتظار تأكيد"
        ),
        "",
        f"🛑 Stop Loss: {_fmt_price(data.get('stop_loss'))}",
        "",
        "🎯 الأهداف",
        f"TP1: {_fmt_price(data.get('tp1'))}",
        f"TP2: {_fmt_price(data.get('tp2'))}",
        f"TP3: {_fmt_price(data.get('tp3'))}",
        ""
    ]

    # =====================================================
    # MOVEMENT
    # =====================================================

    lines += [
        "📊 الحركة الأخيرة",
        f"آخر شمعتين تقريباً: {_fmt_percent(data.get('move_2'))}",
        f"آخر 6 شموع تقريباً: {_fmt_percent(data.get('move_6'))}",
        ""
    ]

    # =====================================================
    # HUNTER
    # =====================================================

    if data.get(
        "hunter_score"
    ) is not None:

        lines += [
            "🎯 Trend Hunter",
            f"Hunter Score: {data.get('hunter_score', 0)}",
            f"Hunter Direction: {data.get('hunter_direction', 'NEUTRAL')}",
            ""
        ]

    # =====================================================
    # REASONS
    # =====================================================

    lines += [
        "🔍 أسباب القرار"
    ]

    reasons = data.get(
        "reasons",
        []
    )

    if reasons:

        lines += [
            f"• {reason}"
            for reason in reasons[:10]
        ]

    else:

        lines.append(
            "• لا توجد عوامل قوية كافية حالياً"
        )

    # =====================================================
    # MARKET STRUCTURE EVIDENCE
    # =====================================================

    lines += [
        "",
        "🏗️ أدلة هيكل السوق"
    ]

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
    # LIQUIDITY EVIDENCE
    # =====================================================

    lines += [
        "",
        "💧 أدلة السيولة"
    ]

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
    # MOMENTUM EVIDENCE
    # =====================================================

    momentum_reasons = data.get(
        "momentum_reasons",
        []
    )

    if momentum_reasons:

        lines += [
            "",
            "🚀 أدلة Momentum"
        ]

        lines += [
            f"• {reason}"
            for reason in momentum_reasons[:6]
        ]

    # =====================================================
    # BOTTOM EVIDENCE
    # =====================================================

    if data.get(
        "bottom_found"
    ):

        lines += [
            "",
            "🎯 أدلة التجميع"
        ]

        bottom_reasons = data.get(
            "bottom_reasons",
            []
        )

        if bottom_reasons:

            lines += [
                f"• {reason}"
                for reason in bottom_reasons
            ]

        else:

            lines.append(
                "• توجد مؤشرات تجميع مبكرة"
            )

    # =====================================================
    # NO ENTRY
    # =====================================================

    if trade != "ENTRY READY":

        lines += [
            "",
            "🚫 لماذا لم يدخل؟",
            "• لا يوجد تأكيد دخول كامل حالياً"
        ]

    # =====================================================
    # FOOTER
    # =====================================================

    lines += [
        "",
        "⚠️ إشارة تحليلية وليست ضماناً للربح.",
        "⚠️ 1D + 4H للاتجاه العام.",
        "⚠️ 1H + 30m + 15m لتأكيد الدخول.",
        "⚠️ BOS + السيولة + الحجم + Momentum عوامل تأكيد.",
        "⚠️ ENTRY READY لا تعني ضمان الربح."
    ]

    return "\n".join(lines)
