import os
import telebot
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)
@app.route('/')
def home(): return "Trend Hunter Active"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.text.lower() in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "🔍 جاري مسح السوق بحثاً عن السيولة العالية...")
            
            # استخدام API عام ومفتوح لا يحظر المواقع
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=100&page=1"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=15)
            data = response.json()
            
            long_list = []
            short_list = []
            
            for coin in data:
                price = coin.get('current_price', 0)
                change = coin.get('price_change_percentage_24h', 0)
                vol = coin.get('total_volume', 0)
                sym = coin.get('symbol', '').upper()
                
                # منطق صيد الترند:
                # 1. LONG: سعر هابط أو متذبذب بسيط (-5% إلى +1%) مع سيولة ضخمة جداً (تجميع)
                if -5 <= change <= 1 and vol > 50000000:
                    long_list.append(f"{sym}: السعر {price} | سيولة {vol/1000000:.1f}M")
                
                # 2. SHORT: عملة صعدت بقوة (+7% فأكثر) مع سيولة عالية (تشبع بيعي متوقع)
                elif change >= 7 and vol > 70000000:
                    short_list.append(f"{sym}: السعر {price} | تغير {change:.1f}%")
            
            result = "🎯 **تقرير صياد السيولة والترند:**\n\n🟢 **تجميع (LONG - سيولة قوية في القاع):**\n"
            result += "\n".join(long_list[:5]) if long_list else "لا توجد فرص تجميع حالياً."
            
            result += "\n\n🔴 **تشبع (SHORT - بداية انعكاس):**\n"
            result += "\n".join(short_list[:5]) if short_list else "لا توجد فرص تصحيح حالياً."
            
            bot.reply_to(message, result)
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ: {e}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
