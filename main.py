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
# FLASK SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "BingX AI Scanner is running."


@app.route("/health")
def health():
    return "OK"


def run_flask():

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
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

        "🤖 أهلاً بك في BingX AI Scanner\n\n"

        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n"
        "XRP\n"
        "أو أي عملة USDT موجودة على BingX.\n\n"

        "📌 أو استخدم:\n"
        "/scan\n\n"

        "🔎 التحليل يعتمد على:\n"
        "• اتجاه 4H كاتجاه رئيسي\n"
        "• فريم الساعة لتحديد منطقة الدخول\n"
        "• RSI\n"
        "• Volume\n"
        "• دخول وخروج السيولة\n"
        "• القاع والتجميع\n"
        "• الدعم والمقاومة\n"
        "• Market Structure\n"
        "• Entry / SL / TP\n\n"

        "⚠️ لا يتم فتح LONG عكس اتجاه 4H.\n"
        "⚠️ ولا يتم فتح SHORT عكس اتجاه 4H."
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

        "🔍 جاري فحص BingX Futures...\n\n"
        "📊 يتم البحث عن العملات التي:\n"
        "• يوجد بها دخول سيولة → LONG\n"
        "• يوجد بها خروج سيولة → SHORT\n"
        "• اتجاه 4H واضح\n"
        "• الساعة مناسبة لمنطقة الدخول\n\n"
        "⏳ انتظر قليلاً..."
    )

    try:

        results = scan_market(
            limit=5
        )

    except Exception as exc:

        logger.exception(
            "Scanner error: %s",
            exc
        )

        await update.message.reply_text(

            "❌ حدث خطأ أثناء فحص السوق.\n\n"
            "حاول مرة أخرى بعد قليل."
        )

        return

    if not results:

        await update.message.reply_text(

            "🟡 انتهى الفحص.\n\n"

            "لم يتم العثور حالياً على فرص "
            "تستوفي شروط التأكيد.\n\n"

            "هذا يعني أن البوت رفض الدخول "
            "بدلاً من إعطاء صفقة ضعيفة."
        )

        return

    await update.message.reply_text(

        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص.\n"
        f"📊 سيتم إرسال أفضل الفرص."
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

    text = text.strip()

    if not text:
        return

    symbol = normalize_symbol(
        text
    )

    await update.message.reply_text(

        f"🔍 جاري تحليل {symbol}...\n\n"
        "📊 4H = الاتجاه الرئيسي\n"
        "⏱️ 1H = تحديد منطقة الدخول"
    )

    try:

        data = get_coin_analysis(
            symbol
        )

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

            "تأكد أن العملة موجودة على BingX "
            "Futures وأن الزوج USDT."
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
            "Generate report error: %s",
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إنشاء تقرير التحليل."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    logger.error(
        "Telegram error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # =====================================================
    # START FLASK
    # =====================================================

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    # =====================================================
    # TELEGRAM APPLICATION
    # =====================================================

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # =====================================================
    # COMMANDS
    # =====================================================

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

    # =====================================================
    # COIN MESSAGE
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # =====================================================
    # ERROR HANDLER
    # =====================================================

    application.add_error_handler(
        error_handler
    )

    # =====================================================
    # START
    # =====================================================

    print(
        "Telegram bot is starting..."
    )

    print(
        "Flask server is starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
