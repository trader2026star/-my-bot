import os
import telebot
import requests
from flask import Flask, request

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, threaded=False)
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

app = Flask(__name__)

@app.route('/')
def home():
    return "Webhook Bot is Live!"

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
            
            response = requests.get("https://api.coincap.io/v2/assets?limit=50", timeout=5)
            data = response.json().get('data', [])
            
            if not data:
                bot.reply_to(message, "⚠️ جاري تحديث السوق، حاول لاحقاً.")
                return
            
            accumulation_list = []
            fast_movers_list = []
            exhaustion_list = []
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = float(coin.get('priceUsd', 0))
                change = float(coin.get('changePercent24Hr', 0))
                vol = float(coin.get('volumeUsd24Hr', 0) or 0)
                
                if -7 <= change <= -1 and vol > 5000000:
                    accumulation_list.append(f"🟢 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                elif change >= 8 and vol > 10000000:
                    fast_movers_list.append(f"🚀 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                elif 3 <= change < 8 and vol > 8000000:
                    exhaustion_list.append(f"🔴 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
            
            reply = "🎯 **تقرير صياد السوق الشامل:**\n\n"
            reply += "📦 **1. تجميع العملات الهابطة (LONG):**\n"
            reply += "\n".join(accumulation_list[:3]) + "\n" if accumulation_list else "لا توجد فرص حالياً.\n"
            
            reply += "\n🚀 **2. العملات السريعة والزخم:**\n"
            reply += "\n".join(fast_movers_list[:3]) + "\n" if fast_movers_list else "لا توجد عملات سريعة حالياً.\n"
            
            reply += "\n⚡ **3. تشبعات الترند (SHORT):**\n"
            reply += "\n".join(exhaustion_list[:3]) if exhaustion_list else "لا توجد فرص حالياً."
            
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception:
            bot.reply_to(message, "❌ حدث خطأ مؤقت، جرب مرة أخرى.")
            
    else:
        try:
            coin_name = text.upper()
            response = requests.get("https://api.coincap.io/v2/assets?limit=50", timeout=5)
            data = response.json().get('data', [])
            
            found = None
            for coin in data:
                if coin.get('symbol', '').upper() == coin_name or coin.get('name', '').lower() == text:
                    found = coin
                    break
            
            if found:
                symbol = found.get('symbol', '').upper()
                name = found.get('name', '')
                price = float(found.get('priceUsd', 0))
                change = float(found.get('changePercent24Hr', 0))
                
                reply = (
                    f"📊 **مراجعة العملة: {name} ({symbol})**\n\n"
                    f"💵 السعر الحالي: `{price:.4f}$`\n"
                    f"📈 التغير (24 ساعة): `{change:.2f}%`\n\n"
                    f"🔍 *جاهزة للتحليل الفني.*"
                )
                bot.reply_to(message, reply, parse_mode="Markdown")
            else:
                bot.reply_to(message, f"⚠️ لم يتم العثور على العملة `{text.upper()}`.")
        except Exception:
            bot.reply_to(message, "❌ تعذر جلب بيانات العملة.")

if __name__ == "__main__":
    bot.remove_webhook()
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
