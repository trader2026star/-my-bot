import time
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

def api_get(base, path, params=None, timeout=8):
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


def get_klines(symbol, interval, limit=200):

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    # Futures
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


# =========================================================
# MATH
# =========================================================

def average(values):
    return sum(values) / len(values) if values else 0


def pct(old, new):

    if old is None or old == 0:
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

    avg20 = average(volumes[-20:])
    avg10 = average(volumes[-10:])
    avg5 = average(volumes[-5:])
    previous5 = average(volumes[-10:-5])

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

    # -----------------------------------------------------
    # EMA STRUCTURE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # MOVEMENT
    # -----------------------------------------------------

    change = pct(
        closes[-2],
        closes[-1]
    )

    change3 = (
        pct(closes[-4], closes[-1])
        if len(closes) >= 4
        else 0
    )

    change5 = (
        pct(closes[-6], closes[-1])
        if len(closes) >= 6
        else 0
    )

    change10 = (
        pct(closes[-11], closes[-1])
        if len(closes) >= 11
        else 0
    )

    change20 = (
        pct(closes[-21], closes[-1])
        if len(closes) >= 21
        else 0
    )

    # -----------------------------------------------------
    # RANGE / POSITION
    # -----------------------------------------------------

    high20 = max(highs[-20:])
    low20 = min(lows[-20:])

    range20 = high20 - low20

    if range20 > 0:

        position20 = (
            (price - low20)
            / range20
        ) * 100

    else:

        position20 = 50

    # -----------------------------------------------------
    # RECENT LOW / RECOVERY
    # -----------------------------------------------------

    low10 = min(lows[-10:])
    high10 = max(highs[-10:])

    recovery_from_low = pct(
        low10,
        price
    )

    # -----------------------------------------------------
    # CANDLE BODY
    # -----------------------------------------------------

    candle_range = highs[-1] - lows[-1]

    if candle_range > 0:

        close_position = (
            (closes[-1] - lows[-1])
            / candle_range
        ) * 100

    else:

        close_position = 50

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

        "avg10_volume": avg10,

        "bull": bull,
        "bear": bear,

        "change": change,
        "change3": change3,
        "change5": change5,
        "change10": change10,
        "change20": change20,

        "high20": high20,
        "low20": low20,
        "position20": position20,

        "low10": low10,
        "high10": high10,

        "recovery_from_low": recovery_from_low,
        "close_position": close_position
    }


# =========================================================
# FULL MULTI-TIMEFRAME ANALYSIS
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

    # -----------------------------------------------------
    # GET TIMEFRAMES
    # -----------------------------------------------------

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
    # DAILY TREND
    # =====================================================

    if tf1d["bull"] >= 3:

        long_score += 20

        long_reasons.append(
            "1D يدعم الاتجاه الصاعد"
        )

    elif tf1d["bull"] >= 2:

        long_score += 10

    if tf1d["bear"] >= 3:

        short_score += 20

        short_reasons.append(
            "1D يدعم الاتجاه الهابط"
        )

    elif tf1d["bear"] >= 2:

        short_score += 10

    # =====================================================
    # 4H TREND
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
            "1H يؤكد الصعود"
        )

    elif tf1h["bull"] >= 2:

        long_score += 8

    if tf1h["bear"] >= 3:

        short_score += 15

        short_reasons.append(
            "1H يؤكد الهبوط"
        )

    elif tf1h["bear"] >= 2:

        short_score += 8

    # =====================================================
    # 30M
    # =====================================================

    if tf30["bull"] >= 3:

        long_score += 10

        long_reasons.append(
            "30M يؤكد الحركة"
        )

    elif tf30["bull"] >= 2:

        long_score += 5

    if tf30["bear"] >= 3:

        short_score += 10

        short_reasons.append(
            "30M يؤكد الضعف"
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

    rsi1h = tf1h["rsi"]
    rsi4h = tf4h["rsi"]
    rsi1d = tf1d["rsi"]

    if rsi15 is not None:

        # منطقة مناسبة للـ LONG
        if 40 <= rsi15 <= 60:

            long_score += 5

            long_reasons.append(
                "RSI 15m داخل منطقة مناسبة قبل الحركة"
            )

        elif 60 < rsi15 <= 68:

            long_score += 3

        # RSI منخفض مع بداية تحسن
        if rsi15 < 35:

            long_score += 3

            long_reasons.append(
                "RSI منخفض واحتمال بداية ارتداد"
            )

        # Short
        if 68 <= rsi15 <= 82:

            short_score += 5

            short_reasons.append(
                "RSI مرتفع"
            )

    # =====================================================
    # VOLUME
    # =====================================================

    if tf15["volume_ratio"] >= 1.05:

        long_score += 4

        long_reasons.append(
            "الحجم أعلى من متوسطه"
        )

    if tf15["volume_trend"] >= 1.05:

        long_score += 5

        long_reasons.append(
            "الحجم يتحسن تدريجيًا"
        )

    if (
        tf15["volume_trend"] < 0.88
        and tf15["change"] < 0
    ):

        short_score += 5

        short_reasons.append(
            "ضعف الحجم مع استمرار الضغط"
        )

    # =====================================================
    # EARLY ACCUMULATION
    # =====================================================

    # العملة لا تزال قريبة من منطقة القاع
    near_low = (
        tf15["position20"] <= 55
    )

    # لم تتحرك بقوة بعد
    not_pumped = (
        tf15["change20"] <= 5
        and tf30["change20"] <= 8
    )

    # بدأت تستعيد السعر
    recovering = (
        tf15["change5"] > -1.5
        and tf15["change3"] > -1
        and tf15["close_position"] >= 55
    )

    # الحجم يتحسن
    volume_improving = (
        tf15["volume_trend"] >= 1.02
    )

    # RSI ليس في منطقة مطاردة
    rsi_ok = (
        rsi15 is not None
        and 35 <= rsi15 <= 65
    )

    accumulation = (
        near_low
        and not_pumped
        and recovering
        and volume_improving
        and rsi_ok
    )

    if accumulation:

        long_score += 18

        long_reasons.append(
            "🟢 العملة هابطة وقريبة من القاع وبدأت تجمع سيولة قبل الحركة"
        )

    # =====================================================
    # EARLY BREAKOUT
    # =====================================================

    early_breakout = (
        tf15["price"] > tf15["ema9"]
        and tf15["ema9"] > tf15["ema20"]
        and tf15["volume_trend"] >= 1.05
        and tf15["change5"] > 0
        and tf15["change5"] < 5
    )

    if early_breakout:

        long_score += 8

        long_reasons.append(
            "بداية كسر إيجابي بدون Pump متأخر"
        )

    # =====================================================
    # RECOVERY AFTER DUMP
    # =====================================================

    recovery_after_dump = (
        tf15["change20"] <= -3
        and tf15["change5"] > -1
        and tf15["recovery_from_low"] >= 1
        and tf15["volume_trend"] >= 1.02
    )

    if recovery_after_dump:

        long_score += 10

        long_reasons.append(
            "هبوط سابق ثم بدأ استرداد من القاع"
        )

    # =====================================================
    # DISTRIBUTION
    # =====================================================

    distribution = (
        tf1h["change20"] >= 5
        and (
            tf15["change"] < 0
            or tf15["change5"] < 0
            or tf15["volume_trend"] < 0.92
        )
    )

    if distribution:

        short_score += 18

        short_reasons.append(
            "السعر صعد سابقًا وبدأ يفقد الزخم والسيولة"
        )

    # =====================================================
    # SHORT BREAKDOWN
    # =====================================================

    short_breakdown = (
        tf15["price"] < tf15["ema9"]
        and tf15["price"] < tf15["ema20"]
        and tf15["change5"] < -1
        and tf15["volume_ratio"] >= 1.05
    )

    if short_breakdown:

        short_score += 10

        short_reasons.append(
            "كسر هابط مع حجم يدعم البيع"
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
            "🚫 الحركة انفجرت بالفعل - ممنوع مطاردة Pump"
        )

    # =====================================================
    # STRONG DUMP
    # =====================================================

    strong_dump = (
        tf15["change5"] <= -4
        and tf15["volume_ratio"] >= 1.5
    )

    if strong_dump:

        long_score -= 20

        long_reasons.append(
            "ضغط بيع قوي - لا يتم اقتناص السقوط مباشرة"
        )

    # =====================================================
    # OVERHEATED
    # =====================================================

    overheated = (
        (
            rsi4h is not None
            and rsi4h >= 80
        )
        or
        (
            rsi1d is not None
            and rsi1d >= 80
        )
    )

    if overheated:

        long_score -= 15
        short_score += 4

        long_reasons.append(
            "4H/1D ساخن جدًا - الدخول متأخر"
        )

    # =====================================================
    # DAILY CONFLICT
    # =====================================================

    if tf1d["bear"] >= 3:

        long_score -= 10

    if tf1d["bull"] >= 3:

        short_score -= 10

    # =====================================================
    # STRONG LONG CONFIRMATION
    # =====================================================

    multi_long = (
        tf15["bull"] >= 2
        and tf30["bull"] >= 2
        and tf1h["bull"] >= 2
    )

    if multi_long:

        long_score += 5

    # =====================================================
    # STRONG SHORT CONFIRMATION
    # =====================================================

    multi_short = (
        tf15["bear"] >= 2
        and tf30["bear"] >= 2
        and tf1h["bear"] >= 2
    )

    if multi_short:

        short_score += 5

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

    # -----------------------------------------------------
    # EARLY LONG
    # -----------------------------------------------------

    if (
        long_score >= 70
        and long_score >= short_score + 15
        and not late_pump
        and not strong_dump
        and not overheated
    ):

        signal = "EARLY_LONG"

    # -----------------------------------------------------
    # SHORT
    # -----------------------------------------------------

    elif (
        short_score >= 70
        and short_score >= long_score + 15
    ):

        signal = "SHORT"

    # -----------------------------------------------------
    # WATCH LONG
    # -----------------------------------------------------

    elif (
        long_score >= 55
        and long_score >= short_score + 10
        and not strong_dump
    ):

        signal = "WATCH_LONG"

    # -----------------------------------------------------
    # WATCH SHORT
    # -----------------------------------------------------

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

        "volume_ratio":
            tf15["volume_ratio"],

        "volume_trend":
            tf15["volume_trend"],

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

        "overheated":
            overheated,

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

        # تجاهل الرموز غير المناسبة
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

        # سيولة أساسية
        if quote_volume < 500_000:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change
            )
        )

    if not candidates:
        return []

    # =====================================================
    # المرحلة الأولى:
    # نأخذ مجموعة واسعة بدل أعلى 15 فقط
    # =====================================================

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    # حد آمن للـ Render
    candidates = candidates[:40]

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

            if not result:
                continue

            result["quote_volume"] = (
                quote_volume
            )

            result["daily_change"] = (
                daily_change
            )

            # =================================================
            # فلترة ذكية:
            # لا نريد مجرد عملة صاعدة.
            # نريد فرصة مبكرة أو ضعف واضح.
            # =================================================

            useful = (
                result["signal"]
                in [
                    "EARLY_LONG",
                    "SHORT",
                    "WATCH_LONG",
                    "WATCH_SHORT"
                ]
                or
                result["accumulation"]
                or
                result["distribution"]
            )

            if useful:

                results.append(
                    result
                )

                print(
                    "SCAN CANDIDATE:",
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

        # تخفيف الضغط على Binance وRender
        time.sleep(0.06)

    # =====================================================
    # RANKING
    # =====================================================

    def rank(result):

        signal = result.get(
            "signal",
            "WAIT"
        )

        long_score = result.get(
            "long_score",
            0
        )

        short_score = result.get(
            "short_score",
            0
        )

        direction = max(
            long_score,
            short_score
        )

        difference = abs(
            long_score
            - short_score
        )

        signal_bonus = {
            "EARLY_LONG": 60,
            "SHORT": 60,
            "WATCH_LONG": 30,
            "WATCH_SHORT": 30,
            "WAIT": 0
        }.get(
            signal,
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

        # مكافأة للعملة التي لم تنفجر بعد
        early_bonus = 0

        if (
            not result.get("late_pump")
            and not result.get("overheated")
        ):
            early_bonus = 8

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
            + early_bonus
            + liquidity_bonus
        )

    results.sort(
        key=rank,
        reverse=True
    )

    # =====================================================
    # إزالة التكرار
    # =====================================================

    final_results = []
    seen = set()

    for result in results:

        symbol = result["symbol"]

        if symbol in seen:
            continue

        seen.add(symbol)

        final_results.append(
            result
        )

        if len(final_results) >= 8:
            break

    print(
        "SCAN FINAL RESULTS:",
        [
            (
                x["symbol"],
                x["signal"],
                x["long_score"],
                x["short_score"]
            )
            for x in final_results
        ]
    )

    return final_results


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
# TRADE PREPARATION
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

    # حماية في حالة ATR غير متاح
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

    # WAIT
    return None
