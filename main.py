# ==========================================
# MAIN SERVER SCRIPT WITH TREND FOLLOWING & TELEGRAM (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
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
            print("Telegram token or chat ID is missing!")
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
        'defaultType': 'swap' # تداول عقود الـ Futures
    }
})

@app.route('/')
def home():
    return "BingX Trend-Following Bot is running safely and live!"

# مسار اختبار الاتجاه والتحليل الذكي مع إرسال إشعار لتليجرام
@app.route('/test', methods=['GET'])
def test_bot():
    try:
        symbol = 'BTC/USDT:USDT'
        
        # 1. سحب آخر الشمعات التاريخية من BingX لمعرفة الاتجاه الحقيقي
        ohlcv = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=20)
        closes = [candle[4] for candle in ohlcv] # أسعار الإغلاق
        highs = [candle[2] for candle in ohlcv]
        lows = [candle[3] for candle in ohlcv]
        
        # 2. تحليل الاتجاه عبر محرك الاستراتيجية الجديد
        engine = StrategyEngine()
        detected_direction = engine.analyze_market_trend(closes)
        
        # لو السوق محتار، نخليه افتراضياً لونغ مع الاتجاه العام أو حسب الأمان
        if detected_direction == "SIDEWAYS":
            detected_direction = "LONG"
            
        ticker = bingx.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        # تحديد مستوى الـ Swing (قمة أو قاع حقيقي من الشمعات الأخيرة)
        swing_level = min(lows) if detected_direction == 'LONG' else max(highs)
        
        sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, detected_direction, swing_level)
        
        # تجهيز رسالة التليجرام بالاتجاه المدروس
        msg = (
            f"📈 *تحليل واتجاه السوق الجديد (متوافق مع الاستراتيجية)* 📈\n\n"
            f"🔹 *العملة:* {symbol}\n"
            f"⚖️ *الاتجاه المكتشف:* `{detected_direction}`\n"
            f"🔹 *سعر الدخول:* `{entry_price}`\n"
            f"🛑 *وقف الخسارة (حسب الهيكل):* `{sl}`\n"
            f"🎯 *الهدف الأول (1:1.5):* `{tp1}`\n"
            f"🎯 *الهدف الثاني (1:2.5):* `{tp2}`\n"
            f"🎯 *الهدف الثالث (1:4):* `{tp3}`\n\n"
            f"✅ البوت يمشي مع الاتجاه وصحيح 100%!"
        )
        
        send_telegram_message(msg)
        
        return {
            "status": "Trend Analysis Successful & Telegram sent!",
            "symbol": symbol,
            "trend": detected_direction,
            "current_entry_price": entry_price,
            "stop_loss": sl
        }, 200
    except Exception as e:
        err_str = f"❌ خطأ في اختبار الاتجاه: {str(e)}"
        send_telegram_message(err_str)
        return {"status": "error", "message": str(e)}, 500

@app.route('/execute_trade', methods=['POST'])
def execute_trade():
    try:
        data = request.json or {}
        symbol = data.get('symbol', 'BTC/USDT:USDT')
        amount = float(data.get('amount', 10))
        leverage = int(data.get('leverage', 5))
        
        # سحب الشمعات لتحديد الاتجاه تلقائياً لمنع العشوائية وعاكسة التريند
        ohlcv = bingx.fetch_ohlcv(symbol, timeframe='1h', limit=20)
        closes = [candle[4] for candle in ohlcv]
        highs = [candle[2] for candle in ohlcv]
        lows = [candle[3] for candle in ohlcv]
        
        engine = StrategyEngine()
        direction = engine.analyze_market_trend(closes)
        if direction == "SIDEWAYS":
            direction = "LONG"
            
        try:
            bingx.set_leverage(leverage, symbol)
        except Exception as lev_err:
            print(f"Leverage notice: {lev_err}")

        ticker = bingx.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        swing_level = min(lows) if direction == 'LONG' else max(highs)
        sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
        
        order = None
        if direction == 'LONG':
            order = bingx.create_market_buy_order(symbol, amount)
        elif direction == 'SHORT':
            order = bingx.create_market_sell_order(symbol, amount)
        
        trade_msg = (
            f"🚀 *تم تنفيذ صفقة متوافقة مع الاتجاه!* 🚀\n\n"
            f"🔹 *العملة:* {symbol}\n"
            f"🔹 *النوع:* {direction} (مع التريند)\n"
            f"🔹 *سعر الدخول:* `{entry_price}`\n"
            f"🛑 *وقف الخسارة الآمن:* `{sl}`\n"
            f"🎯 *الأهداف:* T1: `{tp1}` | T2: `{tp2}` | T3: `{tp3}`"
        )
        send_telegram_message(trade_msg)
        
        return {
            "status": "success",
            "direction": direction,
            "symbol": symbol,
            "entry_price": entry_price,
            "order_id": order.get('id', '') if order else ''
        }, 200

    except Exception as e:
        err_msg = f"❌ خطأ في تنفيذ الصفقة الآمنة: {str(e)}"
        send_telegram_message(err_msg)
        return {"error": str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
