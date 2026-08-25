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
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Crypto Zero Reversal Bot is running."


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

    logger.info(
        "Flask server starting on port %s",
        port
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

    await update.message.reply_text(

        "🤖 أهلاً بك في Crypto Zero Reversal\n\n"

        "📌 أرسل اسم العملة:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n\n"

        "📌 أو استخدم:\n"
        "/scan\n\n"

        "🔎 التحليل يعتمد على:\n"
        "• اتجاه 4H كاتجاه رئيسي\n"
        "• EMA\n"
        "• RSI\n"
        "• Volume\n"
        "• دخول/خروج السيولة\n"
        "• اكتشاف القاع والتجميع\n"
        "• الدعم والمقاومة\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"

        "⚠️ لا يتم فتح LONG ضد اتجاه 4H.\n"
        "⚠️ لا يتم فتح SHORT ضد اتجاه 4H."
    )


# =========================================================
# SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        await update.message.reply_text(
            "🔍 جاري فحص السوق...\n"
            "📊 الاتجاه الرئيسي: 4H\n"
            "⏳ انتظر حتى انتهاء الفحص."
        )

        results = scan_market(
            limit=5
        )

        if not results:

            await update.message.reply_text(
                "🟡 انتهى الفحص.\n\n"
                "لم يتم العثور حالياً على فرصة "
                "تتوافق مع اتجاه 4H وشروط التأكيد."
            )

            return

        await update.message.reply_text(
            f"✅ انتهى الفحص.\n"
            f"وجدت {len(results)} فرص مطابقة للشروط."
        )

        for data in results:

            report = generate_evidence_report(
                data
            )

            await update.message.reply_text(
                report
            )

    except Exception as exc:

        logger.exception(
            "SCAN ERROR: %s",
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n"
            "راجع Logs في Render."
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

    symbol = normalize_symbol(
        text
    )

    try:

        await update.message.reply_text(
            f"🔍 جاري تحليل {symbol}...\n"
            f"📊 الاتجاه الرئيسي: 4H"
        )

        data = get_coin_analysis(
            symbol
        )

        if not data:

            await update.message.reply_text(
                f"❌ تعذر تحليل {symbol} حالياً.\n\n"
                "قد يكون السبب:\n"
                "• الزوج غير موجود على BingX Futures\n"
                "• بيانات السوق غير متاحة مؤقتاً\n"
                "• 4H غير واضح وبالتالي لا توجد صفقة"
            )

            return

        report = generate_evidence_report(
            data
        )

        await update.message.reply_text(
            report
        )

    except Exception as exc:

        logger.exception(
            "COIN ANALYSIS ERROR %s: %s",
            symbol,
            exc
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء تحليل العملة."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def telegram_error_handler(
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

    logger.info(
        "Starting Crypto Zero Reversal..."
    )

    # =====================================================
    # FLASK THREAD
    # =====================================================

    flask_thread = threading.Thread(
        target=run_flask,
        name="FlaskThread",
        daemon=True
    )

    flask_thread.start()

    # =====================================================
    # TELEGRAM
    # =====================================================

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # Commands

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

    # Coin messages

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    application.add_error_handler(
        telegram_error_handler
    )

    logger.info(
        "Telegram bot is starting..."
    )

    # =====================================================
    # POLLING
    # =====================================================

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()
