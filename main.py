import os
import time
import requests

from flask import Flask, request


# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing"
    )

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
# HOME
# =========================================================

@app.route("/", methods=["GET", "HEAD"])
def home():

    return (
        "Crypto Zero Reversal Bot is running.",
        200
    )


@app.route("/health", methods=["GET"])
def health():

    return "OK", 200


# =========================================================
# TELEGRAM WEBHOOK
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

            print(
                ">>> EMPTY UPDATE"
            )

            return "OK", 200

        message = update.get(
            "message"
        )

        if not message:

            print(
                ">>> NO MESSAGE"
            )

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
                "اتصال Telegram + Render ناجح ✅\n\n"
                "الأوامر:\n\n"
                "/scan\n"
                "🔎 فحص السوق\n\n"
                "/coin AVAXUSDT\n"
                "📊 تحليل عملة"
            )

            print(
                ">>> START RESPONSE SENT"
            )

            return "OK", 200


        # =================================================
        # SCAN
        # =================================================

        if text.startswith("/scan"):

            send_message(
                chat_id,

                "🔎 استلمت أمر SCAN.\n\n"
                "سيتم تشغيل Scanner السوق في النسخة التحليلية."
            )

            print(
                ">>> SCAN RESPONSE SENT"
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

                f"📊 استلمت طلب تحليل {symbol}\n\n"
                "جاري تجهيز وحدة التحليل."
            )

            print(
                ">>> COIN RESPONSE SENT:",
                symbol
            )

            return "OK", 200


        # =================================================
        # UNKNOWN MESSAGE
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
# SET WEBHOOK
# =========================================================

def setup_webhook():

    time.sleep(3)

    print("")
    print("==============================")
    print("SETTING TELEGRAM WEBHOOK")
    print(
        "WEBHOOK:",
        WEBHOOK_URL
    )
    print("==============================")


    # حذف القديم

    telegram_request(
        "deleteWebhook",
        {
            "drop_pending_updates": True
        }
    )

    time.sleep(2)


    # وضع الجديد

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


    # فحص الحالة

    info = telegram_request(
        "getWebhookInfo"
    )

    print(
        "WEBHOOK INFO:",
        info
    )

    print("")
    print("==============================")
    print("TELEGRAM WEBHOOK READY")
    print("==============================")


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
