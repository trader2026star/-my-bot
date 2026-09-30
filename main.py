import time
import os
import requests
import ccxt
import pandas as pd
from flask import Flask
from threading import Thread
from analysis import analyze_market_conditions

app = Flask('')

@app.route('/')
def home():
    return "Elite Sniper Bot is Running Safely!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# إعداد توكن تليجرام والـ Chat ID من متغيرات البيئة في Render لضمان الأمان وعدم توقف البوت
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()

def job():
    symbols = ['BRUSDT.P', 'ESPORTSUSDT', 'XPL/USDT']
    print("--- Scanning Market with Strict Rules ---")
    
    for symbol in symbols:
        try:
            df_15m = fetch_data(symbol, '15m')
            df_1h = fetch_data(symbol, '1h')
            df_4h = fetch_data(symbol, '4h')
            
            if df_15m.empty or df_1h.empty or df_4h.empty:
                continue
                
            result = analyze_market_conditions(df_15m, df_1h, df_4h)
            
            if result.get("signal") == "LONG":
                msg = (
                    f"🎯 *فرصة قنص نموذجية مؤكدة!*\n\n"
                    f"🔹 العملة: `{symbol}`\n"
                    f"🟢 الإشارة: **LONG**\n"
                    f"📍 الدخول: `{result['entry']}`\n"
                    f"🛑 الوقف: `{result['stop_loss']}`\n"
                    f"🎯 الهدف: `{result['take_profit']}`\n"
                    f"💡 السبب: {result['reason']}"
                )
                send_telegram_message(msg)
            else:
                print(f"Skipped {symbol}: {result.get('reason')}")
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    keep_alive()
    send_telegram_message("🚀 تم تشغيل النسخة الاحترافية الصارمة للبوت بنجاح.")
    
    while True:
        job()
        time.sleep(900)
