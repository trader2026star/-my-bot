import os
import threading
import requests

from flask import Flask, request

from analysis import (
    analyze_symbol,
    scan_market,
    prepare_trade,
    format_price
)


# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

if not TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing"
    )

RENDER_URL = os.environ.get(
    "RENDER_URL",
    "https://my-bot-mtyr.onrender.com"
).rstrip("/")

WEBHOOK_PATH = "/telegram/webhook"

WEBHOOK_URL = (
    RENDER_URL
    + WEBHOOK_PATH
)

TELEGRAM_API = (
    "https://api.telegram.org/bot"
    + TOKEN
)

app = Flask(__name__)


# =========================================================
# TELEGRAM
# =========================================================

def telegram_request(
    method,
    data=None
):

    try:

        response = requests.post(
            TELEGRAM_API + "/" + method,
            json=data or {},
            timeout=20
        )

        print(
            "Telegram:",
            method,
            response.status_code,
            response.text[:300]
        )

        return response.json()

    except Exception as e:

        print(
            "Telegram ERROR:",
            repr(e)
        )

        return None


def send_message(
    chat_id,
    text
):

    max_length = 3900

    if not text:
        text = "⚠️ لا توجد بيانات."

    if len(text) <= max_length:

        return telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text
            }
        )

    result = None

    for i in range(
        0,
        len(text),
        max_length
    ):

        result = telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[
                    i:i + max_length
                ]
            }
        )

    return result


# =========================================================
# FORMAT
# =========================================================

def fmt_price(value):

    if value is None:
        return "-"

    return format_price(value)


def fmt_pct(value):

    if value is None:
        return "-"

    return "{:+.2f}%".format(
        value
    )


def fmt_rsi(value):

    if value is None:
        return "-"

    return "{:.1f}".format(
        value
    )


def fmt_number(value):

    if value is None:
        return "-"

    return "{:.4f}".format(
        float(value)
    )


def tf_direction(
    bull,
    bear
):

    if bull > bear:
        return "🟢 صاعد"

    if bear > bull:
        return "🔴 هابط"

    return "⚪ محايد"


def final_direction(result):

    signal = result.get(
        "signal",
        "WAIT"
    )

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        return "🟢 LONG"

    if signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        return "🔴 SHORT"

    return "⚪ WAIT"


# =========================================================
# COIN MESSAGE
# =========================================================

def build_coin_message(
    result
):

    symbol = result["symbol"]

    message = (
        "🔥 Crypto Zero Reversal\n"
        "━━━━━━━━━━━━━━\n"
        "📊 تحليل فني كامل\n\n"
    )

    message += (
        "🪙 العملة: "
        + symbol
        + "\n"
    )

    message += (
        "💰 السعر: "
        + fmt_price(
            result["price"]
        )
        + "\n\n"
    )

    # =====================================================
    # FINAL DIRECTION
    # =====================================================

    message += (
        "🎯 الاتجاه النهائي: "
        + final_direction(result)
        + "\n"
    )

    message += (
        "🟢 Long: "
        + str(
            result["long_score"]
        )
        + "/100\n"
    )

    message += (
        "🔴 Short: "
        + str(
            result["short_score"]
        )
        + "/100\n\n"
    )

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    message += (
        "📊 MULTI TIMEFRAME\n"
    )

    for name, bull, bear in [
        (
            "15m",
            result["tf15_bull"],
            result["tf15_bear"]
        ),
        (
            "30m",
            result["tf30_bull"],
            result["tf30_bear"]
        ),
        (
            "1H",
            result["tf1h_bull"],
            result["tf1h_bear"]
        ),
        (
            "4H",
            result["tf4h_bull"],
            result["tf4h_bear"]
        ),
        (
            "1D",
            result["tf1d_bull"],
            result["tf1d_bear"]
        )
    ]:

        message += (
            name
            + ": "
            + tf_direction(
                bull,
                bear
            )
            + "\n"
        )

    # =====================================================
    # RSI
    # =====================================================

    message += "\n📈 RSI\n"

    message += (
        "15m: "
        + fmt_rsi(
            result["rsi15"]
        )
        + "\n"
    )

    message += (
        "1H: "
        + fmt_rsi(
            result["rsi1h"]
        )
        + "\n"
    )

    message += (
        "4H: "
        + fmt_rsi(
            result["rsi4h"]
        )
        + "\n"
    )

    message += (
        "1D: "
        + fmt_rsi(
            result["rsi1d"]
        )
        + "\n"
    )

    # =====================================================
    # EMA
    # =====================================================

    message += "\n📊 EMA\n"

    for name in [
        "ema9",
        "ema20",
        "ema50",
        "ema200"
    ]:

        message += (
            name.upper()
            + ": "
            + fmt_price(
                result[name]
            )
            + "\n"
        )

    # =====================================================
    # MACD
    # =====================================================

    message += "\n📉 MACD\n"

    message += (
        "MACD: "
        + fmt_number(
            result.get("macd")
        )
        + "\n"
    )

    message += (
        "Signal: "
        + fmt_number(
            result.get("macd_signal")
        )
        + "\n"
    )

    message += (
        "Histogram: "
        + fmt_number(
            result.get("macd_hist")
        )
        + "\n"
    )

    # =====================================================
    # VOLUME
    # =====================================================

    message += "\n📦 VOLUME / LIQUIDITY\n"

    message += (
        "Volume: "
        + "{:.2f}".format(
            result["volume_ratio"]
        )
        + "x\n"
    )

    message += (
        "Volume Trend: "
        + "{:.2f}".format(
            result["volume_trend"]
        )
        + "x\n"
    )

    # =====================================================
    # PRICE MOVEMENT
    # =====================================================

    message += "\n📉 الحركة\n"

    for name, key in [
        ("15m", "change15"),
        ("30m", "change30"),
        ("1H", "change1h"),
        ("4H", "change4h"),
        ("1D", "change1d")
    ]:

        message += (
            name
            + ": "
            + fmt_pct(
                result[key]
            )
            + "\n"
        )

    # =====================================================
    # TECHNICAL LEVELS
    # =====================================================

    message += "\n🧱 التحليل الفني\n"

    message += (
        "Support: "
        + fmt_price(
            result.get("support")
        )
        + "\n"
    )

    message += (
        "Resistance: "
        + fmt_price(
            result.get("resistance")
        )
        + "\n"
    )

    message += (
        "ATR: "
        + fmt_price(
            result.get("atr")
        )
        + "\n"
    )

    message += (
        "Volatility: "
        + fmt_pct(
            result.get(
                "volatility_pct"
            )
        )
        + "\n"
    )

    # =====================================================
    # QUANTITATIVE RANGE
    # =====================================================

    message += (
        "\n📐 النطاق الكمي "
        "(Quantitative Range)\n"
    )

    message += (
        "QR Low: "
        + fmt_price(
            result.get("qr_low")
        )
        + "\n"
    )

    message += (
        "QR High: "
        + fmt_price(
            result.get("qr_high")
        )
        + "\n"
    )

    message += (
        "QR Width: "
        + fmt_pct(
            result.get(
                "qr_width_pct"
            )
        )
        + "\n"
    )

    # =====================================================
    # MARKET STRUCTURE
    # =====================================================

    message += (
        "\n🔎 MARKET STRUCTURE\n"
    )

    message += (
        "🟢 Accumulation: "
        + (
            "YES ✅"
            if result.get(
                "accumulation"
            )
            else "NO"
        )
        + "\n"
    )

    message += (
        "🔴 Distribution: "
        + (
            "YES ⚠️"
            if result.get(
                "distribution"
            )
            else "NO"
        )
        + "\n"
    )

    message += (
        "🚀 Late Pump: "
        + (
            "HIGH ⚠️"
            if result.get(
                "late_pump"
            )
            else "LOW ✅"
        )
        + "\n"
    )

    message += (
        "🔥 Overheated: "
        + (
            "YES ⚠️"
            if result.get(
                "overheated"
            )
            else "NO"
        )
        + "\n"
    )

    message += (
        "💥 Strong Dump: "
        + (
            "YES ⚠️"
            if result.get(
                "strong_dump"
            )
            else "NO"
        )
        + "\n"
    )

    # =====================================================
    # TRADE
    # =====================================================

    trade = prepare_trade(
        result
    )

    if trade:

        message += (
            "\n🎯 الصفقة المقترحة\n\n"
        )

        message += (
            "النوع: "
            + trade["side"]
            + "\n"
        )

        message += (
            "Entry: "
            + trade["entry"]
            + "\n"
        )

        message += (
            "SL: "
            + trade["stop"]
            + "\n"
        )

        message += (
            "TP1: "
            + trade["tp1"]
            + "\n"
        )

        message += (
            "TP2: "
            + trade["tp2"]
            + "\n"
        )

        message += (
            "TP3: "
            + trade["tp3"]
            + "\n"
        )

    else:

        message += (
            "\n⏳ لا توجد صفقة مؤكدة حاليًا.\n"
            "البوت ينتظر شروطًا أفضل.\n"
        )

    # =====================================================
    # REASONS
    # =====================================================

    signal = result.get(
        "signal",
        "WAIT"
    )

    if signal in (
        "EARLY_LONG",
        "WATCH_LONG"
    ):

        reasons = result.get(
            "long_reasons",
            []
        )

    elif signal in (
        "SHORT",
        "WATCH_SHORT"
    ):

        reasons = result.get(
            "short_reasons",
            []
        )

    else:

        reasons = []

    if reasons:

        message += (
            "\n🧠 أسباب الإشارة:\n"
        )

        for reason in reasons[:7]:

            message += (
                "• "
                + str(reason)
                + "\n"
            )

    return message


# =========================================================
# SCAN MESSAGE
# =========================================================

def build_scan_message(
    results
):

    if not results:

        return (
            "🔥 Crypto Zero Reversal\n\n"
            "⚠️ لم تصل بيانات كافية من Binance.\n\n"
            "أعد /scan بعد لحظات."
        )

    message = (
        "🔥 Crypto Zero Reversal\n"
        "📡 BEST MARKET SETUPS\n\n"
        "15m + 30m + 1H + 4H + 1D\n"
        "📐 Quantitative Range\n"
        "📈 Technical Analysis\n"
        "💧 Liquidity + Volume + Momentum\n"
        "🎯 Entry / SL / TP\n\n"
    )

    for index, result in enumerate(
        results[:8],
        1
    ):

        signal = result.get(
            "signal",
            "WAIT"
        )

        if signal == "EARLY_LONG":

            setup = (
                "🟢 LONG — تجميع قبل الحركة"
            )

        elif signal == "WATCH_LONG":

            setup = (
                "🟢 LONG — مراقبة دخول"
            )

        elif signal == "SHORT":

            setup = (
                "🔴 SHORT — خروج سيولة"
            )

        elif signal == "WATCH_SHORT":

            setup = (
                "🔴 SHORT — مراقبة ضعف"
            )

        else:

            setup = (
                "⚪ WAIT"
            )

        message += (
            "#"
            + str(index)
            + " 🪙 "
            + result["symbol"]
            + "\n"
        )

        message += (
            "💰 السعر: "
            + fmt_price(
                result["price"]
            )
            + "\n"
        )

        message += (
            "🎯 الحالة: "
            + setup
            + "\n"
        )

        message += (
            "🟢 Long: "
            + str(
                result["long_score"]
            )
            + "/100\n"
        )

        message += (
            "🔴 Short: "
            + str(
                result["short_score"]
            )
            + "/100\n"
        )

        message += (
            "📊 MTF: "
            + tf_direction(
                result["tf1h_bull"]
                + result["tf4h_bull"]
                + result["tf1d_bull"],
                result["tf1h_bear"]
                + result["tf4h_bear"]
                + result["tf1d_bear"]
            )
            + "\n"
        )

        message += (
            "📈 RSI 15m: "
            + fmt_rsi(
                result["rsi15"]
            )
            + "\n"
        )

        message += (
            "📦 Volume: "
            + "{:.2f}".format(
                result["volume_ratio"]
            )
            + "x\n"
        )

        message += (
            "📈 Volume Trend: "
            + "{:.2f}".format(
                result["volume_trend"]
            )
            + "x\n"
        )

        message += (
            "📐 QR: "
            + fmt_price(
                result.get("qr_low")
            )
            + " → "
            + fmt_price(
                result.get("qr_high")
            )
            + "\n"
        )

        if result.get(
            "accumulation"
        ):

            message += (
                "🟢 Accumulation: YES ✅\n"
            )

        if result.get(
            "distribution"
        ):

            message += (
                "🔴 Distribution: YES ⚠️\n"
            )

        if result.get(
            "late_pump"
        ):

            message += (
                "🚀 Late Pump: HIGH ⚠️\n"
            )

        if result.get(
            "overheated"
        ):

            message += (
                "🔥 Overheated: YES ⚠️\n"
            )

        trade = prepare_trade(
            result
        )

        if trade:

            message += (
                "\n🎯 الصفقة:\n"
            )

            message += (
                "النوع: "
                + trade["side"]
                + "\n"
            )

            message += (
                "Entry: "
                + trade["entry"]
                + "\n"
            )

            message += (
                "SL: "
                + trade["stop"]
                + "\n"
            )

            message += (
                "TP1: "
                + trade["tp1"]
                + "\n"
            )

            message += (
                "TP2: "
                + trade["tp2"]
                + "\n"
            )

            message += (
                "TP3: "
                + trade["tp3"]
                + "\n"
            )

        else:

            message += (
                "\n⏳ لا يوجد دخول آمن الآن.\n"
            )

        if signal in (
            "EARLY_LONG",
            "WATCH_LONG"
        ):

            reasons = result.get(
                "long_reasons",
                []
            )

        elif signal in (
            "SHORT",
            "WATCH_SHORT"
        ):

            reasons = result.get(
                "short_reasons",
                []
            )

        else:

            reasons = []

        if reasons:

            message += (
                "\n🧠 الأسباب:\n"
            )

            for reason in reasons[:5]:

                message += (
                    "• "
                    + str(reason)
                    + "\n"
                )

        message += (
            "\n━━━━━━━━━━━━━━\n\n"
        )

    return message


# =========================================================
# BACKGROUND SCAN
# =========================================================

def run_scan(chat_id):

    try:

        results = scan_market(
            limit=15
        )

        message = build_scan_message(
            results
        )

        send_message(
            chat_id,
            message
        )

    except Exception as e:

        print(
            "SCAN ERROR:",
            repr(e)
        )

        send_message(
            chat_id,
            "❌ خطأ في Scanner:\n"
            + repr(e)
        )


# =========================================================
# HOME
# =========================================================

@app.route(
    "/",
    methods=["GET", "HEAD"]
)
def home():

    return (
        "Crypto Zero Reversal Bot is running.",
        200
    )


@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return "OK", 200


# =========================================================
# WEBHOOK
# =========================================================

@app.route(
    "/telegram/webhook",
    methods=["POST"]
)
def telegram_webhook():

    try:

        update = request.get_json(
            silent=True
        )

        print(
            "UPDATE:",
            update
        )

        if not update:
            return "OK", 200

        message = update.get(
            "message"
        )

        if not message:
            return "OK", 200

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get(
            "id"
        )

        text = message.get(
            "text",
            ""
        ).strip()

        if not chat_id:
            return "OK", 200

        # =================================================
        # START
        # =================================================

        if text.lower().startswith(
            "/start"
        ):

            send_message(
                chat_id,

                "🚀 Crypto Zero Reversal شغال!\n\n"

                "📊 التحليل الفني:\n"
                "EMA + RSI + MACD + ATR\n"
                "Support / Resistance\n\n"

                "📐 النطاق الكمي:\n"
                "Quantitative Range\n\n"

                "📊 Multi-Timeframe:\n"
                "15m + 30m + 1H + 4H + 1D\n\n"

                "💧 Liquidity + Volume\n"
                "🟢 Accumulation\n"
                "🔴 Distribution\n\n"

                "الأوامر:\n\n"
                "/scan\n"
                "🔎 فحص السوق\n\n"
                "/coin BTC\n"
                "📊 تحليل العملة وتجهيز الصفقة\n\n"
                "🎯 Entry / SL / TP1 / TP2 / TP3"
            )

            return "OK", 200

        # =================================================
        # SCAN
        # =================================================

        if text.lower().startswith(
            "/scan"
        ):

            send_message(
                chat_id,

                "🔎 بدأ فحص السوق الحقيقي...\n\n"
                "📐 النطاق الكمي\n"
                "📈 التحليل الفني\n"
                "💧 السيولة والحجم\n"
                "📊 15m + 30m + 1H + 4H + 1D\n\n"
                "🟢 البحث عن تجميع قبل الحركة\n"
                "🔴 البحث عن Distribution والضعف\n\n"
                "⏳ جاري التحليل..."
            )

            threading.Thread(
                target=run_scan,
                args=(chat_id,),
                daemon=True
            ).start()

            return "OK", 200

        # =================================================
        # COIN
        # =================================================

        if text.lower().startswith(
            "/coin"
        ):

            parts = text.split()

            if len(parts) < 2:

                send_message(
                    chat_id,
                    "اكتب:\n\n"
                    "/coin BTC"
                )

                return "OK", 200

            symbol = parts[1].upper()

            if not symbol.endswith(
                "USDT"
            ):

                symbol += "USDT"

            send_message(
                chat_id,

                "📊 جاري تحليل "
                + symbol
                + "...\n\n"
                "📈 التحليل الفني\n"
                "📐 النطاق الكمي\n"
                "💧 السيولة + التجميع + التوزيع\n"
                "📊 15m + 30m + 1H + 4H + 1D\n"
                "🎯 تجهيز الصفقة..."
            )

            try:

                result = analyze_symbol(
                    symbol
                )

                if not result:

                    send_message(
                        chat_id,
                        "❌ لم أستطع جلب بيانات "
                        + symbol
                        + " من Binance."
                    )

                    return "OK", 200

                send_message(
                    chat_id,
                    build_coin_message(
                        result
                    )
                )

            except Exception as e:

                print(
                    "COIN ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,
                    "❌ حدث خطأ أثناء التحليل:\n"
                    + repr(e)
                )

            return "OK", 200

        # =================================================
        # UNKNOWN
        # =================================================

        send_message(
            chat_id,

            "👋 البوت متصل.\n\n"
            "استخدم:\n"
            "/start\n"
            "/scan\n"
            "/coin BTC"
        )

        return "OK", 200

    except Exception as e:

        print(
            "WEBHOOK ERROR:",
            repr(e)
        )

        return "OK", 200


# =========================================================
# WEBHOOK SETUP
# =========================================================

def setup_webhook():

    print(
        "SETTING WEBHOOK:",
        WEBHOOK_URL
    )

    try:

        delete_result = telegram_request(
            "deleteWebhook",
            {
                "drop_pending_updates": True
            }
        )

        print(
            "DELETE WEBHOOK:",
            delete_result
        )

        set_result = telegram_request(
            "setWebhook",
            {
                "url": WEBHOOK_URL,
                "drop_pending_updates": True
            }
        )

        print(
            "SET WEBHOOK:",
            set_result
        )

        info = telegram_request(
            "getWebhookInfo"
        )

        print(
            "WEBHOOK INFO:",
            info
        )

    except Exception as e:

        print(
            "WEBHOOK SETUP ERROR:",
            repr(e)
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    setup_webhook()

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    print(
        "Starting Flask on 0.0.0.0:"
        + str(port)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
