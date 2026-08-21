import requests
import time


# =========================================================
# BINANCE
# =========================================================

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})


# =========================================================
# REQUEST
# =========================================================

def request_json(base_url, path, params=None, timeout=12):

    try:
        response = SESSION.get(
            base_url + path,
            params=params,
            timeout=timeout
        )

        print(
            "BINANCE:",
            base_url,
            path,
            response.status_code
        )

        if response.status_code != 200:
            print(
                "BINANCE ERROR:",
                response.text[:500]
            )
            return None

        return response.json()

    except Exception as e:

        print(
            "BINANCE CONNECTION ERROR:",
            repr(e)
        )

        return None


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol, interval="15m", limit=120):

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    # Futures
    data = request_json(
        FUTURES_URL,
        "/fapi/v1/klines",
        params
    )

    if data and isinstance(data, list):
        return data

    # Fallback
    data = request_json(
        DATA_URL,
        "/api/v3/klines",
        params
    )

    if data and isinstance(data, list):
        return data

    return None


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    params = {
        "symbol": symbol.upper()
    }

    data = request_json(
        FUTURES_URL,
        "/fapi/v1/ticker/price",
        params
    )

    if data:
        try:
            return float(data["price"])
        except:
            pass

    data = request_json(
        DATA_URL,
        "/api/v3/ticker/price",
        params
    )

    if data:
        try:
            return float(data["price"])
        except:
            pass

    return None


# =========================================================
# TICKERS
# =========================================================

def get_tickers():

    data = request_json(
        FUTURES_URL,
        "/fapi/v1/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    data = request_json(
        DATA_URL,
        "/api/v3/ticker/24hr"
    )

    if isinstance(data, list):
        return data

    return []


# =========================================================
# FUTURES SYMBOLS
# =========================================================

def get_futures_symbols():

    data = request_json(
        FUTURES_URL,
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


# =========================================================
# MATH
# =========================================================

def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


def pct_change(old, new):

    if old == 0:
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

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

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
# TIMEFRAME ANALYSIS
# =========================================================

def analyze_timeframe(
    symbol,
    interval
):

    klines = get_klines(
        symbol,
        interval,
        120
    )

    if not klines:

        print(
            "NO DATA:",
            symbol,
            interval
        )

        return None

    if len(klines) < 60:

        print(
            "NOT ENOUGH DATA:",
            symbol,
            interval
        )

        return None

    try:

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

        change5 = pct_change(
            closes[-6],
            price
        )

        change15 = pct_change(
            closes[-16],
            price
        )

        change30 = pct_change(
            closes[-31],
            price
        )

        change60 = pct_change(
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

        if change60 > 0:
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

            "change5": change5,
            "change15": change15,
            "change30": change30,
            "change60": change60,

            "recent_high": recent_high,
            "recent_low": recent_low,

            "range_pct": range_pct,

            "bullish": bullish,
            "bearish": bearish
        }

    except Exception as e:

        print(
            "TIMEFRAME ERROR:",
            symbol,
            interval,
            repr(e)
        )

        return None


# =========================================================
# FULL COIN ANALYSIS
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

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    print(
        "ANALYZING:",
        symbol
    )

    tf15 = analyze_timeframe(
        symbol,
        "15m"
    )

    if not tf15:

        print(
            "15M FAILED:",
            symbol
        )

        return None

    tf1h = analyze_timeframe(
        symbol,
        "1h"
    )

    if not tf1h:

        print(
            "1H FAILED:",
            symbol
        )

        return None

    price = tf15["price"]

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # EARLY LONG BASE SCORE
    # =====================================================

    if tf15["change30"] < -1:

        long_score += 10
        long_reasons.append(
            "هبوط سابق"
        )

    if (
        tf15["change5"] > -0.5
        and tf15["change15"] < 1.5
    ):

        long_score += 10
        long_reasons.append(
            "توقف الهبوط"
        )

    if (
        tf15["ema9"]
        and price > tf15["ema9"]
    ):

        long_score += 10
        long_reasons.append(
            "استعادة EMA9"
        )

    if (
        tf15["ema9"]
        and tf15["ema20"]
        and tf15["ema9"] > tf15["ema20"]
    ):

        long_score += 10
        long_reasons.append(
            "تحسن الاتجاه"
        )

    if (
        tf15["rsi"] is not None
        and 40 <= tf15["rsi"] <= 62
    ):

        long_score += 10
        long_reasons.append(
            "RSI مناسب"
        )

    if tf15["volume_ratio"] >= 1.10:

        long_score += 10
        long_reasons.append(
            "دخول حجم"
        )

    if tf15["volume_trend"] >= 1.05:

        long_score += 10
        long_reasons.append(
            "الحجم يتزايد"
        )

    if (
        tf15["change15"] < 5
        and tf15["range_pct"] < 10
    ):

        long_score += 10
        long_reasons.append(
            "لم يحدث Pump كبير"
        )

    if tf1h["bullish"] >= 3:

        long_score += 10
        long_reasons.append(
            "تأكيد 1H"
        )

    if tf15["ema20"]:

        distance = abs(
            (
                price
                - tf15["ema20"]
            )
            / tf15["ema20"]
        ) * 100

        if distance <= 4:

            long_score += 10
            long_reasons.append(
                "قريب من EMA20"
            )

    # =====================================================
    # SHORT BASE SCORE
    # =====================================================

    if tf15["change30"] > 3:

        short_score += 10
        short_reasons.append(
            "صعود قوي"
        )

    if tf15["change15"] > 2:

        short_score += 10
        short_reasons.append(
            "صعود سريع"
        )

    if (
        tf15["ema9"]
        and price < tf15["ema9"]
    ):

        short_score += 10
        short_reasons.append(
            "كسر EMA9"
        )

    if (
        tf15["ema9"]
        and tf15["ema20"]
        and tf15["ema9"] < tf15["ema20"]
    ):

        short_score += 10
        short_reasons.append(
            "EMA9 تحت EMA20"
        )

    if (
        tf15["rsi"] is not None
        and tf15["rsi"] >= 68
    ):

        short_score += 10
        short_reasons.append(
            "RSI مرتفع"
        )

    if tf15["volume_ratio"] >= 1.30:

        short_score += 10
        short_reasons.append(
            "حجم مرتفع"
        )

    if tf15["volume_trend"] < 0.90:

        short_score += 10
        short_reasons.append(
            "ضعف الحجم"
        )

    if price < tf15["recent_high"]:

        short_score += 10
        short_reasons.append(
            "رفض من القمة"
        )

    if tf1h["bearish"] >= 3:

        short_score += 10
        short_reasons.append(
            "تأكيد 1H هابط"
        )

    if (
        tf15["atr"]
        and price
        and (
            tf15["atr"]
            / price
            * 100
        ) > 1
    ):

        short_score += 10
        short_reasons.append(
            "تقلب مرتفع"
        )

    # =====================================================
    # EARLY PUMP FILTER
    # =====================================================

    one_hour_move = tf15["change60"]
    fifteen_move = tf15["change15"]
    thirty_move = tf15["change30"]

    # كلما زادت الحركة، تقل صلاحية الدخول المبكر.
    if one_hour_move >= 4:
        long_score -= 10

    if one_hour_move >= 6:
        long_score -= 20

    if one_hour_move >= 8:
        long_score -= 35

    if fifteen_move >= 2:
        long_score -= 10

    if fifteen_move >= 3:
        long_score -= 20

    if fifteen_move >= 5:
        long_score -= 35

    if thirty_move >= 4:
        long_score -= 15

    if thirty_move >= 6:
        long_score -= 25

    # منع مطاردة الانفجار
    if (
        one_hour_move >= 8
        or fifteen_move >= 5
        or thirty_move >= 6
    ):

        long_score = min(
            long_score,
            49
        )

    # =====================================================
    # ACCUMULATION BONUS
    # =====================================================

    if (
        tf15["change30"] < 0
        and one_hour_move < 4
        and fifteen_move < 1.5
        and tf15["volume_trend"] >= 1.10
    ):

        long_score += 10
        long_reasons.append(
            "تجميع مبكر"
        )

    if (
        tf15["change30"] < -1
        and one_hour_move < 4
        and 0.8 <= tf15["volume_ratio"] <= 1.8
        and tf15["volume_trend"] >= 1.15
    ):

        long_score += 10
        long_reasons.append(
            "حجم يتزايد قبل الحركة"
        )

    # =====================================================
    # SHORT LATE-TREND FILTER
    # =====================================================

    if (
        one_hour_move >= 6
        and tf15["volume_trend"] < 1
    ):

        short_score += 10
        short_reasons.append(
            "ضعف بعد صعود"
        )

    if (
        one_hour_move >= 8
        and fifteen_move < 0
    ):

        short_score += 15
        short_reasons.append(
            "رفض بعد Pump"
        )

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
    # SIGNAL
    # =====================================================

    signal = "WAIT"

    # Early Long حقيقي:
    # لا نريد عملة تحركت بالفعل.
    if (
        long_score >= 70
        and long_score > short_score + 10
        and one_hour_move < 6
        and fifteen_move < 3
        and thirty_move < 5
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
        and one_hour_move < 8
        and fifteen_move < 4
    ):

        signal = "WATCH_LONG"

    elif (
        short_score >= 55
        and short_score > long_score + 5
    ):

        signal = "WATCH_SHORT"

    # =====================================================
    # FINAL LATE-PUMP PROTECTION
    # =====================================================

    if (
        signal == "EARLY_LONG"
        and (
            one_hour_move >= 8
            or fifteen_move >= 5
            or thirty_move >= 6
        )
    ):

        signal = "WAIT"

    return {

        "symbol": symbol,

        "price": price,

        "rsi": tf15["rsi"],

        "ema9": tf15["ema9"],
        "ema20": tf15["ema20"],
        "ema50": tf15["ema50"],

        "volume_ratio":
            tf15["volume_ratio"],

        "volume_trend":
            tf15["volume_trend"],

        "change_15m":
            tf15["change15"],

        "change_30m":
            tf15["change30"],

        "change_60m":
            tf15["change60"],

        "range_pct":
            tf15["range_pct"],

        "long_score":
            long_score,

        "short_score":
            short_score,

        "long_reasons":
            long_reasons,

        "short_reasons":
            short_reasons,

        "signal":
            signal,

        "atr":
            tf15["atr"],

        "tf1h_bullish":
            tf1h["bullish"],

        "tf1h_bearish":
            tf1h["bearish"]
    }


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market(limit=30):

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

        # سيولة أساسية
        if quote_volume < 2_000_000:
            continue

        # عملات شبه ميتة
        if abs(daily_change) < 0.5:
            continue

        # Pump يومي مبالغ فيه
        if daily_change > 30:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                daily_change
            )
        )

    # الأعلى سيولة أولًا
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[:limit]

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

            if result["signal"] != "WAIT":

                results.append(
                    result
                )

        except Exception as e:

            print(
                "SCAN ERROR:",
                symbol,
                repr(e)
            )

        # تخفيف الضغط على Binance
        time.sleep(0.10)

    # =====================================================
    # ترتيب خاص
    # =====================================================

    def ranking(item):

        signal = item.get(
            "signal",
            "WAIT"
        )

        score = max(
            item.get("long_score", 0),
            item.get("short_score", 0)
        )

        # أولوية Early Long
        if signal == "EARLY_LONG":
            priority = 3

        elif signal == "SHORT":
            priority = 2

        else:
            priority = 1

        return (
            priority,
            score
        )

    results.sort(
        key=ranking,
        reverse=True
    )

    return results


# =========================================================
# FORMAT PRICE
# =========================================================

def format_price(price):

    if price is None:
        return "-"

    try:
        price = float(price)
    except:
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
# PREPARE TRADE
# =========================================================

def prepare_trade(result):

    if not result:
        return None

    price = result.get(
        "price"
    )

    signal = result.get(
        "signal"
    )

    atr_value = result.get(
        "atr"
    )

    if not price:
        return None

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

        risk = price - stop

        if risk <= 0:
            return None

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

        risk = stop - price

        if risk <= 0:
            return None

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
