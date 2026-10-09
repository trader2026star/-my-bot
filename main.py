# ==========================================
# FULL AUTOMATED MARKET SCANNER & BOT (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
import time
import requests
from flask import Flask, request
from analysis import StrategyEngine
import ccxt

app = Flask(__name__)

# إعدادات تليجرام الآمنة من متغيرات البيئة على Render
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def send_telegram_message(message):
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

# إعدادات ربط منصة BingX عبر API
bingx = ccxt.bingx({
    'apiKey': os.environ.get('BINGX_API_KEY', ''),
    'secret': os.environ.get('BINGX_SECRET_KEY', ''),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap'
    }
})

# قائمة العملات القوية اللي البوت هيعملها مسح أوتوماتيك
TARGET_SYMBOLS = [
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
    'SOL/USDT:USDT',
    'XRP/USDT:USDT',
    'DOGE/USDT:USDT',
    'ADA/USDT:USDT'
]

@app.route('/')
def home():
    return "BingX Fully Automated Market Scanner is running live!"

# مسار لفحص وتحليل السوق كله أوتوماتيك وإرسال النتائج لتليجرام
@app.route('/scan_market', methods=['GET'])
def scan_market():
    results = []
    engine = StrategyEngine()
    
    for symbol in TARGET_SYMBOLS:
        try:
            # 1. سحب الشمعات لكل عملة
            ohlcv = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=20)
            if not ohlcv or len(ohlcv) < 10:
                continue
                
            closes = [candle[4] for candle in ohlcv]
            highs = [candle[2] for candle in ohlcv]
            lows = [candle[3] for candle in ohlcv]
            
            # 2. تحليل الاتجاه
            direction = engine.analyze_market_trend(closes)
            if direction == "SIDEWAYS":
                continue # لو السوق عرضي، سيبك منها وروح لغيرها
                
            ticker = bingx.fetch_ticker(symbol)
            entry_price = ticker['last']
            
            swing_level = min(lows) if direction == 'LONG' else max(highs)
            sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
            
            # تجهيز وإرسال إشعار فوري للعملة اللي تم رصدها
            msg = (
                f"🚨 *فرصة مؤكدة بروح التريند!* 🚨\n\n"
                f"🔹 *العملة:* {symbol}\n"
                f"⚖️ *الاتجاه:* `{direction}`\n"
                f"🔹 *سعر الدخول:* `{entry_price}`\n"
                f"🛑 *وقف الخسارة:* `{sl}`\n"
                f"🎯 *الهدف 1:* `{tp1}`\n"
                f"🎯 *الهدف 2:* `{tp2}`\n"
                f"🎯 *الهدف 3:* `{tp3}`"
            )
            send_telegram_message(msg)
            results.append({"symbol": symbol, "direction": direction, "status": "Alert sent"})
            
        except Exception as ex:
            print(f"Error scanning {symbol}: {ex}")
            
    return {"status": "Scan completed", "scanned_pairs": results}, 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
