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
            bot.reply_to(message, "⚡ جاري فحص السوق بدقة...")
            
            # استخدام API قوي ومجاني بدون حظر
            url = "https://api.coincap.io/v2/assets?limit=50"
            response = requests.get(url, timeout=10)
            result = response.json()
            
            data = result.get('data', [])
            if not data:
                bot.reply_to(message, "⚠️ جارٍ تحديث البيانات، حاول بعد ثوانٍ.")
                return
            
            long_msg = "🟢 **فرص صيد التجميع (LONG):**\n"
            short_msg = "🔴 **فرص صيد التشبع والهبوط (SHORT):**\n"
            
            long_count = 0
            short_count = 0
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = float(coin.get('priceUsd', 0))
                change = float(coin.get('changePercent24Hr', 0))
                vol = float(coin.get('volumeUsd24Hr', 0))
                
                # 1. تجميع (LONG): عملة هابطة أو قريبة من الصفر بس عليها سيولة ممتازة
                if -5 <= change <= 1 and vol > 20000000:
                    long_msg += f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`\n"
                    long_count += 1
                
                # 2. تشبع (SHORT): عملة طارت فوق 6% وهتهبط
                elif change >= 6 and vol > 30000000:
                    short_msg += f"💎 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`\n"
                    short_count += 1
            
            final_reply = ""
            if long_count > 0:
                final_reply += long_msg + "\n"
            else:
                final_reply += "🟢 **فرص LONG:** لا توجد فرص مطابقة حالياً.\n\n"
                
            if short_count > 0:
                final_reply += short_msg
            else:
                final_reply += "🔴 **فرص SHORT:** لا توجد فرص مطابقة حالياً."
                
            bot.reply_to(message, final_reply, parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ مؤقت، جرب مرة أخرى.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
