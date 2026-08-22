import time
import requests


# =========================================================
# SETTINGS
# =========================================================

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

        response = SESSION.get(
            base + path,
            params=params,
            timeout=timeout
        )

        if response.status_code == 200:
            return response.json()

        print(
            "BINANCE ERROR:",
            response.status_code,
            response.text[:250]
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

    # Futures first
    data = api_get(
        FUTURES_URL,
        "/fapi/v1/klines",
        params
    )

    if isinstance(data, list) and len(data) >= 60:
        return data

    # Spot fallback
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


def get_order_book(symbol, limit=100):

    params = {
        "symbol": symbol.upper(),
        "limit": limit
    }

    data = api_get(
        FUTURES_URL,
        "/fapi/v1/depth",
        params
    )

    if isinstance(data, dict) and "bids" in data and "asks" in data:
        return data

    data = api_get(
        DATA_URL,
        "/api/v3/depth",
        params
    )

    if isinstance(data, dict) and "bids" in data and "asks" in data:
        return data

    return None


# =========================================================
# MATH
# =========================================================

def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


def pct(old, new):

    if old is None or old == 0:
        return 0

    return ((new - old) / old) * 100


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


def atr(
    highs,
    lows,
    closes,
    period=14
):

    if len(closes) <= period:
        return None

    trs = []

    for i in range(
        1,
        len(closes)
    ):

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


def macd(
    closes,
    fast_period=12,
    slow_period=26,
    signal_period=9
):

    if len(closes) < slow_period + signal_period:
        return None, None, None

    fast_values = []
    slow_values = []

    for i in range(
        slow_period,
        len(closes) + 1
    ):

        section = closes[:i]

        fast_values.append(
            ema(
                section,
                fast_period
            )
        )

        slow_values.append(
            ema(
                section,
                slow_period
            )
        )

    macd_values = []

    for fast_value, slow_value in zip(
        fast_values,
        slow_values
    ):

        if fast_value is not None and slow_value is not None:

            macd_values.append(
                fast_value - slow_value
            )

    if len(macd_values) < signal_period:
        return None, None, None

    signal = ema(
        macd_values,
        signal_period
    )

    current = macd_values[-1]

    histogram = (
        current - signal
        if signal is not None
        else None
    )

    return (
        current,
        signal,
        histogram
    )


def bollinger(
    closes,
    period=20,
    deviation=2
):

    if len(closes) < period:
        return None, None, None

    values = closes[-period:]

    middle = average(values)

    variance = average([
        (x - middle) ** 2
        for x in values
    ])

    std = variance ** 0.5

    upper = (
        middle
        + deviation * std
    )

    lower = (
        middle
        - deviation * std
    )

    return (
        middle,
        upper,
        lower
    )


# =========================================================
# LIQUIDITY & HEALTH SCANS
# =========================================================

def analyze_market_depth(symbol):

    depth = get_order_book(symbol, limit=100)

    if not depth:
        return {
            "bid_volume": 0,
            "ask_volume": 0,
            "imbalance_ratio": 1.0,
            "pressure": "NEUTRAL"
        }

    bids = depth.get("bids", [])
    asks = depth.get("asks", [])

    bid_vol = sum([float(b[0]) * float(b[1]) for b in bids])
    ask_vol = sum([float(a[0]) * float(a[1]) for a in asks])

    total_vol = bid_vol + ask_vol

    if total_vol == 0:
        return {
            "bid_volume": 0,
            "ask_volume": 0,
            "imbalance_ratio": 1.0,
            "pressure": "NEUTRAL"
        }

    imbalance = bid_vol / ask_vol if ask_vol > 0 else 1.0

    if imbalance >= 1.3:
        pressure = "BUY_PRESSURE"
    elif imbalance <= 0.7:
        pressure = "SELL_PRESSURE"
    else:
        pressure = "NEUTRAL"

    return {
        "bid_volume": bid_vol,
        "ask_volume": ask_vol,
        "imbalance_ratio": imbalance,
        "pressure": pressure
    }


def check_asset_health(symbol, quote_volume=0, daily_change=0, tf15=None):

    health_score = 100
    flags = []

    if quote_volume > 0 and quote_volume < 1_000_000:
        health_score -= 30
        flags.append("سيولة منخفضة (Low Liquidity)")

    if abs(daily_change) > 25:
        health_score -= 25
        flags.append("تقلبات حادة جداً (High Volatility Risk)")

    if tf15 and tf15.get("volume_ratio", 1) < 0.3:
        health_score -= 20
        flags.append("ضعف مفاجئ في حجم التداول")

    is_healthy = health_score >= 60

    return {
        "health_score": health_score,
        "is_healthy": is_healthy,
        "flags": flags
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

    macd_value, macd_signal, macd_hist = macd(
        closes
    )

    bb_middle, bb_upper, bb_lower = bollinger(
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

    # EMA structure

    if e20 is not None and e50 is not None:

        if e20 > e50:
            bull += 1
        else:
            bear += 1

    if e50 is not None and e200 is not None:

        if e50 > e200:
            bull += 1
        else:
            bear += 1

    if e20 is not None:

        if price > e20:
            bull += 1
        else:
            bear += 1

    if e50 is not None:

        if price > e50:
            bull += 1
        else:
            bear += 1

    if e200 is not None:

        if price > e200:
            bull += 1
        else:
            bear += 1

    # MACD

    if macd_value is not None and macd_signal is not None:

        if macd_value > macd_signal:

            bull += 1

        else:

            bear += 1

    # RSI

    if rsi_value is not None:

        if 50 <= rsi_value <= 70:

            bull += 1

        elif rsi_value < 45:

            bear += 1

    # Momentum

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

    # Structure

    high20 = max(
        highs[-20:]
    )

    low20 = min(
        lows[-20:]
    )

    range_size = (
        high20 - low20
    )

    range_position = (
        (price - low20)
        / range_size
        if range_size > 0
        else 0.5
    )

    # Candle body / buying pressure

    candle_body = (
        closes[-1]
        - opens[-1]
    )

    candle_range = (
        highs[-1]
        - lows[-1]
    )

    body_ratio = (
        abs(candle_body)
        / candle_range
        if candle_range > 0
        else 0
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

        "atr": atr_value,

        "macd": macd_value,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,

        "bb_middle": bb_middle,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "bull": bull,
        "bear": bear,

        "change": change,
        "change5": change5,
        "change20": change20,

        "high20": high20,
        "low20": low20,

        "range_position": range_position,

        "body_ratio": body_ratio
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

    # Depth & Health Check
    depth_analysis = analyze_market_depth(symbol)
    health_scan = check_asset_health(symbol, tf15=tf15)

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # Orderbook Pressure Boost
    if depth_analysis["pressure"] == "BUY_PRESSURE":
        long_score += 5
        long_reasons.append("وجود ضغط شراء مباشر على دفتر الأوامر (Bids)")
    elif depth_analysis["pressure"] == "SELL_PRESSURE":
        short_score += 5
        short_reasons.append("وجود ضغط بيع مباشر على دفتر الأوامر (Asks)")

    # =====================================================
    # DAILY TREND
    # =====================================================

    if tf1d["bull"] >= 4:

        long_score += 18

        long_reasons.append(
            "اليومي يدعم الاتجاه الصاعد"
        )

    elif tf1d["bull"] >= 3:

        long_score += 10

    if tf1d["bear"] >= 4:

        short_score += 18

        short_reasons.append(
            "اليومي يدعم الاتجاه الهابط"
        )

    elif tf1d["bear"] >= 3:

        short_score += 10

    # =====================================================
    # 4H
    # =====================================================

    if tf4h["bull"] >= 4:

        long_score += 18

        long_reasons.append(
            "4H يدعم الصعود"
        )

    elif tf4h["bull"] >= 3:

        long_score += 10

    if tf4h["bear"] >= 4:

        short_score += 18

        short_reasons.append(
            "4H يدعم الهبوط"
        )

    elif tf4h["bear"] >= 3:

        short_score += 10

    # =====================================================
    # 1H
    # =====================================================

    if tf1h["bull"] >= 4:

        long_score += 14

        long_reasons.append(
            "1H يؤكد تحسن الاتجاه"
        )

    elif tf1h["bull"] >= 3:

        long_score += 8

    if tf1h["bear"] >= 4:

        short_score += 14

        short_reasons.append(
            "1H يؤكد ضعف الاتجاه"
        )

    elif tf1h["bear"] >= 3:

        short_score += 8

    # =====================================================
    # 30M
    # =====================================================

    if tf30["bull"] >= 4:

        long_score += 10

        long_reasons.append(
            "30M يؤكد الزخم"
        )

    elif tf30["bull"] >= 3:

        long_score += 5

    if tf30["bear"] >= 4:

        short_score += 10

        short_reasons.append(
            "30M يؤكد الهبوط"
        )

    elif tf30["bear"] >= 3:

        short_score += 5

    # =====================================================
    # 15M
    # =====================================================

    if tf15["bull"] >= 4:

        long_score += 10

        long_reasons.append(
            "15M يعطي تأكيد الدخول"
        )

    elif tf15["bull"] >= 3:

        long_score += 5

    if tf15["bear"] >= 4:

        short_score += 10

        short_reasons.append(
            "15M يعطي تأكيد الهبوط"
        )

    elif tf15["bear"] >= 3:

        short_score += 5

    # =====================================================
    # RSI
    # =====================================================

    rsi15 = tf15["rsi"]

    if rsi15 is not None:

        if 42 <= rsi15 <= 60:

            long_score += 5

            long_reasons.append(
                "RSI في منطقة مناسبة لبداية الصعود"
            )

        elif 60 < rsi15 <= 68:

            long_score += 2

        if 68 <= rsi15 <= 82:

            short_score += 5

            short_reasons.append(
                "RSI مرتفع"
            )

        if rsi15 < 30:

            # لا نعطي Long قوي لمجرد oversold
            long_score += 2

    # =====================================================
    # MACD
    # =====================================================

    if tf15["macd_hist"] is not None:

        if tf15["macd_hist"] > 0:

            long_score += 5

            long_reasons.append(
                "MACD إيجابي"
            )

        else:

            short_score += 4

            short_reasons.append(
                "MACD سلبي"
            )

    if tf1h["macd_hist"] is not None:

        if tf1h["macd_hist"] > 0:

            long_score += 4

        else:

            short_score += 4

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.10:

        long_score += 4

        long_reasons.append(
            "Volume أعلى من المتوسط"
        )

    if tf15["volume_trend"] >= 1.05:

        long_score += 5

        long_reasons.append(
            "الحجم يتحسن تدريجيًا"
        )

    if (
        tf15["volume_trend"] < 0.85
        and tf15["change"] < 0
    ):

        short_score += 5

        short_reasons.append(
            "الحجم يضعف مع الهبوط"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    accumulation = (

        tf15["change20"] <= 3.0

        and tf15["change5"] <= 3.0

        and tf15["change"] > -2.0

        and tf15["volume_trend"] >= 1.02

        and rsi15 is not None

        and 38 <= rsi15 <= 62

        and tf15["range_position"] <= 0.70

        and not (
            tf15["change5"] >= 5
        )
    )

    if accumulation:

        long_score += 18

        long_reasons.append(
            "تجميع بعد هبوط سابق قبل الانطلاق"
        )

    # =====================================================
    # EARLY MOMENTUM
    # =====================================================

    early_momentum = (

        tf15["change"] > 0

        and tf15["change5"] > -2

        and tf15["volume_trend"] >= 1.05

        and (
            tf15["macd_hist"] is not None
            and tf15["macd_hist"] > 0
        )
    )

    if early_momentum:

        long_score += 8

        long_reasons.append(
            "بداية تحسن Momentum قبل الحركة الكبيرة"
        )

    # =====================================================
    # DISTRIBUTION
    # =====================================================

    distribution = (

        tf1h["change20"] >= 5

        and (
            tf15["change"] < 0

            or tf15["volume_trend"] < 0.90

            or (
                tf15["macd_hist"] is not None
                and tf15["macd_hist"] < 0
            )
        )
    )

    if distribution:

        short_score += 18

        short_reasons.append(
            "Distribution وخروج سيولة بعد صعود سابق"
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

        long_score -= 25

        long_reasons.append(
            "Late Pump — ممنوع مطاردة العملة"
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
            "ضغط بيع قوي — ليس تجميعًا آمنًا"
        )

    # =====================================================
    # OVERHEATED
    # =====================================================

    overheated = (

        (
            tf4h["rsi"] is not None
            and tf4h["rsi"] >= 78
        )

        or

        (
            tf1d["rsi"] is not None
            and tf1d["rsi"] >= 78
        )
    )

    if overheated:

        long_score -= 15
        short_score += 5

        long_reasons.append(
            "4H/1D ساخن — خطر الدخول المتأخر"
        )

    # =====================================================
    # DAILY CONFLICT
    # =====================================================

    if tf1d["bear"] >= 4:

        long_score -= 12

    if tf1d["bull"] >= 4:

        short_score -= 12

    # =====================================================
    # SUPPORT / RESISTANCE
    # =====================================================

    price = tf15["price"]

    resistance_distance = (
        (
            tf15["high20"]
            - price
        )
        / price
        * 100
        if price > 0
        else 0
    )

    support_distance = (
        (
            price
            - tf15["low20"]
        )
        / price
        * 100
        if price > 0
        else 0
    )

    if resistance_distance < 1.5:

        long_score -= 8

        long_reasons.append(
            "السعر قريب من مقاومة"
        )

    if support_distance < 1.5:

        short_score -= 5

        short_reasons.append(
            "السعر قريب من دعم"
        )

    # =====================================================
    # RANGE / QUANTITATIVE ZONE
    # =====================================================

    quantitative_zone = (

        tf15["range_position"] <= 0.65

        and tf15["change20"] <= 3

        and not late_pump
    )

    if quantitative_zone:

        long_score += 6

        long_reasons.append(
            "داخل نطاق كمي منخفض نسبيًا"
        )

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

    # Strong early long
    if (

        long_score >= 70

        and long_score >= short_score + 15

        and accumulation

        and not late_pump

        and not strong_dump

        and not overheated
    ):

        signal = "EARLY_LONG"

    # Strong short
    elif (

        short_score >= 70

        and short_score >= long_score + 15

        and distribution
    ):

        signal = "SHORT"

    # Watch long
    elif (

        long_score >= 55

        and long_score >= short_score + 10

        and not late_pump

        and not strong_dump
    ):

        signal = "WATCH_LONG"

    # Watch short
    elif (

        short_score >= 55

        and short_score >= long_score + 10

        and distribution
    ):

        signal = "WATCH_SHORT"

    return {

        "symbol": symbol,

        "price": price,

        "signal": signal,

        "long_score": long_score,
        "short_score": short_score,

        "candidate_score": 0,

        "rsi15": tf15["rsi"],
        "rsi1h": tf1h["rsi"],
        "rsi4h": tf4h["rsi"],
        "rsi1d": tf1d["rsi"],

        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],
        "ema200": tf15["ema200"],

        "macd": tf15["macd"],
        "macd_signal": tf15["macd_signal"],
        "macd_hist": tf15["macd_hist"],

        "bb_middle": tf15["bb_middle"],
        "bb_upper": tf15["bb_upper"],
        "bb_lower": tf15["bb_lower"],

        "volume_ratio": tf15["volume_ratio"],
        "volume_trend": tf15["volume_trend"],

        "change15": tf15["change"],
        "change30": tf30["change"],
        "change1h": tf1h["change"],
        "change4h": tf4h["change"],
        "change1d": tf1d["change"],

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
        "overheated": overheated,

        "quantitative_zone": quantitative_zone,

        "depth_analysis": depth_analysis,
        "health_scan": health_scan,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons
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

        # =================================================
        # LIQUIDITY FILTER
        # =================================================

        if quote_volume < 500_000:
            continue

        # =================================================
        # QUANTITATIVE CANDIDATE SCORE
        # =================================================

        candidate_score = 0

        # العملات الهابطة التي تستحق البحث
        if daily_change <= -3:

            candidate_score += 20

        elif daily_change >= 10:

            # منع مطاردة العملات المنفجرة
            candidate_score -= 20

        # هبوط شديد جدًا
        if daily_change <= -12:

            candidate_score -= 15

        # نطاق الهبوط المناسب للبحث عن بداية تجميع
        if -8 <= daily_change <= -3:

            candidate_score += 10

        # هبوط متوسط وليس انهيارًا
        if -12 < daily_change < -8:

            candidate_score += 5

        # تحسن نسبي
        if daily_change > -3 and daily_change < 2:

            candidate_score += 3

        # =================================================
        # VOLUME / LIQUIDITY BONUS
        # =================================================

        if quote_volume >= 5_000_000:

            candidate_score += 3

        if quote_volume >= 20_000_000:

            candidate_score += 3

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change,
                candidate_score
            )
        )

    # =====================================================
    # IMPORTANT:
    # لا نأخذ أعلى Volume فقط.
    # نرتب أولًا حسب فرصة الاكتشاف المبكر.
    # =====================================================

    candidates.sort(
        key=lambda x: (
            x[3],
            x[1]
        ),
        reverse=True
    )

    # نفحص عددًا أكبر حتى لا نفوّت العملات الهابطة
    candidates = candidates[:limit * 3]

    results = []

    for (
        symbol,
        quote_volume,
        daily_change,
        candidate_score
    ) in candidates:

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                result["quote_volume"] = (
                    quote_volume
                )

                result["daily_change"] = (
                    daily_change
                )

                result["candidate_score"] = (
                    candidate_score
                )

                # تحديث فحص الأمان بالسيولة الحقيقية للرمز
                result["health_scan"] = check_asset_health(
                    symbol,
                    quote_volume=quote_volume,
                    daily_change=daily_change
                )

                results.append(
                    result
                )

                print(
                    "SCAN OK:",
                    symbol,
                    "CAND:",
                    candidate_score,
                    "SIGNAL:",
                    result["signal"],
                    "LONG:",
                    result["long_score"],
                    "SHORT:",
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
    # FINAL RANKING
    # =====================================================

    def rank(result):

        signal_bonus = {

            "EARLY_LONG": 80,
            "SHORT": 75,

            "WATCH_LONG": 35,
            "WATCH_SHORT": 35,

            "WAIT": 0
        }.get(
            result["signal"],
            0
        )

        direction_score = max(
            result["long_score"],
            result["short_score"]
        )

        difference = abs(
            result["long_score"]
            - result["short_score"]
        )

        candidate_bonus = min(
            30,
            result.get(
                "candidate_score",
                0
            )
        )

        accumulation_bonus = (
            25
            if result.get(
                "accumulation"
            )
            else 0
        )

        late_penalty = (
            40
            if result.get(
                "late_pump"
            )
            else 0
        )

        overheated_penalty = (
            25
            if result.get(
                "overheated"
            )
            else 0
        )

        return (

            signal_bonus

            + direction_score

            + difference

            + candidate_bonus

            + accumulation_bonus

            - late_penalty

            - overheated_penalty
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

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = (
            price
            - atr_value * 0.20
        )

        entry_high = (
            price
            + atr_value * 0.10
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
                    price
                    + risk * 1.5
                ),

            "tp2":
                format_price(
                    price
                    + risk * 2.5
                ),

            "tp3":
                format_price(
                    price
                    + risk * 4.0
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
            price
            - atr_value * 0.10
        )

        entry_high = (
            price
            + atr_value * 0.20
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
                    price
                    - risk * 1.5
                ),

            "tp2":
                format_price(
                    price
                    - risk * 2.5
                ),

            "tp3":
                format_price(
                    price
                    - risk * 4.0
                )
        }

    return None


# =========================================================
# RESEARCH REPORT GENERATOR (EVIDENCE-BASED)
# =========================================================

def generate_evidence_report(result, trade_setup=None):

    if not result:
        return "لا توجد بيانات متاحة لإنشاء التقرير."

    symbol = result["symbol"]
    price = format_price(result["price"])
    signal = result["signal"]
    long_score = result["long_score"]
    short_score = result["short_score"]
    depth = result.get("depth_analysis", {})
    health = result.get("health_scan", {})

    direction_ar = (
        "صاعد (Bullish)" if signal in ["EARLY_LONG", "WATCH_LONG"]
        else "هابط (Bearish)" if signal in ["SHORT", "WATCH_SHORT"]
        else "محايد / انتظار (Neutral)"
    )

    report = []
    report.append("=========================================================")
    report.append(f"📊 تقرير بحثي مبني على الأدلة والذكاء الاصطناعي (EVIDENCE REPORT): {symbol}")
    report.append("=========================================================")
    report.append(f"• السعر الحالي: {price} USDT")
    report.append(f"• اتجاه السوق المقترح: {direction_ar} | الإشارة: {signal}")
    report.append(f"• تقييم الشراء (Long Score): {long_score}/100 | تقييم البيع (Short Score): {short_score}/100")
    report.append("")
    report.append("🔍 1. تحليل السيولة وضغط الأوامر (Market Liquidity & Depth):")
    report.append(f"   - حالة ضغط الأوامر: {depth.get('pressure', 'N/A')}")
    report.append(f"   - نسبة توازن السيولة (Bid/Ask Imbalance): {depth.get('imbalance_ratio', 1.0):.2f}")
    report.append("")
    report.append("🛡️ 2. فحص الأمان وصحة الأصل (Asset Health & Risk Scan):")
    report.append(f"   - درجة الأمان والسيولة: {health.get('health_score', 100)}/100")
    report.append(f"   - حالة الأصل: {'آمن للتداول' if health.get('is_healthy', True) else 'عالي المخاطر'}")
    if health.get("flags"):
        report.append(f"   - تنبيهات المخاطر: {', '.join(health.get('flags', []))}")
    report.append("")
    report.append("📌 3. الأدلة والأسباب الفنية (Evidence & Reasons):")
    reasons = result.get("long_reasons" if "LONG" in signal else "short_reasons", [])
    if reasons:
        for r in reasons:
            report.append(f"   ✓ {r}")
    else:
        report.append("   - لا توجد أسباب اتجاهية قوية حالياً، السوق في حالة انتظار.")

    if trade_setup:
        report.append("")
        report.append("🎯 4. خطة التداول وتحديد المخاطر (Trade Setup & Risk Context):")
        report.append(f"   - الاتجاه: {trade_setup.get('side')}")
        report.append(f"   - منطقة الدخول: {trade_setup.get('entry')}")
        report.append(f"   - وقف الخسارة (Stop Loss): {trade_setup.get('stop')}")
        report.append(f"   - الهدف الأول (TP1): {trade_setup.get('tp1')}")
        report.append(f"   - الهدف الثاني (TP2): {trade_setup.get('tp2')}")
        report.append(f"   - الهدف الثالث (TP3): {trade_setup.get('tp3')}")

    report.append("=========================================================")
    return "\n".join(report)
