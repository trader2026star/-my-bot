import os
import telebot
import requests
from flask import Flask, request

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, threaded=False)

# رابط سيرفرك على رندر (تأكد من وضع رابط خدمتك الصحيح هنا أو اتركه يعمل تلقائياً)
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

app = Flask(__name__)

@app.route('/')
def home():
    return "Webhook Bot is Live!"

# استقبال الرسائل من تليجرام عبر الـ Webhook بدون أخطاء 409
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "!", 200
    else:
        return "Internal Error", 403

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower().strip()
    if text in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري فحص السوق...")
            
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
                
                if -6 <= change <= 1 and vol > 10000000:
                    long_list.append(f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                elif change >= 5 and vol > 15000000:
                    short_list.append(f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
            
            reply = "🎯 **تقرير صياد الترند:**\n\n🟢 **فرص صيد التجميع (LONG):**\n"
            reply += "\n".join(long_list[:3]) + "\n" if long_list else "لا توجد فرص مطابقة حالياً.\n"
                
            reply += "\n🔴 **فرص صيد التشبع (SHORT):**\n"
            reply += "\n".join(short_list[:3]) if short_list else "لا توجد فرص مطابقة حالياً."
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception:
            bot.reply_to(message, "❌ ضغط مؤقت في الاتصال، أرسل scan مرة أخرى.")

if __name__ == "__main__":
    # إزالة أي ويب هوك قديم وضبط الجديد
    bot.remove_webhook()
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")
    
    # تشغيل سيرفر Flask فقط لاستقبال الويب هوك
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
