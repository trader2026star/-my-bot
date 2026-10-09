# ==========================================
# 24/7 ADVANCED MULTI-FACTOR SCANNER (main.py)
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
    return "BingX Advanced Multi-Factor Analysis Bot is running live!"

def background_scanner():
    time.sleep(10)
    send_telegram_message("🤖 *تم تشغيل المحلل الآلي الشامل بنجاح!* البوت يفحص السوق الآن بناءً على الفوليوم والزخم وتقييم النقاط.")
    
    while True:
        try:
            markets = bingx.load_markets()
            all_symbols = [
                symbol for symbol, market in markets.items() 
                if market.get('swap', False) and symbol.endswith('/USDT:USDT')
            ]
            
            engine = StrategyEngine()
            
            for symbol in all_symbols:
                try:
                    ohlcv = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=25)
                    if not ohlcv or len(ohlcv) < 20:
                        continue
                        
                    highs = [candle[2] for candle in ohlcv]
                    lows = [candle[3] for candle in ohlcv]
                    
                    # تحليل السوق عبر استراتيجية الفوليوم والزخم الجديدة
                    signal, ai_score, volume_ratio = engine.analyze_market_conditions(ohlcv)
                    
                    if signal == "NEUTRAL":
                        continue
                        
                    ticker = bingx.fetch_ticker(symbol)
                    entry_price = ticker['last']
                    
                    swing_level = min(lows) if signal in ['LONG', 'BUY'] else max(highs)
                    sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, signal, swing_level)
                    
                    # رسالة منسقة تشبه لوحة التحليل الشامل
                    msg = (
                        f"📊 *المحلل الآلي الشامل يرضد فرصة!* 📊\n\n"
                        f"🔹 *العملة:* {symbol}\n"
                        f"🟢 *الإشارة:* `{signal}`\n"
                        f"⭐ *تقييم الذكاء (AI Score):* `{ai_score}/100`\n"
                        f"📈 *حجم التداول (Volume):* `{volume_ratio}x`\n"
                        f"🔹 *سعر الدخول:* `{entry_price}`\n"
                        f"🛑 *وقف الخسارة:* `{sl}`\n"
                        f"🎯 *الهدف 1:* `{tp1}`\n"
                        f"🎯 *الهدف 2:* `{tp2}`\n"
                        f"🎯 *الهدف 3:* `{tp3}`"
                    )
                    send_telegram_message(msg)
                    
                    time.sleep(15)
                    
                except Exception as inner_err:
                    print(f"Error processing {symbol}: {inner_err}")
            
            time.sleep(600)
            
        except Exception as e:
            print(f"Global scanner error: {e}")
            time.sleep(60)

scanner_thread = threading.Thread(target=background_scanner, daemon=True)
scanner_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
