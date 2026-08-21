import os
import threading
import time

import telebot
from flask import Flask, request

from analysis import (
    scan_market,
    analyze_symbol,
    prepare_trade,
    format_price
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing in Render Environment Variables."
    )

# رابط Render الحالي
RENDER_URL = os.environ.get(
    "RENDER_URL",
    "https://my-bot-mtyr.onrender.com"
).rstrip("/")

WEBHOOK_PATH = f"/telegram/{TOKEN}"
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)


# =========================================================
# HEALTH CHECK
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

    try:
        json_string = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(
            json_string
        )

        bot.process_new_updates([update])

        return "OK", 200

    except Exception as e:

        print("WEBHOOK ERROR:", repr(e))

        return "ERROR", 500


# =========================================================
# START
# =========================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):

    bot.reply_to(
        message,
        "🚀 Crypto Zero Reversal شغال يا محمد!\n\n"
        "🔎 /scan\n"
        "لفحص السوق والبحث عن فرص مبكرة.\n\n"
        "📊 /coin AVAXUSDT\n"
        "لتحليل عملة وتجهيز الصفقة."
    )


# =========================================================
# SCAN
# =========================================================

@bot.message_handler(commands=["scan"])
def scan_command(message):

    bot.reply_to(
        message,
        "🔎 جاري فحص السوق...\n\n"
        "أبحث عن:\n"
        "🟢 تجميع + دخول سيولة + بداية حركة\n"
        "🔴 ترند متأخر + ضعف + خروج سيولة"
    )

    try:

        results = scan_market(limit=40)

        if not results:

            bot.send_message(
                message.chat.id,
                "❌ لم أجد حاليًا فرصة قوية بالشروط المطلوبة.\n\n"
                "أفضل الانتظار بدل إعطاء صفقة ضعيفة."
            )

            return

        early = [
            x for x in results
            if x["signal"] in (
                "EARLY_LONG",
                "WATCH_LONG"
            )
        ]

        shorts = [
            x for x in results
            if x["signal"] in (
                "SHORT",
                "WATCH_SHORT"
            )
        ]

        output = "📡 Crypto Zero Reversal\n"
        output += "نتائج فحص السوق\n\n"

        # -------------------------------------------------
        # LONG
        # -------------------------------------------------

        if early:

            output += "🟢 فرص التجميع / Long:\n\n"

            for r in early[:5]:

                output += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Score: {r['long_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"السيولة/الحجم: "
                    f"{r['volume_ratio']:.2f}x\n"
                    f"15m: {r['change_15m']:.2f}%\n"
                    f"30m: {r['change_30m']:.2f}%\n\n"
                )

        # -------------------------------------------------
        # SHORT
        # -------------------------------------------------

        if shorts:

            output += "🔴 ضعف الترند / Short:\n\n"

            for r in shorts[:5]:

                output += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Score: {r['short_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"السيولة/الحجم: "
                    f"{r['volume_ratio']:.2f}x\n"
                    f"15m: {r['change_15m']:.2f}%\n"
                    f"30m: {r['change_30m']:.2f}%\n\n"
                )

        output += (
            "⚠️ الإشارة ليست ضمانًا للحركة.\n"
            "الدخول يحتاج تأكيد السعر والسيولة."
        )

        bot.send_message(
            message.chat.id,
            output
        )

    except Exception as e:

        print("SCAN ERROR:", repr(e))

        bot.send_message(
            message.chat.id,
            "❌ حدث خطأ أثناء فحص السوق."
        )


# =========================================================
# COIN ANALYSIS
# =========================================================

@bot.message_handler(commands=["coin"])
def coin_command(message):

    try:

        parts = message.text.split()

        if len(parts) < 2:

            bot.reply_to(
                message,
                "اكتب العملة بهذا الشكل:\n\n"
                "/coin AVAXUSDT"
            )

            return

        symbol = parts[1].upper()

        if not symbol.endswith("USDT"):
            symbol += "USDT"

        bot.reply_to(
            message,
            f"📊 جاري تحليل {symbol}..."
        )

        result = analyze_symbol(
            symbol,
            "15m"
        )

        if not result:

            bot.send_message(
                message.chat.id,
                f"❌ لم أستطع الحصول على بيانات {symbol}."
            )

            return

        trade = prepare_trade(result)

        text = (
            f"📊 تحليل {symbol}\n\n"
            f"السعر: {format_price(result['price'])}\n"
            f"الحالة: {result['signal']}\n\n"
            f"🟢 Long Score: "
            f"{result['long_score']}/100\n"
            f"🔴 Short Score: "
            f"{result['short_score']}/100\n"
            f"RSI: {result['rsi']:.1f}\n"
            f"الحجم: {result['volume_ratio']:.2f}x\n"
            f"15m: {result['change_15m']:.2f}%\n"
            f"30m: {result['change_30m']:.2f}%\n"
        )

        if trade:

            text += (
                "\n\n"
                f"🎯 الاتجاه: {trade['side']}\n"
                f"Entry: {trade['entry']}\n"
                f"🛑 SL: {trade['stop']}\n"
                f"🎯 TP1: {trade['tp1']}\n"
                f"🎯 TP2: {trade['tp2']}\n"
                f"🎯 TP3: {trade['tp3']}\n"
            )

        else:

            text += (
                "\n\n"
                "⏳ لا توجد صفقة جاهزة الآن.\n"
                "الأفضل انتظار تأكيد أقوى."
            )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        print("COIN ERROR:", repr(e))

        bot.send_message(
            message.chat.id,
            "❌ حدث خطأ أثناء تحليل العملة."
        )


# =========================================================
# SET WEBHOOK
# =========================================================

def setup_webhook():

    while True:

        try:

            print("Setting Telegram webhook...")
            print("Webhook URL:", WEBHOOK_URL)

            # حذف أي webhook قديم أولًا
            bot.delete_webhook(
                drop_pending_updates=True
            )

            time.sleep(2)

            # وضع webhook الجديد
            result = bot.set_webhook(
                url=WEBHOOK_URL,
                drop_pending_updates=True
            )

            print(
                "Webhook set result:",
                result
            )

            info = bot.get_webhook_info()

            print(
                "Webhook active:",
                info.url
            )

            print(
                "Pending updates:",
                info.pending_update_count
            )

            print("Telegram webhook is READY.")

            break

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

    # إعداد webhook في Thread حتى لا يمنع Flask
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
