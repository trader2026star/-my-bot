import os
import random
import logging
from flask import Flask
from analysis import ExpertAnalystBot  # استيراد كلاس التحليل

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

# تهيئة محرك التحليل
analyst_engine = ExpertAnalystBot(exchange_id='bingx', api_key=API_KEY, secret_key=SECRET_KEY, timeframe='15m')

def send_telegram_message(message):
    logger.info(f"Telegram Notification: {message}")

@app.route('/')
def home():
    """رد سريع وفوري لتجنب خطأ 502 Timeout على Render"""
    return "🤖 Expert Trading Bot is Live and Running Successfully 24/7!"

@app.route('/scan')
def scan_market():
    """مسار منفصل مخصص لفحص السوق والعملات عند الحاجة"""
    try:
        exchange = analyst_engine.exchange
        exchange.load_markets()

        all_symbols = [symbol for symbol in exchange.symbols if symbol.endswith('/USDT:USDT') and not symbol.startswith('NC')]    
        sample_size = min(10, len(all_symbols))    
        symbols_to_scan = random.sample(all_symbols, sample_size)    
            
        html_output = f"<h2>Expert Fibonacci & Momentum Scanner Report 📊</h2>"    
        signals_found = 0
            
        for symbol in symbols_to_scan:    
            html_output += f"<h3>Analysis for {symbol}:</h3><ul>"    
                
            try:    
                result = analyst_engine.evaluate_strategy(symbol=symbol)    
                
                if result and isinstance(result, dict) and "Decision" in result:
                    decision_val = result["Decision"]
                    if "NO TRADE" not in decision_val:
                        signals_found += 1
                        html_output += f"<li><b>Status:</b> <span style='color:green;'>EXPERT SIGNAL FOUND 🚀</span></li>"
                        html_output += f"<li><pre>{decision_val}</pre></li>"
                        send_telegram_message(decision_val)
                    else:
                        html_output += f"<li><b>Status:</b> NO TRADE ⏳</li>"
                else:
                    html_output += f"<li><b>Status:</b> Insufficient Data or Error</li>"

                if result and isinstance(result, dict):
                    for key, value in result.items():
                        if key != "Decision":
                            html_output += f"<li><b>{key}:</b> {value}</li>"
                        
            except Exception as ex:    
                html_output += f"<li><b>Error:</b> {ex}</li>"    
                    
            html_output += "</ul><hr>"    
                
        return html_output    
    except Exception as e:    
        error_msg = f"خطأ عام أثناء فحص السوق: {e}"    
        logger.error(error_msg)    
        return f"Scanner error: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
