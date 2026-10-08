import os
import time
import ccxt
import requests
import pandas as pd
from flask import Flask, jsonify
from threading import Thread

import analysis

app = Flask(__name__)

exchange = ccxt.bingx({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
    }
})

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TOKEN")
    or ""
)

TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID")
    or os.environ.get("CHAT_ID")
    or ""
)

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception:
        return False

def fetch_ohlcv_data(symbol):
    try:
        tf_1m = exchange.fetch_ohlcv(symbol, timeframe='1m', limit=60)
        tf_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        tf_4h = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=50)
        
        if not tf_1m or not tf_15m or not tf_4h:
            return None, None, None

        df_1m = pd.DataFrame(tf_1m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_15m = pd.DataFrame(tf_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h = pd.DataFrame(tf_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df_1m[col] = pd.to_numeric(df_1m[col], errors='coerce')
            df_15m[col] = pd.to_numeric(df_15m[col], errors='coerce')
            df_4h[col] = pd.to_numeric(df_4h[col], errors='coerce')
            
        return df_1m.dropna(), df_15m.dropna(), df_4h.dropna()
    except Exception:
        return None, None, None

def get_active_symbols():
    try:
        exchange.load_markets()
        symbols = []
        for symbol, market in exchange.markets.items():
            try:
                if not market.get("swap", False) or not market.get("linear", True) or not market.get("active", True):
                    continue
                if market.get("quote", "") != "USDT":
                    continue
                base = str(market.get("base", "")).upper()
                if "NCSK" in base or "TEST" in base or ":USDT" not in symbol:
                    continue
                symbols.append(symbol)
            except Exception:
                continue
        return sorted(list(set(symbols)))
    except Exception:
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

def run_trading_bot():
    print("Strict Multi-Timeframe Bot Started...")
    while True:
        try:
            symbols = get_active_symbols()
            for symbol in symbols:
                df_1m, df_15m, df_4h = fetch_ohlcv_data(symbol)
                if df_1m is not None and not df_1m.empty:
                    signal = analysis.analyze_market_conditions(df_1m, df_15m, df_4h)
                    if signal:
                        msg = (
                            f"🚀 *تنبيه صفقة دقيقة وآمنة* 🚀\n\n"
                            f"📌 *العملة:* `{symbol}`\n"
                            f"🟢 *الاتجاه:* `{signal['signal']}`\n"
                            f"💰 *سعر الدخول:* `{signal['entry']}`\n"
                            f"🛑 *وقف الخسارة المحمي:* `{signal['stop_loss']}`\n"
                            f"🎯 *الهدف الأول:* `{signal['tp1']}`\n"
                            f"🎯 *الهدف الثاني:* `{signal['tp2']}`\n"
                            f"🎯 *الهدف الثالث:* `{signal['tp3']}`\n"
                        )
                        send_telegram_message(msg)
                        time.sleep(1)
                time.sleep(0.1)
            
            time.sleep(60)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

@app.route('/')
def home():
    return jsonify({"status": "Active", "message": "Strict Multi-Timeframe Bot is running!"})

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    t = Thread(target=run_trading_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
