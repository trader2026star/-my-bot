import time
import math
import requests

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/6.0"
})


# =========================================================
# BINANCE API
# =========================================================

def api_get(base, path, params=None, timeout=10):
    try:
        r = SESSION.get(
            base + path,
            params=params,
            timeout=timeout
        )

        if r.status_code == 200:
            return r.json()

        print(
            "BINANCE ERROR:",
            r.status_code,
            r.text[:250]
        )

    except Exception as e:
        print(
            "BINANCE REQUEST ERROR:",
            repr(e)
        )

    return None


def get_klines(symbol, interval, limit=220):

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

    if isinstance(data, list) and len(data) >= 60:
        return data

    return None


def get_tickers():

    data = api_get(
        FUTURES_URL,
        "/fapi/v1/ticker/24hr"
    )

    if isinstance(data, list) and data:
        return data

    data = api_get(
        DATA_URL,
        "/api/v3/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    return []


# =========================================================
# BASIC MATH
# =========================================================

def average(values):
    return (
        sum(values) / len(values)
        if values else 0
    )


def pct(old, new):

    if old is None or old == 0:
        return 0

    return ((new - old) / old) * 100


def stddev(values):

    if len(values) < 2:
        return 0

    avg = average(values)

    variance = average([
        (x - avg) ** 2
        for x in values
    ])

    return math.sqrt(variance)


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = average(
        values[:period]
    )

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


# =========================================================
# RSI
# =========================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = average(
        gains[:period]
    )

    avg_loss = average(
        losses[:period]
    )

    for i in range(
        period,
        len(gains)
    ):

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

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# ATR
# =========================================================

def atr(
    highs,
    lows,
    closes,
    period=14
):

    if len(closes) <= period:
        return None

    trs = []

    for i in range(1, len(closes)):

        tr = max(
            highs[i] - lows[i],
            abs(
                highs[i]
                - closes[i - 1]
            ),
            abs(
                lows[i]
                - closes[i - 1]
            )
        )

        trs.append(tr)

    return average(
        trs[-period:]
    )


# =========================================================
# MACD
# =========================================================

def macd(values):

    if len(values) < 35:
        return {
            "macd": None,
            "signal": None,
            "hist": None
        }

    fast_values = []
    slow_values = []

    for i in range(
        25,
        len(values)
    ):

        fast = ema(
            values[:i + 1],
            12
        )

        slow = ema(
            values[:i + 1],
            26
        )

        if fast is not None and slow is not None:
            fast_values.append(
                fast - slow
            )

    if not fast_values:
        return {
            "macd": None,
            "signal": None,
            "hist": None
        }

    macd_line = fast_values[-1]

    signal_line = ema(
        fast_values,
        9
    )

    if signal_line is None:
        signal_line = macd_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "hist": (
            macd_line
            - signal_line
        )
    }


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(
    symbol,
    interval,
    limit=220
):

    klines = get_klines(
        symbol,
        interval,
        limit
    )

    if not klines or len(klines) < 60:
        return None

    opens = [
        float(x[1])
        for x in klines
    ]

    highs = [
        float(x[2])
        for x in klines
    ]

    lows = [
        float(x[3])
        for x in klines
    ]

    closes = [
        float(x[4])
        for x in klines
    ]

    volumes = [
        float(x[5])
        for x in klines
    ]

    price = closes[-1]

    e9 = ema(
        closes,
        9
    )

    e20 = ema(
        closes,
        20
    )

    e50 = ema(
        closes,
        50
    )

    e200 = ema(
        closes,
        200
    )

    rsi_value = rsi(
        closes
    )

    atr_value = atr(
        highs,
        lows,
        closes
    )

    macd_data = macd(
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
        if avg20
        else 0
    )

    volume_trend = (
        avg5 / previous5
        if previous5
        else 1
    )

    bull = 0
    bear = 0

    # EMA 20 / 50
    if e20 and e50:

        if e20 > e50:
            bull += 1
        else:
            bear += 1

    # EMA 50 / 200
    if e50 and e200:

        if e50 > e200:
            bull += 1
        else:
            bear += 1

    # Price / EMA20
    if e20:

        if price > e20:
            bull += 1
        else:
            bear += 1

    # Price / EMA50
    if e50:

        if price > e50:
            bull += 1
        else:
            bear += 1

    # Price / EMA200
    if e200:

        if price > e200:
            bull += 1
        else:
            bear += 1

    change = pct(
        closes[-2],
        closes[-1]
    )

    change5 = (
        pct(
            closes[-6],
            closes[-1]
        )
        if len(closes) >= 6
        else 0
    )

    change20 = (
        pct(
            closes[-21],
            closes[-1]
        )
        if len(closes) >= 21
        else 0
    )

    high20 = max(
        highs[-20:]
    )

    low20 = min(
        lows[-20:]
    )

    # Technical support / resistance
    support = min(
        lows[-30:]
    )

    resistance = max(
        highs[-30:]
    )

    # Volatility
    returns = []

    for i in range(
        max(1, len(closes) - 20),
        len(closes)
    ):

        if closes[i - 1] != 0:

            returns.append(
                (
                    closes[i]
                    - closes[i - 1]
                )
                / closes[i - 1]
                * 100
            )

    volatility_pct = stddev(
        returns
    )

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

        "macd": macd_data["macd"],
        "macd_signal": macd_data["signal"],
        "macd_hist": macd_data["hist"],

        "atr": atr_value,

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "bull": bull,
        "bear": bear,

        "change": change,
        "change5": change5,
        "change20": change20,

        "high20": high20,
        "low20": low20,

        "support": support,
        "resistance": resistance,

        "volatility_pct": volatility_pct
    }


# =========================================================
# QUANTITATIVE RANGE
# =========================================================

def calculate_quantitative_range(
    price,
    atr_value,
    support,
    resistance,
    volatility_pct
):

    if not price:
        return None

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.008

    # ATR-based expected movement
    atr_component = (
        atr_value * 1.20
    )

    # Volatility component
    volatility_component = (
        price
        * max(
            volatility_pct,
            0.20
        )
        / 100
        * 1.50
    )

    # Combine statistical components
    movement = max(
        atr_component,
        volatility_component
    )

    qr_low = (
        price - movement
    )

    qr_high = (
        price + movement
    )

    # Keep the range connected
    # to nearby technical structure
    if support and support < price:
        qr_low = max(
            qr_low,
            support
        )

    if resistance and resistance > price:
        qr_high = min(
            qr_high,
            resistance
        )

    if qr_low >= price:
        qr_low = (
            price - movement
        )

    if qr_high <= price:
        qr_high = (
            price + movement
        )

    width_pct = (
        (
            qr_high - qr_low
        )
        / price
        * 100
    )

    return {
        "low": qr_low,
        "high": qr_high,
        "width_pct": width_pct,
        "movement": movement
    }


# =========================================================
# FULL ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = (
        symbol.upper()
        .replace("/", "")
        .replace("-", "")
        .strip()
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    tf15 = analyze_timeframe(
        symbol,
        "15m",
        220
    )

    tf30 = analyze_timeframe(
        symbol,
        "30m",
        220
    )

    tf1h = analyze_timeframe(
        symbol,
        "1h",
        220
    )

    tf4h = analyze_timeframe(
        symbol,
        "4h",
        220
    )

    tf1d = analyze_timeframe(
        symbol,
        "1d",
        220
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
    # DAILY TREND
    # =====================================================

    if tf1d["bull"] >= 3:

        long_score += 20

        long_reasons.append(
            "اليومي يدعم الاتجاه الصاعد"
        )

    elif tf1d["bull"] >= 2:

        long_score += 10

    if tf1d["bear"] >= 3:

        short_score += 20

        short_reasons.append(
            "اليومي يدعم الاتجاه الهابط"
        )

    elif tf1d["bear"] >= 2:

        short_score += 10

    # =====================================================
    # 4H
    # =====================================================

    if tf4h["bull"] >= 3:

        long_score += 20

        long_reasons.append(
            "4H صاعد"
        )

    elif tf4h["bull"] >= 2:

        long_score += 10

    if tf4h["bear"] >= 3:

        short_score += 20

        short_reasons.append(
            "4H هابط"
        )

    elif tf4h["bear"] >= 2:

        short_score += 10

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

    elif tf30["bull"] >= 2:

        long_score += 5

    if tf30["bear"] >= 3:

        short_score += 10

        short_reasons.append(
            "30M يؤكد الهبوط"
        )

    elif tf30["bear"] >= 2:

        short_score += 5

    # =====================================================
    # 15M
    # =====================================================

    if tf15["bull"] >= 3:

        long_score += 10

        long_reasons.append(
            "15M يعطي تأكيد دخول"
        )

    elif tf15["bull"] >= 2:

        long_score += 5

    if tf15["bear"] >= 3:

        short_score += 10

        short_reasons.append(
            "15M يعطي تأكيد هبوط"
        )

    elif tf15["bear"] >= 2:

        short_score += 5

    # =====================================================
    # RSI
    # =====================================================

    rsi15 = tf15["rsi"]

    if rsi15 is not None:

        if 42 <= rsi15 <= 62:

            long_score += 5

            long_reasons.append(
                "RSI في منطقة مناسبة للشراء"
            )

        elif rsi15 < 32:

            long_score += 3

            long_reasons.append(
                "RSI منخفض - احتمال ارتداد"
            )

        if 68 <= rsi15 <= 82:

            short_score += 5

            short_reasons.append(
                "RSI مرتفع"
            )

    # =====================================================
    # MACD
    # =====================================================

    if tf15["macd_hist"] is not None:

        if tf15["macd_hist"] > 0:

            long_score += 5

            long_reasons.append(
                "MACD إيجابي"
            )

        elif tf15["macd_hist"] < 0:

            short_score += 5

            short_reasons.append(
                "MACD سلبي"
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
        and tf15["change"] < 0
    ):

        short_score += 5

        short_reasons.append(
            "ضعف الحجم مع الهبوط"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    accumulation = (
        tf15["change20"] <= 2.0
        and tf15["change5"] <= 3.0
        and tf15["change"] > -2
        and tf15["volume_trend"] >= 1.02
        and rsi15 is not None
        and 38 <= rsi15 <= 62
    )

    if accumulation:

        long_score += 15

        long_reasons.append(
            "تجميع سيولة وبداية انعكاس قبل البمب"
        )

    # =====================================================
    # DISTRIBUTION
    # =====================================================

    distribution = (
        tf1h["change20"] >= 5
        and (
            tf15["change"] < 0
            or tf15["volume_trend"] < 0.90
        )
    )

    if distribution:

        short_score += 20

        short_reasons.append(
            "Distribution وخروج سيولة بعد صعود"
        )

    # =====================================================
    # LATE PUMP
    # =====================================================

    late_pump = (
        tf15["change5"] >= 5
        or tf30["change5"] >= 8
        or tf1h["change5"] >= 10
        or tf4h["change"] >= 8
    )

    if late_pump:

        long_score -= 20

        long_reasons.append(
            "الحركة متأخرة - منع مطاردة Pump"
        )

    # =====================================================
    # STRONG DUMP
    # =====================================================

    strong_dump = (
        tf15["change5"] <= -3
        and tf15["volume_ratio"] >= 1.5
    )

    if strong_dump:

        long_score -= 20

        long_reasons.append(
            "ضغط بيع قوي"
        )

    # =====================================================
    # OVERHEATED
    # =====================================================

    overheated = (
        (
            tf4h["rsi"] is not None
            and tf4h["rsi"] >= 80
        )
        or
        (
            tf1d["rsi"] is not None
            and tf1d["rsi"] >= 80
        )
    )

    if overheated:

        long_score -= 12
        short_score += 4

        long_reasons.append(
            "4H/1D ساخن جدًا"
        )

    # =====================================================
    # DAILY CONFLICT
    # =====================================================

    if tf1d["bear"] >= 3:

        long_score -= 10

    if tf1d["bull"] >= 3:

        short_score -= 10

    # =====================================================
    # QUANTITATIVE RANGE
    # =====================================================

    qr = calculate_quantitative_range(
        tf15["price"],
        tf15["atr"],
        tf15["support"],
        tf15["resistance"],
        tf15["volatility_pct"]
    )

    # =====================================================
    # TECHNICAL STRUCTURE
    # =====================================================

    support = tf15["support"]
    resistance = tf15["resistance"]

    near_support = False
    near_resistance = False

    if support and tf15["price"]:

        support_distance = (
            (
                tf15["price"]
                - support
            )
            / tf15["price"]
            * 100
        )

        near_support = (
            0 <= support_distance <= 2.5
        )

    if resistance and tf15["price"]:

        resistance_distance = (
            (
                resistance
                - tf15["price"]
            )
            / tf15["price"]
            * 100
        )

        near_resistance = (
            0 <= resistance_distance <= 2.5
        )

    if near_support:

        long_score += 5

        long_reasons.append(
            "السعر قريب من دعم فني"
        )

    if near_resistance:

        long_score -= 5

        long_reasons.append(
            "السعر قريب من مقاومة"
        )

        short_score += 3

    # =====================================================
    # LIMIT
    # =====================================================

    long_score = max(
        0,
        min(
            100,
            int(round(long_score))
        )
    )

    short_score = max(
        0,
        min(
            100,
            int(round(short_score))
        )
    )

    # =====================================================
    # SIGNAL
    # =====================================================

    signal = "WAIT"

    if (
        long_score >= 70
        and long_score >= short_score + 15
        and not late_pump
        and not strong_dump
        and not overheated
    ):

        signal = "EARLY_LONG"

    elif (
        short_score >= 70
        and short_score >= long_score + 15
    ):

        signal = "SHORT"

    elif (
        long_score >= 52
        and long_score >= short_score + 10
    ):

        signal = "WATCH_LONG"

    elif (
        short_score >= 52
        and short_score >= long_score + 10
    ):

        signal = "WATCH_SHORT"

    return {

        "symbol": symbol,

        "price": tf15["price"],

        "signal": signal,

        "long_score": long_score,
        "short_score": short_score,

        # RSI
        "rsi15": tf15["rsi"],
        "rsi1h": tf1h["rsi"],
        "rsi4h": tf4h["rsi"],
        "rsi1d": tf1d["rsi"],

        # EMA
        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],
        "ema200": tf15["ema200"],

        # MACD
        "macd": tf15["macd"],
        "macd_signal": tf15["macd_signal"],
        "macd_hist": tf15["macd_hist"],

        # Volume
        "volume_ratio":
            tf15["volume_ratio"],

        "volume_trend":
            tf15["volume_trend"],

        # Changes
        "change15":
            tf15["change"],

        "change30":
            tf30["change"],

        "change1h":
            tf1h["change"],

        "change4h":
            tf4h["change"],

        "change1d":
            tf1d["change"],

        # ATR
        "atr":
            tf15["atr"],

        # Technical levels
        "support":
            support,

        "resistance":
            resistance,

        "near_support":
            near_support,

        "near_resistance":
            near_resistance,

        # Quantitative Range
        "qr_low":
            qr["low"] if qr else None,

        "qr_high":
            qr["high"] if qr else None,

        "qr_width_pct":
            qr["width_pct"] if qr else None,

        "qr_movement":
            qr["movement"] if qr else None,

        "volatility_pct":
            tf15["volatility_pct"],

        # Timeframes
        "tf15_bull":
            tf15["bull"],

        "tf15_bear":
            tf15["bear"],

        "tf30_bull":
            tf30["bull"],

        "tf30_bear":
            tf30["bear"],

        "tf1h_bull":
            tf1h["bull"],

        "tf1h_bear":
            tf1h["bear"],

        "tf4h_bull":
            tf4h["bull"],

        "tf4h_bear":
            tf4h["bear"],

        "tf1d_bull":
            tf1d["bull"],

        "tf1d_bear":
            tf1d["bear"],

        # Structure
        "accumulation":
            accumulation,

        "distribution":
            distribution,

        "late_pump":
            late_pump,

        "overheated":
            overheated,

        "strong_dump":
            strong_dump,

        # Reasons
        "long_reasons":
            long_reasons,

        "short_reasons":
            short_reasons
    }


# =========================================================
# SCANNER
# =========================================================

def scan_market(limit=15):

    tickers = get_tickers()

    if not tickers:

        print(
            "SCAN: NO TICKERS"
        )

        return []

    candidates = []

    for ticker in tickers:

        symbol = ticker.get(
            "symbol",
            ""
        )

        if not symbol.endswith("USDT"):
            continue

        if any(
            x in symbol
            for x in [
                "UPUSDT",
                "DOWNUSDT",
                "BULLUSDT",
                "BEARUSDT"
            ]
        ):
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

        except Exception:

            continue

        if quote_volume < 500_000:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change
            )
        )

    # نأخذ عددًا أكبر للتحليل
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[
        :max(limit * 2, 30)
    ]

    results = []

    for (
        symbol,
        quote_volume,
        daily_change
    ) in candidates:

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                result[
                    "quote_volume"
                ] = quote_volume

                result[
                    "daily_change"
                ] = daily_change

                results.append(
                    result
                )

                print(
                    "SCAN OK:",
                    symbol,
                    result["signal"],
                    result["long_score"],
                    result["short_score"]
                )

        except Exception as e:

            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        time.sleep(0.05)

    # =====================================================
    # RANKING
    # =====================================================

    def rank(result):

        direction = max(
            result["long_score"],
            result["short_score"]
        )

        difference = abs(
            result["long_score"]
            - result["short_score"]
        )

        signal_bonus = {
            "EARLY_LONG": 60,
            "SHORT": 60,
            "WATCH_LONG": 30,
            "WATCH_SHORT": 30,
            "WAIT": 0
        }.get(
            result["signal"],
            0
        )

        accumulation_bonus = (
            15
            if result.get(
                "accumulation"
            )
            else 0
        )

        distribution_bonus = (
            15
            if result.get(
                "distribution"
            )
            else 0
        )

        liquidity_bonus = min(
            10,
            result.get(
                "quote_volume",
                0
            ) / 10_000_000
        )

        return (
            signal_bonus
            + direction
            + difference
            + accumulation_bonus
            + distribution_bonus
            + liquidity_bonus
        )

    results.sort(
        key=rank,
        reverse=True
    )

    return results[:8]


# =========================================================
# PRICE FORMAT
# =========================================================

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


# =========================================================
# TRADE
# =========================================================

def prepare_trade(result):

    if not result:
        return None

    signal = result.get(
        "signal",
        "WAIT"
    )

    price = float(
        result["price"]
    )

    atr_value = result.get(
        "atr"
    )

    if not atr_value or atr_value <= 0:

        atr_value = price * 0.008

    qr_low = result.get(
        "qr_low"
    )

    qr_high = result.get(
        "qr_high"
    )

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = (
            max(
                qr_low
                if qr_low
                else price - atr_value * 0.20,
                price - atr_value * 0.35
            )
        )

        entry_high = (
            min(
                qr_high
                if qr_high
                else price + atr_value * 0.10,
                price + atr_value * 0.10
            )
        )

        stop = (
            price
            - atr_value * 1.20
        )

        risk = (
            price
            - stop
        )

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
                    price + risk * 4.0
                )
        }

    # =====================================================
    # SHORT
    # =====================================================

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        entry_low = (
            max(
                qr_low
                if qr_low
                else price - atr_value * 0.10,
                price - atr_value * 0.10
            )
        )

        entry_high = (
            min(
                qr_high
                if qr_high
                else price + atr_value * 0.20,
                price + atr_value * 0.35
            )
        )

        stop = (
            price
            + atr_value * 1.20
        )

        risk = (
            stop
            - price
        )

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
                    price - risk * 4.0
                )
        }

    return None
