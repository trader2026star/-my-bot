# ==========================================
# MAIN SERVER SCRIPT (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
from flask import Flask, request
from analysis import StrategyEngine

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running safely with institutional rules (SMC & ICT) for Long & Short!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data:
            return "No data", 400
        
        # استخراج بيانات الإشارة الواردة (تحديد الاتجاه وسعر الدخول والمرجع الفني)
        direction = data.get('direction', 'NEUTRAL').upper() # LONG أو SHORT
        entry_price = float(data.get('entry_price', 0))
        swing_level = float(data.get('swing_level', 0))
        
        if direction in ['LONG', 'SHORT'] and entry_price > 0 and swing_level > 0:
            # تمرير البيانات لمحرك الاستراتيجية لحساب الـ Stop Loss والـ Targets
            engine = StrategyEngine(None, None)
            sl, tp1, tp2, tp3 = engine.calculate_risk_management(entry_price, direction, swing_level)
            
            print(f"Signal Received -> Direction: {direction} | Entry: {entry_price} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | TP3: {tp3}")
            # هنا يتم ربط التنفيذ الفعلي على المنصة (BingX / Binance)
            
        return "OK", 200
    except Exception as e:
        print(f"Error in webhook: {e}")
        return "Error", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
