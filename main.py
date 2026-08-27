import os
import logging
import threading
import asyncio
import time

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
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT TOKEN
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )


# =========================================================
# FLASK / RENDER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "BingX AI Scanner is running.", 200


@app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", "10000"))

    logger.info(
        "Starting Flask server on 0.0.0.0:%s",
        port
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"

        "📌 أرسل اسم العملة للتحليل مباشرة:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n\n"

        "📌 أمر الفحص الشامل للسوق:\n"
        "/scan\n\n"

        "🟢 البوت جاهز لإعطاء الصفقات وتحديد نقاط الدخول والأهداف بدقة."
    )


# =========================================================
# SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    start_time = time.time()

    await update.message.reply_text(
        "🔍 جاري فحص سوق العملات على BingX Futures...\n\n"
        "⏳ يرجى الانتظار ثوانٍ معدودة لجلب أفضل الصفقات..."
    )

    try:

        results = await asyncio.to_thread(
            scan_market,
            5
        )

    except Exception as exc:

        logger.exception(
            "Scanner error: %s",
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق."
        )

        return

    elapsed = round(
        time.time() - start_time,
        1
    )

    if not results:

        # Fallback اضطراري إضافي لو حدث أي طارئ
        fallback_res = await asyncio.to_thread(get_coin_analysis, "BTCUSDT")
        if fallback_res:
            results = [fallback_res]

    if not results:

        await update.message.reply_text(
            "⚠️ لم يتم العثور على نتائج، حاول مرة أخرى بعد قليل."
        )

        return

    await update.message.reply_text(
        f"✅ تم الانتهاء من الفحص بنجاح!\n"
        f"🎯 عدد الصفقات المتاحة: {len(results)}\n"
        f"⏱️ استغرق الفحص: {elapsed} ثانية\n\n"
        "👇 إليك التفاصيل:"
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
    context: ContextTypes.DEFAULT_TYPE,
):

    if (
        not update.message
        or not update.message.text
    ):
        return

    text = update.message.text.strip()

    if not text:
        return

    symbol = normalize_symbol(text)

    await update.message.reply_text(
        f"🔍 جاري تحليل وتجهيز صفقة لـ {symbol}...\n\n"
        "⏳ انتظر اللحظات..."
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
            f"❌ حدث خطأ أثناء تحليل {symbol}."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol}، تأكد أنه زوج USDT صحيح على BingX."
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
            "Report error for %s: %s",
            symbol,
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إنشاء التقرير."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Telegram error: %s",
        context.error,
        exc_info=True,
    )


# =========================================================
# TELEGRAM BOT
# =========================================================

def run_bot():

    logger.info(
        "Creating Telegram application..."
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
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Telegram bot is starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info("=" * 60)
    logger.info(
        "BingX AI Scanner starting..."
    )
    logger.info("=" * 60)

    flask_thread = threading.Thread(
        target=run_flask,
        name="FlaskServer",
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "Flask thread started."
    )

    time.sleep(1)

    run_bot()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
