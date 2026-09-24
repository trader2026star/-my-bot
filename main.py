import os
import random
import logging
import requests
from flask import Flask
from analysis import ExpertAnalystBot

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

# بيانات تليجرام الخاصة بك
TELEGRAM_TOKEN = "8523562412:AAFegshLw8TrNcAIdDuLgm3uWc0ao9myMqo"
TELEGRAM_CHAT_ID = "7695985627"

# تهيئة محرك التحليل على فريم الـ 4 ساعات الآمن
analyst_engine = ExpertAnalystBot(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY, timeframe='4h')

def send_telegram_message(message):
    """إرسال الصفقات الحقيقية والمدروسة مباشرة إلى تليجرام"""
    logger.info(f"Telegram Notification: {message}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram message sent successfully to bot!")
            else:
                logger.error(f"Failed to send telegram message: {response.text}")
        except Exception as e:
            logger.error(f"Error sending message to telegram: {e}")
    else:
        logger.warning("⚠️ TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is missing!")

@app.route('/')
def home():
    """فحص هادئ ومستقر للعملات على فريم الأربع ساعات"""
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()

        all_symbols = [symbol for symbol in exchange.symbols if symbol.endswith('/USDT:USDT') and not symbol.startswith('NC')]    
        
        sample_size = min(15, len(all_symbols))    
        symbols_to_scan = random.sample(all_symbols, sample_size)    
            
        signals_found = 0
            
        for symbol in symbols_to_scan:    
            try:    
                result = analyst_engine.evaluate_strategy(symbol=symbol)    
                if result and isinstance(result, dict) and "Decision" in result:
                    decision_val = result["Decision"]
                    signals_found += 1
                    send_telegram_message(decision_val)
            except Exception as ex:    
                logger.error(f"Error in symbol {symbol}: {ex}")

        return f"🛡️ Safe Trend Bot Running (4H)! Scanned {sample_size} symbols. High-quality signals found: {signals_found}"
    except Exception as e:
        return f"Bot is active, loop running: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
