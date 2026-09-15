import os
import logging
import requests
from flask import Flask
from analysis import DeterministicTradingAnalyst

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
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"فشل إرسال رسالة تليجرام: {response.text}")
    except Exception as e:
        logger.error(f"خطأ في الاتصال بخدمة تليجرام: {e}")

# جلب مفاتيح الـ API من متغيرات البيئة في Render بأمان
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# تهيئة محرك التحليل الحتمي
analyst_engine = DeterministicTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

@app.route('/')
def home():
    """الصفحة الرئيسية لتشغيل السيرفر وعرض آخر نتيجة تحليل فوري لعملة BTC وإرسالها لتليجرام"""
    try:
        # تنفيذ التحليل الرياضي الحتمي على زوج BTC/USDT
        result = analyst_engine.evaluate_strategy(symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01)
        
        # تنسيق رسالة تيليجرام
        telegram_msg = "🚨 *Deterministic Crypto Bot Report* 🚀\n\n"
        html_output = "<h2>Deterministic Crypto Trading Bot is Active 🚀</h2>"
        html_output += "<h3>Latest Market Analysis Report:</h3><ul>"
        
        for key, value in result.items():
            html_output += f"<li><b>{key}:</b> {value}</li>"
            telegram_msg += f"• *{key}*: {value}\n"
            
        html_output += "</ul>"
        
        # إرسال التقرير إلى تيليجرام
        send_telegram_message(telegram_msg)
        
        return html_output
    except Exception as e:
        error_msg = f"خطأ أثناء جلب التحليل في صفحة الويب: {e}"
        logger.error(error_msg)
        send_telegram_message(f"⚠️ *Bot Error:* {e}")
        return f"Bot is running, but encountered an error during analysis: {e}"

if __name__ == "__main__":
    # تشغيل سيرفر الويب لالتقاط المنفذ المطلوب من Render (افتراضياً 10000)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
