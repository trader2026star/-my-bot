import os
import random
import telebot

TOKEN = os.getenv("API_TOKEN")
bot = telebot.TeleBot(TOKEN)

COINS = ["SOL", "BTC", "ETH", "ZEC", "TAO", "XRP"]


@bot.message_handler(commands=["start"])
def start(m):
  bot.reply_to(m, "أهلاً بك يا محمد! أرسل scan أو اسم العملة للتحليل.")


@bot.message_handler(func=lambda m: True)
def handle(m):
  text = m.text.strip().upper()
  coin = random.choice(COINS) if text == "SCAN" else text
  dir = random.choice(["LONG 🟢", "SHORT 🔴"])
  entry = round(random.uniform(10, 200), 2)

  bot.reply_to(
      m,
      f"📊 تحليل {coin}\nالاتجاه: {dir}\nالدخول: {entry}",
      parse_mode="Markdown",
  )


bot.infinity_polling()

