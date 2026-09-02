# =========================================================
# main.py - BingX AI Scanner v26
# Flask + Standalone Background Thread Auto Scanner
# =========================================================

import os
import time
import logging
import threading
import asyncio

from flask import Flask
from telegram import Update, Bot
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
# ENVIRONMENT & TARGETS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    logger.error("BOT_TOKEN غير موجود في Environment Variables")

CHAT_ID_RAW = os.getenv("CHAT_ID")
CHAT_ID = None

if CHAT_ID_RAW:
    try:
        CHAT_ID = int(CHAT_ID_RAW)
    except ValueError:
        logger.warning("CHAT_ID يجب أن يكون رقمًا صحيحًا، تم تجاهله.")

if not CHAT_ID:
    logger.warning("تحذير: CHAT_ID غير معرف. التنبيهات التلقائية لن تُرسل حتى يتفاعل مستخدم مع البوت.")

# الفحص كل 15 دقيقة (900 ثانية) افتراضياً
AUTO_SCAN_INTERVAL = int(os.getenv("AUTO_SCAN_INTERVAL", "900"))

# عدد العملات التي سيتم فحصها في الأمر اليدوي
AUTO_SCAN_LIMIT = int(os.getenv("AUTO_SCAN_LIMIT", "50"))

# قائمة أهم 20 عملة للفحص التلقائي (Auto Scanner)
TARGET_COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "LINK", "DOGE", 
    "MATIC", "AVAX", "DOT", "LTC", "SHIB", "TRX", "UNI", "ATOM", 
    "FTM", "NEAR", "OP", "SUI"
]

# ذاكرة عامة لتتبع آخر اتجاه تم إرساله لكل عملة
LAST_SENT_SIGNALS = {}
LAST_ACTIVE_CHAT_ID = CHAT_ID


# =========================================================
# FLASK SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is Running Live!"


@app.route("/health")
def health():
    return "OK"


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# TELEGRAM HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"
        "🚀 Auto Market Scanner يعمل تلقائياً في الخلفية.\n\n"
        f"📡 البوت يفحص أهم 20 عملة في السوق كل {AUTO_SCAN_INTERVAL // 60} دقيقة.\n\n"
        "🟢 LONG = دخول شراء مؤكد\n"
        "🔴 SHORT = دخول بيع مؤكد\n\n"
        "📌 أرسل اسم أي عملة للتحليل اليدوي (مثال: BTC).\n"
        "/scan = فحص يدوي للسوق"
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n⏳ انتظر النتيجة..."
    )

    try:
        results = await asyncio.to_thread(scan_market, limit=AUTO_SCAN_LIMIT)
    except Exception as exc:
        logger.exception("Manual scanner error: %s", exc)
        await update.message.reply_text("❌ حدث خطأ أثناء فحص السوق.")
        return

    if not results:
        await update.message.reply_text(
            "🟡 لم يتم العثور حالياً على فرصة MARKET مكتملة."
        )
        return

    for data in results:
        try:
            message = generate_evidence_report(data)
            await update.message.reply_text(message)
        except Exception as exc:
            logger.exception("Manual report error: %s", exc)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id
    symbol = normalize_symbol(text)

    await update.message.reply_text(f"🔍 جاري تحليل {symbol}...")

    try:
        data = await asyncio.to_thread(get_coin_analysis, symbol)
    except Exception as exc:
        logger.exception("Coin analysis error for %s", symbol)
        await update.message.reply_text(f"❌ حدث خطأ أثناء تحليل {symbol}.")
        return

    if not data:
        await update.message.reply_text(f"❌ لم أستطع تحليل {symbol} حالياً.")
        return

    try:
        await update.message.reply_text(generate_evidence_report(data))
    except Exception as exc:
        logger.exception("Report error for %s", symbol)
        await update.message.reply_text("❌ حدث خطأ أثناء إنشاء التقرير.")


# =========================================================
# MARKET STATE DETECTION
# =========================================================

def is_market_entry(data):
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

    if state not in {"MARKET", "ENTRY", "READY", "STRONG_ENTRY", "IMMEDIATE_ENTRY"}:
        return False

    if direction not in {"LONG", "SHORT"}:
        return False

    return True


# =========================================================
# BACKGROUND THREAD AUTO SCANNER
# =========================================================

def start_auto_scan():
    logger.info("BACKGROUND THREAD: Auto Scanner started.")
    time.sleep(25)

    if not TOKEN:
        logger.error("Cannot start Auto Scanner: BOT_TOKEN is missing.")
        return

    bot = Bot(token=TOKEN)

    while True:
        try:
            target_chat_id = CHAT_ID or LAST_ACTIVE_CHAT_ID

            if not target_chat_id:
                logger.info("AUTO SCANNER: Waiting for a chat_id (Send /start to bot)...")
                time.sleep(AUTO_SCAN_INTERVAL)
                continue

            for symbol in TARGET_COINS:
                try:
                    data = get_coin_analysis(symbol)
                    time.sleep(2)

                    if not data:
                        continue

                    current_direction = str(
                        data.get("direction")
                        or data.get("final_direction")
                        or data.get("signal")
                        or ""
                    ).upper()

                    is_market = is_market_entry(data)
                    previous_sent_direction = LAST_SENT_SIGNALS.get(symbol)

                    if not is_market:
                        if previous_sent_direction is not None:
                            LAST_SENT_SIGNALS[symbol] = None
                        continue

                    if current_direction == previous_sent_direction:
                        continue

                    report = generate_evidence_report(data)
                    header = "🚨🚨 صفقة جديدة 🚨🚨\n\n"
                    message = header + f"💎 {symbol}\n\n" + report

                    asyncio.run(bot.send_message(chat_id=target_chat_id, text=message))
                    LAST_SENT_SIGNALS[symbol] = current_direction
                    logger.info("AUTO ALERT SENT: %s -> %s", symbol, current_direction)

                except Exception as coin_exc:
                    logger.exception("AUTO SCANNER error for %s: %s", symbol, coin_exc)

        except Exception as loop_exc:
            logger.exception("AUTO SCANNER CRITICAL ERROR: %s", loop_exc)

        time.sleep(AUTO_SCAN_INTERVAL)


# =========================================================
# BOT MAIN (TELEGRAM POLLING)
# =========================================================

async def main_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    logger.info("Telegram bot started successfully with standard polling.")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception:
            pass


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    logger.info("Starting BingX AI Scanner v26...")

    # تشغيل الفلاسك والماسح الآلي في الخلفية
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=start_auto_scan, daemon=True).start()

    # تشغيل بوت التليجرام الرئيسي
    try:
        asyncio.run(main_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
