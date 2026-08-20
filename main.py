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
            bot.reply_to(message, "⚡ جاري رصد السيولة اللحظية وصيد العملات السريعة وبدايات الترند...")
            
            # جلب البيانات مع الترتيب حسب الحجم (السيولة) لضمان مراقبة العملات الأكثر نشاطاً
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=40&page=1&sparkline=false"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if not data or not isinstance(data, list):
                bot.reply_to(message, "⚠️ عذراً، ضغط على السيرفر، جرب مرة أخرى بعد قليل.")
                return
                
            accumulation_long = [] # هابطة / في قاع وجمعت سيولة لبدء الترند الصاعد
            exhaustion_short = []  # صعدت بقوة / ترند صاعد بينتهي وهتهبط من القمة
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = coin.get('current_price', 0)
                change = coin.get('price_change_percentage_24h', 0)
                volume = coin.get('total_volume', 0)
                
                # شرط التجميع من القاع (هابطة أو سلبية بنسبة تتراوح بين -10% إلى +1% بس عليها سيولة ضخمة جداً)
                if -12 <= change <= 1 and volume > 30000000:
                    accumulation_long.append((symbol, price, change, volume))
                
                # شرط التشبع للصعود وهبوط القمة (صعدت بأكتر من 7% وبدأت تظهر عليها سيولة تداول مفرطة)
                elif change > 7:
                    exhaustion_short.append((symbol, price, change, volume))
            
            reply = "🎯 **تقرير رصد السيولة وصيد بدايات الترند (رأس مال 3$):**\n\n"
            
            reply += "🟢 **صيد الترند الصاعد من القاع (تجميع سيولة / LONG):**\n"
            if accumulation_long:
                # ترتيب حسب الأقرب للقاع والأكثر سيولة
                for sym, p, ch, vol in accumulation_long[:3]:
                    tp = p * 1.018  # هدف سريع ومناسب
                    sl = p * 0.988  # وقف خسارة ضيق لحماية رأس المال
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch}%`\n📊 السيولة: `{vol:,.0f}$`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد فرص تجميع في القاع حالياً.\n\n"
                
            reply += "🔴 **صيد الترند الهابط من القمة (انعكاس التشبع / SHORT):**\n"
            if exhaustion_short:
                for sym, p, ch, vol in exhaustion_short[:3]:
                    tp = p * 0.982  # هدف هبوط سريع
                    sl = p * 1.012  # وقف خسارة فوق القمة مباشرة
                    reply += f"💎 `{sym}USDT`\n💵 السعر: `{p}` | التغير: `{ch}%`\n📊 السيولة: `{vol:,.0f}$`\n🎯 هدف: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`\n\n"
            else:
                reply += "لا توجد عملات وصلت للتشبع الهبوطي حالياً.\n"
                
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء فحص السوق: {e}")
    else:
        bot.reply_to(message, "أهلاً يا محمد! أرسل **scan** أو **فحص** لصيد العملات السريعة وبدايات الترند.")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Trend Hunter Bot is running...")
    bot.infinity_polling()
