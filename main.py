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
        "XRP\n\n"

        "أو أي زوج USDT موجود على BingX Futures.\n\n"

        "📌 أمر الفحص الكامل:\n"
        "/scan\n\n"

        "🔎 النظام يعتمد على:\n"
        "• 4H = الاتجاه الرئيسي\n"
        "• 1H = بوابة الدخول\n"
        "• BOS مؤكد\n"
        "• Market Structure\n"
        "• السيولة\n"
        "• Volume\n"
        "• RSI\n"
        "• EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"

        "🛡️ لا يتم اعتماد الصفقة إلا بعد اكتمال التأكيدات."
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

        "🧠 شروط البحث:\n"
        "• اتجاه 4H واضح\n"
        "• تأكيد 1H\n"
        "• BOS\n"
        "• سيولة مؤكدة\n"
        "• Volume مناسب\n"
        "• عدم مطاردة القاع أو البامب\n\n"

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
            "راجع Logs وحاول مرة أخرى."
        )

        return

    if not results:

        await update.message.reply_text(

            "🟡 انتهى الفحص.\n\n"

            "لم يتم العثور حالياً على صفقة "
            "مؤكدة بالشروط النهائية.\n\n"

            "🛡️ البوت فضّل الانتظار بدلاً من "
            "إعطاء صفقة ضعيفة."
        )

        return

    await update.message.reply_text(

        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص مؤكدة.\n"
        f"📊 سيتم إرسال الأفضل."
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
# COIN
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
        "⏱️ 1H = بوابة الدخول\n"
        "🧠 جاري فحص BOS + السيولة + الحجم..."
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

            "تأكد أن الزوج موجود على "
            "BingX Futures وأنه USDT."
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
# ERROR
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

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

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
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

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
