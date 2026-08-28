# =========================================================
# analysis.py
# BingX Futures AI Scanner
# ORDER BLOCK PRIMARY ENGINE
# Liquidity + BOS + Retest + MTF Confirmation
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
    "User-Agent": "CryptoZeroReversal-BingX-OB-Scanner/11.0",
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
    return max(low, min(high, value))


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

                _RATE_LIMIT_UNTIL = time.time() + 5

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
                        or item.get("quoteVolume")
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
                    "open": safe_float(item[1]),
                    "high": safe_float(item[2]),
                    "low": safe_float(item[3]),
                    "close": safe_float(item[4]),
                    "volume": safe_float(item[5]),
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

        # BingX normally returns chronological data,
        # but sorting protects the OB calculations.
        candles.sort(
            key=lambda x: safe_float(
                x.get("time", 0)
            )
        )

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

    multiplier = 2 / (period + 1)

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

        prev_close = previous["close"]

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

    recent = klines[-1]["volume"]

    previous = [
        x["volume"]
        for x in klines[-period - 1:-1]
        if x["volume"] > 0
    ]

    if not previous:
        return 1.0

    avg_volume = mean(previous)

    if avg_volume <= 0:
        return 1.0

    return recent / avg_volume


def calculate_volume_trend(
    klines,
    lookback=8,
):

    if len(klines) < lookback * 2:
        return "NEUTRAL"

    recent = [
        x["volume"]
        for x in klines[-lookback:]
    ]

    previous = [
        x["volume"]
        for x in klines[
            -lookback * 2:-lookback
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
# ORDER BLOCK ENGINE
# =========================================================

def _candle_body(candle):

    return abs(
        candle["close"]
        - candle["open"]
    )


def _candle_range(candle):

    return max(
        candle["high"]
        - candle["low"],
        0.0,
    )


def _is_bullish(candle):

    return candle["close"] > candle["open"]


def _is_bearish(candle):

    return candle["close"] < candle["open"]


def _impulse_after(
    klines,
    index,
    direction,
    bars=4,
):

    if index + 1 >= len(klines):
        return 0.0

    end = min(
        len(klines),
        index + 1 + bars,
    )

    block = klines[
        index + 1:end
    ]

    if not block:
        return 0.0

    ob = klines[index]

    if direction == "BULLISH":

        highest = max(
            x["high"]
            for x in block
        )

        if ob["high"] <= 0:
            return 0.0

        return (
            highest
            - ob["high"]
        ) / ob["high"] * 100

    lowest = min(
        x["low"]
        for x in block
    )

    if ob["low"] <= 0:
        return 0.0

    return (
        ob["low"]
        - lowest
    ) / ob["low"] * 100


def _future_break(
    klines,
    index,
    direction,
    bars=6,
):

    if index + 1 >= len(klines):
        return False

    end = min(
        len(klines),
        index + 1 + bars,
    )

    future = klines[
        index + 1:end
    ]

    if not future:
        return False

    if index < 5:
        return False

    previous = klines[
        max(0, index - 12):index
    ]

    if not previous:
        return False

    if direction == "BULLISH":

        previous_high = max(
            x["high"]
            for x in previous
        )

        return any(
            x["close"] > previous_high
            for x in future
        )

    previous_low = min(
        x["low"]
        for x in previous
    )

    return any(
        x["close"] < previous_low
        for x in future
    )


def detect_order_blocks(
    klines,
    lookback=80,
):

    result = {
        "bullish": [],
        "bearish": [],
    }

    if len(klines) < 30:
        return result

    start = max(
        5,
        len(klines) - lookback - 8,
    )

    end = len(klines) - 5

    for i in range(
        start,
        end,
    ):

        candle = klines[i]

        rng = _candle_range(candle)

        if rng <= 0:
            continue

        body = _candle_body(candle)

        body_ratio = (
            body / rng
        )

        volume = candle["volume"]

        surrounding = klines[
            max(0, i - 10):i
        ]

        avg_volume = mean([
            x["volume"]
            for x in surrounding
            if x["volume"] > 0
        ]) if surrounding else 0

        volume_factor = (
            volume / avg_volume
            if avg_volume > 0
            else 1.0
        )

        # -------------------------------------------------
        # BULLISH ORDER BLOCK
        #
        # آخر منطقة بيع قبل impulse صاعد
        # -------------------------------------------------

        if _is_bearish(candle):

            impulse = _impulse_after(
                klines,
                i,
                "BULLISH",
                5,
            )

            broke = _future_break(
                klines,
                i,
                "BULLISH",
                8,
            )

            if (
                impulse >= 1.0
                and (
                    broke
                    or impulse >= 2.0
                )
            ):

                strength = 35

                if impulse >= 2:
                    strength += 10

                if impulse >= 4:
                    strength += 10

                if broke:
                    strength += 15

                if volume_factor >= 1.2:
                    strength += 10

                if body_ratio <= 0.65:
                    strength += 5

                zone_low = candle["low"]
                zone_high = max(
                    candle["open"],
                    candle["close"],
                )

                result["bullish"].append({
                    "index": i,
                    "low": zone_low,
                    "high": zone_high,
                    "strength": int(
                        clamp(
                            strength,
                            0,
                            100,
                        )
                    ),
                    "impulse": impulse,
                    "volume_factor":
                        volume_factor,
                    "broken": broke,
                    "time": candle.get(
                        "time"
                    ),
                })

        # -------------------------------------------------
        # BEARISH ORDER BLOCK
        #
        # آخر منطقة شراء قبل impulse هابط
        # -------------------------------------------------

        if _is_bullish(candle):

            impulse = _impulse_after(
                klines,
                i,
                "BEARISH",
                5,
            )

            broke = _future_break(
                klines,
                i,
                "BEARISH",
                8,
            )

            if (
                impulse >= 1.0
                and (
                    broke
                    or impulse >= 2.0
                )
            ):

                strength = 35

                if impulse >= 2:
                    strength += 10

                if impulse >= 4:
                    strength += 10

                if broke:
                    strength += 15

                if volume_factor >= 1.2:
                    strength += 10

                if body_ratio <= 0.65:
                    strength += 5

                zone_low = min(
                    candle["open"],
                    candle["close"],
                )

                zone_high = candle["high"]

                result["bearish"].append({
                    "index": i,
                    "low": zone_low,
                    "high": zone_high,
                    "strength": int(
                        clamp(
                            strength,
                            0,
                            100,
                        )
                    ),
                    "impulse": impulse,
                    "volume_factor":
                        volume_factor,
                    "broken": broke,
                    "time": candle.get(
                        "time"
                    ),
                })

    # الأحدث أولاً
    result["bullish"].sort(
        key=lambda x: (
            x["strength"],
            x["index"],
        ),
        reverse=True,
    )

    result["bearish"].sort(
        key=lambda x: (
            x["strength"],
            x["index"],
        ),
        reverse=True,
    )

    return result


# =========================================================
# ORDER BLOCK RETEST
# =========================================================

def _price_in_zone(
    price,
    zone,
    tolerance=0.006,
):

    low = zone["low"]
    high = zone["high"]

    expanded_low = (
        low * (1 - tolerance)
    )

    expanded_high = (
        high * (1 + tolerance)
    )

    return (
        expanded_low
        <= price
        <= expanded_high
    )


def _distance_to_zone(
    price,
    zone,
):

    low = zone["low"]
    high = zone["high"]

    if low <= price <= high:
        return 0.0

    if price < low:
        return (
            (low - price)
            / price
            * 100
        )

    return (
        (price - high)
        / price
        * 100
    )


def find_best_order_block(
    klines,
    direction,
):

    blocks = detect_order_blocks(
        klines
    )

    if not klines:
        return None

    price = klines[-1]["close"]

    if direction == "LONG":

        candidates = blocks[
            "bullish"
        ]

    else:

        candidates = blocks[
            "bearish"
        ]

    if not candidates:
        return None

    best = None
    best_score = -999

    for block in candidates:

        distance = _distance_to_zone(
            price,
            block,
        )

        # لا نعتبر OB قديم بعيد جداً صالحاً للدخول.
        if distance > 12:
            continue

        retest = _price_in_zone(
            price,
            block,
            tolerance=0.006,
        )

        score = block["strength"]

        if retest:
            score += 30

        elif distance <= 2:
            score += 20

        elif distance <= 5:
            score += 10

        # الأفضل هو الأقرب والأقوى
        score -= min(
            distance * 2,
            20,
        )

        if score > best_score:

            best_score = score

            best = {
                **block,
                "distance": distance,
                "retest": retest,
                "score": int(
                    clamp(
                        score,
                        0,
                        100,
                    )
                ),
            }

    return best


# =========================================================
# ORDER BLOCK STATE
# =========================================================

def get_order_block_state(
    klines,
):

    if len(klines) < 30:

        return {
            "state": "NONE",
            "direction": "NEUTRAL",
            "score": 0,
            "bullish": None,
            "bearish": None,
        }

    bullish = find_best_order_block(
        klines,
        "LONG",
    )

    bearish = find_best_order_block(
        klines,
        "SHORT",
    )

    bull_score = (
        bullish["score"]
        if bullish
        else 0
    )

    bear_score = (
        bearish["score"]
        if bearish
        else 0
    )

    if (
        bull_score >= 55
        and bull_score
        >= bear_score + 10
    ):

        state = (
            "BULLISH_ORDER_BLOCK"
        )

        direction = "LONG"

    elif (
        bear_score >= 55
        and bear_score
        >= bull_score + 10
    ):

        state = (
            "BEARISH_ORDER_BLOCK"
        )

        direction = "SHORT"

    elif (
        bull_score >= 50
        and bull_score > bear_score
    ):

        state = (
            "BULLISH_OB_WATCH"
        )

        direction = "LONG"

    elif (
        bear_score >= 50
        and bear_score > bull_score
    ):

        state = (
            "BEARISH_OB_WATCH"
        )

        direction = "SHORT"

    else:

        state = "NEUTRAL"

        direction = "NEUTRAL"

    return {
        "state": state,
        "direction": direction,
        "score": max(
            bull_score,
            bear_score,
        ),
        "bull_score": bull_score,
        "bear_score": bear_score,
        "bullish": bullish,
        "bearish": bearish,
    }


# =========================================================
# MARKET STRUCTURE / BOS
# =========================================================

def detect_market_structure(
    klines,
):

    if len(klines) < 30:

        return {
            "structure": "MIXED",
            "bos": "NONE",
            "bullish": False,
            "bearish": False,
        }

    lookback = 25

    recent = klines[
        -lookback:
    ]

    current_close = (
        recent[-1]["close"]
    )

    # -----------------------------------------------------
    # استخدم swing levels وليس لون الشموع
    # -----------------------------------------------------

    swing_high = max(
        x["high"]
        for x in recent[:-5]
    )

    swing_low = min(
        x["low"]
        for x in recent[:-5]
    )

    bullish = (
        current_close
        > swing_high
    )

    bearish = (
        current_close
        < swing_low
    )

    if bullish:

        return {
            "structure": "BULLISH",
            "bos": "BULLISH",
            "bullish": True,
            "bearish": False,
        }

    if bearish:

        return {
            "structure": "BEARISH",
            "bos": "BEARISH",
            "bullish": False,
            "bearish": True,
        }

    return {
        "structure": "MIXED",
        "bos": "NONE",
        "bullish": False,
        "bearish": False,
    }


# =========================================================
# LIQUIDITY
# =========================================================
#
# مهم:
# السيولة هنا ليست مبنية على:
# green candles = inflow
# red candles   = outflow
#
# بل تعتمد على:
# OB + price reaction + volume confirmation
# =========================================================

def detect_liquidity_flow(
    klines,
):

    result = {
        "state": "NEUTRAL",
        "bullish_volume": 0.0,
        "bearish_volume": 0.0,
        "ratio": 1.0,
        "confidence": 0,
    }

    if len(klines) < 30:
        return result

    ob = get_order_block_state(
        klines
    )

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    structure = (
        detect_market_structure(
            klines
        )
    )

    price = klines[-1]["close"]

    bull_ob = ob.get(
        "bullish"
    )

    bear_ob = ob.get(
        "bearish"
    )

    bull_confirmation = 0
    bear_confirmation = 0

    if bull_ob:

        if _price_in_zone(
            price,
            bull_ob,
            0.008,
        ):
            bull_confirmation += 2

        elif bull_ob["distance"] <= 3:
            bull_confirmation += 1

        if bull_ob["strength"] >= 70:
            bull_confirmation += 1

    if bear_ob:

        if _price_in_zone(
            price,
            bear_ob,
            0.008,
        ):
            bear_confirmation += 2

        elif bear_ob["distance"] <= 3:
            bear_confirmation += 1

        if bear_ob["strength"] >= 70:
            bear_confirmation += 1

    if structure["bullish"]:
        bull_confirmation += 1

    if structure["bearish"]:
        bear_confirmation += 1

    if volume_ratio >= 1.10:

        if bull_confirmation > bear_confirmation:
            bull_confirmation += 1

        elif bear_confirmation > bull_confirmation:
            bear_confirmation += 1

    if (
        bull_confirmation >= 3
        and bull_confirmation
        >= bear_confirmation + 1
    ):

        state = "INFLOW"

        confidence = int(
            clamp(
                55
                + bull_confirmation * 10,
                0,
                100,
            )
        )

    elif (
        bear_confirmation >= 3
        and bear_confirmation
        >= bull_confirmation + 1
    ):

        state = "OUTFLOW"

        confidence = int(
            clamp(
                55
                + bear_confirmation * 10,
                0,
                100,
            )
        )

    else:

        state = "NEUTRAL"
        confidence = 0

    return {
        "state": state,
        "bullish_volume":
            float(bull_confirmation),
        "bearish_volume":
            float(bear_confirmation),
        "ratio":
            volume_ratio,
        "confidence":
            confidence,
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

    ob = get_order_block_state(
        klines
    )

    bullish_ob = ob.get(
        "bullish"
    )

    price = klines[-1]["close"]

    if bullish_ob:

        if bullish_ob["strength"] >= 55:

            result["score"] += 3

            result["reasons"].append(
                "Bullish Order Block قوي"
            )

        if _price_in_zone(
            price,
            bullish_ob,
            0.008,
        ):

            result["score"] += 2

            result["reasons"].append(
                "السعر داخل Bullish OB"
            )

        elif bullish_ob["distance"] <= 3:

            result["score"] += 1

            result["reasons"].append(
                "السعر قريب من Bullish OB"
            )

    # -----------------------------------------------------
    # السعر السابق فقط كـ context
    # وليس لتحديد الاتجاه
    # -----------------------------------------------------

    recent = klines[-30:]

    highest = max(
        x["high"]
        for x in recent
    )

    lowest = min(
        x["low"]
        for x in recent
    )

    if lowest > 0:

        result["range"] = (
            (highest - lowest)
            / lowest
            * 100
        )

    # -----------------------------------------------------
    # volume confirmation
    # -----------------------------------------------------

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    if volume_ratio >= 1.10:

        result["score"] += 1

        result["reasons"].append(
            "الحجم يؤكد منطقة الـ OB"
        )

    structure = (
        detect_market_structure(
            klines
        )
    )

    if structure["bullish"]:

        result["score"] += 2

        result["reasons"].append(
            "BOS صاعد من منطقة الطلب"
        )

    if result["score"] >= 6:

        result["state"] = (
            "STRONG_ACCUMULATION"
        )

    elif result["score"] >= 4:

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

    ob = get_order_block_state(
        klines
    )

    bearish_ob = ob.get(
        "bearish"
    )

    price = klines[-1]["close"]

    if bearish_ob:

        if bearish_ob["strength"] >= 55:

            result["score"] += 3

            result["reasons"].append(
                "Bearish Order Block قوي"
            )

        if _price_in_zone(
            price,
            bearish_ob,
            0.008,
        ):

            result["score"] += 2

            result["reasons"].append(
                "السعر داخل Bearish OB"
            )

        elif bearish_ob["distance"] <= 3:

            result["score"] += 1

            result["reasons"].append(
                "السعر قريب من Bearish OB"
            )

    recent = klines[-30:]

    highest = max(
        x["high"]
        for x in recent
    )

    lowest = min(
        x["low"]
        for x in recent
    )

    if lowest > 0:

        result["range"] = (
            (highest - lowest)
            / lowest
            * 100
        )

    volume_ratio = (
        calculate_volume_ratio(
            klines
        )
    )

    if volume_ratio >= 1.10:

        result["score"] += 1

        result["reasons"].append(
            "الحجم يؤكد منطقة العرض"
        )

    structure = (
        detect_market_structure(
            klines
        )
    )

    if structure["bearish"]:

        result["score"] += 2

        result["reasons"].append(
            "BOS هابط من منطقة العرض"
        )

    if result["score"] >= 6:

        result["state"] = (
            "STRONG_DISTRIBUTION"
        )

    elif result["score"] >= 4:

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

    ob = get_order_block_state(
        klines
    )

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

    # -----------------------------------------------------
    # BULLISH REVERSAL
    # -----------------------------------------------------

    if ob["direction"] == "LONG":

        result["bull_score"] += 3

        result["reasons"].append(
            "Bullish Order Block"
        )

    if ob.get("bullish"):

        if ob["bullish"]["retest"]:

            result["bull_score"] += 2

            result["reasons"].append(
                "Retest للـ Bullish OB"
            )

        if ob["bullish"]["strength"] >= 70:

            result["bull_score"] += 1

    if flow["state"] == "INFLOW":

        result["bull_score"] += 2

    if structure["bullish"]:

        result["bull_score"] += 2

    # -----------------------------------------------------
    # BEARISH REVERSAL
    # -----------------------------------------------------

    if ob["direction"] == "SHORT":

        result["bear_score"] += 3

        result["reasons"].append(
            "Bearish Order Block"
        )

    if ob.get("bearish"):

        if ob["bearish"]["retest"]:

            result["bear_score"] += 2

            result["reasons"].append(
                "Retest للـ Bearish OB"
            )

        if ob["bearish"]["strength"] >= 70:

            result["bear_score"] += 1

    if flow["state"] == "OUTFLOW":

        result["bear_score"] += 2

    if structure["bearish"]:

        result["bear_score"] += 2

    # -----------------------------------------------------
    # FINAL
    # -----------------------------------------------------

    if (
        result["bull_score"] >= 5
        and result["bull_score"]
        >= result["bear_score"] + 2
    ):

        result["state"] = (
            "BULLISH_REVERSAL"
        )

    elif (
        result["bear_score"] >= 5
        and result["bear_score"]
        >= result["bull_score"] + 2
    ):

        result["state"] = (
            "BEARISH_REVERSAL"
        )

    return result


# =========================================================
# LATE PUMP / DUMP
# =========================================================
#
# لا تستخدم لتحديد الاتجاه.
# فقط تحمي من مطاردة الحركة.
# =========================================================

def detect_late_pump(
    klines,
):

    if len(klines) < 30:
        return False

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

    price = closes[-1]

    atr = calculate_atr(
        klines
    )

    if atr <= 0:
        return False

    extension = (
        price - ema20
    ) / atr

    return (
        extension >= 4
        and price > ema9
    )


def detect_late_dump(
    klines,
):

    if len(klines) < 30:
        return False

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

    price = closes[-1]

    atr = calculate_atr(
        klines
    )

    if atr <= 0:
        return False

    extension = (
        ema20 - price
    ) / atr

    return (
        extension >= 4
        and price < ema9
    )


# =========================================================
# MTF ORDER BLOCK DIRECTION
# =========================================================

def get_mtf_ob_direction(
    tf_15m,
    tf_30m,
    tf_1h,
    tf_4h,
):

    scores = {
        "LONG": 0,
        "SHORT": 0,
    }

    details = {}

    for name, data in (
        ("15m", tf_15m),
        ("30m", tf_30m),
        ("1h", tf_1h),
        ("4h", tf_4h),
    ):

        ob = get_order_block_state(
            data
        )

        details[name] = ob

        if ob["direction"] == "LONG":

            weight = {
                "15m": 1,
                "30m": 2,
                "1h": 3,
                "4h": 3,
            }[name]

            scores["LONG"] += (
                ob["score"] / 100
            ) * weight

        elif ob["direction"] == "SHORT":

            weight = {
                "15m": 1,
                "30m": 2,
                "1h": 3,
                "4h": 3,
            }[name]

            scores["SHORT"] += (
                ob["score"] / 100
            ) * weight

    if (
        scores["LONG"]
        >= scores["SHORT"] + 2
    ):

        direction = "LONG"

    elif (
        scores["SHORT"]
        >= scores["LONG"] + 2
    ):

        direction = "SHORT"

    else:

        direction = "NEUTRAL"

    return {
        "direction": direction,
        "long_score": scores["LONG"],
        "short_score": scores["SHORT"],
        "details": details,
    }


# =========================================================
# CLASSIFICATION
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
    ob_direction="NEUTRAL",
    ob_score=0,
    mtf_ob_direction="NEUTRAL",
):

    # =====================================================
    # HARD ORDER BLOCK PRIORITY
    # =====================================================

    if ob_direction == "LONG":

        if mtf_ob_direction == "LONG":

            if reversal == "BULLISH_REVERSAL":

                return (
                    "LONG",
                    "ENTRY READY",
                )

            if (
                structure == "BULLISH"
                or flow == "INFLOW"
            ):

                return (
                    "LONG",
                    "ENTRY READY",
                )

            return (
                "LONG WATCH",
                "ACCUMULATION WATCH",
            )

        return (
            "LONG WATCH",
            "ACCUMULATION WATCH",
        )

    if ob_direction == "SHORT":

        if mtf_ob_direction == "SHORT":

            if reversal == "BEARISH_REVERSAL":

                return (
                    "SHORT",
                    "ENTRY READY",
                )

            if (
                structure == "BEARISH"
                or flow == "OUTFLOW"
            ):

                return (
                    "SHORT",
                    "ENTRY READY",
                )

            return (
                "SHORT WATCH",
                "REVERSAL WATCH",
            )

        return (
            "SHORT WATCH",
            "REVERSAL WATCH",
        )

    # =====================================================
    # NO STRONG OB
    # =====================================================

    return (
        "WAIT",
        "NO TRADE",
    )


# =========================================================
# ENTRY SCORE
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
    ob_direction="NEUTRAL",
    ob_score=0,
    mtf_ob_direction="NEUTRAL",
    mtf_long_score=0,
    mtf_short_score=0,
):

    long_score = 0
    short_score = 0

    # =====================================================
    # ORDER BLOCK = 50%+ OF SCORE
    # =====================================================

    if ob_direction == "LONG":

        long_score += 40

        long_score += int(
            clamp(
                ob_score * 0.15,
                0,
                15,
            )
        )

    elif ob_direction == "SHORT":

        short_score += 40

        short_score += int(
            clamp(
                ob_score * 0.15,
                0,
                15,
            )
        )

    # =====================================================
    # MTF OB
    # =====================================================

    if mtf_ob_direction == "LONG":

        long_score += 15

    elif mtf_ob_direction == "SHORT":

        short_score += 15

    # =====================================================
    # BOS
    # =====================================================

    if reversal == "BULLISH_REVERSAL":

        long_score += 15

    elif reversal == "BEARISH_REVERSAL":

        short_score += 15

    # =====================================================
    # LIQUIDITY CONFIRMATION
    # =====================================================

    if flow == "INFLOW":

        long_score += 10

    elif flow == "OUTFLOW":

        short_score += 10

    # =====================================================
    # ACCUMULATION / DISTRIBUTION
    # =====================================================

    if accumulation in (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    ):

        long_score += 10

    if distribution in (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    ):

        short_score += 10

    # =====================================================
    # HARD PROTECTION
    # =====================================================

    if ob_direction == "LONG":

        short_score = min(
            short_score,
            30,
        )

    if ob_direction == "SHORT":

        long_score = min(
            long_score,
            30,
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
# SINGLE COIN
# =========================================================

def get_coin_analysis(
    symbol,
):

    symbol = normalize_symbol(
        symbol
    )

    try:

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
        # MTF TREND
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
        # PRIMARY ORDER BLOCK
        # =================================================

        ob_1h = get_order_block_state(
            tf_1h
        )

        mtf_ob = get_mtf_ob_direction(
            tf_15m,
            tf_30m,
            tf_1h,
            tf_4h,
        )

        ob_direction = (
            ob_1h["direction"]
        )

        ob_score = (
            ob_1h["score"]
        )

        # =================================================
        # CONFIRMATIONS
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
        # PRICE
        # =================================================

        price = tf_1h[-1]["close"]

        support = min(
            x["low"]
            for x in tf_1h[-80:]
        )

        resistance = max(
            x["high"]
            for x in tf_1h[-80:]
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
        # CLASSIFY
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
                ob_direction,
                ob_score,
                mtf_ob["direction"],
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
                ob_direction,
                ob_score,
                mtf_ob["direction"],
                mtf_ob["long_score"],
                mtf_ob["short_score"],
            )
        )

        # =================================================
        # FINAL DIRECTION PROTECTION
        # =================================================

        # Bullish OB يمنع SHORT
        if (
            ob_direction == "LONG"
            and ob_score >= 60
        ):

            if direction in (
                "SHORT",
                "SHORT WATCH",
            ):

                direction = "LONG WATCH"

                state = (
                    "ACCUMULATION WATCH"
                )

        # Bearish OB يمنع LONG
        if (
            ob_direction == "SHORT"
            and ob_score >= 60
        ):

            if direction in (
                "LONG",
                "LONG WATCH",
            ):

                direction = "SHORT WATCH"

                state = (
                    "REVERSAL WATCH"
                )

        # =================================================
        # NO OB = NO TRADE
        # =================================================

        if ob_direction == "NEUTRAL":

            direction = "WAIT"

            state = "NO TRADE"

        # =================================================
        # LEVELS BASED ON ORDER BLOCK
        # =================================================

        entry = price

        active_ob = None

        if direction in (
            "LONG",
            "LONG WATCH",
        ):

            active_ob = (
                ob_1h.get("bullish")
            )

            if active_ob:

                sl = (
                    active_ob["low"]
                    - atr * 0.35
                )

            else:

                sl = (
                    price
                    - atr * 1.5
                )

            if sl >= price:

                sl = (
                    price
                    - atr * 1.5
                )

            risk = max(
                price - sl,
                atr * 0.8,
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

            active_ob = (
                ob_1h.get("bearish")
            )

            if active_ob:

                sl = (
                    active_ob["high"]
                    + atr * 0.35
                )

            else:

                sl = (
                    price
                    + atr * 1.5
                )

            if sl <= price:

                sl = (
                    price
                    + atr * 1.5
                )

            risk = max(
                sl - price,
                atr * 0.8,
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
        # REASONS
        # =================================================

        reasons = []

        if ob_direction == "LONG":

            reasons.append(
                "🟢 Bullish Order Block"
            )

            if ob_1h.get("bullish"):

                reasons.append(
                    "📍 منطقة الطلب "
                    f"{ob_1h['bullish']['low']:.8g}"
                    " - "
                    f"{ob_1h['bullish']['high']:.8g}"
                )

                if ob_1h["bullish"]["retest"]:

                    reasons.append(
                        "🔄 السعر داخل Retest للـ OB"
                    )

        elif ob_direction == "SHORT":

            reasons.append(
                "🔴 Bearish Order Block"
            )

            if ob_1h.get("bearish"):

                reasons.append(
                    "📍 منطقة العرض "
                    f"{ob_1h['bearish']['low']:.8g}"
                    " - "
                    f"{ob_1h['bearish']['high']:.8g}"
                )

                if ob_1h["bearish"]["retest"]:

                    reasons.append(
                        "🔄 السعر داخل Retest للـ OB"
                    )

        if mtf_ob["direction"] == "LONG":

            reasons.append(
                "🟢 MTF Order Blocks تميل للـ LONG"
            )

        elif mtf_ob["direction"] == "SHORT":

            reasons.append(
                "🔴 MTF Order Blocks تميل للـ SHORT"
            )

        if structure["bos"] == "BULLISH":

            reasons.append(
                "📈 BOS صاعد"
            )

        elif structure["bos"] == "BEARISH":

            reasons.append(
                "📉 BOS هابط"
            )

        if flow_data["state"] == "INFLOW":

            reasons.append(
                "💧 تأكيد سيولة للشراء"
            )

        elif flow_data["state"] == "OUTFLOW":

            reasons.append(
                "💧 تأكيد سيولة للبيع"
            )

        if accumulation["state"] in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        ):

            reasons.append(
                "🔵 Accumulation"
            )

        if distribution["state"] in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        ):

            reasons.append(
                "🔴 Distribution"
            )

        # =================================================
        # WARNING
        # =================================================

        warning = ""

        if (
            ob_direction == "LONG"
            and flow_data["state"] == "OUTFLOW"
        ):

            warning = (
                "⚠️ Bullish OB موجود، "
                "لكن تأكيد السيولة غير مكتمل. "
                "لا تطارد LONG."
            )

        elif (
            ob_direction == "SHORT"
            and flow_data["state"] == "INFLOW"
        ):

            warning = (
                "⚠️ Bearish OB موجود، "
                "لكن تأكيد السيولة غير مكتمل. "
                "لا تطارد SHORT."
            )

        if late_pump and direction in (
            "LONG",
            "LONG WATCH",
        ):

            warning = (
                "⚠️ السعر ممتد عن منطقة الـ OB. "
                "انتظر Retest."
            )

        if late_dump and direction in (
            "SHORT",
            "SHORT WATCH",
        ):

            warning = (
                "⚠️ السعر ممتد هبوطاً عن منطقة الـ OB. "
                "انتظر Retest."
            )

        # =================================================
        # FINAL SCORE
        # =================================================

        score = max(
            long_score,
            short_score,
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

            "long_score": long_score,

            "short_score": short_score,

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

            "rsi_1h": rsi_1h,

            "rsi_15m": rsi_15m,

            "volume_ratio": volume_ratio,

            "volume_trend": volume_trend,

            "liquidity":
                flow_data["state"],

            "liquidity_confidence":
                flow_data["confidence"],

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

            "support":
                support,

            "resistance":
                resistance,

            "late_pump":
                late_pump,

            "late_dump":
                late_dump,

            "order_block_direction":
                ob_direction,

            "order_block_state":
                ob_1h["state"],

            "order_block_score":
                ob_score,

            "mtf_ob_direction":
                mtf_ob["direction"],

            "mtf_ob_long_score":
                mtf_ob["long_score"],

            "mtf_ob_short_score":
                mtf_ob["short_score"],

            "bullish_ob":
                ob_1h.get("bullish"),

            "bearish_ob":
                ob_1h.get("bearish"),

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
    # =====================================================
    #
    # الفلترة هنا تعتمد على OB وليس أكبر ربح/خسارة.
    # =====================================================

    for symbol in symbols:

        try:

            klines = get_klines(
                symbol,
                "1h",
                60,
            )

            if len(klines) < 30:
                continue

            current = klines[-1]["close"]

            if current <= 0:
                continue

            ob = get_order_block_state(
                klines
            )

            flow = detect_liquidity_flow(
                klines
            )

            priority = 0

            # =================================================
            # ORDER BLOCK PRIMARY
            # =================================================

            if ob["direction"] in (
                "LONG",
                "SHORT",
            ):

                priority += 50

                priority += int(
                    ob["score"] * 0.35
                )

            # =================================================
            # RETEST
            # =================================================

            if (
                ob.get("bullish")
                and ob["bullish"]["retest"]
            ):

                priority += 20

            if (
                ob.get("bearish")
                and ob["bearish"]["retest"]
            ):

                priority += 20

            # =================================================
            # LIQUIDITY CONFIRMATION
            # =================================================

            if flow["state"] != "NEUTRAL":

                priority += 10

            # =================================================
            # VOLUME فقط تأكيد
            # =================================================

            volume_ratio = (
                calculate_volume_ratio(
                    klines
                )
            )

            if volume_ratio >= 1.10:

                priority += 5

            # =================================================
            # NO OB = DROP
            # =================================================

            if ob["direction"] == "NEUTRAL":

                continue

            candidates.append({
                "symbol": symbol,
                "priority": priority,
            })

        except Exception:

            continue

    if not candidates:
        return []

    candidates.sort(
        key=lambda x: x["priority"],
        reverse=True,
    )

    # =====================================================
    # DEEP SCAN
    # =====================================================

    deep_limit = min(
        max(
            limit * 4,
            20,
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

    # =====================================================
    # RANK
    # =====================================================

    state_rank = {

        "ENTRY READY": 6,

        "ACCUMULATION WATCH": 5,

        "REVERSAL WATCH": 5,

        "LATE PUMP - WAIT": 2,

        "LATE DUMP - WAIT": 2,

        "NO TRADE": 1,
    }

    results.sort(
        key=lambda x: (
            state_rank.get(
                x.get(
                    "state",
                    "",
                ),
                0,
            ),

            x.get(
                "score",
                0,
            ),

            x.get(
                "order_block_score",
                0,
            ),

            x.get(
                "scan_priority",
                0,
            ),
        ),
        reverse=True,
    )

    # =====================================================
    # ONLY USEFUL OB RESULTS
    # =====================================================

    useful = []

    for result in results:

        if result.get(
            "order_block_direction"
        ) not in (
            "LONG",
            "SHORT",
        ):
            continue

        if result.get(
            "state"
        ) in (
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
            "order_block_score",
            0,
        ) >= 55:

            fallback.append(
                result
            )

    if fallback:

        return fallback[:limit]

    return []


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
        "🤖 BingX AI Scanner — ORDER BLOCK"
    )

    lines.append("")

    lines.append(
        f"💎 العملة: {symbol}"
    )

    if direction == "LONG":

        direction_text = "🟢 LONG"

    elif direction == "SHORT":

        direction_text = "🔴 SHORT"

    elif direction == "LONG WATCH":

        direction_text = "🟡 LONG WATCH"

    elif direction == "SHORT WATCH":

        direction_text = "🟠 SHORT WATCH"

    else:

        direction_text = "⚪ WAIT"

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
    # ORDER BLOCK
    # =====================================================

    lines.append(
        "🏦 ORDER BLOCK — العامل الأساسي:"
    )

    ob_direction = result.get(
        "order_block_direction",
        "NEUTRAL",
    )

    ob_state = result.get(
        "order_block_state",
        "NEUTRAL",
    )

    ob_score = result.get(
        "order_block_score",
        0,
    )

    lines.append(
        f"الاتجاه: {ob_direction}"
    )

    lines.append(
        f"الحالة: {ob_state}"
    )

    lines.append(
        f"قوة الـ OB: {ob_score}/100"
    )

    bullish_ob = result.get(
        "bullish_ob"
    )

    bearish_ob = result.get(
        "bearish_ob"
    )

    if bullish_ob:

        lines.append(
            "🟢 Bullish OB: "
            f"{bullish_ob['low']:.8g}"
            " - "
            f"{bullish_ob['high']:.8g}"
        )

        lines.append(
            f"قوة المنطقة: "
            f"{bullish_ob['strength']}/100"
        )

        lines.append(
            f"Retest: "
            f"{'YES' if bullish_ob['retest'] else 'NO'}"
        )

    if bearish_ob:

        lines.append(
            "🔴 Bearish OB: "
            f"{bearish_ob['low']:.8g}"
            " - "
            f"{bearish_ob['high']:.8g}"
        )

        lines.append(
            f"قوة المنطقة: "
            f"{bearish_ob['strength']}/100"
        )

        lines.append(
            f"Retest: "
            f"{'YES' if bearish_ob['retest'] else 'NO'}"
        )

    lines.append("")

    # =====================================================
    # MTF OB
    # =====================================================

    lines.append(
        "🧭 MTF Order Block:"
    )

    lines.append(
        f"15m/30m/1H/4H: "
        f"{result.get('mtf_ob_direction', 'NEUTRAL')}"
    )

    lines.append("")

    # =====================================================
    # TRENDS
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

    lines.append("")

    # =====================================================
    # CONFIRMATION
    # =====================================================

    lines.append(
        "🔎 التأكيد:"
    )

    lines.append(
        f"BOS: {result.get('bos', 'NONE')}"
    )

    lines.append(
        f"Structure: "
        f"{result.get('market_structure', 'MIXED')}"
    )

    lines.append(
        f"Liquidity: "
        f"{result.get('liquidity', 'NEUTRAL')}"
    )

    lines.append(
        f"Liquidity Confidence: "
        f"{result.get('liquidity_confidence', 0)}%"
    )

    lines.append(
        f"Volume Ratio: "
        f"{result.get('volume_ratio', 1):.2f}x"
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
    # LEVELS
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
            "🧠 أسباب القرار:"
        )

        for reason in reasons[:10]:

            lines.append(
                f"• {reason}"
            )

    warning = result.get(
        "warning",
        "",
    )

    if warning:

        lines.append("")

        lines.append(
            warning
        )

    lines.append("")

    lines.append(
        "🛡️ ملاحظة: "
        "الشموع ليست العامل الأساسي لتحديد LONG/SHORT. "
        "Order Block هو المحور، والسيولة وBOS والتايم فريمات عوامل تأكيد."
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
            "لم يتم العثور على Order Block "
            "قوي ومؤكد حالياً.\n\n"
            "🛡️ البوت فضّل الانتظار."
        )

    lines = [

        "🤖 BingX AI Scanner",

        "🏦 ORDER BLOCK ENGINE",

        "",

        "🔎 أفضل المناطق حالياً:",

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

        ob_direction = result.get(
            "order_block_direction",
            "NEUTRAL",
        )

        ob_score = result.get(
            "order_block_score",
            0,
        )

        if direction == "LONG":

            icon = "🟢"

        elif direction == "SHORT":

            icon = "🔴"

        elif direction == "LONG WATCH":

            icon = "🔵"

        elif direction == "SHORT WATCH":

            icon = "🟠"

        else:

            icon = "⚪"

        lines.append(
            f"{index}. "
            f"{icon} {symbol}"
        )

        lines.append(
            f"   الاتجاه: {direction}"
        )

        lines.append(
            f"   الحالة: {state}"
        )

        lines.append(
            f"   OB: "
            f"{ob_direction} "
            f"({ob_score}/100)"
        )

        lines.append(
            f"   Score: {score}/100"
        )

        lines.append(
            f"   Liquidity: "
            f"{result.get('liquidity', 'NEUTRAL')}"
        )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# END
# =========================================================
