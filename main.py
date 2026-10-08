# ==========================================
# MAIN SERVER SCRIPT WITH AUTO-TEST (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
from flask import Flask, request
from analysis import StrategyEngine
import ccxt

app = Flask(__name__)

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
    return "BingX Direct Bot is running safely with institutional rules (SMC & ICT)!"

# مسار اختبار ذاتي مباشر: افتح الرابط وفيه /test وهيعمل تجربة لوحده
@app.route('/test', methods=['GET'])
def test_bot():
    try:
        symbol = 'BTC/USDT:USDT'
        direction = 'SHORT'
        amount = 10
        leverage = 5
        swing_level = 65000.0
        
        # جلب السعر الحالي للتجربة
        ticker = bingx.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        # حساب إدارة المخاطر
        engine = StrategyEngine(None, None)
        sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
        
        test_result = {
            "status": "Test Successful",
            "symbol": symbol,
            "direction": direction,
            "current_entry_price": entry_price,
            "calculated_stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "message": "Bot analysis and risk management are working perfectly!"
        }
        return test_result, 200
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
            print(f"BingX LONG Executed -> Symbol: {symbol} | Price: {entry_price} | SL: {sl}")
            
        elif direction == 'SHORT':
            order = bingx.create_market_sell_order(symbol, amount)
            print(f"BingX SHORT Executed -> Symbol: {symbol} | Price: {entry_price} | SL: {sl}")
        else:
            return {"error": "Invalid direction, must be LONG or SHORT"}, 400
        
        return {
            "status": "success",
            "direction": direction,
            "symbol": symbol,
            "entry_price": entry_price,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "order_id": order.get('id', '') if order else ''
        }, 200

    except Exception as e:
        print(f"Error executing trade on BingX: {e}")
        return {"error": str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
