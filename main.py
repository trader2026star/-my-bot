import os
import telebot

TOKEN = os.environ.get('API_TOKEN')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك! بوت التداول الخاص بك يعمل الآن بنجاح على السحاب.")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"أهلاً بك يا محمد، لقد استلمت رسالتك: {message.text}")

if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling()
