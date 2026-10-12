import os
from flask import Flask, request, jsonify
import ccxt
import requests

app = Flask(__name__)

# إعداد منصة التداول
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "YOUR_CHAT_ID")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

def analyze_and_execute(symbol):
    try:
        # جلب أخر 21 شمعة على فريم 15 دقيقة
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=21)
        if not ohlcv or len(ohlcv) < 21:
            return

        last_closed_candle = ohlcv[-2]  
        prev_candles = ohlcv[:-2]       

        close_price = last_closed_candle[4]
        volume = last_closed_candle[5]

        avg_volume = sum(c[5] for c in prev_candles) / len(prev_candles)
        recent_high = max(c[2] for c in prev_candles)
        recent_low = min(c[3] for c in prev_candles)

        high_volume = volume >= (avg_volume * 1.5)
        closed_above = close_price > recent_high
        closed_below = close_price < recent_low

        if closed_above and high_volume:
            msg = f"🚀 *إشارة LONG مؤكدة (إغلاق شمعة)*\nالعملة: `{symbol}`\nسعر الدخول: `{close_price}`"
            send_telegram_alert(msg)
        elif closed_below and high_volume:
            msg = f"📉 *إشارة SHORT مؤكدة (إغلاق شمعة)*\nالعملة: `{symbol}`\nسعر الدخول: `{close_price}`"
            send_telegram_alert(msg)

    except Exception as e:
        print(f"Analysis error for {symbol}: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    symbol = data.get('symbol', 'BTC/USDT')
    analyze_and_execute(symbol)
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
