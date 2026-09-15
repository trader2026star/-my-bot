import os
import logging
import requests
from flask import Flask
# تم تعديل الاستيراد هنا ليتطابق مع اسم الكلاس الجديد في ملف analysis.py
from analysis import SmartMoneyTradingAnalyst

# إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🌐 إنشاء تطبيق الويب (Flask) لإرضاء منصة Render وفتح المنفذ المطلوب
app = Flask(__name__)

# إعدادات بوت تيليجرام
TELEGRAM_BOT_TOKEN = "8523562412:AAHlYdYB19cbZsVSDdVwzEePJEsdBoGRLxI"
TELEGRAM_CHAT_ID = "7695985627"

def send_telegram_message(message):
    """دالة مخصصة لإرسال رسائل أو تقارير التحليل إلى تليجرام فوراً"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error(f"فشل إرسال رسالة تليجرام: {response.text}")
    except Exception as e:
        logger.error(f"خطأ في الاتصال بخدمة تليجرام: {e}")

# جلب مفاتيح الـ API من متغيرات البيئة في Render بأمان
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# تهيئة محرك التحليل المتقدم (SMC / Market Structure)
analyst_engine = SmartMoneyTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

@app.route('/')
def home():
    """الصفحة الرئيسية لفحص سوق العقود الآجلة بالكامل وإرسال التقارير لتيليجرام"""
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()
        
        # اختيار العقود التي تنتهي بـ USDT:USDT
        all_symbols = [symbol for symbol in exchange.symbols if 'USDT:USDT' in symbol]
        symbols_to_scan = all_symbols[:15] 
        
        telegram_msg = "🚨 *Smart Money Market Report (BingX)* 🚀\n\n"
        html_output = f"<h2>Smart Money Scanner Active 🚀 (Scanned {len(symbols_to_scan)} Coins)</h2>"
        
        for symbol in symbols_to_scan:
            html_output += f"<h3>Analysis for {symbol}:</h3><ul>"
            telegram_msg += f"📊 *Symbol: {symbol}*\n"
            
            try:
                result = analyst_engine.evaluate_strategy(symbol=symbol, account_balance=1000.0, risk_percentage=0.01)
                for key, value in result.items():
                    html_output += f"<li><b>{key}:</b> {value}</li>"
                    telegram_msg += f"• *{key}*: {value}\n"
            except Exception as ex:
                html_output += f"<li><b>Error:</b> {ex}</li>"
                telegram_msg += f"• Error analyzing this coin.\n"
                
            html_output += "</ul><hr>"
            telegram_msg += "-------------------\n"
            
        send_telegram_message(telegram_msg)
        return html_output
    except Exception as e:
        error_msg = f"خطأ عام أثناء فحص السوق: {e}"
        logger.error(error_msg)
        send_telegram_message(f"⚠️ *Market Scanner Error:* {e}")
        return f"Bot is running, but encountered an error: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
