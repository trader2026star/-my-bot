import os
import logging
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
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
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error(f"فشل إرسال رسالة تليجرام: {response.text}")
    except Exception as e:
        logger.error(f"خطأ في الاتصال بخدمة تليجرام: {e}")

# جلب مفاتيح الـ API من متغيرات البيئة في Render بأمان
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# تهيئة محرك التحليل الحتمي
analyst_engine = DeterministicTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

def run_market_scanner():
    """دالة فحص السوق التلقائية التي تعمل في الخلفية"""
    logger.info("بدء فحص السوق التلقائي في الخلفية...")
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()
        
        # اختيار العملات التي تنتهي بـ USDT:USDT (عقود فيوتشر) - أول 15 عملة
        all_symbols = [symbol for symbol in exchange.symbols if 'USDT:USDT' in symbol]
        symbols_to_scan = all_symbols[:15] 
        
        telegram_msg = "🚨 *Auto Full Market Crypto Report (BingX)* 🚀\n\n"
        
        for symbol in symbols_to_scan:
            telegram_msg += f"📊 *Symbol: {symbol}*\n"
            try:
                result = analyst_engine.evaluate_strategy(symbol=symbol, account_balance=1000.0, risk_percentage=0.01)
                for key, value in result.items():
                    telegram_msg += f"• *{key}*: {value}\n"
            except Exception as ex:
                telegram_msg += f"• Error analyzing this coin.\n"
            telegram_msg += "-------------------\n"
            
        # إرسال التقرير التلقائي إلى تيليجرام
        send_telegram_message(telegram_msg)
        logger.info("تم الانتهاء من فحص السوق التلقائي وإرسال التقرير بنجاح.")
    except Exception as e:
        logger.error(f"خطأ أثناء فحص السوق التلقائي: {e}")
        send_telegram_message(f"⚠️ *Auto Scanner Error:* {e}")

# إعداد جدول التشغيل التلقائي (يعمل تلقائياً كل ساعة مثلاً، أو يمكنك تعديل التوقيت)
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_market_scanner, trigger="interval", hours=1) # يشتغل كل ساعة تلقائياً
scheduler.start()

@app.route('/')
def home():
    """الصفحة الرئيسية للتأكد من أن السيرفر يعمل"""
    return "<h2>Deterministic Crypto Trading Bot (Auto-Scheduler Mode) is Active 🚀</h2>"

if __name__ == "__main__":
    # تشغيل سيرفر الويب لالتقاط المنفذ المطلوب من Render (افتراضياً 10000)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
