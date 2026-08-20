import os
import time
import requests
import pandas as pd
import numpy as np
from binance.um_futures import UMFutures
from flask import Flask
from threading import Thread

# تشغيل سيرفر وهمي صغير عشان Render يرضى وما يطلعش مشكلة الـ Port
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# بيانات التيليجرام
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = UMFutures()

SELECTED_WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "PEPEUSDT", "SUIUSDT", 
    "NEARUSDT", "AVAXUSDT", "RENDERUSDT", "FETUSDT", "INJUSDT"
]

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def get_active_symbols():
    symbols_set = set(SELECTED_WATCHLIST)
    try:
        ticker_info = client.ticker_24hr_price_change()
        df = pd.DataFrame(ticker_info)
        df['quoteVolume'] = df['quoteVolume'].astype(float)
        usdt_pairs = df[df['symbol'].str.endswith('USDT')].copy()
        top_volume_coins = usdt_pairs.sort_values(by='quoteVolume', ascending=False).head(15)['symbol'].tolist()
        for sym in top_volume_coins:
            symbols_set.add(sym)
    except Exception as e:
        print(f"Error fetching symbols: {e}")
    return list(symbols_set)

def analyze_market():
    symbols = get_active_symbols()
    for symbol in symbols:
        try:
            klines = client.klines(symbol=symbol, interval='1h', limit=50)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'n_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            current_price = df['close'].iloc[-1]
            current_rsi = df['rsi'].iloc[-1]
            
            if current_rsi < 35:
                tp = current_price * 1.015
                sl = current_price * 0.990
                msg = (
                    f"🟢 **فرصة صعود (LONG)** 🟢\n"
                    f"💎 العملة: `{symbol}`\n"
                    f"💵 السعر الحالي: `{current_price}`\n"
                    f"📊 مؤشر RSI: `{current_rsi:.2f}` (تشبع بيعي)\n"
                    f"🎯 الهدف المقترح: `{tp:.4f}`\n"
                    f"🛑 وقف الخسارة: `{sl:.4f}`\n"
                    f"💡 *مخصص برأس مال 3$ وهدف سريع*"
                )
                send_telegram_message(msg)
                time.sleep(2)

            elif current_rsi > 65:
                tp = current_price * 0.985
                sl = current_price * 1.010
                msg = (
                    f"🔴 **فرصة هبوط (SHORT)** 🔴\n"
                    f"💎 العملة: `{symbol}`\n"
                    f"💵 السعر الحالي: `{current_price}`\n"
                    f"📊 مؤشر RSI: `{current_rsi:.2f}` (تشبع شرائي)\n"
                    f"🎯 الهدف المقترح: `{tp:.4f}`\n"
                    f"🛑 وقف الخسارة: `{sl:.4f}`\n"
                    f"💡 *مخصص برأس مال 3$ وهدف سريع*"
                )
                send_telegram_message(msg)
                time.sleep(2)
                
        except Exception as e:
            continue

if __name__ == "__main__":
    # تشغيل السيرفر الوهمي في الخلفية عشان Render ما يقفلش البوت
    keep_alive()
    print("Bot started successfully with web port server...")
    while True:
        analyze_market()
        time.sleep(900)
