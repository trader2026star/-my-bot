import os
import time
import ccxt
import requests
from flask import Flask, jsonify
from threading import Thread

# استيراد ملف التحليل (تقدر تغير اسم الملف لـ analysis_version1 أو analysis_version2 حسب الاستراتيجية اللي هتعمدها)
import analysis

app = Flask(__name__)

# إعدادات البوت والاتصال بـ BingX عبر CCXT
exchange = ccxt.bingx({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',  # تداول العقود الآجلة (Futures)
    }
})

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram token not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def fetch_ohlcv_data(symbol):
    try:
        # جلب البيانات لثلاثة فريمات مختلفة (15دقيقة، ساعة، 4 ساعات)
        tf_15m = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        tf_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        tf_4h = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=100)
        
        import pandas as pd
        df_15m = pd.DataFrame(tf_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h = pd.DataFrame(tf_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_4h = pd.DataFrame(tf_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        return df_15m, df_1h, df_4h
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None, None, None

def run_trading_bot():
    print("Trading Bot Started with New Strategy...")
    while True:
        try:
            exchange.load_markets()
            # استخراج العملات المتاحة USDT Futures النشطة
            symbols = [s for s in exchange.symbols if '/USDT:USDT' in s or ('/USDT' in s and exchange.markets[s].get('linear', False))]
            # نختار عينة سريعة من العملات عشان الفحص
            active_symbols = symbols[:40] 

            for symbol in symbols[:30]: # فحص أول 30 عملة كمثال
                df_15m, df_1h, df_4h = fetch_ohlcv_data(symbol)
                if df_15m is not None and not df_15m.empty:
                    signal = analysis.analyze_market_conditions(df_15m, df_1h, df_4h)
                    if signal:
                        msg = (
                            f"🚀 *تنبيه صفقة جديدة (استراتيجية حديثة)* 🚀\n\n"
                            f"📌 *العملة:* `{symbol}`\n"
                            f"🟢 *الاتجاه:* `{signal['signal']}`\n"
                            f"📊 *النموذج:* `{signal['strength']}`\n"
                            f"💰 *سعر الدخول:* `{signal['entry']}`\n"
                            f"🛑 *وقف الخسارة:* `{signal['stop_loss']}`\n"
                            f"🎯 *الهدف الأول:* `{signal['tp1']}`\n"
                            f"🎯 *الهدف الثاني:* `{signal['tp2']}`\n"
                            f"🎯 *الهدف الثالث:* `{signal['tp3']}`\n"
                            f"📈 *نسبة المخاطرة للعائد:* `{signal['risk_reward']}`\n"
                            f"📊 *التغير (24س):* `{signal['change_24h']}%`\n"
                        )
                        send_telegram_message(msg)
                        time.sleep(2) # فاصل زمني بسيط بين الرسائل
                
                time.sleep(1) # فاصل بين كل عملة والثانية لتجنب الحظر من المنصة
            
            print("Completed scanning cycle. Waiting for next cycle...")
            time.sleep(300) # الانتظار 5 دقائق قبل الدورة القادمة
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(60)

@app.route('/')
def home():
    return jsonify({"status": "Active", "message": "New Strategy Trading Bot is running successfully!"})

if __name__ == '__main__':
    # تشغيل بوت التداول في خلفية منفصلة عن سيرفر Flask
    t = Thread(target=run_trading_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
