import os
import logging
from flask import Flask
from analysis import DeterministicTradingAnalyst

# إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 🌐 إنشاء تطبيق الويب (Flask) لإرضاء منصة Render وفتح المنفذ المطلوب
app = Flask(__name__)

# جلب مفاتيح الـ API من متغيرات البيئة في Render بأمان
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# تهيئة محرك التحليل الحتمي
analyst_engine = DeterministicTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

@app.route('/')
def home():
    """الصفحة الرئيسية لتشغيل السيرفر وعرض آخر نتيجة تحليل فوري لعملة BTC"""
    try:
        # تنفيذ التحليل الرياضي الحتمي على زوج BTC/USDT
        result = analyst_engine.evaluate_strategy(symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01)
        
        # تنسيق النتيجة لعرضها بشكل جميل على متصفح الويب
        html_output = "<h2>Deterministic Crypto Trading Bot is Active 🚀</h2>"
        html_output += "<h3>Latest Market Analysis Report:</h3><ul>"
        for key, value in result.items():
            html_output += f"<li><b>{key}:</b> {value}</li>"
        html_output += "</ul>"
        return html_output
    except Exception as e:
        logger.error(f"خطأ أثناء جلب التحليل في صفحة الويب: {e}")
        return f"Bot is running, but encountered an error during analysis: {e}"

if __name__ == "__main__":
    # تشغيل سيرفر الويب لالتقاط المنفذ المطلوب من Render (افتراضياً 10000)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
