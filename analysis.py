import time
from decimal import Decimal
from typing import Dict, List, Optional

import requests


BINANCE_BASE_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Binance-AI-Scanner/2.0",
    "Accept": "application/json",
})


# ============================================================
# BINANCE API
# ============================================================

def binance_get(endpoint: str, params: Optional[dict] = None):

    response = SESSION.get(
        BINANCE_BASE_URL + endpoint,
        params=params or {},
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and data.get("code"):
        raise RuntimeError(
            f"Binance API error {data.get('code')}: {data.get('msg')}"
        )

    return data


def get_usdt_symbols() -> List[str]:

    data = binance_get("/api/v3/exchangeInfo")

    excluded = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "DAIUSDT",
        "EURUSDT",
        "TRYUSDT",
        "BRLUSDT",
        "GBPUSDT",
        "AUDUSDT",
        "USDPUSDT",
    }

    symbols = []

    for item in data.get("symbols", []):

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is False:
            continue

        symbol = item.get("symbol")

        if symbol and symbol not in excluded:
            symbols.append(symbol)

    return symbols


def get_current_price(symbol: str) -> Decimal:

    data = binance_get(
        "/api/v3/ticker/price",
        {"symbol": symbol},
    )

    return Decimal(str(data["price"]))


def get_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 250,
):

    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
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


# ============================================================
# INDICATORS
# ============================================================

def ema(
    values: List[float],
    period: int,
) -> List[Optional[float]]:

    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)

    previous = sum(values[:period]) / period

    result[period - 1] = previous

    for i in range(period, len(values)):

        previous = (
            (values[i] - previous) * multiplier
            + previous
        )

        result[i] = previous

    return result


def rsi(
    values: List[float],
    period: int = 14,
) -> List[Optional[float]]:

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
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

        if avg_loss == 0:
            result[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))

    return result


def macd(values: List[float]):

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)

    line = [None] * len(values)

    for i in range(len(values)):

        if (
            ema12[i] is not None
            and ema26[i] is not None
        ):
            line[i] = ema12[i] - ema26[i]

    valid = [
        x for x in line
        if x is not None
    ]

    signal_valid = ema(valid, 9)

    signal = [None] * len(values)

    start = len(values) - len(valid)

    for i, value in enumerate(signal_valid):

        if value is not None:
            signal[start + i] = value

    return line, signal


def atr(
    candles: List[dict],
    period: int = 14,
) -> List[Optional[float]]:

    result = [None] * len(candles)

    if len(candles) <= period:
        return result

    true_ranges = [None]

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges.append(true_range)

    first_atr = sum(
        true_ranges[1:period + 1]
    ) / period

    result[period] = first_atr

    previous = first_atr

    for i in range(period + 1, len(candles)):

        previous = (
            previous * (period - 1)
            + true_ranges[i]
        ) / period

        result[i] = previous

    return result


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_support(
    candles: List[dict],
    lookback: int = 50,
):

    data = candles[-lookback:]

    return min(
        candle["low"]
        for candle in data
    )


def get_resistance(
    candles: List[dict],
    lookback: int = 50,
):

    data = candles[-lookback:]

    return max(
        candle["high"]
        for candle in data
    )


def bullish_structure(
    candles: List[dict],
):

    if len(candles) < 40:
        return False

    recent = candles[-40:]

    first = recent[:20]
    second = recent[20:]

    high1 = max(x["high"] for x in first)
    high2 = max(x["high"] for x in second)

    low1 = min(x["low"] for x in first)
    low2 = min(x["low"] for x in second)

    return (
        high2 > high1
        and low2 > low1
    )


def bearish_structure(
    candles: List[dict],
):

    if len(candles) < 40:
        return False

    recent = candles[-40:]

    first = recent[:20]
    second = recent[20:]

    high1 = max(x["high"] for x in first)
    high2 = max(x["high"] for x in second)

    low1 = min(x["low"] for x in first)
    low2 = min(x["low"] for x in second)

    return (
        high2 < high1
        and low2 < low1
    )


def bullish_breakout(
    candles: List[dict],
    lookback: int = 20,
):

    if len(candles) < lookback + 2:
        return False

    previous = candles[-lookback - 1:-1]

    resistance = max(
        candle["high"]
        for candle in previous
    )

    last = candles[-1]

    return (
        last["close"] > resistance
        and last["volume"] > 0
    )


def bearish_breakdown(
    candles: List[dict],
    lookback: int = 20,
):

    if len(candles) < lookback + 2:
        return False

    previous = candles[-lookback - 1:-1]

    support = min(
        candle["low"]
        for candle in previous
    )

    last = candles[-1]

    return (
        last["close"] < support
        and last["volume"] > 0
    )


def volume_ratio(
    candles: List[dict],
    period: int = 20,
):

    if len(candles) < period + 1:
        return 0

    current = candles[-1]["volume"]

    previous = [
        candle["volume"]
        for candle in candles[-period - 1:-1]
    ]

    average = sum(previous) / len(previous)

    if average == 0:
        return 0

    return current / average


# ============================================================
# ANALYZE ONE SYMBOL
# ============================================================

def analyze_symbol(symbol: str) -> Optional[Dict]:

    symbol = symbol.upper().strip()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    try:

        candles_1h = get_klines(
            symbol,
            "1h",
            250,
        )

        candles_4h = get_klines(
            symbol,
            "4h",
            150,
        )

    except Exception as e:

        print(
            f"Error loading {symbol}: {e}"
        )

        return None

    if len(candles_1h) < 200:
        return None

    if len(candles_4h) < 50:
        return None

    closes_1h = [
        candle["close"]
        for candle in candles_1h
    ]

    closes_4h = [
        candle["close"]
        for candle in candles_4h
    ]

    # ========================================================
    # 1H INDICATORS
    # ========================================================

    ema20_1h = ema(
        closes_1h,
        20,
    )[-1]

    ema50_1h = ema(
        closes_1h,
        50,
    )[-1]

    ema200_1h = ema(
        closes_1h,
        200,
    )[-1]

    rsi_1h = rsi(
        closes_1h,
        14,
    )[-1]

    macd_line, signal_line = macd(
        closes_1h
    )

    macd_1h = macd_line[-1]
    signal_1h = signal_line[-1]

    atr_1h = atr(
        candles_1h,
        14,
    )[-1]

    # ========================================================
    # 4H TREND
    # ========================================================

    ema20_4h = ema(
        closes_4h,
        20,
    )[-1]

    ema50_4h = ema(
        closes_4h,
        50,
    )[-1]

    ema200_4h = ema(
        closes_4h,
        200,
    )[-1]

    # EMA200 قد لا تكون متاحة على 150 شمعة
    # لذلك نعتمد على EMA20/50 في 4H.

    required = [
        ema20_1h,
        ema50_1h,
        ema200_1h,
        rsi_1h,
        macd_1h,
        signal_1h,
        atr_1h,
        ema20_4h,
        ema50_4h,
    ]

    if any(value is None for value in required):
        return None

    price = closes_1h[-1]

    support = get_support(
        candles_1h,
        50,
    )

    resistance = get_resistance(
        candles_1h,
        50,
    )

    vol_ratio = volume_ratio(
        candles_1h,
        20,
    )

    bull_structure = bullish_structure(
        candles_1h
    )

    bear_structure = bearish_structure(
        candles_1h
    )

    bull_breakout = bullish_breakout(
        candles_1h,
        20,
    )

    bear_breakdown = bearish_breakdown(
        candles_1h,
        20,
    )

    # ========================================================
    # SCORE
    # ========================================================

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    if price > ema20_1h:

        long_score += 8
        long_reasons.append(
            "السعر فوق EMA20 على 1H"
        )

    if ema20_1h > ema50_1h:

        long_score += 8
        long_reasons.append(
            "EMA20 فوق EMA50"
        )

    if ema50_1h > ema200_1h:

        long_score += 8
        long_reasons.append(
            "EMA50 فوق EMA200"
        )

    if ema20_4h > ema50_4h:

        long_score += 15
        long_reasons.append(
            "اتجاه 4H صاعد"
        )

    if 50 <= rsi_1h <= 67:

        long_score += 10
        long_reasons.append(
            "RSI في منطقة داعمة"
        )

    if macd_1h > signal_1h:

        long_score += 10
        long_reasons.append(
            "MACD إيجابي"
        )

    if bull_structure:

        long_score += 12
        long_reasons.append(
            "هيكل السوق صاعد"
        )

    if bull_breakout:

        long_score += 14
        long_reasons.append(
            "اختراق مقاومة مؤكد"
        )

    if vol_ratio >= 1.20:

        long_score += 10
        long_reasons.append(
            "حجم التداول مرتفع"
        )

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

    if price < ema20_1h:

        short_score += 8
        short_reasons.append(
            "السعر تحت EMA20 على 1H"
        )

    if ema20_1h < ema50_1h:

        short_score += 8
        short_reasons.append(
            "EMA20 تحت EMA50"
        )

    if ema50_1h < ema200_1h:

        short_score += 8
        short_reasons.append(
            "EMA50 تحت EMA200"
        )

    if ema20_4h < ema50_4h:

        short_score += 15
        short_reasons.append(
            "اتجاه 4H هابط"
        )

    if 33 <= rsi_1h <= 50:

        short_score += 10
        short_reasons.append(
            "RSI في منطقة داعمة للشورت"
        )

    if macd_1h < signal_1h:

        short_score += 10
        short_reasons.append(
            "MACD سلبي"
        )

    if bear_structure:

        short_score += 12
        short_reasons.append(
            "هيكل السوق هابط"
        )

    if bear_breakdown:

        short_score += 14
        short_reasons.append(
            "كسر دعم مؤكد"
        )

    if vol_ratio >= 1.20:

        short_score += 10
        short_reasons.append(
            "حجم التداول مرتفع"
        )

    # ========================================================
    # SELECT DIRECTION
    # ========================================================

    if long_score > short_score:

        direction = "LONG"
        score = long_score
        reasons = long_reasons

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score
        reasons = short_reasons

    else:

        return None

    # ========================================================
    # STRONG SIGNAL FILTER
    # ========================================================

    if score < 75:
        return None

    # لا ندخل إذا كانت الإشارة متعارضة بشدة
    difference = abs(
        long_score - short_score
    )

    if difference < 10:
        return None

    # ========================================================
    # DISTANCE FROM SUPPORT / RESISTANCE
    # ========================================================

    if direction == "LONG":

        room = (
            resistance - price
        ) / price

        if room < 0.015:
            return None

    else:

        room = (
            price - support
        ) / price

        if room < 0.015:
            return None

    # ========================================================
    # ENTRY / STOP / TARGETS
    # ========================================================

    if direction == "LONG":

        entry_low = max(
            support,
            price - atr_1h * 0.35,
        )

        entry_high = price

        stop = min(
            support - atr_1h * 0.20,
            price - atr_1h * 1.20,
        )

        risk = price - stop

        if risk <= 0:
            return None

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 3.5

    else:

        entry_low = price

        entry_high = min(
            resistance,
            price + atr_1h * 0.35,
        )

        stop = max(
            resistance + atr_1h * 0.20,
            price + atr_1h * 1.20,
        )

        risk = stop - price

        if risk <= 0:
            return None

        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 3.5

    # ========================================================
    # RISK / REWARD CHECK
    # ========================================================

    reward = abs(tp2 - price)

    if risk <= 0:
        return None

    rr = reward / risk

    if rr < 2:
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
        "rsi": rsi_1h,
        "volume_ratio": vol_ratio,
        "support": support,
        "resistance": resistance,
        "atr": atr_1h,
        "risk_reward": rr,
        "reasons": reasons,
    }


# ============================================================
# MARKET SCANNER
# ============================================================

def scan_market() -> List[Dict]:

    symbols = get_usdt_symbols()

    results = []

    print(
        f"Scanning {len(symbols)} Binance USDT pairs..."
    )

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result:
                results.append(result)

        except Exception as e:

            print(
                f"{symbol}: {e}"
            )

        if index % 10 == 0:

            print(
                f"Progress: "
                f"{index}/{len(symbols)}"
            )

        time.sleep(0.03)

    results.sort(
        key=lambda x: (
            x["score"],
            x.get("risk_reward", 0),
        ),
        reverse=True,
    )

    return results


# ============================================================
# FORMAT NUMBER
# ============================================================

def format_number(value: float) -> str:

    value = float(value)

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return (
            f"{value:.4f}"
            .rstrip("0")
            .rstrip(".")
        )

    if value >= 0.01:
        return (
            f"{value:.6f}"
            .rstrip("0")
            .rstrip(".")
        )

    if value >= 0.0001:
        return (
            f"{value:.8f}"
            .rstrip("0")
            .rstrip(".")
        )

    return (
        f"{value:.10f}"
        .rstrip("0")
        .rstrip(".")
    )
