import os
import telebot
from flask import Flask
from threading import Thread
from analysis import get_market_movers

# قراءة توكن البوت من بيئة التشغيل
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# إعداد سيرفر ويب وهمي لتجاوز قيود البورتات في Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run():
    app.run(host='0.0.0.0', port=8080)

# أمر ترحيبي بسيط للتأكد من عمل البوت
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً يا محمد، البوت يعمل الآن بنجاح وجاهز لرصد السوق!")

# أمر رصد العملات الأكثر صعوداً من بينانس
@bot.message_handler(commands=['monitor'])
def monitor_market(message):
    bot.reply_to(message, "جاري رصد العملات الأكثر صعوداً... انتظر لحظة.")
    report = get_market_movers()
    bot.reply_to(message, f"العملات الأكثر صعوداً حالياً:\n{report}")

if __name__ == "__main__":
    # تشغيل السيرفر في الخلفية
    t = Thread(target=run)
    t.start()
    # تشغيل البوت
    bot.polling()
