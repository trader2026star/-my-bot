import time
import requests

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/2.0"
})


def _get(base, path, params=None, timeout=10):
    try:
        r = SESSION.get(
            base + path,
            params=params,
            timeout=timeout
        )

        if r.status_code == 200:
            return r.json()

        print("BINANCE ERROR:", r.status_code, r.text[:300])

    except Exception as e:
        print("BINANCE REQUEST ERROR:", repr(e))

    return None


def get_klines(symbol, interval="15m", limit=180):
    symbol = symbol.upper()

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    data = _get(
        FUTURES_URL,
        "/fapi/v1/klines",
        params
    )

    if isinstance(data, list) and len(data) >= 60:
        return data

    data = _get(
        DATA_URL,
        "/api/v3/klines",
        params
    )

    return data if isinstance(data, list) else None


def get_price(symbol):
    symbol = symbol.upper()

    data = _get(
        FUTURES_URL,
        "/fapi/v1/ticker/price",
        {"symbol": symbol}
    )

    if data:
        try:
            return float(data["price"])
        except:
            pass

    data = _get(
        DATA_URL,
        "/api/v3/ticker/price",
        {"symbol": symbol}
    )

    try:
        return float(data["price"])
    except:
        return None


def get_tickers():
    data = _get(
        FUTURES_URL,
        "/fapi/v1/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    data = _get(
        DATA_URL,
        "/api/v3/ticker/24hr"
    )

    return data if isinstance(data, list) else []


def average(values):
    return sum(values) / len(values) if values else 0


def pct(old, new):
    if old == 0:
        return 0

    return ((new - old) / old) * 100


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = average(values[:period])

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = average(gains[:period])
    avg_loss = average(losses[:period])

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(highs, lows, closes, period=14):

    if len(closes) <= period:
        return None

    trs = []

    for i in range(1, len(closes)):

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )

        trs.append(tr)

    return average(trs[-period:])


def timeframe_analysis(symbol, interval):

    klines = get_klines(
        symbol,
        interval,
        180
    )

    if not klines or len(klines) < 80:
        return None

    highs = [float(x[2]) for x in klines]
    lows = [float(x[3]) for x in klines]
    closes = [float(x[4]) for x in klines]
    volumes = [float(x[5]) for x in klines]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi_value = rsi(closes)
    atr_value = atr(
        highs,
        lows,
        closes
    )

    volume20 = average(
        volumes[-20:]
    )

    volume5 = average(
        volumes[-5:]
    )

    previous_volume = average(
        volumes[-10:-5]
    )

    volume_ratio = (
        volume5 / volume20
        if volume20
        else 0
    )

    volume_trend = (
        volume5 / previous_volume
        if previous_volume
        else 1
    )

    bullish = 0
    bearish = 0

    if ema20 and ema50:

        if ema20 > ema50:
            bullish += 1
        else:
            bearish += 1

    if ema50 and ema200:

        if ema50 > ema200:
            bullish += 1
        else:
            bearish += 1

    if ema20:

        if price > ema20:
            bullish += 1
        else:
            bearish += 1

    if ema50:

        if price > ema50:
            bullish += 1
        else:
            bearish += 1

    if ema200:

        if price > ema200:
            bullish += 1
        else:
            bearish += 1

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi_value,
        "atr": atr_value,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "bullish": bullish,
        "bearish": bearish,
        "change15": pct(
            closes[-16],
            price
        ),
        "change30": pct(
            closes[-31],
            price
        ),
        "change60": pct(
            closes[-61],
            price
        ),
        "high20": max(highs[-20:]),
        "low20": min(lows[-20:])
    }


def analyze_symbol(symbol):

    symbol = symbol.upper().replace(
        "/",
        ""
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    tf15 = timeframe_analysis(
        symbol,
        "15m"
    )

    tf1h = timeframe_analysis(
        symbol,
        "1h"
    )

    tf4h = timeframe_analysis(
        symbol,
        "4h"
    )

    if not tf15 or not tf1h or not tf4h:
        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =========================
    # MULTI TIMEFRAME
    # =========================

    if tf4h["bullish"] >= 3:
        long_score += 15
        long_reasons.append("4H اتجاه صاعد")

    if tf1h["bullish"] >= 3:
        long_score += 15
        long_reasons.append("1H اتجاه صاعد")

    if tf15["bullish"] >= 3:
        long_score += 10
        long_reasons.append("15M يتحسن")

    if tf4h["bearish"] >= 3:
        short_score += 15
        short_reasons.append("4H اتجاه هابط")

    if tf1h["bearish"] >= 3:
        short_score += 15
        short_reasons.append("1H اتجاه هابط")

    if tf15["bearish"] >= 3:
        short_score += 10
        short_reasons.append("15M ضعيف")

    # =========================
    # LONG
    # =========================

    if tf15["price"] > tf15["ema20"]:
        long_score += 5
        long_reasons.append("فوق EMA20")

    if tf15["ema20"] > tf15["ema50"]:
        long_score += 5
        long_reasons.append("EMA20 فوق EMA50")

    if (
        tf15["rsi"]
        and 42 <= tf15["rsi"] <= 62
    ):
        long_score += 5
        long_reasons.append("RSI صحي")

    if tf15["volume_ratio"] >= 1.05:
        long_score += 5
        long_reasons.append("Volume نشط")

    if tf15["volume_trend"] >= 1.05:
        long_score += 5
        long_reasons.append("Volume في تحسن")

    # =========================
    # ACCUMULATION
    # =========================

    accumulation = (
        tf15["change30"] < 2
        and tf15["change60"] < 6
        and tf15["change15"] > -2
        and tf15["volume_trend"] >= 1.05
        and 38 <= tf15["rsi"] <= 62
    )

    if accumulation:
        long_score += 15
        long_reasons.append(
            "تجميع مبكر"
        )

    # =========================
    # SHORT
    # =========================

    if tf15["price"] < tf15["ema20"]:
        short_score += 5
        short_reasons.append(
            "تحت EMA20"
        )

    if tf15["ema20"] < tf15["ema50"]:
        short_score += 5
        short_reasons.append(
            "EMA20 تحت EMA50"
        )

    if tf15["rsi"] >= 68:
        short_score += 10
        short_reasons.append(
            "RSI مرتفع"
        )

    if tf15["volume_trend"] < 0.90:
        short_score += 10
        short_reasons.append(
            "ضعف Volume"
        )

    # =========================
    # DISTRIBUTION
    # =========================

    distribution = (
        tf15["change60"] >= 6
        and (
            tf15["change15"] < 0
            or tf15["volume_trend"] < 0.90
        )
    )

    if distribution:
        short_score += 15
        short_reasons.append(
            "احتمال توزيع"
        )

    # =========================
    # LATE PUMP PROTECTION
    # =========================

    late_pump = (
        tf15["change15"] >= 5
        or tf15["change60"] >= 10
    )

    if late_pump:
        long_score -= 30
        long_reasons.append(
            "الحركة متأخرة"
        )

    # =========================
    # DUMP PROTECTION
    # =========================

    dump = (
        tf15["change15"] <= -3
        and tf15["volume_ratio"] >= 1.5
    )

    if dump:
        long_score -= 30
        long_reasons.append(
            "ضغط بيع قوي"
        )

    long_score = max(
        0,
        min(100, long_score)
    )

    short_score = max(
        0,
        min(100, short_score)
    )

    # =========================
    # SIGNAL
    # =========================

    signal = "WAIT"

    if (
        long_score >= 70
        and long_score >= short_score + 15
        and not late_pump
        and not dump
    ):
        signal = "EARLY_LONG"

    elif (
        short_score >= 70
        and short_score >= long_score + 15
    ):
        signal = "SHORT"

    elif (
        long_score >= 55
        and long_score > short_score + 5
    ):
        signal = "WATCH_LONG"

    elif (
        short_score >= 55
        and short_score > long_score + 5
    ):
        signal = "WATCH_SHORT"

    return {
        "symbol": symbol,
        "price": tf15["price"],
        "signal": signal,

        "long_score": long_score,
        "short_score": short_score,

        "rsi": tf15["rsi"],

        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],
        "ema200": tf15["ema200"],

        "volume_ratio": tf15["volume_ratio"],
        "volume_trend": tf15["volume_trend"],

        "change15": tf15["change15"],
        "change30": tf15["change30"],
        "change60": tf15["change60"],

        "atr": tf15["atr"],

        "tf15_bull": tf15["bullish"],
        "tf15_bear": tf15["bearish"],

        "tf1h_bull": tf1h["bullish"],
        "tf1h_bear": tf1h["bearish"],

        "tf4h_bull": tf4h["bullish"],
        "tf4h_bear": tf4h["bearish"],

        "accumulation": accumulation,
        "distribution": distribution,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }


def scan_market(limit=25):

    tickers = get_tickers()

    candidates = []

    for ticker in tickers:

        symbol = ticker.get(
            "symbol",
            ""
        )

        if not symbol.endswith("USDT"):
            continue

        try:

            volume = float(
                ticker.get(
                    "quoteVolume",
                    0
                )
            )

            daily_change = float(
                ticker.get(
                    "priceChangePercent",
                    0
                )
            )

        except:
            continue

        if volume < 2_000_000:
            continue

        if abs(daily_change) < 0.5:
            continue

        if daily_change > 30:
            continue

        candidates.append(
            (
                symbol,
                volume,
                daily_change
            )
        )

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[:limit]

    results = []

    for symbol, volume, daily_change in candidates:

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                result["quote_volume"] = volume
                result["daily_change"] = daily_change

                if result["signal"] != "WAIT":
                    results.append(
                        result
                    )

        except Exception as e:

            print(
                "SCAN ERROR",
                symbol,
                repr(e)
            )

        time.sleep(0.08)

    priority = {
        "EARLY_LONG": 4,
        "SHORT": 3,
        "WATCH_LONG": 2,
        "WATCH_SHORT": 1
    }

    results.sort(
        key=lambda x: (
            priority.get(
                x["signal"],
                0
            ),
            max(
                x["long_score"],
                x["short_score"]
            )
        ),
        reverse=True
    )

    return results


def format_price(price):

    if price is None:
        return "-"

    price = float(price)

    if price >= 1000:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.4f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    return f"{price:.10f}"


def prepare_trade(result):

    if not result:
        return None

    price = result["price"]

    atr_value = result.get(
        "atr"
    )

    if not atr_value:
        atr_value = price * 0.01

    signal = result["signal"]

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = price - (
            atr_value * 0.20
        )

        entry_high = price + (
            atr_value * 0.10
        )

        stop = price - (
            atr_value * 1.20
        )

        risk = price - stop

        return {
            "side": "LONG",

            "entry":
                f"{format_price(entry_low)} - "
                f"{format_price(entry_high)}",

            "stop":
                format_price(stop),

            "tp1":
                format_price(
                    price + risk * 1.5
                ),

            "tp2":
                format_price(
                    price + risk * 2.5
                ),

            "tp3":
                format_price(
                    price + risk * 4
                )
        }

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        entry_low = price - (
            atr_value * 0.10
        )

        entry_high = price + (
            atr_value * 0.20
        )

        stop = price + (
            atr_value * 1.20
        )

        risk = stop - price

        return {
            "side": "SHORT",

            "entry":
                f"{format_price(entry_low)} - "
                f"{format_price(entry_high)}",

            "stop":
                format_price(stop),

            "tp1":
                format_price(
                    price - risk * 1.5
                ),

            "tp2":
                format_price(
                    price - risk * 2.5
                ),

            "tp3":
                format_price(
                    price - risk * 4
                )
        }

    return None
