import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from analysis import scan_market, generate_evidence_report, get_coin_analysis

# =========================================================
# خادم ويب سريع لإرضاء فحص البورتات في Render المجاني
# =========================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# =========================================================
# تشغيل بوت التيليجرام والأوامر
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! بوت التحليل الفني يعمل بكفاءة.\nاستخدم الأمر /scan لفحص السوق أو اكتب /coin ثم اسم العملة (مثل /coin BTC)."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص السوق وتحليل العمليات، أرجو الانتظار قليلاً...")
    
    try:
        results = scan_market(limit=3)
        
        if not results:
            await update.message.reply_text("لم يتم العثور على فرص مطابقة بالشروط الحالية.")
            return

        for res in results:
            report_text = generate_evidence_report(res)
            await update.message.reply_text(report_text, parse_mode="Markdown")
            
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء الفحص: {str(e)}")

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        coin_name = context.args[0]
        coin_data = get_coin_analysis(coin_name)
        if coin_data:
            report_text = generate_evidence_report(coin_data)
            await update.message.reply_text(report_text, parse_mode="Markdown")
            return
    await update.message.reply_text("⚠️ يرجى كتابة اسم العملة بعد الأمر بشكل صحيح، مثال: `/coin BTC`", parse_mode="Markdown")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) <= 10 and not text.startswith('/'):
        coin_data = get_coin_analysis(text)
        if coin_data:
            report_text = generate_evidence_report(coin_data)
            await update.message.reply_text(report_text, parse_mode="Markdown")

def main():
    if not TELEGRAM_TOKEN:
        print("تحذير: يرجى تعيين متغير البيئة TELEGRAM_TOKEN.")

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("coin", coin_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("البوت يعمل الآن بنجاح...")
    # إضافة drop_pending_updates لتجاهل أي تعارض قديم في الاتصال
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
