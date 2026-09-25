import logging
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
import threading
import os
import time
import requests

# إعداد اللوجز
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Expert Analyst Bot with Telegram is running perfectly!"


class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='4h'):
        self.exchange_id = exchange_id
        self.timeframe = timeframe 
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def fetch_ohlcv_data(self, symbol, timeframe, limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            return None

    def evaluate_strategy(self, symbol):
        df = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df is None or len(df) < 50:
            return None

        df['vol_ma20'] = df['volume'].rolling(window=20).mean()
        df['candle_body'] = abs(df['close'] - df['open'])
        df['body_ma20'] = df['candle_body'].rolling(window=20).mean()

        current_close = df['close'].iloc[-1]
        current_open = df['open'].iloc[-1]
        current_volume = df['volume'].iloc[-1]
        vol_ma20 = df['vol_ma20'].iloc[-1]
        
        prev_low = df['low'].iloc[-2]

        is_green_candle = current_close > current_open
        is_high_volume = current_volume > (vol_ma20 * 1.8)
        is_big_body = df['candle_body'].iloc[-1] > (df['body_ma20'].iloc[-1] * 1.5)
        
        is_valid_setup = is_green_candle and is_high_volume and is_big_body
        if not is_valid_setup:
            return None

        stop_loss = round(min(prev_low, current_close * 0.95), 4 if current_close < 1 else 2)
        risk_distance = current_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_close) * 100, 2)
        if risk_pct > 6.0:
            return None

        tp1 = round(current_close + (2.2 * risk_distance), 4 if current_close < 1 else 2)
        tp2 = round(current_close + (3.8 * risk_distance), 4 if current_close < 1 else 2)

        tp1_pct = round(((tp1 - current_close) / current_close) * 100, 2)
        tp2_pct = round(((tp2 - current_close) / current_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        report_message = f"""
🚀 رصد انفجار سيولة ونموذج ناجح (4H) 🎯
تم رصد شمعة انفجار حقيقية بفوليوم حيتان مطابقة للشروط!

🔹 العملة: ${clean_symbol}
📊 سعر الدخول / المراقبة: {current_close}

🛑 وقف الخسارة (محمي): {stop_loss} ({risk_pct}%)

🎯 الأهداف الاستثمارية:
• TP1: {tp1} (+{tp1_pct}%) [Risk/Reward 1:2.2]
• TP2: {tp2} (+{tp2_pct}%) [Risk/Reward 1:3.8]

💡 مميزات الفرصة:
✔ فوليوم تداول ضخم يفوق المتوسطات
✔ شمعة انفجار صاعدة على فريم 4 ساعات
✔ وقف خسارة محمي بعيد عن التذبذب
"""
        return report_message.strip()


def send_telegram_message(message):
    token = "8523562412:AAFegshLw8TrNcAIdDuLgm3uWc0ao9myMqo"
    chat_id = "7695985627"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logger.error(f"خطأ في إرسال رسالة تليجرام: {e}")


def bot_worker():
    # إرسال رسالة تأكيد فورية عند بدء تشغيل البوت للتأكد من أن الاتصال يعمل
    send_telegram_message("🟢 تم بدء تشغيل بوت تحليل السوق وفحص العملات بنجاح تام على السيرفر!")
    logger.info("بدء تشغيل حلقة فحص السوق الشامل...")
    bot = ExpertAnalystBot(exchange_id='bingx')
    
    symbols = [
        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT', 
        'ADA/USDT:USDT', 'AVAX/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT', 
        'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'NEAR/USDT:USDT', 'UNI/USDT:USDT', 
        'FET/USDT:USDT', 'RNDR/USDT:USDT', 'INJ/USDT:USDT', 'SUI/USDT:USDT', 
        'APT/USDT:USDT', 'ARBI/USDT:USDT', 'OP/USDT:USDT', 'PEPE/USDT:USDT', 
        'SHIB/USDT:USDT', 'WIF/USDT:USDT', 'RENDER/USDT:USDT', 'TIA/USDT:USDT'
    ]
    
    while True:
        try:
            logger.info("جاري فحص قائمة العملات الموسعة...")
            for symbol in symbols:
                signal = bot.evaluate_strategy(symbol)
                if signal:
                    send_telegram_message(signal)
                    logger.info(f"تم إرسال تنبيه للعملة: {symbol}")
                time.sleep(2)
            
            time.sleep(1800) 
        except Exception as e:
            logger.error(f"حدث خطأ في حلقة الفحص: {e}")
            time.sleep(60)

# تشغيل خيط البوت تلقائياً فور تحميل الملف بواسطة Gunicorn
bot_thread = threading.Thread(target=bot_worker, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
