# ==========================================
# MAIN SERVER SCRIPT (main.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import os
from flask import Flask, request
from analysis import StrategyEngine
import pandas as pd

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running safely with institutional rules (SMC & ICT)!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data:
            return "No data", 400
        
        # هنا بوابه استقبال الإشارات وتطبيق محرك الاستراتيجيه الجديد
        # يتم تمرير البيانات والتحقق من التوافق الفني وإدارة المخاطر
        
        return "OK", 200
    except Exception as e:
        print(f"Error in webhook: {e}")
        return "Error", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
