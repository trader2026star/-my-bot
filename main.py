import os
import logging
import asyncio

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
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO
)

logger = logging.getLogger(__name__)


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

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    await update.message.reply_text(
        "🤖 أهلاً بك في Binance AI Scanner\n\n"
        "📌 أرسل اسم العملة:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n\n"
        "📌 أو استخدم:\n"
        "/scan\n\n"
        "🔎 التحليل يشمل:\n"
        "• اصطياد القيعان\n"
        "• التجميع المبكر\n"
        "• دخول السيولة\n"
        "• خروج السيولة\n"
        "• الدعم والمقاومة\n"
        "• RSI\n"
        "• Volume\n"
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

    if not update.message:
        return

    await update.message.reply_text(
        "🔍 جاري فحص Binance Futures...\n"
        "⏳ أبحث عن القيعان والتجميع ودخول السيولة."
    )

    try:
        results = await asyncio.to_thread(
            scan_market,
            5
        )

    except Exception as exc:
        logger.exception(
            "Scan error: %s",
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n"
            "راجع Render Logs."
        )

        return

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم أجد حالياً فرصة قوية تتجاوز "
            "شروط الفلترة."
        )

        return

    await update.message.reply_text(
        "✅ انتهى الفحص.\n"
        f"وجدت {len(results)} فرص محتملة."
    )

    for data in results:

        try:
            report = generate_evidence_report(
                data
            )

            await update.message.reply_text(
                report
            )

        except Exception as exc:
            logger.exception(
                "Report error: %s",
                exc
            )


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
        f"🔍 جاري تحليل {symbol}...\n"
        "⏳ أفحص الاتجاه والسيولة والقاع والدعم والمقاومة."
    )

    try:
        data = await asyncio.to_thread(
            get_coin_analysis,
            symbol
        )

    except Exception as exc:
        logger.exception(
            "Coin analysis error for %s: %s",
            symbol,
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء التحليل.\n"
            "راجع Render Logs."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أستطع جلب بيانات {symbol}.\n\n"
            "تأكد أن العملة موجودة على "
            "Binance Futures كزوج USDT Perpetual."
        )

        return

    try:
        report = generate_evidence_report(
            data
        )

        await update.message.reply_text(
            report
        )

    except Exception as exc:
        logger.exception(
            "Report generation error: %s",
            exc
        )

        await update.message.reply_text(
            "❌ تم تحليل العملة لكن حدث خطأ "
            "أثناء تجهيز التقرير."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error,
        exc_info=True
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info(
        "Starting CryptoZeroReversal bot..."
    )

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & (~filters.COMMAND),
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Bot is starting polling..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
