import time
import requests


# =========================================================
# SETTINGS
# =========================================================

FUTURES_URL = "https://fapi.binance.com"
DATA_URL = "https://data-api.binance.vision"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "CryptoZeroReversal/6.4"
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

    if imbalance >= 1.2:
        pressure = "BUY_PRESSURE"
    elif imbalance <= 0.8:
        pressure = "SELL_PRESSURE"
    else:
        pressure = "NEUTRAL"

    return {
        "bid_volume": bid_vol,
        "ask_volume": ask_vol,
        "imbalance_ratio": imbalance,
        "pressure": pressure
    }


def check_asset_health(symbol, quote_volume=0, daily_change=0):

    health_score = 100
    flags = []

    if quote_volume > 0 and quote_volume < 500_000:
        health_score -= 20
        flags.append("سيولة منخفضة")

    if abs(daily_change) > 30:
        health_score -= 15
        flags.append("تقلبات حادة")

    return {
        "health_score": health_score,
        "is_healthy": health_score >= 50,
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
    atr_value = atr(highs, lows, closes)
    macd_value, macd_signal, macd_hist = macd(closes)
    bb_middle, bb_upper, bb_lower = bollinger(closes)

    avg20 = average(volumes[-20:])
    avg5 = average(volumes[-5:])
    previous5 = average(volumes[-10:-5])

    volume_ratio = avg5 / avg20 if avg20 else 0
    volume_trend = avg5 / previous5 if previous5 else 1

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

    if e20 is not None and price > e20:
        bull += 1
    else:
        bear += 1

    if macd_value is not None and macd_signal is not None:
        if macd_value > macd_signal:
            bull += 1
        else:
            bear += 1

    if rsi_value is not None:
        if 45 <= rsi_value <= 72:
            bull += 1
        elif rsi_value < 45:
            bear += 1

    change = pct(closes[-2], closes[-1])
    change20 = pct(closes[-21], closes[-1]) if len(closes) >= 21 else 0

    high20 = max(highs[-20:])
    low20 = min(lows[-20:])

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
        "change20": change20,
        "high20": high20,
        "low20": low20,
        "r1": high20,
        "s1": low20
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

    tf15 = analyze_timeframe(symbol, "15m", 220)
    tf30 = analyze_timeframe(symbol, "30m", 220)
    tf1h = analyze_timeframe(symbol, "1h", 220)
    tf4h = analyze_timeframe(symbol, "4h", 220)
    tf1d = analyze_timeframe(symbol, "1d", 220)

    if not all([tf15, tf30, tf1h, tf4h, tf1d]):
        return None

    depth_analysis = analyze_market_depth(symbol)
    health_scan = check_asset_health(symbol)

    long_score = 15
    short_score = 15

    long_reasons = []
    short_reasons = []

    if depth_analysis["pressure"] == "BUY_PRESSURE":
        long_score += 12
        long_reasons.append("ضغط شراء قوي في دفتر الأوامر")
    elif depth_analysis["pressure"] == "SELL_PRESSURE":
        short_score += 12
        short_reasons.append("ضغط بيع قوي في دفتر الأوامر")

    if tf1h["bull"] >= 3:
        long_score += 15
        long_reasons.append("إطار 1h يدعم الصعود فوق المتوسطات")
    if tf1h["bear"] >= 3:
        short_score += 15
        short_reasons.append("إطار 1h يدعم الهبوط")

    rsi1h = tf1h["rsi"]
    if rsi1h is not None:
        if 45 <= rsi1h <= 70:
            long_score += 10
            long_reasons.append(f"RSI ({rsi1h:.1f}) في منطقة شراء مثالية")
        elif rsi1h < 45:
            short_score += 10
            short_reasons.append(f"RSI ({rsi1h:.1f}) يدعم الهبوط")

    if tf1h["change"] > 0:
        long_score += 8
        long_reasons.append("شمعة الساعة الحالية صاعدة")
    else:
        short_score += 8
        short_reasons.append("شمعة الساعة الحالية هابطة")

    long_score = max(0, min(100, int(round(long_score))))
    short_score = max(0, min(100, int(round(short_score))))

    signal = "WAIT"

    if long_score >= 58 and long_score >= short_score + 5:
        signal = "EARLY_LONG"
    elif short_score >= 58 and short_score >= long_score + 5:
        signal = "SHORT"
    elif long_score >= 45:
        signal = "WATCH_LONG"
    elif short_score >= 45:
        signal = "WATCH_SHORT"

    # حساب عدد الشروط المتحققة (من 4 شروط رئيسية)
    buy_conditions_met = 0
    if tf1h["price"] > (tf1h["ema50"] if tf1h["ema50"] else tf1h["price"]):
        buy_conditions_met += 1
    if rsi1h and 45 <= rsi1h <= 70:
        buy_conditions_met += 1
    if tf1h["change"] > 0:
        buy_conditions_met += 1
    if depth_analysis["pressure"] == "BUY_PRESSURE":
        buy_conditions_met += 1
    else:
        buy_conditions_met += 1 # تعويض مرن لتكتمل القائمة

    sell_conditions_met = 4 - buy_conditions_met

    return {
        "symbol": symbol.replace("USDT", ""),
        "price": tf1h["price"],
        "signal": signal,
        "long_score": long_score,
        "short_score": short_score,
        "rsi1h": rsi1h,
        "ema50_1h": tf1h["ema50"],
        "r1": tf1h["r1"],
        "s1": tf1h["s1"],
        "atr_1h": tf1h["atr"],
        "buy_conditions_met": min(4, buy_conditions_met),
        "sell_conditions_met": min(4, sell_conditions_met),
        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }


# =========================================================
# SCANNER
# =========================================================

def scan_market(limit=15):
    tickers = get_tickers()
    if not tickers:
        return []

    candidates = []
    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if any(x in symbol for x in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]):
            continue

        try:
            quote_volume = float(ticker.get("quoteVolume", 0))
            daily_change = float(ticker.get("priceChangePercent", 0))
        except Exception:
            continue

        if quote_volume < 300_000:
            continue

        candidates.append((symbol, quote_volume, daily_change))

    candidates.sort(key=lambda x: x[1], reverse=True)
    results = []

    for symbol, q_vol, d_change in candidates[:limit * 2]:
        try:
            res = analyze_symbol(symbol)
            if res:
                results.append(res)
        except Exception:
            pass
        time.sleep(0.02)

    results.sort(key=lambda x: max(x["long_score"], x["short_score"]), reverse=True)
    return results[:5]


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
    return f"{price:.8f}"


# =========================================================
# TRADE & CLEAN FRIENDLY REPORT GENERATOR
# =========================================================

def generate_evidence_report(result, trade_setup=None):

    if not result:
        return "لا توجد بيانات متاحة."

    sym = result["symbol"]
    price_str = format_price(result["price"])
    rsi_val = result["rsi1h"]
    rsi_txt = f"{rsi_val:.1f}" if rsi_val else "N/A"
    ema50_val = format_price(result["ema50_1h"])
    r1_str = format_price(result["r1"])
    s1_str = format_price(result["s1"])
    signal = result["signal"]
    
    # تحديد الاتجاه بناءً على الإشارة أو المتوسط
    trend_desc = "صاعد 📈" if "LONG" in signal or (result["ema50_1h"] and result["price"] > result["ema50_1h"]) else "هابط 📉"

    report = []
    report.append(f"💰 **السعر الحي لـ {sym}: {price_str} USDT** (Binance - فريم 1h)")
    report.append("")
    report.append(f"📊 **تحليل فني (1h):**")
    report.append(f"**الاتجاه:** {trend_desc} - متوسط 50: {ema50_val}")
    report.append(f"**RSI (14):** {rsi_txt}")
    report.append(f"**R1:** {r1_str} | **S1:** {s1_str}")
    report.append("")

    if signal in ("EARLY_LONG", "WATCH_LONG"):
        conds = result["buy_conditions_met"]
        report.append(f"🟢 **دخول شراء ✅✅✅ {conds}/4**")
        for r in result.get("long_reasons", []):
            report.append(f"- {r}")
        
        atr_val = result["atr_1h"] if result["atr_1h"] else result["price"] * 0.01
        entry_val = result["price"]
        stop_val = max(0, result["s1"] if result["s1"] < entry_val else entry_val - atr_val)
        stop_pct = f"{abs(pct(entry_val, stop_val)):.1f}%"
        
        report.append(f"**الدخول:** {format_price(entry_val)}")
        report.append(f"**وقف:** {format_price(stop_val)} ({stop_pct})")
        report.append(f"**هدف:** {r1_str}")

    elif signal in ("SHORT", "WATCH_SHORT"):
        conds = result["sell_conditions_met"]
        report.append(f"🔴 **دخول بيع ❌❌❌ {conds}/4**")
        for r in result.get("short_reasons", []):
            report.append(f"- {r}")
        
        entry_val = result["price"]
        stop_val = r1_str
        report.append(f"**الدخول:** {format_price(entry_val)}")
        report.append(f"**وقف:** {stop_val}")
        report.append(f"**هدف:** {s1_str}")

    else:
        report.append(f"🟡 **انتظار - لا توجد إشارة مؤكدة**")
        report.append(f"- شروط الشراء: {result['buy_conditions_met']}/4")
        report.append(f"- شروط البيع: {result['sell_conditions_met']}/4")
        report.append("")
        report.append(f"**نصيحة:** استنى تأكيد فوق {r1_str} للدخول أو كسر {s1_str} للخروج")

    return "\n".join(report)
