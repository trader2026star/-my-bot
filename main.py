# ==========================================
# MAIN SERVER SCRIPT WITH SECURE TELEGRAM & BINGX (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
import requests
from flask import Flask, request
from analysis import StrategyEngine
import ccxt

app = Flask(__name__)

# إعدادات تليجرام بأمان من متغيرات البيئة على Render
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
        'defaultType': 'swap' # تداول عقود الـ Futures / Perpetuals
    }
})

@app.route('/')
def home():
    return "BingX Direct Bot with Secure Telegram is running safely!"

# مسار اختبار ذاتي مع إرسال إشعار لتليجرام
@app.route('/test', methods=['GET'])
def test_bot():
    try:
        symbol = 'BTC/USDT:USDT'
        direction = 'SHORT'
        amount = 10
        leverage = 5
        swing_level = 65000.0
        
        ticker = bingx.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        engine = StrategyEngine(None, None)
        sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
        
        # تجهيز رسالة التليجرام
        msg = (
            f"🚨 *تجربة ناجحة للبوت* 🚨\n\n"
            f"🔹 *العملة:* {symbol}\n"
            f"🔹 *الاتجاه:* {direction}\n"
            f"🔹 *سعر الدخول:* `{entry_price}`\n"
            f"🛑 *وقف الخسارة:* `{sl}`\n"
            f"🎯 *الهدف الأول:* `{tp1}`\n"
            f"🎯 *الهدف الثاني:* `{tp2}`\n"
            f"🎯 *الهدف الثالث:* `{tp3}`\n\n"
            f"✅ البوت متصل ويسحب البيانات بنجاح!"
        )
        
        # إرسال الرسالة إلى تليجرام
        send_telegram_message(msg)
        
        return {
            "status": "Test Successful & Telegram message sent!",
            "symbol": symbol,
            "current_entry_price": entry_price,
            "calculated_stop_loss": sl
        }, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/execute_trade', methods=['POST'])
def execute_trade():
    try:
        data = request.json
        if not data:
            return {"error": "No data provided"}, 400
        
        symbol = data.get('symbol', 'BTC/USDT:USDT')
        direction = data.get('direction', '').upper()
        amount = float(data.get('amount', 10))
        leverage = int(data.get('leverage', 5))
        swing_level = float(data.get('swing_level', 0))
        
        try:
            bingx.set_leverage(leverage, symbol)
        except Exception as lev_err:
            print(f"Leverage notice: {lev_err}")

        ticker = bingx.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        engine = StrategyEngine(None, None)
        sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
        
        order = None
        if direction == 'LONG':
            order = bingx.create_market_buy_order(symbol, amount)
        elif direction == 'SHORT':
            order = bingx.create_market_sell_order(symbol, amount)
        else:
            return {"error": "Invalid direction"}, 400
        
        # إرسال إشعار بتنفيذ الصفقة على تليجرام
        trade_msg = (
            f"🔥 *تم تنفيذ صفقة جديدة على BingX!* 🔥\n\n"
            f"🔹 *العملة:* {symbol}\n"
            f"🔹 *النوع:* {direction}\n"
            f"🔹 *سعر الدخول:* `{entry_price}`\n"
            f"🛑 *وقف الخسارة:* `{sl}`\n"
            f"🎯 *الهدف 1:* `{tp1}` | *الهدف 2:* `{tp2}` | *الهدف 3:* `{tp3}`"
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
        err_msg = f"❌ خطأ في تنفيذ الصفقة: {str(e)}"
        send_telegram_message(err_msg)
        return {"error": str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
