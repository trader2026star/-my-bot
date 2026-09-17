import os
import random
import logging
import requests
import time
import threading
from flask import Flask
from analysis import SmartMoneyTradingAnalyst

# إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# قراءة مفاتيح تيليجرام بأمان تام من متغيرات البيئة (Render Environment Variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("خطأ: مفاتيح تيليجرام غير مُعرفة في متغيرات البيئة.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error(f"فشل إرسال رسالة تليجرام. رمز الحالة: {response.status_code}")
    except Exception as e:
        logger.error(f"خطأ في الاتصال بخدمة تليجرام: {e}")

API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# تهيئة محرك التحليل والماتش المالي
analyst_engine = SmartMoneyTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

def run_market_scan():
    """الدالة المسؤولة عن معالجة البيانات وفحص السوق وإرسال التقارير"""
    try:
        logger.info("بدء جولة فحص السوق الذكية الحالية...")
        exchange = analyst_engine.exchange
        exchange.load_markets()
        
        # تصفية أزواج العملات الحقيقية فقط المتاحة للتداول بنظام الـ Swap
        all_symbols = [symbol for symbol in exchange.symbols if symbol.endswith('/USDT:USDT') and not symbol.startswith('NC')]
        
        if not all_symbols:
            logger.warning("لم يتم العثور على أزواج تداول صالحة تنتهي بـ /USDT:USDT")
            return "No valid symbols found.", "No symbols to scan."

        # اختيار عينة عشوائية مكونة من 10 عملات
        sample_size = min(10, len(all_symbols))
        symbols_to_scan = random.sample(all_symbols, sample_size)
        
        telegram_msg = f"🚨 *Smart Money Rotating Report (BingX)* 🚀\n\n"
        html_output = f"<h2>Smart Money Scanner Active 🚀 (Clean Real Coins Batch)</h2>"
        
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
        logger.info("تم الانتهاء من الفحص بنجاح وإرسال التقرير المالي للتليجرام.")
        return html_output
    except Exception as e:
        error_msg = f"خطأ عام أثناء فحص السوق: {e}"
        logger.error(error_msg)
        send_telegram_message(f"⚠️ *Market Scanner Error:* {e}")
        return f"Bot encountered an error during scan: {e}"

def autonomous_worker():
    """حلقة مفرغة تعمل في الخلفية لضمان استمرارية عمل البوت تلقائياً كل ساعة دون توقف"""
    logger.info("بدء تشغيل عامل الخلفية الآلي المستقل...")
    # انتظر قليلاً حتى يستقر خادم الويب الأساسي عند بدء التشغيل لأول مرة
    time.sleep(10) 
    while True:
        try:
            run_market_scan()
        except Exception as e:
            logger.error(f"خطأ غير متوقع في خادم الخلفية: {e}")
        
        # الفحص التلقائي المتكرر كل ساعة واحدة (3600 ثانية)
        logger.info("في انتظار دورة الفحص القادمة بعد ساعة...")
        time.sleep(3600)

@app.route('/')
def home():
    """رابط الـ Health Check الأساسي لمنصة Render لرد فوري ومنع حدوث خطأ 502"""
    return "Bot Core Service is Online & Running Perfectly! 🟢"

@app.route('/scan')
def manual_scan():
    """رابط إضافي في حال أردت تفعيل الفحص اليدوي فوراً عبر المتصفح"""
    html_result = run_market_scan()
    return html_result

if __name__ == "__main__":
    # تشغيل نظام الفحص التلقائي في الخلفية في مسار منفصل (Thread) لعدم تعطيل خادم Flask
    worker_thread = threading.Thread(target=autonomous_worker)
    worker_thread.daemon = True
    worker_thread.start()

    # تشغيل خادم الويب بالمنفذ الذي يحدده Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
