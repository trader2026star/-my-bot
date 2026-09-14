# =========================================================
# main.py - BingX AI Scanner v50.3 (Auto-Scanner & High-Accuracy Pro)
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
    get_futures_symbols,
    get_coin_analysis,
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

# الفحص التلقائي كل 30 دقيقة (1800 ثانية)
AUTO_SCAN_INTERVAL = int(os.getenv("AUTO_SCAN_INTERVAL", "1800"))

# عدد العملات التي سيتم فحصها
AUTO_SCAN_LIMIT = int(os.getenv("AUTO_SCAN_LIMIT", "20"))

# ذاكرة لتتبع العملات التي تم إرسال تنبيه لها لمنع التكرار المزعج
LAST_SENT_SIGNALS = {}
LAST_ACTIVE_CHAT_ID = CHAT_ID


# =========================================================
# FLASK SERVER (لحماية Render من السبات)
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is Alive and Scanning 24/7 (v50.3)!"


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
        "🤖 أهلاً بك في BingX Institutional SMC v50.3\n\n"
        "🚀 Auto Market Scanner يعمل تلقائياً في الخلفية على مدار الساعة.\n\n"
        f"📡 البوت يفحص أعلى العملات سيولة كل {AUTO_SCAN_INTERVAL // 60} دقيقة.\n\n"
        "📌 أرسل اسم أي عملة للتحليل الفوري (مثال: BTC أو ETH).\n"
        "/scan = فحص يدوي لأفضل الفرص المتاحة حالياً"
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id

    await update.message.reply_text(
        "🔍 جاري فحص سيولة BingX Futures وتطبيق فلاتر الـ SMC الصارمة... ⏳ انتظر قليلاً..."
    )

    try:
        symbols_set = await asyncio.to_thread(get_futures_symbols, False)
        symbols = list(symbols_set)[:AUTO_SCAN_LIMIT]
        sent_count = 0

        for sym in symbols:
            report = await asyncio.to_thread(get_coin_analysis, sym, '1h')
            if report and isinstance(report, str) and "TRADE CANCELLED" not in report and "EXCEPTION" not in report:
                await update.message.reply_text(report)
                sent_count += 1
                await asyncio.sleep(1.5)
                if sent_count >= 3:
                    break
        
        if sent_count == 0:
            await update.message.reply_text(
                "🟡 لم يتم العثور حالياً على فرص مطابقة للشروط الصارمة (البوت يحمي المحفظة ضد التذبذب)."
            )

    except Exception as exc:
        logger.exception("Manual scanner error: %s", exc)
        await update.message.reply_text("❌ حدث خطأ أثناء فحص السوق.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id
    symbol = normalize_symbol(text)

    await update.message.reply_text(f"🔍 جاري تحليل العملة `{symbol}` وفق أحدث معايير الـ SMC والمستويات المؤسسية...")

    try:
        report = await asyncio.to_thread(get_coin_analysis, symbol, '1h')
    except Exception as exc:
        logger.exception("Coin analysis error for %s", symbol)
        await update.message.reply_text(f"❌ حدث خطأ أثناء تحليل {symbol}.")
        return

    if not report:
        await update.message.reply_text(f"❌ لم أستطع تحليل {symbol} حالياً.")
        return

    try:
        await update.message.reply_text(report)
    except Exception as exc:
        logger.exception("Report error for %s", symbol)
        await update.message.reply_text("❌ حدث خطأ أثناء إرسال التقرير.")


# =========================================================
# BACKGROUND THREAD AUTO SCANNER (v50.3)
# =========================================================

def start_auto_scan():
    logger.info("BACKGROUND THREAD: Auto Scanner started.")
    time.sleep(20)

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

            symbols_set = get_futures_symbols(False)
            symbols = list(symbols_set)[:AUTO_SCAN_LIMIT]

            for symbol in symbols:
                try:
                    report = get_coin_analysis(symbol, '1h')
                    time.sleep(1.5)

                    if not report or not isinstance(report, str):
                        continue

                    if "TRADE CANCELLED" in report or "EXCEPTION" in report or "DATA ERROR" in report:
                        continue

                    current_direction = "LONG" if "MARKET LONG" in report else ("SHORT" if "MARKET SHORT" in report else "UNKNOWN")
                    if current_direction == "UNKNOWN":
                        continue

                    previous_sent = LAST_SENT_SIGNALS.get(symbol)
                    if current_direction == previous_sent:
                        continue

                    header = "🚨🚨 فرصة تداول مؤسسية مؤكدة (Auto-Scanner) 🚨🚨\n\n"
                    message = header + report

                    asyncio.run(bot.send_message(chat_id=target_chat_id, text=message))
                    LAST_SENT_SIGNALS[symbol] = current_direction
                    logger.info("AUTO ALERT SENT: %s -> %s", symbol, current_direction)
                    time.sleep(3)

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
    logger.info("Starting BingX AI Scanner v50.3...")

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=start_auto_scan, daemon=True).start()

    try:
        asyncio.run(main_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
