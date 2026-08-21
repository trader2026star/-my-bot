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

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

RENDER_URL = os.environ.get(
    "RENDER_URL",
    "https://my-bot-mtyr.onrender.com"
).rstrip("/")

WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_URL = RENDER_URL + WEBHOOK_PATH

TELEGRAM_API = "https://api.telegram.org/bot" + TOKEN

app = Flask(__name__)


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_request(method, data=None):

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
            response.text[:500]
        )

        return response.json()

    except Exception as e:

        print(
            "Telegram API ERROR:",
            repr(e)
        )

        return None


def send_message(chat_id, text):

    max_length = 3900

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

        part = text[i:i + max_length]

        result = telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": part
            }
        )

    return result


# =========================================================
# FORMAT HELPERS
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


def tf_direction(bull, bear):

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
# COIN ANALYSIS MESSAGE
# =========================================================

def build_coin_message(result):

    symbol = result["symbol"]
    price = result["price"]

    signal = result["signal"]

    long_score = result["long_score"]
    short_score = result["short_score"]

    message = ""

    message += "📊 تحليل " + symbol + "\n\n"

    message += (
        "💰 السعر: "
        + fmt_price(price)
        + "\n\n"
    )

    message += (
        "🎯 الاتجاه النهائي: "
        + final_direction(result)
        + "\n"
    )

    message += (
        "🟢 Long: "
        + str(long_score)
        + "/100\n"
    )

    message += (
        "🔴 Short: "
        + str(short_score)
        + "/100\n\n"
    )

    # =====================================================
    # MULTI TIMEFRAME
    # =====================================================

    message += "📊 MULTI TIMEFRAME\n\n"

    message += (
        "15m: "
        + tf_direction(
            result["tf15_bull"],
            result["tf15_bear"]
        )
        + "\n"
    )

    message += (
        "30m: "
        + tf_direction(
            result["tf30_bull"],
            result["tf30_bear"]
        )
        + "\n"
    )

    message += (
        "1H: "
        + tf_direction(
            result["tf1h_bull"],
            result["tf1h_bear"]
        )
        + "\n"
    )

    message += (
        "4H: "
        + tf_direction(
            result["tf4h_bull"],
            result["tf4h_bear"]
        )
        + "\n"
    )

    message += (
        "1D: "
        + tf_direction(
            result["tf1d_bull"],
            result["tf1d_bear"]
        )
        + "\n\n"
    )

    # =====================================================
    # RSI
    # =====================================================

    message += "📈 RSI\n"

    message += (
        "15m: "
        + fmt_rsi(result["rsi15"])
        + "\n"
    )

    message += (
        "1H: "
        + fmt_rsi(result["rsi1h"])
        + "\n"
    )

    message += (
        "4H: "
        + fmt_rsi(result["rsi4h"])
        + "\n"
    )

    message += (
        "1D: "
        + fmt_rsi(result["rsi1d"])
        + "\n\n"
    )

    # =====================================================
    # EMA
    # =====================================================

    message += "📊 EMA\n"

    message += (
        "EMA9: "
        + fmt_price(result["ema9"])
        + "\n"
    )

    message += (
        "EMA20: "
        + fmt_price(result["ema20"])
        + "\n"
    )

    message += (
        "EMA50: "
        + fmt_price(result["ema50"])
        + "\n"
    )

    message += (
        "EMA200: "
        + fmt_price(result["ema200"])
        + "\n\n"
    )

    # =====================================================
    # VOLUME
    # =====================================================

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
        + "x\n\n"
    )

    # =====================================================
    # PRICE CHANGES
    # =====================================================

    message += "📉 الحركة\n"

    message += (
        "15m: "
        + fmt_pct(result["change15"])
        + "\n"
    )

    message += (
        "30m: "
        + fmt_pct(result["change30"])
        + "\n"
    )

    message += (
        "1H: "
        + fmt_pct(result["change1h"])
        + "\n"
    )

    message += (
        "4H: "
        + fmt_pct(result["change4h"])
        + "\n"
    )

    message += (
        "1D: "
        + fmt_pct(result["change1d"])
        + "\n\n"
    )

    # =====================================================
    # MARKET STRUCTURE
    # =====================================================

    message += "🔎 MARKET STRUCTURE\n"

    if result["accumulation"]:
        message += "🟢 Accumulation: YES ✅\n"
    else:
        message += "🟢 Accumulation: NO\n"

    if result["distribution"]:
        message += "🔴 Distribution: YES ⚠️\n"
    else:
        message += "🔴 Distribution: NO\n"

    if result["late_pump"]:
        message += "🚀 Late Pump Risk: HIGH ⚠️\n"
    else:
        message += "🚀 Late Pump Risk: LOW ✅\n"

    # =====================================================
    # TRADE
    # =====================================================

    trade = prepare_trade(result)

    if trade:

        message += "\n🎯 الصفقة المقترحة\n\n"

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
            "\n⏳ لا توجد صفقة قوية حاليًا.\n"
            "الأفضل الانتظار بدل الدخول بدون تأكيد.\n"
        )

    # =====================================================
    # REASONS
    # =====================================================

    reasons = []

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

    if reasons:

        message += "\n🧠 أسباب الإشارة:\n"

        for reason in reasons[:6]:

            message += (
                "• "
                + str(reason)
                + "\n"
            )

    return message


# =========================================================
# SCAN MESSAGE
# =========================================================

def build_scan_message(results):

    if not results:

        return (
            "🔥 Crypto Zero Reversal\n\n"
            "📡 Multi-Timeframe Scanner\n\n"
            "15m + 30m + 1H + 4H + 1D\n\n"
            "⚪ لا توجد عملات تحقق شروط "
            "الإشارة القوية حاليًا.\n\n"
            "وده أفضل من إجبار البوت "
            "على صفقة ضعيفة."
        )

    message = (
        "🔥 Crypto Zero Reversal\n"
        "📡 Multi-Timeframe Scanner\n\n"
        "15m + 30m + 1H + 4H + 1D\n\n"
    )

    for index, result in enumerate(
        results[:8],
        1
    ):

        message += (
            "#"
            + str(index)
            + "\n"
        )

        message += (
            "🪙 "
            + result["symbol"]
            + "\n"
        )

        message += (
            "💰 السعر: "
            + fmt_price(result["price"])
            + "\n"
        )

        message += (
            "📌 الإشارة: "
            + result["signal"]
            + "\n"
        )

        message += (
            "🟢 Long: "
            + str(result["long_score"])
            + "/100\n"
        )

        message += (
            "🔴 Short: "
            + str(result["short_score"])
            + "/100\n\n"
        )

        message += "📊 الاتجاهات:\n"

        message += (
            "15m: "
            + tf_direction(
                result["tf15_bull"],
                result["tf15_bear"]
            )
            + "\n"
        )

        message += (
            "30m: "
            + tf_direction(
                result["tf30_bull"],
                result["tf30_bear"]
            )
            + "\n"
        )

        message += (
            "1H: "
            + tf_direction(
                result["tf1h_bull"],
                result["tf1h_bear"]
            )
            + "\n"
        )

        message += (
            "4H: "
            + tf_direction(
                result["tf4h_bull"],
                result["tf4h_bear"]
            )
            + "\n"
        )

        message += (
            "1D: "
            + tf_direction(
                result["tf1d_bull"],
                result["tf1d_bear"]
            )
            + "\n\n"
        )

        message += (
            "RSI 15m: "
            + fmt_rsi(result["rsi15"])
            + "\n"
        )

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

        message += (
            "15m: "
            + fmt_pct(result["change15"])
            + "\n"
        )

        message += (
            "30m: "
            + fmt_pct(result["change30"])
            + "\n"
        )

        message += (
            "1H: "
            + fmt_pct(result["change1h"])
            + "\n"
        )

        message += (
            "4H: "
            + fmt_pct(result["change4h"])
            + "\n"
        )

        message += (
            "1D: "
            + fmt_pct(result["change1d"])
            + "\n"
        )

        trade = prepare_trade(result)

        if trade:

            message += "\n🎯 الصفقة:\n"

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
            limit=20
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
            "❌ حدث خطأ أثناء فحص السوق:\n\n"
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
    WEBHOOK_PATH,
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

        print(
            "CHAT:",
            chat_id,
            "TEXT:",
            text
        )

        # =================================================
        # START
        # =================================================

        if text.lower().startswith(
            "/start"
        ):

            send_message(
                chat_id,

                "🚀 Crypto Zero Reversal شغال!\n\n"
                "📊 Multi-Timeframe Analysis\n"
                "15m + 30m + 1H + 4H + 1D\n\n"
                "الأوامر:\n\n"
                "/scan\n"
                "🔎 فحص السوق\n\n"
                "/coin BTCUSDT\n"
                "📊 تحليل عملة\n\n"
                "البوت لا يجبر صفقة بدون تأكيد."
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
                "📊 15m + 30m + 1H + 4H + 1D\n"
                "🟢 فحص التجميع قبل الـPump\n"
                "🔴 فحص التوزيع وضعف الترند\n"
                "⏳ جاري التحليل..."
            )

            thread = threading.Thread(
                target=run_scan,
                args=(chat_id,),
                daemon=True
            )

            thread.start()

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
                    "اكتب العملة هكذا:\n\n"
                    "/coin BTCUSDT"
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
                "⏳ 15m + 30m + 1H + 4H + 1D\n"
                "⏳ جاري فحص الاتجاه والحجم والزخم..."
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

                message = build_coin_message(
                    result
                )

                send_message(
                    chat_id,
                    message
                )

            except Exception as e:

                print(
                    "COIN ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,
                    "❌ حدث خطأ أثناء التحليل:\n\n"
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
            "/coin BTCUSDT"
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
        "SETTING WEBHOOK:"
    )

    print(
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
