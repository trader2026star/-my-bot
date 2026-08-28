import os
import logging
import threading
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
    return "BingX AI Scanner - ORDER BLOCK ENGINE is running.", 200


@app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", "10000"))

    logger.info(
        "Starting Flask server on 0.0.0.0:%s",
        port,
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# =========================================================
# TELEGRAM MESSAGE HELPER
# =========================================================

async def send_long_message(
    update: Update,
    text: str,
):
    """
    Telegram يسمح بحوالي 4096 حرف.
    نقسم التقرير بأمان بدون فقدان المحتوى.
    """

    if not update.message:
        return

    if not text:
        return

    max_length = 3900

    if len(text) <= max_length:

        await update.message.reply_text(
            text
        )

        return

    current = ""

    for line in text.split("\n"):

        # لو السطر نفسه طويل جداً
        if len(line) > max_length:

            if current:

                await update.message.reply_text(
                    current
                )

                current = ""

            for i in range(
                0,
                len(line),
                max_length,
            ):

                await update.message.reply_text(
                    line[i:i + max_length]
                )

            continue

        if (
            len(current)
            + len(line)
            + 1
            > max_length
        ):

            if current:

                await update.message.reply_text(
                    current
                )

            current = ""

        current += line + "\n"

    if current:

        await update.message.reply_text(
            current
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
        "🤖 BingX AI Scanner\n\n"

        "🏦 المحرك الأساسي:\n"
        "ORDER BLOCK\n\n"

        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n"
        "XRP\n\n"

        "أو أي زوج USDT موجود على BingX Futures.\n\n"

        "📌 للفحص الكامل للسوق:\n"
        "/scan\n\n"

        "🧠 منهج التحليل:\n"
        "• 1D = Context\n"
        "• 4H = MTF Order Block\n"
        "• 1H = Primary Order Block\n"
        "• 30m + 15m = Confirmation\n"
        "• BOS + Market Structure\n"
        "• Liquidity + Volume\n"
        "• Retest\n"
        "• Accumulation / Distribution\n"
        "• ATR + Entry / SL / TP\n\n"

        "🟢 ENTRY READY\n"
        "🟡 REVERSAL WATCH\n"
        "🔵 ACCUMULATION WATCH\n\n"

        "🛡️ Order Block هو العامل الأساسي.\n"
        "الشموع لا يتم استخدامها وحدها لتحديد LONG أو SHORT."
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

    started = time.time()

    # -----------------------------------------------------
    # START MESSAGE
    # -----------------------------------------------------

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"

        "🏦 ORDER BLOCK هو المحرك الأساسي.\n\n"

        "⚡ فلترة سريعة للسوق أولاً.\n"
        "🧠 ثم تحليل أفضل المرشحين فقط.\n\n"

        "🟢 ENTRY READY\n"
        "🟡 REVERSAL WATCH\n"
        "🔵 ACCUMULATION WATCH\n\n"

        "⏳ انتظر..."
    )

    try:

        results = scan_market(
            limit=5
        )

    except Exception as exc:

        logger.exception(
            "Market scan failed: %s",
            exc,
        )

        elapsed = (
            time.time()
            - started
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n\n"
            f"⏱️ وقت الفحص: {elapsed:.1f} ثانية\n\n"
            "راجع Logs في Render."
        )

        return

    elapsed = (
        time.time()
        - started
    )

    # -----------------------------------------------------
    # NO RESULTS
    # -----------------------------------------------------

    if not results:

        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"

            "لم يتم العثور حالياً على "
            "Order Block قوي ومؤكد.\n\n"

            "🛡️ البوت فضّل الانتظار "
            "بدلاً من إعطاء صفقة ضعيفة.\n\n"

            f"⏱️ وقت الفحص: {elapsed:.1f} ثانية"
        )

        return

    # -----------------------------------------------------
    # RESULTS
    # -----------------------------------------------------

    await update.message.reply_text(
        "✅ انتهى الفحص.\n\n"

        f"🎯 عدد المرشحين: {len(results)}\n"
        f"⏱️ وقت الفحص: {elapsed:.1f} ثانية\n\n"

        "🏦 أفضل مناطق Order Block:"
    )

    # -----------------------------------------------------
    # SEND RESULTS
    # -----------------------------------------------------

    for index, data in enumerate(
        results,
        start=1,
    ):

        try:

            symbol = data.get(
                "symbol",
                "UNKNOWN",
            )

            direction = data.get(
                "direction",
                "WAIT",
            )

            state = data.get(
                "state",
                "NO TRADE",
            )

            score = data.get(
                "score",
                0,
            )

            ob_direction = data.get(
                "order_block_direction",
                "NEUTRAL",
            )

            ob_score = data.get(
                "order_block_score",
                0,
            )

            logger.info(
                "SCAN RESULT %s | %s | direction=%s | state=%s | score=%s | OB=%s/%s",
                index,
                symbol,
                direction,
                state,
                score,
                ob_direction,
                ob_score,
            )

            report = generate_evidence_report(
                data
            )

            await send_long_message(
                update,
                report,
            )

        except Exception as exc:

            logger.exception(
                "Failed sending scan result: %s",
                exc,
            )

            await update.message.reply_text(
                "⚠️ تعذر إرسال تقرير إحدى النتائج."
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

    text = (
        update.message.text
        .strip()
    )

    if not text:
        return

    # -----------------------------------------------------
    # Ignore accidental commands
    # -----------------------------------------------------

    if text.startswith("/"):
        return

    symbol = normalize_symbol(
        text
    )

    if not symbol:

        await update.message.reply_text(
            "❌ اكتب اسم العملة مثل BTC أو ETH."
        )

        return

    await update.message.reply_text(
        f"🔍 جاري تحليل {symbol}...\n\n"

        "🏦 ORDER BLOCK = المحرك الأساسي\n\n"

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

    try:

        data = get_coin_analysis(
            symbol
        )

    except Exception as exc:

        logger.exception(
            "Coin analysis exception for %s: %s",
            symbol,
            exc,
        )

        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\n"
            "حاول مرة أخرى بعد قليل."
        )

        return

    # -----------------------------------------------------
    # NO DATA
    # -----------------------------------------------------

    if not data:

        await update.message.reply_text(
            f"❌ لم تصل بيانات تحليل {symbol}.\n\n"
            "تأكد أن الزوج موجود على BingX Futures."
        )

        return

    # -----------------------------------------------------
    # ANALYSIS FAILED
    # -----------------------------------------------------

    if not data.get(
        "analysis_ok",
        False,
    ):

        reason = data.get(
            "reason",
            "",
        )

        message = (
            f"⚠️ تعذر إكمال تحليل {symbol}.\n\n"
            "لم يتم إعطاء صفقة وهمية."
        )

        if reason:

            message += (
                f"\n\n🧾 السبب: {reason}"
            )

        await update.message.reply_text(
            message
        )

        return

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    try:

        report = generate_evidence_report(
            data
        )

        await send_long_message(
            update,
            report,
        )

    except Exception as exc:

        logger.exception(
            "Report generation failed for %s: %s",
            symbol,
            exc,
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

    error = context.error

    logger.error(
        "Telegram error: %s",
        error,
        exc_info=True,
    )

    if error and "Conflict" in str(error):

        logger.error(
            "TELEGRAM CONFLICT: "
            "another bot instance is running."
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

    # -----------------------------------------------------
    # COMMANDS
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

    # -----------------------------------------------------
    # COIN MESSAGES
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message,
        )
    )

    # -----------------------------------------------------
    # ERROR HANDLER
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Telegram bot is starting..."
    )

    # -----------------------------------------------------
    # POLLING
    # -----------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info("=" * 70)

    logger.info(
        "BingX AI Scanner starting..."
    )

    logger.info(
        "ENGINE: ORDER BLOCK PRIMARY"
    )

    logger.info(
        "DIRECTION: OB + MTF OB + BOS + LIQUIDITY"
    )

    logger.info(
        "CANDLE COLOR IS NOT A PRIMARY DIRECTION SIGNAL"
    )

    logger.info("=" * 70)

    # -----------------------------------------------------
    # FLASK
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
    # WAIT FOR FLASK
    # -----------------------------------------------------

    time.sleep(1)

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    run_bot()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
