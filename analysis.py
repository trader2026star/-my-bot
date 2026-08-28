# =========================================================
# analysis.py
# BingX Futures AI Scanner
# Liquidity First + Accumulation + Distribution + Reversal
# Scanner v11.0
# =========================================================

import time
import logging
import threading
import requests
from statistics import mean


# =========================================================
# CONFIG
# =========================================================

BINGX_URL = "https://open-api.bingx.com"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal-BingX-Scanner/11.0",
    "Accept": "application/json",
})

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 12

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60

MIN_REQUEST_INTERVAL = 0.35

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

_KLINE_CACHE = {}

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

_RATE_LIMIT_UNTIL = 0.0


# =========================================================
# HELPERS
# =========================================================

def safe_float(value, default=0.0):

    try:
        return float(value)

    except Exception:
        return default


def clamp(value, low, high):

    return max(
        low,
        min(high, value)
    )


def normalize_symbol(symbol):

    if not symbol:
        return ""

    s = str(symbol).upper().strip()

    replacements = (
        "-PERP",
        "_PERP",
        "/USDT",
        "-USDT",
        "_USDT",
        " USDT",
    )

    for x in replacements:
        s = s.replace(x, "")

    s = (
        s.replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )

    if not s.endswith("USDT"):
        s += "USDT"

    return s


def bingx_symbol(symbol):

    return normalize_symbol(symbol)


# =========================================================
# REQUEST THROTTLE
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


# =========================================================
# HTTP
# =========================================================

def _get_json(path, params=None):

    global _RATE_LIMIT_UNTIL

    if time.time() < _RATE_LIMIT_UNTIL:
        return None

    url = BINGX_URL + path

    for attempt in range(3):

        try:

            _throttle()

            response = SESSION.get(
                url,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:

                _RATE_LIMIT_UNTIL = (
                    time.time() + 5
                )

                time.sleep(1.5)

                continue

            response.raise_for_status()

            data = response.json()

            code = str(
                data.get("code", "")
            )

            if code in (
                "109429",
                "109400",
            ):

                _RATE_LIMIT_UNTIL = (
                    time.time() + 5
                )

                time.sleep(1.5)

                continue

            return data

        except Exception as exc:

            if attempt == 2:

                logger.warning(
                    "BingX request failed: %s",
                    exc,
                )

                return None

            time.sleep(0.6)

    return None


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

    data = _get_json(
        "/openApi/swap/v2/quote/contracts"
    )

    symbols = set()

    try:

        rows = (
            data.get("data", [])
            if data
            else []
        )

        for row in rows:

            if isinstance(row, dict):

                symbol = (
                    row.get("symbol")
                    or row.get("contractId")
                    or row.get("name")
                )

            else:

                symbol = row

            if not symbol:
                continue

            symbol = normalize_symbol(
                symbol
            )

            if symbol.endswith("USDT"):
                symbols.add(symbol)

    except Exception as exc:

        logger.warning(
            "Symbol parsing failed: %s",
            exc,
        )

    if symbols:

        _SYMBOL_CACHE = symbols
        _SYMBOL_CACHE_TIME = now

    return list(_SYMBOL_CACHE)


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval="1h",
    limit=100,
):

    symbol = bingx_symbol(symbol)

    cache_key = (
        symbol,
        interval,
        limit,
    )

    now = time.time()

    cached = _KLINE_CACHE.get(
        cache_key
    )

    if cached:

        timestamp, values = cached

        if (
            now - timestamp
            < KLINE_CACHE_SECONDS
        ):

            return values

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    data = _get_json(
        "/openApi/swap/v3/quote/klines",
        params=params,
    )

    if not data:
        return []

    raw = data.get(
        "data",
        [],
    )

    candles = []

    try:

        for item in raw:

            if isinstance(item, dict):

                candles.append({
                    "open": safe_float(
                        item.get("open")
                    ),
                    "high": safe_float(
                        item.get("high")
                    ),
                    "low": safe_float(
                        item.get("low")
                    ),
                    "close": safe_float(
                        item.get("close")
                    ),
                    "volume": safe_float(
                        item.get("volume")
                        or item.get(
                            "quoteVolume"
                        )
                    ),
                    "time": item.get(
                        "time"
                    ),
                })

            elif (
                isinstance(
                    item,
                    (list, tuple),
                )
                and len(item) >= 6
            ):

                candles.append({
                    "open": safe_float(
                        item[1]
                    ),
                    "high": safe_float(
                        item[2]
                    ),
                    "low": safe_float(
                        item[3]
                    ),
                    "close": safe_float(
                        item[4]
                    ),
                    "volume": safe_float(
                        item[5]
                    ),
                    "time": item[0],
                })

    except Exception as exc:

        logger.warning(
            "Kline parsing failed %s %s: %s",
            symbol,
            interval,
            exc,
        )

    if candles:

        _KLINE_CACHE[
            cache_key
        ] = (
            now,
            candles,
        )

    return candles


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if not values:
        return 0.0

    if len(values) < period:
        return mean(values)

    multiplier = 2 / (
        period + 1
    )

    ema = mean(
        values[:period]
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
            + ema
        )

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(
    closes,
    period=14,
):

    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(closes),
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = mean(
        gains[-period:]
    )

    avg_loss = mean(
        losses[-period:]
    )

    if avg_loss == 0:

        return (
            100.0
            if avg_gain > 0
            else 50.0
        )

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
    period=14,
):

    if len(klines) < period + 1:
        return 0.0

    trs = []

    for i in range(
        1,
        len(klines),
    ):

        current = klines[i]
        previous = klines[i - 1]

        high = current["high"]
        low = current["low"]

        prev_close = (
            previous["close"]
        )

        tr = max(
            high - low,
            abs(
                high - prev_close
            ),
            abs(
                low - prev_close
            ),
        )

        trs.append(tr)

    return mean(
        trs[-period:]
    )


# =========================================================
# VOLUME
# =========================================================

def calculate_volume_ratio(
    klines,
    period=20,
):

    if len(klines) < period + 1:
        return 1.0

    recent = klines[-1][
        "volume"
    ]

    previous = [
        x["volume"]
        for x in klines[
            -period - 1:-1
        ]
        if x["volume"] > 0
    ]

    if not previous:
        return 1.0

    avg_volume = mean(
        previous
    )

    if avg_volume <= 0:
        return 1.0

    return (
        recent
        / avg_volume
    )


def calculate_volume_trend(
    klines,
    lookback=8,
):

    if len(klines) < lookback * 2:
        return "NEUTRAL"

    recent = [
        x["volume"]
        for x in klines[
            -lookback:
        ]
    ]

    previous = [
        x["volume"]
        for x in klines[
            -lookback * 2:
            -lookback
        ]
    ]

    if not recent or not previous:
        return "NEUTRAL"

    r = mean(recent)
    p = mean(previous)

    if p <= 0:
        return "NEUTRAL"

    change = (
        (r - p)
        / p
        * 100
    )

    if change >= 12:
        return "RISING"

    if change <= -12:
        return "FALLING"

    return "NEUTRAL"


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(
    klines,
):

    if not klines:
        return 0.0, 0.0

    lookback = min(
        80,
        len(klines),
    )

    recent = klines[
        -lookback:
    ]

    support = min(
        x["low"]
        for x in recent
    )

    resistance = max(
        x["high"]
        for x in recent
    )

    return (
        support,
        resistance,
    )


# =========================================================
# DRAW DOWN / RALLY
# =========================================================

def recent_drawdown(
    klines,
    lookback=30,
):

    if len(klines) < 5:
        return 0.0

    data = klines[
        -lookback:
    ]

    highest = max(
        x["high"]
        for x in data
    )

    current = data[-1][
        "close"
    ]

    if highest <= 0:
        return 0.0

    return (
        (current - highest)
        / highest
        * 100
    )


def recent_rally(
    klines,
    lookback=30,
):

    if len(klines) < 5:
        return 0.0

    data = klines[
        -lookback:
    ]

    lowest = min(
        x["low"]
        for x in data
    )

    current = data[-1][
        "close"
    ]

    if lowest <= 0:
        return 0.0

    return (
        (current - lowest)
        / lowest
        * 100
    )


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(
    klines,
):

    if len(klines) < 25:

        return {
            "structure": "MIXED",
            "bos": "NONE",
            "bullish": False,
            "bearish": False,
        }

    recent = klines[
        -25:
    ]

    highs = [
        x["high"]
        for x in recent
    ]

    lows = [
        x["low"]
        for x in recent
    ]

    previous_high = max(
        highs[:-5]
    )

    previous_low = min(
        lows[:-5]
    )

    current_close = (
        recent[-1]["close"]
    )

    bullish = (
        current_close
        > previous_high
    )

    bearish = (
        current_close
        < previous_low
    )

    if bullish:

        structure = "BULLISH"
        bos = "BULLISH"

    elif bearish:

        structure = "BEARISH"
        bos = "BEARISH"

    else:

        structure = "MIXED"
        bos = "NONE"

    return {
        "structure": structure,
        "bos": bos,
        "bullish": bullish,
        "bearish": bearish,
    }


# =========================================================
# LIQUIDITY FLOW
#
# ملاحظة:
# هذا تقدير من بيانات الشموع والحجم وليس Order Book حقيقي.
# لذلك لا نعتبره وحده كافيًا لدخول الصفقة.
# =========================================================

def detect_liquidity_flow(
    klines,
):

    if len(klines) < 20:

        return {
            "state": "NEUTRAL",
            "bullish_volume": 0.0,
            "bearish_volume": 0.0,
            "ratio": 1.0,
            "confidence": 0,
        }

    recent = klines[
        -20:
    ]

    bullish_volume = 0.0
    bearish_volume = 0.0

    for candle in recent:

        o = candle["open"]
        c = candle["close"]
        v = candle["volume"]

        if v <= 0:
            continue

        candle_range = max(
            candle["high"]
            - candle["low"],
            1e-12,
        )

        body = abs(c - o)

        # -------------------------------------------------
        # وزن جسم الشمعة
        # -------------------------------------------------

        body_factor = clamp(
            body / candle_range,
            0.15,
            1.0,
        )

        if c > o:

            bullish_volume += (
                v * (
                    0.60
                    + 0.40
                    * body_factor
                )
            )

        elif c < o:

            bearish_volume += (
                v * (
                    0.60
                    + 0.40
                    * body_factor
                )
            )

        else:

            bullish_volume += (
                v * 0.5
            )

            bearish_volume += (
                v * 0.5
            )

    if bearish_volume <= 0:

        ratio = 99.0

    else:

        ratio = (
            bullish_volume
            / bearish_volume
        )

    total = (
        bullish_volume
        + bearish_volume
    )

    if total > 0:

        imbalance = (
            abs(
                bullish_volume
                - bearish_volume
            )
            / total
        )

        confidence = int(
            clamp(
                imbalance * 100,
                0,
                100,
            )
        )

    else:

        confidence = 0

    # -----------------------------------------------------
    # يحتاج فرقًا واضحًا
    # -----------------------------------------------------

    if (
        bullish_volume
        >= bearish_volume * 1.20
        and ratio >= 1.05
    ):

        state = "INFLOW"

    elif (
        bearish_volume
        >= bullish_volume * 1.20
        and ratio <= 0.95
    ):

        state = "OUTFLOW"

    else:

        state = "NEUTRAL"

    return {
        "state": state,
        "bullish_volume": bullish_volume,
        "bearish_volume": bearish_volume,
        "ratio": ratio,
        "confidence": confidence,
    }


# =========================================================
# ACCUMULATION
# =========================================================

def detect_bottom_accumulation(
    klines,
):

    result = {
        "state": "NONE",
        "score": 0,
        "drawdown": 0.0,
        "range": 0.0,
        "reasons": [],
    }

    if len(klines) < 30:
        return result

    recent = klines[
        -30:
    ]

    highs = [
        x["high"]
        for x in recent
    ]

    lows = [
        x["low"]
        for x in recent
    ]

    highest = max(highs)
    lowest = min(lows)

    current = recent[-1][
        "close"
    ]

    if highest <= 0:
        return result

    drawdown = (
        (current - highest)
        / highest
        * 100
    )

    if lowest > 0:

        recent_range = (
            (highest - lowest)
            / lowest
            * 100
        )

    else:

        recent_range = 999

    result["drawdown"] = drawdown
    result["range"] = recent_range

    flow = detect_liquidity_flow(
        klines
    )

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    volume_trend = (
        calculate_volume_trend(
            klines
        )
    )

    # -----------------------------------------------------
    # هبوط سابق
    # -----------------------------------------------------

    if drawdown <= -5:

        result["score"] += 1

        result["reasons"].append(
            "هبوط سابق"
        )

    if drawdown <= -10:

        result["score"] += 1

        result["reasons"].append(
            "هبوط قوي سابق"
        )

    # -----------------------------------------------------
    # نطاق تجميع
    # -----------------------------------------------------

    if recent_range <= 18:

        result["score"] += 1

        result["reasons"].append(
            "تجميع داخل نطاق"
        )

    # -----------------------------------------------------
    # دخول السيولة
    # -----------------------------------------------------

    if flow["state"] == "INFLOW":

        result["score"] += 2

        result["reasons"].append(
            "دخول سيولة"
        )

    # -----------------------------------------------------
    # الحجم
    # -----------------------------------------------------

    if volume_ratio >= 1.03:

        result["score"] += 1

        result["reasons"].append(
            "الحجم أعلى من المتوسط"
        )

    if volume_trend == "RISING":

        result["score"] += 1

        result["reasons"].append(
            "الحجم يتزايد"
        )

    # -----------------------------------------------------
    # ثبات القاع
    # -----------------------------------------------------

    last_lows = [
        x["low"]
        for x in recent[-8:]
    ]

    if len(last_lows) >= 6:

        old_low = min(
            last_lows[:3]
        )

        new_low = min(
            last_lows[3:]
        )

        if new_low >= (
            old_low * 0.997
        ):

            result["score"] += 1

            result["reasons"].append(
                "القاع ثابت"
            )

    # -----------------------------------------------------
    # النتيجة
    # -----------------------------------------------------

    if result["score"] >= 5:

        result["state"] = (
            "STRONG_ACCUMULATION"
        )

    elif result["score"] >= 3:

        result["state"] = (
            "ACCUMULATION"
        )

    elif result["score"] >= 2:

        result["state"] = (
            "POSSIBLE_ACCUMULATION"
        )

    return result


# =========================================================
# DISTRIBUTION
# =========================================================

def detect_distribution(
    klines,
):

    result = {
        "state": "NONE",
        "score": 0,
        "rally": 0.0,
        "range": 0.0,
        "reasons": [],
    }

    if len(klines) < 30:
        return result

    recent = klines[
        -30:
    ]

    highs = [
        x["high"]
        for x in recent
    ]

    lows = [
        x["low"]
        for x in recent
    ]

    highest = max(highs)
    lowest = min(lows)

    current = recent[-1][
        "close"
    ]

    if lowest <= 0:
        return result

    rally = (
        (current - lowest)
        / lowest
        * 100
    )

    recent_range = (
        (highest - lowest)
        / lowest
        * 100
    )

    result["rally"] = rally
    result["range"] = recent_range

    flow = detect_liquidity_flow(
        klines
    )

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    volume_trend = (
        calculate_volume_trend(
            klines
        )
    )

    # -----------------------------------------------------
    # صعود سابق
    # -----------------------------------------------------

    if rally >= 8:

        result["score"] += 1

        result["reasons"].append(
            "صعود سابق قوي"
        )

    if rally >= 15:

        result["score"] += 1

        result["reasons"].append(
            "صعود ممتد"
        )

    # -----------------------------------------------------
    # قرب القمة
    # -----------------------------------------------------

    distance_from_high = (
        (highest - current)
        / highest
        * 100
    )

    if distance_from_high <= 5:

        result["score"] += 1

        result["reasons"].append(
            "قريب من القمة"
        )

    # -----------------------------------------------------
    # خروج السيولة
    # -----------------------------------------------------

    if flow["state"] == "OUTFLOW":

        result["score"] += 2

        result["reasons"].append(
            "خروج سيولة"
        )

    # -----------------------------------------------------
    # الحجم
    # -----------------------------------------------------

    if volume_ratio >= 1.03:

        result["score"] += 1

        result["reasons"].append(
            "الحجم مرتفع"
        )

    if volume_trend == "RISING":

        result["score"] += 1

        result["reasons"].append(
            "الحجم يتزايد"
        )

    # -----------------------------------------------------
    # النتيجة
    # -----------------------------------------------------

    if result["score"] >= 5:

        result["state"] = (
            "STRONG_DISTRIBUTION"
        )

    elif result["score"] >= 3:

        result["state"] = (
            "DISTRIBUTION"
        )

    elif result["score"] >= 2:

        result["state"] = (
            "POSSIBLE_DISTRIBUTION"
        )

    return result


# =========================================================
# TREND
# =========================================================

def calculate_timeframe_trend(
    klines,
):

    if len(klines) < 55:
        return "NEUTRAL"

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(
        closes,
        9,
    )

    ema20 = calculate_ema(
        closes,
        20,
    )

    ema50 = calculate_ema(
        closes,
        50,
    )

    price = closes[-1]

    bullish = (
        price > ema9
        and ema9 > ema20
        and ema20 > ema50
    )

    bearish = (
        price < ema9
        and ema9 < ema20
        and ema20 < ema50
    )

    if bullish:
        return "LONG"

    if bearish:
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# LIQUIDITY BIAS
#
# السيولة لها الأولوية.
# =========================================================

def calculate_liquidity_bias(
    flow_state,
    accumulation_state,
    distribution_state,
):

    accumulation_states = (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    )

    distribution_states = (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    )

    bullish = (
        flow_state == "INFLOW"
        and accumulation_state
        in accumulation_states
    )

    bearish = (
        flow_state == "OUTFLOW"
        and distribution_state
        in distribution_states
    )

    if bullish:
        return "LONG"

    if bearish:
        return "SHORT"

    if flow_state == "INFLOW":
        return "LONG WATCH"

    if flow_state == "OUTFLOW":
        return "SHORT WATCH"

    return "NEUTRAL"


# =========================================================
# REVERSAL
# =========================================================

def detect_reversal(
    klines,
):

    result = {
        "state": "NONE",
        "bull_score": 0,
        "bear_score": 0,
        "reasons": [],
    }

    if len(klines) < 30:
        return result

    structure = (
        detect_market_structure(
            klines
        )
    )

    flow = (
        detect_liquidity_flow(
            klines
        )
    )

    accumulation = (
        detect_bottom_accumulation(
            klines
        )
    )

    distribution = (
        detect_distribution(
            klines
        )
    )

    closes = [
        x["close"]
        for x in klines
    ]

    rsi = calculate_rsi(
        closes
    )

    drawdown = recent_drawdown(
        klines
    )

    rally = recent_rally(
        klines
    )

    # =====================================================
    # BULL
    # =====================================================

    if accumulation["state"] in (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    ):

        result["bull_score"] += 3

    if flow["state"] == "INFLOW":

        result["bull_score"] += 3

    if structure["bullish"]:

        result["bull_score"] += 2

    if rsi <= 45:

        result["bull_score"] += 1

    if drawdown <= -8:

        result["bull_score"] += 1

    # =====================================================
    # BEAR
    # =====================================================

    if distribution["state"] in (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    ):

        result["bear_score"] += 3

    if flow["state"] == "OUTFLOW":

        result["bear_score"] += 3

    if structure["bearish"]:

        result["bear_score"] += 2

    if rsi >= 55:

        result["bear_score"] += 1

    if rally >= 10:

        result["bear_score"] += 1

    # =====================================================
    # HARD LIQUIDITY PROTECTION
    # =====================================================

    if (
        flow["state"] == "INFLOW"
        and accumulation["state"]
        in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        )
    ):

        result["bear_score"] = min(
            result["bear_score"],
            2,
        )

    if (
        flow["state"] == "OUTFLOW"
        and distribution["state"]
        in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        )
    ):

        result["bull_score"] = min(
            result["bull_score"],
            2,
        )

    # =====================================================
    # FINAL
    # =====================================================

    if (
        result["bull_score"] >= 5
        and result["bull_score"]
        >= result["bear_score"] + 2
    ):

        result["state"] = (
            "BULLISH_REVERSAL"
        )

        result["reasons"].append(
            "سيطرة عوامل الانعكاس الصاعد"
        )

    elif (
        result["bear_score"] >= 5
        and result["bear_score"]
        >= result["bull_score"] + 2
    ):

        result["state"] = (
            "BEARISH_REVERSAL"
        )

        result["reasons"].append(
            "سيطرة عوامل الانعكاس الهابط"
        )

    return result


# =========================================================
# CONFIRMATION
# =========================================================

def confirmation_bias(
    tf_15m,
    tf_30m,
):

    score_long = 0
    score_short = 0

    if tf_15m == "LONG":
        score_long += 1

    elif tf_15m == "SHORT":
        score_short += 1

    if tf_30m == "LONG":
        score_long += 1

    elif tf_30m == "SHORT":
        score_short += 1

    if score_long >= 2:
        return "LONG"

    if score_short >= 2:
        return "SHORT"

    if score_long > score_short:
        return "LONG WATCH"

    if score_short > score_long:
        return "SHORT WATCH"

    return "NEUTRAL"


# =========================================================
# EXTENDED SETUP CLASSIFICATION
# =========================================================

def classify_setup(
    trend_1d,
    trend_4h,
    trend_1h,
    flow,
    accumulation,
    distribution,
    reversal,
    structure,
    late_pump,
    late_dump,
    confirmation="NEUTRAL",
):

    accumulation_states = (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    )

    distribution_states = (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    )

    # =====================================================
    # HARD LIQUIDITY DIRECTION
    # =====================================================

    bullish_liquidity = (
        flow == "INFLOW"
        and accumulation
        in accumulation_states
    )

    bearish_liquidity = (
        flow == "OUTFLOW"
        and distribution
        in distribution_states
    )

    # =====================================================
    # LONG LIQUIDITY SETUP
    # =====================================================

    if bullish_liquidity:

        # ممنوع تحويله إلى SHORT
        if late_pump:

            return (
                "LONG WATCH",
                "ACCUMULATION WATCH",
            )

        if (
            reversal == "BULLISH_REVERSAL"
            and confirmation == "LONG"
        ):

            return (
                "LONG",
                "ENTRY READY",
            )

        if (
            structure == "BULLISH"
            and confirmation
            in (
                "LONG",
                "LONG WATCH",
            )
        ):

            return (
                "LONG",
                "ENTRY READY",
            )

        return (
            "LONG WATCH",
            "ACCUMULATION WATCH",
        )

    # =====================================================
    # SHORT LIQUIDITY SETUP
    # =====================================================

    if bearish_liquidity:

        # ممنوع تحويله إلى LONG
        if late_dump:

            return (
                "SHORT WATCH",
                "REVERSAL WATCH",
            )

        if (
            reversal == "BEARISH_REVERSAL"
            and confirmation == "SHORT"
        ):

            return (
                "SHORT",
                "ENTRY READY",
            )

        if (
            structure == "BEARISH"
            and confirmation
            in (
                "SHORT",
                "SHORT WATCH",
            )
        ):

            return (
                "SHORT",
                "ENTRY READY",
            )

        return (
            "SHORT WATCH",
            "REVERSAL WATCH",
        )

    # =====================================================
    # REVERSAL WITHOUT FULL ACCUMULATION/DISTRIBUTION
    # =====================================================

    if reversal == "BULLISH_REVERSAL":

        if confirmation == "LONG":

            return (
                "LONG",
                "ENTRY READY",
            )

        return (
            "LONG WATCH",
            "REVERSAL WATCH",
        )

    if reversal == "BEARISH_REVERSAL":

        if confirmation == "SHORT":

            return (
                "SHORT",
                "ENTRY READY",
            )

        return (
            "SHORT WATCH",
            "REVERSAL WATCH",
        )

    # =====================================================
    # TREND CONTINUATION
    # =====================================================

    bullish_alignment = (
        trend_1d == "LONG"
        and trend_4h == "LONG"
        and trend_1h == "LONG"
        and flow == "INFLOW"
    )

    bearish_alignment = (
        trend_1d == "SHORT"
        and trend_4h == "SHORT"
        and trend_1h == "SHORT"
        and flow == "OUTFLOW"
    )

    if bullish_alignment and not late_pump:

        if confirmation == "LONG":

            return (
                "LONG",
                "ENTRY READY",
            )

        return (
            "LONG WATCH",
            "REVERSAL WATCH",
        )

    if bearish_alignment and not late_dump:

        if confirmation == "SHORT":

            return (
                "SHORT",
                "ENTRY READY",
            )

        return (
            "SHORT WATCH",
            "REVERSAL WATCH",
        )

    # =====================================================
    # LATE MOVEMENT
    # =====================================================

    if late_pump:

        return (
            "WAIT",
            "LATE PUMP - WAIT",
        )

    if late_dump:

        return (
            "WAIT",
            "LATE DUMP - WAIT",
        )

    return (
        "WAIT",
        "NO TRADE",
    )


# =========================================================
# SCORE
# =========================================================

def calculate_entry_score(
    trend_1d,
    trend_4h,
    trend_1h,
    flow,
    accumulation,
    distribution,
    reversal,
    late_pump,
    late_dump,
):

    long_score = 0
    short_score = 0

    accumulation_states = (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    )

    distribution_states = (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    )

    # =====================================================
    # LONG
    # =====================================================

    if flow == "INFLOW":
        long_score += 25

    if accumulation in accumulation_states:
        long_score += 25

    if reversal == "BULLISH_REVERSAL":
        long_score += 20

    if trend_1d == "LONG":
        long_score += 8

    if trend_4h == "LONG":
        long_score += 10

    if trend_1h == "LONG":
        long_score += 10

    if late_dump:
        long_score += 2

    # =====================================================
    # SHORT
    # =====================================================

    if flow == "OUTFLOW":
        short_score += 25

    if distribution in distribution_states:
        short_score += 25

    if reversal == "BEARISH_REVERSAL":
        short_score += 20

    if trend_1d == "SHORT":
        short_score += 8

    if trend_4h == "SHORT":
        short_score += 10

    if trend_1h == "SHORT":
        short_score += 10

    if late_pump:
        short_score += 2

    # =====================================================
    # HARD LIQUIDITY PROTECTION
    # =====================================================

    if (
        flow == "INFLOW"
        and accumulation
        in accumulation_states
    ):

        # لا يمكن أن يفوز SHORT بسبب EMA
        short_score = min(
            short_score,
            20,
        )

        long_score = max(
            long_score,
            55,
        )

    if (
        flow == "OUTFLOW"
        and distribution
        in distribution_states
    ):

        # لا يمكن أن يفوز LONG بسبب EMA
        long_score = min(
            long_score,
            20,
        )

        short_score = max(
            short_score,
            55,
        )

    # =====================================================
    # REVERSAL PROTECTION
    # =====================================================

    if reversal == "BULLISH_REVERSAL":

        short_score = min(
            short_score,
            25,
        )

    if reversal == "BEARISH_REVERSAL":

        long_score = min(
            long_score,
            25,
        )

    return (
        int(
            clamp(
                long_score,
                0,
                100,
            )
        ),

        int(
            clamp(
                short_score,
                0,
                100,
            )
        ),
    )


# =========================================================
# LATE PUMP
# =========================================================

def detect_late_pump(
    klines,
):

    if len(klines) < 30:
        return False

    rally = recent_rally(
        klines,
        25,
    )

    rsi = calculate_rsi([
        x["close"]
        for x in klines
    ])

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    if (
        rally >= 18
        and rsi >= 68
    ):
        return True

    if (
        rally >= 25
        and volume_ratio >= 1.5
    ):
        return True

    return False


# =========================================================
# LATE DUMP
# =========================================================

def detect_late_dump(
    klines,
):

    if len(klines) < 30:
        return False

    drawdown = recent_drawdown(
        klines,
        25,
    )

    rsi = calculate_rsi([
        x["close"]
        for x in klines
    ])

    if (
        drawdown <= -18
        and rsi <= 28
    ):
        return True

    return False


# =========================================================
# SINGLE COIN
# =========================================================

def get_coin_analysis(
    symbol,
):

    symbol = normalize_symbol(
        symbol
    )

    try:

        # =================================================
        # DATA
        # =================================================

        tf_15m = get_klines(
            symbol,
            "15m",
            100,
        )

        tf_30m = get_klines(
            symbol,
            "30m",
            100,
        )

        tf_1h = get_klines(
            symbol,
            "1h",
            120,
        )

        tf_4h = get_klines(
            symbol,
            "4h",
            120,
        )

        tf_1d = get_klines(
            symbol,
            "1d",
            100,
        )

        if not all([
            tf_15m,
            tf_30m,
            tf_1h,
            tf_4h,
            tf_1d,
        ]):

            return {
                "symbol": symbol,
                "direction": "WAIT",
                "state": "NO DATA",
                "score": 0,
                "analysis_ok": False,
            }

        # =================================================
        # TRENDS
        # =================================================

        trend_1d = (
            calculate_timeframe_trend(
                tf_1d
            )
        )

        trend_4h = (
            calculate_timeframe_trend(
                tf_4h
            )
        )

        trend_1h = (
            calculate_timeframe_trend(
                tf_1h
            )
        )

        trend_30m = (
            calculate_timeframe_trend(
                tf_30m
            )
        )

        trend_15m = (
            calculate_timeframe_trend(
                tf_15m
            )
        )

        # =================================================
        # 1H CORE ANALYSIS
        # =================================================

        flow_data = (
            detect_liquidity_flow(
                tf_1h
            )
        )

        accumulation = (
            detect_bottom_accumulation(
                tf_1h
            )
        )

        distribution = (
            detect_distribution(
                tf_1h
            )
        )

        structure = (
            detect_market_structure(
                tf_1h
            )
        )

        reversal = (
            detect_reversal(
                tf_1h
            )
        )

        # =================================================
        # CONFIRMATION
        # =================================================

        confirmation = (
            confirmation_bias(
                trend_15m,
                trend_30m,
            )
        )

        liquidity_bias = (
            calculate_liquidity_bias(
                flow_data["state"],
                accumulation["state"],
                distribution["state"],
            )
        )

        late_pump = (
            detect_late_pump(
                tf_1h
            )
        )

        late_dump = (
            detect_late_dump(
                tf_1h
            )
        )

        # =================================================
        # PRICE / LEVELS
        # =================================================

        price = tf_1h[-1][
            "close"
        ]

        support, resistance = (
            calculate_support_resistance(
                tf_1h
            )
        )

        atr = calculate_atr(
            tf_1h
        )

        if atr <= 0:
            atr = price * 0.01

        rsi_1h = calculate_rsi([
            x["close"]
            for x in tf_1h
        ])

        rsi_15m = calculate_rsi([
            x["close"]
            for x in tf_15m
        ])

        volume_ratio = (
            calculate_volume_ratio(
                tf_1h
            )
        )

        volume_trend = (
            calculate_volume_trend(
                tf_1h
            )
        )

        # =================================================
        # SCORE
        # =================================================

        long_score, short_score = (
            calculate_entry_score(
                trend_1d,
                trend_4h,
                trend_1h,
                flow_data["state"],
                accumulation["state"],
                distribution["state"],
                reversal["state"],
                late_pump,
                late_dump,
            )
        )

        # =================================================
        # CLASSIFICATION
        # =================================================

        direction, state = (
            classify_setup(
                trend_1d,
                trend_4h,
                trend_1h,
                flow_data["state"],
                accumulation["state"],
                distribution["state"],
                reversal["state"],
                structure["structure"],
                late_pump,
                late_dump,
                confirmation,
            )
        )

        # =================================================
        # HARD FINAL LIQUIDITY PROTECTION
        #
        # أهم جزء في النسخة.
        # =================================================

        bullish_liquidity_setup = (
            flow_data["state"]
            == "INFLOW"
            and accumulation["state"]
            in (
                "ACCUMULATION",
                "STRONG_ACCUMULATION",
            )
        )

        bearish_liquidity_setup = (
            flow_data["state"]
            == "OUTFLOW"
            and distribution["state"]
            in (
                "DISTRIBUTION",
                "STRONG_DISTRIBUTION",
            )
        )

        # -------------------------------------------------
        # INFLOW + ACCUMULATION
        # -------------------------------------------------

        if bullish_liquidity_setup:

            if direction in (
                "SHORT",
                "SHORT WATCH",
            ):

                direction = "LONG WATCH"

                state = (
                    "ACCUMULATION WATCH"
                )

            # لا نسمح بإشارة SHORT
            short_score = min(
                short_score,
                20,
            )

            long_score = max(
                long_score,
                55,
            )

        # -------------------------------------------------
        # OUTFLOW + DISTRIBUTION
        # -------------------------------------------------

        if bearish_liquidity_setup:

            if direction in (
                "LONG",
                "LONG WATCH",
            ):

                direction = "SHORT WATCH"

                state = (
                    "REVERSAL WATCH"
                )

            long_score = min(
                long_score,
                20,
            )

            short_score = max(
                short_score,
                55,
            )

        # =================================================
        # NO LIQUIDITY = NO AGGRESSIVE ENTRY
        # =================================================

        if (
            flow_data["state"]
            == "NEUTRAL"
        ):

            if direction == "LONG":

                direction = "LONG WATCH"

                state = (
                    "REVERSAL WATCH"
                )

            elif direction == "SHORT":

                direction = "SHORT WATCH"

                state = (
                    "REVERSAL WATCH"
                )

        # =================================================
        # LEVELS
        # =================================================

        entry = price

        if direction in (
            "LONG",
            "LONG WATCH",
        ):

            if support > 0:

                structural_sl = (
                    support * 0.985
                )

            else:

                structural_sl = (
                    price
                    - atr * 1.5
                )

            volatility_sl = (
                price
                - atr * 1.2
            )

            sl = min(
                structural_sl,
                volatility_sl,
            )

            risk = max(
                price - sl,
                atr,
            )

            tp1 = (
                price
                + risk * 1.2
            )

            tp2 = (
                price
                + risk * 2.0
            )

            tp3 = (
                price
                + risk * 3.0
            )

        elif direction in (
            "SHORT",
            "SHORT WATCH",
        ):

            if resistance > 0:

                structural_sl = (
                    resistance * 1.015
                )

            else:

                structural_sl = (
                    price
                    + atr * 1.5
                )

            volatility_sl = (
                price
                + atr * 1.2
            )

            sl = max(
                structural_sl,
                volatility_sl,
            )

            risk = max(
                sl - price,
                atr,
            )

            tp1 = (
                price
                - risk * 1.2
            )

            tp2 = (
                price
                - risk * 2.0
            )

            tp3 = (
                price
                - risk * 3.0
            )

        else:

            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0
            tp3 = 0.0

        # =================================================
        # FINAL SCORE
        # =================================================

        score = max(
            long_score,
            short_score,
        )

        # =================================================
        # REASONS
        # =================================================

        reasons = []

        if flow_data["state"] == "INFLOW":

            reasons.append(
                "🟢 دخول سيولة"
            )

        elif flow_data["state"] == "OUTFLOW":

            reasons.append(
                "🔴 خروج سيولة"
            )

        else:

            reasons.append(
                "🟡 السيولة محايدة"
            )

        if accumulation["state"] in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        ):

            reasons.append(
                "🔵 تجميع"
            )

        if distribution["state"] in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        ):

            reasons.append(
                "🔴 توزيع"
            )

        if reversal["state"] == (
            "BULLISH_REVERSAL"
        ):

            reasons.append(
                "🟢 انعكاس صاعد"
            )

        elif reversal["state"] == (
            "BEARISH_REVERSAL"
        ):

            reasons.append(
                "🔴 انعكاس هابط"
            )

        if structure["bos"] == "BULLISH":

            reasons.append(
                "📈 BOS صاعد"
            )

        elif structure["bos"] == "BEARISH":

            reasons.append(
                "📉 BOS هابط"
            )

        if confirmation == "LONG":

            reasons.append(
                "✅ تأكيد 15m + 30m صاعد"
            )

        elif confirmation == "SHORT":

            reasons.append(
                "✅ تأكيد 15m + 30m هابط"
            )

        elif confirmation == "LONG WATCH":

            reasons.append(
                "🟡 تأكيد قصير الأجل يميل للصعود"
            )

        elif confirmation == "SHORT WATCH":

            reasons.append(
                "🟡 تأكيد قصير الأجل يميل للهبوط"
            )

        # =================================================
        # WARNING
        # =================================================

        warning = ""

        if bullish_liquidity_setup:

            warning = (
                "🛡️ حماية السيولة: "
                "دخول سيولة + تجميع — "
                "ممنوع مطاردة SHORT لمجرد أن السعر هبط."
            )

        elif bearish_liquidity_setup:

            warning = (
                "🛡️ حماية السيولة: "
                "خروج سيولة + توزيع — "
                "ممنوع مطاردة LONG لمجرد أن السعر صعد."
            )

        elif late_pump:

            warning = (
                "⚠️ حركة صاعدة متأخرة — "
                "لا تطارد السعر."
            )

        elif late_dump:

            warning = (
                "⚠️ حركة هابطة متأخرة — "
                "لا تطارد SHORT."
            )

        # =================================================
        # RETURN
        # =================================================

        return {

            "symbol": symbol,

            "direction": direction,

            "state": state,

            "score": int(
                clamp(
                    score,
                    0,
                    100,
                )
            ),

            "long_score": int(
                clamp(
                    long_score,
                    0,
                    100,
                )
            ),

            "short_score": int(
                clamp(
                    short_score,
                    0,
                    100,
                )
            ),

            "price": price,

            "entry": entry,

            "sl": sl,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "trend_1d": trend_1d,

            "trend_4h": trend_4h,

            "trend_1h": trend_1h,

            "trend_30m": trend_30m,

            "trend_15m": trend_15m,

            "confirmation": confirmation,

            "liquidity_bias": liquidity_bias,

            "rsi_1h": rsi_1h,

            "rsi_15m": rsi_15m,

            "volume_ratio": volume_ratio,

            "volume_trend": volume_trend,

            "liquidity":
                flow_data["state"],

            "liquidity_confidence":
                flow_data["confidence"],

            "liquidity_ratio":
                flow_data["ratio"],

            "accumulation":
                accumulation["state"],

            "accumulation_score":
                accumulation["score"],

            "distribution":
                distribution["state"],

            "distribution_score":
                distribution["score"],

            "market_structure":
                structure["structure"],

            "bos":
                structure["bos"],

            "reversal":
                reversal["state"],

            "bull_reversal_score":
                reversal["bull_score"],

            "bear_reversal_score":
                reversal["bear_score"],

            "drawdown":
                recent_drawdown(
                    tf_1h
                ),

            "rally":
                recent_rally(
                    tf_1h
                ),

            "support":
                support,

            "resistance":
                resistance,

            "late_pump":
                late_pump,

            "late_dump":
                late_dump,

            "reasons":
                reasons,

            "warning":
                warning,

            "analysis_ok":
                True,
        }

    except Exception as exc:

        logger.exception(
            "Analysis failed for %s",
            symbol,
        )

        return {
            "symbol": symbol,
            "direction": "WAIT",
            "state": "ERROR",
            "score": 0,
            "reason": str(exc),
            "analysis_ok": False,
        }


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market(
    limit=5,
):

    symbols = get_futures_symbols()

    if not symbols:
        return []

    candidates = []

    # =====================================================
    # FAST FILTER
    #
    # لا نستخدم أكبر هبوط/صعود كاتجاه.
    # نستخدمه فقط كعامل مساعد.
    # =====================================================

    for symbol in symbols:

        try:

            klines = get_klines(
                symbol,
                "1h",
                45,
            )

            if len(klines) < 30:
                continue

            current = klines[-1][
                "close"
            ]

            if current <= 0:
                continue

            flow = (
                detect_liquidity_flow(
                    klines
                )
            )

            accumulation = (
                detect_bottom_accumulation(
                    klines
                )
            )

            distribution = (
                detect_distribution(
                    klines
                )
            )

            drawdown = (
                recent_drawdown(
                    klines,
                    30,
                )
            )

            rally = (
                recent_rally(
                    klines,
                    30,
                )
            )

            volume_ratio = (
                calculate_volume_ratio(
                    klines
                )
            )

            priority = 0

            # =================================================
            # LIQUIDITY
            # =================================================

            if flow["state"] in (
                "INFLOW",
                "OUTFLOW",
            ):

                priority += 40

            # =================================================
            # ACCUMULATION
            # =================================================

            if accumulation["state"] == (
                "STRONG_ACCUMULATION"
            ):

                priority += 45

            elif accumulation["state"] == (
                "ACCUMULATION"
            ):

                priority += 35

            elif accumulation["state"] == (
                "POSSIBLE_ACCUMULATION"
            ):

                priority += 15

            # =================================================
            # DISTRIBUTION
            # =================================================

            if distribution["state"] == (
                "STRONG_DISTRIBUTION"
            ):

                priority += 45

            elif distribution["state"] == (
                "DISTRIBUTION"
            ):

                priority += 35

            elif distribution["state"] == (
                "POSSIBLE_DISTRIBUTION"
            ):

                priority += 15

            # =================================================
            # VOLUME
            # =================================================

            if volume_ratio >= 1.10:

                priority += 10

            # =================================================
            # PRICE MOVEMENT
            #
            # وزن ضعيف جدًا.
            # =================================================

            if drawdown <= -10:

                priority += 3

            if rally >= 10:

                priority += 3

            candidates.append({
                "symbol": symbol,
                "priority": priority,
            })

        except Exception as exc:

            logger.debug(
                "Fast filter failed %s: %s",
                symbol,
                exc,
            )

            continue

    if not candidates:
        return []

    candidates.sort(
        key=lambda x: x[
            "priority"
        ],
        reverse=True,
    )

    # =====================================================
    # DEEP SCAN
    # =====================================================

    deep_limit = min(
        max(
            limit * 5,
            25,
        ),
        len(candidates),
    )

    results = []

    for candidate in candidates[
        :deep_limit
    ]:

        result = get_coin_analysis(
            candidate["symbol"]
        )

        if not result.get(
            "analysis_ok"
        ):
            continue

        result[
            "scan_priority"
        ] = candidate[
            "priority"
        ]

        results.append(
            result
        )

    if not results:
        return []

    # =====================================================
    # RANK
    #
    # الأولوية:
    # 1. Liquidity + Accumulation/Distribution
    # 2. ENTRY READY
    # 3. WATCH
    # 4. Score
    # =====================================================

    def ranking_key(x):

        state = x.get(
            "state",
            "",
        )

        liquidity = x.get(
            "liquidity",
            "NEUTRAL",
        )

        accumulation = x.get(
            "accumulation",
            "NONE",
        )

        distribution = x.get(
            "distribution",
            "NONE",
        )

        priority = 0

        # =================================================
        # STATE
        # =================================================

        if state == "ENTRY READY":
            priority += 1000

        elif state == "ACCUMULATION WATCH":
            priority += 850

        elif state == "REVERSAL WATCH":
            priority += 800

        elif state in (
            "LATE PUMP - WAIT",
            "LATE DUMP - WAIT",
        ):
            priority += 300

        # =================================================
        # LIQUIDITY
        # =================================================

        if (
            liquidity == "INFLOW"
            and accumulation
            in (
                "ACCUMULATION",
                "STRONG_ACCUMULATION",
            )
        ):

            priority += 500

        if (
            liquidity == "OUTFLOW"
            and distribution
            in (
                "DISTRIBUTION",
                "STRONG_DISTRIBUTION",
            )
        ):

            priority += 500

        if liquidity in (
            "INFLOW",
            "OUTFLOW",
        ):

            priority += 150

        # =================================================
        # SCORE
        # =================================================

        priority += (
            x.get(
                "score",
                0,
            )
            * 3
        )

        priority += x.get(
            "scan_priority",
            0,
        )

        return priority

    results.sort(
        key=ranking_key,
        reverse=True,
    )

    # =====================================================
    # USEFUL RESULTS
    # =====================================================

    useful = []

    for result in results:

        state = result.get(
            "state",
            "",
        )

        if state in (
            "ENTRY READY",
            "ACCUMULATION WATCH",
            "REVERSAL WATCH",
        ):

            useful.append(
                result
            )

    if useful:

        return useful[:limit]

    # =====================================================
    # FALLBACK
    # =====================================================

    fallback = []

    for result in results:

        if result.get(
            "liquidity"
        ) in (
            "INFLOW",
            "OUTFLOW",
        ):

            fallback.append(
                result
            )

    if fallback:

        return fallback[:limit]

    return results[:limit]


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(
    result,
):

    if not result:
        return "لا توجد بيانات تحليل."

    symbol = result.get(
        "symbol",
        "UNKNOWN",
    )

    direction = result.get(
        "direction",
        "WAIT",
    )

    state = result.get(
        "state",
        "NO TRADE",
    )

    score = result.get(
        "score",
        0,
    )

    price = result.get(
        "price",
        0,
    )

    lines = []

    lines.append(
        "🤖 BingX AI Scanner v11"
    )

    lines.append("")

    lines.append(
        f"💎 العملة: {symbol}"
    )

    # =====================================================
    # DIRECTION
    # =====================================================

    if direction == "LONG":

        direction_text = (
            "🟢 LONG"
        )

    elif direction == "SHORT":

        direction_text = (
            "🔴 SHORT"
        )

    elif direction == "LONG WATCH":

        direction_text = (
            "🟡 LONG WATCH"
        )

    elif direction == "SHORT WATCH":

        direction_text = (
            "🟠 SHORT WATCH"
        )

    else:

        direction_text = (
            "⚪ WAIT"
        )

    lines.append(
        f"📌 الاتجاه: {direction_text}"
    )

    lines.append(
        f"⭐ Score: {score}/100"
    )

    lines.append(
        f"🧠 الحالة: {state}"
    )

    lines.append("")

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    lines.append(
        "📊 الاتجاه متعدد الفريمات:"
    )

    lines.append(
        f"1D: {result.get('trend_1d', 'NEUTRAL')}"
    )

    lines.append(
        f"4H: {result.get('trend_4h', 'NEUTRAL')}"
    )

    lines.append(
        f"1H: {result.get('trend_1h', 'NEUTRAL')}"
    )

    lines.append(
        f"30m: {result.get('trend_30m', 'NEUTRAL')}"
    )

    lines.append(
        f"15m: {result.get('trend_15m', 'NEUTRAL')}"
    )

    lines.append(
        f"تأكيد 15m/30m: "
        f"{result.get('confirmation', 'NEUTRAL')}"
    )

    lines.append("")

    # =====================================================
    # LIQUIDITY
    # =====================================================

    lines.append(
        "💧 السيولة:"
    )

    liquidity = result.get(
        "liquidity",
        "NEUTRAL",
    )

    if liquidity == "INFLOW":

        lines.append(
            "🟢 INFLOW — دخول سيولة"
        )

    elif liquidity == "OUTFLOW":

        lines.append(
            "🔴 OUTFLOW — خروج سيولة"
        )

    else:

        lines.append(
            "🟡 NEUTRAL"
        )

    lines.append(
        f"Liquidity Bias: "
        f"{result.get('liquidity_bias', 'NEUTRAL')}"
    )

    lines.append(
        f"Liquidity Confidence: "
        f"{result.get('liquidity_confidence', 0)}%"
    )

    lines.append(
        f"Volume Ratio: "
        f"{result.get('volume_ratio', 1):.2f}x"
    )

    lines.append(
        f"Volume Trend: "
        f"{result.get('volume_trend', 'NEUTRAL')}"
    )

    lines.append("")

    # =====================================================
    # SMART MONEY
    # =====================================================

    lines.append(
        "🏦 Smart Money State:"
    )

    lines.append(
        "Accumulation: "
        f"{result.get('accumulation', 'NONE')}"
    )

    lines.append(
        "Accumulation Score: "
        f"{result.get('accumulation_score', 0)}"
    )

    lines.append(
        "Distribution: "
        f"{result.get('distribution', 'NONE')}"
    )

    lines.append(
        "Distribution Score: "
        f"{result.get('distribution_score', 0)}"
    )

    lines.append(
        "Reversal: "
        f"{result.get('reversal', 'NONE')}"
    )

    lines.append(
        "BOS: "
        f"{result.get('bos', 'NONE')}"
    )

    lines.append("")

    # =====================================================
    # SCORES
    # =====================================================

    lines.append(
        "⚖️ اتجاه السيولة/التحليل:"
    )

    lines.append(
        f"🟢 LONG Score: "
        f"{result.get('long_score', 0)}/100"
    )

    lines.append(
        f"🔴 SHORT Score: "
        f"{result.get('short_score', 0)}/100"
    )

    lines.append("")

    # =====================================================
    # RSI
    # =====================================================

    lines.append(
        "📈 RSI:"
    )

    lines.append(
        f"1H: "
        f"{result.get('rsi_1h', 50):.1f}"
    )

    lines.append(
        f"15m: "
        f"{result.get('rsi_15m', 50):.1f}"
    )

    lines.append("")

    # =====================================================
    # PRICE LEVELS
    # =====================================================

    lines.append(
        "🎯 المستويات:"
    )

    lines.append(
        f"Entry: {price:.8g}"
    )

    if result.get("sl"):

        lines.append(
            f"🛑 SL: "
            f"{result['sl']:.8g}"
        )

        lines.append(
            f"🎯 TP1: "
            f"{result['tp1']:.8g}"
        )

        lines.append(
            f"🎯 TP2: "
            f"{result['tp2']:.8g}"
        )

        lines.append(
            f"🎯 TP3: "
            f"{result['tp3']:.8g}"
        )

    # =====================================================
    # REASONS
    # =====================================================

    reasons = result.get(
        "reasons",
        [],
    )

    if reasons:

        lines.append("")

        lines.append(
            "🧠 أسباب التحليل:"
        )

        for reason in reasons[:10]:

            lines.append(
                f"• {reason}"
            )

    # =====================================================
    # WARNING
    # =====================================================

    warning = result.get(
        "warning",
        "",
    )

    if warning:

        lines.append("")

        lines.append(
            warning
        )

    return "\n".join(lines)


# =========================================================
# FORMAT SCAN
# =========================================================

def format_scan_results(
    results,
):

    if not results:

        return (
            "🟡 انتهى الفحص.\n\n"
            "لم يتم العثور على "
            "مرشحين مناسبين حالياً.\n\n"
            "🛡️ البوت فضّل الانتظار."
        )

    lines = [

        "🤖 BingX AI Scanner v11",

        "",

        "🔎 أفضل المرشحين حالياً:",

        "",
    ]

    for index, result in enumerate(
        results,
        start=1,
    ):

        symbol = result.get(
            "symbol",
            "UNKNOWN",
        )

        direction = result.get(
            "direction",
            "WAIT",
        )

        state = result.get(
            "state",
            "NO TRADE",
        )

        score = result.get(
            "score",
            0,
        )

        liquidity = result.get(
            "liquidity",
            "NEUTRAL",
        )

        if state == "ENTRY READY":

            icon = "🟢"

        elif state == (
            "ACCUMULATION WATCH"
        ):

            icon = "🔵"

        elif state == (
            "REVERSAL WATCH"
        ):

            icon = "🟡"

        else:

            icon = "⚪"

        lines.append(
            f"{index}. "
            f"{icon} {symbol}"
        )

        lines.append(
            f"   الاتجاه: "
            f"{direction}"
        )

        lines.append(
            f"   الحالة: "
            f"{state}"
        )

        lines.append(
            f"   Score: "
            f"{score}/100"
        )

        lines.append(
            f"   💧 السيولة: "
            f"{liquidity}"
        )

        lines.append(
            f"   🧭 Liquidity Bias: "
            f"{result.get('liquidity_bias', 'NEUTRAL')}"
        )

        lines.append(
            f"   🟢 LONG: "
            f"{result.get('long_score', 0)}/100"
        )

        lines.append(
            f"   🔴 SHORT: "
            f"{result.get('short_score', 0)}/100"
        )

        if result.get(
            "accumulation"
        ) in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        ):

            lines.append(
                "   🔵 يوجد تجميع"
            )

        if result.get(
            "distribution"
        ) in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        ):

            lines.append(
                "   🔴 يوجد توزيع"
            )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# END
# =========================================================
