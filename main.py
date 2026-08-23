import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from analysis import scan_market, generate_evidence_report

# 1. إعداد خادم الويب البسيط لإرضاء بورتات Render المجانية
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# تشغيل الخادم في الخلفية بالتوازي مع البوت
threading.Thread(target=run_http_server, daemon=True).start()

# 2. إعدادات بوت التيليجرام
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! بوت التحليل الفني يعمل بكفاءة. استخدم الأمر /scan لفحص السوق وإرسال التقارير."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص السوق وتحليل العمليات، أرجو الانتظار قليلاً...")
    
    try:
        results = scan_market(limit=10)
        
        if not results:
            await update.message.reply_text("لم يتم العثور على فرص مطابقة بالشروط الحالية.")
            return

        for res in results:
            report_text = generate_evidence_report(res)
            await update.message.reply_text(report_text, parse_mode="Markdown")
            
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء الفحص: {str(e)}")

def main():
    if not TELEGRAM_TOKEN:
        print("تحذير: يرجى تعيين متغير البيئة TELEGRAM_TOKEN.")

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))

    print("البوت يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
