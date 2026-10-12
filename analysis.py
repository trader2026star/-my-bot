from flask import Flask, request, jsonify
import ccxt
import pandas as pd
import numpy as np
import requests

app = Flask(__name__)

# إعداد منصة التداول (مثال: Binance Futures)
exchange = ccxt.binance({
    'options': {
        'defaultType': 'future',
    },
    'enableRateLimit': True
})

TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

def send_telegram_alert(message):
    """إرسال تنبيهات تليجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_market_data(symbol, timeframe='15m', limit=100):
    """جلب بيانات الشموع التاريخية والفوليوم"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def analyze_and_execute(symbol):
    """التحليل الفني وتطبيق شروط التأكيد الجديدة"""
    df = fetch_market_data(symbol, timeframe='15m', limit=50)
    if df is None or len(df) < 20:
        return

    # حساب المتوسط المتحرك للفوليوم
    df['avg_volume'] = df['volume'].rolling(window=20).mean()
    
    # تحديد القمم والقيعان الأخيرة للسيولة (مثال مبسط لاختبار القمة/القاع السابقة)
    recent_high = df['high'].iloc[-20:-1].max()
    recent_low = df['low'].iloc[-20:-1].min()

    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]

    # --- تطبيق الفلاتر الجديدة للحماية ---
    
    # 1. فلتر الفوليوم المؤسسي (أكبر من 1.5 ضعف المتوسط)
    high_volume_confirmed = last_candle['volume'] >= (last_candle['avg_volume'] * 1.5)
    
    # 2. فلتر إغلاق الشمعة (يجب أن تغلق الشمعة بالكامل فوق/تحت مستوى السيولة وليس مجرد ذيل)
    candle_closed_above = last_candle['close'] > recent_high
    candle_closed_below = last_candle['close'] < recent_low

    # تنفيذ الإشارة بناءً على التأكيد الحقيقي
    if candle_closed_above and high_volume_confirmed:
        msg = f"🚀 *إشارة شراء مؤكدة (LONG)*\nالعملة: `{symbol}`\nسعر الدخول بعد الإغلاق: `{last_candle['close']}`\nالفوليوم: مؤكد وصاعد"
        send_telegram_alert(msg)
        
    elif candle_closed_below and high_volume_confirmed:
        msg = f"📉 *إشارة بيع مؤكدة (SHORT)*\nالعملة: `{symbol}`\nسعر الدخول بعد الإغلاق: `{last_candle['close']}`\nالفوليوم: مؤكد وهابط"
        send_telegram_alert(msg)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    symbol = data.get('symbol', 'BTC/USDT')
    analyze_and_execute(symbol)
    return jsonify({"status": "success", "message": "Analyzed with candle confirmation"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
