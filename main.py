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
            bot.reply_to(message, "⚡ جاري فحص العملات السريعة، التجميع، والتشبعات...")
            
            response = requests.get("https://api.coincap.io/v2/assets?limit=70", timeout=8)
            data = response.json().get('data', [])
            
            if not data:
                bot.reply_to(message, "⚠️ جاري تحديث السوق، حاول بعد لحظات.")
                return
            
            accumulation_list = []  # 1. تجميع العملات الهابطة قبل الانعكاس (LONG)
            fast_movers_list = []   # 2. العملات السريعة وذات الزخم العالي جداً
            exhaustion_list = []    # 3. العملات الصاعدة بقوة المعرضة للهبوط (SHORT)
            
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                price = float(coin.get('priceUsd', 0))
                change = float(coin.get('changePercent24Hr', 0))
                vol = float(coin.get('volumeUsd24Hr', 0) or 0)
                
                # تجميع الهابطة بهدوء قبل الانطلاق
                if -7 <= change <= -1 and vol > 8000000:
                    accumulation_list.append(f"🟢 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                
                # العملات السريعة (زخم صعودي قوي ومشتعل)
                elif change >= 8 and vol > 15000000:
                    fast_movers_list.append(f"🚀 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
                
                # تشبعات الترند القوية المعرضة للهبوط
                elif change >= 4 and change < 8 and vol > 10000000:
                    exhaustion_list.append(f"🔴 `{symbol}` | السعر: `{price:.4f}` | التغير: `{change:.2f}%`")
            
            reply = "🎯 **تقرير صياد السوق الشامل:**\n\n"
            
            reply += "📦 **1. تجميع العملات الهابطة (مراكز LONG بالقاع):**\n"
            reply += "\n".join(accumulation_list[:3]) + "\n" if accumulation_list else "لا توجد فرص تجميع حالياً.\n"
            
            reply += "\n🚀 **2. العملات السريعة (زخم واشتعال لحظي):**\n"
            reply += "\n".join(fast_movers_list[:3]) + "\n" if fast_movers_list else "لا توجد عملات سريعة نشطة حالياً.\n"
            
            reply += "\n⚡ **3. تشبعات الترند (مرشحة للهبوط SHORT):**\n"
            reply += "\n".join(exhaustion_list[:3]) if exhaustion_list else "لا توجد فرص تشبع واضحة حالياً."
            
            bot.reply_to(message, reply, parse_mode="Markdown")
            
        except Exception:
            bot.reply_to(message, "❌ حدث ضغط في جلب البيانات، أرسل scan مرة أخرى.")
            
    else:
        # الرد الفوري المخصص عند إرسال اسم العملة
        try:
            coin_name = text.upper()
            response = requests.get("https://api.coincap.io/v2/assets?limit=100", timeout=6)
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
                change = float(found.get('changePercent24Hor', found.get('changePercent24Hr', 0)))
                market_cap = float(found.get('marketCapUsd', 0))
                
                reply = (
                    f"📊 **مراجعة العملة: {name} ({symbol})**\n\n"
                    f"💵 السعر الحالي: `{price:.4f}$`\n"
                    f"📈 التغير (24 ساعة): `{change:.2f}%`\n"
                    f"💰 القيمة السوقية: `{market_cap:,.0f}$`\n\n"
                    f"🔍 *جاهزة للتحليل الفني وتحديد مناطق الدخول.*"
                )
                bot.reply_to(message, reply, parse_mode="Markdown")
            else:
                bot.reply_to(message, f"⚠️ لم يتم العثور على العملة `{text.upper()}`، تأكد من الرمز.")
        except Exception:
            bot.reply_to(message, "❌ تعذر جلب البيانات حالياً.")

if __name__ == "__main__":
    bot.remove_webhook()
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
