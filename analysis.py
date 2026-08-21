import time
import requests

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/3.0"
})


def api_get(base, path, params=None, timeout=12):
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


def get_klines(symbol, interval, limit=200):
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    data = api_get(
        FUTURES_URL,
        "/fapi/v1/klines",
        params
    )

    if isinstance(data, list) and len(data) >= 60:
        return data

    data = api_get(
        DATA_URL,
        "/api/v3/klines",
        params
    )

    if isinstance(data, list):
        return data

    return None


def get_tickers():
    data = api_get(
        FUTURES_URL,
        "/fapi/v1/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    return []


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


def analyze_timeframe(symbol, interval, limit=200):

    klines = get_klines(
        symbol,
        interval,
        limit
    )

    if not klines or len(klines) < 60:
        return None

    opens = [float(x[1]) for x in klines]
    highs = [float(x[2]) for x in klines]
    lows = [float(x[3]) for x in klines]
    closes = [float(x[4]) for x in klines]
    volumes = [float(x[5]) for x in klines]

    price = closes[-1]

    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    rsi_value = rsi(closes)
    atr_value = atr(
        highs,
        lows,
        closes
    )

    avg20 = average(
        volumes[-20:]
    )

    avg5 = average(
        volumes[-5:]
    )

    previous5 = average(
        volumes[-10:-5]
    )

    volume_ratio = (
        avg5 / avg20
        if avg20 else 0
    )

    volume_trend = (
        avg5 / previous5
        if previous5 else 1
    )

    bull = 0
    bear = 0

    if e20 and e50:
        if e20 > e50:
            bull += 1
        else:
            bear += 1

    if e50 and e200:
        if e50 > e200:
            bull += 1
        else:
            bear += 1

    if e20:
        if price > e20:
            bull += 1
        else:
            bear += 1

    if e50:
        if price > e50:
            bull += 1
        else:
            bear += 1

    if e200:
        if price > e200:
            bull += 1
        else:
            bear += 1

    return {
        "price": price,
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],

        "ema9": e9,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,

        "rsi": rsi_value,
        "atr": atr_value,

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "bull": bull,
        "bear": bear,

        "change15": pct(
            closes[-16],
            price
        ) if len(closes) >= 16 else 0,

        "change30": pct(
            closes[-31],
            price
        ) if len(closes) >= 31 else 0,

        "change60": pct(
            closes[-61],
            price
        ) if len(closes) >= 61 else 0,

        "high20": max(
            highs[-20:]
        ),

        "low20": min(
            lows[-20:]
        )
    }


def analyze_symbol(symbol):

    symbol = (
        symbol.upper()
        .replace("/", "")
        .replace("-", "")
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    tf15 = analyze_timeframe(
        symbol,
        "15m",
        180
    )

    tf30 = analyze_timeframe(
        symbol,
        "30m",
        180
    )

    tf1h = analyze_timeframe(
        symbol,
        "1h",
        180
    )

    tf4h = analyze_timeframe(
        symbol,
        "4h",
        200
    )

    tf1d = analyze_timeframe(
        symbol,
        "1d",
        200
    )

    if not all([
        tf15,
        tf30,
        tf1h,
        tf4h,
        tf1d
    ]):
        print(
            "TIMEFRAME DATA MISSING:",
            symbol
        )
        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # 1D - الاتجاه العام
    # =====================================================

    if tf1d["bull"] >= 3:
        long_score += 20
        long_reasons.append(
            "اليومي يدعم الاتجاه الصاعد"
        )

    elif tf1d["bull"] >= 2:
        long_score += 10
        long_reasons.append(
            "اليومي إيجابي جزئيًا"
        )

    if tf1d["bear"] >= 3:
        short_score += 20
        short_reasons.append(
            "اليومي يدعم الاتجاه الهابط"
        )

    elif tf1d["bear"] >= 2:
        short_score += 10
        short_reasons.append(
            "اليومي ضعيف"
        )

    # =====================================================
    # 4H - الاتجاه الرئيسي
    # =====================================================

    if tf4h["bull"] >= 3:
        long_score += 20
        long_reasons.append(
            "4H صاعد"
        )

    elif tf4h["bull"] >= 2:
        long_score += 10
        long_reasons.append(
            "4H إيجابي"
        )

    if tf4h["bear"] >= 3:
        short_score += 20
        short_reasons.append(
            "4H هابط"
        )

    elif tf4h["bear"] >= 2:
        short_score += 10
        short_reasons.append(
            "4H ضعيف"
        )

    # =====================================================
    # 1H
    # =====================================================

    if tf1h["bull"] >= 3:
        long_score += 15
        long_reasons.append(
            "1H صاعد"
        )

    elif tf1h["bull"] >= 2:
        long_score += 8

    if tf1h["bear"] >= 3:
        short_score += 15
        short_reasons.append(
            "1H هابط"
        )

    elif tf1h["bear"] >= 2:
        short_score += 8

    # =====================================================
    # 30M
    # =====================================================

    if tf30["bull"] >= 3:
        long_score += 10
        long_reasons.append(
            "30M يؤكد الصعود"
        )

    if tf30["bear"] >= 3:
        short_score += 10
        short_reasons.append(
            "30M يؤكد الهبوط"
        )

    # =====================================================
    # 15M - TRIGGER
    # =====================================================

    if tf15["bull"] >= 3:
        long_score += 10
        long_reasons.append(
            "15M يعطي تأكيد دخول"
        )

    if tf15["bear"] >= 3:
        short_score += 10
        short_reasons.append(
            "15M يعطي تأكيد هبوط"
        )

    # =====================================================
    # RSI
    # =====================================================

    if tf15["rsi"]:

        if 42 <= tf15["rsi"] <= 62:
            long_score += 5
            long_reasons.append(
                "RSI مناسب للشراء"
            )

        if 68 <= tf15["rsi"] <= 80:
            short_score += 8
            short_reasons.append(
                "RSI مرتفع"
            )

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.10:
        long_score += 5
        long_reasons.append(
            "دخول حجم"
        )

    if tf15["volume_trend"] >= 1.10:
        long_score += 5
        long_reasons.append(
            "الحجم يتحسن"
        )

    if (
        tf15["volume_trend"] < 0.85
        and tf15["change15"] < 0
    ):
        short_score += 5
        short_reasons.append(
            "ضعف الحجم مع هبوط"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    accumulation = (
        tf15["change30"] <= 1.5
        and tf15["change60"] <= 5
        and tf15["change15"] > -2
        and tf15["volume_trend"] >= 1.05
        and 38 <= tf15["rsi"] <= 62
    )

    if accumulation:
        long_score += 10
        long_reasons.append(
            "تجميع مبكر قبل الحركة"
        )

    # =====================================================
    # DISTRIBUTION
    # =====================================================

    distribution = (
        tf1h["change60"] >= 5
        and (
            tf15["change15"] < 0
            or tf15["volume_trend"] < 0.90
        )
    )

    if distribution:
        short_score += 15
        short_reasons.append(
            "احتمال توزيع وفقد زخم"
        )

    # =====================================================
    # LATE PUMP PROTECTION
    # =====================================================

    late_pump = (
        tf15["change15"] >= 5
        or tf30["change30"] >= 8
        or tf1h["change60"] >= 15
    )

    if late_pump:
        long_score -= 20
        long_reasons.append(
            "الحركة متأخرة - منع مطاردة Pump"
        )

    # =====================================================
    # STRONG DUMP PROTECTION
    # =====================================================

    strong_dump = (
        tf15["change15"] <= -3
        and tf15["volume_ratio"] >= 1.5
    )

    if strong_dump:
        long_score -= 20
        long_reasons.append(
            "ضغط بيع قوي"
        )

    # =====================================================
    # DAILY CONFLICT
    # =====================================================

    daily_bear = tf1d["bear"] >= 3
    daily_bull = tf1d["bull"] >= 3

    if daily_bear:
        long_score -= 10

    if daily_bull:
        short_score -= 10

    # =====================================================
    # LIMIT
    # =====================================================

    long_score = max(
        0,
        min(100, long_score)
    )

    short_score = max(
        0,
        min(100, short_score)
    )

    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    signal = "WAIT"

    if (
        long_score >= 75
        and long_score >= short_score + 20
        and not late_pump
        and not strong_dump
    ):
        signal = "EARLY_LONG"

    elif (
        short_score >= 75
        and short_score >= long_score + 20
    ):
        signal = "SHORT"

    elif (
        long_score >= 60
        and long_score >= short_score + 10
    ):
        signal = "WATCH_LONG"

    elif (
        short_score >= 60
        and short_score >= long_score + 10
    ):
        signal = "WATCH_SHORT"

    # =====================================================
    # RETURN
    # =====================================================

    return {
        "symbol": symbol,
        "price": tf15["price"],

        "signal": signal,

        "long_score": long_score,
        "short_score": short_score,

        "rsi15": tf15["rsi"],
        "rsi1h": tf1h["rsi"],
        "rsi4h": tf4h["rsi"],
        "rsi1d": tf1d["rsi"],

        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],
        "ema200": tf15["ema200"],

        "volume_ratio": tf15["volume_ratio"],
        "volume_trend": tf15["volume_trend"],

        "change15": tf15["change15"],
        "change30": tf30["change30"],
        "change1h": tf1h["change60"],
        "change4h": tf4h["change60"],
        "change1d": tf1d["change60"],

        "atr": tf15["atr"],

        "tf15_bull": tf15["bull"],
        "tf15_bear": tf15["bear"],

        "tf30_bull": tf30["bull"],
        "tf30_bear": tf30["bear"],

        "tf1h_bull": tf1h["bull"],
        "tf1h_bear": tf1h["bear"],

        "tf4h_bull": tf4h["bull"],
        "tf4h_bear": tf4h["bear"],

        "tf1d_bull": tf1d["bull"],
        "tf1d_bear": tf1d["bear"],

        "accumulation": accumulation,
        "distribution": distribution,
        "late_pump": late_pump,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }


def scan_market(limit=20):

    tickers = get_tickers()

    if not tickers:
        return []

    candidates = []

    for ticker in tickers:

        symbol = ticker.get(
            "symbol",
            ""
        )

        if not symbol.endswith("USDT"):
            continue

        try:
            quote_volume = float(
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

        if quote_volume < 2_000_000:
            continue

        if abs(daily_change) < 0.5:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
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
                    results.append(result)

        except Exception as e:

            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        time.sleep(0.10)

    priority = {
        "EARLY_LONG": 4,
        "SHORT": 4,
        "WATCH_LONG": 2,
        "WATCH_SHORT": 2
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

    signal = result["signal"]

    if signal == "WAIT":
        return None

    price = result["price"]

    atr_value = result.get(
        "atr"
    )

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.01

    # ==========================================
    # LONG
    # ==========================================

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

    # ==========================================
    # SHORT
    # ==========================================

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
