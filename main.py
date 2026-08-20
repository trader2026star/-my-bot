import os
import telebot
import pandas as pd
from binance.um_futures import UMFutures
from flask import Flask
from threading import Thread
import time

# تشغيل سيرفر Flask عشان Render يفضل مبسوط
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# إعداد البوت
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
client = UMFutures()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.upper().strip()
    if text in ["SCAN", "فحص", "سيولة"]:
        try:
            tickers = client.ticker_24hr_price_change()
            df = pd.DataFrame(tickers)
            df['quoteVolume'] = df['quoteVolume'].astype(float)
            usdt_df = df[df['symbol'].str.endswith('USDT')].copy()
            top_coin = usdt_df.sort_values(by='quoteVolume', ascending=False).iloc[0]
            symbol = top_coin['symbol']
            
            klines = client.klines(symbol=symbol, interval='1h', limit=30)
            df_k = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'trades', 'tb_base', 'tb_quote', 'ignore'])
            df_k['close'] = df_k['close'].astype(float)
            
            rsi = 50 # تبسيط للحساب
            price = df_k['close'].iloc[-1]
            
            reply = f"🚀 العملة الأكثر سيولة: `{symbol}`\n💵 السعر: `{price}`\n🎯 الهدف: `{price*1.015:.4f}` | 🛑 الوقف: `{price*0.990:.4f}`"
            bot.reply_to(message, reply, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"خطأ: {e}")

if __name__ == "__main__":
    # تشغيل Flask في Thread
    Thread(target=run_flask).start()
    # تشغيل البوت بطريقة Polling عادية ومضمونة
    print("Bot is polling...")
    bot.infinity_polling()
