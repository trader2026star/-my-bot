# ==========================================
# 24/7 FULL MARKET SCANNER (All Coins) (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
import time
import threading
import requests
from flask import Flask
from analysis import StrategyEngine
import ccxt

app = Flask(__name__)

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

bingx = ccxt.bingx({
    'apiKey': os.environ.get('BINGX_API_KEY', ''),
    'secret': os.environ.get('BINGX_SECRET_KEY', ''),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap'
    }
})

@app.route('/')
def home():
    return "BingX Full Market Scanner (All Coins) is running live!"

def background_scanner():
    time.sleep(10)
    send_telegram_message("🤖 *تم تشغيل ماسح السوق الشامل!* البوت هيسحب كل عملات المنصة أوتوماتيك ويفحص السوق بالكامل.")
    
    while True:
        try:
            # 1. سحب كل الأسواق المتاحة على المنصة أوتوماتيك
            markets = bingx.load_markets()
            
            # تصفية العملات لجلب عقود الـ USDT المتاحة فقط
            all_symbols = [
                symbol for symbol, market in markets.items() 
                if market.get('swap', False) and symbol.endswith('/USDT:USDT')
            ]
            
            engine = StrategyEngine()
            
            # لفة على جميع عملات السوق بدون استثناء
            for symbol in all_symbols:
                try:
                    ohlcv = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=20)
                    if not ohlcv or len(ohlcv) < 10:
                        continue
                        
                    closes = [candle[4] for candle in ohlcv]
                    highs = [candle[2] for candle in ohlcv]
                    lows = [candle[3] for candle in ohlcv]
                    
                    direction = engine.analyze_market_trend(closes)
                    if direction == "SIDEWAYS":
                        continue
                        
                    ticker = bingx.fetch_ticker(symbol)
                    entry_price = ticker['last']
                    
                    swing_level = min(lows) if direction == 'LONG' else max(highs)
                    sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
                    
                    msg = (
                        f"🔥 *فرصة جديدة من قلب السوق!* 🔥\n\n"
                        f"🔹 *العملة:* {symbol}\n"
                        f"⚖️ *الاتجاه:* `{direction}`\n"
                        f"🔹 *سعر الدخول:* `{entry_price}`\n"
                        f"🛑 *وقف الخسارة:* `{sl}`\n"
                        f"🎯 *الهدف 1:* `{tp1}`\n"
                        f"🎯 *الهدف 2:* `{tp2}`\n"
                        f"🎯 *الهدف 3:* `{tp3}`"
                    )
                    send_telegram_message(msg)
                    
                    # مهلة قصيرة بين كل عملة والتانية عشان مانعملش ضغط على السيرفر والمنصة
                    time.sleep(10)
                    
                except Exception as inner_err:
                    print(f"Error processing {symbol}: {inner_err}")
            
            # استراحة قبل بدء مسح السوق بالكامل من جديد
            time.sleep(600)
            
        except Exception as e:
            print(f"Global scanner error: {e}")
            time.sleep(60)

scanner_thread = threading.Thread(target=background_scanner, daemon=True)
scanner_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
