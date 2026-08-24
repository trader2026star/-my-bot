import time
import requests


# =========================================================
# SETTINGS
# =========================================================

FUTURES_URL = "https://fapi.binance.com"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CryptoAIScanner/1.0"
})


# =========================================================
# BINANCE REQUEST
# =========================================================

def binance_get(path, params=None, timeout=15):
    try:
        response = SESSION.get(
            FUTURES_URL + path,
            params=params,
            timeout=timeout
        )

        if response.status_code == 200:
            return response.json()

        return None

    except requests.RequestException:
        return None


# =========================================================
# SYMBOL
# =========================================================

def normalize_symbol(text):
    text = str(text).strip().upper()

    if text.endswith("/USDT"):
        text = text.replace("/", "")

    if not text.endswith("USDT"):
        text += "USDT"

    return text


# =========================================================
# CHECK FUTURES SYMBOL
# =========================================================

def get_futures_symbols():
    data = binance_get("/fapi/v1/exchangeInfo")

    if not data:
        return set()

    symbols = set()

    for item in data.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
        ):
            symbols.add(item.get("symbol"))

    return symbols


def symbol_exists(symbol):
    symbols = get_futures_symbols()
    return symbol in symbols


# =========================================================
# KLINES
# =========================================================

def get_binance_futures_klines(symbol, interval="1h", limit=200):
    symbol = normalize_symbol(symbol)

    data = binance_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not isinstance(data, list):
        return None

    if len(data) < 20:
        return None

    return data


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = ((price - ema) * multiplier) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return round(100 - (100 / (1 + rs)), 2)


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def calculate_support_resistance(klines):
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    current_price = closes[-1]

    # استخدام آخر 50 شمعة
    recent_highs = highs[-50:]
    recent_lows = lows[-50:]

    resistance_candidates = sorted(
        [x for x in recent_highs if x > current_price]
    )

    support_candidates = sorted(
        [x for x in recent_lows if x < current_price],
        reverse=True
    )

    if support_candidates:
        support = support_candidates[0]
    else:
        support = min(recent_lows)

    if resistance_candidates:
        resistance = resistance_candidates[0]
    else:
        resistance = max(recent_highs)

    return support, resistance


# =========================================================
# VOLUME
# =========================================================

def calculate_volume_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return 1.0

    average_volume = sum(volumes[-period-1:-1]) / period

    if average_volume <= 0:
        return 1.0

    return round(volumes[-1] / average_volume, 2)


# =========================================================
# MULTI TIMEFRAME TREND
# =========================================================

def get_timeframe_trend(symbol, interval):
    klines = get_binance_futures_klines(
        symbol,
        interval,
        100
    )

    if not klines:
        return "UNKNOWN"

    closes = [float(k[4]) for k in klines]

    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    if not ema9 or not ema20 or not ema50:
        return "UNKNOWN"

    if ema9 > ema20 > ema50:
        return "LONG"

    if ema9 < ema20 < ema50:
        return "SHORT"

    return "NEUTRAL"


# =========================================================
# COIN ANALYSIS
# =========================================================

def get_coin_analysis(symbol):
    symbol = normalize_symbol(symbol)

    # تأكيد أن العملة موجودة على Futures
    if not symbol_exists(symbol):
        return None

    klines = get_binance_futures_klines(
        symbol,
        "1h",
        200
    )

    if not klines:
        return None

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    current_price = closes[-1]

    # المؤشرات
    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    rsi = calculate_rsi(closes)

    volume_ratio = calculate_volume_ratio(volumes)

    support, resistance = calculate_support_resistance(klines)

    # -----------------------------------------------------
    # MULTI TIMEFRAME
    # -----------------------------------------------------

    trend_15m = get_timeframe_trend(symbol, "15m")
    trend_1h = get_timeframe_trend(symbol, "1h")
    trend_4h = get_timeframe_trend(symbol, "4h")
    trend_1d = get_timeframe_trend(symbol, "1d")

    # -----------------------------------------------------
    # SCORING
    # -----------------------------------------------------

    long_score = 0
    short_score = 0

    analysis_lines = []

    # EMA
    if ema9 > ema20:
        long_score += 15
        analysis_lines.append("EMA9 أعلى من EMA20")

    else:
        short_score += 15
        analysis_lines.append("EMA9 أسفل EMA20")

    if ema20 > ema50:
        long_score += 10
    else:
        short_score += 10

    # RSI
    if 45 <= rsi <= 68:
        long_score += 10

    if 32 <= rsi <= 55:
        short_score += 10

    # Volume
    if volume_ratio >= 1.20:
        if ema9 > ema20:
            long_score += 15
            analysis_lines.append(
                "ارتفاع ملحوظ في حجم التداول ودخول سيولة محتمل"
            )
        else:
            short_score += 15
            analysis_lines.append(
                "ارتفاع حجم التداول مع ضغط بيعي"
            )

    # Multi timeframe
    if trend_15m == "LONG":
        long_score += 5
    elif trend_15m == "SHORT":
        short_score += 5

    if trend_1h == "LONG":
        long_score += 10
    elif trend_1h == "SHORT":
        short_score += 10

    if trend_4h == "LONG":
        long_score += 15
    elif trend_4h == "SHORT":
        short_score += 15

    if trend_1d == "LONG":
        long_score += 10
    elif trend_1d == "SHORT":
        short_score += 10

    # -----------------------------------------------------
    # SUPPORT / RESISTANCE DISTANCE
    # -----------------------------------------------------

    support_distance = (
        (current_price - support) / current_price * 100
        if current_price > 0
        else 0
    )

    resistance_distance = (
        (resistance - current_price) / current_price * 100
        if current_price > 0
        else 0
    )

    # LONG أفضل إذا السعر قريب نسبيًا من الدعم
    if 0 < support_distance <= 5:
        long_score += 10
        analysis_lines.append(
            "السعر قريب من منطقة دعم ويمكن مراقبة ارتداد"
        )

    # LONG خطر إذا كان قريب من المقاومة
    if 0 < resistance_distance <= 1.5:
        long_score -= 15
        analysis_lines.append(
            "السعر قريب جداً من مقاومة قوية"
        )

    # SHORT أفضل قرب المقاومة
    if 0 < resistance_distance <= 5:
        short_score += 10
        analysis_lines.append(
            "السعر قريب من منطقة مقاومة ويمكن مراقبة رفض سعري"
        )

    # SHORT خطر قرب الدعم
    if 0 < support_distance <= 1.5:
        short_score -= 15
        analysis_lines.append(
            "السعر قريب جداً من دعم قوي"
        )

    # -----------------------------------------------------
    # SELECT DIRECTION
    # -----------------------------------------------------

    if long_score >= short_score:
        direction = "LONG"
        score = max(0, min(100, long_score))
        state = "تجميع + مراقبة دخول السيولة"
        trend = "UP"

    else:
        direction = "SHORT"
        score = max(0, min(100, short_score))
        state = "تصريف + مراقبة خروج السيولة"
        trend = "DOWN"

    # -----------------------------------------------------
    # ENTRY / SL / TP
    # -----------------------------------------------------

    if direction == "LONG":

        entry_min = max(
            support,
            current_price * 0.997
        )

        entry_max = current_price

        stop_loss = support * 0.992

        risk = current_price - stop_loss

        if risk <= 0:
            risk = current_price * 0.01

        tp1 = current_price + risk * 1.5
        tp2 = current_price + risk * 2.5
        tp3 = current_price + risk * 4

        if resistance > current_price:
            tp1 = min(tp1, resistance)

    else:

        entry_min = current_price

        entry_max = min(
            resistance,
            current_price * 1.003
        )

        stop_loss = resistance * 1.008

        risk = stop_loss - current_price

        if risk <= 0:
            risk = current_price * 0.01

        tp1 = current_price - risk * 1.5
        tp2 = current_price - risk * 2.5
        tp3 = current_price - risk * 4

        if support < current_price:
            tp1 = max(tp1, support)

    # -----------------------------------------------------
    # ROUNDING
    # -----------------------------------------------------

    def smart_round(value):
        if value >= 1000:
            return round(value, 2)
        elif value >= 100:
            return round(value, 3)
        elif value >= 1:
            return round(value, 4)
        elif value >= 0.1:
            return round(value, 5)
        elif value >= 0.01:
            return round(value, 6)
        else:
            return round(value, 8)

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "state": state,
        "price": smart_round(current_price),

        "rsi": rsi,
        "volume_ratio": volume_ratio,

        "buy_pressure": round(
            55 + min(volume_ratio * 5, 15)
            if direction == "LONG"
            else 45 - min(volume_ratio * 3, 10),
            1
        ),

        "trend": trend,

        "trend_15m": trend_15m,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "trend_1d": trend_1d,

        "entry_min": smart_round(entry_min),
        "entry_max": smart_round(entry_max),

        "stop_loss": smart_round(stop_loss),

        "tp1": smart_round(tp1),
        "tp2": smart_round(tp2),
        "tp3": smart_round(tp3),

        "support": smart_round(support),
        "resistance": smart_round(resistance),

        "support_distance": round(support_distance, 2),
        "resistance_distance": round(resistance_distance, 2),

        "analysis_lines": analysis_lines
    }


# =========================================================
# MARKET SCANNER
# =========================================================

def get_top_futures_symbols(limit=80):
    symbols = get_futures_symbols()

    if not symbols:
        return []

    ticker_data = binance_get("/fapi/v1/ticker/24hr")

    if not ticker_data:
        return list(symbols)[:limit]

    candidates = []

    for item in ticker_data:

        symbol = item.get("symbol")

        if symbol not in symbols:
            continue

        try:
            quote_volume = float(
                item.get("quoteVolume", 0)
            )

            candidates.append(
                (symbol, quote_volume)
            )

        except Exception:
            continue

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return [
        symbol
        for symbol, volume in candidates[:limit]
    ]


def scan_market(limit=5):
    symbols = get_top_futures_symbols(80)

    if not symbols:
        return []

    results = []

    for symbol in symbols:

        try:
            data = get_coin_analysis(symbol)

            if not data:
                continue

            # لا نعرض إلا الفرص ذات التأكيد الجيد
            if data["score"] >= 70:
                results.append(data)

            if len(results) >= limit:
                break

        except Exception:
            continue

        time.sleep(0.05)

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# =========================================================
# REPORT
# =========================================================

def generate_evidence_report(data):

    direction_emoji = (
        "🟢"
        if data["direction"] == "LONG"
        else "🔴"
    )

    lines = [
        "🤖 Binance AI Scanner",
        "",
        f"💎 العملة: {data['symbol']}",
        f"📈 الاتجاه: {direction_emoji} {data['direction']}",
        f"⭐ Score: {data['score']}/100",
        "",
        f"🧠 الحالة: {data['state']}",
        "",
        f"💰 السعر: {data['price']}",
        f"📊 RSI: {data['rsi']}",
        f"📊 Volume: {data['volume_ratio']}x",
        f"💧 Buy Pressure: {data['buy_pressure']}%",
        "",
        "📊 تأكيد الفريمات",
        f"15M: {data['trend_15m']}",
        f"1H: {data['trend_1h']}",
        f"4H: {data['trend_4h']}",
        f"1D: {data['trend_1d']}",
        "",
        "🛡️ الدعم والمقاومة",
        f"🟢 Support: {data['support']}",
        f"🔴 Resistance: {data['resistance']}",
        f"📏 بُعد السعر عن الدعم: {data['support_distance']}%",
        f"📏 بُعد السعر عن المقاومة: {data['resistance_distance']}%",
        "",
        "📍 منطقة الدخول",
        f"{data['entry_min']} - {data['entry_max']}",
        "",
        f"🛑 Stop Loss: {data['stop_loss']}",
        "",
        "🎯 الأهداف",
        f"TP1: {data['tp1']}",
        f"TP2: {data['tp2']}",
        f"TP3: {data['tp3']}",
        "",
        "🔍 التحليل"
    ]

    for line in data["analysis_lines"]:
        lines.append(f"• {line}")

    lines.extend([
        "",
        "⚠️ الصفقة تحتاج تأكيد حركة السعر قبل الدخول."
    ])

    return "\n".join(lines)
