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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

app = Flask(__name__)

@app.route("/")
def home():
    return "BingX AI Scanner is running."

@app.route("/health")
def health():
    return "OK"

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "🤖 أهلاً بك في BingX AI Scanner\n\n"
        "📌 أرسل اسم العملة للتحليل:\n"
        "BTC\nETH\nSOL\nXRP\n\n"
        "أو أي زوج USDT موجود على BingX Futures.\n\n"
        "📌 أمر الفحص الكامل:\n"
        "/scan\n\n"
        "🔎 النظام يعتمد على:\n"
        "• 1D = الاتجاه العام\n"
        "• 4H = الاتجاه الرئيسي\n"
        "• 1H = بوابة الدخول\n"
        "• 30m + 15m = تأكيد إضافي\n"
        "• BOS + Market Structure\n"
        "• السيولة والحجم\n"
        "• RSI + EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"
        "🛡️ التأكيدات موزونة، وليس شرطاً أن تكون كلها موجودة."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"
        "🧠 شروط البحث:\n"
        "• 1D + 4H اتجاه واضح\n"
        "• 1H بوابة الدخول\n"
        "• 30m + 15m تأكيد\n"
        "• BOS / Market Structure\n"
        "• السيولة والحجم\n"
        "• عدم مطاردة القاع أو البامب\n\n"
        "⏳ انتظر قليلاً..."
    )
    try:
        results = scan_market(limit=5)
    except Exception as exc:
        logger.exception("Scanner error: %s", exc)
        await update.message.reply_text("❌ حدث خطأ أثناء فحص السوق.\n\nراجع Logs وحاول مرة أخرى.")
        return

    if not results:
        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم يتم العثور حالياً على صفقة قوية بالشروط النهائية.\n\n"
            "🛡️ البوت فضّل الانتظار بدلاً من إعطاء صفقة ضعيفة."
        )
        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص.\n"
        f"📊 سيتم إرسال الأفضل."
    )
    for data in results:
        try:
            await update.message.reply_text(generate_evidence_report(data))
        except Exception as exc:
            logger.exception("Report error: %s", exc)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return
    symbol = normalize_symbol(text)
    await update.message.reply_text(
        f"🔍 جاري تحليل {symbol}...\n\n"
        "📊 1D = الاتجاه العام\n"
        "📊 4H = الاتجاه الرئيسي\n"
        "⏱️ 1H = بوابة الدخول\n"
        "🧠 جاري فحص 30m + 15m + BOS + السيولة + الحجم..."
    )
    try:
        data = get_coin_analysis(symbol)
    except Exception as exc:
        logger.exception("Coin analysis error for %s: %s", symbol, exc)
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
        logger.exception("Report error for %s: %s", symbol, exc)
        await update.message.reply_text("❌ حدث خطأ أثناء إنشاء التقرير.")

async def error_handler(update, context):
    logger.error("Telegram error: %s", context.error)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    print("Telegram bot is starting...")
    print("Flask server is starting...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
