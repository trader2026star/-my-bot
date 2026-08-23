import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from analysis import scan_market, generate_evidence_report

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

# تشغيل الخادم فوراً في الخلفية
threading.Thread(target=run_server, daemon=True).start()

# =========================================================
# تشغيل بوت التيليجرام والأوامر
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! بوت التحليل الفني يعمل بكفاءة.\nاستخدم الأمر /scan لفحص السوق وإرسال التقارير."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص السوق وتحليل العمليات، أرجو الانتظار قليلاً...")
    
    try:
        # استدعاء دالة المسح من ملف analysis.py
        results = scan_market(limit=5)
        
        if not results:
            await update.message.reply_text("لم يتم العثور على فرص مطابقة بالشروط الحالية.")
            return

        for res in results:
            # توليد التقرير المنسق من ملف analysis.py
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

    print("البوت يعمل الآن بنجاح...")
    application.run_polling()

if __name__ == "__main__":
    main()
