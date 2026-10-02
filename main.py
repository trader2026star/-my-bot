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
    return "Elite Sniper Bot on BingX (Auto-Scan - Long & Short) is Running Safely!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# إعداد توكن تليجرام والـ Chat ID من متغيرات البيئة في Render
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

# الاتصال بمنصة BingX للعقود الآجلة (Swap)
exchange = ccxt.bingx({
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        return pd.DataFrame()

def get_active_symbols():
    try:
        exchange.load_markets()
        symbols = [
            symbol for symbol, market in exchange.markets.items() 
            if market.get('swap', False) and market.get('quote', '') == 'USDT' and market.get('active', True)
        ]
        return symbols
    except Exception as e:
        print(f"Error loading markets: {e}")
        return ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT', 'AVAX/USDT:USDT']

def job():
    print("--- Loading All BingX Markets for Auto-Scan (Long & Short) ---")
    symbols = get_active_symbols()
    print(f"Total symbols to scan: {len(symbols)}")
    
    for symbol in symbols:
        try:
            df_15m = fetch_data(symbol, '15m')
            df_1h = fetch_data(symbol, '1h')
            df_4h = fetch_data(symbol, '4h')
            df_1d = fetch_data(symbol, '1d', limit=5)
            
            if df_15m.empty or df_1h.empty or df_4h.empty:
                continue
                
            result = analyze_market_conditions(df_15m, df_1h, df_4h, df_1d)
            signal = result.get("signal")
            
            if signal in ["LONG", "SHORT"]:
                emoji_signal = "🟢 **LONG**" if signal == "LONG" else "🔴 **SHORT**"
                msg = (
                    f"🎯 *فرصة قنص نموذجية على BingX!*\n\n"
                    f"🔹 العملة: `{symbol}`\n"
                    f"⚡ الإشارة: {emoji_signal}\n"
                    f"📍 الدخول: `{result['entry']}`\n"
                    f"🛑 الوقف: `{result['stop_loss']}`\n"
                    f"🎯 الهدف: `{result['take_profit']}`\n"
                    f"💡 السبب: {result['reason']}"
                )
                send_telegram_message(msg)
        except Exception as e:
            continue
            
        time.sleep(0.5)

if __name__ == "__main__":
    keep_alive()
    send_telegram_message("🚀 تم تفعيل الفحص التلقائي الشامل لجميع عملات BingX (Long & Short + فلتر الاتجاه اليومي) بنجاح.")
    
    while True:
        job()
        time.sleep(900)
