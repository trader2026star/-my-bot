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
    normalize_symbol,
    get_current_price,
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
        "• Order Block + Retest\n"
        "• BOS + Market Structure\n"
        "• السيولة والحجم\n"
        "• RSI + EMA\n"
        "• القاع والتجميع\n"
        "• Support / Resistance\n"
        "• ATR\n"
        "• Entry / SL / TP\n\n"
        "🛡️ ORDER BLOCK هو المحرك الأساسي."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "🔍 جاري فحص BingX Futures...\n\n"
        "🏦 ORDER BLOCK = المحرك الأساسي\n"
        "📡 الأسعار تُسحب مباشرة من BingX Futures\n"
        "🧠 1D + 4H Context | 1H Primary OB | 30m + 15m Confirmation\n"
        "💧 Liquidity + Volume + BOS\n\n"
        "⏳ انتظر النتيجة..."
    )
    try:
        results = scan_market(limit=5)
    except Exception as exc:
        logger.exception("Scanner error: %s", exc)
        await update.message.reply_text(
            "❌ حدث خطأ أثناء فحص السوق.\n\nراجع Logs وحاول مرة أخرى."
        )
        return

    if not results:
        await update.message.reply_text(
            "🟡 انتهى الفحص.\n\n"
            "لم يتم العثور حالياً على فرصة قوية بالشروط النهائية.\n\n"
            "🛡️ البوت فضّل الانتظار بدلاً من إعطاء صفقة ضعيفة."
        )
        return

    await update.message.reply_text(
        f"✅ انتهى الفحص.\n\n"
        f"🎯 تم العثور على {len(results)} فرص.\n"
        f"💰 كل نتيجة تتضمن السعر الحالي من BingX.\n"
        f"🏦 سيتم إرسال أفضل مناطق Order Block."
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

    # Fetch the price before the progress message so the user sees that the
    # scanner has real market data, not just a symbol name.
    price = get_current_price(symbol, True)
    price_text = f"💰 السعر الحالي: {price}\n" if price is not None else "💰 السعر الحالي: جاري جلبه من BingX...\n"

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
    # Remove any webhook before starting long polling.
    application.bot.delete_webhook(drop_pending_updates=True)
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
