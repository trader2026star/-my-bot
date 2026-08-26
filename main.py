import os
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
# /START
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
        "• BOS + Market Structure\n"
        "• السيولة والحجم\n"
        "• RSI + EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"

        "🟢 ENTRY READY = صفقة جاهزة\n"
        "🟡 REVERSAL WATCH = ننتظر Pullback/تأكيد\n"
        "🔵 ACCUMULATION WATCH = تجميع مبكر\n\n"

        "🛡️ التأكيدات موزونة وليست كلها شروطاً منفردة."
    )


# =========================================================
# /SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"
        "⚡ سيتم أولاً فلترة السوق بسرعة، "
        "ثم تحليل أفضل المرشحين فقط.\n\n"
        "🧠 جاري البحث عن:\n"
        "🟢 ENTRY READY\n"
        "🟡 REVERSAL WATCH\n"
        "🔵 ACCUMULATION WATCH\n\n"
        "⏳ انتظر قليلاً..."
    )

    try:
        results = scan_market(limit=5)

    except Exception as exc:
        logger.exception(
            "Scanner error: %s",
            exc
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
            "تستحق الإرسال.\n\n"
            "🛡️ البوت فضّل الانتظار بدلاً من "
            "إعطاء صفقة ضعيفة."
        )

        return

    await update.message.reply_text(
        "✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} مرشحين.\n\n"
        "📊 يتم إرسال أفضل النتائج:"
    )

    for data in results:

        try:

            report = generate_evidence_report(data)

            await update.message.reply_text(report)

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
        f"🔍 جاري تحليل {symbol}...\n\n"
        "📊 1D = الاتجاه العام\n"
        "📊 4H = الاتجاه الرئيسي\n"
        "⏱️ 1H = بوابة الدخول\n"
        "⏱️ 30m + 15m = التأكيد\n\n"
        "🧠 جاري فحص:\n"
        "BOS + Market Structure\n"
        "السيولة + الحجم\n"
        "RSI + EMA\n"
        "القاع والتجميع\n"
        "Support / Resistance\n\n"
        "⏳ انتظر النتيجة..."
    )

    try:

        data = get_coin_analysis(symbol)

    except Exception as exc:

        logger.exception(
            "Coin analysis error for %s: %s",
            symbol,
            exc
        )

        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\n"
            "حاول مرة أخرى بعد قليل."
        )

        return

    if not data:

        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol} حالياً.\n\n"
            "تأكد أن الزوج موجود على "
            "BingX Futures وأنه USDT."
        )

        return

    try:

        report = generate_evidence_report(data)

        await update.message.reply_text(report)

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

    logger.info("Creating Telegram application...")

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
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("Telegram bot is starting...")

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
    logger.info("BingX AI Scanner starting...")
    logger.info("=" * 60)

    # -----------------------------------------------------
    # Start Flask first
    # -----------------------------------------------------

    flask_thread = threading.Thread(
        target=run_flask,
        name="FlaskServer",
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "Flask thread started."
    )

    # -----------------------------------------------------
    # Give Flask a moment to bind the Render port
    # -----------------------------------------------------

    import time

    time.sleep(1)

    # -----------------------------------------------------
    # Start Telegram in main process
    # -----------------------------------------------------

    run_bot()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
