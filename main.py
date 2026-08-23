import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from analysis import get_coin_analysis, scan_market, generate_evidence_report

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "مرحباً بك في بوت تحليل العملات الرقمية\n\n"
        "الأوامر المتاحة:\n"
        "• /scan - لفحص السوق وجلب أفضل الفرص الحالية.\n"
        "• اكتب اسم العملة مباشرة (مثل: BTC أو ETH) لتحليلها فوراً."
    )
    await update.message.reply_text(welcome_text)

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري فحص عملات السوق وتحليلها...")
    results = scan_market(limit=5)
    
    if not results:
        await update.message.reply_text("لم يتم العثور على فرص حالياً، جرب البحث عن عملة محددة.")
        return

    for data in results:
        report = generate_evidence_report(data)
        await update.message.reply_text(report)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if not text:
        return

    symbol = text
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    await update.message.reply_text(f"جاري تحليل العملة {symbol}...")
    data = get_coin_analysis(symbol)
    
    if not data:
        await update.message.reply_text(f"لم أجد هذه العملة أو الرمز غير صحيح: {text}. تأكد من كتابة الرمز مثل BTC.")
        return

    report = generate_evidence_report(data)
    await update.message.reply_text(report)

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Bot started successfully.")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
