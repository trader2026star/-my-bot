import os
import time
import threading

import telebot

from flask import Flask

from analysis import (
    scan_market,
    analyze_symbol,
    prepare_trade,
    format_price
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
)

if not TOKEN:
    raise RuntimeError(
        "BOT TOKEN NOT FOUND. Add TELEGRAM_BOT_TOKEN or BOT_TOKEN in Render Environment."
    )


bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)


# =========================================================
# RENDER WEB SERVER
# =========================================================

@app.route("/")
def home():
    return "Trading Bot is running.", 200


@app.route("/health")
def health():
    return "OK", 200


# =========================================================
# TELEGRAM
# =========================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):

    text = (
        "🚀 البوت شغال يا محمد\n\n"
        "الأوامر:\n\n"
        "🔎 /scan\n"
        "فحص السوق والبحث عن فرص مبكرة.\n\n"
        "📊 /coin BTCUSDT\n"
        "تحليل عملة وتجهيز الصفقة.\n\n"
        "مثال:\n"
        "/coin AVAXUSDT"
    )

    bot.reply_to(message, text)


@bot.message_handler(commands=["scan"])
def scan_command(message):

    bot.reply_to(
        message,
        "🔎 جاري فحص السوق...\n"
        "أبحث عن التجميع المبكر + دخول السيولة + ضعف الترند."
    )

    try:

        results = scan_market(limit=40)

        if not results:

            bot.send_message(
                message.chat.id,
                "❌ لم أجد حاليًا فرصة قوية بالشروط المطلوبة.\n\n"
                "وده أفضل من إعطاء صفقة ضعيفة."
            )

            return

        early = [
            x for x in results
            if x["signal"] in ("EARLY_LONG", "WATCH_LONG")
        ]

        shorts = [
            x for x in results
            if x["signal"] in ("SHORT", "WATCH_SHORT")
        ]

        output = "📡 نتائج فحص السوق\n\n"

        if early:

            output += "🟢 عملات تحت المراقبة للونج:\n\n"

            for r in early[:5]:

                output += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Long Score: {r['long_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"الحجم: {r['volume_ratio']:.2f}x\n"
                    f"تغير 15m: {r['change_15m']:.2f}%\n"
                    f"تغير 30m: {r['change_30m']:.2f}%\n\n"
                )

        if shorts:

            output += "🔴 عملات تحت المراقبة للشورت:\n\n"

            for r in shorts[:5]:

                output += (
                    f"• {r['symbol']}\n"
                    f"السعر: {format_price(r['price'])}\n"
                    f"Short Score: {r['short_score']}/100\n"
                    f"RSI: {r['rsi']:.1f}\n"
                    f"الحجم: {r['volume_ratio']:.2f}x\n"
                    f"تغير 15m: {r['change_15m']:.2f}%\n"
                    f"تغير 30m: {r['change_30m']:.2f}%\n\n"
                )

        output += (
            "⚠️ النتائج مراقبة وليست ضمانًا للاتجاه.\n"
            "لا يتم اعتبار الصفقة جاهزة لمجرد وجود ارتفاع/هبوط."
        )

        bot.send_message(
            message.chat.id,
            output
        )

    except Exception as e:

        print("SCAN ERROR:", e)

        bot.send_message(
            message.chat.id,
            "❌ حصل خطأ أثناء فحص السوق.\n"
            "راجع Logs في Render."
        )


@bot.message_handler(commands=["coin"])
def coin_command(message):

    try:

        parts = message.text.split()

        if len(parts) < 2:

            bot.reply_to(
                message,
                "اكتب العملة هكذا:\n/coin AVAXUSDT"
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
            f"الاتجاه: {result['signal']}\n"
            f"RSI: {result['rsi']:.1f}\n"
            f"الحجم: {result['volume_ratio']:.2f}x\n"
            f"15m: {result['change_15m']:.2f}%\n"
            f"30m: {result['change_30m']:.2f}%\n\n"
            f"🟢 Long Score: {result['long_score']}/100\n"
            f"🔴 Short Score: {result['short_score']}/100\n"
        )

        if trade:

            text += (
                "\n\n"
                f"🎯 الصفقة المقترحة: {trade['side']}\n"
                f"Entry: {trade['entry']}\n"
                f"SL: {trade['stop']}\n"
                f"TP1: {trade['tp1']}\n"
                f"TP2: {trade['tp2']}\n"
                f"TP3: {trade['tp3']}\n"
            )

        else:

            text += (
                "\n\n"
                "⏳ لا توجد صفقة مؤكدة حاليًا.\n"
                "الأفضل الانتظار بدل الدخول العشوائي."
            )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        print("COIN ERROR:", e)

        bot.send_message(
            message.chat.id,
            "❌ حصل خطأ أثناء تحليل العملة."
        )


# =========================================================
# TELEGRAM POLLING
# =========================================================

def telegram_worker():

    while True:

        try:

            print("Removing Telegram webhook...")

            bot.delete_webhook(
                drop_pending_updates=True
            )

            print("Starting Telegram polling...")

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )

        except Exception as e:

            print("TELEGRAM ERROR:", repr(e))

            time.sleep(10)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=telegram_worker,
        daemon=True
    ).start()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    print(
        f"Starting Flask server on port {port}"
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
