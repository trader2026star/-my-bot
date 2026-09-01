# =========================================================
# main.py - BingX AI Scanner v26
# Flask + Telegram Async Polling
# AUTO MARKET SCANNER (Dynamic Signal Reset)
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
# ENVIRONMENT & TARGETS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

# ضع Chat ID الخاص بك في Render
CHAT_ID_RAW = os.getenv("CHAT_ID")

if not CHAT_ID_RAW:
    logger.warning("CHAT_ID غير موجود. التنبيهات التلقائية لن يتم إرسالها.")

try:
    CHAT_ID = int(CHAT_ID_RAW) if CHAT_ID_RAW else None
except ValueError:
    raise RuntimeError("CHAT_ID يجب أن يكون رقمًا صحيحًا")

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # حفظ Chat ID تلقائيًا في الذاكرة أثناء التشغيل
    context.application.bot_data["last_chat_id"] = update.effective_chat.id

    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"
        "🚀 Auto Market Scanner يعمل تلقائياً في الخلفية (Dynamic Signal Reset).\n\n"
        "📡 البوت يفحص أهم 20 عملة في السوق كل "
        f"{AUTO_SCAN_INTERVAL // 60} دقيقة.\n\n"
        "🟢 LONG = دخول شراء مؤكد 100%\n"
        "🔴 SHORT = دخول بيع مؤكد 100%\n"
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

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        results = await asyncio.to_thread(scan_market, limit=AUTO_SCAN_LIMIT)

    except Exception as exc:
        logger.exception("Manual scanner error: %s", exc)

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

    sent = 0
    for data in results:
        try:
            message = generate_evidence_report(data)
            await update.message.reply_text(message)
            sent += 1
        except Exception as exc:
            logger.exception("Manual report error: %s", exc)

    if sent == 0:
        await update.message.reply_text(
            "🟡 لم يتم العثور على صفقة MARKET مكتملة."
        )


# =========================================================
# MANUAL COIN ANALYSIS
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    # حفظ Chat ID لاستخدامه في التنبيهات التلقائية
    context.application.bot_data["last_chat_id"] = update.effective_chat.id

    symbol = normalize_symbol(text)

    try:
        price = get_current_price(symbol, True)
    except Exception:
        price = None

    price_text = f"💰 السعر الحالي: {price}\n" if price is not None else "💰 السعر الحالي: جاري جلبه من BingX...\n"

    await update.message.reply_text(
        f"🔍 جاري تحليل {symbol}...\n\n"
        f"{price_text}"
        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📊 1D = Context\n"
        "📊 4H = MTF Order Block\n"
        "⏱️ 1H = Primary Entry Zone\n"
        "⏱️ 30m + 15m = Confirmation\n\n"
        "⏳ انتظر النتيجة..."
    )

    try:
        data = await asyncio.to_thread(get_coin_analysis, symbol)
    except Exception as exc:
        logger.exception("Coin analysis error for %s", symbol)
        await update.message.reply_text(
            f"❌ حدث خطأ أثناء تحليل {symbol}.\n\nحاول مرة أخرى بعد قليل."
        )
        return

    if not data:
        await update.message.reply_text(
            f"❌ لم أستطع تحليل {symbol} حالياً.\n\n"
            "تأكد أن الزوج موجود على BingX Futures وأنه USDT."
        )
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
    """ يتحقق أن نتيجة analysis.py تعتبر صفقة دخول فورية (MARKET) فقط """
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
# AUTO MARKET SCANNER (DYNAMIC SIGNAL RESET)
# =========================================================

async def auto_market_scanner(context: ContextTypes.DEFAULT_TYPE):
    """
    فحص تلقائي للسوق في الخلفية لأهم 20 عملة مع دعم Dynamic Signal Reset.
    إذا استمرت نفس الإشارة يتم تجاهلها، وإذا تغيرت الحالة أو الاتجاه، 
    يتم مسح الذاكرة وإرسال التنبيه الجديد فوراً.
    """
    logger.info("AUTO SCANNER: starting market scan for Top 20 coins...")

    chat_id = CHAT_ID
    if not chat_id:
        chat_id = context.application.bot_data.get("last_chat_id")

    if not chat_id:
        logger.warning("AUTO SCANNER: no CHAT_ID available. Cannot send alerts.")
        return

    # ذاكرة لتتبع آخر اتجاه تم إرساله لكل عملة لتنفيذ Dynamic Signal Reset
    last_sent_signals = context.application.bot_data.setdefault("last_sent_signals", {})
    found_market = 0

    for symbol in TARGET_COINS:
        try:
            data = await asyncio.to_thread(get_coin_analysis, symbol)
            await asyncio.sleep(2)  # فاصل زمني حماية للـ API

            if not data:
                continue

            # استخراج الاتجاه الحالي من النتيجة
            current_direction = str(
                data.get("direction")
                or data.get("final_direction")
                or data.get("signal")
                or ""
            ).upper()

            is_market = is_market_entry(data)

            # استرجاع آخر إشارة تم إرسالها لهذه العملة مسبقاً
            previous_sent_direction = last_sent_signals.get(symbol)

            # المنطق الذكي (Dynamic Signal Reset):
            # 1. إذا لم تعد الصفقة MARKET (أصبحت WAIT مثلاً)، نقوم بمسح الذاكرة لهذه العملة لتصبح جاهزة لاستقبال أي صفقة جديدة مستقبلاً.
            if not is_market:
                if previous_sent_direction is not None:
                    logger.info("AUTO SCANNER: Coin %s exited market state. Resetting signal memory.", symbol)
                    last_sent_signals[symbol] = None
                continue

            # 2. إذا كانت الصفقة MARKET، لكن اتجاهها الحالي يطابق تماماً آخر اتجاه تم إرساله مسبقاً، نتجاهلها لعدم التكرار المزعج.
            if current_direction == previous_sent_direction:
                logger.info("AUTO SCANNER: Duplicate signal ignored for %s (%s).", symbol, current_direction)
                continue

            # 3. إذا وصلنا إلى هنا، فهذا يعني أن هناك فرصة MARKET جديدة كلياً (أو تغيرت من LONG إلى SHORT أو العكس، أو بدأت دورة جديدة):
            found_market += 1

            report = generate_evidence_report(data)

            if current_direction == "LONG":
                header = "🚨🚨 صفقة LONG جديدة جاهزة 🚨🚨\n\n🟢 دخول شراء — MARKET\n"
            else:
                header = "🚨🚨 صفقة SHORT جديدة جاهزة 🚨🚨\n\n🔴 دخول بيع — MARKET\n"

            message = (
                header
                + f"💎 {symbol}\n\n"
                + report
                + "\n\n⚠️ تم اجتياز بوابة (v26 Hard Gate) بنجاح - Dynamic Signal Reset"
            )

            await context.bot.send_message(chat_id=chat_id, text=message)
            
            # تحديث الذاكرة بآخر اتجاه تم إرساله لهذه العملة
            last_sent_signals[symbol] = current_direction
            logger.info("AUTO ALERT SENT & MEMORY UPDATED: %s -> %s", symbol, current_direction)

        except Exception as exc:
            logger.exception("AUTO SCANNER error for %s: %s", symbol, exc)

    # تنظيف الذاكرة إذا تجاوزت الحد المسموح
    if len(last_sent_signals) > 500:
        context.application.bot_data["last_sent_signals"] = {
            k: last_sent_signals[k] for k in list(last_sent_signals.keys())[-200:]
        }

    if found_market == 0:
        logger.info("AUTO SCANNER: Completed 20 coins. No new market transitions found.")


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error("Telegram error: %s", context.error)


# =========================================================
# BOT MAIN
# =========================================================

async def main_bot():
    # بناء التطبيق
    application = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # -----------------------------------------------------
    # تشغيل Flask في Thread منفصل لضمان عمل السيرفر 24/7
    # -----------------------------------------------------
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask server started in background thread.")

    # -----------------------------------------------------
    # Telegram initialization
    # -----------------------------------------------------
    await application.initialize()

    # حذف Webhook القديم لمنع Conflict 409
    await application.bot.delete_webhook(drop_pending_updates=True)

    # -----------------------------------------------------
    # بدء Telegram polling
    # -----------------------------------------------------
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    logger.info("Telegram bot started successfully.")

    # -----------------------------------------------------
    # Auto Scanner Job
    # -----------------------------------------------------
    if application.job_queue is not None:
        application.job_queue.run_repeating(
            auto_market_scanner,
            interval=AUTO_SCAN_INTERVAL,
            first=15,  # يبدأ الفحص الأول بعد 15 ثانية من الإقلاع
            name="auto_market_scanner_20_coins",
        )
        logger.info(
            "AUTO MARKET SCANNER enabled: scanning top 20 coins every %d seconds",
            AUTO_SCAN_INTERVAL
        )
    else:
        logger.error(
            "JobQueue غير متوفر. تأكد من تثبيت python-telegram-bot[job-queue]"
        )

    # -----------------------------------------------------
    # إبقاء التطبيق يعمل
    # -----------------------------------------------------
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Bot shutdown requested.")
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
    logger.info("Starting BingX AI Scanner v26...")
    asyncio.run(main_bot())
