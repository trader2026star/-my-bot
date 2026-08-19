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

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")


def build_trade_message(result):
    direction = result.get("direction", "WAIT")

    if direction == "LONG":
        direction_text = "🟢 LONG"
    elif direction == "SHORT":
        direction_text = "🔴 SHORT"
    else:
        direction_text = "🟡 WAIT"

    reasons = result.get("reasons", [])
    reasons_text = "\n".join(f"• {x}" for x in reasons)

    if not reasons_text:
        reasons_text = "• لا توجد أسباب كافية حالياً."

    state = result.get("state", "NORMAL")

    state_names = {
        "ACCUMULATION": "🟢 تجميع + مراقبة دخول السيولة",
        "PRE_BREAKOUT": "🔥 قبل الاختراق",
        "BREAKOUT": "🚀 اختراق",
        "DISTRIBUTION": "🔴 تصريف + خروج سيولة",
        "SELL_PRESSURE": "📉 ضغط بيعي",
        "NORMAL": "⚪ حركة عادية",
    }

    state_text = state_names.get(state, state)

    message = (
        "🤖 **Binance AI Scanner**\n\n"
        f"💎 العملة: `{result['symbol']}`\n"
        f"📈 الاتجاه: **{direction_text}**\n"
        f"⭐ Score: **{result['score']}/100**\n"
        f"🧠 الحالة: **{state_text}**\n\n"
        f"💰 السعر: `{format_number(result['price'])}`\n"
        f"📊 RSI: `{result['rsi']:.1f}`\n"
        f"📊 Volume: `{result['volume_ratio']:.2f}x`\n"
        f"💧 Buy Pressure: `{result['buy_pressure']:.1f}%`\n"
        f"📈 Trend: `{result['trend']}`\n\n"
    )

    if direction in ("LONG", "SHORT"):
        message += (
            "📍 **منطقة الدخول**\n"
            f"`{format_number(result['entry_low'])}` - "
            f"`{format_number(result['entry_high'])}`\n\n"
            "🛑 **Stop Loss**\n"
            f"`{format_number(result['stop'])}`\n\n"
            "🎯 **الأهداف**\n"
            f"TP1: `{format_number(result['tp1'])}`\n"
            f"TP2: `{format_number(result['tp2'])}`\n"
            f"TP3: `{format_number(result['tp3'])}`\n\n"
        )

    message += (
        "🛡️ **الدعم والمقاومة**\n"
        f"Support: `{format_number(result['support'])}`\n"
        f"Resistance: `{format_number(result['resistance'])}`\n\n"
        "🔍 **التحليل**\n"
        f"{reasons_text}\n\n"
    )

    if result.get("is_ready"):
        message += "✅ **الصفقة: جاهزة للمراقبة/الدخول حسب تأكيد السعر**"
    else:
        message += "🟡 **الحالة: انتظار تأكيد — لا تطارد السعر**"

    return message


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "🤖 **Binance AI Scanner**\n\n"
        "🔎 `/scan` = فحص السوق واكتشاف العملات قبل الحركة.\n\n"
        "💎 أرسل رمز العملة مثل:\n"
        "`BTC`\n"
        "`ETH`\n"
        "`SOL`\n\n"
        "وسيتم تحليل الاتجاه والسيولة والحجم والتجميع والتصريف.",
    )


@bot.message_handler(commands=["scan"])
def scan_command(message):
    status = bot.reply_to(
        message,
        "🔎 **جاري فحص Binance...**\n\n"
        "🧠 أبحث عن:\n"
        "• التجميع\n"
        "• دخول السيولة\n"
        "• زيادة الحجم\n"
        "• بداية الترند\n"
        "• العملات قبل الاختراق\n\n"
        "⏳ انتظر...",
    )

    try:
        results = scan_market()

        if not results:
            bot.edit_message_text(
                "🟡 **لم أجد صفقة تستوفي الشروط حالياً.**\n\n"
                "وده أفضل من مطاردة عملة انفجرت بالفعل.",
                message.chat.id,
                status.message_id,
                parse_mode="Markdown",
            )
            return

        top_results = results[:5]

        for result in top_results:
            bot.send_message(
                message.chat.id,
                build_trade_message(result),
                parse_mode="Markdown",
            )
            time.sleep(0.4)

        bot.edit_message_text(
            "✅ **انتهى الفحص**\n\n"
            f"وجدت **{len(results)}** فرص مطابقة للشروط.\n"
            f"تم إرسال أفضل **{len(top_results)}** فرص.",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )

    except Exception as e:
        bot.edit_message_text(
            "❌ **خطأ أثناء Scan**\n\n"
            f"`{str(e)[:700]}`",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )


@bot.message_handler(
    func=lambda message: message.text and not message.text.startswith("/")
)
def coin_handler(message):
    text = message.text.strip().upper()

    if text in ("SCAN", "تحليل", "فحص"):
        scan_command(message)
        return

    symbol = text if text.endswith("USDT") else text + "USDT"

    status = bot.reply_to(
        message,
        f"🔎 جاري تحليل `{symbol}`...",
    )

    try:
        result = analyze_symbol(symbol)

        if not result:
            bot.edit_message_text(
                f"❌ لم أستطع جلب بيانات `{symbol}` من Binance.",
                message.chat.id,
                status.message_id,
                parse_mode="Markdown",
            )
            return

        bot.edit_message_text(
            build_trade_message(result),
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )

    except Exception as e:
        bot.edit_message_text(
            "❌ **حدث خطأ أثناء التحليل**\n\n"
            f"`{str(e)[:700]}`",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )


app = Flask(__name__)


@app.route("/")
def home():
    return "Binance AI Scanner is running."


@app.route("/health")
def health():
    return "OK"


# تشغيل سيرفر الـ Flask في الخلفية لضمان بقاء الخدمة شغالة على Render
def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    print("🤖 Binance AI Scanner Started")

    # تشغيل سيرفر الـ Flask كـ Background Thread
    server_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )
    server_thread.start()

    # تشغيل البوت الأساسي
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30,
    )
