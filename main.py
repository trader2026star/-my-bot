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
    
    if coin not in COINS and text != "SCAN":
        bot.reply_to(m, "يرجى كتابة اسم عملة صحيح أو كلمة scan.")
        return

    direction = random.choice(["LONG 🟢", "SHORT 🔴"])
    entry = round(random.uniform(10, 200), 2)
    tp1 = round(entry * 1.03, 2)
    tp2 = round(entry * 1.06, 2)
    sl = round(entry * 0.98, 2)

    response = (
        f"📊 **تقرير تحليل {coin}**\n\n"
        f"📈 الاتجاه: **{direction}**\n"
        f"📍 سعر الدخول: `{entry}`\n\n"
        f"🎯 الأهداف:\n"
        f"- الهدف الأول: `{tp1}`\n"
        f"- الهدف الثاني: `{tp2}`\n\n"
        f"🛑 وقف الخسارة: `{sl}`"
    )

    bot.reply_to(m, response, parse_mode="Markdown")

bot.infinity_polling()


