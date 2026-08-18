import os
import time
import telebot

from analysis import analyze_symbol, scan_market, format_number


BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN أو API_TOKEN غير موجود في Environment Variables"
    )

bot = telebot.TeleBot(BOT_TOKEN)


def build_trade_message(result):
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
        f"⭐ Score: **{result['score']}/100**\n\n"

        f"💰 السعر الحالي:\n"
        f"`{format_number(result['price'])}`\n\n"

        "📍 **منطقة الدخول:**\n"
        f"`{format_number(result['entry_low'])}` - "
        f"`{format_number(result['entry_high'])}`\n\n"

        "🛑 **وقف الخسارة:**\n"
        f"`{format_number(result['stop'])}`\n\n"

        "🎯 **الأهداف:**\n"
        f"TP1: `{format_number(result['tp1'])}`\n"
        f"TP2: `{format_number(result['tp2'])}`\n"
        f"TP3: `{format_number(result['tp3'])}`\n\n"

        f"📊 RSI: `{result['rsi']:.1f}`\n"
        f"📊 Volume: `{result['volume_ratio']:.2f}x`\n\n"

        "🔍 **التأكيدات:**\n"
        f"{reasons}\n\n"

        "⚠️ لا توجد صفقة مضمونة. استخدم إدارة رأس المال."
    )


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "🤖 **Binance AI Scanner**\n\n"
        "🔎 أرسل `/scan` لفحص السوق.\n\n"
        "💰 أو أرسل رمز عملة مثل:\n"
        "`BTC`\n"
        "`ETH`\n"
        "`SOL`\n\n"
        "سيتم تحليل العملة وإظهار LONG أو SHORT "
        "فقط إذا تحققت الشروط.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["scan"])
def scan_command(message):
    status = bot.reply_to(
        message,
        "🔎 **جاري فحص سوق Binance...**\n\n"
        "⏳ انتظر حتى ينتهي الفحص.",
        parse_mode="Markdown"
    )

    try:
        results = scan_market()

        if not results:
            bot.edit_message_text(
                "🟡 **لا توجد صفقة جاهزة حالياً.**\n\n"
                "تم فحص السوق ولم توجد عملة تحقق شروط الدخول القوية.",
                message.chat.id,
                status.message_id,
                parse_mode="Markdown"
            )
            return

        top_results = results[:3]

        for result in top_results:
            bot.send_message(
                message.chat.id,
                build_trade_message(result),
                parse_mode="Markdown"
            )
            time.sleep(0.5)

        bot.edit_message_text(
            f"✅ انتهى الفحص.\n\n"
            f"تم العثور على **{len(results)}** إشارات.\n"
            f"تم إرسال أفضل **{len(top_results)}** فرص.",
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


@bot.message_handler(
    func=lambda message: message.text and not message.text.startswith("/")
)
def coin_handler(message):
    text = message.text.strip().upper()

    if text == "SCAN":
        scan_command(message)
        return

    symbol = text if text.endswith("USDT") else text + "USDT"

    status = bot.reply_to(
        message,
        f"🔎 جاري تحليل `{symbol}`...",
        parse_mode="Markdown"
    )

    try:
        result = analyze_symbol(symbol)

        if not result:
            bot.edit_message_text(
                f"📊 `{symbol}`\n\n"
                "🟡 **لا توجد صفقة جاهزة حالياً.**\n\n"
                "شروط التحليل القوية لم تكتمل.",
                message.chat.id,
                status.message_id,
                parse_mode="Markdown"
            )
            return

        bot.edit_message_text(
            build_trade_message(result),
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


import threading
from flask import Flask

# إنشاء تطبيق ويب بسيط عشان UptimeRobot يفضله صاحي وما يقفلش
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running 24/7!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    print("🤖 Binance AI Scanner Started with Web Server...")

    # تشغيل سيرفر الويب في مسار منفصل (Background Thread)
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    # تشغيل البوت بشكل طبيعي
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )

