
import os
import time

import telebot

from analysis import (
    analyze_symbol,
    scan_market,
    format_number,
    get_current_price,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN أو API_TOKEN غير موجود في Environment Variables"
    )

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# TRADE MESSAGE
# ============================================================

def build_trade_message(result):

    if result["direction"] == "LONG":
        direction = "🟢 LONG"
    else:
        direction = "🔴 SHORT"

    reasons = "\n".join(
        f"• {reason}"
        for reason in result["reasons"]
    )

    return (
        "🚨 **فرصة تداول**\n\n"

        f"💎 العملة: `{result['symbol']}`\n"
        f"📈 الاتجاه: **{direction}**\n"
        f"⭐ قوة الإشارة: **{result['score']}/100**\n\n"

        f"💰 السعر: `{format_number(result['price'])}`\n\n"

        "📍 **منطقة الدخول:**\n"
        f"`{format_number(result['entry_low'])}`"
        " — "
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

        "⚠️ لا توجد صفقة مضمونة. "
        "استخدم إدارة رأس المال."
    )


# ============================================================
# /START
# ============================================================

@bot.message_handler(commands=["start", "help"])
def start_command(message):

    bot.reply_to(
        message,
        "🤖 **Binance AI Scanner**\n\n"
        "🔎 `/scan`\n"
        "فحص السوق والبحث عن أقوى الفرص.\n\n"
        "📊 `/analyze BTCUSDT`\n"
        "تحليل زوج معين.\n\n"
        "💰 أو اكتب اسم العملة مباشرة:\n"
        "`BTC`\n"
        "`ETH`\n"
        "`SOL`\n\n"
        "إذا لم تكتمل الشروط، لن يرسل البوت صفقة.",
        parse_mode="Markdown",
    )


# ============================================================
# /ANALYZE
# ============================================================

@bot.message_handler(commands=["analyze"])
def analyze_command(message):

    parts = message.text.split()

    if len(parts) < 2:

        bot.reply_to(
            message,
            "اكتب الزوج بعد الأمر، مثال:\n\n"
            "`/analyze BTCUSDT`\n\n"
            "أو:\n"
            "`/analyze KAITO`",
            parse_mode="Markdown",
        )

        return

    symbol = parts[1].strip().upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    status = bot.reply_to(
        message,
        f"🔎 جاري تحليل `{symbol}`...\n\n"
        "انتظر قليلًا.",
        parse_mode="Markdown",
    )

    try:

        result = analyze_symbol(symbol)

        if not result:

            try:
                price = get_current_price(symbol)
                price_text = format_number(float(price))
            except Exception:
                price_text = "غير متاح"

            bot.edit_message_text(
                f"📊 `{symbol}`\n\n"
                f"💰 السعر الحالي: `{price_text}`\n\n"
                "🟡 **لا توجد صفقة جاهزة حاليًا.**\n\n"
                "شروط الدخول القوية لم تكتمل.",
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
            "❌ تعذر تحليل الزوج.\n\n"
            f"`{str(e)[:500]}`",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )


# ============================================================
# /SCAN
# ============================================================

@bot.message_handler(commands=["scan"])
def scan_command(message):

    status = bot.reply_to(
        message,
        "🔎 **بدأ فحص سوق Binance...**\n\n"
        "سيبحث عن أقوى الفرص فقط.\n\n"
        "⏳ لا ترسل أمرًا آخر حتى ينتهي الفحص.",
        parse_mode="Markdown",
    )

    try:

        results = scan_market()

        if not results:

            bot.edit_message_text(
                "🟡 **لا توجد صفقة جاهزة حاليًا.**\n\n"
                "تم فحص السوق ولم تصل أي عملة "
                "للحد المطلوب من التأكيدات.\n\n"
                "عدم الدخول أفضل من صفقة ضعيفة.",
                message.chat.id,
                status.message_id,
                parse_mode="Markdown",
            )

            return

        top_results = results[:3]

        bot.edit_message_text(
            f"✅ انتهى الفحص.\n\n"
            f"تم العثور على **{len(results)}** "
            "إشارة مطابقة للشروط.\n\n"
            f"سيتم إرسال أفضل **{len(top_results)}** فرص.",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )

        time.sleep(0.5)

        for result in top_results:

            bot.send_message(
                message.chat.id,
                build_trade_message(result),
                parse_mode="Markdown",
            )

            time.sleep(0.7)

    except Exception as e:

        bot.edit_message_text(
            "❌ حدث خطأ أثناء فحص السوق:\n\n"
            f"`{str(e)[:500]}`",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )


# ============================================================
# COIN NAME
# ============================================================

@bot.message_handler(
    func=lambda message:
    message.text
    and not message.text.startswith("/")
)
def coin_handler(message):

    text = message.text.strip().upper()

    if not text:
        return

    if " " in text:
        return

    symbol = text

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    status = bot.reply_to(
        message,
        f"🔎 جاري تحليل `{symbol}`...",
        parse_mode="Markdown",
    )

    try:

        result = analyze_symbol(symbol)

        if not result:

            try:
                price = get_current_price(symbol)
                price_text = format_number(float(price))
            except Exception:
                price_text = "غير متاح"

            bot.edit_message_text(
                f"📊 `{symbol}`\n\n"
                f"💰 السعر الحالي: `{price_text}`\n\n"
                "🟡 **لا توجد صفقة جاهزة حاليًا.**\n\n"
                "شروط التحليل لم تكتمل.",
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
            "❌ تعذر تحليل العملة.\n\n"
            f"`{str(e)[:500]}`",
            message.chat.id,
            status.message_id,
            parse_mode="Markdown",
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    print("🤖 Binance AI Scanner Started")

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30,
    )
