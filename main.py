# =========================================================
# main.py - BingX AI Scanner v30.0 (Auto-Scanner & High-Accuracy Pro)
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
    get_top_futures_symbols,
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

# الفحص التلقائي كل 30 دقيقة (1800 ثانية) أو حسب رغبتك
AUTO_SCAN_INTERVAL = int(os.getenv("AUTO_SCAN_INTERVAL", "1800"))

# عدد العملات التي سيتم فحصها في الأمر اليدوي أو التلقائي
AUTO_SCAN_LIMIT = int(os.getenv("AUTO_SCAN_LIMIT", "25"))

# ذاكرة عامة لتتبع آخر اتجاه تم إرساله لكل عملة لمنع التكرار المزعج
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
        "🤖 أهلاً بك في BingX AI Scanner v30.0 (Pro)\n\n"
        "🚀 Auto Market Scanner يعمل تلقائياً في الخلفية.\n\n"
        f"📡 البوت يفحص أعلى العملات سيولة في السوق كل {AUTO_SCAN_INTERVAL // 60} دقيقة.\n\n"
        "🟢 LONG = دخول شراء مؤكد (بتأكيد شمعتين)\n"
        "🔴 SHORT = دخول بيع مؤكد (بتأكيد شمعتين)\n\n"
        "📌 أرسل اسم أي عملة للتحليل اليدوي (مثال: BTC).\n"
        "/scan = فحص يدوي لأفضل الفرص"
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_ACTIVE_CHAT_ID
    if not update.message:
        return

    LAST_ACTIVE_CHAT_ID = update.effective_chat.id

    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures (فلاتر الذكاء الاصطناعي والشمعتين)... ⏳ انتظر النتيجة..."
    )

    try:
        symbols = await asyncio.to_thread(get_top_futures_symbols, limit=AUTO_SCAN_LIMIT)
        results = []
        for sym in symbols:
            d = await asyncio.to_thread(get_coin_analysis, sym, '1h')
            if d and d.get('direction') != 'BLOCKED' and d.get('score', 0) >= 80:
                results.append(d)
    except Exception as exc:
        logger.exception("Manual scanner error: %s", exc)
        await update.message.reply_text("❌ حدث خطأ أثناء فحص السوق.")
        return

    if not results:
        await update.message.reply_text(
            "🟡 لم يتم العثور حالياً على فرص مكتملة الشروط (البوت يحمي المحفظة ضد التذبذب)."
        )
        return

    for data in results[:5]:  # إرسال أفضل 5 فرص كحد أقصى في اليدوي لعدم الإزعاج
        try:
            message = generate_evidence_report(data)
            await update.message.reply_text(message)
            await asyncio.sleep(1)
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

    await update.message.reply_text(f"🔍 جاري تحليل {symbol} وفق أحدث معايير الـ SMC...")

    try:
        data = await asyncio.to_thread(get_coin_analysis, symbol, '1h')
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
# BACKGROUND THREAD AUTO SCANNER (v30.0)
# =========================================================

def start_auto_scan():
    logger.info("BACKGROUND THREAD: Auto Scanner started.")
    time.sleep(15)

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

            symbols = get_top_futures_symbols(limit=AUTO_SCAN_LIMIT)
            for symbol in symbols:
                try:
                    data = get_coin_analysis(symbol, '1h')
                    time.sleep(1.5)

                    if not data:
                        continue

                    current_direction = str(data.get("direction", "")).upper()
                    score = data.get("score", 0)

                    previous_sent_direction = LAST_SENT_SIGNALS.get(symbol)

                    # شروط الإرسال الآلي: يجب أن تكون الفرصة مؤكدة وليست BLOCKED وبنقاط Score عالية (>85)
                    if current_direction == 'BLOCKED' or score < 85:
                        if previous_sent_direction is not None:
                            LAST_SENT_SIGNALS[symbol] = None
                        continue

                    if current_direction == previous_sent_direction:
                        continue

                    report = generate_evidence_report(data)
                    header = "🚨🚨 فرصة تداول مؤكدة (Auto-Scanner) 🚨🚨\n\n"
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
    logger.info("Starting BingX AI Scanner v30.0...")

    # تشغيل الفلاسك والماسح الآلي في الخلفية
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=start_auto_scan, daemon=True).start()

    # تشغيل بوت التليجرام الرئيسي
    try:
        asyncio.run(main_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
