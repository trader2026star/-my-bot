import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "أهلاً بك! البوت جاهز. اكتب اسم العملة (مثل BTC) أو 'scan' لفحص السوق.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower().strip()
    
    if text == "scan":
        bot.reply_to(message, "⚡ جاري جلب البيانات من السوق...")
        try:
            # استخدام API مباشر ومجاني وسريع
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&sparkline=false"
            res = requests.get(url, timeout=10)
            data = res.json()
            
            msg = "📊 **أهم 10 عملات حالياً:**\n\n"
            for coin in data:
                msg += f"🔹 {coin['symbol'].upper()}: {coin['current_price']}$ ({coin['price_change_percentage_24h']:.2f}%)\n"
            bot.reply_to(message, msg, parse_mode="Markdown")
        except:
            bot.reply_to(message, "❌ حدث خطأ في الاتصال بالخادم، حاول مجدداً.")
            
    else:
        # البحث عن عملة محددة
        try:
            # تحويل الاسم للـ id المطلوب في API
            coin_id = text.replace("btc", "bitcoin").replace("eth", "ethereum").replace("sol", "solana")
            res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true", timeout=5)
            data = res.json()
            
            if data and coin_id in data:
                price = data[coin_id]['usd']
                change = data[coin_id]['usd_24h_change']
                bot.reply_to(message, f"📊 **{text.upper()}**: {price}$ | تغير 24س: {change:.2f}%")
            else:
                bot.reply_to(message, "⚠️ تأكد من اسم العملة (اكتب الاسم بالإنجليزية).")
        except:
            bot.reply_to(message, "⚠️ تعذر جلب البيانات.")

bot.infinity_polling()
