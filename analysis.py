import requests
import time
import math

BINANCE_FAPI = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})


def api_get(path, params=None, timeout=15):
    url = BINANCE_FAPI + path

    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("BINANCE ERROR:", e)
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
    data = api_get("/fapi/v1/ticker/24hr")

    if not data:
        return []

    return data


def get_klines(symbol, interval="15m", limit=100):
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
    except:
        return None


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

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

    return sum(trs[-period:]) / period


def average(values):
    if not values:
        return 0

    return sum(values) / len(values)


def pct_change(old, new):
    if old == 0:
        return 0

    return ((new - old) / old) * 100


def analyze_symbol(symbol, interval="15m"):
    klines = get_klines(symbol, interval, 120)

    if not klines or len(klines) < 60:
        return None

    try:
        opens = [float(x[1]) for x in klines]
        highs = [float(x[2]) for x in klines]
        lows = [float(x[3]) for x in klines]
        closes = [float(x[4]) for x in klines]
        volumes = [float(x[5]) for x in klines]
        quote_volumes = [float(x[7]) for x in klines]

        price = closes[-1]

        ema9 = ema(closes, 9)
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)

        rsi_value = rsi(closes, 14)

        atr_value = atr(highs, lows, closes, 14)

        avg_volume_20 = average(volumes[-20:])
        avg_volume_5 = average(volumes[-5:])

        volume_ratio = (
            avg_volume_5 / avg_volume_20
            if avg_volume_20
            else 0
        )

        change_15 = pct_change(closes[-16], price)
        change_30 = pct_change(closes[-31], price)

        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])

        range_pct = pct_change(recent_low, recent_high)

        # ------------------------------------------------
        # ACCUMULATION / EARLY LONG
        # ------------------------------------------------

        long_score = 0

        # العملة كانت هابطة
        if change_30 < -2:
            long_score += 15

        if change_15 < 0:
            long_score += 5

        # بدأ السعر يستعيد EMA9
        if price > ema9:
            long_score += 15

        # EMA9 يتحسن مقابل EMA20
        if ema9 > ema20:
            long_score += 15

        # RSI يخرج من منطقة الضعف
        if rsi_value and 42 <= rsi_value <= 58:
            long_score += 15

        # دخول حجم
        if volume_ratio >= 1.15:
            long_score += 15

        # تماسك نسبي بدل الانفجار
        if range_pct < 8:
            long_score += 10

        # السعر ليس بعيدًا جدًا عن EMA20
        if ema20:
            distance = abs((price - ema20) / ema20) * 100

            if distance < 4:
                long_score += 10

        # ------------------------------------------------
        # LATE TREND / POSSIBLE SHORT
        # ------------------------------------------------

        short_score = 0

        if change_30 > 5:
            short_score += 15

        if change_15 > 2:
            short_score += 10

        if price < ema9:
            short_score += 15

        if ema9 < ema20:
            short_score += 15

        if rsi_value and rsi_value >= 68:
            short_score += 15

        if volume_ratio >= 1.30:
            short_score += 10

        # شمعة حديثة قوية ثم ضعف
        previous_high = max(highs[-10:-2])

        if price < previous_high:
            short_score += 10

        # ATR يساعد على معرفة هل الحركة كبيرة
        if atr_value and price:
            atr_pct = (atr_value / price) * 100

            if atr_pct > 1:
                short_score += 10

        # ------------------------------------------------
        # CLASSIFICATION
        # ------------------------------------------------

        signal = "WAIT"

        if long_score >= 65 and long_score > short_score:
            signal = "EARLY_LONG"

        elif short_score >= 65 and short_score > long_score:
            signal = "SHORT"

        elif long_score >= 50 and long_score > short_score:
            signal = "WATCH_LONG"

        elif short_score >= 50 and short_score > long_score:
            signal = "WATCH_SHORT"

        return {
            "symbol": symbol,
            "price": price,
            "rsi": rsi_value,
            "ema9": ema9,
            "ema20": ema20,
            "ema50": ema50,
            "volume_ratio": volume_ratio,
            "change_15m": change_15,
            "change_30m": change_30,
            "range_pct": range_pct,
            "long_score": long_score,
            "short_score": short_score,
            "signal": signal
        }

    except Exception as e:
        print("ANALYSIS ERROR", symbol, e)
        return None


def scan_market(limit=40):
    """
    يبحث عن:
    1- العملات الهابطة التي بدأت تجمع.
    2- العملات التي أصبحت ترند وبدأ يظهر عليها ضعف.
    """

    tickers = get_tickers()

    if not tickers:
        return []

    candidates = []

    for ticker in tickers:
        symbol = ticker.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        try:
            quote_volume = float(ticker.get("quoteVolume", 0))
            price_change = float(ticker.get("priceChangePercent", 0))
        except:
            continue

        # فلترة أولية للسيولة
        if quote_volume < 1_000_000:
            continue

        # لا نريد العملات عديمة الحركة
        if abs(price_change) < 0.5:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                price_change
            )
        )

    # نبدأ بالأكثر سيولة
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[:limit]

    results = []

    for symbol, quote_volume, price_change in candidates:

        result = analyze_symbol(symbol, "15m")

        if not result:
            continue

        result["quote_volume"] = quote_volume
        result["daily_change"] = price_change

        if result["signal"] != "WAIT":
            results.append(result)

        # تخفيف الضغط على Binance
        time.sleep(0.08)

    results.sort(
        key=lambda x: max(
            x["long_score"],
            x["short_score"]
        ),
        reverse=True
    )

    return results


def format_price(price):
    if price is None:
        return "-"

    if price >= 1000:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.4f}"

    if price >= 0.01:
        return f"{price:.6f}"

    return f"{price:.10f}"


def prepare_trade(result):
    price = result["price"]

    atr_value = abs(
        result["ema20"] - price
    )

    # لا نستخدم ATR الحقيقي هنا إذا كان غير متوفر
    # لذلك نستخدم نسبة محافظة من السعر.

    if result["signal"] in ("EARLY_LONG", "WATCH_LONG"):

        entry_low = price * 0.995
        entry_high = price * 1.005

        stop = price * 0.975

        risk = price - stop

        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 4

        return {
            "side": "LONG",
            "entry": f"{format_price(entry_low)} - {format_price(entry_high)}",
            "stop": format_price(stop),
            "tp1": format_price(tp1),
            "tp2": format_price(tp2),
            "tp3": format_price(tp3)
        }

    if result["signal"] in ("SHORT", "WATCH_SHORT"):

        entry_low = price * 0.995
        entry_high = price * 1.005

        stop = price * 1.025

        risk = stop - price

        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 4

        return {
            "side": "SHORT",
            "entry": f"{format_price(entry_low)} - {format_price(entry_high)}",
            "stop": format_price(stop),
            "tp1": format_price(tp1),
            "tp2": format_price(tp2),
            "tp3": format_price(tp3)
        }

    return None
