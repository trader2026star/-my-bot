import requests
import time
import math
from statistics import mean

# =========================================================
# BINANCE CONFIG
# =========================================================

BINANCE_URL = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})

REQUEST_TIMEOUT = 15


# =========================================================
# HTTP
# =========================================================

def binance_get(endpoint, params=None):
    try:
        url = BINANCE_URL + endpoint

        r = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        r.raise_for_status()

        return r.json()

    except Exception as e:
        print("Binance API error:", e)
        return None


# =========================================================
# SYMBOLS
# =========================================================

def get_usdt_symbols():
    """
    Get active USDT perpetual futures symbols.
    """

    data = binance_get("/fapi/v1/exchangeInfo")

    if not data:
        return []

    symbols = []

    for item in data.get("symbols", []):

        if (
            item.get("quoteAsset") == "USDT"
            and item.get("contractType") == "PERPETUAL"
            and item.get("status") == "TRADING"
        ):
            symbols.append(item["symbol"])

    return symbols


# =========================================================
# 24H MARKET DATA
# =========================================================

def get_24h_tickers():

    data = binance_get("/fapi/v1/ticker/24hr")

    if not data:
        return []

    result = []

    for x in data:

        symbol = x.get("symbol")

        if not symbol or not symbol.endswith("USDT"):
            continue

        try:
            result.append({
                "symbol": symbol,
                "price": float(x["lastPrice"]),
                "quote_volume": float(x["quoteVolume"]),
                "change": float(x["priceChangePercent"]),
                "high": float(x["highPrice"]),
                "low": float(x["lowPrice"])
            })

        except Exception:
            continue

    return result


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval="15m", limit=150):

    data = binance_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    candles = []

    for x in data:

        try:
            candles.append({
                "open_time": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
                "close_time": int(x[6]),
                "quote_volume": float(x[7])
            })

        except Exception:
            continue

    return candles


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

    return ema_value


# =========================================================
# RSI
# =========================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])

    for i in range(period, len(gains)):

        avg_gain = (
            ((avg_gain * (period - 1)) + gains[i])
            / period
        )

        avg_loss = (
            ((avg_loss * (period - 1)) + losses[i])
            / period
        )

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================================================
# ATR
# =========================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    return mean(trs[-period:])


# =========================================================
# PRICE CHANGE
# =========================================================

def percentage_change(old, new):

    if old == 0:
        return 0

    return ((new - old) / old) * 100


# =========================================================
# RANGE / CONSOLIDATION
# =========================================================

def calculate_range(candles):

    if not candles:
        return None

    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]

    highest = max(highs)
    lowest = min(lows)

    if lowest == 0:
        return None

    return ((highest - lowest) / lowest) * 100


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_levels(candles):

    recent = candles[-40:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    resistance = max(highs)
    support = min(lows)

    return support, resistance


# =========================================================
# VOLUME ANALYSIS
# =========================================================

def volume_analysis(candles):

    if len(candles) < 40:
        return None

    current_volume = candles[-1]["volume"]

    previous_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    average_volume = mean(previous_volumes)

    if average_volume <= 0:
        return None

    ratio = current_volume / average_volume

    recent_5 = mean(
        x["volume"]
        for x in candles[-5:]
    )

    previous_20 = mean(
        x["volume"]
        for x in candles[-25:-5]
    )

    if previous_20 > 0:
        liquidity_growth = (
            (recent_5 / previous_20) - 1
        ) * 100
    else:
        liquidity_growth = 0

    return {
        "current": current_volume,
        "average": average_volume,
        "ratio": ratio,
        "growth": liquidity_growth
    }


# =========================================================
# PUMP FILTER
# =========================================================

def already_pumped(candles):

    if len(candles) < 25:
        return False

    current = candles[-1]["close"]

    price_1h = candles[-5]["close"]
    price_4h = candles[-17]["close"]

    change_1h = percentage_change(
        price_1h,
        current
    )

    change_4h = percentage_change(
        price_4h,
        current
    )

    # Do not chase a coin that already exploded.
    if change_1h >= 8:
        return True

    if change_4h >= 15:
        return True

    return False


# =========================================================
# ACCUMULATION DETECTION
# =========================================================

def detect_accumulation(candles):

    if len(candles) < 60:
        return {
            "score": 0,
            "signals": []
        }

    closes = [x["close"] for x in candles]

    recent = candles[-24:]

    range_percent = calculate_range(recent)

    volume = volume_analysis(candles)

    if volume is None:
        return {
            "score": 0,
            "signals": []
        }

    score = 0
    signals = []

    # Tight range = possible accumulation
    if range_percent <= 5:
        score += 20
        signals.append("نطاق سعري ضيق")

    elif range_percent <= 8:
        score += 10
        signals.append("تجميع متوسط")

    # Volume increasing without huge price explosion
    if volume["ratio"] >= 1.20:
        score += 15
        signals.append("ارتفاع الحجم")

    if volume["growth"] >= 15:
        score += 15
        signals.append("السيولة تتحسن")

    # Higher lows
    lows_1 = min(
        x["low"]
        for x in candles[-20:-10]
    )

    lows_2 = min(
        x["low"]
        for x in candles[-10:]
    )

    if lows_2 > lows_1:
        score += 15
        signals.append("Higher Low")

    # Price close to resistance
    support, resistance = calculate_levels(candles)

    current = closes[-1]

    distance_to_resistance = (
        (resistance - current) / current
    ) * 100

    if 0 < distance_to_resistance <= 3:
        score += 15
        signals.append("قرب المقاومة")

    # EMA structure
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    if ema20 and ema50 and ema20 >= ema50:
        score += 10
        signals.append("EMA إيجابي")

    # Avoid already pumped coins
    if already_pumped(candles):
        score -= 35
        signals.append("⚠️ العملة انفجرت بالفعل")

    score = max(0, min(100, score))

    return {
        "score": score,
        "signals": signals
    }


# =========================================================
# LONG ANALYSIS
# =========================================================

def analyze_long(candles):

    closes = [x["close"] for x in candles]

    current = closes[-1]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    rsi = calculate_rsi(closes)

    atr = calculate_atr(candles)

    volume = volume_analysis(candles)

    support, resistance = calculate_levels(candles)

    score = 0
    signals = []

    if ema20 and current > ema20:
        score += 15
        signals.append("السعر فوق EMA20")

    if ema20 and ema50 and ema20 > ema50:
        score += 20
        signals.append("EMA20 > EMA50")

    if rsi and 50 <= rsi <= 68:
        score += 15
        signals.append("RSI مناسب للصعود")

    if volume:

        if volume["ratio"] >= 1.15:
            score += 15
            signals.append("حجم مرتفع")

        if volume["growth"] >= 10:
            score += 10
            signals.append("السيولة في تحسن")

    # Higher lows
    if candles[-1]["low"] > candles[-10]["low"]:
        score += 10
        signals.append("Higher Low")

    # Breakout proximity
    distance = (
        (resistance - current) / current
    ) * 100

    if 0 <= distance <= 2.5:
        score += 15
        signals.append("قريب من الاختراق")

    return {
        "score": max(0, min(100, score)),
        "signals": signals,
        "price": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "support": support,
        "resistance": resistance
    }


# =========================================================
# SHORT ANALYSIS
# =========================================================

def analyze_short(candles):

    closes = [x["close"] for x in candles]

    current = closes[-1]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    rsi = calculate_rsi(closes)

    atr = calculate_atr(candles)

    volume = volume_analysis(candles)

    support, resistance = calculate_levels(candles)

    score = 0
    signals = []

    if ema20 and current < ema20:
        score += 20
        signals.append("السعر تحت EMA20")

    if ema20 and ema50 and ema20 < ema50:
        score += 20
        signals.append("EMA20 < EMA50")

    if rsi and 32 <= rsi <= 50:
        score += 15
        signals.append("RSI يدعم الهبوط")

    if volume:

        if volume["ratio"] >= 1.15:
            score += 15
            signals.append("حجم مرتفع")

        if volume["growth"] >= 10:
            score += 10
            signals.append("السيولة مرتفعة")

    # Lower High
    if candles[-1]["high"] < candles[-10]["high"]:
        score += 10
        signals.append("Lower High")

    # Near support
    distance = (
        (current - support) / current
    ) * 100

    if 0 <= distance <= 2.5:
        score += 10
        signals.append("قريب من كسر الدعم")

    return {
        "score": max(0, min(100, score)),
        "signals": signals,
        "price": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "support": support,
        "resistance": resistance
    }


# =========================================================
# FULL ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = symbol.upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    candles_15m = get_klines(
        symbol,
        "15m",
        150
    )

    candles_1h = get_klines(
        symbol,
        "1h",
        100
    )

    if len(candles_15m) < 60:
        return None

    long_result = analyze_long(
        candles_15m
    )

    short_result = analyze_short(
        candles_15m
    )

    accumulation = detect_accumulation(
        candles_15m
    )

    current = candles_15m[-1]["close"]

    # 1H trend confirmation
    trend_1h = "NEUTRAL"

    if len(candles_1h) >= 50:

        closes_1h = [
            x["close"]
            for x in candles_1h
        ]

        ema20_1h = calculate_ema(
            closes_1h,
            20
        )

        ema50_1h = calculate_ema(
            closes_1h,
            50
        )

        if (
            ema20_1h
            and ema50_1h
            and ema20_1h > ema50_1h
        ):
            trend_1h = "UP"

        elif (
            ema20_1h
            and ema50_1h
            and ema20_1h < ema50_1h
        ):
            trend_1h = "DOWN"

    # Final classification
    long_score = long_result["score"]
    short_score = short_result["score"]

    if accumulation["score"] >= 65:
        status = "PRE_PUMP"

    elif long_score >= 70:
        status = "LONG"

    elif short_score >= 70:
        status = "SHORT"

    else:
        status = "WAIT"

    return {
        "symbol": symbol,
        "price": current,
        "status": status,
        "long": long_result,
        "short": short_result,
        "accumulation": accumulation,
        "trend_1h": trend_1h
    }


# =========================================================
# SCANNER
# =========================================================

def scan_market(mode="all", max_symbols=80):

    tickers = get_24h_tickers()

    if not tickers:
        return []

    # Remove extremely low liquidity coins
    tickers = [
        x for x in tickers
        if x["quote_volume"] >= 5_000_000
    ]

    # Sort by 24h quote volume
    tickers.sort(
        key=lambda x: x["quote_volume"],
        reverse=True
    )

    # Analyze highest liquidity candidates first
    candidates = tickers[:max_symbols]

    results = []

    for item in candidates:

        symbol = item["symbol"]

        try:

            result = analyze_symbol(symbol)

            if not result:
                continue

            if mode == "long":

                score = max(
                    result["long"]["score"],
                    result["accumulation"]["score"]
                )

                if score < 55:
                    continue

            elif mode == "short":

                if result["short"]["score"] < 55:
                    continue

            else:

                best = max(
                    result["long"]["score"],
                    result["short"]["score"],
                    result["accumulation"]["score"]
                )

                if best < 55:
                    continue

            result["volume_24h"] = item["quote_volume"]

            result["change_24h"] = item["change"]

            results.append(result)

            # Small delay to avoid API pressure
            time.sleep(0.08)

        except Exception as e:
            print(
                "Scan error",
                symbol,
                e
            )

    def ranking(x):

        return max(
            x["long"]["score"],
            x["short"]["score"],
            x["accumulation"]["score"]
        )

    results.sort(
        key=ranking,
        reverse=True
    )

    return results[:15]


# =========================================================
# TRADE PREPARATION
# =========================================================

def prepare_trade(symbol):

    result = analyze_symbol(symbol)

    if not result:
        return None

    price = result["price"]

    long_data = result["long"]
    short_data = result["short"]

    accumulation_score = result[
        "accumulation"
    ]["score"]

    # =====================================================
    # LONG
    # =====================================================

    if (
        long_data["score"] >= 70
        and long_data["score"] > short_data["score"]
    ):

        atr = long_data["atr"]

        if not atr:
            return None

        # Entry around current market
        entry = price

        stop = entry - (
            atr * 1.5
        )

        risk = entry - stop

        tp1 = entry + risk
        tp2 = entry + (risk * 2)
        tp3 = entry + (risk * 3)

        return {
            "symbol": symbol.upper(),
            "direction": "LONG",
            "status": result["status"],
            "score": long_data["score"],
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rsi": long_data["rsi"],
            "support": long_data["support"],
            "resistance": long_data["resistance"],
            "trend_1h": result["trend_1h"],
            "accumulation": accumulation_score,
            "signals": long_data["signals"]
        }

    # =====================================================
    # SHORT
    # =====================================================

    if (
        short_data["score"] >= 70
        and short_data["score"] > long_data["score"]
    ):

        atr = short_data["atr"]

        if not atr:
            return None

        entry = price

        stop = entry + (
            atr * 1.5
        )

        risk = stop - entry

        tp1 = entry - risk
        tp2 = entry - (risk * 2)
        tp3 = entry - (risk * 3)

        return {
            "symbol": symbol.upper(),
            "direction": "SHORT",
            "status": result["status"],
            "score": short_data["score"],
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rsi": short_data["rsi"],
            "support": short_data["support"],
            "resistance": short_data["resistance"],
            "trend_1h": result["trend_1h"],
            "accumulation": accumulation_score,
            "signals": short_data["signals"]
        }

    # =====================================================
    # PRE-PUMP WATCH
    # =====================================================

    if accumulation_score >= 65:

        return {
            "symbol": symbol.upper(),
            "direction": "WATCH",
            "status": "PRE_PUMP",
            "score": accumulation_score,
            "entry": price,
            "stop": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "rsi": long_data["rsi"],
            "support": long_data["support"],
            "resistance": long_data["resistance"],
            "trend_1h": result["trend_1h"],
            "accumulation": accumulation_score,
            "signals": result["accumulation"]["signals"]
        }

    return {
        "symbol": symbol.upper(),
        "direction": "WAIT",
        "status": "WAIT",
        "score": max(
            long_data["score"],
            short_data["score"]
        ),
        "entry": price,
        "stop": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "rsi": long_data["rsi"],
        "support": long_data["support"],
        "resistance": long_data["resistance"],
        "trend_1h": result["trend_1h"],
        "accumulation": accumulation_score,
        "signals": []
    }


# =========================================================
# FORMAT PRICE
# =========================================================

def format_number(value):

    if value is None:
        return "-"

    value = float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    if value >= 0.0001:
        return f"{value:.8f}"

    return f"{value:.10f}"
