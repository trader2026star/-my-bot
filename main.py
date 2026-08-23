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
    normalize_symbol,
    get_coin_analysis,
    scan_market,
    generate_evidence_report
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    welcome_text = (
        "🤖 مرحباً بك في Crypto Zero Reversal\n\n"

        "الأوامر المتاحة:\n"

        "• /scan\n"
        "لفحص السوق والبحث عن أفضل الفرص المؤكدة.\n\n"

        "• اكتب اسم العملة مباشرة\n"
        "مثال: BTC أو BTCUSDT\n\n"

        "سيتم تحليل العملة على:\n"
        "15m + 1H + 4H + 1D"
    )

    await update.message.reply_text(
        welcome_text
    )


# =========================================================
# SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔎 جاري فحص السوق وتحليل العملات...\n"
        "15m + 1H + 4H + 1D"
    )

    try:

        results = scan_market(limit=5)

    except Exception as e:

        logger.exception(
            "Scan failed: %s",
            e
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n"
            "راجع Logs في Render."
        )

        return

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم تظهر حالياً فرص LONG أو SHORT "
            "تتجاوز شروط التأكيد.\n\n"
            "هذا يعني أن الفلتر رفض الفرص الضعيفة "
            "وليس أن Binance لا يعمل."
        )

        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n"
        f"وجدت {len(results)} فرص مطابقة للشروط.\n"
        f"سيتم إرسال أفضل الفرص الآن."
    )

    for data in results:

        try:

            report = generate_evidence_report(
                data
            )

            await update.message.reply_text(
                report
            )

        except Exception as e:

            logger.exception(
                "Report error: %s",
                e
            )


# =========================================================
# DIRECT COIN ANALYSIS
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    original_text = (
        update.message.text.strip()
    )

    if not original_text:
        return

    # IMPORTANT:
    # Normalize only once here.
    symbol = normalize_symbol(
        original_text
    )

    if not symbol:

        await update.message.reply_text(
            "❌ اكتب رمز العملة مثل BTC أو ETH."
        )

        return

    await update.message.reply_text(
        f"🔎 جاري تحليل العملة {symbol}...\n"
        f"15m + 1H + 4H + 1D"
    )

    try:

        data = get_coin_analysis(
            symbol
        )

    except Exception as e:

        logger.exception(
            "Coin analysis failed for %s: %s",
            symbol,
            e
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء الاتصال ببيانات Binance.\n"
            "راجع Logs في Render."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أجد زوج {symbol} على Binance "
            f"أو تعذر جلب بياناته حالياً.\n\n"
            f"مثال صحيح: BTC"
        )

        return

    report = generate_evidence_report(
        data
    )

    await update.message.reply_text(
        report
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        logger.error(
            "BOT_TOKEN is missing!"
        )

        return

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
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
            filters.TEXT & (~filters.COMMAND),
            handle_message
        )
    )

    logger.info(
        "Crypto Zero Reversal bot started successfully."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
