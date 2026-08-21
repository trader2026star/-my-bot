import requests
import time
import math

BINANCE_FAPI = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Crypto-Zero-Reversal-Bot/1.0"
})

# =========================================================
# BINANCE API
# =========================================================

def api_get(path, params=None, timeout=12):
    try:
        r = SESSION.get(
            BINANCE_FAPI + path,
            params=params,
            timeout=timeout
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("BINANCE ERROR:", path, repr(e))
        return None


def get_futures_symbols():
    data = api_get("/fapi/v1/exchangeInfo")

    if not data:
        return []

    symbols = []

    for s in data.get("symbols", []):
        if (
            s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("contractType") == "PERPETUAL"
        ):
            symbols.append(s["symbol"])

    return symbols


def get_tickers():
    return api_get("/fapi/v1/ticker/24hr") or []


def get_klines(symbol, interval="15m", limit=150):
    return api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def get_price(symbol):
    data = api_get(
        "/fapi/v1/ticker/price",
        {"symbol": symbol}
    )

    if not data:
        return None

    try:
        return float(data["price"])
    except Exception:
        return None


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
            + result
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

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

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

    return sum(trs[-period:]) / period


def average(values):
    if not values:
        return 0

    return sum(values) / len(values)


def pct_change(old, new):
    if not old:
        return 0

    return ((new - old) / old) * 100


def safe_div(a, b):
    return a / b if b else 0


# =========================================================
# CANDLE DATA
# =========================================================

def parse_klines(klines):
    if not klines:
        return None

    try:
        return {
            "opens": [float(x[1]) for x in klines],
            "highs": [float(x[2]) for x in klines],
            "lows": [float(x[3]) for x in klines],
            "closes": [float(x[4]) for x in klines],
            "volumes": [float(x[5]) for x in klines],
            "quote_volumes": [float(x[7]) for x in klines]
        }
    except Exception:
        return None


# =========================================================
# SINGLE TIMEFRAME ANALYSIS
# =========================================================

def timeframe_analysis(symbol, interval="15m", limit=150):
    klines = get_klines(
        symbol,
        interval,
        limit
    )

    data = parse_klines(klines)

    if not data or len(data["closes"]) < 60:
        return None

    opens = data["opens"]
    highs = data["highs"]
    lows = data["lows"]
    closes = data["closes"]
    volumes = data["volumes"]
    quote_volumes = data["quote_volumes"]

    price = closes[-1]

    ema9 = ema(closes, 9)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi_value = rsi(closes, 14)
    atr_value = atr(
        highs,
        lows,
        closes,
        14
    )

    avg_vol_20 = average(volumes[-20:])
    avg_vol_5 = average(volumes[-5:])

    volume_ratio = safe_div(
        avg_vol_5,
        avg_vol_20
    )

    # Volume trend:
    # آخر 5 شموع مقابل الخمس السابقة
    last5 = average(volumes[-5:])
    previous5 = average(volumes[-10:-5])

    volume_trend = safe_div(
        last5,
        previous5
    )

    change_15 = (
        pct_change(closes[-16], price)
        if len(closes) >= 16
        else 0
    )

    change_30 = (
        pct_change(closes[-31], price)
        if len(closes) >= 31
        else 0
    )

    change_60 = (
        pct_change(closes[-61], price)
        if len(closes) >= 61
        else 0
    )

    recent_high_20 = max(highs[-20:])
    recent_low_20 = min(lows[-20:])

    range_pct = pct_change(
        recent_low_20,
        recent_high_20
    )

    atr_pct = safe_div(
        atr_value,
        price
    ) * 100

    # =====================================================
    # ACCUMULATION DETECTION
    # =====================================================

    # هل كان هناك هبوط قبل التماسك؟
    previous_drop = (
        change_60 < -4
        or change_30 < -2
    )

    # آخر 10 شموع لا تتحرك بعنف
    last10_high = max(highs[-10:])
    last10_low = min(lows[-10:])

    consolidation_pct = pct_change(
        last10_low,
        last10_high
    )

    consolidation = (
        consolidation_pct <= 7
    )

    # السعر قريب من قاع النطاق وليس عند قمة انفجارية
    range_position = safe_div(
        price - recent_low_20,
        recent_high_20 - recent_low_20
    )

    near_lower_range = (
        range_position <= 0.65
    )

    # Volume يزيد تدريجيًا
    gradual_volume = (
        volume_trend >= 1.05
        and volume_ratio >= 0.95
        and volume_ratio <= 2.20
    )

    # Momentum يتحسن بدون تشبع
    momentum_improving = (
        rsi_value is not None
        and 40 <= rsi_value <= 62
    )

    # EMA9 يتحسن
    ema_recovery = (
        ema9 is not None
        and ema20 is not None
        and (
            ema9 >= ema20
            or closes[-1] > ema9
        )
    )

    # هل حصل انفجار بالفعل؟
    exploded = (
        change_15 >= 8
        or change_30 >= 15
        or range_pct >= 18
        or (
            rsi_value is not None
            and rsi_value >= 78
        )
    )

    # =====================================================
    # LONG SCORE
    # =====================================================

    long_score = 0

    if previous_drop:
        long_score += 20

    if consolidation:
        long_score += 15

    if near_lower_range:
        long_score += 10

    if gradual_volume:
        long_score += 15

    if momentum_improving:
        long_score += 15

    if ema_recovery:
        long_score += 10

    # بداية اختراق وليست Pump
    if (
        price > ema20
        and change_15 > 0
        and change_15 < 5
    ):
        long_score += 10

    # خصم إذا انفجرت العملة
    if exploded:
        long_score -= 25

    # =====================================================
    # SHORT SCORE
    # =====================================================

    short_score = 0

    strong_rise = (
        change_60 > 5
        or change_30 > 4
    )

    if strong_rise:
        short_score += 20

    if change_15 > 2:
        short_score += 10

    if (
        rsi_value is not None
        and rsi_value >= 68
    ):
        short_score += 20

    # ضعف مقابل قمة حديثة
    previous_high = max(
        highs[-12:-2]
    )

    if price < previous_high:
        short_score += 10

    # فقدان EMA
    if (
        ema9 is not None
        and price < ema9
    ):
        short_score += 10

    if (
        ema9 is not None
        and ema20 is not None
        and ema9 < ema20
    ):
        short_score += 15

    # Volume عالي بدون استمرار قوي
    if (
        volume_ratio >= 1.30
        and change_15 < 3
    ):
        short_score += 10

    # ATR مرتفع = حركة ساخنة
    if atr_pct > 1.5:
        short_score += 5

    return {
        "price": price,
        "ema9": ema9,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi_value,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,
        "change_15m": change_15,
        "change_30m": change_30,
        "change_60m": change_60,
        "range_pct": range_pct,
        "consolidation_pct": consolidation_pct,
        "range_position": range_position,
        "exploded": exploded,
        "long_score": max(0, long_score),
        "short_score": max(0, short_score)
    }


# =========================================================
# FULL MULTI-TIMEFRAME ANALYSIS
# =========================================================

def analyze_symbol(symbol, interval="15m"):
    symbol = symbol.upper()

    tf15 = timeframe_analysis(
        symbol,
        "15m",
        150
    )

    if not tf15:
        return None

    # تأكيد الاتجاه من 1H
    tf1h = timeframe_analysis(
        symbol,
        "1h",
        120
    )

    if not tf1h:
        return None

    price = tf15["price"]

    long_score = tf15["long_score"]
    short_score = tf15["short_score"]

    # =====================================================
    # MULTI TIMEFRAME CONFIRMATION
    # =====================================================

    # LONG confirmation
    if (
        tf1h["price"] > tf1h["ema20"]
        and tf1h["ema9"] >= tf1h["ema20"]
    ):
        long_score += 15

    elif (
        tf1h["price"] > tf1h["ema9"]
    ):
        long_score += 8

    # SHORT confirmation
    if (
        tf1h["price"] < tf1h["ema20"]
        and tf1h["ema9"] <= tf1h["ema20"]
    ):
        short_score += 15

    elif (
        tf1h["price"] < tf1h["ema9"]
    ):
        short_score += 8

    # =====================================================
    # AVOID LATE LONG
    # =====================================================

    if (
        tf15["change_15m"] > 6
        or tf15["change_30m"] > 12
        or tf15["rsi"] >= 72
    ):
        long_score -= 20

    # =====================================================
    # AVOID EARLY SHORT
    # =====================================================

    if (
        tf15["change_15m"] < -5
        and tf15["rsi"] < 35
    ):
        short_score -= 15

    long_score = max(
        0,
        min(100, long_score)
    )

    short_score = max(
        0,
        min(100, short_score)
    )

    # =====================================================
    # CLASSIFICATION
    # =====================================================

    signal = "WAIT"

    if (
        long_score >= 75
        and long_score > short_score + 10
    ):
        signal = "EARLY_LONG"

    elif (
        short_score >= 75
        and short_score > long_score + 10
    ):
        signal = "SHORT"

    elif (
        long_score >= 60
        and long_score > short_score + 8
    ):
        signal = "WATCH_LONG"

    elif (
        short_score >= 60
        and short_score > long_score + 8
    ):
        signal = "WATCH_SHORT"

    # =====================================================
    # REASONS
    # =====================================================

    long_reasons = []

    if tf15["change_30m"] < -2:
        long_reasons.append("هبوط سابق")

    if tf15["consolidation_pct"] <= 7:
        long_reasons.append("تجميع/تماسك")

    if tf15["volume_trend"] >= 1.05:
        long_reasons.append("Volume يتحسن")

    if tf15["rsi"] and 40 <= tf15["rsi"] <= 62:
        long_reasons.append("الزخم يتحسن")

    if tf15["price"] > tf15["ema20"]:
        long_reasons.append("استعادة EMA20")

    if tf1h["price"] > tf1h["ema20"]:
        long_reasons.append("تأكيد 1H")

    short_reasons = []

    if tf15["change_30m"] > 4:
        short_reasons.append("صعود قوي")

    if tf15["rsi"] and tf15["rsi"] >= 68:
        short_reasons.append("RSI مرتفع")

    if tf15["price"] < tf15["ema9"]:
        short_reasons.append("فقد EMA9")

    if tf15["ema9"] < tf15["ema20"]:
        short_reasons.append("EMA سلبي")

    if tf15["volume_ratio"] >= 1.30:
        short_reasons.append("Volume مرتفع")

    if tf1h["price"] < tf1h["ema20"]:
        short_reasons.append("تأكيد هابط 1H")

    return {
        "symbol": symbol,
        "price": price,

        "rsi": tf15["rsi"],
        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],
        "atr": tf15["atr"],
        "atr_pct": tf15["atr_pct"],

        "volume_ratio": tf15["volume_ratio"],
        "volume_trend": tf15["volume_trend"],

        "change_15m": tf15["change_15m"],
        "change_30m": tf15["change_30m"],
        "change_60m": tf15["change_60m"],

        "range_pct": tf15["range_pct"],
        "consolidation_pct": tf15["consolidation_pct"],

        "long_score": int(long_score),
        "short_score": int(short_score),

        "signal": signal,

        "long_reasons": long_reasons,
        "short_reasons": short_reasons,

        "tf1h": tf1h
    }


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market(limit=30):
    """
    Scanner حقيقي:

    1. يجلب عملات Futures USDT.
    2. فلترة أولية بالسيولة والحركة.
    3. يحلل أفضل المرشحين.
    4. يستخدم 15m + 1h.
    5. يمنع الدخول المتأخر بعد Pump.
    """

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

        # استبعاد رموز غير مرغوبة
        if any(x in symbol for x in [
            "USDC",
            "BUSD"
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

        # سيولة دنيا
        if quote_volume < 2_000_000:
            continue

        # يجب أن يكون هناك حركة
        if abs(daily_change) < 0.5:
            continue

        candidates.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "daily_change": daily_change
        })

    # السيولة أولًا
    candidates.sort(
        key=lambda x: x["quote_volume"],
        reverse=True
    )

    # عدد محدود حتى لا نضغط API
    candidates = candidates[:limit]

    results = []

    for item in candidates:

        symbol = item["symbol"]

        try:
            result = analyze_symbol(
                symbol,
                "15m"
            )

            if result:

                result["quote_volume"] = (
                    item["quote_volume"]
                )

                result["daily_change"] = (
                    item["daily_change"]
                )

                # نعرض فقط المرشحين الحقيقيين
                if result["signal"] != "WAIT":
                    results.append(result)

        except Exception as e:
            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        # حماية من Rate Limit
        time.sleep(0.10)

    results.sort(
        key=lambda x: (
            max(
                x["long_score"],
                x["short_score"]
            ),
            x.get("quote_volume", 0)
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

    try:
        price = float(price)
    except Exception:
        return "-"

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

    if signal == "WAIT":
        return None

    price = result.get("price")

    if not price:
        return None

    atr_value = result.get("atr")

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.015

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = price - (
            atr_value * 0.35
        )

        entry_high = price + (
            atr_value * 0.15
        )

        stop = price - (
            atr_value * 1.20
        )

        risk = price - stop

        tp1 = price + (
            risk * 1.5
        )

        tp2 = price + (
            risk * 2.5
        )

        tp3 = price + (
            risk * 4.0
        )

        return {
            "side": "LONG",
            "entry_low": format_price(
                entry_low
            ),
            "entry_high": format_price(
                entry_high
            ),
            "entry": (
                f"{format_price(entry_low)}"
                f" - "
                f"{format_price(entry_high)}"
            ),
            "stop": format_price(stop),
            "tp1": format_price(tp1),
            "tp2": format_price(tp2),
            "tp3": format_price(tp3)
        }

    # =====================================================
    # SHORT
    # =====================================================

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        entry_low = price - (
            atr_value * 0.15
        )

        entry_high = price + (
            atr_value * 0.35
        )

        stop = price + (
            atr_value * 1.20
        )

        risk = stop - price

        tp1 = price - (
            risk * 1.5
        )

        tp2 = price - (
            risk * 2.5
        )

        tp3 = price - (
            risk * 4.0
        )

        return {
            "side": "SHORT",
            "entry_low": format_price(
                entry_low
            ),
            "entry_high": format_price(
                entry_high
            ),
            "entry": (
                f"{format_price(entry_low)}"
                f" - "
                f"{format_price(entry_high)}"
            ),
            "stop": format_price(stop),
            "tp1": format_price(tp1),
            "tp2": format_price(tp2),
            "tp3": format_price(tp3)
        }

    return None
