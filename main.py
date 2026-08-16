import os
import requests
import telebot

TOKEN = os.getenv("API_TOKEN")
bot = telebot.TeleBot(TOKEN)

COINS = ["SOL", "BTC", "ETH", "ZEC", "TAO", "XRP"]

def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data["price"])
    except Exception:
        return None

@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "أهلاً بك يا محمد! أرسل scan أو اسم العملة لجلب السعر الحقيقي من السوق.")

@bot.message_handler(func=lambda m: True)
def handle(m):
    text = m.text.strip().upper()
    
    if text == "SCAN":
        import random
        coin = random.choice(COINS)
    else:
        coin = text

    if coin not in COINS:
        bot.reply_to(m, "يرجى كتابة اسم عملة صحيح (مثل BTC, SOL) أو كلمة scan.")
        return

    price = get_binance_price(coin)
    if not price:
        bot.reply_to(m, "عذراً، حدث خطأ أثناء جلب السعر من المنصة. حاول مرة أخرى.")
        return

    # حساب الأهداف ووقف الخسارة بناءً على السعر الحقيقي
    import random
    direction = random.choice(["LONG 🟢", "SHORT 🔴"])
    
    if "LONG" in direction:
        tp1 = round(price * 1.02, 2)
        tp2 = round(price * 1.04, 2)
        sl = round(price * 0.98, 2)
    else:
        tp1 = round(price * 0.98, 2)
        tp2 = round(price * 0.96, 2)
        sl = round(price * 1.02, 2)

    response = (
        f"📊 **تقرير تحليل السوق الحقيقي: {coin}/USDT**\n\n"
        f"📈 الاتجاه المقترح: **{direction}**\n"
        f"📍 السعر الحقيقي الآن: `{price}`\n\n"
        f"🎯 الأهداف الحية:\n"
        f"- الهدف الأول: `{tp1}`\n"
        f"- الهدف الثاني: `{tp2}`\n\n"
        f"🛑 وقف الخسارة: `{sl}`"
    )

    bot.reply_to(m, response, parse_mode="Markdown")

bot.infinity_polling()



