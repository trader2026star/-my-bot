import os
import telebot
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Active"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower().strip()
    if text in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري فحص السوق...")
            
            # جلب البيانات برابط مباشر وسريع
            url = "https://api.coincap.io/v2/assets?limit=30"
            response = requests.get(url, timeout=5)
            res_json = response.json()
            data = res_json.get('data', [])
            
            if not data:
                bot.reply_to(message, "⚠️ جاري تحديث السوق، حاول بعد ثوانٍ.")
                return
            
            long_list = []
            short_list = []
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = float(coin.get('priceUsd', 0))
                change = float(coin.get('changePercent24Hr', 0))
                vol = float(coin.get('volumeUsd24Hr', 0))
                
                # تجميع (LONG)
                if -6 <= change <= 1 and vol > 10000000:
                    long_list.append(f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                
                # تشبع (SHORT)
                elif change >= 5 and vol > 15000000:
                    short_list.append(f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
            
            reply = "🎯 **تقرير صياد الترند:**\n\n🟢 **فرص صيد التجميع (LONG):**\n"
            if long_list:
                reply += "\n".join(long_list[:3]) + "\n"
            else:
                reply += "لا توجد فرص مطابقة حالياً.\n"
                
            reply += "\n🔴 **فرص صيد التشبع (SHORT):**\n"
            if short_list:
                reply += "\n".join(short_list[:3])
            else:
                reply += "لا توجد فرص مطابقة حالياً."
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception:
            bot.reply_to(message, "❌ ضغط مؤقت في الاتصال، أرسل scan مرة أخرى.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    # إجبار تليجرام على إنهاء أي جلسة قديمة لغلق خطأ 409 نهائياً
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    except:
        pass
        
    print("Bot started cleanly...")
    bot.infinity_polling(skip_pending=True)
