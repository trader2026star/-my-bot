import os
import telebot
from flask import Flask
from threading import Thread

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

# الأوامر المعتمدة فقط
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "البوت يعمل الآن! جرب كتابة /hello")

@bot.message_handler(commands=['hello'])
def say_hello(message):
    bot.reply_to(message, "أهلاً يا محمد، البوت شغال تمام!")

if __name__ == "__main__":
    t = Thread(target=run)
    t.start()
    bot.polling()
