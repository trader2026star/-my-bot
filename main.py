import os
import time
import threading

import telebot
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
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing in Render Environment Variables"
    )

RENDER_URL = os.environ.get(
    "RENDER_URL",
    "https://my-bot-mtyr.onrender.com"
).rstrip("/")

WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_URL = RENDER_URL + WEBHOOK_PATH

bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)


# =========================================================
# RENDER HEALTH
# =========================================================

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Crypto Zero Reversal Bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():

    print(">>> TELEGRAM UPDATE RECEIVED")

    try:
        data = request.get_data().decode("utf-8")

        print(">>> UPDATE SIZE:", len(data))

        update = telebot.types.Update.de_json(data)

        bot.process_new_updates([update])

        print(">>> UPDATE PROCESSED")

        return "OK", 200

    except Exception as e:

        print(">>> WEBHOOK ERROR:", repr(e))

        return "ERROR", 500


# =========================================================
# START
# =========================================================

@bot.message_handler(commands=["start"])
def start_command(message):

    print(
        ">>> START FROM:",
        message.from_user.username,
        message.chat.id
    )

    bot.send_message(
        message.chat.id,
        "🚀 Crypto Zero Reversal شغال يا محمد!\n\n"
        "الأوامر:\n\n"
        "🔎 /scan\n"
        "فحص السوق.\n\n"
        "📊 /coin AVAXUSDT\n"
        "تحليل عملة وتجهيز الصفقة."
    )


# =========================================================
# SCAN
# =========================================================

@bot.message_handler(commands=["scan"])
def scan_command(message):

    print(">>> SCAN REQUEST")

    bot.send_message(
        message.chat.id,
        "🔎 جاري فحص السوق...\n"
        "أبحث عن التجميع ودخول السيولة وضعف الترند."
    )

    try:

        results = scan_market(limit=40)

        if not results:

            bot.send_message(
                message.chat.id,
                "❌ لا توجد فرصة قوية حاليًا."
            )

            return

        long_results = [
            x for x in results
            if x["signal"] in (
                "EARLY_LONG",
                "WATCH_LONG"
            )
        ]

        short_results = [
            x for x in results
            if x["signal"] in (
                "SHORT",
                "WATCH_SHORT"
            )
        ]

        text = "📡 نتائج الفحص\n\n"

        if long_results:

            text += "🟢 التجميع / Long:\n\n"

            for r in long_results[:5]:

                text += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Score: {r['long_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"الحجم: {r['volume_ratio']:.2f}x\n"
                    f"15m: {r['change_15m']:.2f}%\n"
                    f"30m: {r['change_30m']:.2f}%\n\n"
                )

        if short_results:

            text += "🔴 ضعف الترند / Short:\n\n"

            for r in short_results[:5]:

                text += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Score: {r['short_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"الحجم: {r['volume_ratio']:.2f}x\n"
                    f"15m: {r['change_15m']:.2f}%\n"
                    f"30m: {r['change_30m']:.2f}%\n\n"
                )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        print(">>> SCAN ERROR:", repr(e))

        bot.send_message(
            message.chat.id,
            "❌ حدث خطأ أثناء فحص السوق."
        )


# =========================================================
# COIN
# =========================================================

@bot.message_handler(commands=["coin"])
def coin_command(message):

    print(">>> COIN REQUEST:", message.text)

    try:

        parts = message.text.split()

        if len(parts) < 2:

            bot.send_message(
                message.chat.id,
                "اكتب:\n/coin AVAXUSDT"
            )

            return

        symbol = parts[1].upper()

        if not symbol.endswith("USDT"):
            symbol += "USDT"

        bot.send_message(
            message.chat.id,
            f"📊 جاري تحليل {symbol}..."
        )

        result = analyze_symbol(
            symbol,
            "15m"
        )

        if not result:

            bot.send_message(
                message.chat.id,
                f"❌ لم أجد بيانات {symbol}."
            )

            return

        trade = prepare_trade(result)

        text = (
            f"📊 {symbol}\n\n"
            f"السعر: {format_price(result['price'])}\n"
            f"الحالة: {result['signal']}\n\n"
            f"🟢 Long: {result['long_score']}/100\n"
            f"🔴 Short: {result['short_score']}/100\n"
            f"RSI: {result['rsi']:.1f}\n"
            f"الحجم: {result['volume_ratio']:.2f}x\n"
            f"15m: {result['change_15m']:.2f}%\n"
            f"30m: {result['change_30m']:.2f}%\n"
        )

        if trade:

            text += (
                "\n"
                f"🎯 الاتجاه: {trade['side']}\n"
                f"Entry: {trade['entry']}\n"
                f"🛑 SL: {trade['stop']}\n"
                f"🎯 TP1: {trade['tp1']}\n"
                f"🎯 TP2: {trade['tp2']}\n"
                f"🎯 TP3: {trade['tp3']}"
            )

        else:

            text += (
                "\n⏳ لا توجد صفقة جاهزة الآن."
            )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        print(">>> COIN ERROR:", repr(e))

        bot.send_message(
            message.chat.id,
            "❌ حدث خطأ أثناء تحليل العملة."
        )


# =========================================================
# SET WEBHOOK
# =========================================================

def setup_webhook():

    # ننتظر Flask حتى يبدأ
    time.sleep(3)

    while True:

        try:

            print("====================================")
            print("SETTING TELEGRAM WEBHOOK")
            print("URL:", WEBHOOK_URL)
            print("====================================")

            # حذف أي Webhook قديم
            bot.delete_webhook(
                drop_pending_updates=True
            )

            time.sleep(2)

            # إنشاء الـ Webhook الجديد
            result = bot.set_webhook(
                url=WEBHOOK_URL,
                drop_pending_updates=True
            )

            print("SET WEBHOOK RESULT:", result)

            # فحص الحالة
            info = bot.get_webhook_info()

            print("WEBHOOK URL:", info.url)
            print(
                "PENDING UPDATES:",
                info.pending_update_count
            )
            print(
                "LAST ERROR:",
                info.last_error_message
            )
            print(
                "LAST ERROR DATE:",
                info.last_error_date
            )

            if info.url == WEBHOOK_URL:

                print("====================================")
                print("TELEGRAM WEBHOOK READY")
                print("====================================")

                break

            print("Webhook URL mismatch. Retrying...")
            time.sleep(10)

        except Exception as e:

            print(
                "WEBHOOK SETUP ERROR:",
                repr(e)
            )

            time.sleep(10)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=setup_webhook,
        daemon=True
    ).start()

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
