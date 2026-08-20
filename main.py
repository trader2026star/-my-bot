import os
import telebot
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Online"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.text.lower() in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "🔍 جاري فحص السوق...")
            
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=50&page=1"
            response = requests.get(url, timeout=10)
            
            # التأكد أن الرد هو بيانات JSON صالحة
            data = response.json()
            
            if not isinstance(data, list):
                bot.reply_to(message, "⚠️ السيرفر مشغول حالياً، انتظر ثواني وحاول مجدداً.")
                return
            
            long_msg = "🟢 **فرص LONG (تجميع سيولة):**\n"
            short_msg = "🔴 **فرص SHORT (تشبع):**\n"
            
            for coin in data:
                # نستخدم .get() بأمان هنا
                sym = coin.get('symbol', '???').upper()
                price = coin.get('current_price', 0)
                change = coin.get('price_change_percentage_24h', 0)
                vol = coin.get('total_volume', 0)
                
                if vol > 50000000 and -5 <= change <= 1:
                    long_msg += f"💎 {sym} | السعر: {price}\n"
                elif vol > 70000000 and change >= 7:
                    short_msg += f"💎 {sym} | السعر: {price} ({change:.1f}%)\n"
            
            bot.reply_to(message, f"{long_msg}\n{short_msg}")
            
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ في معالجة البيانات، جرب مرة أخرى بعد قليل.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
