import os
import asyncio
import logging
import threading

from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

from analysis import (
    scan_market,
    get_coin_analysis,
    generate_evidence_report,
    normalize_symbol,
    get_current_price,
)


# =========================================================
# Logging
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# Telegram Token
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )


# =========================================================
# Flask Server - Render
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is Running Live!"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    """
    Flask runs in a completely separate background thread.
    Render provides the PORT dynamically.
    """

    port = int(
        os.environ.get("PORT", "5000")
    )

    logger.info(
        "Starting Flask server on port %s",
        port,
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"

        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n"
        "XRP\n\n"

        "أو أي زوج USDT موجود على BingX Futures.\n\n"

        "📌 أمر الفحص الكامل:\n"
        "/scan\n\n"

        "🔎 النظام يعتمد على:\n"
        "• 1D = الاتجاه العام\n"
        "• 4H = الاتجاه الرئيسي\n"
        "• 1H = بوابة الدخول\n"
        "• 30m + 15m = تأكيد إضافي\n"
        "• Order Block + Retest\n"
        "• BOS + Market Structure\n"
        "• السيولة والحجم\n"
        "• RSI + EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"

        "🛡️ ORDER BLOCK هو المحرك الأساسي."
    )


# =========================================================
# /scan
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"

        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📡 الأسعار تُسحب مباشرة من BingX Futures\n"
        "🧠 1D + 4H Context | 1H Primary OB | "
        "30m + 15m Confirmation\n"
        "💧 Liquidity + Volume + BOS\n\n"

        "⏳ انتظر النتيجة..."
    )

    try:
        results = scan_market(
            limit=5
        )

    except Exception as exc:
        logger.exception(
            "Scanner error: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n\n"
            "راجع Logs وحاول مرة أخرى."
        )

        return

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"

            "لم يتم العثور حالياً على فرصة قوية "
            "بالشروط النهائية.\n\n"

            "🛡️ البوت فضّل الانتظار بدلاً من إعطاء صفقة ضعيفة."
        )

        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص.\n"
        f"💰 كل نتيجة تتضمن السعر الحالي من BingX.\n"
        f"🏦 سيتم إرسال أفضل مناطق Order Block."
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
                exc,
            )


# =========================================================
# Coin Analysis
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    symbol = normalize_symbol(
        text
    )

    # -----------------------------------------------------
    # Current BingX Futures Price
    # -----------------------------------------------------

    try:

        price = get_current_price(
            symbol,
            True,
        )

    except Exception as exc:

        logger.exception(
            "Price error for %s: %s",
            symbol,
            exc,
        )

        price = None

    if price is not None:

        price_text = (
            f"💰 السعر الحالي: {price}\n"
        )

    else:

        price_text = (
            "💰 السعر الحالي: جاري جلبه من BingX...\n"
        )

    # -----------------------------------------------------
    # Progress Message
    # -----------------------------------------------------

    await update.message.reply_text(
        f"🔍 جاري تحليل {symbol}...\n\n"

        f"{price_text}"

        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📊 1D = Context\n"
        "📊 4H = MTF Order Block\n"
        "⏱️ 1H = Primary Entry Zone\n"
        "⏱️ 30m + 15m = Confirmation\n\n"

        "🧠 جاري فحص:\n"
        "Order Block\n"
        "OB Retest\n"
        "BOS + Market Structure\n"
        "Liquidity + Volume\n"
        "Accumulation / Distribution\n"
        "MTF Order Blocks\n"
        "ATR + Entry / SL / TP\n\n"

        "⏳ انتظر النتيجة..."
    )

    # -----------------------------------------------------
    # Analysis
    # -----------------------------------------------------

    try:

        data = get_coin_analysis(
            symbol
        )

    except Exception as exc:

        logger.exception(
            "Coin analysis error for %s: %s",
            symbol,
            exc,
        )

        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\n"
            "حاول مرة أخرى بعد قليل."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol} حالياً.\n\n"
            "تأكد أن الزوج موجود على BingX Futures "
            "وأنه USDT."
        )

        return

    # -----------------------------------------------------
    # Evidence Report
    # -----------------------------------------------------

    try:

        report = generate_evidence_report(
            data
        )

        await update.message.reply_text(
            report
        )

    except Exception as exc:

        logger.exception(
            "Report error for %s: %s",
            symbol,
            exc,
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إنشاء التقرير."
        )


# =========================================================
# Telegram Error Handler
# =========================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Telegram error: %s",
        context.error,
    )


# =========================================================
# Telegram Bot Application
# =========================================================

application = None


# =========================================================
# Main Async Telegram Loop
# =========================================================

async def main_bot():

    global application

    logger.info(
        "Creating Telegram application..."
    )

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Handlers
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    application.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # Initialize Telegram Application
    # -----------------------------------------------------

    logger.info(
        "Initializing Telegram application..."
    )

    await application.initialize()

    # -----------------------------------------------------
    # Delete Old Webhook
    # -----------------------------------------------------

    logger.info(
        "Deleting old Telegram webhook..."
    )

    try:

        await application.bot.delete_webhook(
            drop_pending_updates=True
        )

        logger.info(
            "Telegram webhook deleted successfully."
        )

    except Exception as exc:

        logger.exception(
            "Webhook deletion failed: %s",
            exc
        )

        await application.shutdown()

        raise

    # -----------------------------------------------------
    # Start Telegram Application
    # -----------------------------------------------------

    logger.info(
        "Starting Telegram application..."
    )

    await application.start()

    # -----------------------------------------------------
    # Start Long Polling
    # -----------------------------------------------------

    if application.updater is None:
        raise RuntimeError(
            "Telegram updater is not available."
        )

    logger.info(
        "Starting Telegram polling..."
    )

    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

    logger.info(
        "Telegram bot is now running."
    )

    print(
        "========================================"
    )
    print(
        "BingX AI Scanner is LIVE"
    )
    print(
        "Flask: RUNNING"
    )
    print(
        "Telegram: POLLING"
    )
    print(
        "Event Loop: ACTIVE"
    )
    print(
        "========================================"
    )

    # -----------------------------------------------------
    # Keep the SAME Event Loop Alive
    # -----------------------------------------------------

    try:

        await asyncio.Event().wait()

    except asyncio.CancelledError:

        logger.info(
            "Main Telegram task cancelled."
        )

    finally:

        # -------------------------------------------------
        # Stop Polling
        # -------------------------------------------------

        if application.updater:

            try:

                await application.updater.stop()

            except Exception as exc:

                logger.exception(
                    "Error stopping updater: %s",
                    exc,
                )

        # -------------------------------------------------
        # Stop Application
        # -------------------------------------------------

        try:

            await application.stop()

        except Exception as exc:

            logger.exception(
                "Error stopping application: %s",
                exc,
            )

        # -------------------------------------------------
        # Shutdown Application
        # -------------------------------------------------

        try:

            await application.shutdown()

        except Exception as exc:

            logger.exception(
                "Error shutting down application: %s",
                exc,
            )


# =========================================================
# Program Entry Point
# =========================================================

if __name__ == "__main__":

    # -----------------------------------------------------
    # 1. Start Flask in a separate background Thread
    # -----------------------------------------------------

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
        name="FlaskThread",
    )

    flask_thread.start()

    logger.info(
        "Flask background thread started."
    )

    # -----------------------------------------------------
    # 2. Run Telegram inside ONE dedicated Event Loop
    # -----------------------------------------------------

    try:

        asyncio.run(
            main_bot()
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped by keyboard interrupt."
        )

    except Exception as exc:

        logger.exception(
            "Fatal Telegram bot error: %s",
            exc,
        )

        raise
