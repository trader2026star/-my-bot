import os
import logging
import requests
from flask import Flask
from analysis import SmartMoneyTradingAnalyst

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

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
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        logger.error(f"خطأ في الاتصال بخدمة تليجرام: {e}")

API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

analyst_engine = SmartMoneyTradingAnalyst(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY)

@app.route('/')
def home():
    """فحص أقوى 30 عملة بناءً على حجم التداول (Volume) واستخراج الفرص المؤسسية"""
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()

        tickers = exchange.fetch_tickers()
        valid_symbols = [symbol for symbol in exchange.symbols if symbol.endswith('/USDT:USDT') and not symbol.startswith('NC')]  
          
        sorted_symbols = sorted(
            valid_symbols,
            key=lambda s: tickers.get(s, {}).get('quoteVolume', 0),
            reverse=True
        )

        # تم زيادة العدد إلى 30 عملة للبحث في نطاق أوسع من السوق
        symbols_to_scan = sorted_symbols[:30]
          
        telegram_msg = f"🚨 *Smart Money Volume-Scan Report (BingX - Top 30)* 🚀\n\n"  
        html_output = f"<h2>Smart Money Scanner Active 🚀 (Top 30 Volume Coins Batch)</h2>"  
          
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
