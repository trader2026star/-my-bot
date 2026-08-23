import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from analysis import scan_market, generate_evidence_report, get_coin_analysis

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, format, *args): pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN") or ""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! 🤖\n\nاستخدم /scan لفحص جميع عملات USDT، أو اكتب اسم العملة مباشرة مثل BTC أو AVAX.")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص جميع عملات USDT وتحليلها... قد يستغرق بعض الوقت.")
    try:
        results = scan_market(limit=5)
        if not results:
            await update.message.reply_text("⚠️ لم يتم العثور على فرص مطابقة للشروط حالياً."); return
        await update.message.reply_text(f"Crypto Zero Reversal:\n✅ انتهى الفحص\nوجدت فرص مطابقة للشروط.\nتم إرسال أفضل {len(results)} فرص.")
        for res in results:
            await update.message.reply_text(generate_evidence_report(res), parse_mode="Markdown")
    except Exception as e:
        print(f"SCAN ERROR: {e}"); await update.message.reply_text(f"⚠️ حدث خطأ أثناء الفحص: {e}")

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ اكتب رمز العملة هكذا: /coin BTC"); return
    try:
        data = get_coin_analysis(context.args[0])
        if not data:
            await update.message.reply_text(f"⚠️ لم أجد العملة `{context.args[0].upper()}` على Binance.", parse_mode="Markdown"); return
        await update.message.reply_text(generate_evidence_report(data), parse_mode="Markdown")
    except Exception as e:
        print(f"COIN ERROR: {e}"); await update.message.reply_text(f"⚠️ حدث خطأ أثناء تحليل العملة: {e}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text or text.startswith("/") or len(text) > 20 or " " in text: return
    try:
        data = get_coin_analysis(text)
        if data:
            await update.message.reply_text(generate_evidence_report(data), parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ لم أجد هذه العملة على Binance. اكتب الرمز مثل BTC أو AVAX")
    except Exception as e:
        print(f"TEXT ERROR: {e}"); await update.message.reply_text(f"⚠️ حدث خطأ أثناء تحليل العملة: {e}")

def main():
    if not TELEGRAM_TOKEN:
        print("خطأ: ضع TELEGRAM_TOKEN أو BOT_TOKEN في Environment Variables."); return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    print("Crypto Zero Reversal Bot connected.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
