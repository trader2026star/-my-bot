import time
import requests
from typing import Dict, List, Optional


# =========================================================
# BINANCE PUBLIC API
# =========================================================

BINANCE_API_URL = "https://data-api.binance.vision"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 Binance-AI-Scanner/1.0"
})


# =========================================================
# BASIC HELPERS
# =========================================================

def format_number(value):
    if value is None:
        return "N/A"

    value = float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.10f}"


def safe_get(path, params=None, timeout=10):
    try:
        response = SESSION.get(
            BINANCE_API_URL + path,
            params=params,
            timeout=timeout,
        )

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"Binance API error: {path} -> {e}")
        return None


# =========================================================
# SYMBOLS
# =========================================================

def get_usdt_symbols() -> List[str]:
    """
    جلب كل عملات USDT المتاحة في Binance Spot.
    """

    data = safe_get(
        "/api/v3/exchangeInfo",
        timeout=15,
    )

    if not data:
        return []

    symbols = []

    for item in data.get("symbols", []):
        try:
            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed", True)
            ):
                symbol = item.get("symbol")

                if symbol:
                    symbols.append(symbol)

        except Exception:
            continue

    return symbols


# =========================================================
# 24H MARKET DATA
# =========================================================

def get_24h_tickers():
    data = safe_get(
        "/api/v3/ticker/24hr",
        timeout=15,
    )

    if not isinstance(data, list):
        return []

    return data


# =========================================================
# KLINES
# =========================================================

def get_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 100,
):
    data = safe_get(
        "/api/v3/klines",
        params={
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        },
        timeout=10,
    )

    if not isinstance(data, list):
        return []

    candles = []

    for row in data:
        try:
            candles.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "quote_volume": float(row[7]),
                "trades": int(row[8]),
                "taker_buy_base": float(row[9]),
                "taker_buy_quote": float(row[10]),
            })
        except Exception:
            continue

    return candles


# =========================================================
# INDICATORS
# =========================================================

def ema(values: List[float], period: int):
    if not values:
        return 0.0

    if len(values) < period:
        return sum(values) / len(values)

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            price - result
        ) * multiplier + result

    return result


def rsi(values: List[float], period: int = 14):
    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    trs = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        trs.append(tr)

    return sum(trs[-period:]) / period


# =========================================================
# MARKET STRUCTURE
# =========================================================

def get_support_resistance(candles, lookback=30):
    recent = candles[-lookback:]

    support = min(x["low"] for x in recent)
    resistance = max(x["high"] for x in recent)

    return support, resistance


def trend_analysis(closes):
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    price = closes[-1]

    if price > e9 > e20 > e50:
        return "STRONG_UP"

    if price > e20 and e20 > e50:
        return "UP"

    if price < e9 < e20 < e50:
        return "STRONG_DOWN"

    if price < e20 and e20 < e50:
        return "DOWN"

    return "SIDEWAYS"


# =========================================================
# VOLUME / LIQUIDITY
# =========================================================

def volume_analysis(candles):
    volumes = [x["quote_volume"] for x in candles]

    current = volumes[-1]

    base = volumes[-21:-1]

    average = (
        sum(base) / len(base)
        if base
        else current
    )

    if average <= 0:
        ratio = 1.0
    else:
        ratio = current / average

    return ratio


def buy_pressure_analysis(candles, period=10):
    recent = candles[-period:]

    total_quote = sum(
        x["quote_volume"]
        for x in recent
    )

    buy_quote = sum(
        x["taker_buy_quote"]
        for x in recent
    )

    if total_quote <= 0:
        return 50.0

    return (
        buy_quote / total_quote
    ) * 100


def liquidity_flow(candles):
    """
    تقدير تدفق السيولة اعتماداً على:
    - حجم التداول
    - ضغط الشراء
    - اتجاه إغلاق الشموع
    """

    recent = candles[-10:]

    score = 0

    for candle in recent:
        if candle["close"] > candle["open"]:
            score += candle["quote_volume"]
        else:
            score -= candle["quote_volume"]

    total = sum(
        x["quote_volume"]
        for x in recent
    )

    if total <= 0:
        return 0

    return score / total


# =========================================================
# ACCUMULATION / DISTRIBUTION
# =========================================================

def detect_accumulation(candles):
    """
    البحث عن تجميع قبل الانفجار.

    الشروط ليست مجرد ارتفاع السعر.
    نبحث عن:
    - نطاق سعري متماسك
    - حجم يبدأ في الارتفاع
    - ضغط شراء أعلى
    - السعر قريب من متوسطاته
    """

    if len(candles) < 40:
        return False, 0

    recent = candles[-20:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    highest = max(highs)
    lowest = min(lows)

    current = candles[-1]["close"]

    if current <= 0:
        return False, 0

    range_pct = (
        (highest - lowest) / current
    ) * 100

    volume_ratio = volume_analysis(candles)
    buy_pressure = buy_pressure_analysis(candles)

    e20 = ema(
        [x["close"] for x in candles],
        20,
    )

    distance_ema = (
        abs(current - e20) / current
    ) * 100

    points = 0

    # نطاق ضيق = تجميع محتمل
    if range_pct <= 10:
        points += 25

    if range_pct <= 6:
        points += 10

    # الحجم بدأ يزيد
    if volume_ratio >= 1.15:
        points += 15

    if volume_ratio >= 1.5:
        points += 10

    # ضغط شراء
    if buy_pressure >= 52:
        points += 15

    if buy_pressure >= 55:
        points += 10

    # قريب من EMA20
    if distance_ema <= 4:
        points += 10

    return points >= 55, min(points, 100)


def detect_distribution(candles):
    """
    اكتشاف احتمال التصريف / خروج السيولة.
    """

    if len(candles) < 40:
        return False, 0

    closes = [x["close"] for x in candles]

    price = closes[-1]

    highest_20 = max(
        closes[-20:]
    )

    volume_ratio = volume_analysis(candles)
    buy_pressure = buy_pressure_analysis(candles)

    points = 0

    # السعر قريب من قمة حديثة
    if highest_20 > 0:
        distance = (
            (highest_20 - price)
            / highest_20
        ) * 100

        if distance <= 3:
            points += 20

    # الحجم مرتفع
    if volume_ratio >= 1.3:
        points += 20

    # ضغط الشراء ضعيف
    if buy_pressure <= 48:
        points += 20

    if buy_pressure <= 45:
        points += 15

    # شموع هابطة
    red = sum(
        1
        for x in candles[-8:]
        if x["close"] < x["open"]
    )

    if red >= 5:
        points += 20

    return points >= 55, min(points, 100)


# =========================================================
# OVEREXTENSION
# =========================================================

def is_overextended(candles):
    closes = [x["close"] for x in candles]

    price = closes[-1]

    e20 = ema(closes, 20)

    if e20 <= 0:
        return False

    distance = (
        (price - e20) / e20
    ) * 100

    # لا نطارد العملة بعد ارتفاع كبير
    return distance >= 8


# =========================================================
# PRE-BREAKOUT
# =========================================================

def detect_pre_breakout(candles):
    if len(candles) < 30:
        return False

    support, resistance = get_support_resistance(
        candles,
        25,
    )

    price = candles[-1]["close"]

    if resistance <= 0:
        return False

    distance = (
        (resistance - price)
        / resistance
    ) * 100

    volume_ratio = volume_analysis(candles)
    buy_pressure = buy_pressure_analysis(candles)

    return (
        0 <= distance <= 4
        and volume_ratio >= 1.15
        and buy_pressure >= 52
    )


# =========================================================
# TRADE CALCULATION
# =========================================================

def build_long_trade(
    symbol,
    candles,
    score,
    reasons,
):
    price = candles[-1]["close"]

    support, resistance = get_support_resistance(
        candles,
        30,
    )

    current_atr = atr(candles)

    if current_atr <= 0:
        current_atr = price * 0.02

    entry_low = max(
        support,
        price - current_atr * 0.5,
    )

    entry_high = price

    stop = min(
        support - current_atr * 0.5,
        price - current_atr * 1.5,
    )

    risk = price - stop

    if risk <= 0:
        risk = current_atr

    tp1 = price + risk * 1.5
    tp2 = price + risk * 2.5
    tp3 = price + risk * 4.0

    return {
        "symbol": symbol,
        "direction": "LONG",
        "score": int(score),
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "is_ready": score >= 75,
    }


def build_short_trade(
    symbol,
    candles,
    score,
    reasons,
):
    price = candles[-1]["close"]

    support, resistance = get_support_resistance(
        candles,
        30,
    )

    current_atr = atr(candles)

    if current_atr <= 0:
        current_atr = price * 0.02

    entry_low = price

    entry_high = min(
        resistance,
        price + current_atr * 0.5,
    )

    stop = max(
        resistance + current_atr * 0.5,
        price + current_atr * 1.5,
    )

    risk = stop - price

    if risk <= 0:
        risk = current_atr

    tp1 = price - risk * 1.5
    tp2 = price - risk * 2.5
    tp3 = price - risk * 4.0

    return {
        "symbol": symbol,
        "direction": "SHORT",
        "score": int(score),
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "is_ready": score >= 75,
    }


# =========================================================
# FULL ANALYSIS
# =========================================================

def analyze_symbol(symbol: str) -> Optional[Dict]:
    symbol = symbol.upper().strip()

    candles = get_klines(
        symbol,
        interval="1h",
        limit=100,
    )

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    price = closes[-1]

    trend = trend_analysis(closes)

    rsi_value = rsi(closes)

    volume_ratio = volume_analysis(candles)

    buy_pressure = buy_pressure_analysis(candles)

    flow = liquidity_flow(candles)

    support, resistance = get_support_resistance(
        candles,
        30,
    )

    accumulation, accumulation_score = detect_accumulation(
        candles
    )

    distribution, distribution_score = detect_distribution(
        candles
    )

    pre_breakout = detect_pre_breakout(
        candles
    )

    overextended = is_overextended(
        candles
    )

    score_long = 0
    score_short = 0

    long_reasons = []
    short_reasons = []

    # =====================================================
    # LONG
    # =====================================================

    if trend == "STRONG_UP":
        score_long += 20
        long_reasons.append(
            "الترند صاعد بقوة: EMA9 > EMA20 > EMA50"
        )

    elif trend == "UP":
        score_long += 15
        long_reasons.append(
            "الترند العام صاعد"
        )

    if accumulation:
        score_long += 25
        long_reasons.append(
            f"تجميع محتمل قبل الحركة — قوة التجميع {accumulation_score}/100"
        )

    if pre_breakout:
        score_long += 15
        long_reasons.append(
            "السعر قريب من مقاومة مع تحسن الحجم والسيولة"
        )

    if buy_pressure >= 55:
        score_long += 20
        long_reasons.append(
            "ضغط شراء قوي ودخول سيولة"
        )

    elif buy_pressure >= 52:
        score_long += 10
        long_reasons.append(
            "ضغط شراء أعلى من المتوسط"
        )

    if volume_ratio >= 1.5:
        score_long += 15
        long_reasons.append(
            f"الحجم أعلى من متوسطه بحوالي {volume_ratio:.2f}x"
        )

    elif volume_ratio >= 1.2:
        score_long += 8
        long_reasons.append(
            "الحجم بدأ في الارتفاع"
        )

    if 50 <= rsi_value <= 68:
        score_long += 10
        long_reasons.append(
            "RSI في منطقة تسمح باستمرار الحركة بدون تشبع شديد"
        )

    if flow > 0.10:
        score_long += 10
        long_reasons.append(
            "تدفق السيولة يميل للمشترين"
        )

    # لا ندخل بعد انفجار متأخر
    if overextended:
        score_long -= 30
        long_reasons.append(
            "⚠️ السعر ممتد عن EMA20 — تجنب مطاردة الصعود"
        )

    # التصريف يلغي جزء كبير من إشارة LONG
    if distribution:
        score_long -= 30
        long_reasons.append(
            "⚠️ توجد علامات تصريف / خروج سيولة"
        )

    # =====================================================
    # SHORT
    # =====================================================

    if trend == "STRONG_DOWN":
        score_short += 20
        short_reasons.append(
            "الترند هابط بقوة: EMA9 < EMA20 < EMA50"
        )

    elif trend == "DOWN":
        score_short += 15
        short_reasons.append(
            "الترند العام هابط"
        )

    if distribution:
        score_short += 25
        short_reasons.append(
            f"علامات تصريف وخروج سيولة — قوة {distribution_score}/100"
        )

    if buy_pressure <= 45:
        score_short += 20
        short_reasons.append(
            "ضغط البيع أعلى من ضغط الشراء"
        )

    elif buy_pressure <= 48:
        score_short += 10
        short_reasons.append(
            "ضعف واضح في ضغط الشراء"
        )

    if volume_ratio >= 1.5:
        score_short += 15
        short_reasons.append(
            f"الحجم مرتفع {volume_ratio:.2f}x مع ضغط بيعي"
        )

    if rsi_value <= 45:
        score_short += 10
        short_reasons.append(
            "RSI يميل للضعف"
        )

    if flow < -0.10:
        score_short += 10
        short_reasons.append(
            "تدفق السيولة يميل للبائعين"
        )

    # لا نبيع عملة منهارة بالفعل
    if rsi_value < 25:
        score_short -= 20
        short_reasons.append(
            "⚠️ العملة منهارة وممتدة هبوطياً — لا نطارد الهبوط"
        )

    # =====================================================
    # FINAL DECISION
    # =====================================================

    score_long = max(0, min(100, score_long))
    score_short = max(0, min(100, score_short))

    if score_long >= score_short:
        final_score = score_long
        direction = "LONG"
        reasons = long_reasons
    else:
        final_score = score_short
        direction = "SHORT"
        reasons = short_reasons

    # لا تعتبر الصفقة جاهزة إلا إذا كانت قوية فعلاً
    if final_score < 68:
        direction = "WAIT"

    if direction == "LONG":
        result = build_long_trade(
            symbol,
            candles,
            final_score,
            reasons,
        )

    elif direction == "SHORT":
        result = build_short_trade(
            symbol,
            candles,
            final_score,
            reasons,
        )

    else:
        result = {
            "symbol": symbol,
            "direction": "WAIT",
            "score": final_score,
            "price": price,
            "entry_low": price,
            "entry_high": price,
            "stop": price,
            "tp1": price,
            "tp2": price,
            "tp3": price,
            "support": support,
            "resistance": resistance,
            "reasons": reasons,
            "is_ready": False,
        }

    # الحالة
    if distribution:
        state = "DISTRIBUTION"

    elif accumulation and pre_breakout:
        state = "PRE_BREAKOUT"

    elif accumulation:
        state = "ACCUMULATION"

    elif distribution_score >= 45:
        state = "SELL_PRESSURE"

    else:
        state = "NORMAL"

    result.update({
        "rsi": rsi_value,
        "volume_ratio": volume_ratio,
        "buy_pressure": buy_pressure,
        "liquidity_flow": flow,
        "trend": trend,
        "state": state,
    })

    return result


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market() -> List[Dict]:
    """
    Scanner حقيقي:

    1. يجلب العملات المتاحة.
    2. يجلب 24h volume.
    3. يختار العملات ذات السيولة والنشاط.
    4. يحللها واحدة واحدة.
    5. يمنع مطاردة العملات المنفجرة.
    6. يرجع أفضل الفرص.
    """

    print("🔎 Starting Binance market scan...")

    tickers = get_24h_tickers()

    if not tickers:
        print("❌ Unable to get Binance 24h tickers")
        return []

    candidates = []

    excluded = (
        "USDC",
        "FDUSD",
        "TUSD",
        "USDP",
        "DAI",
        "EUR",
        "TRY",
        "BRL",
        "GBP",
        "AUD",
        "JPY",
        "RUB",
        "BUSD",
    )

    for ticker in tickers:
        try:
            symbol = ticker.get("symbol", "")

            if not symbol.endswith("USDT"):
                continue

            if any(x in symbol for x in excluded):
                continue

            quote_volume = float(
                ticker.get("quoteVolume", 0)
            )

            price_change = float(
                ticker.get("priceChangePercent", 0)
            )

            last_price = float(
                ticker.get("lastPrice", 0)
            )

            if quote_volume < 1_000_000:
                continue

            if last_price <= 0:
                continue

            # نركز على العملات النشطة لكن لا نبحث عن انفجار +50%
            if abs(price_change) > 35:
                continue

            candidates.append({
                "symbol": symbol,
                "quote_volume": quote_volume,
                "change": price_change,
            })

        except Exception:
            continue

    # الأعلى سيولة أولاً
    candidates.sort(
        key=lambda x: x["quote_volume"],
        reverse=True,
    )

    # حتى لا نضرب Binance بطلبات ضخمة
    candidates = candidates[:120]

    print(
        f"📊 Candidates selected: {len(candidates)}"
    )

    results = []

    for index, candidate in enumerate(candidates):
        symbol = candidate["symbol"]

        try:
            result = analyze_symbol(symbol)

            if not result:
                continue

            # نريد فرصاً حقيقية وليس مجرد WAIT
            if result["direction"] == "WAIT":
                continue

            if result["score"] < 68:
                continue

            # منع مطاردة العملات الممتدة
            if result["direction"] == "LONG":
                if result["state"] == "DISTRIBUTION":
                    continue

            if result["direction"] == "SHORT":
                if result["rsi"] < 25:
                    continue

            results.append(result)

            print(
                f"{index + 1}/{len(candidates)} "
                f"{symbol} -> "
                f"{result['direction']} "
                f"{result['score']}"
            )

        except Exception as e:
            print(
                f"Analysis error {symbol}: {e}"
            )

        # تهدئة الطلبات
        time.sleep(0.08)

    # ترتيب حسب قوة الإشارة
    results.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["buy_pressure"],
        ),
        reverse=True,
    )

    print(
        f"✅ Scan finished. Signals: {len(results)}"
    )

    return results
