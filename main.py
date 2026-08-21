import telebot
import requests
import os
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# سيرفر وهمي صغير جداً عشان نرضي رندر وما يعطيناش خطأ البورتات
app = Flask('')

@app.route('/')
def home():
    return "Bot is active and running!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# تشغيل البوت
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "⚡ **أهلاً بك يا محمد**\n\n"
        "• اكتب `scan` لفحص السوق ورصد العملات والسيولة.\n"
        "• أو اكتب رمز أي عملة (مثل `btc`, `zec`, `tao`, `sol`) لعرض تفاصيلها الفورية."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "🔍 **جاري فحص السوق ورصد السيولة...**", parse_mode="Markdown")
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            gainers = []
            losers = []
            
            for ticker in data:
                symbol = ticker['symbol']
                if symbol.endswith('USDT'):
                    change = float(ticker['priceChangePercent'])
                    coin_name = symbol.replace('USDT', '')
                    if change > 0:
                        gainers.append((coin_name, change))
                    else:
                        losers.append((coin_name, change))
            
            gainers = sorted(gainers, key=lambda x: x[1], reverse=True)[:5]
            losers = sorted(losers, key=lambda x: x[1], reverse=True)[:5]
            
            msg = "📊 **تقرير سيولة السوق اللحظي:**\n\n"
            msg += "🟢 **أصول قوية / دخول سيولة (مرشحة للاستمرار):**\n"
            for coin, ch in gainers:
                msg += f"• **{coin}**: +{ch:.2f}%\n"
            
            msg += "\n🔴 **أصول ضعيفة / خروج سيولة (مرشحة للهبوط):**\n"
            for coin, ch in losers:
                msg += f"• **{coin}**: {ch:.2f}%\n"
                
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ مؤقت في جلب البيانات، حاول مجدداً.")
            
    else:
        query = text.upper().replace("$", "").strip() + "USDT"
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={query}"
            res = requests.get(url, timeout=5)
            data = res.json()
            
            if 'lastPrice' in data:
                price = float(data['lastPrice'])
                change = float(data['priceChangePercent'])
                high = float(data['highPrice'])
                low = float(data['lowPrice'])
                
                trend = "🟢 إيجابي / سيولة داخلة" if change >= 0 else "🔴 سلبي / خروج سيولة"
                
                response_text = (
                    f"🎯 **تحليل الأصل: {query.replace('USDT', '')}**\n\n"
                    f"💰 **السعر الحالي:** ${price:,.4f}\n"
                    f"📈 **التغير (24س):** {change:+.2f}%\n"
                    f"🌊 **الحالة:** {trend}\n"
                    f"⬆️ **القمة:** ${high:,.4f} | ⬇️ **القاع:** ${low:,.4f}"
                )
                bot.reply_to(message, response_text, parse_mode="Markdown")
            else:
                bot.reply_to(message, "⚠️ لم يتم العثور على هذا الأصل، تأكد من الرمز.")
        except Exception as e:
            bot.reply_to(message, "⚠️ حدث خطأ في جلب السعر.")

# تشغيل السيرفر الوهمي في الخلفية بالتزامن مع البوت
if __name__ == '__main__':
    t = Thread(target=run_web)
    t.start()
    bot.infinity_polling()
