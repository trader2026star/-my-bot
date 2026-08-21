import os
import telebot
from flask import Flask, request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# الرابط بتاعك اللي اخدته من Render
WEBHOOK_URL = "https://my-bot-mtyr.onrender.com/" 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '!', 403

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "تم الربط بنجاح! البوت يعمل الآن بنظام Webhook.")

if __name__ == "__main__":
    # تنظيف أي Webhook قديم وتعيين الجديد
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
