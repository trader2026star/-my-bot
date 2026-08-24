import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

from analysis import (
    scan_market,
    get_coin_analysis,
    generate_evidence_report,
    normalize_symbol
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


# =========================================================
# TOKEN
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 أهلاً بك في Binance AI Scanner\n\n"
        "📌 أرسل اسم العملة:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n\n"
        "📌 أو استخدم:\n"
        "/scan\n\n"
        "🔎 البوت يحلل:\n"
        "• الاتجاه\n"
        "• RSI\n"
        "• Volume\n"
        "• السيولة\n"
        "• الدعم والمقاومة\n"
        "• 15M / 1H / 4H / 1D\n"
        "• Entry / SL / TP"
    )


# =========================================================
# SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔍 جاري فحص Binance Futures...\n"
        "⏳ يتم البحث عن أفضل الفرص."
    )

    results = scan_market(limit=5)

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم يتم العثور حالياً على فرص "
            "تتجاوز شروط التأكيد."
        )

        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n"
        f"وجدت {len(results)} فرص مطابقة للشروط."
    )

    for data in results:

        report = generate_evidence_report(data)

        await update.message.reply_text(report)


# =========================================================
# COIN ANALYSIS
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    symbol = normalize_symbol(text)

    await update.message.reply_text(
        f"🔍 جاري تحليل العملة {symbol}..."
    )

    data = get_coin_analysis(symbol)

    if not data:

        await update.message.reply_text(
            f"❌ تعذر جلب بيانات {symbol} "
            f"من Binance Futures حالياً.\n\n"
            f"تأكد أن الزوج موجود على Binance Futures "
            f"وأنه USDT Perpetual."
        )

        return

    report = generate_evidence_report(data)

    await update.message.reply_text(report)


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("scan", scan_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            handle_message
        )
    )

    print("Bot is starting polling...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
