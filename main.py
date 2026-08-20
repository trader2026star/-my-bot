import os
import telebot
import pandas as pd
import numpy as np
from binance.um_futures import UMFutures
from flask import Flask
from threading import Thread

# سيرفر رندر الوهمي
app = Flask('')
@app.route('/')
def home(): return "Hunter Bot is running!"
def run_web(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
Thread(target=run_web).start()

# البوت
bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
client = UMFutures()

@bot.message_handler(func=lambda message: message.text.upper() in ["SCAN", "فحص", "سيولة"])
def scan_market(message):
    bot.reply_to(message, "🔍 جاري البحث عن العملات الأكثر سيولة وترند في السوق حالياً...")
    try:
        # جلب بيانات السوق كاملة
        tickers = client.ticker_24hr_price_change()
        df = pd.DataFrame(tickers)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        df['priceChangePercent'] = df['priceChangePercent'].astype(float)
        
        # تصفية عملات USDT فقط
        usdt_df = df[df['symbol'].str.endswith('USDT')].copy()
        
        # اختيار العملة الأقوى (أعلى سيولة + تغير في السعر)
        top_coin = usdt_df.sort_values(by='quoteVolume', ascending=False).iloc[0]
        symbol = top_coin['symbol']
        
        # تحليل RSI للعملة دي
        klines = client.klines(symbol=symbol, interval='1h', limit=30)
        df_k = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'trades', 'tb_base', 'tb_quote', 'ignore'])
        df_k['close'] = df_k['close'].astype(float)
        
        # حساب RSI
        delta = df_k['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
        
        # تحديد الفرصة
        price = df_k['close'].iloc[-1]
        if rsi < 35:
            direction = "🟢 **فرصة صعود (قاع وسرعة سيولة)**"
            tp, sl = price * 1.02, price * 0.98
        elif rsi > 65:
            direction = "🔴 **فرصة هبوط (تشبع شرائي وبداية تصحيح)**"
            tp, sl = price * 0.98, price * 1.02
        else:
            direction = "⚪ **مرحلة تذبذب (مراقبة)**"
            tp, sl = price * 1.01, price * 0.99

        reply = (
            f"🚀 **العملة الأكثر سيولة الآن:** `{symbol}`\n"
            f"💵 السعر: `{price}`\n"
            f"📊 تغير 24 ساعة: `{top_coin['priceChangePercent']}%`\n"
            f"📊 مؤشر RSI: `{rsi:.2f}`\n"
            f"💡 التوقع: {direction}\n"
            f"🎯 هدف سريع: `{tp:.4f}` | 🛑 وقف: `{sl:.4f}`"
        )
        bot.reply_to(message, reply, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"خطأ في الفحص: {e}")

if __name__ == "__main__":
    bot.infinity_polling()
