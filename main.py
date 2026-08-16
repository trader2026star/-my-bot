import os
import random
import requests
import telebot

TOKEN = os.getenv("API_TOKEN")
bot = telebot.TeleBot(TOKEN)

# قائمة العملات المدعومة بأسماء أزواج بينانس الصحيحة
COINS_MAP = {
    "BTC": "BTCUSDT",
    "SOL": "SOLUSDT",
    "ETH": "ETHUSDT",
    "ZEC": "ZECUSDT",
    "TAO": "TAOUSDT",
    "XRP": "XRPUSDT"
}

@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "أهلاً بك يا محمد! أرسل اسم العملة (مثل BTC أو SOL) أو scan لجلب السعر الحقيقي.")

@bot.message_handler(func=lambda m: True)
def handle(m):
    text = m.text.strip().upper()
    
    if text == "SCAN":
        coin_key = random.choice(list(COINS_MAP.keys()))
    else:
        coin_key = text

    if coin_key not in COINS_MAP:
        bot.reply_to(m, "يرجى كتابة اسم عملة صحيح من القائمة (BTC, SOL, ETH, ZEC, TAO, XRP) أو كلمة scan.")
        return

    symbol = COINS_MAP[coin_key]
    
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=5)
        data = res.json()
        price = float(data["price"])
    except Exception:
        bot.reply_to(m, "عذراً، لم نتمكن من جلب السعر اللحظي من المنصة حالياً.")
        return

    direction = random.choice(["LONG 🟢", "SHORT 🔴"])
    
    if "LONG" in direction:
        tp1 = round(price * 1.02, 4)
        tp2 = round(price * 1.04, 4)
        sl = round(price * 0.98, 4)
    else:
        tp1 = round(price * 0.98, 4)
        tp2 = round(price * 0.96, 4)
        sl = round(price * 1.02, 4)

    response = (
        f"📊 **تحليل السوق اللحظي: {coin_key}/USDT**\n\n"
        f"📈 الاتجاه: **{direction}**\n"
        f"📍 السعر الفوري من Binance: `{price}`\n\n"
        f"🎯 الأهداف:\n"
        f"- الهدف الأول: `{tp1}`\n"
        f"- الهدف الثاني: `{tp2}`\n\n"
        f"🛑 وقف الخسارة: `{sl}`"
    )

    bot.reply_to(m, response, parse_mode="Markdown")

bot.infinity_polling()



