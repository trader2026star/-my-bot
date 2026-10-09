# ==========================================
# 24/7 AUTOMATED TRADING & SCANNER BOT (main.py)
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

# قائمة العملات المتاحة للمسح المستمر
TARGET_SYMBOLS = [
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
    'SOL/USDT:USDT',
    'XRP/USDT:USDT',
    'DOGE/USDT:USDT'
]

@app.route('/')
def home():
    return "BingX 24/7 Automated Trend Bot is running live!"

# دالة التشغيل التلقائي المستمر في الخلفية (تشتغل لوحدها 24 ساعة)
def background_scanner():
    # تأخير بسيط لحد ما السيرفر يقوم تماماً
    time.sleep(10)
    send_telegram_message("🤖 *تم تشغيل البوت بنجاح!* البوت يعمل الآن أوتوماتيكياً على مدار 24 ساعة لمراقبة السوق مع التريند.")
    
    while True:
        try:
            engine = StrategyEngine()
            for symbol in TARGET_SYMBOLS:
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
                    
                    # إرسال تنبيه بالفرصة المؤكدة أوتوماتيكياً
                    msg = (
                        f"🔥 *فرصة تلقائية جديدة مع الاتجاه!* 🔥\n\n"
                        f"🔹 *العملة:* {symbol}\n"
                        f"⚖️ *الاتجاه:* `{direction}`\n"
                        f"🔹 *سعر الدخول:* `{entry_price}`\n"
                        f"🛑 *وقف الخسارة:* `{sl}`\n"
                        f"🎯 *الهدف 1:* `{tp1}`\n"
                        f"🎯 *الهدف 2:* `{tp2}`\n"
                        f"🎯 *الهدف 3:* `{tp3}`"
                    )
                    send_telegram_message(msg)
                    
                    # الانتظار ربع ساعة بين كل عملة والتانية عشان ميكرراش الرسائل بسرعة
                    time.sleep(900)
                    
                except Exception as inner_err:
                    print(f"Error in symbol loop {symbol}: {inner_err}")
            
            # الانتظار ساعة قبل إعادة فحص السوق بالكامل
            time.sleep(3600)
            
        except Exception as e:
            print(f"Background scanner general error: {e}")
            time.sleep(60)

# تشغيل خيط الخلفية (Background Thread) أوتوماتيك مع السيرفر
scanner_thread = threading.Thread(target=background_scanner, daemon=True)
scanner_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
