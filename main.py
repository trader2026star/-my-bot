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

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

app = Flask(__name__)


# =========================================================
# TELEGRAM
# =========================================================

def telegram_request(method, data=None):
    try:
        response = requests.post(
            f"{TELEGRAM_API}/{method}",
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
        print("Telegram API ERROR:", repr(e))
        return None


def send_message(chat_id, text):
    return telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================================================
# HOME / HEALTH
# =========================================================

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Crypto Zero Reversal Bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


# =========================================================
# SCAN FORMAT
# =========================================================

def format_scan_result(result, number):

    signal = result.get("signal")

    if signal in ("EARLY_LONG", "WATCH_LONG"):
        emoji = "🟢"
        side = "LONG"
        score = result["long_score"]
        reasons = result.get("long_reasons", [])

    elif signal in ("SHORT", "WATCH_SHORT"):
        emoji = "🔴"
        side = "SHORT"
        score = result["short_score"]
        reasons = result.get("short_reasons", [])

    else:
        return ""

    trade = prepare_trade(result)

    if not trade:
        return ""

    reasons_text = (
        "، ".join(reasons)
        if reasons
        else "تأكيدات محدودة"
    )

    return (
        f"{number}️⃣ {emoji} {result['symbol']}\n"
        f"الاتجاه: {side}\n"
        f"القوة: {score}/100\n"
        f"السعر: {format_price(result['price'])}\n"
        f"RSI: {result['rsi']:.1f}\n"
        f"Volume: {result['volume_ratio']:.2f}x\n"
        f"15m: {result['change_15m']:+.2f}%\n"
        f"30m: {result['change_30m']:+.2f}%\n"
        f"السبب: {reasons_text}\n\n"
        f"🎯 دخول: {trade['entry']}\n"
        f"🛑 SL: {trade['stop']}\n"
        f"TP1: {trade['tp1']}\n"
        f"TP2: {trade['tp2']}\n"
        f"TP3: {trade['tp3']}\n"
    )


# =========================================================
# COIN FORMAT
# =========================================================

def format_coin_result(result):

    if not result:
        return (
            "❌ لم أستطع جلب بيانات العملة من Binance."
        )

    signal = result["signal"]

    if signal in ("EARLY_LONG", "WATCH_LONG"):
        direction = "🟢 LONG"
        score = result["long_score"]
        reasons = result["long_reasons"]

    elif signal in ("SHORT", "WATCH_SHORT"):
        direction = "🔴 SHORT"
        score = result["short_score"]
        reasons = result["short_reasons"]

    else:
        direction = "⚪ WAIT"
        score = max(
            result["long_score"],
            result["short_score"]
        )
        reasons = []

    text = (
        f"📊 تحليل {result['symbol']}\n\n"
        f"السعر: {format_price(result['price'])}\n"
        f"الاتجاه: {direction}\n"
        f"القوة: {score}/100\n\n"
        f"RSI: {result['rsi']:.1f}\n"
        f"EMA9: {format_price(result['ema9'])}\n"
        f"EMA20: {format_price(result['ema20'])}\n"
        f"Volume: {result['volume_ratio']:.2f}x\n"
        f"Volume Trend: {result['volume_trend']:.2f}x\n"
        f"15m: {result['change_15m']:+.2f}%\n"
        f"30m: {result['change_30m']:+.2f}%\n"
        f"1H: {result['change_60m']:+.2f}%\n\n"
    )

    if reasons:
        text += (
            "🔎 التأكيدات:\n"
            + "\n".join(
                f"• {x}" for x in reasons
            )
            + "\n\n"
        )

    if signal == "WAIT":
        text += (
            "⏳ لا توجد صفقة قوية حاليًا.\n"
            "الأفضل الانتظار بدل الدخول بدون تأكيد."
        )
        return text

    trade = prepare_trade(result)

    if not trade:
        return text

    text += (
        "━━━━━━━━━━━━━━\n"
        "🎯 الصفقة المحتملة\n"
        "━━━━━━━━━━━━━━\n\n"
        f"الدخول: {trade['entry']}\n"
        f"🛑 SL: {trade['stop']}\n"
        f"🎯 TP1: {trade['tp1']}\n"
        f"🎯 TP2: {trade['tp2']}\n"
        f"🎯 TP3: {trade['tp3']}\n\n"
        "⚠️ تحليل وليس ضمانًا للربح."
    )

    return text


# =========================================================
# WEBHOOK
# =========================================================

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():

    print("==============================")
    print(">>> TELEGRAM UPDATE RECEIVED")
    print("==============================")

    try:

        update = request.get_json(silent=True)

        if not update:
            return "OK", 200

        message = update.get("message")

        if not message:
            return "OK", 200

        chat = message.get("chat", {})
        chat_id = chat.get("id")

        text = message.get(
            "text",
            ""
        ).strip()

        if not chat_id:
            return "OK", 200

        print("CHAT:", chat_id)
        print("TEXT:", text)

        # =================================================
        # START
        # =================================================

        if text.startswith("/start"):

            send_message(
                chat_id,
                "🚀 Crypto Zero Reversal Bot\n\n"
                "Binance Scanner: ✅\n"
                "Multi-Timeframe: ✅\n\n"
                "الأوامر:\n\n"
                "/scan\n"
                "🔎 فحص السوق الحقيقي\n\n"
                "/coin AVAXUSDT\n"
                "📊 تحليل عملة محددة"
            )

            return "OK", 200

        # =================================================
        # SCAN
        # =================================================

        if text.startswith("/scan"):

            send_message(
                chat_id,
                "🔎 جاري فحص Binance...\n\n"
                "🟢 البحث عن التجميع قبل الحركة\n"
                "🟢 Volume تدريجي\n"
                "🟢 تحسن Momentum\n"
                "🔴 البحث عن فرص Short\n"
                "📊 تأكيد 15m + 1H\n\n"
                "⏳ انتظر النتيجة..."
            )

            try:

                results = scan_market(limit=30)

                if not results:

                    send_message(
                        chat_id,
                        "⚪ لا توجد حاليًا فرصة قوية "
                        "بالشروط المطلوبة.\n\n"
                        "WAIT أفضل من صفقة ضعيفة."
                    )

                    return "OK", 200

                output = (
                    "🔎 نتائج Scanner\n"
                    "━━━━━━━━━━━━━━\n\n"
                )

                count = 0

                for result in results[:5]:

                    block = format_scan_result(
                        result,
                        count + 1
                    )

                    if block:

                        output += (
                            block
                            + "━━━━━━━━━━━━━━\n"
                        )

                        count += 1

                if count == 0:
                    output = (
                        "⚪ لم يتم العثور على صفقة "
                        "مطابقة بقوة كافية."
                    )

                send_message(
                    chat_id,
                    output
                )

            except Exception as e:

                print(
                    "SCAN COMMAND ERROR:",
                    repr(e)
                )

                send_message(
                    chat_id,
                    "❌ حدث خطأ أثناء فحص السوق.\n"
                    "راجع Render Logs."
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

            symbol = (
                parts[1]
                .upper()
                .replace("/", "")
            )

            if not symbol.endswith("USDT"):
                symbol += "USDT"

            if not symbol.isalnum():

                send_message(
                    chat_id,
                    "❌ رمز العملة غير صحيح."
                )

                return "OK", 200

            send_message(
                chat_id,
                f"📊 جاري تحليل {symbol}...\n\n"
                "Binance 15m + 1H"
            )

            try:

                result = analyze_symbol(
                    symbol,
                    "15m"
                )

                send_message(
                    chat_id,
                    format_coin_result(result)
                )

            except Exception as e:

                print(
                    "COIN ERROR:",
                    symbol,
                    repr(e)
                )

                send_message(
                    chat_id,
                    f"❌ تعذر تحليل {symbol}.\n\n"
                    "تأكد أن الرمز موجود في Binance Futures."
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
            "WEBHOOK ERROR:",
            repr(e)
        )

        return "ERROR", 500


# =========================================================
# WEBHOOK SETUP
# =========================================================

def setup_webhook():

    time.sleep(3)

    print("SETTING WEBHOOK:")
    print(WEBHOOK_URL)

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
