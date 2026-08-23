import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from analysis import get_coin_analysis, scan_market, generate_evidence_report

# إعداد السجلات
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# توكن البوت يتم سحبه تلقائياً من متغيرات البيئة في Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **مرحباً بك في بوت تحليل العملات الرقمية**\n\n"
        "الأوامر المتاحة:\n"
        "• `/scan` - لفحص السوق وجلب أفضل الفرص المتاحة حالياً.\n"
        "• اكتب اسم أي عملة مباشرة (مثل: `BTC` أو `ETH` أو `SOL` أو `TAO`) لتحليلها فوراً."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص عملات السوق وتحليلها... قد يستغرق بعض الوقت.")
    results = scan_market(limit=5)
    
    if not results:
        # إذا لم يجد شروط صارمة، يقوم بعرض تحليل سريع لأشهر العملات كبديل لكي لا يظهر فارغاً
        fallback_coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for symbol in fallback_coins:
            res = get_coin_analysis(symbol)
            if res:
                results.append(res)
                
    if not results:
        await update.message.reply_text("⚠️ لم يتم العثور على فرص مطابقة بالشروط الصارمة حالياً، جرب البحث عن عملة محددة مباشرة.")
        return

    for data in results:
        report = generate_evidence_report(data)
        await update.message.reply_text(report, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if not text:
        return

    # تنظيف النص وإضافة USDT تلقائياً لأي رمز يدخله المستخدم
    symbol = text
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    await update.message.reply_text(f"🔍 جاري تحليل العملة `{symbol}`...")
    data = get_coin_analysis(symbol)
    
    if not data:
        await update.message.reply_text(f"⚠️ لم أجد هذه العملة على Binance أو الرمز غير صحيح: `{text}`. اكتب الرمز مثل `BTC` أو `AVAX`.")
        return

    report = generate_evidence_report(data)
    await update.message.reply_text(report, parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing in environment variables!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Crypto Zero Reversal Bot connected.")
    app.run_polling()

if __name__ == "__main__":
    main()
