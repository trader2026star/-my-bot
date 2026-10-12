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
        # جلب أخر شمعة ومقارنتها بفارق الحركة والانفجار السعري
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=25)
        if not ohlcv or len(ohlcv) < 25:
            return

        last_candle = ohlcv[-1]
        prev_candles = ohlcv[:-1]

        open_price = last_candle[1]
        close_price = last_candle[4]
        high_price = last_candle[2]
        low_price = last_candle[3]
        volume = last_candle[5]

        avg_volume = sum(c[5] for c in prev_candles) / len(prev_candles)
        recent_high = max(c[2] for c in prev_candles)
        recent_low = min(c[3] for c in prev_candles)

        # فلتر الزخم الانفجاري والفوليوم العالي (نفس منطق رادار العملات الصاعدة والهابطة)
        is_pumping = volume >= (avg_volume * 2.0)
        
        # إذا حدث صنف انفجاري واخترق القمة ثم بدأ يغلق تحتها (فخ صاعد -> SHORT)
        if high_price > recent_high and close_price < recent_high and is_pumping:
            entry_price = close_price
            sl = high_price * 1.01 # وقف خسارة فوق قمة الذيل بقليل
            tp1 = entry_price * 0.98
            tp2 = entry_price * 0.95
            tp3 = entry_price * 0.92
            
            msg = (
                f"🚨 *إشارة PHOENIX SHORT مؤكدة*\n"
                f" العملة: `{symbol}`[span_9](start_span)[span_9](end_span)\n"
                f" السعر الحالي: `{entry_price}`[span_10](start_span)[span_10](end_span)\n"
                f" وقف الخسارة: `{sl:.4f}`[span_11](start_span)[span_11](end_span)\n"
                f" 🎯 الهدف الأول: `{tp1:.4f}`\n"
                f" 🎯 الهدف الثاني: `{tp2:.4f}`\n"
                f" 🎯 الهدف الثالث: `{tp3:.4f}`"
            )
            send_telegram_alert(msg)

        # إذا حدث هبوط انفجاري واخترق القاع ثم ارتد (فخ هابط -> LONG)
        elif low_price < recent_low and close_price > recent_low and is_pumping:
            entry_price = close_price
            sl = low_price * 0.99
            tp1 = entry_price * 1.02
            tp2 = entry_price * 1.05
            tp3 = entry_price * 1.08
            
            msg = (
                f"🚀 *إشارة PHOENIX LONG مؤكدة*\n"
                f" العملة: `{symbol}`\n"
                f" السعر الحالي: `{entry_price}`\n"
                f" وقف الخسارة: `{sl:.4f}`\n"
                f" 🎯 الهدف الأول: `{tp1:.4f}`\n"
                f" 🎯 الهدف الثاني: `{tp2:.4f}`\n"
                f" 🎯 الهدف الثالث: `{tp3:.4f}`"
            )
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
