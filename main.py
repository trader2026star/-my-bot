import os
import time
import threading

import telebot

from flask import Flask

from analysis import (
    get_price,
    analyze_symbol,
    scan_market,
    prepare_trade,
    format_number
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. Add BOT_TOKEN in Render Environment."
    )

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

app = Flask(__name__)


# =========================================================
# RENDER KEEP ALIVE
# =========================================================

@app.route("/")
def home():
    return "Binance AI Scanner Bot is running."


@app.route("/health")
def health():
    return "OK"


def run_web():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )


# =========================================================
# START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    text = """
<b>🤖 BINANCE SMART SCANNER</b>

البوت جاهز للعمل ✅

<b>الأوامر:</b>

/scan
🔎 مسح السوق بالكامل

/scan_long
🟢 البحث عن فرص LONG مبكرة

/scan_short
🔴 البحث عن فرص SHORT مبكرة

/analyze BTCUSDT
📊 تحليل أي عملة

/trade BTCUSDT
🎯 تجهيز الصفقة

/price BTCUSDT
💰 السعر الحالي

/help
📚 المساعدة

<b>النظام يراقب:</b>

💧 السيولة
📊 Volume
📈 Trend
📦 Accumulation
🚀 Pre-Pump
🔻 Distribution
📉 بداية الهبوط
⚡ Breakout
"""

    bot.reply_to(
        message,
        text
    )


# =========================================================
# HELP
# =========================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    bot.reply_to(
        message,
        """
<b>📚 طريقة الاستخدام</b>

مثال:

<code>/scan</code>

أو:

<code>/scan_long</code>

أو:

<code>/scan_short</code>

لتحليل عملة:

<code>/analyze AVAXUSDT</code>

لتجهيز الصفقة:

<code>/trade AVAXUSDT</code>

للسعر:

<code>/price AVAXUSDT</code>
"""
    )


# =========================================================
# PRICE
# =========================================================

@bot.message_handler(
    commands=["price"]
)
def price_command(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "اكتب:\n<code>/price BTCUSDT</code>"
        )

        return

    symbol = parts[1].upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    price = get_price(symbol)

    if price is None:

        bot.reply_to(
            message,
            f"❌ لم أجد <b>{symbol}</b>"
        )

        return

    bot.reply_to(
        message,
        f"""
💰 <b>{symbol}</b>

السعر:

<code>{format_number(price)}</code>
"""
    )


# =========================================================
# ANALYZE
# =========================================================

@bot.message_handler(
    commands=["analyze"]
)
def analyze_command(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "اكتب:\n<code>/analyze AVAXUSDT</code>"
        )

        return

    symbol = parts[1].upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    bot.send_chat_action(
        message.chat.id,
        "typing"
    )

    result = analyze_symbol(symbol)

    if not result:

        bot.reply_to(
            message,
            "❌ لم أستطع تحليل العملة."
        )

        return

    long_data = result["long"]
    short_data = result["short"]
    accumulation = result["accumulation"]

    accumulation_signals = "\n".join(
        "• " + x
        for x in accumulation["signals"]
    )

    text = f"""
<b>📊 تحليل {symbol}</b>

💰 السعر:
<code>{format_number(result["price"])}</code>

━━━━━━━━━━━━━━

🟢 LONG SCORE:
<b>{long_data["score"]}/100</b>

🔴 SHORT SCORE:
<b>{short_data["score"]}/100</b>

📦 ACCUMULATION:
<b>{accumulation["score"]}/100</b>

📈 1H TREND:
<b>{result["trend_1h"]}</b>

RSI:
<code>{long_data["rsi"]:.2f}</code>

━━━━━━━━━━━━━━

<b>📦 إشارات التجميع:</b>

{accumulation_signals or "لا توجد إشارات قوية"}

━━━━━━━━━━━━━━

🟢 LONG:

{" • ".join(long_data["signals"])}

🔴 SHORT:

{" • ".join(short_data["signals"])}

━━━━━━━━━━━━━━

<b>الحالة:</b>
{result["status"]}
"""

    bot.reply_to(
        message,
        text
    )


# =========================================================
# TRADE
# =========================================================

@bot.message_handler(
    commands=["trade"]
)
def trade_command(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "اكتب:\n<code>/trade AVAXUSDT</code>"
        )

        return

    symbol = parts[1].upper()

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    bot.send_chat_action(
        message.chat.id,
        "typing"
    )

    trade = prepare_trade(symbol)

    if not trade:

        bot.reply_to(
            message,
            "❌ لم أستطع تجهيز التحليل."
        )

        return

    direction = trade["direction"]

    # =====================================================
    # WAIT
    # =====================================================

    if direction == "WAIT":

        bot.reply_to(
            message,
            f"""
⚪ <b>NO TRADE</b>

<b>{symbol}</b>

السعر:
<code>{format_number(trade["entry"])}</code>

Score:
<b>{trade["score"]}/100</b>

لا توجد شروط كافية للدخول.

<b>القرار:</b>
انتظار.
"""
        )

        return

    # =====================================================
    # PRE PUMP
    # =====================================================

    if direction == "WATCH":

        signals = "\n".join(
            "• " + x
            for x in trade["signals"]
        )

        bot.reply_to(
            message,
            f"""
🟢 <b>PRE-PUMP WATCH</b>

<b>{symbol}</b>

السعر:
<code>{format_number(trade["entry"])}</code>

📊 قوة التجميع:
<b>{trade["score"]}/100</b>

💧 الحالة:
<b>تجميع قبل الحركة</b>

📈 1H:
<b>{trade["trend_1h"]}</b>

RSI:
<code>{trade["rsi"]:.2f}</code>

━━━━━━━━━━━━━━

<b>الإشارات:</b>

{signals}

━━━━━━━━━━━━━━

⚠️ <b>ليست صفقة دخول بعد.</b>

انتظر اختراق المقاومة مع زيادة الحجم.
"""
        )

        return

    # =====================================================
    # REAL SETUP
    # =====================================================

    emoji = (
        "🟢"
        if direction == "LONG"
        else "🔴"
    )

    signals = "\n".join(
        "• " + x
        for x in trade["signals"]
    )

    text = f"""
{emoji} <b>{direction} SETUP</b>

<b>{symbol}</b>

━━━━━━━━━━━━━━

📊 Score:
<b>{trade["score"]}/100</b>

📈 1H Trend:
<b>{trade["trend_1h"]}</b>

📦 Accumulation:
<b>{trade["accumulation"]}/100</b>

RSI:
<code>{trade["rsi"]:.2f}</code>

━━━━━━━━━━━━━━

🎯 <b>ENTRY</b>

<code>{format_number(trade["entry"])}</code>

🛑 <b>STOP LOSS</b>

<code>{format_number(trade["stop"])}</code>

🎯 <b>TP1</b>

<code>{format_number(trade["tp1"])}</code>

🎯 <b>TP2</b>

<code>{format_number(trade["tp2"])}</code>

🎯 <b>TP3</b>

<code>{format_number(trade["tp3"])}</code>

━━━━━━━━━━━━━━

📍 Support:

<code>{format_number(trade["support"])}</code>

📍 Resistance:

<code>{format_number(trade["resistance"])}</code>

━━━━━━━━━━━━━━

<b>التأكيدات:</b>

{signals}

━━━━━━━━━━━━━━

⚠️ الصفقة تحليل آلي وليست ضمانًا للربح.
"""


    bot.reply_to(
        message,
        text
    )


# =========================================================
# SCAN FORMAT
# =========================================================

def format_scan_result(results, mode):

    if not results:

        return """
❌ لم يتم العثور على فرص قوية حاليًا.

الأفضل الانتظار بدل إجبار البوت على صفقة.
"""

    if mode == "long":
        title = "🟢 LONG SCANNER"

    elif mode == "short":
        title = "🔴 SHORT SCANNER"

    else:
        title = "🔎 MARKET SCANNER"

    text = f"""
<b>{title}</b>

تم فحص السوق وترتيب أفضل الفرص:

━━━━━━━━━━━━━━
"""

    for i, result in enumerate(
        results[:10],
        1
    ):

        symbol = result["symbol"]

        price = result["price"]

        long_score = result[
            "long"
        ]["score"]

        short_score = result[
            "short"
        ]["score"]

        accumulation = result[
            "accumulation"
        ]["score"]

        trend = result[
            "trend_1h"
        ]

        if accumulation >= 65:
            state = "🟢 PRE-PUMP"

        elif long_score >= 70:
            state = "🟢 LONG"

        elif short_score >= 70:
            state = "🔴 SHORT"

        else:
            state = "🟡 WATCH"

        text += f"""
<b>{i}. {symbol}</b>

{state}

💰 {format_number(price)}

🟢 L: {long_score}
🔴 S: {short_score}
📦 A: {accumulation}
📈 1H: {trend}

"""

    text += """
━━━━━━━━━━━━━━

💡 استخدم:

<code>/trade SYMBOL</code>

لتجهيز الصفقة بالتفصيل.
"""

    return text


# =========================================================
# SCAN
# =========================================================

@bot.message_handler(
    commands=["scan"]
)
def scan_command(message):

    bot.reply_to(
        message,
        """
🔎 <b>بدأ فحص السوق...</b>

سأبحث عن:

💧 السيولة
📊 الحجم
📦 التجميع
🚀 Pre-Pump
📈 الترند
🔻 بداية الهبوط

قد يستغرق الفحص بعض الوقت.
"""
    )

    try:

        results = scan_market(
            mode="all",
            max_symbols=80
        )

        text = format_scan_result(
            results,
            "all"
        )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        bot.send_message(
            message.chat.id,
            f"❌ Scan Error:\n<code>{str(e)}</code>"
        )


# =========================================================
# SCAN LONG
# =========================================================

@bot.message_handler(
    commands=["scan_long"]
)
def scan_long_command(message):

    bot.reply_to(
        message,
        "🟢 بدأ البحث عن فرص LONG مبكرة..."
    )

    try:

        results = scan_market(
            mode="long",
            max_symbols=80
        )

        text = format_scan_result(
            results,
            "long"
        )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        bot.send_message(
            message.chat.id,
            f"❌ Error:\n<code>{str(e)}</code>"
        )


# =========================================================
# SCAN SHORT
# =========================================================

@bot.message_handler(
    commands=["scan_short"]
)
def scan_short_command(message):

    bot.reply_to(
        message,
        "🔴 بدأ البحث عن فرص SHORT / بداية هبوط..."
    )

    try:

        results = scan_market(
            mode="short",
            max_symbols=80
        )

        text = format_scan_result(
            results,
            "short"
        )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        bot.send_message(
            message.chat.id,
            f"❌ Error:\n<code>{str(e)}</code>"
        )


# =========================================================
# BOT LOOP
# =========================================================

def run_bot():

    while True:

        try:

            print(
                "Telegram bot started..."
            )

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )

        except Exception as e:

            print(
                "Telegram polling error:",
                e
            )

            time.sleep(10)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    run_bot()
