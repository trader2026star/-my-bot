import time
import requests

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/4.0"
})


# =========================================================
# BINANCE API
# =========================================================

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

    if isinstance(data, list):
        return data

    data = api_get(
        DATA_URL,
        "/api/v3/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    return []


# =========================================================
# BASIC INDICATORS
# =========================================================

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

    # -----------------------------------------------------
    # REAL TIMEFRAME CHANGES
    # -----------------------------------------------------

    change1 = pct(
        closes[-2],
        price
    ) if len(closes) >= 2 else 0

    change3 = pct(
        closes[-4],
        price
    ) if len(closes) >= 4 else 0

    change5 = pct(
        closes[-6],
        price
    ) if len(closes) >= 6 else 0

    change10 = pct(
        closes[-11],
        price
    ) if len(closes) >= 11 else 0

    change20 = pct(
        closes[-21],
        price
    ) if len(closes) >= 21 else 0

    change50 = pct(
        closes[-51],
        price
    ) if len(closes) >= 51 else 0

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    high20 = max(highs[-20:])
    low20 = min(lows[-20:])

    high50 = max(highs[-50:])
    low50 = min(lows[-50:])

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
        "change50": change50,

        "high20": high20,
        "low20": low20,

        "high50": high50,
        "low50": low50
    }


# =========================================================
# MAIN ANALYSIS
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
    # 1D - MACRO TREND
    # =====================================================

    if tf1d["bull"] >= 4:
        long_score += 25
        long_reasons.append(
            "اليومي صاعد بقوة"
        )

    elif tf1d["bull"] >= 3:
        long_score += 18
        long_reasons.append(
            "اليومي يدعم الصعود"
        )

    elif tf1d["bull"] >= 2:
        long_score += 8

    if tf1d["bear"] >= 4:
        short_score += 25
        short_reasons.append(
            "اليومي هابط بقوة"
        )

    elif tf1d["bear"] >= 3:
        short_score += 18
        short_reasons.append(
            "اليومي يدعم الهبوط"
        )

    elif tf1d["bear"] >= 2:
        short_score += 8

    # =====================================================
    # 4H - MAIN TREND
    # =====================================================

    if tf4h["bull"] >= 4:
        long_score += 25
        long_reasons.append(
            "4H صاعد بقوة"
        )

    elif tf4h["bull"] >= 3:
        long_score += 18
        long_reasons.append(
            "4H صاعد"
        )

    elif tf4h["bull"] >= 2:
        long_score += 8

    if tf4h["bear"] >= 4:
        short_score += 25
        short_reasons.append(
            "4H هابط بقوة"
        )

    elif tf4h["bear"] >= 3:
        short_score += 18
        short_reasons.append(
            "4H هابط"
        )

    elif tf4h["bear"] >= 2:
        short_score += 8

    # =====================================================
    # 1H - CONFIRMATION
    # =====================================================

    if tf1h["bull"] >= 4:
        long_score += 15
        long_reasons.append(
            "1H يؤكد الاتجاه الصاعد"
        )

    elif tf1h["bull"] >= 3:
        long_score += 10
        long_reasons.append(
            "1H صاعد"
        )

    if tf1h["bear"] >= 4:
        short_score += 15
        short_reasons.append(
            "1H يؤكد الاتجاه الهابط"
        )

    elif tf1h["bear"] >= 3:
        short_score += 10
        short_reasons.append(
            "1H هابط"
        )

    # =====================================================
    # 30M - SETUP
    # =====================================================

    if tf30["bull"] >= 4:
        long_score += 10
        long_reasons.append(
            "30M يؤكد الصعود"
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
    # 15M - ENTRY TRIGGER
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
    rsi1h = tf1h["rsi"]
    rsi4h = tf4h["rsi"]

    if rsi15 is not None:

        if 40 <= rsi15 <= 62:
            long_score += 5
            long_reasons.append(
                "RSI 15M مناسب للشراء"
            )

        elif rsi15 < 30:
            long_score += 2

        if 68 <= rsi15 <= 82:
            short_score += 8
            short_reasons.append(
                "RSI 15M مرتفع"
            )

    # =====================================================
    # VOLUME / LIQUIDITY
    # =====================================================

    if tf15["volume_ratio"] >= 1.20:
        long_score += 7
        long_reasons.append(
            "ارتفاع واضح في الحجم"
        )

    elif tf15["volume_ratio"] >= 1.05:
        long_score += 3

    if tf15["volume_trend"] >= 1.15:
        long_score += 7
        long_reasons.append(
            "الحجم يتزايد"
        )

    elif tf15["volume_trend"] >= 1.05:
        long_score += 3

    if tf15["volume_trend"] < 0.85:
        short_score += 5
        short_reasons.append(
            "الحجم يفقد القوة"
        )

    # =====================================================
    # ACCUMULATION
    # =====================================================

    accumulation = (
        tf15["change20"] <= 4
        and tf15["change10"] <= 3
        and tf15["change5"] > -2.5
        and tf15["volume_trend"] >= 1.05
        and 38 <= rsi15 <= 62
        and tf1h["bull"] >= 2
    )

    if accumulation:
        long_score += 10
        long_reasons.append(
            "تجميع محتمل قبل الحركة"
        )

    # =====================================================
    # DISTRIBUTION
    # =====================================================

    distribution = (
        tf1h["change20"] >= 5
        and (
            tf15["change5"] < 0
            or tf15["volume_trend"] < 0.90
        )
        and rsi1h is not None
        and rsi1h >= 55
    )

    if distribution:
        short_score += 15
        short_reasons.append(
            "علامات توزيع وفقد زخم"
        )

    # =====================================================
    # LATE PUMP PROTECTION
    # =====================================================

    late_pump = (
        tf15["change5"] >= 4
        or tf30["change5"] >= 6
        or tf1h["change10"] >= 10
        or tf4h["change5"] >= 15
    )

    if late_pump:
        long_score -= 20
        long_reasons.append(
            "Pump متأخر - منع مطاردة السعر"
        )

    # =====================================================
    # STRONG DUMP
    # =====================================================

    strong_dump = (
        tf15["change5"] <= -3
        and tf15["volume_ratio"] >= 1.40
    )

    if strong_dump:
        long_score -= 25
        long_reasons.append(
            "ضغط بيع قوي - منع LONG"
        )

    # =====================================================
    # HIGHER TIMEFRAME CONFLICT
    # =====================================================

    daily_bull = tf1d["bull"] >= 3
    daily_bear = tf1d["bear"] >= 3

    four_hour_bull = tf4h["bull"] >= 3
    four_hour_bear = tf4h["bear"] >= 3

    # LONG conflict
    if daily_bear:
        long_score -= 15
        long_reasons.append(
            "اليومي ضد LONG"
        )

    if four_hour_bear:
        long_score -= 20
        long_reasons.append(
            "4H ضد LONG"
        )

    # SHORT conflict
    if daily_bull:
        short_score -= 15
        short_reasons.append(
            "اليومي ضد SHORT"
        )

    if four_hour_bull:
        short_score -= 20
        short_reasons.append(
            "4H ضد SHORT"
        )

    # =====================================================
    # 4H PRICE MOMENTUM
    # =====================================================

    if tf4h["change5"] > 0:
        long_score += 3

    if tf4h["change5"] < 0:
        short_score += 3

    # =====================================================
    # SCORE LIMIT
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

    # Strong LONG
    if (
        long_score >= 75
        and long_score >= short_score + 20
        and daily_bull
        and four_hour_bull
        and not late_pump
        and not strong_dump
    ):
        signal = "EARLY_LONG"

    # Strong SHORT
    elif (
        short_score >= 75
        and short_score >= long_score + 20
        and daily_bear
        and four_hour_bear
    ):
        signal = "SHORT"

    # Watch LONG
    elif (
        long_score >= 60
        and long_score >= short_score + 12
        and not strong_dump
    ):
        signal = "WATCH_LONG"

    # Watch SHORT
    elif (
        short_score >= 60
        and short_score >= long_score + 12
    ):
        signal = "WATCH_SHORT"

    # =====================================================
    # FINAL TREND
    # =====================================================

    if daily_bull and four_hour_bull:
        final_direction = "LONG"

    elif daily_bear and four_hour_bear:
        final_direction = "SHORT"

    elif (
        daily_bull
        and four_hour_bear
    ):
        final_direction = "CONFLICT"

    elif (
        daily_bear
        and four_hour_bull
    ):
        final_direction = "CONFLICT"

    else:
        final_direction = "NEUTRAL"

    # =====================================================
    # RETURN
    # =====================================================

    return {
        "symbol": symbol,
        "price": tf15["price"],

        "signal": signal,
        "direction": final_direction,

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

        "change15": tf15["change1"],
        "change30": tf30["change1"],
        "change1h": tf1h["change1"],
        "change4h": tf4h["change1"],
        "change1d": tf1d["change1"],

        "change15_period": tf15["change5"],
        "change30_period": tf30["change5"],
        "change1h_period": tf1h["change10"],
        "change4h_period": tf4h["change5"],
        "change1d_period": tf1d["change5"],

        "atr": tf15["atr"],

        "support": tf15["low20"],
        "resistance": tf15["high20"],

        "support50": tf15["low50"],
        "resistance50": tf15["high50"],

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
        "strong_dump": strong_dump,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }


# =========================================================
# MARKET SCANNER
# =========================================================

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

        # تجاهل العملات الغريبة
        if symbol.endswith("USDC"):
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

        # سيولة أفضل
        if quote_volume < 2_000_000:
            continue

        # لا نأخذ العملات الميتة
        if abs(daily_change) < 0.5:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change
            )
        )

    # السيولة أولًا
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[:limit]

    results = []

    for symbol, volume, daily_change in candidates:

        try:

            result = analyze_symbol(symbol)

            if result:

                result["quote_volume"] = volume
                result["daily_change"] = daily_change

                # لا نعرض WAIT في النتائج النهائية
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

    return results


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

    signal = result["signal"]

    if signal == "WAIT":
        return None

    price = float(result["price"])

    atr_value = result.get("atr")

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.01

    support = result.get(
        "support",
        price - atr_value
    )

    resistance = result.get(
        "resistance",
        price + atr_value
    )

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        # منطقة دخول حول السعر
        entry_low = price - (
            atr_value * 0.20
        )

        entry_high = price + (
            atr_value * 0.10
        )

        # دعم + ATR
        technical_stop = support - (
            atr_value * 0.25
        )

        atr_stop = price - (
            atr_value * 1.20
        )

        stop = min(
            technical_stop,
            atr_stop
        )

        # حماية من SL بعيد جدًا
        max_risk = price * 0.035

        if price - stop > max_risk:
            stop = price - max_risk

        risk = price - stop

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 4.0

        # لا نجعل TP أقل من المقاومة القريبة
        if resistance > price:
            tp1 = max(
                tp1,
                resistance
            )

        return {
            "side": "LONG",

            "entry":
                f"{format_price(entry_low)} - "
                f"{format_price(entry_high)}",

            "stop":
                format_price(stop),

            "tp1":
                format_price(tp1),

            "tp2":
                format_price(tp2),

            "tp3":
                format_price(tp3)
        }

    # =====================================================
    # SHORT
    # =====================================================

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

        technical_stop = resistance + (
            atr_value * 0.25
        )

        atr_stop = price + (
            atr_value * 1.20
        )

        stop = max(
            technical_stop,
            atr_stop
        )

        max_risk = price * 0.035

        if stop - price > max_risk:
            stop = price + max_risk

        risk = stop - price

        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 4.0

        if support < price:
            tp1 = min(
                tp1,
                support
            )

        return {
            "side": "SHORT",

            "entry":
                f"{format_price(entry_low)} - "
                f"{format_price(entry_high)}",

            "stop":
                format_price(stop),

            "tp1":
                format_price(tp1),

            "tp2":
                format_price(tp2),

            "tp3":
                format_price(tp3)
        }

    return None
