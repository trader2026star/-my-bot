# =========================================================
# main.py - BingX AI Scanner v26
# Flask + Telegram Async Polling
# AUTO MARKET SCANNER
# =========================================================

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
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ENVIRONMENT
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

# ضع Chat ID الخاص بك في Render
CHAT_ID_RAW = os.getenv("CHAT_ID")

if not CHAT_ID_RAW:
    logger.warning(
        "CHAT_ID غير موجود. التنبيهات التلقائية لن يتم إرسالها."
    )

try:
    CHAT_ID = int(CHAT_ID_RAW) if CHAT_ID_RAW else None
except ValueError:
    raise RuntimeError("CHAT_ID يجب أن يكون رقمًا صحيحًا")


# =========================================================
# AUTO SCANNER SETTINGS
# =========================================================

# الفحص كل 30 دقيقة
AUTO_SCAN_INTERVAL = int(
    os.getenv("AUTO_SCAN_INTERVAL", "1800")
)

# عدد العملات التي سيتم فحصها
AUTO_SCAN_LIMIT = int(
    os.getenv("AUTO_SCAN_LIMIT", "50")
)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is Running Live!"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.environ.get("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# START COMMAND
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    # حفظ Chat ID تلقائيًا في الذاكرة أثناء التشغيل
    context.application.bot_data["last_chat_id"] = update.effective_chat.id

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"
        "🚀 Auto Market Scanner يعمل تلقائياً.\n\n"
        "📡 البوت يفحص السوق في الخلفية كل "
        f"{AUTO_SCAN_INTERVAL // 60} دقيقة.\n\n"
        "🟢 LONG = دخول شراء مؤكد\n"
        "🔴 SHORT = دخول بيع مؤكد\n"
        "🟡 WAIT = لا يتم إرسال تنبيه تلقائي\n\n"
        "📌 يمكنك أيضاً إرسال اسم أي عملة للتحليل اليدوي.\n\n"
        "مثال:\n"
        "BTC\n"
        "ETH\n"
        "SOL\n\n"
        "/scan = فحص يدوي للسوق"
    )


# =========================================================
# MANUAL MARKET SCAN
# =========================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    context.application.bot_data["last_chat_id"] = update.effective_chat.id

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"
        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "🧠 v26 Hard Gate\n"
        "📡 1D + 4H Context\n"
        "⏱️ 1H Primary Entry\n"
        "⏱️ 30m + 15m Confirmation\n"
        "💧 Liquidity + Volume + BOS\n\n"
        "⏳ انتظر النتيجة..."
    )

    try:
        results = scan_market(limit=AUTO_SCAN_LIMIT)

    except Exception as exc:
        logger.exception(
            "Manual scanner error: %s",
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
            "لم يتم العثور حالياً على فرصة MARKET مكتملة.\n\n"
            "🛡️ البوت فضّل الانتظار بدلاً من إعطاء صفقة ضعيفة."
        )
        return

    # إرسال النتائج التي أعادها محرك التحليل
    sent = 0

    for data in results:
        try:
            message = generate_evidence_report(data)

            await update.message.reply_text(message)

            sent += 1

        except Exception as exc:
            logger.exception(
                "Manual report error: %s",
                exc
            )

    if sent == 0:
        await update.message.reply_text(
            "🟡 لم يتم العثور على صفقة MARKET مكتملة."
        )


# =========================================================
# MANUAL COIN ANALYSIS
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    # حفظ Chat ID لاستخدامه في التنبيهات التلقائية
    context.application.bot_data["last_chat_id"] = update.effective_chat.id

    symbol = normalize_symbol(text)

    # السعر الحالي
    try:
        price = get_current_price(symbol, True)
    except Exception:
        price = None

    if price is not None:
        price_text = f"💰 السعر الحالي: {price}\n"
    else:
        price_text = (
            "💰 السعر الحالي: جاري جلبه من BingX...\n"
        )

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

    try:
        data = get_coin_analysis(symbol)

    except Exception as exc:
        logger.exception(
            "Coin analysis error for %s",
            symbol
        )

        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\n"
            "حاول مرة أخرى بعد قليل."
        )
        return

    if not data:
        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol} حالياً.\n\n"
            "تأكد أن الزوج موجود على BingX Futures وأنه USDT."
        )
        return

    try:
        await update.message.reply_text(
            generate_evidence_report(data)
        )

    except Exception as exc:
        logger.exception(
            "Report error for %s",
            symbol
        )

        await update.message.reply_text(
            "❌ حدث خطأ أثناء إنشاء التقرير."
        )


# =========================================================
# MARKET STATE DETECTION
# =========================================================

def is_market_entry(data):
    """
    يتحقق أن نتيجة analysis.py تعتبر صفقة دخول فورية.

    نحاول قراءة أكثر من اسم محتمل للحقل حتى لا نعتمد
    على اسم واحد فقط.
    """

    if not isinstance(data, dict):
        return False

    state = str(
        data.get("state")
        or data.get("status")
        or data.get("final_state")
        or data.get("trade_state")
        or ""
    ).upper()

    direction = str(
        data.get("direction")
        or data.get("final_direction")
        or data.get("signal")
        or ""
    ).upper()

    # يجب أن تكون MARKET
    if state not in {
        "MARKET",
        "ENTRY",
        "READY",
        "STRONG_ENTRY",
        "IMMEDIATE_ENTRY",
    }:
        return False

    # ويجب أن تكون LONG أو SHORT فقط
    if direction not in {
        "LONG",
        "SHORT",
    }:
        return False

    return True


# =========================================================
# AUTO MARKET SCANNER
# =========================================================

async def auto_market_scanner(
    context: ContextTypes.DEFAULT_TYPE
):
    """
    فحص تلقائي للسوق في الخلفية.

    لا يحتاج المستخدم إلى إرسال /scan.

    سيتم إرسال التنبيه فقط عندما يجد محرك v26
    فرصة دخول MARKET حقيقية LONG أو SHORT.
    """

    logger.info(
        "AUTO SCANNER: starting market scan..."
    )

    # الحصول على Chat ID
    chat_id = CHAT_ID

    if not chat_id:
        chat_id = context.application.bot_data.get(
            "last_chat_id"
        )

    if not chat_id:
        logger.warning(
            "AUTO SCANNER: no CHAT_ID available."
        )
        return

    try:
        # تشغيل الفحص الثقيل خارج Event Loop
        # حتى لا يتجمد Telegram Bot.
        results = await asyncio.to_thread(
            scan_market,
            limit=AUTO_SCAN_LIMIT
        )

    except Exception as exc:
        logger.exception(
            "AUTO SCANNER ERROR: %s",
            exc
        )
        return

    if not results:
        logger.info(
            "AUTO SCANNER: no opportunities found."
        )
        return

    logger.info(
        "AUTO SCANNER: received %d results.",
        len(results)
    )

    # ذاكرة لمنع تكرار نفس التنبيه
    alerted = context.application.bot_data.setdefault(
        "alerted_market_signals",
        {}
    )

    found_market = 0

    for data in results:

        try:
            # لا نرسل WAIT
            if not is_market_entry(data):
                continue

            found_market += 1

            symbol = str(
                data.get("symbol")
                or data.get("pair")
                or data.get("coin")
                or "UNKNOWN"
            ).upper()

            direction = str(
                data.get("direction")
                or data.get("final_direction")
                or data.get("signal")
                or ""
            ).upper()

            # مفتاح فريد للإشارة
            signal_key = f"{symbol}:{direction}"

            # منع إرسال نفس الإشارة كل 30 دقيقة
            if alerted.get(signal_key):
                logger.info(
                    "AUTO SCANNER: duplicate ignored: %s",
                    signal_key
                )
                continue

            # إنشاء التقرير من محرك التحليل نفسه
            report = generate_evidence_report(data)

            # عنوان واضح للتنبيه
            if direction == "LONG":
                header = (
                    "🚨🚨 صفقة LONG جاهزة 🚨🚨\n\n"
                    "🟢 دخول شراء — MARKET\n"
                )
            else:
                header = (
                    "🚨🚨 صفقة SHORT جاهزة 🚨🚨\n\n"
                    "🔴 دخول بيع — MARKET\n"
                )

            message = (
                header
                + f"💎 {symbol}\n\n"
                + report
                + "\n\n"
                "⚠️ هذه الإشارة اجتازت بوابة الدخول "
                "في محرك التحليل."
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

            # تسجيل أن التنبيه أُرسل
            alerted[signal_key] = True

            logger.info(
                "AUTO ALERT SENT: %s",
                signal_key
            )

        except Exception as exc:
            logger.exception(
                "AUTO SCANNER report error: %s",
                exc
            )

    # تنظيف الذاكرة إذا أصبحت كبيرة
    if len(alerted) > 500:
        context.application.bot_data[
            "alerted_market_signals"
        ] = dict(
            list(alerted.items())[-200:]
        )

    if found_market == 0:
        logger.info(
            "AUTO SCANNER: all results were WAIT/NO TRADE."
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
# BOT MAIN
# =========================================================

async def main_bot():

    # بناء التطبيق
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # Handlers
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("scan", scan_command)
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

    # -----------------------------------------------------
    # تشغيل Flask في Thread منفصل
    # -----------------------------------------------------

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    logger.info(
        "Flask server started in background thread."
    )

    # -----------------------------------------------------
    # Telegram initialization
    # -----------------------------------------------------

    await application.initialize()

    # حذف Webhook القديم لمنع Conflict 409
    await application.bot.delete_webhook(
        drop_pending_updates=True
    )

    # -----------------------------------------------------
    # بدء Telegram polling
    # -----------------------------------------------------

    await application.start()

    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

    logger.info(
        "Telegram bot started successfully."
    )

    # -----------------------------------------------------
    # Auto Scanner
    # -----------------------------------------------------

    if application.job_queue is not None:

        application.job_queue.run_repeating(
            auto_market_scanner,
            interval=AUTO_SCAN_INTERVAL,
            first=15,
            name="auto_market_scanner",
        )

        logger.info(
            "AUTO MARKET SCANNER enabled: every %d seconds",
            AUTO_SCAN_INTERVAL
        )

    else:

        logger.error(
            "JobQueue غير متوفر. "
            "تأكد من تثبيت python-telegram-bot[job-queue]"
        )

    # -----------------------------------------------------
    # إبقاء التطبيق يعمل
    # -----------------------------------------------------

    try:

        while True:
            await asyncio.sleep(3600)

    except asyncio.CancelledError:

        logger.info(
            "Bot shutdown requested."
        )

    finally:

        try:
            await application.updater.stop()
        except Exception:
            pass

        try:
            await application.stop()
        except Exception:
            pass

        try:
            await application.shutdown()
        except Exception:
            pass


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    logger.info(
        "Starting BingX AI Scanner v26..."
    )

    asyncio.run(main_bot())

مهم جدًا في Render

أضف Environment Variable:

BOT_TOKEN=توكن_البوت
CHAT_ID=رقم_الشات_الخاص_بك
AUTO_SCAN_INTERVAL=1800
AUTO_SCAN_LIMIT=50

"1800" = كل 30 دقيقة.
ولو أردته كل 15 دقيقة ضع:

AUTO_SCAN_INTERVAL=900

وكذلك في "requirements.txt" تأكد أن مكتبة Telegram مثبتة مع الـ Job Queue:

python-telegram-bot[job-queue]
Flask

والأهم: البوت لن يرسل لك كل العملات التي نتيجتها WAIT. التنبيه التلقائي مصمم لإرسال 🟢 LONG أو 🔴 SHORT فقط عندما ترجع النتيجة كدخول MARKET.
