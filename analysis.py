# =========================================================
# analysis.py
# BingX Futures AI Scanner
# Liquidity + Accumulation/Distribution + Reversal Engine
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
    "User-Agent": "CryptoZeroReversal-BingX-Scanner/9.0",
    "Accept": "application/json",
})

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 12

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 60

MIN_REQUEST_INTERVAL = 0.45

_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0

_KLINE_CACHE = {}
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_TIME = 0.0

_RATE_LIMIT_UNTIL = 0.0


# =========================================================
# BASIC HELPERS
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

    for suffix in (
        "-PERP",
        "_PERP",
        "/USDT",
        "-USDT",
        "_USDT",
        " USDT",
    ):
        s = s.replace(suffix, "")

    s = s.replace("/", "").replace("-", "").replace("_", "")

    if not s.endswith("USDT"):
        s += "USDT"

    return s


def bingx_symbol(symbol):
    s = normalize_symbol(symbol)
    return s


def _throttle():
    global _LAST_REQUEST_TIME

    with _REQUEST_LOCK:
        now = time.time()
        wait = MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST_TIME)

        if wait > 0:
            time.sleep(wait)

        _LAST_REQUEST_TIME = time.time()


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

            code = str(data.get("code", ""))

            if code in ("109429", "109400"):
                _RATE_LIMIT_UNTIL = time.time() + 5
                time.sleep(1.5)
                continue

            return data

        except Exception as exc:
            if attempt == 2:
                logger.warning("BingX request failed: %s", exc)
                return None

            time.sleep(0.8)

    return None


# =========================================================
# SYMBOLS
# =========================================================

def get_futures_symbols():
    global _SYMBOL_CACHE
    global _SYMBOL_CACHE_TIME

    now = time.time()

    if _SYMBOL_CACHE and now - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return list(_SYMBOL_CACHE)

    data = _get_json("/openApi/swap/v2/quote/contracts")

    symbols = set()

    try:
        rows = data.get("data", []) if data else []

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

            symbol = normalize_symbol(symbol)

            if symbol.endswith("USDT"):
                symbols.add(symbol)

    except Exception as exc:
        logger.warning("Symbol parsing failed: %s", exc)

    if symbols:
        _SYMBOL_CACHE = symbols
        _SYMBOL_CACHE_TIME = now

    return list(_SYMBOL_CACHE)


# =========================================================
# KLINES
# =========================================================

def _interval_minutes(interval):
    mapping = {
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    return mapping.get(interval, 60)


def get_klines(symbol, interval="1h", limit=120):

    symbol = bingx_symbol(symbol)

    cache_key = (symbol, interval, limit)
    now = time.time()

    cached = _KLINE_CACHE.get(cache_key)

    if cached:
        timestamp, values = cached

        if now - timestamp < KLINE_CACHE_SECONDS:
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

    raw = data.get("data", [])

    candles = []

    try:

        for item in raw:

            if isinstance(item, dict):

                candles.append({
                    "open": safe_float(item.get("open")),
                    "high": safe_float(item.get("high")),
                    "low": safe_float(item.get("low")),
                    "close": safe_float(item.get("close")),
                    "volume": safe_float(
                        item.get("volume")
                        or item.get("quoteVolume")
                    ),
                    "time": item.get("time"),
                })

            elif isinstance(item, (list, tuple)) and len(item) >= 6:

                candles.append({
                    "open": safe_float(item[1]),
                    "high": safe_float(item[2]),
                    "low": safe_float(item[3]),
                    "close": safe_float(item[4]),
                    "volume": safe_float(item[5]),
                    "time": item[0],
                })

    except Exception as exc:
        logger.warning("Kline parsing failed %s %s: %s",
                       symbol, interval, exc)

    if candles:
        _KLINE_CACHE[cache_key] = (now, candles)

    return candles


# =========================================================
# INDICATORS
# =========================================================

def calculate_ema(values, period):
    if not values:
        return 0.0

    if len(values) < period:
        return mean(values)

    multiplier = 2 / (period + 1)

    ema = mean(values[:period])

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calculate_rsi(closes, period=14):

    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = mean(gains[-period:])
    avg_loss = mean(losses[-period:])

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def calculate_atr(klines, period=14):

    if len(klines) < period + 1:
        return 0.0

    trs = []

    for i in range(1, len(klines)):

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

    return mean(trs[-period:])


def calculate_volume_ratio(klines, period=20):

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


def calculate_volume_trend(klines, lookback=8):

    if len(klines) < lookback * 2:
        return "NEUTRAL"

    recent = [
        x["volume"]
        for x in klines[-lookback:]
    ]

    previous = [
        x["volume"]
        for x in klines[-lookback * 2:-lookback]
    ]

    if not recent or not previous:
        return "NEUTRAL"

    r = mean(recent)
    p = mean(previous)

    if p <= 0:
        return "NEUTRAL"

    change = (r - p) / p * 100

    if change >= 15:
        return "RISING"

    if change <= -15:
        return "FALLING"

    return "NEUTRAL"


# =========================================================
# PRICE STRUCTURE
# =========================================================

def calculate_support_resistance(klines):

    if not klines:
        return 0.0, 0.0

    lookback = min(80, len(klines))

    recent = klines[-lookback:]

    support = min(x["low"] for x in recent)
    resistance = max(x["high"] for x in recent)

    return support, resistance


def price_position(price, support, resistance):

    if resistance <= support:
        return 50.0

    return clamp(
        ((price - support) / (resistance - support)) * 100,
        0,
        100,
    )


def recent_drawdown(klines, lookback=30):

    if len(klines) < 5:
        return 0.0

    data = klines[-lookback:]

    highest = max(x["high"] for x in data)
    current = data[-1]["close"]

    if highest <= 0:
        return 0.0

    return (current - highest) / highest * 100


def recent_rally(klines, lookback=30):

    if len(klines) < 5:
        return 0.0

    data = klines[-lookback:]

    lowest = min(x["low"] for x in data)
    current = data[-1]["close"]

    if lowest <= 0:
        return 0.0

    return (current - lowest) / lowest * 100


# =========================================================
# MARKET STRUCTURE
# =========================================================

def detect_market_structure(klines):

    if len(klines) < 20:
        return {
            "structure": "MIXED",
            "bos": "NONE",
            "bullish": False,
            "bearish": False,
        }

    recent = klines[-20:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    previous_high = max(highs[:-5])
    previous_low = min(lows[:-5])

    current_close = recent[-1]["close"]

    bullish_bos = current_close > previous_high
    bearish_bos = current_close < previous_low

    if bullish_bos:
        structure = "BULLISH"
        bos = "BULLISH"

    elif bearish_bos:
        structure = "BEARISH"
        bos = "BEARISH"

    else:
        structure = "MIXED"
        bos = "NONE"

    return {
        "structure": structure,
        "bos": bos,
        "bullish": bullish_bos,
        "bearish": bearish_bos,
    }


# =========================================================
# LIQUIDITY FLOW
# =========================================================

def detect_liquidity_flow(klines):

    if len(klines) < 20:
        return {
            "state": "NEUTRAL",
            "bullish_volume": 0.0,
            "bearish_volume": 0.0,
            "ratio": 1.0,
            "confidence": 0,
        }

    recent = klines[-20:]

    bullish_volume = 0.0
    bearish_volume = 0.0

    for candle in recent:

        o = candle["open"]
        c = candle["close"]
        v = candle["volume"]

        if c > o:
            bullish_volume += v

        elif c < o:
            bearish_volume += v

        else:
            bullish_volume += v * 0.5
            bearish_volume += v * 0.5

    if bearish_volume <= 0:
        ratio = 99.0
    else:
        ratio = bullish_volume / bearish_volume

    total = bullish_volume + bearish_volume

    confidence = 0

    if total > 0:
        imbalance = abs(
            bullish_volume - bearish_volume
        ) / total

        confidence = int(
            clamp(imbalance * 100, 0, 100)
        )

    # -----------------------------------------------------
    # IMPORTANT:
    # لا نعتمد على اتجاه السعر وحده.
    # -----------------------------------------------------

    if (
        bullish_volume > bearish_volume * 1.20
        and ratio >= 1.05
    ):
        state = "INFLOW"

    elif (
        bearish_volume > bullish_volume * 1.20
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

def detect_bottom_accumulation(klines):

    result = {
        "state": "NONE",
        "score": 0,
        "drawdown": 0.0,
        "range": 0.0,
        "reasons": [],
    }

    if len(klines) < 35:
        return result

    recent = klines[-30:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    highest = max(highs)
    lowest = min(lows)

    current = recent[-1]["close"]

    if highest <= 0:
        return result

    drawdown = (current - highest) / highest * 100

    if lowest > 0:
        recent_range = (
            (highest - lowest) / lowest * 100
        )
    else:
        recent_range = 999

    result["drawdown"] = drawdown
    result["range"] = recent_range

    volume_ratio = calculate_volume_ratio(klines)
    volume_trend = calculate_volume_trend(klines)

    flow = detect_liquidity_flow(klines)

    # -----------------------------------------------------
    # 1 - السعر هبط من القمة
    # -----------------------------------------------------

    if drawdown <= -5:
        result["score"] += 1
        result["reasons"].append(
            "هبوط سابق واضح"
        )

    # -----------------------------------------------------
    # 2 - بدأ يضيق في نطاق
    # -----------------------------------------------------

    if recent_range <= 15:
        result["score"] += 1
        result["reasons"].append(
            "نطاق سعري مضغوط"
        )

    # -----------------------------------------------------
    # 3 - السيولة تدخل
    # أهم فلتر
    # -----------------------------------------------------

    if flow["state"] == "INFLOW":
        result["score"] += 2
        result["reasons"].append(
            "دخول سيولة شرائية"
        )

    # -----------------------------------------------------
    # 4 - volume rising
    # -----------------------------------------------------

    if volume_ratio >= 1.05:
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
    # 5 - القاع لا يصنع قاعًا جديدًا
    # -----------------------------------------------------

    last_lows = [
        x["low"]
        for x in recent[-8:]
    ]

    if len(last_lows) >= 5:

        old_low = min(last_lows[:4])
        new_low = min(last_lows[4:])

        if new_low >= old_low * 0.995:
            result["score"] += 1
            result["reasons"].append(
                "القاع ثابت"
            )

    # -----------------------------------------------------
    # classification
    # -----------------------------------------------------

    if result["score"] >= 4:
        result["state"] = "STRONG_ACCUMULATION"

    elif result["score"] >= 3:
        result["state"] = "ACCUMULATION"

    elif result["score"] >= 2:
        result["state"] = "POSSIBLE_ACCUMULATION"

    return result


# =========================================================
# DISTRIBUTION
# =========================================================

def detect_distribution(klines):

    result = {
        "state": "NONE",
        "score": 0,
        "rally": 0.0,
        "range": 0.0,
        "reasons": [],
    }

    if len(klines) < 35:
        return result

    recent = klines[-30:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    highest = max(highs)
    lowest = min(lows)

    current = recent[-1]["close"]

    if lowest <= 0:
        return result

    rally = (current - lowest) / lowest * 100

    recent_range = (
        (highest - lowest) / lowest * 100
    )

    result["rally"] = rally
    result["range"] = recent_range

    flow = detect_liquidity_flow(klines)
    volume_ratio = calculate_volume_ratio(klines)
    volume_trend = calculate_volume_trend(klines)

    # صعود قوي سابق
    if rally >= 8:
        result["score"] += 1
        result["reasons"].append(
            "صعود سابق قوي"
        )

    # السعر قريب من القمة
    if highest > 0:

        distance_from_high = (
            highest - current
        ) / highest * 100

        if distance_from_high <= 4:
            result["score"] += 1
            result["reasons"].append(
                "السعر قريب من القمة"
            )

    # -----------------------------------------------------
    # أهم شيء:
    # خروج السيولة بعد الصعود
    # -----------------------------------------------------

    if flow["state"] == "OUTFLOW":
        result["score"] += 2
        result["reasons"].append(
            "خروج سيولة بيعية"
        )

    if volume_ratio >= 1.05:
        result["score"] += 1
        result["reasons"].append(
            "حجم مرتفع"
        )

    if volume_trend == "RISING":
        result["score"] += 1
        result["reasons"].append(
            "الحجم يتزايد"
        )

    if result["score"] >= 4:
        result["state"] = "STRONG_DISTRIBUTION"

    elif result["score"] >= 3:
        result["state"] = "DISTRIBUTION"

    elif result["score"] >= 2:
        result["state"] = "POSSIBLE_DISTRIBUTION"

    return result


# =========================================================
# TIMEFRAME TREND
# =========================================================

def calculate_timeframe_trend(klines):

    if len(klines) < 55:
        return "NEUTRAL"

    closes = [
        x["close"]
        for x in klines
    ]

    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

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
# REVERSAL DETECTOR
# =========================================================

def detect_reversal(klines):

    result = {
        "state": "NONE",
        "bull_score": 0,
        "bear_score": 0,
        "reasons": [],
    }

    if len(klines) < 30:
        return result

    structure = detect_market_structure(klines)
    flow = detect_liquidity_flow(klines)

    accumulation = detect_bottom_accumulation(klines)
    distribution = detect_distribution(klines)

    rsi = calculate_rsi(
        [x["close"] for x in klines]
    )

    drawdown = recent_drawdown(klines)
    rally = recent_rally(klines)

    # =====================================================
    # BULLISH REVERSAL
    # =====================================================

    if accumulation["state"] in (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    ):
        result["bull_score"] += 2
        result["reasons"].append(
            "Accumulation"
        )

    if flow["state"] == "INFLOW":
        result["bull_score"] += 2
        result["reasons"].append(
            "Liquidity Inflow"
        )

    if structure["bullish"]:
        result["bull_score"] += 2
        result["reasons"].append(
            "Bullish BOS"
        )

    if rsi <= 42:
        result["bull_score"] += 1
        result["reasons"].append(
            "RSI منخفض"
        )

    if drawdown <= -8:
        result["bull_score"] += 1
        result["reasons"].append(
            "هبوط سابق كبير"
        )

    # =====================================================
    # BEARISH REVERSAL
    # =====================================================

    if distribution["state"] in (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    ):
        result["bear_score"] += 2
        result["reasons"].append(
            "Distribution"
        )

    if flow["state"] == "OUTFLOW":
        result["bear_score"] += 2
        result["reasons"].append(
            "Liquidity Outflow"
        )

    if structure["bearish"]:
        result["bear_score"] += 2
        result["reasons"].append(
            "Bearish BOS"
        )

    if rsi >= 58:
        result["bear_score"] += 1
        result["reasons"].append(
            "RSI مرتفع"
        )

    if rally >= 10:
        result["bear_score"] += 1
        result["reasons"].append(
            "صعود سابق كبير"
        )

    # =====================================================
    # FINAL REVERSAL
    # =====================================================

    if (
        result["bull_score"] >= 4
        and result["bull_score"] >= result["bear_score"] + 2
    ):
        result["state"] = "BULLISH_REVERSAL"

    elif (
        result["bear_score"] >= 4
        and result["bear_score"] >= result["bull_score"] + 2
    ):
        result["state"] = "BEARISH_REVERSAL"

    return result


# =========================================================
# LATE PUMP FILTER
# =========================================================

def detect_late_pump(klines):

    if len(klines) < 30:
        return False

    rally = recent_rally(klines, 25)

    rsi = calculate_rsi(
        [x["close"] for x in klines]
    )

    volume_ratio = calculate_volume_ratio(klines)

    if rally >= 18 and rsi >= 68:
        return True

    if rally >= 25 and volume_ratio >= 1.5:
        return True

    return False


# =========================================================
# LATE DUMP FILTER
# =========================================================

def detect_late_dump(klines):

    if len(klines) < 30:
        return False

    drawdown = recent_drawdown(klines, 25)

    rsi = calculate_rsi(
        [x["close"] for x in klines]
    )

    if drawdown <= -18 and rsi <= 28:
        return True

    return False


# =========================================================
# SCORE ENGINE
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

    # =====================================================
    # LONG
    # =====================================================

    if trend_1d == "LONG":
        long_score += 10

    if trend_4h == "LONG":
        long_score += 15

    if trend_1h == "LONG":
        long_score += 15

    if flow == "INFLOW":
        long_score += 20

    if accumulation in (
        "ACCUMULATION",
        "STRONG_ACCUMULATION",
    ):
        long_score += 20

    if reversal == "BULLISH_REVERSAL":
        long_score += 15

    if late_dump:
        long_score += 5

    # =====================================================
    # SHORT
    # =====================================================

    if trend_1d == "SHORT":
        short_score += 10

    if trend_4h == "SHORT":
        short_score += 15

    if trend_1h == "SHORT":
        short_score += 15

    if flow == "OUTFLOW":
        short_score += 20

    if distribution in (
        "DISTRIBUTION",
        "STRONG_DISTRIBUTION",
    ):
        short_score += 20

    if reversal == "BEARISH_REVERSAL":
        short_score += 15

    if late_pump:
        short_score += 5

    # =====================================================
    # CRITICAL OVERRIDE
    #
    # السيولة + التجميع تمنع SHORT
    # السيولة الخارجة + التوزيع تمنع LONG
    # =====================================================

    if (
        flow == "INFLOW"
        and accumulation in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        )
    ):
        short_score = min(short_score, 35)

    if (
        flow == "OUTFLOW"
        and distribution in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        )
    ):
        long_score = min(long_score, 35)

    # انعكاس قوي له الأولوية
    if reversal == "BULLISH_REVERSAL":
        short_score = min(short_score, 40)

    if reversal == "BEARISH_REVERSAL":
        long_score = min(long_score, 40)

    return clamp(long_score, 0, 100), clamp(short_score, 0, 100)


# =========================================================
# SINGLE COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):

    symbol = normalize_symbol(symbol)

    try:

        tf_15m = get_klines(symbol, "15m", 100)
        tf_30m = get_klines(symbol, "30m", 100)
        tf_1h = get_klines(symbol, "1h", 120)
        tf_4h = get_klines(symbol, "4h", 120)
        tf_1d = get_klines(symbol, "1d", 100)

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
                "score": 0,
                "reason": "بيانات غير كافية",
            }

        # -------------------------------------------------
        # trends
        # -------------------------------------------------

        trend_1d = calculate_timeframe_trend(tf_1d)
        trend_4h = calculate_timeframe_trend(tf_4h)
        trend_1h = calculate_timeframe_trend(tf_1h)
        trend_30m = calculate_timeframe_trend(tf_30m)
        trend_15m = calculate_timeframe_trend(tf_15m)

        # -------------------------------------------------
        # Main 1H analysis
        # -------------------------------------------------

        flow_data = detect_liquidity_flow(tf_1h)

        accumulation = detect_bottom_accumulation(tf_1h)

        distribution = detect_distribution(tf_1h)

        structure = detect_market_structure(tf_1h)

        reversal = detect_reversal(tf_1h)

        late_pump = detect_late_pump(tf_1h)

        late_dump = detect_late_dump(tf_1h)

        # -------------------------------------------------
        # price
        # -------------------------------------------------

        price = tf_1h[-1]["close"]

        support, resistance = calculate_support_resistance(
            tf_1h
        )

        atr = calculate_atr(tf_1h)

        rsi_1h = calculate_rsi(
            [x["close"] for x in tf_1h]
        )

        rsi_15m = calculate_rsi(
            [x["close"] for x in tf_15m]
        )

        volume_ratio = calculate_volume_ratio(tf_1h)

        # -------------------------------------------------
        # score
        # -------------------------------------------------

        long_score, short_score = calculate_entry_score(
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

        # -------------------------------------------------
        # FINAL DIRECTION
        # -------------------------------------------------

        direction = "WAIT"
        state = "NO TRADE"

        # =================================================
        # HARD SAFETY:
        # =================================================

        # دخول سيولة + تجميع
        # ممنوع SHORT
        bullish_liquidity_setup = (
            flow_data["state"] == "INFLOW"
            and accumulation["state"] in (
                "ACCUMULATION",
                "STRONG_ACCUMULATION",
            )
        )

        # خروج سيولة + توزيع
        # ممنوع LONG
        bearish_liquidity_setup = (
            flow_data["state"] == "OUTFLOW"
            and distribution["state"] in (
                "DISTRIBUTION",
                "STRONG_DISTRIBUTION",
            )
        )

        # -------------------------------------------------
        # BULLISH
        # -------------------------------------------------

        if bullish_liquidity_setup:

            if (
                reversal["state"] == "BULLISH_REVERSAL"
                or structure["bullish"]
            ):
                direction = "LONG"
                state = "ENTRY READY"

            else:
                direction = "LONG WATCH"
                state = "REVERSAL WATCH"

        # -------------------------------------------------
        # BEARISH
        # -------------------------------------------------

        elif bearish_liquidity_setup:

            if (
                reversal["state"] == "BEARISH_REVERSAL"
                or structure["bearish"]
            ):
                direction = "SHORT"
                state = "ENTRY READY"

            else:
                direction = "SHORT WATCH"
                state = "REVERSAL WATCH"

        # -------------------------------------------------
        # Normal LONG
        # -------------------------------------------------

        elif (
            long_score >= 65
            and long_score > short_score + 10
            and not late_pump
        ):

            direction = "LONG"
            state = "ENTRY READY"

        # -------------------------------------------------
        # Normal SHORT
        # -------------------------------------------------

        elif (
            short_score >= 65
            and short_score > long_score + 10
            and not late_dump
        ):

            direction = "SHORT"
            state = "ENTRY READY"

        # -------------------------------------------------
        # Late pump protection
        # -------------------------------------------------

        if late_pump and direction == "LONG":

            direction = "LONG WATCH"
            state = "LATE PUMP - WAIT"

        # -------------------------------------------------
        # Late dump protection
        # -------------------------------------------------

        if late_dump and direction == "SHORT":

            direction = "SHORT WATCH"
            state = "LATE DUMP - WAIT"

        # -------------------------------------------------
        # Calculate trade levels
        # -------------------------------------------------

        entry = price

        if atr <= 0:
            atr = price * 0.01

        if direction in ("LONG", "LONG WATCH"):

            sl = min(
                support * 0.985 if support > 0 else price - atr * 1.5,
                price - atr * 1.2,
            )

            risk = max(
                price - sl,
                atr,
            )

            tp1 = price + risk * 1.2
            tp2 = price + risk * 2.0
            tp3 = price + risk * 3.0

        elif direction in ("SHORT", "SHORT WATCH"):

            sl = max(
                resistance * 1.015 if resistance > 0 else price + atr * 1.5,
                price + atr * 1.2,
            )

            risk = max(
                sl - price,
                atr,
            )

            tp1 = price - risk * 1.2
            tp2 = price - risk * 2.0
            tp3 = price - risk * 3.0

        else:

            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0
            tp3 = 0.0

        # -------------------------------------------------
        # Confidence
        # -------------------------------------------------

        score = max(
            long_score,
            short_score,
        )

        if direction in ("LONG", "SHORT"):
            confidence = int(
                clamp(score, 0, 100)
            )
        else:
            confidence = int(
                clamp(
                    max(long_score, short_score),
                    0,
                    100,
                )
            )

        # -------------------------------------------------
        # Reasons
        # -------------------------------------------------

        reasons = []

        if flow_data["state"] == "INFLOW":
            reasons.append("دخول سيولة")

        elif flow_data["state"] == "OUTFLOW":
            reasons.append("خروج سيولة")

        if accumulation["state"] in (
            "ACCUMULATION",
            "STRONG_ACCUMULATION",
        ):
            reasons.append("تجميع")

        if distribution["state"] in (
            "DISTRIBUTION",
            "STRONG_DISTRIBUTION",
        ):
            reasons.append("توزيع")

        if reversal["state"] == "BULLISH_REVERSAL":
            reasons.append("انعكاس صاعد")

        if reversal["state"] == "BEARISH_REVERSAL":
            reasons.append("انعكاس هابط")

        if structure["bos"] == "BULLISH":
            reasons.append("BOS صاعد")

        elif structure["bos"] == "BEARISH":
            reasons.append("BOS هابط")

        # -------------------------------------------------
        # Critical warning
        # -------------------------------------------------

        warning = ""

        if bullish_liquidity_setup:
            warning = (
                "⚠️ العملة هابطة سعرياً لكن السيولة تدخل "
                "مع وجود تجميع؛ لا يتم مطاردتها SHORT."
            )

        elif bearish_liquidity_setup:
            warning = (
                "⚠️ العملة صاعدة سعرياً لكن السيولة تخرج "
                "مع وجود توزيع؛ لا يتم مطاردتها LONG."
            )

        return {
            "symbol": symbol,

            "direction": direction,
            "state": state,

            "score": confidence,

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
            "volume_trend": calculate_volume_trend(tf_1h),

            "liquidity": flow_data["state"],
            "liquidity_confidence": flow_data["confidence"],

            "accumulation": accumulation["state"],
            "accumulation_score": accumulation["score"],

            "distribution": distribution["state"],
            "distribution_score": distribution["score"],

            "market_structure": structure["structure"],
            "bos": structure["bos"],

            "reversal": reversal["state"],
            "bull_reversal_score": reversal["bull_score"],
            "bear_reversal_score": reversal["bear_score"],

            "drawdown": recent_drawdown(tf_1h),
            "rally": recent_rally(tf_1h),

            "support": support,
            "resistance": resistance,

            "late_pump": late_pump,
            "late_dump": late_dump,

            "reasons": reasons,
            "warning": warning,

            "analysis_ok": True,
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
# MARKET SCANNER
# =========================================================

def scan_market(limit=5):

    symbols = get_futures_symbols()

    if not symbols:
        return []

    candidates = []

    # -----------------------------------------------------
    # لا نفحص كل السوق بنفس العمق.
    # نعمل فلترة سريعة أولاً.
    # -----------------------------------------------------

    for symbol in symbols:

        try:

            klines = get_klines(
                symbol,
                "1h",
                45,
            )

            if len(klines) < 30:
                continue

            current = klines[-1]["close"]

            if current <= 0:
                continue

            drawdown = recent_drawdown(
                klines,
                30,
            )

            rally = recent_rally(
                klines,
                30,
            )

            volume_ratio = calculate_volume_ratio(
                klines
            )

            flow = detect_liquidity_flow(
                klines
            )

            accumulation = detect_bottom_accumulation(
                klines
            )

            distribution = detect_distribution(
                klines
            )

            # -------------------------------------------------
            # الأولوية ليست لأكبر هبوط أو أكبر صعود.
            # الأولوية للـsetup.
            # -------------------------------------------------

            priority = 0

            if flow["state"] == "INFLOW":
                priority += 30

            if flow["state"] == "OUTFLOW":
                priority += 30

            if accumulation["state"] == "STRONG_ACCUMULATION":
                priority += 35

            elif accumulation["state"] == "ACCUMULATION":
                priority += 25

            if distribution["state"] == "STRONG_DISTRIBUTION":
                priority += 35

            elif distribution["state"] == "DISTRIBUTION":
                priority += 25

            # الهبوط وحده لا يعطي أولوية كبيرة
            if drawdown <= -10:
                priority += 5

            # الصعود وحده لا يعطي أولوية كبيرة
            if rally >= 10:
                priority += 5

            if volume_ratio >= 1.15:
                priority += 10

            candidates.append({
                "symbol": symbol,
                "priority": priority,
                "drawdown": drawdown,
                "rally": rally,
            })

        except Exception:
            continue

    # -----------------------------------------------------
    # أفضل setups وليس أعلى الرابحين/الخاسرين فقط
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: x["priority"],
        reverse=True,
    )

    # -----------------------------------------------------
    # تحليل أعمق لأفضل المرشحين
    # -----------------------------------------------------

    results = []

    max_deep_scan = min(
        max(limit * 4, 15),
        len(candidates),
    )

    for item in candidates[:max_deep_scan]:

        result = get_coin_analysis(
            item["symbol"]
        )

        if not result.get("analysis_ok"):
            continue

        result["scan_priority"] = item["priority"]

        results.append(result)

    # -----------------------------------------------------
    # ترتيب نهائي
    #
    # ENTRY READY أولاً
    # ثم REVERSAL WATCH
    # ثم باقي الحالات
    # -----------------------------------------------------

    state_rank = {
        "ENTRY READY": 5,
        "REVERSAL WATCH": 4,
        "LATE PUMP - WAIT": 2,
        "LATE DUMP - WAIT": 2,
        "NO TRADE": 1,
    }

    results.sort(
        key=lambda x: (
            state_rank.get(
                x.get("state", ""),
                0,
            ),
            x.get("score", 0),
            x.get("scan_priority", 0),
        ),
        reverse=True,
    )

    return results[:limit]


# =========================================================
# EVIDENCE REPORT
# =========================================================

def generate_evidence_report(result):

    if not result:
        return "لا توجد بيانات تحليل."

    symbol = result.get("symbol", "UNKNOWN")

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

    long_score = result.get(
        "long_score",
        0,
    )

    short_score = result.get(
        "short_score",
        0,
    )

    liquidity = result.get(
        "liquidity",
        "NEUTRAL",
    )

    accumulation = result.get(
        "accumulation",
        "NONE",
    )

    distribution = result.get(
        "distribution",
        "NONE",
    )

    reversal = result.get(
        "reversal",
        "NONE",
    )

    bos = result.get(
        "bos",
        "NONE",
    )

    rsi = result.get(
        "rsi_1h",
        50,
    )

    volume_ratio = result.get(
        "volume_ratio",
        1,
    )

    reasons = result.get(
        "reasons",
        [],
    )

    warning = result.get(
        "warning",
        "",
    )

    lines = []

    lines.append(
        f"🤖 BingX AI Scanner"
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
        f"📌 الاتجاه النهائي: {direction_text}"
    )

    lines.append(
        f"⭐ Score: {score}/100"
    )

    lines.append(
        f"🧠 الحالة: {state}"
    )

    lines.append("")

    lines.append("📊 الاتجاهات:")

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

    lines.append("💧 السيولة:")

    if liquidity == "INFLOW":
        liquidity_text = "🟢 INFLOW — دخول سيولة"

    elif liquidity == "OUTFLOW":
        liquidity_text = "🔴 OUTFLOW — خروج سيولة"

    else:
        liquidity_text = "🟡 NEUTRAL"

    lines.append(liquidity_text)

    lines.append(
        f"Volume Ratio: {volume_ratio:.2f}x"
    )

    lines.append("")

    lines.append("🏦 حالة السوق:")

    lines.append(
        f"Accumulation: {accumulation}"
    )

    lines.append(
        f"Distribution: {distribution}"
    )

    lines.append(
        f"Reversal: {reversal}"
    )

    lines.append(
        f"BOS: {bos}"
    )

    lines.append("")

    lines.append("📈 المؤشرات:")

    lines.append(
        f"RSI 1H: {rsi:.1f}"
    )

    lines.append(
        f"LONG Score: {long_score}"
    )

    lines.append(
        f"SHORT Score: {short_score}"
    )

    lines.append("")

    lines.append("🎯 المستويات:")

    lines.append(
        f"Entry: {price:.8g}"
    )

    if result.get("sl"):
        lines.append(
            f"🛑 SL: {result['sl']:.8g}"
        )

        lines.append(
            f"🎯 TP1: {result['tp1']:.8g}"
        )

        lines.append(
            f"🎯 TP2: {result['tp2']:.8g}"
        )

        lines.append(
            f"🎯 TP3: {result['tp3']:.8g}"
        )

    lines.append("")

    if reasons:

        lines.append("🧠 أسباب التحليل:")

        for reason in reasons[:8]:
            lines.append(
                f"• {reason}"
            )

    if warning:

        lines.append("")
        lines.append(warning)

    return "\n".join(lines)


# =========================================================
# OPTIONAL QUICK SCAN TEXT
# =========================================================

def format_scan_results(results):

    if not results:
        return (
            "🟡 انتهى الفحص.\n\n"
            "لم يتم العثور حالياً على setup قوي."
        )

    lines = [
        "🤖 BingX AI Scanner",
        "",
        "🔎 أفضل الفرص الحالية:",
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

        score = result.get(
            "score",
            0,
        )

        state = result.get(
            "state",
            "NO TRADE",
        )

        liquidity = result.get(
            "liquidity",
            "NEUTRAL",
        )

        if direction in (
            "LONG",
            "LONG WATCH",
        ):
            icon = "🟢"

        elif direction in (
            "SHORT",
            "SHORT WATCH",
        ):
            icon = "🔴"

        else:
            icon = "⚪"

        lines.append(
            f"{index}. {icon} {symbol}"
        )

        lines.append(
            f"   {direction} | "
            f"{state} | "
            f"Score {score}"
        )

        lines.append(
            f"   💧 Liquidity: {liquidity}"
        )

        lines.append("")

    return "\n".join(lines)


# =========================================================
# END
# =========================================================
