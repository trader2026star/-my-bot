import os
import telebot

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً يا محمد، البوت شغال دلوقتي وجاهز!")

@bot.message_handler(commands=['hello'])
def say_hello(message):
    bot.reply_to(message, "يا هلا بيك يا محمد، أنا سامعك تمام!")

if __name__ == "__main__":
    # تشغيل مباشر بدون فلاسك وبدون تعقيد السيرفرات
    bot.infinity_polling()
