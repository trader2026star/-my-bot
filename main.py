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
# SETTINGS
# =========================================================

BOT_TOKEN = "8927885606:AAGf6tXEKi-Q9uQOdl1NVif8_OjODH3DPbQ"

PORT = int(
    os.environ.get(
        "PORT",
        "10000"
    )
)


# =========================================================
# RENDER WEB SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():

    return (
        "Crypto Zero Reversal Bot "
        "is running."
    )


@app.route("/health")
def health():

    return "OK"


def run_web_server():

    logger.info(
        "Render web server listening "
        "on port %s",
        PORT
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
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

        "🤖 Crypto Zero Reversal\n\n"

        "الأوامر المتاحة:\n"

        "• /scan - فحص سوق Binance Futures بالكامل\n"

        "• BTC - تحليل عملة محددة\n\n"

        "📊 التحليل يعتمد على:\n"

        "15m + 1H + 4H + 1D\n"

        "الدعم + المقاومة + السيولة "
        "+ التجميع + الزخم"
    )


# =========================================================
# SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🔎 جاري فحص سوق Binance Futures بالكامل...\n\n"

        "أبحث عن:\n"

        "• الهبوط السابق\n"
        "• التجميع\n"
        "• دخول السيولة\n"
        "• الدعم والمقاومة\n"
        "• تحسن الحجم والزخم\n"
        "• تأكيد 15m / 1H / 4H / 1D\n\n"

        "⏳ انتظر حتى ينتهي الفحص."
    )

    try:

        results = scan_market(
            limit=5
        )

    except Exception:

        logger.exception(
            "Scan failed"
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

            "تم استبعاد الفرص الضعيفة "
            "أو التي تحركت بالفعل."
        )

        return

    await update.message.reply_text(

        f"✅ انتهى الفحص.\n"
        f"وجدت {len(results)} فرص مطابقة للشروط.\n"
        f"تم اختيار أفضل الفرص."
    )

    for data in results:

        try:

            report = (
                generate_evidence_report(
                    data
                )
            )

            await update.message.reply_text(
                report
            )

        except Exception:

            logger.exception(
                "Report error"
            )


# =========================================================
# COIN MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
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

    symbol = normalize_symbol(
        text
    )

    if not symbol:

        await update.message.reply_text(
            "❌ اكتب رمز العملة مثل BTC."
        )

        return

    await update.message.reply_text(

        f"🔎 جاري تحليل العملة "
        f"{symbol}...\n"

        "15m + 1H + 4H + 1D"
    )

    try:

        data = get_coin_analysis(
            symbol
        )

    except Exception:

        logger.exception(
            "Coin analysis error"
        )

        await update.message.reply_text(

            "❌ حدث خطأ أثناء جلب بيانات Binance."
        )

        return

    if not data:

        await update.message.reply_text(

            f"❌ لم أجد زوج "
            f"{symbol} على Binance Futures "
            f"أو تعذر جلب بياناته حالياً."
        )

        return

    try:

        report = (
            generate_evidence_report(
                data
            )
        )

        await update.message.reply_text(
            report
        )

    except Exception:

        logger.exception(
            "Report generation error"
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إنشاء التقرير."
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

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    while True:
        try:
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
                    filters.TEXT
                    & ~filters.COMMAND,
                    handle_message
                )
            )

            logger.info(
                "Crypto Zero Reversal bot "
                "starting..."
            )

            application.run_polling(
                drop_pending_updates=True
            )

        except Exception as e:
            logger.error(f"Polling error: {e}. Reconnecting in 5 seconds...")
            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
