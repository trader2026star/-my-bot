import requests
import time
import math


# =========================================================
# BINANCE FUTURES SETTINGS
# =========================================================

BINANCE_FAPI = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# =========================================================
# BINANCE REQUEST
# =========================================================

def api_get(path, params=None, timeout=15):

    url = BINANCE_FAPI + path

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=timeout
        )

        response.raise_for_status()

        data = response.json()

        return data

    except requests.exceptions.RequestException as e:

        print(
            "BINANCE REQUEST ERROR:",
            path,
            params,
            repr(e)
        )

        return None

    except Exception as e:

        print(
            "BINANCE API ERROR:",
            path,
            repr(e)
        )

        return None


# =========================================================
# SYMBOLS
# =========================================================

def get_futures_symbols():

    data = api_get(
        "/fapi/v1/exchangeInfo"
    )

    if not data:
        return []

    symbols = []

    for item in data.get("symbols", []):

        if (
            item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
        ):
            symbols.append(
                item.get("symbol")
            )

    return symbols


def symbol_exists(symbol):

    symbol = symbol.upper()

    symbols = get_futures_symbols()

    return symbol in symbols


# =========================================================
# TICKERS
# =========================================================

def get_tickers():

    data = api_get(
        "/fapi/v1/ticker/24hr"
    )

    if not data:
        return []

    if not isinstance(data, list):
        return []

    return data


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol,
    interval="15m",
    limit=120
):

    return api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        }
    )


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    data = api_get(
        "/fapi/v1/ticker/price",
        {
            "symbol": symbol.upper()
        }
    )

    if not data:
        return None

    try:
        return float(
            data["price"]
        )

    except Exception:
        return None


# =========================================================
# MATH
# =========================================================

def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def pct_change(old, new):

    if old is None:
        return 0.0

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if not values:
        return None

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = average(
        values[:period]
    )

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
        ) + result

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

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
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
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:

        if avg_gain == 0:
            return 50.0

        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

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

        true_range = max(
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

        trs.append(
            true_range
        )

    if len(trs) < period:
        return None

    return average(
        trs[-period:]
    )


# =========================================================
# KLINE PARSER
# =========================================================

def parse_klines(klines):

    if not klines:
        return None

    try:

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

        quote_volumes = [
            float(x[7])
            for x in klines
        ]

        return {
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": volumes,
            "quote_volumes": quote_volumes
        }

    except Exception as e:

        print(
            "KLINE PARSE ERROR:",
            repr(e)
        )

        return None


# =========================================================
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(
    symbol,
    interval,
    limit=120
):

    klines = get_klines(
        symbol,
        interval,
        limit
    )

    if not klines:

        print(
            "NO KLINES:",
            symbol,
            interval
        )

        return None

    if len(klines) < 60:

        print(
            "INSUFFICIENT KLINES:",
            symbol,
            interval,
            len(klines)
        )

        return None

    data = parse_klines(
        klines
    )

    if not data:
        return None

    opens = data["opens"]
    highs = data["highs"]
    lows = data["lows"]
    closes = data["closes"]
    volumes = data["volumes"]

    price = closes[-1]

    ema9 = ema(
        closes,
        9
    )

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi_value = rsi(
        closes,
        14
    )

    atr_value = atr(
        highs,
        lows,
        closes,
        14
    )

    avg_volume_20 = average(
        volumes[-20:]
    )

    avg_volume_5 = average(
        volumes[-5:]
    )

    avg_volume_previous_5 = average(
        volumes[-10:-5]
    )

    volume_ratio = (
        avg_volume_5
        / avg_volume_20
        if avg_volume_20 > 0
        else 0
    )

    volume_trend = (
        avg_volume_5
        / avg_volume_previous_5
        if avg_volume_previous_5 > 0
        else 1
    )

    change_5 = pct_change(
        closes[-6],
        price
    )

    change_15 = pct_change(
        closes[-16],
        price
    )

    change_30 = pct_change(
        closes[-31],
        price
    )

    change_60 = pct_change(
        closes[-61],
        price
    )

    recent_high = max(
        highs[-20:]
    )

    recent_low = min(
        lows[-20:]
    )

    range_pct = pct_change(
        recent_low,
        recent_high
    )

    # =============================================
    # TREND
    # =============================================

    bullish = 0
    bearish = 0

    if ema9 and ema20:

        if ema9 > ema20:
            bullish += 1
        else:
            bearish += 1

    if ema20 and ema50:

        if ema20 > ema50:
            bullish += 1
        else:
            bearish += 1

    if price > ema20:
        bullish += 1
    else:
        bearish += 1

    if price > ema50:
        bullish += 1
    else:
        bearish += 1

    if change_60 > 0:
        bullish += 1
    else:
        bearish += 1

    return {
        "price": price,

        "ema9": ema9,
        "ema20": ema20,
        "ema50": ema50,

        "rsi": rsi_value,

        "atr": atr_value,

        "volume_ratio": volume_ratio,
        "volume_trend": volume_trend,

        "change_5m": change_5,
        "change_15m": change_15,
        "change_30m": change_30,
        "change_60m": change_60,

        "recent_high": recent_high,
        "recent_low": recent_low,

        "range_pct": range_pct,

        "bullish": bullish,
        "bearish": bearish
    }


# =========================================================
# MAIN ANALYSIS
# =========================================================

def analyze_symbol(
    symbol,
    interval="15m"
):

    symbol = (
        symbol
        .upper()
        .replace("/", "")
        .strip()
    )

    # -----------------------------------------------------
    # Validate symbol
    # -----------------------------------------------------

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    # -----------------------------------------------------
    # 15 MIN
    # -----------------------------------------------------

    tf15 = analyze_timeframe(
        symbol,
        "15m",
        120
    )

    if not tf15:

        print(
            "15M ANALYSIS FAILED:",
            symbol
        )

        return None

    # -----------------------------------------------------
    # 1 HOUR
    # -----------------------------------------------------

    tf1h = analyze_timeframe(
        symbol,
        "1h",
        120
    )

    if not tf1h:

        print(
            "1H ANALYSIS FAILED:",
            symbol
        )

        return None

    price = tf15["price"]

    # =====================================================
    # LONG SCORE
    # =====================================================

    long_score = 0
    long_reasons = []

    # 1. كان هابطًا على المدى القصير
    if tf15["change_30m"] < -1.0:

        long_score += 10

        long_reasons.append(
            "هبوط سابق"
        )

    # 2. توقف الهبوط
    if (
        tf15["change_5m"] > -0.5
        and tf15["change_15m"] > -1.5
    ):

        long_score += 10

        long_reasons.append(
            "توقف ضغط البيع"
        )

    # 3. السعر فوق EMA9
    if (
        tf15["ema9"]
        and price > tf15["ema9"]
    ):

        long_score += 10

        long_reasons.append(
            "استعادة EMA9"
        )

    # 4. EMA9 بدأ يتحسن
    if (
        tf15["ema9"]
        and tf15["ema20"]
        and tf15["ema9"] > tf15["ema20"]
    ):

        long_score += 10

        long_reasons.append(
            "EMA9 أعلى EMA20"
        )

    # 5. RSI منطقة انتقال
    if (
        tf15["rsi"] is not None
        and 42 <= tf15["rsi"] <= 62
    ):

        long_score += 10

        long_reasons.append(
            "RSI يتحسن"
        )

    # 6. Volume أعلى من المتوسط
    if tf15["volume_ratio"] >= 1.10:

        long_score += 10

        long_reasons.append(
            "دخول حجم"
        )

    # 7. Volume يتزايد تدريجيًا
    if tf15["volume_trend"] >= 1.05:

        long_score += 10

        long_reasons.append(
            "Volume في تحسن"
        )

    # 8. الحركة ليست Pump كبير
    if (
        tf15["change_15m"] < 5
        and tf15["range_pct"] < 10
    ):

        long_score += 10

        long_reasons.append(
            "لم تنفجر بعد"
        )

    # 9. تأكيد الساعة
    if tf1h["bullish"] >= 3:

        long_score += 10

        long_reasons.append(
            "تأكيد 1H"
        )

    # 10. السعر قريب من EMA20
    if tf15["ema20"]:

        distance = (
            abs(
                price
                - tf15["ema20"]
            )
            / tf15["ema20"]
        ) * 100

        if distance <= 4:

            long_score += 10

            long_reasons.append(
                "قريب من منطقة القيمة"
            )

    # =====================================================
    # SHORT SCORE
    # =====================================================

    short_score = 0
    short_reasons = []

    # 1. صعود سابق قوي
    if tf15["change_30m"] > 3:

        short_score += 10

        short_reasons.append(
            "صعود قوي سابق"
        )

    # 2. الحركة الأخيرة مبالغ فيها
    if tf15["change_15m"] > 2:

        short_score += 10

        short_reasons.append(
            "صعود سريع"
        )

    # 3. السعر تحت EMA9
    if (
        tf15["ema9"]
        and price < tf15["ema9"]
    ):

        short_score += 10

        short_reasons.append(
            "كسر EMA9"
        )

    # 4. EMA9 تحت EMA20
    if (
        tf15["ema9"]
        and tf15["ema20"]
        and tf15["ema9"] < tf15["ema20"]
    ):

        short_score += 10

        short_reasons.append(
            "EMA9 تحت EMA20"
        )

    # 5. RSI مرتفع
    if (
        tf15["rsi"] is not None
        and tf15["rsi"] >= 68
    ):

        short_score += 10

        short_reasons.append(
            "RSI مرتفع"
        )

    # 6. حجم قوي بعد حركة
    if tf15["volume_ratio"] >= 1.30:

        short_score += 10

        short_reasons.append(
            "حجم مرتفع"
        )

    # 7. ضعف Volume
    if tf15["volume_trend"] < 0.90:

        short_score += 10

        short_reasons.append(
            "ضعف الحجم"
        )

    # 8. فشل عند القمة
    previous_high = max(
        tf15["recent_high"],
        tf1h["recent_high"]
    )

    if price < previous_high:

        short_score += 10

        short_reasons.append(
            "رفض من القمة"
        )

    # 9. تأكيد الساعة
    if tf1h["bearish"] >= 3:

        short_score += 10

        short_reasons.append(
            "تأكيد 1H هابط"
        )

    # 10. ATR مرتفع
    if (
        tf15["atr"]
        and price
    ):

        atr_pct = (
            tf15["atr"]
            / price
        ) * 100

        if atr_pct > 1:

            short_score += 10

            short_reasons.append(
                "تقلب مرتفع"
            )

    # =====================================================
    # FILTER EXTREME PUMP
    # =====================================================

    # لا نريد الدخول Long بعد انفجار
    if tf15["change_15m"] >= 7:

        long_score -= 25

    # لا نريد Short عشوائي بعد شمعة واحدة
    if tf15["change_15m"] <= -7:

        short_score -= 20

    # =====================================================
    # CLASSIFICATION
    # =====================================================

    signal = "WAIT"

    if (
        long_score >= 70
        and long_score > short_score + 10
    ):

        signal = "EARLY_LONG"

    elif (
        short_score >= 70
        and short_score > long_score + 10
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

    # =====================================================
    # RESULT
    # =====================================================

    return {

        "symbol": symbol,

        "price": price,

        "rsi": tf15["rsi"],

        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],

        "volume_ratio": tf15["volume_ratio"],
        "volume_trend": tf15["volume_trend"],

        "change_15m": tf15["change_15m"],
        "change_30m": tf15["change_30m"],
        "change_60m": tf15["change_60m"],

        "range_pct": tf15["range_pct"],

        "long_score": max(
            0,
            min(100, long_score)
        ),

        "short_score": max(
            0,
            min(100, short_score)
        ),

        "long_reasons": long_reasons,

        "short_reasons": short_reasons,

        "signal": signal,

        "atr": tf15["atr"],

        "tf1h_bullish": tf1h["bullish"],

        "tf1h_bearish": tf1h["bearish"]
    }


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market(limit=30):

    tickers = get_tickers()

    if not tickers:

        print(
            "SCANNER: NO TICKERS"
        )

        return []

    candidates = []

    for ticker in tickers:

        symbol = ticker.get(
            "symbol",
            ""
        )

        if not symbol.endswith(
            "USDT"
        ):

            continue

        try:

            quote_volume = float(
                ticker.get(
                    "quoteVolume",
                    0
                )
            )

            price_change = float(
                ticker.get(
                    "priceChangePercent",
                    0
                )
            )

        except Exception:

            continue

        # -------------------------------------------------
        # Liquidity
        # -------------------------------------------------

        if quote_volume < 2_000_000:

            continue

        # -------------------------------------------------
        # Avoid dead coins
        # -------------------------------------------------

        if abs(price_change) < 0.5:

            continue

        # -------------------------------------------------
        # Avoid extreme 24h pumps
        # -------------------------------------------------

        if price_change > 30:

            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                price_change
            )
        )

    # الأكثر سيولة أولًا
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[
        :limit
    ]

    results = []

    for (
        symbol,
        quote_volume,
        price_change
    ) in candidates:

        try:

            result = analyze_symbol(
                symbol,
                "15m"
            )

            if not result:

                continue

            result[
                "quote_volume"
            ] = quote_volume

            result[
                "daily_change"
            ] = price_change

            if result[
                "signal"
            ] != "WAIT":

                results.append(
                    result
                )

        except Exception as e:

            print(
                "SCANNER ERROR:",
                symbol,
                repr(e)
            )

        # تخفيف الضغط
        time.sleep(0.10)

    results.sort(
        key=lambda x: max(
            x["long_score"],
            x["short_score"]
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
        "signal"
    )

    price = result.get(
        "price"
    )

    atr_value = result.get(
        "atr"
    )

    if not price:
        return None

    # -----------------------------------------------------
    # ATR fallback
    # -----------------------------------------------------

    if not atr_value or atr_value <= 0:

        atr_value = price * 0.01

    # =====================================================
    # LONG
    # =====================================================

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        entry_low = (
            price
            - atr_value * 0.25
        )

        entry_high = (
            price
            + atr_value * 0.15
        )

        stop = (
            price
            - atr_value * 1.25
        )

        risk = (
            price
            - stop
        )

        if risk <= 0:
            return None

        tp1 = (
            price
            + risk * 1.5
        )

        tp2 = (
            price
            + risk * 2.5
        )

        tp3 = (
            price
            + risk * 4.0
        )

        return {

            "side": "LONG",

            "entry": (
                f"{format_price(entry_low)}"
                f" - "
                f"{format_price(entry_high)}"
            ),

            "stop": format_price(
                stop
            ),

            "tp1": format_price(
                tp1
            ),

            "tp2": format_price(
                tp2
            ),

            "tp3": format_price(
                tp3
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
            - atr_value * 0.15
        )

        entry_high = (
            price
            + atr_value * 0.25
        )

        stop = (
            price
            + atr_value * 1.25
        )

        risk = (
            stop
            - price
        )

        if risk <= 0:
            return None

        tp1 = (
            price
            - risk * 1.5
        )

        tp2 = (
            price
            - risk * 2.5
        )

        tp3 = (
            price
            - risk * 4.0
        )

        return {

            "side": "SHORT",

            "entry": (
                f"{format_price(entry_low)}"
                f" - "
                f"{format_price(entry_high)}"
            ),

            "stop": format_price(
                stop
            ),

            "tp1": format_price(
                tp1
            ),

            "tp2": format_price(
                tp2
            ),

            "tp3": format_price(
                tp3
            )
        }

    return None
