import time
import requests


# =========================================================
# CONFIG
# =========================================================

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/5.0"
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
            r.text[:200]
        )

    except Exception as e:
        print(
            "BINANCE REQUEST ERROR:",
            repr(e)
        )

    return None


# =========================================================
# KLINES
# =========================================================

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

    if isinstance(data, list) and len(data) >= 60:
        return data

    return None


# =========================================================
# TICKERS
# =========================================================

def get_tickers():

    data = api_get(
        FUTURES_URL,
        "/fapi/v1/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    return []


# =========================================================
# MATH
# =========================================================

def average(values):

    return (
        sum(values) / len(values)
        if values else 0
    )


def pct(old, new):

    if old in (None, 0):
        return 0

    return ((new - old) / old) * 100


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


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(
    symbol,
    interval,
    limit=180
):

    klines = get_klines(
        symbol,
        interval,
        limit
    )

    if not klines:
        return None

    if len(klines) < 60:
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

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

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
        if avg20 > 0
        else 0
    )

    volume_trend = (
        avg5 / previous5
        if previous5 > 0
        else 1
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    bull = 0
    bear = 0

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

    # -----------------------------------------------------
    # REAL CANDLE MOVEMENTS
    # -----------------------------------------------------

    change1 = pct(
        closes[-2],
        closes[-1]
    )

    change3 = pct(
        closes[-4],
        closes[-1]
    )

    change5 = pct(
        closes[-6],
        closes[-1]
    )

    change10 = pct(
        closes[-11],
        closes[-1]
    )

    change20 = pct(
        closes[-21],
        closes[-1]
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

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "bull": bull,
        "bear": bear,

        "change1": change1,
        "change3": change3,
        "change5": change5,
        "change10": change10,
        "change20": change20,

        "high20": max(
            highs[-20:]
        ),

        "low20": min(
            lows[-20:]
        )
    }


# =========================================================
# FULL SYMBOL ANALYSIS
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

    # =====================================================
    # ALL TIMEFRAMES
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
        180
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

        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # DAILY TREND
    # =====================================================

    if tf1d["bull"] >= 4:

        long_score += 20

        long_reasons.append(
            "اليومي صاعد بقوة"
        )

    elif tf1d["bull"] >= 3:

        long_score += 14

        long_reasons.append(
            "اليومي يدعم الصعود"
        )

    elif tf1d["bull"] >= 2:

        long_score += 7

    if tf1d["bear"] >= 4:

        short_score += 20

        short_reasons.append(
            "اليومي هابط بقوة"
        )

    elif tf1d["bear"] >= 3:

        short_score += 14

        short_reasons.append(
            "اليومي يدعم الهبوط"
        )

    elif tf1d["bear"] >= 2:

        short_score += 7

    # =====================================================
    # 4H TREND
    # =====================================================

    if tf4h["bull"] >= 4:

        long_score += 20

        long_reasons.append(
            "4H صاعد بقوة"
        )

    elif tf4h["bull"] >= 3:

        long_score += 14

        long_reasons.append(
            "4H صاعد"
        )

    elif tf4h["bull"] >= 2:

        long_score += 7

    if tf4h["bear"] >= 4:

        short_score += 20

        short_reasons.append(
            "4H هابط بقوة"
        )

    elif tf4h["bear"] >= 3:

        short_score += 14

        short_reasons.append(
            "4H هابط"
        )

    elif tf4h["bear"] >= 2:

        short_score += 7

    # =====================================================
    # 1H
    # =====================================================

    if tf1h["bull"] >= 4:

        long_score += 15

        long_reasons.append(
            "1H صاعد بقوة"
        )

    elif tf1h["bull"] >= 3:

        long_score += 10

        long_reasons.append(
            "1H صاعد"
        )

    elif tf1h["bull"] >= 2:

        long_score += 5

    if tf1h["bear"] >= 4:

        short_score += 15

        short_reasons.append(
            "1H هابط بقوة"
        )

    elif tf1h["bear"] >= 3:

        short_score += 10

        short_reasons.append(
            "1H هابط"
        )

    elif tf1h["bear"] >= 2:

        short_score += 5

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

    r15 = tf15["rsi"]
    r1h = tf1h["rsi"]
    r4h = tf4h["rsi"]
    r1d = tf1d["rsi"]

    if r15 is not None:

        if 42 <= r15 <= 62:

            long_score += 5

            long_reasons.append(
                "RSI مناسب للشراء"
            )

        elif 35 <= r15 < 42:

            long_score += 3

        if 68 <= r15 <= 78:

            short_score += 5

            short_reasons.append(
                "RSI مرتفع"
            )

        if r15 >= 80:

            short_score += 8

    # =====================================================
    # HIGHER TF RSI PROTECTION
    # =====================================================

    # مهم جدًا:
    # منع Long لمجرد أن كل EMA أخضر
    # إذا كان السوق في تشبع شديد.

    if r4h is not None and r4h >= 85:

        long_score -= 12

        long_reasons.append(
            "RSI 4H مرتفع - خطر تصحيح"
        )

    if r1d is not None and r1d >= 80:

        long_score -= 12

        long_reasons.append(
            "RSI اليومي مرتفع - خطر تصحيح"
        )

    if r4h is not None and r4h <= 25:

        short_score -= 8

    if r1d is not None and r1d <= 25:

        short_score -= 8

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.10:

        long_score += 5

        long_reasons.append(
            "الحجم يدعم الحركة"
        )

    if tf15["volume_trend"] >= 1.05:

        long_score += 5

        long_reasons.append(
            "الحجم يتحسن"
        )

    if (
        tf15["volume_trend"] < 0.90
        and tf15["change1"] < 0
    ):

        short_score += 5

        short_reasons.append(
            "ضعف الحجم مع الهبوط"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    accumulation = (

        abs(tf15["change10"]) <= 3.0

        and abs(tf30["change5"]) <= 4.0

        and tf15["volume_trend"] >= 1.02

        and r15 is not None
        and 38 <= r15 <= 62

        and tf15["price"]
        >= tf15["low20"] * 1.005

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

        tf1h["change20"] >= 5

        and (
            tf15["change1"] < 0
            or tf15["volume_trend"] < 0.90
        )

    )

    if distribution:

        short_score += 12

        short_reasons.append(
            "احتمال توزيع وفقد زخم"
        )

    # =====================================================
    # LATE PUMP
    # =====================================================

    late_pump = (

        tf15["change3"] >= 4

        or tf30["change3"] >= 6

        or tf1h["change5"] >= 8

        or tf4h["change5"] >= 15

        or tf1d["change5"] >= 25

    )

    if late_pump:

        long_score -= 18

        long_reasons.append(
            "الحركة متأخرة - لا تطارد Pump"
        )

    # =====================================================
    # STRONG DUMP
    # =====================================================

    strong_dump = (

        tf15["change1"] <= -3

        and tf15["volume_ratio"] >= 1.30

    )

    if strong_dump:

        long_score -= 18

        long_reasons.append(
            "ضغط بيع قوي"
        )

    # =====================================================
    # DAILY / 4H CONFLICT
    # =====================================================

    daily_bull = tf1d["bull"] >= 3
    daily_bear = tf1d["bear"] >= 3

    four_bull = tf4h["bull"] >= 3
    four_bear = tf4h["bear"] >= 3

    if daily_bear:

        long_score -= 8

    if daily_bull:

        short_score -= 8

    if four_bear:

        long_score -= 6

    if four_bull:

        short_score -= 6

    # =====================================================
    # SHORT MOMENTUM
    # =====================================================

    if (

        tf15["change1"] < 0

        and tf30["change1"] < 0

        and tf1h["change1"] < 0

    ):

        short_score += 5

        short_reasons.append(
            "الزخم القصير سلبي"
        )

    # =====================================================
    # LONG MOMENTUM
    # =====================================================

    if (

        tf15["change1"] > 0

        and tf30["change1"] > 0

        and tf1h["change1"] > 0

    ):

        long_score += 5

        long_reasons.append(
            "الزخم القصير متوافق"
        )

    # =====================================================
    # SCORE LIMIT
    # =====================================================

    long_score = max(
        0,
        min(
            100,
            int(long_score)
        )
    )

    short_score = max(
        0,
        min(
            100,
            int(short_score)
        )
    )

    # =====================================================
    # SIGNAL
    # =====================================================

    signal = "WAIT"

    # Strong Early Long
    if (

        long_score >= 70

        and long_score >= short_score + 15

        and not strong_dump

        and not late_pump

    ):

        signal = "EARLY_LONG"

    # Strong Short
    elif (

        short_score >= 70

        and short_score >= long_score + 15

    ):

        signal = "SHORT"

    # Watch Long
    elif (

        long_score >= 55

        and long_score >= short_score + 10

        and not strong_dump

    ):

        signal = "WATCH_LONG"

    # Watch Short
    elif (

        short_score >= 55

        and short_score >= long_score + 10

    ):

        signal = "WATCH_SHORT"

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

        "volume_ratio":
            tf15["volume_ratio"],

        "volume_trend":
            tf15["volume_trend"],

        "change15":
            tf15["change1"],

        "change30":
            tf30["change1"],

        "change1h":
            tf1h["change1"],

        "change4h":
            tf4h["change1"],

        "change1d":
            tf1d["change1"],

        "atr":
            tf15["atr"],

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

        "accumulation":
            accumulation,

        "distribution":
            distribution,

        "late_pump":
            late_pump,

        "strong_dump":
            strong_dump,

        "long_reasons":
            long_reasons,

        "short_reasons":
            short_reasons
    }


# =========================================================
# FAST SCANNER
# =========================================================

def scan_market(limit=80):

    tickers = get_tickers()

    if not tickers:

        print(
            "SCAN: Binance returned no tickers"
        )

        return []

    candidates = []

    # =====================================================
    # FAST FILTER
    # =====================================================

    for ticker in tickers:

        symbol = ticker.get(
            "symbol",
            ""
        )

        if not symbol.endswith("USDT"):
            continue

        # Remove leveraged tokens

        blocked = (
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        )

        if any(
            x in symbol
            for x in blocked
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

            last_price = float(
                ticker.get(
                    "lastPrice",
                    0
                )
            )

        except Exception:

            continue

        if last_price <= 0:
            continue

        # -------------------------------------------------
        # LIQUIDITY
        # -------------------------------------------------

        if quote_volume < 1_000_000:
            continue

        # -------------------------------------------------
        # Don't require daily pump.
        #
        # This is important for finding accumulation.
        # -------------------------------------------------

        candidates.append({

            "symbol":
                symbol,

            "quote_volume":
                quote_volume,

            "daily_change":
                daily_change,

            "last_price":
                last_price

        })

    # =====================================================
    # RANK CANDIDATES
    # =====================================================

    def candidate_score(x):

        change = abs(
            x["daily_change"]
        )

        volume_score = min(
            x["quote_volume"]
            / 10_000_000,
            20
        )

        movement_score = min(
            change,
            20
        )

        return (
            volume_score
            + movement_score
        )

    candidates.sort(
        key=candidate_score,
        reverse=True
    )

    # More candidates than before
    candidates = candidates[:limit]

    print(
        "SCAN CANDIDATES:",
        len(candidates)
    )

    results = []

    # =====================================================
    # FULL ANALYSIS
    # =====================================================

    for candidate in candidates:

        symbol = candidate["symbol"]

        try:

            result = analyze_symbol(
                symbol
            )

            if result is None:
                continue

            result["quote_volume"] = (
                candidate["quote_volume"]
            )

            result["daily_change"] = (
                candidate["daily_change"]
            )

            # -------------------------------------------------
            # IMPORTANT:
            # Keep WATCH signals too.
            # -------------------------------------------------

            if result["signal"] != "WAIT":

                results.append(
                    result
                )

                print(
                    "SCAN FOUND:",
                    symbol,
                    result["signal"],
                    "L:",
                    result["long_score"],
                    "S:",
                    result["short_score"]
                )

        except Exception as e:

            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        time.sleep(
            0.04
        )

    # =====================================================
    # PRIORITY
    # =====================================================

    priority = {

        "EARLY_LONG": 5,

        "SHORT": 5,

        "WATCH_LONG": 3,

        "WATCH_SHORT": 3

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
            ),

            x.get(
                "quote_volume",
                0
            )

        ),

        reverse=True

    )

    # =====================================================
    # RETURN TOP 10
    # =====================================================

    return results[:10]


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

    if signal == "WAIT":
        return None

    price = result["price"]

    atr_value = result.get(
        "atr"
    )

    if not atr_value or atr_value <= 0:

        atr_value = (
            price * 0.01
        )

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
            price - stop
        )

        return {

            "side":
                "LONG",

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
                    + risk * 4
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
            stop - price
        )

        return {

            "side":
                "SHORT",

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
                    - risk * 4
                )

        }

    return None
