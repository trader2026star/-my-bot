import telebot
import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# ده بيحذف الويب هوك تلقائياً قبل ما البوت يبدأ شغل
try:
    bot.remove_webhook()
except:
    pass

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower().strip()
    
    if text in ["scan", "فحص", "سيولة"]:
        try:
            bot.reply_to(message, "⚡ جاري فحص السوق...")
            response = requests.get("https://api.coincap.io/v2/assets?limit=30", timeout=10)
            data = response.json().get('data', [])
            
            longs = [f"🟢 `{c['symbol']}` | `{float(c['priceUsd']):.4f}` | `{float(c['changePercent24Hr']):.2f}%`" 
                     for c in data if -7 <= float(c['changePercent24Hr']) <= -1]
            shorts = [f"🔴 `{c['symbol']}` | `{float(c['priceUsd']):.4f}` | `{float(c['changePercent24Hr']):.2f}%`" 
                      for c in data if float(c['changePercent24Hr']) >= 4]
            
            reply = f"📦 **تجميع:**\n" + "\n".join(longs[:3]) + "\n\n⚡ **تشبع:**\n" + "\n".join(shorts[:3])
            bot.reply_to(message, reply, parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, "❌ خطأ في الاتصال.")
    else:
        # البحث عن عملة
        try:
            coin_name = text.upper()
            response = requests.get("https://api.coincap.io/v2/assets?limit=50", timeout=10)
            data = response.json().get('data', [])
            coin = next((c for c in data if c['symbol'].upper() == coin_name), None)
            if coin:
                bot.reply_to(message, f"📊 {coin['name']}: {float(coin['priceUsd']):.4f}$ | تغير: {float(coin['changePercent24Hr']):.2f}%")
            else:
                bot.reply_to(message, "⚠️ عملة غير معروفة.")
        except:
            bot.reply_to(message, "❌ خطأ في الاتصال.")

print("Bot is running...")
bot.infinity_polling()
