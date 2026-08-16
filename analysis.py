import time
from decimal import Decimal
from typing import Dict, List, Optional

import requests


BINANCE_BASE_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Binance-Technical-Scanner/1.0",
    "Accept": "application/json",
})


# ============================================================
# Binance API
# ============================================================

def binance_get(endpoint: str, params: Optional[dict] = None):
    url = BINANCE_BASE_URL + endpoint

    response = SESSION.get(
        url,
        params=params or {},
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and data.get("code"):
        raise RuntimeError(
            f"Binance API error: {data.get('code')} - {data.get('msg')}"
        )

    return data


def get_usdt_symbols() -> List[str]:
    """
    جلب جميع أزواج USDT المتاحة على Binance Spot.
    """

    data = binance_get("/api/v3/exchangeInfo")

    symbols = []

    for item in data.get("symbols", []):

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is False:
            continue

        symbol = item.get("symbol")

        if symbol:
            symbols.append(symbol)

    return symbols


def get_klines(symbol: str, interval: str = "1h", limit: int = 250):
    """
    جلب الشموع الحقيقية من Binance.
    """

    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    candles = []

    for row in data:

        candles.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })

    return candles


def get_current_price(symbol: str) -> Decimal:
    """
    السعر الفوري من Binance Spot.
    """

    data = binance_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return Decimal(str(data["price"]))


# ============================================================
# Indicators
# ============================================================

def sma(values: List[float], period: int) -> List[Optional[float]]:

    result = [None] * len(values)

    if len(values) < period:
        return result

    for i in range(period - 1, len(values)):

        window = values[i - period + 1:i + 1]

        result[i] = sum(window) / period

    return result


def ema(values: List[float], period: int) -> List[Optional[float]]:

    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)

    first = sum(values[:period]) / period

    result[period - 1] = first

    previous = first

    for i in range(period, len(values)):

        current = (
            (values[i] - previous) * multiplier
            + previous
        )

        result[i] = current
        previous = current

    return result


def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:

    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

        if avg_loss == 0:
            result[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))

    return result


def macd(values: List[float]):
    """
    MACD 12/26/9
    """

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)

    line = [None] * len(values)

    for i in range(len(values)):

        if ema12[i] is not None and ema26[i] is not None:
            line[i] = ema12[i] - ema26[i]

    valid_macd = [
        x for x in line if x is not None
    ]

    signal_values = ema(valid_macd, 9)

    signal = [None] * len(values)

    start_index = len(values) - len(valid_macd)

    for i, value in enumerate(signal_values):

        if value is not None:
            signal[start_index + i] = value

    return line, signal


def atr(
    candles: List[dict],
    period: int = 14
) -> List[Optional[float]]:

    if not candles:
        return []

    true_ranges = [None]

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        true_ranges.append(tr)

    result = [None] * len(candles)

    valid = [
        x for x in true_ranges
        if x is not None
    ]

    if len(valid) < period:
        return result

    first_atr = sum(valid[:period]) / period

    result[period] = first_atr

    previous = first_atr

    for i in range(period, len(valid)):

        current = (
            (previous * (period - 1))
            + valid[i]
        ) / period

        result[i + 1] = current
        previous = current

    return result


# ============================================================
# Market structure
# ============================================================

def recent_support(candles: List[dict], lookback: int = 40):

    data = candles[-lookback:]

    return min(
        candle["low"]
        for candle in data
    )


def recent_resistance(candles: List[dict], lookback: int = 40):

    data = candles[-lookback:]

    return max(
        candle["high"]
        for candle in data
    )


def detect_higher_highs_lows(candles: List[dict]) -> bool:

    if len(candles) < 30:
        return False

    recent = candles[-30:]

    first_half = recent[:15]
    second_half = recent[15:]

    high1 = max(x["high"] for x in first_half)
    high2 = max(x["high"] for x in second_half)

    low1 = min(x["low"] for x in first_half)
    low2 = min(x["low"] for x in second_half)

    return high2 > high1 and low2 > low1


def detect_lower_highs_lows(candles: List[dict]) -> bool:

    if len(candles) < 30:
        return False

    recent = candles[-30:]

    first_half = recent[:15]
    second_half = recent[15:]

    high1 = max(x["high"] for x in first_half)
    high2 = max(x["high"] for x in second_half)

    low1 = min(x["low"] for x in first_half)
    low2 = min(x["low"] for x in second_half)

    return high2 < high1 and low2 < low1


# ============================================================
# Volume
# ============================================================

def volume_ratio(candles: List[dict], period: int = 20):

    if len(candles) < period + 1:
        return 0

    current_volume = candles[-1]["volume"]

    previous = [
        c["volume"]
        for c in candles[-period - 1:-1]
    ]

    average = sum(previous) / len(previous)

    if average == 0:
        return 0

    return current_volume / average


# ============================================================
# Analyze one symbol
# ============================================================

def analyze_symbol(symbol: str) -> Optional[Dict]:

    try:

        candles_1h = get_klines(
            symbol,
            "1h",
            250
        )

        candles_4h = get_klines(
            symbol,
            "4h",
            250
        )

    except Exception:
        return None

    if len(candles_1h) < 100:
        return None

    closes = [
        c["close"]
        for c in candles_1h
    ]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi_values = rsi(closes, 14)

    macd_line, signal_line = macd(closes)

    atr_values = atr(candles_1h, 14)

    price = closes[-1]

    e20 = ema20[-1]
    e50 = ema50[-1]
    e200 = ema200[-1]

    current_rsi = rsi_values[-1]

    current_macd = macd_line[-1]
    current_signal = signal_line[-1]

    current_atr = atr_values[-1]

    if None in (
        e20,
        e50,
        e200,
        current_rsi,
        current_macd,
        current_signal,
        current_atr
    ):
        return None

    support = recent_support(
        candles_1h,
        40
    )

    resistance = recent_resistance(
        candles_1h,
        40
    )

    vol_ratio = volume_ratio(
        candles_1h,
        20
    )

    bullish_structure = detect_higher_highs_lows(
        candles_1h
    )

    bearish_structure = detect_lower_highs_lows(
        candles_1h
    )

    # ========================================================
    # LONG SCORE
    # ========================================================

    long_score = 0
    long_reasons = []

    if price > e20:
        long_score += 10
        long_reasons.append("السعر فوق EMA20")

    if e20 > e50:
        long_score += 10
        long_reasons.append("EMA20 فوق EMA50")

    if e50 > e200:
        long_score += 10
        long_reasons.append("EMA50 فوق EMA200")

    if 50 <= current_rsi <= 68:
        long_score += 10
        long_reasons.append("RSI داعم للونج")

    if current_macd > current_signal:
        long_score += 10
        long_reasons.append("MACD إيجابي")

    if bullish_structure:
        long_score += 15
        long_reasons.append("هيكل قمم وقيعان صاعد")

    if vol_ratio >= 1.20:
        long_score += 10
        long_reasons.append("حجم تداول مرتفع")

    # ========================================================
    # SHORT SCORE
    # ========================================================

    short_score = 0
    short_reasons = []

    if price < e20:
        short_score += 10
        short_reasons.append("السعر تحت EMA20")

    if e20 < e50:
        short_score += 10
        short_reasons.append("EMA20 تحت EMA50")

    if e50 < e200:
        short_score += 10
        short_reasons.append("EMA50 تحت EMA200")

    if 32 <= current_rsi <= 50:
        short_score += 10
        short_reasons.append("RSI داعم للشورت")

    if current_macd < current_signal:
        short_score += 10
        short_reasons.append("MACD سلبي")

    if bearish_structure:
        short_score += 15
        short_reasons.append("هيكل قمم وقيعان هابط")

    if vol_ratio >= 1.20:
        short_score += 10
        short_reasons.append("حجم تداول مرتفع")

    # ========================================================
    # اختيار الاتجاه
    # ========================================================

    if long_score >= short_score:
        direction = "LONG"
        score = long_score
        reasons = long_reasons
    else:
        direction = "SHORT"
        score = short_score
        reasons = short_reasons

    # ========================================================
    # فلتر قوي
    # ========================================================

    if score < 55:
        return None

    # لا نريد الدخول إذا كان السعر قريباً جداً من المقاومة
    if direction == "LONG":

        distance_to_resistance = (
            resistance - price
        ) / price

        if distance_to_resistance < 0.012:
            return None

    else:

        distance_to_support = (
            price - support
        ) / price

        if distance_to_support < 0.012:
            return None

    # ========================================================
    # Entry / SL / TP
    # ========================================================

    if direction == "LONG":

        entry_low = max(
            support,
            price - current_atr * 0.35
        )

        entry_high = price

        stop = min(
            support - current_atr * 0.25,
            price - current_atr * 1.25
        )

        risk = price - stop

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 3.5

    else:

        entry_high = min(
            resistance,
            price + current_atr * 0.35
        )

        entry_low = price

        stop = max(
            resistance + current_atr * 0.25,
            price + current_atr * 1.25
        )

        risk = stop - price

        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 3.5

    if risk <= 0:
        return None

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": current_rsi,
        "volume_ratio": vol_ratio,
        "support": support,
        "resistance": resistance,
        "atr": current_atr,
        "reasons": reasons,
    }


# ============================================================
# Scan market
# ============================================================

def scan_market(
    max_symbols: Optional[int] = None
) -> List[Dict]:

    symbols = get_usdt_symbols()

    # استبعاد بعض أزواج العملات غير المرغوبة
    excluded = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "USDTUSDT",
        "DAIUSDT",
        "EURUSDT",
        "TRYUSDT",
        "BRLUSDT",
        "GBPUSDT",
        "AUDUSDT",
    }

    symbols = [
        s for s in symbols
        if s not in excluded
    ]

    if max_symbols:
        symbols = symbols[:max_symbols]

    results = []

    for index, symbol in enumerate(symbols):

        result = analyze_symbol(symbol)

        if result:
            results.append(result)

        # حماية بسيطة من الضغط على API
        if index % 10 == 0:
            time.sleep(0.05)

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# ============================================================
# Helpers
# ============================================================

def format_number(value: float) -> str:

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")

    if value >= 0.01:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    if value >= 0.0001:
        return f"{value:.8f}".rstrip("0").rstrip(".")

    return f"{value:.10f}".rstrip("0").rstrip(".")
