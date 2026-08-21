import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/Final-4.0"
})


# =========================================================
# BINANCE
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

        print("BINANCE ERROR:", r.status_code, r.text[:200])

    except Exception as e:
        print("BINANCE REQUEST ERROR:", repr(e))

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

    if isinstance(data, list):
        return data

    return []


# =========================================================
# MATH
# =========================================================

def average(values):
    return sum(values) / len(values) if values else 0


def pct(old, new):

    if old in (None, 0):
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


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(symbol, interval, limit=220):

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

    avg20 = average(volumes[-20:])
    avg5 = average(volumes[-5:])
    previous5 = average(volumes[-10:-5])

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

    # EMA20 / EMA50
    if e20 and e50:

        if e20 > e50:
            bull += 1
        else:
            bear += 1

    # EMA50 / EMA200
    if e50 and e200:

        if e50 > e200:
            bull += 1
        else:
            bear += 1

    # Price vs EMA20
    if e20:

        if price > e20:
            bull += 1
        else:
            bear += 1

    # Price vs EMA50
    if e50:

        if price > e50:
            bull += 1
        else:
            bear += 1

    # Price vs EMA200
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

        # IMPORTANT:
        # حركة الشمعة/الفترة الحالية
        "change": pct(
            closes[-2],
            closes[-1]
        ) if len(closes) >= 2 else 0,

        # حركة آخر 3 فترات
        "change3": pct(
            closes[-4],
            closes[-1]
        ) if len(closes) >= 4 else 0,

        # حركة آخر 6 فترات
        "change6": pct(
            closes[-7],
            closes[-1]
        ) if len(closes) >= 7 else 0,

        "high20": max(highs[-20:]),
        "low20": min(lows[-20:])
    }


# =========================================================
# SYMBOL ANALYSIS
# =========================================================

def analyze_symbol(symbol):

    symbol = (
        symbol.upper()
        .replace("/", "")
        .replace("-", "")
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    # -----------------------------------------------------
    # 5 TIMEFRAMES
    # -----------------------------------------------------

    with ThreadPoolExecutor(max_workers=5) as executor:

        futures = {
            "15m": executor.submit(
                analyze_timeframe,
                symbol,
                "15m",
                180
            ),

            "30m": executor.submit(
                analyze_timeframe,
                symbol,
                "30m",
                180
            ),

            "1h": executor.submit(
                analyze_timeframe,
                symbol,
                "1h",
                180
            ),

            "4h": executor.submit(
                analyze_timeframe,
                symbol,
                "4h",
                220
            ),

            "1d": executor.submit(
                analyze_timeframe,
                symbol,
                "1d",
                220
            )
        }

        data = {
            key: future.result()
            for key, future in futures.items()
        }

    tf15 = data["15m"]
    tf30 = data["30m"]
    tf1h = data["1h"]
    tf4h = data["4h"]
    tf1d = data["1d"]

    if not all([
        tf15,
        tf30,
        tf1h,
        tf4h,
        tf1d
    ]):
        print("TIMEFRAME DATA MISSING:", symbol)
        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # DAILY
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

    if tf30["bear"] >= 3:

        short_score += 10

        short_reasons.append(
            "30M يؤكد الهبوط"
        )

    # =====================================================
    # 15M
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

    rsi15 = tf15["rsi"]
    rsi4h = tf4h["rsi"]
    rsi1d = tf1d["rsi"]

    if rsi15 is not None:

        if 42 <= rsi15 <= 62:

            long_score += 5

            long_reasons.append(
                "RSI 15m مناسب للشراء"
            )

        elif 68 <= rsi15 <= 80:

            short_score += 5

            short_reasons.append(
                "RSI 15m مرتفع"
            )

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.10:

        long_score += 5

        long_reasons.append(
            "حجم تداول داعم"
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

        abs(tf15["change3"]) <= 1.5

        and abs(tf15["change6"]) <= 4

        and tf15["volume_trend"] >= 1.05

        and rsi15 is not None

        and 38 <= rsi15 <= 62

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

        tf1h["change6"] >= 4

        and (

            tf15["change"] < 0

            or tf15["volume_trend"] < 0.90

        )

    )

    if distribution:

        short_score += 15

        short_reasons.append(
            "احتمال توزيع وفقد زخم"
        )

    # =====================================================
    # LATE PUMP
    # =====================================================

    late_pump = (

        tf15["change6"] >= 5

        or tf30["change6"] >= 6

        or tf1h["change6"] >= 10

    )

    # =====================================================
    # OVERHEATED MARKET
    # =====================================================

    overheated = False

    if rsi4h is not None and rsi4h >= 78:
        overheated = True

    if rsi1d is not None and rsi1d >= 78:
        overheated = True

    # =====================================================
    # STRONG DUMP
    # =====================================================

    strong_dump = (

        tf15["change6"] <= -3

        and tf15["volume_ratio"] >= 1.30

    )

    # =====================================================
    # PROTECTION
    # =====================================================

    if late_pump:

        long_score -= 20

        long_reasons.append(
            "منع مطاردة Pump متأخر"
        )

    if overheated:

        long_score -= 25

        long_reasons.append(
            "RSI 4H/1D مرتفع - خطر دخول متأخر"
        )

    if distribution:

        long_score -= 10

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
    # SHORT OVERHEAT BONUS
    # =====================================================

    if overheated:

        short_score += 10

        short_reasons.append(
            "تشبع شراء على الفريمات الكبيرة"
        )

    # =====================================================
    # LIMIT SCORES
    # =====================================================

    long_score = max(
        0,
        min(100, int(long_score))
    )

    short_score = max(
        0,
        min(100, int(short_score))
    )

    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    signal = "WAIT"

    # Strong LONG
    if (
        long_score >= 75
        and long_score >= short_score + 20
        and not late_pump
        and not overheated
        and not strong_dump
        and not distribution
    ):

        signal = "EARLY_LONG"

    # Strong SHORT
    elif (
        short_score >= 75
        and short_score >= long_score + 20
    ):

        signal = "SHORT"

    # Watch LONG
    elif (
        long_score >= 55
        and long_score >= short_score + 10
        and not strong_dump
        and not overheated
    ):

        signal = "WATCH_LONG"

    # Watch SHORT
    elif (
        short_score >= 55
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

        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }


# =========================================================
# SCANNER
# =========================================================

def scan_one(symbol):

    try:
        return analyze_symbol(symbol)
    except Exception as e:
        print(
            "SCAN ERROR:",
            symbol,
            repr(e)
        )
        return None


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

        if any(x in symbol for x in [
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        ]):
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

        # سيولة كافية
        if quote_volume < 2_000_000:
            continue

        # لا نريد عملات ميتة
        if abs(daily_change) < 0.3:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change
            )
        )

    # نأخذ أعلى العملات من ناحية السيولة
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[:limit]

    results = []

    # تحليل متوازي حتى /scan لا يطول جدًا
    with ThreadPoolExecutor(max_workers=5) as executor:

        futures = [
            executor.submit(
                scan_one,
                item[0]
            )
            for item in candidates
        ]

        for future in as_completed(futures):

            result = future.result()

            if result:
                results.append(result)

    # =====================================================
    # SCORE FOR SCANNER
    # =====================================================

    def ranking(result):

        signal = result["signal"]

        signal_priority = {
            "EARLY_LONG": 5,
            "SHORT": 5,
            "WATCH_LONG": 3,
            "WATCH_SHORT": 3,
            "WAIT": 1
        }

        return (
            signal_priority.get(
                signal,
                0
            ),

            max(
                result["long_score"],
                result["short_score"]
            ),

            result["volume_ratio"]
        )

    results.sort(
        key=ranking,
        reverse=True
    )

    # =====================================================
    # IMPORTANT:
    # DO NOT RETURN EMPTY SCAN EASILY
    # =====================================================

    strong = [
        r for r in results
        if r["signal"] in (
            "EARLY_LONG",
            "SHORT",
            "WATCH_LONG",
            "WATCH_SHORT"
        )
    ]

    if strong:

        return strong[:8]

    # إذا لم توجد إشارات:
    # نعرض أفضل 5 مرشحين بدل نتيجة فارغة
    fallback = sorted(
        results,
        key=lambda x: max(
            x["long_score"],
            x["short_score"]
        ),
        reverse=True
    )

    for item in fallback[:5]:

        if item["long_score"] >= item["short_score"]:
            item["signal"] = "WATCH_LONG"
        else:
            item["signal"] = "WATCH_SHORT"

    return fallback[:5]


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

    signal = result["signal"]

    if signal == "WAIT":
        return None

    price = float(result["price"])

    atr_value = result.get("atr")

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.01

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = price - atr_value * 0.20
        entry_high = price + atr_value * 0.10

        stop = price - atr_value * 1.20

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

    # =====================================================
    # SHORT
    # =====================================================

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        entry_low = price - atr_value * 0.10
        entry_high = price + atr_value * 0.20

        stop = price + atr_value * 1.20

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
