import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# تنظيف أي ويب هوك قديم
try:
    bot.remove_webhook()
except:
    pass

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower().strip()
    
    if text in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري الفحص...")
            # استخدام API الخاص بـ Binance للسرعة
            res = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10)
            data = res.json()
            
            # فلترة العملات (التي تقابل USDT فقط)
            usdt_pairs = [c for c in data if c['symbol'].endswith('USDT')][:50]
            
            longs = []
            shorts = []
            
            for c in usdt_pairs:
                change = float(c['priceChangePercent'])
                symbol = c['symbol'].replace('USDT', '')
                price = float(c['lastPrice'])
                
                if -7 <= change <= -1:
                    longs.append(f"🟢 {symbol}: {price:.4f} ({change:.2f}%)")
                elif change >= 4:
                    shorts.append(f"🔴 {symbol}: {price:.4f} ({change:.2f}%)")
            
            reply = "📦 **تجميع:**\n" + "\n".join(longs[:3]) + "\n\n⚡ **تشبع:**\n" + "\n".join(shorts[:3])
            bot.reply_to(message, reply)
            
        except Exception:
            bot.reply_to(message, "🔄 جاري تحديث بيانات السوق، حاول مرة أخرى بعد لحظات.")
            
    else:
        # البحث عن عملة
        try:
            coin = text.upper() + "USDT"
            res = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={coin}", timeout=5)
            data = res.json()
            if 'lastPrice' in data:
                bot.reply_to(message, f"📊 {text.upper()}: {float(data['lastPrice']):.4f}$ | تغير: {float(data['priceChangePercent']):.2f}%")
            else:
                bot.reply_to(message, "⚠️ تأكد من اسم العملة.")
        except:
            bot.reply_to(message, "⚠️ تعذر جلب البيانات.")

print("Bot is running...")
bot.infinity_polling()
