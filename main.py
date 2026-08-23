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


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 Crypto Zero Reversal\n\n"
        "الأوامر المتاحة:\n"
        "• /scan - فحص سوق Binance Futures بالكامل\n"
        "• BTC - تحليل عملة محددة\n\n"
        "التحليل يعتمد على:\n"
        "15m + 1H + 4H + 1D\n"
        "الدعم + المقاومة + السيولة + التجميع + الزخم"
    )


async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔎 جاري فحص سوق Binance Futures بالكامل...\n\n"
        "أبحث عن:\n"
        "• هبوط سابق\n"
        "• تجميع\n"
        "• دخول السيولة\n"
        "• دعم ومقاومة\n"
        "• تحسن الحجم والزخم\n"
        "• تأكيد 15m / 1H / 4H / 1D\n\n"
        "قد يستغرق الفحص بعض الوقت."
    )

    try:

        results = scan_market(
            limit=5
        )

    except Exception as e:

        logger.exception(
            "Scan failed: %s",
            e
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص Binance.\n"
            "راجع Logs في Render."
        )

        return

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم أجد حالياً فرصة LONG أو SHORT "
            "تتجاوز شروط التأكيد.\n\n"
            "تم رفض الفرص الضعيفة أو القريبة "
            "من الدعم/المقاومة أو التي تحركت بالفعل."
        )

        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n"
        f"وجدت {len(results)} فرص مطابقة للشروط.\n"
        f"تم اختيار أفضل الفرص."
    )

    for data in results:

        try:

            await update.message.reply_text(
                generate_evidence_report(
                    data
                )
            )

        except Exception as e:

            logger.exception(
                "Report error: %s",
                e
            )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    text = text.strip()

    if not text:
        return

    # BTC -> BTCUSDT
    # BTCUSDT -> BTCUSDT
    symbol = normalize_symbol(
        text
    )

    if not symbol:

        await update.message.reply_text(
            "❌ اكتب رمز العملة مثل BTC."
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
            "Coin analysis error: %s",
            e
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء جلب بيانات Binance."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أجد زوج {symbol} "
            f"على Binance Futures "
            f"أو تعذر جلب بياناته حالياً."
        )

        return

    await update.message.reply_text(
        generate_evidence_report(
            data
        )
    )


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
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    logger.info(
        "Crypto Zero Reversal started successfully."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
