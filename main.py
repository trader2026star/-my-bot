import os
import logging
import requests
import time
import gc
from flask import Flask
from analysis import SmartMoneyTradingAnalyst

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "scan_state.txt"
BATCH_SIZE = 5  # فحص 5 عملات في كل مرة لضمان عدم استهلاك الـ RAM

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

def get_next_batch(sorted_symbols):
    """إدارة دفعات السوق (5 عملات في كل دورة دون تكرار)"""
    total_symbols = len(sorted_symbols)
    if total_symbols == 0:
        return [], 0, 0
    
    index = 0
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                index = int(f.read().strip())
        except:
            index = 0
            
    if index >= total_symbols:
        index = 0
        
    end_index = min(index + BATCH_SIZE, total_symbols)
    batch = sorted_symbols[index:end_index]
    
    next_index = end_index if end_index < total_symbols else 0
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(next_index))
    except:
        pass
        
    return batch, index + 1, total_symbols

@app.route('/')
def home():
    """فحص دفعة مكونة من 5 عملات بأمان تام وتحليل مؤسسي متقدم"""
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

        symbols_to_scan, start_pos, total_market = get_next_batch(sorted_symbols)
          
        telegram_msg = f"🚨 *Institutional SMC Batch Scan ({start_pos} to {start_pos + len(symbols_to_scan) - 1} of {total_market})* 🚀\n\n"  
        html_output = f"<h2>Institutional Scanner 🚀 (Batch Range: {start_pos} - {start_pos + len(symbols_to_scan) - 1})</h2>"  
          
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
            
            # مهلة صغيرة بين كل عملة والأخرى وتفريغ الذاكرة
            time.sleep(1)
            gc.collect()
              
        # إرسال التقرير لتليجرام للدفعة الحالية
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
