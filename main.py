import os
import telebot
import ccxt
from flask import Flask
from threading import Thread

# تشغيل سيرفر Flask عشان رندر يفضل مفعل البوت
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Active!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# إعدادات البوت
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً يا محمد! أرسل **scan** لبدء رصد السوق.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.upper().strip()
    
    if text in ["SCAN", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري الفحص المباشر من بينانس...")
            
            # جلب البيانات من بينانس مباشرة بدون وسيط
            tickers = exchange.fetch_tickers()
            
            accumulation = []
            exhaustion = []
            
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol:
                    price = ticker.get('last')
                    change = ticker.get('percentage')
                    volume = ticker.get('quoteVolume')
                    
                    if price and change and volume:
                        # 1. تجميع (LONG): عملة في القاع وجمعت سيولة
                        if -10 <= change <= 2 and volume > 5000000:
                            accumulation.append((symbol, price, change, volume))
                        # 2. تشبع (SHORT): عملة طارت وهتهبط
                        elif change > 8 and volume > 10000000:
                            exhaustion.append((symbol, price, change, volume))
            
            # ترتيب النتائج بالأكثر سيولة
            accumulation.sort(key=lambda x: x[3], reverse=True)
            exhaustion.sort(key=lambda x: x[3], reverse=True)
            
            reply = "🎯 **تقرير صياد الترند (بينانس مباشر):**\n\n🟢 **تجميع / LONG (بداية الصعود):**\n"
            for s, p, c, v in accumulation[:3]:
                reply += f"💎 `{s}` | السعر: `{p}` | التغير: `{c:.2f}%`\n"
            
            reply += "\n🔴 **تشبع / SHORT (بداية الهبوط):**\n"
            for s, p, c, v in exhaustion[:3]:
                reply += f"💎 `{s}` | السعر: `{p}` | التغير: `{c:.2f}%`\n"
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ: {e}")

if __name__ == "__main__":
    # تشغيل السيرفر
    Thread(target=run_flask).start()
    # تنظيف الجلسة القديمة لمنع خطأ 409
    try:
        bot.remove_webhook()
    except:
        pass
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)
