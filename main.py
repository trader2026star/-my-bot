import time
import ccxt
import pandas as pd
from flask import Flask
from threading import Thread
from analysis import analyze_market_conditions
# استدعاء دالة إرسال الإشعارات إلى تليجرام الخاصة بك
from telegram import send_telegram_message  # أو حسب اسم مكتبتك الحالية

app = Flask('')

@app.route('/')
def home():
    return "CISD Elite Sniper Bot is Active and Running Safely!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# إعداد اتصال المنصة عبر CCXT (مثلاً باينناس)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}  # العمل على العقود الآجلة
})

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()

def job():
    # قائمة العملات التي يتم مراقبتها
    symbols = ['BRUSDT.P', 'ESPORTSUSDT', 'XPL/USDT']
    
    print("--- Running Market Scan with Strict Elite Rules ---")
    
    for symbol in symbols:
        try:
            # جلب الفريمات المختلفة للتأكد من الشروط الصارمة
            df_15m = fetch_data(symbol, '15m')
            df_1h = fetch_data(symbol, '1h')
            df_4h = fetch_data(symbol, '4h')
            
            if df_15m.empty or df_1h.empty or df_4h.empty:
                continue
                
            # تشغيل التحليل الصارم
            result = analyze_market_conditions(df_15m, df_1h, df_4h)
            
            if result.get("signal") == "LONG":
                msg = (
                    f"🎯 **تم رصد فرصة قنص نموذجية!**\n\n"
                    f"🔹 العملة: `{symbol}`\n"
                    f"🟢 الإشارة: **LONG**\n"
                    f"📍 سعر الدخول: `{result['entry']}`\n"
                    f"🛑 وقف الخسارة (Stop Loss): `{result['stop_loss']}`\n"
                    f"🎯 الهدف المقترح (Take Profit): `{result['take_profit']}`\n"
                    f"💡 السبب: {result['reason']}"
                )
                send_telegram_message(msg)
                print(f"Signal sent for {symbol}")
            else:
                print(f"Skipped {symbol}: {result.get('reason')}")
                
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    keep_alive()
    send_telegram_message("🚀 تم تشغيل بوت القنص الصارم بنجاح ويراقب السوق بأمان تام.")
    
    while True:
        job()
        # فحص السوق كل 15 دقيقة لتجنب كثرة العمليات وتخفيف الاستهلاك
        time.sleep(900)
