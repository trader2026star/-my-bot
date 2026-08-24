import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from analysis import scan_market, get_coin_analysis, generate_evidence_report

# إعداد السجل (Logs) لرؤية الأخطاء إن وجدت بوضوح
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("BOT_TOKEN", "8523562412:AAGKKEXKbedyLqmd6hAEnxJdJVFgMiVxDxA")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 أهلاً بك يا غالي في بوت تداول العملات الرقمية (Binance Futures).\n\n"
        "الأوامر المتاحة:\n"
        "• أرسل اسم أي عملة مثل: `BTC` أو `FLOW` أو `SOL` للحصول على التحليل الفني.\n"
        "• أرسل الأمر `/scan` لفحص السوق والبحث عن الفرص."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص سوق Binance Futures بالكامل والبحث عن أفضل الفرص...")
    results = scan_market(limit=3)
    if not results:
        await update.message.reply_text("🟡 انتهى الفحص.\nلم أجد حالياً فرص تتجاوز شروط التأكيد القوية.")
        return
    
    for data in results:
        report = generate_evidence_report(data)
        await update.message.reply_text(report)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return
    
    symbol = text.strip()
    if symbol.startswith("/"):
        return
        
    await update.message.reply_text(f"🔍 جاري تحليل العملة {symbol.upper()}USDT...")
    data = get_coin_analysis(symbol)
    
    if not data:
        await update.message.reply_text(f"❌ لم أجد زوج {symbol.upper()}USDT على Binance Futures أو تعذر جلب بياناته حالياً.")
        return
        
    report = generate_evidence_report(data)
    await update.message.reply_text(report)

def main():
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
