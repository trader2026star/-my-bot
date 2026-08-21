import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🚀 **أهلاً بك يا محمد في بوت السوق الاحترافي**\n\n"
        "• لفحص السوق وجلب الأصول: اكتب `scan`\n"
        "• للبحث عن سعر أي عملة: اكتب رمزها مباشرة (مثل: `btc`, `zec`, `tao`, `eth`, `sol`)\n"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "⚡ **جاري جلب بيانات السوق الحية...**", parse_mode="Markdown")
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            msg = "📊 **أبرز العملات الرقمية (بينانس):**\n\n"
            count = 0
            for ticker in data:
                symbol = ticker['symbol']
                if symbol.endswith('USDT') and count < 10:
                    price = float(ticker['lastPrice'])
                    change = float(ticker['priceChangePercent'])
                    trend = "🟢" if change >= 0 else "🔴"
                    msg += f"{trend} **{symbol.replace('USDT', '')}**: ${price:,.4f} | التغير: {change:.2f}%\n"
                    count += 1
            
            bot.reply_to(message, msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ حدث خطأ في الاتصال، حاول مجدداً.")
            
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
                trend = "🟢 صاعد" if change >= 0 else "🔴 هابط"
                
                response_text = (
                    f"🎯 **أصل السوق: {query.replace('USDT', '')}**\n\n"
                    f"💰 **السعر الحالي:** ${price:,.4f}\n"
                    f"📈 **حالة 24س:** {trend} ({change:.2f}%)\n"
                    f"⬆️ **أعلى سعر:** ${high:,.4f}\n"
                    f"⬇️ **أقل سعر:** ${low:,.4f}\n\n"
                    f"⚡ *جاهز لأي إعدادات أو تحليل قادم.*"
                )
                bot.reply_to(message, response_text, parse_mode="Markdown")
            else:
                bot.reply_to(message, "⚠️ لم يتم العثور على هذا الأصل، تأكد من الرمز (مثل BTC, ETH).")
        except Exception as e:
            bot.reply_to(message, "⚠️ حدث خطأ في جلب السعر.")

bot.infinity_polling()
