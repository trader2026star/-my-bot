
import os
import time
from decimal import Decimal
import requests
import telebot


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN أو API_TOKEN غير موجود في Environment Variables"
    )

bot = telebot.TeleBot(BOT_TOKEN)

BINANCE_URL = "https://data-api.binance.vision"

session = requests.Session()

session.headers.update({
    "User-Agent": "Binance-AI-Scanner/1.0",
    "Accept": "application/json"
})


# ============================================================
# BINANCE API
# ============================================================

def binance_get(endpoint, params=None):

    response = session.get(
        BINANCE_URL + endpoint,
        params=params or {},
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(
            f"Binance API Error {data.get('code')}: "
            f"{data.get('msg')}"
        )

    return data


def get_usdt_symbols():

    data = binance_get(
        "/api/v3/exchangeInfo"
    )

    excluded = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "DAIUSDT",
        "EURUSDT",
        "TRYUSDT",
        "BRLUSDT",
        "GBPUSDT",
        "AUDUSDT"
    }

    symbols = []

    for item in data.get("symbols", []):

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is False:
            continue

        symbol = item.get("symbol")

        if symbol and symbol not in excluded:
            symbols.append(symbol)

    return symbols


def get_current_price(symbol):

    data = binance_get(
        "/api/v3/ticker/price",
        {
            "symbol": symbol
        }
    )

    return Decimal(
        str(data["price"])
    )


def get_klines(
    symbol,
    interval="1h",
    limit=250
):

    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    candles = []

    for row in data:

        candles.append({
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5])
        })

    return candles


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):

    result = [None] * len(values)

    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)

    previous = sum(
        values[:period]
    ) / period

    result[period - 1] = previous

    for i in range(
        period,
        len(values)
    ):

        previous = (
            (values[i] - previous)
            * multiplier
            + previous
        )

        result[i] = previous

    return result


def rsi(values, period=14):

    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

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

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains) + 1
    ):

        if i > period:

            avg_gain = (
                (
                    avg_gain
                    * (period - 1)
                )
                + gains[i - 1]
            ) / period

            avg_loss = (
                (
                    avg_loss
                    * (period - 1)
                )
                + losses[i - 1]
            ) / period

        if avg_loss == 0:

            result[i] = 100

        else:

            rs = (
                avg_gain
                / avg_loss
            )

            result[i] = (
                100
                - (
                    100
                    / (1 + rs)
                )
            )

    return result


def macd(values):

    ema12 = ema(
        values,
        12
    )

    ema26 = ema(
        values,
        26
    )

    line = [None] * len(values)

    for i in range(
        len(values)
    ):

        if (
            ema12[i] is not None
            and
            ema26[i] is not None
        ):

            line[i] = (
                ema12[i]
                - ema26[i]
            )

    valid = [
        x
        for x in line
        if x is not None
    ]

    signal_valid = ema(
        valid,
        9
    )

    signal = [None] * len(values)

    start = (
        len(values)
        - len(valid)
    )

    for i, value in enumerate(
        signal_valid
    ):

        if value is not None:

            signal[
                start + i
            ] = value

    return line, signal


def atr(
    candles,
    period=14
):

    if len(candles) <= period:
        return [None] * len(candles)

    trs = [None]

    for i in range(
        1,
        len(candles)
    ):

        high = candles[i]["high"]

        low = candles[i]["low"]

        previous_close = (
            candles[i - 1]["close"]
        )

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            )
        )

        trs.append(tr)

    result = [
        None
    ] * len(candles)

    first = (
        sum(
            trs[1:period + 1]
        )
        / period
    )

    result[period] = first

    previous = first

    for i in range(
        period + 1,
        len(candles)
    ):

        previous = (
            (
                previous
                * (period - 1)
            )
            + trs[i]
        ) / period

        result[i] = previous

    return result


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_support(
    candles,
    lookback=50
):

    return min(
        x["low"]
        for x in candles[-lookback:]
    )


def get_resistance(
    candles,
    lookback=50
):

    return max(
        x["high"]
        for x in candles[-lookback:]
    )


def bullish_structure(candles):

    recent = candles[-40:]

    first = recent[:20]

    second = recent[20:]

    high1 = max(
        x["high"]
        for x in first
    )

    high2 = max(
        x["high"]
        for x in second
    )

    low1 = min(
        x["low"]
        for x in first
    )

    low2 = min(
        x["low"]
        for x in second
    )

    return (
        high2 > high1
        and
        low2 > low1
    )


def bearish_structure(candles):

    recent = candles[-40:]

    first = recent[:20]

    second = recent[20:]

    high1 = max(
        x["high"]
        for x in first
    )

    high2 = max(
        x["high"]
        for x in second
    )

    low1 = min(
        x["low"]
        for x in first
    )

    low2 = min(
        x["low"]
        for x in second
    )

    return (
        high2 < high1
        and
        low2 < low1
    )


def volume_ratio(
    candles,
    period=20
):

    current = (
        candles[-1]["volume"]
    )

    previous = [
        x["volume"]
        for x in candles[
            -period - 1:-1
        ]
    ]

    if not previous:
        return 0

    average = (
        sum(previous)
        / len(previous)
    )

    if average == 0:
        return 0

    return current / average


# ============================================================
# ANALYZE ONE COIN
# ============================================================

def analyze_symbol(symbol):

    try:

        candles_1h = get_klines(
            symbol,
            "1h",
            250
        )

        candles_4h = get_klines(
            symbol,
            "4h",
            150
        )

    except Exception as e:

        print(
            f"Error loading {symbol}: {e}"
        )

        return None

    if len(candles_1h) < 200:
        return None

    closes = [
        x["close"]
        for x in candles_1h
    ]

    ema20_values = ema(
        closes,
        20
    )

    ema50_values = ema(
        closes,
        50
    )

    ema200_values = ema(
        closes,
        200
    )

    rsi_values = rsi(
        closes,
        14
    )

    macd_line, signal_line = macd(
        closes
    )

    atr_values = atr(
        candles_1h,
        14
    )

    e20 = ema20_values[-1]

    e50 = ema50_values[-1]

    e200 = ema200_values[-1]

    rsi_value = rsi_values[-1]

    macd_value = macd_line[-1]

    signal_value = signal_line[-1]

    atr_value = atr_values[-1]

    if any(
        value is None
        for value in [
            e20,
            e50,
            e200,
            rsi_value,
            macd_value,
            signal_value,
            atr_value
        ]
    ):

        return None

    price = closes[-1]

    support = get_support(
        candles_1h
    )

    resistance = get_resistance(
        candles_1h
    )

    volume = volume_ratio(
        candles_1h
    )

    bullish = bullish_structure(
        candles_1h
    )

    bearish = bearish_structure(
        candles_1h
    )

    # ========================================================
    # 4H TREND
    # ========================================================

    closes_4h = [
        x["close"]
        for x in candles_4h
    ]

    ema20_4h = ema(
        closes_4h,
        20
    )[-1]

    ema50_4h = ema(
        closes_4h,
        50
    )[-1]

    if (
        ema20_4h is None
        or
        ema50_4h is None
    ):

        return None

    # ========================================================
    # LONG SCORE /100
    # ========================================================

    long_score = 0

    long_reasons = []

    if price > e20:

        long_score += 10

        long_reasons.append(
            "السعر فوق EMA20"
        )

    if e20 > e50:

        long_score += 10

        long_reasons.append(
            "EMA20 فوق EMA50"
        )

    if e50 > e200:

        long_score += 10

        long_reasons.append(
            "EMA50 فوق EMA200"
        )

    if 50 <= rsi_value <= 68:

        long_score += 10

        long_reasons.append(
            "RSI داعم للاتجاه الصاعد"
        )

    if macd_value > signal_value:

        long_score += 10

        long_reasons.append(
            "MACD إيجابي"
        )

    if bullish:

        long_score += 15

        long_reasons.append(
            "هيكل السوق صاعد"
        )

    if volume >= 1.20:

        long_score += 10

        long_reasons.append(
            "حجم التداول أعلى من المتوسط"
        )

    if ema20_4h > ema50_4h:

        long_score += 15

        long_reasons.append(
            "اتجاه 4H صاعد"
        )

    # ========================================================
    # SHORT SCORE /100
    # ========================================================

    short_score = 0

    short_reasons = []

    if price < e20:

        short_score += 10

        short_reasons.append(
            "السعر تحت EMA20"
        )

    if e20 < e50:

        short_score += 10

        short_reasons.append(
            "EMA20 تحت EMA50"
        )

    if e50 < e200:

        short_score += 10

        short_reasons.append(
            "EMA50 تحت EMA200"
        )

    if 32 <= rsi_value <= 50:

        short_score += 10

        short_reasons.append(
            "RSI داعم للشورت"
        )

    if macd_value < signal_value:

        short_score += 10

        short_reasons.append(
            "MACD سلبي"
        )

    if bearish:

        short_score += 15

        short_reasons.append(
            "هيكل السوق هابط"
        )

    if volume >= 1.20:

        short_score += 10

        short_reasons.append(
            "حجم التداول أعلى من المتوسط"
        )

    if ema20_4h < ema50_4h:

        short_score += 15

        short_reasons.append(
            "اتجاه 4H هابط"
        )

    # ========================================================
    # SELECT DIRECTION
    # ========================================================

    if long_score >= short_score:

        direction = "LONG"

        score = long_score

        reasons = long_reasons

    else:

        direction = "SHORT"

        score = short_score

        reasons = short_reasons

    # ========================================================
    # STRONG SIGNAL ONLY
    # ========================================================

    if score < 70:
        return None

    # ========================================================
    # AVOID NEAR RESISTANCE / SUPPORT
    # ========================================================

    if direction == "LONG":

        if resistance > price:

            room = (
                resistance - price
            ) / price

            if room < 0.015:
                return None

    else:

        if price > support:

            room = (
                price - support
            ) / price

            if room < 0.015:
                return None

    # ========================================================
    # ENTRY / SL / TP
    # ========================================================

    if direction == "LONG":

        entry_low = max(
            support,
            price - (
                atr_value * 0.35
            )
        )

        entry_high = price

        stop = min(
            support - (
                atr_value * 0.20
            ),
            price - (
                atr_value * 1.20
            )
        )

        risk = price - stop

        if risk <= 0:
            return None

        tp1 = price + (
            risk * 1.5
        )

        tp2 = price + (
            risk * 2.5
        )

        tp3 = price + (
            risk * 3.5
        )

    else:

        entry_low = price

        entry_high = min(
            resistance,
            price + (
                atr_value * 0.35
            )
        )

        stop = max(
            resistance + (
                atr_value * 0.20
            ),
            price + (
                atr_value * 1.20
            )
        )

        risk = stop - price

        if risk <= 0:
            return None

        tp1 = price - (
            risk * 1.5
        )

        tp2 = price - (
            risk * 2.5
        )

        tp3 = price - (
            risk * 3.5
        )

    return {

        "symbol": symbol,

        "direction": direction,

        "score": score,

        "price": price,

        "entry_low": entry_low,

        "entry_high": entry_high,

        "stop": stop,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "rsi": rsi_value,

        "volume_ratio": volume,

        "reasons": reasons
    }


# ============================================================
# FULL MARKET SCANNER
# ============================================================

def scan_market():

    symbols = get_usdt_symbols()

    results = []

    print(
        f"🔎 Scanning {len(symbols)} Binance USDT pairs..."
    )

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                results.append(
                    result
                )

        except Exception as e:

            print(
                f"{symbol}: {e}"
            )

        if index % 10 == 0:

            print(
                f"Progress: "
                f"{index}/{len(symbols)}"
            )

        # حماية من الضغط على API
        time.sleep(0.03)

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# ============================================================
# FORMAT PRICE
# ============================================================

def format_number(value):

    value = float(value)

    if value >= 1000:

        return f"{value:.2f}"

    if value >= 1:

        return (
            f"{value:.4f}"
            .rstrip("0")
            .rstrip(".")
        )

    if value >= 0.01:

        return (
            f"{value:.6f}"
            .rstrip("0")
            .rstrip(".")
        )

    if value >= 0.0001:

        return (
            f"{value:.8f}"
            .rstrip("0")
            .rstrip(".")
        )

    return (
        f"{value:.10f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(
    commands=[
        "start",
        "help"
    ]
)
def start(message):

    bot.reply_to(
        message,

        "🤖 **Binance AI Scanner**\n\n"

        "🔎 `/scan`\n"
        "لفحص سوق Binance والبحث عن أفضل الصفقات.\n\n"

        "💰 أو أرسل رمز العملة:\n"
        "`BTC`\n"
        "`SOL`\n"
        "`ETH`\n\n"

        "لن يتم اختيار LONG أو SHORT عشوائياً."
    ,
        parse_mode="Markdown"
    )


def build_trade_message(
    result
):

    direction = (
        "🟢 LONG"
        if result["direction"] == "LONG"
        else "🔴 SHORT"
    )

    reasons = "\n".join(
        f"• {reason}"
        for reason in result["reasons"]
    )

    return (

        "🚨 **فرصة تداول مكتشفة**\n\n"

        f"💎 العملة: `{result['symbol']}`\n"

        f"📈 الاتجاه: **{direction}**\n"

        f"⭐ Score: "
        f"**{result['score']}/100**\n\n"

        f"💰 السعر الحالي:\n"
        f"`{format_number(result['price'])}`\n\n"

        "📍 **منطقة الدخول:**\n"

        f"`{format_number(result['entry_low'])}`"
        " - "
        f"`{format_number(result['entry_high'])}`\n\n"

        "🛑 **وقف الخسارة:**\n"

        f"`{format_number(result['stop'])}`\n\n"

        "🎯 **الأهداف:**\n"

        f"TP1: `{format_number(result['tp1'])}`\n"

        f"TP2: `{format_number(result['tp2'])}`\n"

        f"TP3: `{format_number(result['tp3'])}`\n\n"

        f"📊 RSI: `{result['rsi']:.1f}`\n"

        f"📊 Volume: "
        f"`{result['volume_ratio']:.2f}x`\n\n"

        "🔍 **التأكيدات:**\n"

        f"{reasons}\n\n"

        "⚠️ لا توجد صفقة مضمونة. "
        "استخدم إدارة رأس المال."
    )


# ============================================================
# SCAN COMMAND
# ============================================================

@bot.message_handler(
    commands=["scan"]
)
def scan_command(message):

    status = bot.reply_to(
        message,

        "🔎 **جاري فحص سوق Binance...**\n\n"

        "سيتم فحص أزواج USDT المتاحة "
        "والبحث عن أقوى الإشارات.\n\n"

        "⏳ انتظر حتى ينتهي الفحص."
    ,
        parse_mode="Markdown"
    )

    try:

        results = scan_market()

        if not results:

            bot.edit_message_text(

                "🟡 **لا توجد صفقة جاهزة حالياً.**\n\n"

                "تم فحص السوق، لكن لم توجد "
                "عملة تحقق الحد الأدنى من شروط الدخول.\n\n"

                "عدم الدخول أفضل من الدخول في صفقة ضعيفة.",

                message.chat.id,

                status.message_id,

                parse_mode="Markdown"
            )

            return

        # أفضل 3 فرص فقط
        top_results = results[:3]

        for result in top_results:

            bot.send_message(

                message.chat.id,

                build_trade_message(
                    result
                ),

                parse_mode="Markdown"
            )

            time.sleep(0.7)

        bot.edit_message_text(

            f"✅ انتهى الفحص.\n\n"
            f"وجدت **{len(results)}** "
            f"إشارة مطابقة للشروط.\n\n"
            f"تم إرسال أفضل "
            f"**{len(top_results)}** فرص.",

            message.chat.id,

            status.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        bot.edit_message_text(

            "❌ حدث خطأ أثناء فحص السوق:\n\n"

            f"`{str(e)[:500]}`",

            message.chat.id,

            status.message_id,

            parse_mode="Markdown"
        )


# ============================================================
# COIN ANALYSIS
# ============================================================

@bot.message_handler(
    func=lambda message:
    message.text
    and
    not message.text.startswith("/")
)
def coin_handler(message):

    text = (
        message.text
        .strip()
        .upper()
    )

    if text == "SCAN":

        scan_command(message)

        return

    symbol = (
        text
        if text.endswith("USDT")
        else text + "USDT"
    )

    status = bot.reply_to(
        message,

        f"🔎 جاري تحليل "
        f"`{symbol}`...",

        parse_mode="Markdown"
    )

    try:

        result = analyze_symbol(
            symbol
        )

        if not result:

            try:

                price = get_current_price(
                    symbol
                )

                price_text = str(
                    price
                )

            except Exception:

                price_text = (
                    "غير متاح"
                )

            bot.edit_message_text(

                f"📊 `{symbol}`\n\n"

                f"💰 السعر الحالي من Binance:\n"
                f"`{price_text}`\n\n"

                "🟡 **لا توجد صفقة جاهزة حالياً.**\n\n"

                "شروط التحليل لم تكتمل.",

                message.chat.id,

                status.message_id,

                parse_mode="Markdown"
            )

            return

        bot.edit_message_text(

            build_trade_message(
                result
            ),

            message.chat.id,

            status.message_id,

            parse_mode="Markdown"
        )

    except Exception as e:

        bot.edit_message_text(

            "❌ تعذر تحليل العملة.\n\n"

            f"`{str(e)[:500]}`",

            message.chat.id,

            status.message_id,

            parse_mode="Markdown"
        )


# ============================================================
# RUN BOT
# ============================================================

if __name__ == "__main__":

    print(
        "🤖 Binance AI Scanner Started..."
    )

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )
