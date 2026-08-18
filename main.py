import os
import time
import threading
from flask import Flask
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
        "🟢 LONG (صاعد)"
        if result["direction"] == "LONG"
        else "🔴 SHORT (هابط)"
    )

    reasons = "\n".join(
        f"• {reason}"
        for reason in result["reasons"]
    ) if result["reasons"] else "• لا توجد مؤشرات قوية كافية حالياً."

    # لو الفرصة جاهزة تماماً وتعطى إشارة دخول
    if result.get("is_ready", True):
        return (
            "📊 **تحليل فني متقدم (إشارة مؤكدة)**\n\n"
            f"💎 العملة: `{result['symbol']}`\n"
            f"📈 الاتجاه: **{direction}**\n"
            f"⭐ Score: **{result['score']}/100**\n\n"

            f"💰 السعر الحالي: `{format_number(result['price'])}`\n"
            f"📊 RSI: `{result['rsi']:.1f}` | Vol: `{result['volume_ratio']:.2f}x`\n\n"

            "📍 **منطقة الدخول:**\n"
            f"`{format_number(result['entry_low'])}` - `{format_number(result['entry_high'])}`\n\n"

            "🛑 **وقف الخسارة:**\n"
            f"`{format_number(result['stop'])}`\n\n"

            "🎯 **الأهداف:**\n"
            f"TP1: `{format_number(result['tp1'])}`\n"
            f"TP2: `{format_number(result['tp2'])}`\n"
            f"TP3: `{format_number(result['tp3'])}`\n\n"

            f"🛡️ **الدعم والمقاومة:**\n"
            f"S: `{format_number(result['support'])}` | R: `{format_number(result['resistance'])}`\n\n"

            "🔍 **الإيجابيات:**\n"
            f"{reasons}\n\n"
            "✅ **حالة الصفقة:** دخول مؤكد 🟢"
        )
    else:
        # لو الشروط لم تكتمل بالكامل ويحتاج انتظار
        return (
            "📊 **تحليل فني (حالة انتظار)**\n\n"
            f"💎 العملة: `{result['symbol']}`\n"
            f"📈 الاتجاه العام: **{direction}**\n"
            f"⭐ Score: **{result['score']}/100**\n\n"

            f"💰 السعر الحالي: `{format_number(result['price'])}`\n"
            f"📊 RSI: `{result['rsi']:.1f}` | Vol: `{result['volume_ratio']:.2f}x`\n\n"

            f"🛡️ **الدعم والمقاومة:**\n"
            f"الدعم: `{format_number(result['support'])}` | المقاومة: `{format_number(result['resistance'])}`\n\n"

            "🟡 **انتظار - لا توجد إشارة دخول قوية مؤكدة**\n"
            f"المؤشرات الحالية:\n{reasons}\n\n"
            f"💡 **نصيحة:** استنى تأكيد الاختراق فوق المقاومة أو الارتداد من الدعم."
        )


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "🤖 **Binance AI Scanner**\n\n"
        "🔎 أرسل `/scan` أو `SCAN` لفحص السوق بالكامل.\n\n"
        "💰 أو أرسل رمز أي عملة (مثل `BTC`, `ETH`, `OGN`) "
        "ليتم تحليلها فوراً وإعطاؤك تقريراً فنياً كاملاً.",
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

    if text == "SCAN" or text == "تحليل":
        scan_command(message)
        return

    symbol = text if text.endswith("USDT") else text + "USDT"

    status = bot.reply_to(
        message,
        f"🔎 جاري تحليل `{symbol}` وإعداد التقرير الفني...",
        parse_mode="Markdown"
    )

    try:
        result = analyze_symbol(symbol)

        if not result:
            bot.edit_message_text(
                f"📊 `{symbol}`\n\n"
                "🟡 **عذراً، تعذر جلب بيانات هذه العملة حالياً من منصة Binance.**",
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


# إنشاء تطبيق ويب مصغر لتشغيل سيرفر الويب بجانب البوت لتوافق تام مع Render
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    print("🤖 Binance AI Scanner Started with Web Server...")

    # تشغيل سيرفر الويب في مسار خلفي (Background Thread)
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    # تشغيل البوت
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


