import os
import telebot
import requests
from flask import Flask
from threading import Thread

# تشغيل سيرفر Flask عشان Render يضل شغال
app = Flask(__name__)
@app.route('/')
def home(): return "Trend Hunter Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.upper().strip()
    
    if text in ["SCAN", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "🔍 جاري رصد السيولة وصيد العملات التي تبدأ الترند (صعوداً وهبوطاً)...")
            
            # جلب أسواق العملات مع السيولة والتغيرات
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=25&page=1&sparkline=false"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if not data or not isinstance(data, list):
                bot.reply_to(message, "⚠️ عذراً، لم نتمكن من جلب بيانات السوق حالياً.")
                return
                
            long_candidates = []
            short_candidates = []
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = coin.get('current_price', 0)
                change = coin.get('price_change_percentage_24h', 0)
                volume = coin.get('total_volume', 0)
                
                # صيد العملات التي جمعت سيولة وهي في القاع/تبدأ الصعود (تغير سلبي طفيف أو صعود هادئ مع حجم قوي)
                if -5 <= change <= 3 and volume > 50000000:
                    long_candidates.append((symbol, price, change, volume))
                
                # صيد العملات التي صعدت بقوة وبدأت تهبط أو وصلت قمة (تشبع وصعود قوي جداً)
                elif change > 8:
                    short_candidates.append((symbol, price, change, volume))
            
            reply = "🎯 **تقرير صياد الترند والسيولة (رأس مال 3$):**\n\n"
            
            reply += "🟢 **فرص صعود من القاع (بداية الترند / LONG):**\n"
            if long_candidates:
                for sym, p, ch, vol in long_candidates[:3]:
                    tp = p * 1.015
                    sl = p * 0.990
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch}%`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد فرص قاع واضحة حالياً، جرب لاحقاً.\n\n"
                
            reply += "🔴 **فرص هبوط وانعكاس (نهاية الترند / SHORT):**\n"
            if short_candidates:
                for sym, p, ch, vol in short_candidates[:3]:
                    tp = p * 0.985
                    sl = p * 1.010
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch}%`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد عملات في قمة مناسبة للهبوط حالياً.\n"
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء فحص السوق: {e}")
    else:
        bot.reply_to(message, "أهلاً يا محمد! أرسل **scan** أو **فحص** لصيد العملات ذات السيولة وبدايات الترند.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Trend Hunter Bot is running...")
    bot.infinity_polling()
