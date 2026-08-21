import os
import time
import requests

from flask import Flask, request

from analysis import (
    scan_market,
    analyze_symbol,
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

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TOKEN}"
)


app = Flask(__name__)


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_request(method, data=None):

    url = f"{TELEGRAM_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=30
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


# =========================================================
# SEND MESSAGE
# =========================================================

def send_message(chat_id, text):

    return telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================================================
# FORMAT SCAN RESULT
# =========================================================

def format_scan_result(result):

    symbol = result.get(
        "symbol",
        "-"
    )

    price = result.get(
        "price"
    )

    signal = result.get(
        "signal",
        "WAIT"
    )

    long_score = result.get(
        "long_score",
        0
    )

    short_score = result.get(
        "short_score",
        0
    )

    volume_ratio = result.get(
        "volume_ratio",
        0
    )

    volume_trend = result.get(
        "volume_trend",
        0
    )

    change_15m = result.get(
        "change_15m",
        0
    )

    change_30m = result.get(
        "change_30m",
        0
    )

    change_60m = result.get(
        "change_60m",
        0
    )

    rsi_value = result.get(
        "rsi"
    )

    text = (
        f"🪙 {symbol}\n"
        f"السعر: {format_price(price)}\n"
        f"الإشارة: {signal}\n"
        f"🟢 Long: {long_score}/100\n"
        f"🔴 Short: {short_score}/100\n"
        f"RSI: {rsi_value:.1f}\n"
        f"Volume: {volume_ratio:.2f}x\n"
        f"Volume Trend: {volume_trend:.2f}x\n"
        f"15m: {change_15m:+.2f}%\n"
        f"30m: {change_30m:+.2f}%\n"
        f"1H: {change_60m:+.2f}%"
    )

    trade = prepare_trade(
        result
    )

    if trade:

        text += (
            "\n\n"
            "🎯 الصفقة:\n"
            f"النوع: {trade['side']}\n"
            f"Entry: {trade['entry']}\n"
            f"SL: {trade['stop']}\n"
            f"TP1: {trade['tp1']}\n"
            f"TP2: {trade['tp2']}\n"
            f"TP3: {trade['tp3']}"
        )

    return text


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

    print("")
    print("==============================")
    print(">>> TELEGRAM UPDATE RECEIVED")
    print("==============================")

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

        print(
            ">>> CHAT:",
            chat_id
        )

        print(
            ">>> TEXT:",
            text
        )


        # =================================================
        # START
        # =================================================

        if text.startswith("/start"):

            send_message(
                chat_id,

                "🚀 Crypto Zero Reversal شغال يا محمد!\n\n"

                "Binance Scanner: ✅\n"
                "Multi-Timeframe: ✅\n"
                "Volume Analysis: ✅\n"
                "Early Accumulation: ✅\n"
                "Long / Short Detection: ✅\n\n"

                "الأوامر:\n\n"

                "/scan\n"
                "🔎 فحص السوق والبحث عن أفضل الفرص\n\n"

                "/coin AVAXUSDT\n"
                "📊 تحليل عملة بالتفصيل"
            )

            return "OK", 200


        # =================================================
        # SCAN
        # =================================================

        if text.startswith("/scan"):

            send_message(
                chat_id,

                "🔎 بدأ فحص السوق الحقيقي...\n\n"
                "⏳ جاري فحص السيولة والحجم والزخم\n"
                "📊 15m + 1H\n"
                "🟢 البحث عن التجميع قبل الـPump\n"
                "🔴 البحث عن ضعف الترند وفرص Short\n\n"
                "انتظر النتيجة..."
            )

            print(
                ">>> STARTING REAL MARKET SCAN"
            )

            try:

                results = scan_market(
                    limit=30
                )

            except Exception as e:

                print(
                    ">>> SCAN ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,

                    "❌ حدث خطأ أثناء Scanner.\n\n"
                    "راجع Render Logs لمعرفة السبب."
                )

                return "OK", 200

            # ---------------------------------------------
            # NO RESULTS
            # ---------------------------------------------

            if not results:

                send_message(
                    chat_id,

                    "🔎 نتيجة Scanner\n\n"
                    "❌ لم أجد صفقة قوية حاليًا.\n\n"
                    "البوت لم يدخل صفقة إجبارية، "
                    "والأفضل الانتظار حتى تظهر سيولة "
                    "وزخم وتأكيد أقوى."
                )

                print(
                    ">>> SCAN: NO STRONG RESULTS"
                )

                return "OK", 200


            # ---------------------------------------------
            # RESULTS
            # ---------------------------------------------

            # نأخذ أفضل 8 فقط
            top_results = results[:8]

            header = (
                "🔥 Crypto Zero Reversal\n"
                "📡 نتيجة Scanner\n\n"
            )

            send_message(
                chat_id,
                header
            )

            for index, result in enumerate(
                top_results,
                start=1
            ):

                text_result = format_scan_result(
                    result
                )

                message_text = (
                    f"#{index}\n"
                    f"{text_result}"
                )

                send_message(
                    chat_id,
                    message_text
                )

                time.sleep(
                    0.20
                )

            print(
                ">>> SCAN COMPLETE:",
                len(results),
                "signals"
            )

            return "OK", 200


        # =================================================
        # COIN
        # =================================================

        if text.startswith("/coin"):

            parts = text.split()

            if len(parts) < 2:

                send_message(
                    chat_id,

                    "اكتب العملة هكذا:\n\n"
                    "/coin AVAXUSDT"
                )

                return "OK", 200

            symbol = parts[1].upper()

            if not symbol.endswith("USDT"):
                symbol += "USDT"

            send_message(
                chat_id,

                f"📊 جاري تحليل {symbol}...\n\n"
                "Binance 15m + 1H"
            )

            print(
                ">>> ANALYZING COIN:",
                symbol
            )

            try:

                result = analyze_symbol(
                    symbol
                )

            except Exception as e:

                print(
                    ">>> COIN ANALYSIS ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,

                    "❌ حدث خطأ أثناء تحليل "
                    f"{symbol}.\n\n"
                    "راجع Render Logs."
                )

                return "OK", 200


            if not result:

                send_message(
                    chat_id,

                    "❌ لم أستطع جلب بيانات "
                    f"{symbol} من Binance."
                )

                return "OK", 200


            # ---------------------------------------------
            # COIN RESULT
            # ---------------------------------------------

            signal = result.get(
                "signal",
                "WAIT"
            )

            long_score = result.get(
                "long_score",
                0
            )

            short_score = result.get(
                "short_score",
                0
            )

            if signal in (
                "EARLY_LONG",
                "WATCH_LONG"
            ):

                direction = (
                    f"🟢 LONG\n"
                    f"القوة: {long_score}/100"
                )

            elif signal in (
                "SHORT",
                "WATCH_SHORT"
            ):

                direction = (
                    f"🔴 SHORT\n"
                    f"القوة: {short_score}/100"
                )

            else:

                direction = (
                    "⚪ WAIT\n"
                    "القوة: "
                    f"{max(long_score, short_score)}/100"
                )


            rsi_value = result.get(
                "rsi"
            )

            if rsi_value is None:
                rsi_text = "-"
            else:
                rsi_text = f"{rsi_value:.1f}"


            response = (
                f"📊 تحليل {symbol}\n\n"

                f"السعر: "
                f"{format_price(result.get('price'))}\n"

                f"الاتجاه: {direction}\n"

                f"RSI: {rsi_text}\n"

                f"EMA9: "
                f"{format_price(result.get('ema9'))}\n"

                f"EMA20: "
                f"{format_price(result.get('ema20'))}\n"

                f"Volume: "
                f"{result.get('volume_ratio', 0):.2f}x\n"

                f"Volume Trend: "
                f"{result.get('volume_trend', 0):.2f}x\n"

                f"15m: "
                f"{result.get('change_15m', 0):+.2f}%\n"

                f"30m: "
                f"{result.get('change_30m', 0):+.2f}%\n"

                f"1H: "
                f"{result.get('change_60m', 0):+.2f}%"
            )


            trade = prepare_trade(
                result
            )

            if trade:

                response += (

                    "\n\n"
                    "🎯 الصفقة المقترحة\n"

                    f"النوع: "
                    f"{trade['side']}\n"

                    f"Entry: "
                    f"{trade['entry']}\n"

                    f"SL: "
                    f"{trade['stop']}\n"

                    f"TP1: "
                    f"{trade['tp1']}\n"

                    f"TP2: "
                    f"{trade['tp2']}\n"

                    f"TP3: "
                    f"{trade['tp3']}"
                )

            else:

                response += (

                    "\n\n"
                    "⏳ لا توجد صفقة قوية حاليًا.\n"
                    "الأفضل الانتظار بدل الدخول "
                    "بدون تأكيد."
                )


            send_message(
                chat_id,
                response
            )

            print(
                ">>> COIN ANALYSIS SENT:",
                symbol,
                signal
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
            "/coin AVAXUSDT"
        )

        return "OK", 200


    except Exception as e:

        print(
            ">>> WEBHOOK ERROR:",
            repr(e)
        )

        return "ERROR", 500


# =========================================================
# WEBHOOK SETUP
# =========================================================

def setup_webhook():

    time.sleep(3)

    print("")
    print("==============================")
    print("SETTING WEBHOOK:")
    print(WEBHOOK_URL)
    print("==============================")


    telegram_request(
        "deleteWebhook",
        {
            "drop_pending_updates": True
        }
    )

    time.sleep(2)


    result = telegram_request(
        "setWebhook",
        {
            "url": WEBHOOK_URL,
            "drop_pending_updates": True
        }
    )

    print(
        "SET WEBHOOK RESULT:",
        result
    )


    info = telegram_request(
        "getWebhookInfo"
    )

    print(
        "WEBHOOK INFO:",
        info
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
        f"Starting Flask on 0.0.0.0:{port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
