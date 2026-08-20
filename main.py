import os
import telebot
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)
@app.route('/')
def home(): return "Trend Hunter & Liquidity Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.upper().strip()
    
    if text in ["SCAN", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري مراقبة السيولة وصيد بدايات الترند للعملات السريعة...")
            
            # جلب البيانات وترتيبها حسب السيولة (Volume) لصيد العملات السريعة
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=50&page=1&sparkline=false"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if not data or not isinstance(data, list):
                bot.reply_to(message, "⚠️ عذراً، يوجد ضغط على مزود البيانات، جرب مرة أخرى.")
                return
                
            accumulation_long = [] 
            exhaustion_short = []  
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = coin.get('current_price', 0)
                change = coin.get('price_change_percentage_24h', 0)
                volume = coin.get('total_volume', 0)
                
                # 1. صيد الترند الصاعد: عملة هابطة أو في القاع (-10% إلى +2%) ولكن جمعت سيولة ضخمة جداً
                if -10 <= change <= 2 and volume > 30000000:
                    accumulation_long.append((symbol, price, change, volume))
                
                # 2. صيد الترند الهابط: عملة سريعة طارت فوق 8% ووصلت لمرحلة التشبع (انعكاس)
                elif change > 8 and volume > 40000000:
                    exhaustion_short.append((symbol, price, change, volume))
            
            reply = "🎯 **تقرير صياد الترند والسيولة السريعة:**\n\n"
            
            reply += "🟢 **صعود من القاع (جمعت سيولة لبدء الترند / LONG):**\n"
            if accumulation_long:
                # عرض أفضل 3 فرص
                for sym, p, ch, vol in accumulation_long[:3]:
                    tp = p * 1.018  # هدف 1.8%
                    sl = p * 0.988  # وقف خسارة 1.2%
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch:.2f}%`\n📊 السيولة: `{vol:,.0f}$`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد فرص تجميع واضحة في القاع حالياً.\n\n"
                
            reply += "🔴 **هبوط من القمة (تشبع شرائي ونهاية الترند / SHORT):**\n"
            if exhaustion_short:
                # عرض أفضل 3 فرص
                for sym, p, ch, vol in exhaustion_short[:3]:
                    tp = p * 0.982  # هدف هبوط 1.8%
                    sl = p * 1.012  # وقف خسارة 1.2% فوق القمة
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch:.2f}%`\n📊 السيولة: `{vol:,.0f}$`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد عملات في قمة التشبع حالياً.\n"
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء الفحص: {e}")
    else:
        bot.reply_to(message, "أهلاً يا محمد! أرسل **scan** أو **فحص** لصيد العملات السريعة وبدايات الترند.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    # هذا السطر مهم جداً لمنع خطأ 409 Conflict الذي ظهر لك سابقاً
    try:
        bot.remove_webhook()
    except:
        pass
        
    print("Trend Hunter Bot is running cleanly...")
    # skip_pending=True تتجاهل أي رسائل قديمة معلقة لتجنب التضارب
    bot.infinity_polling(skip_pending=True)
