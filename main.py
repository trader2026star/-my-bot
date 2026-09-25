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
    return "Optimized SMC Analyst Bot is running perfectly!"


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

    def fetch_ohlcv_data(self, symbol, timeframe, limit=120):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            return None

    def evaluate_smc_strategy(self, symbol):
        df = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=120)
        
        if df is None or len(df) < 60:
            return None

        # حساب المتوسطات ومؤشرات السيولة
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()
        df['candle_body'] = abs(df['close'] - df['open'])
        df['body_ma20'] = df['candle_body'].rolling(window=20).mean()

        # بيانات الشمعة الحالية
        curr_close = df['close'].iloc[-1]
        curr_open = df['open'].iloc[-1]
        curr_vol = df['volume'].iloc[-1]
        vol_ma20 = df['vol_ma20'].iloc[-1]

        # شروط مرنة وأسرع للـ SMC (تخفيف الشروط قليلاً لالتقاط صفقات أسرع)
        # 1. كسر مقاومة أخر 10 شمعات (بدل 15 عشان نسرع الفرص)
        recent_resistance = df['high'].iloc[-10:-2].max()
        is_bos = curr_close > recent_resistance
        
        # 2. فوليوم متحسن (أعلى من المتوسط بـ 1.3 ضعف بدل 2.0)
        is_whale_volume = curr_vol > (vol_ma20 * 1.3)
        
        # 3. جسم شمعة جيد
        is_strong_body = df['candle_body'].iloc[-1] > (df['body_ma20'].iloc[-1] * 1.2)
        
        # فلتر اتجاه مرن (المتوسط المتحرك 30 بدل 50)
        df['ma30'] = df['close'].rolling(window=30).mean()
        is_bullish_trend = curr_close > df['ma30'].iloc[-1]

        # جمع الشروط المعدلة
        if not (is_bos and is_whale_volume and is_strong_body and is_bullish_trend):
            return None

        # تحديد الوقف والأهداف
        structure_low = df['low'].iloc[-4:-1].min()
        stop_loss = round(min(structure_low, curr_close * 0.97), 4 if curr_close < 1 else 2)
        
        risk_distance = curr_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / curr_close) * 100, 2)
        if risk_pct > 7.0: 
            return None

        tp1 = round(curr_close + (2.0 * risk_distance), 4 if curr_close < 1 else 2)
        tp2 = round(curr_close + (3.5 * risk_distance), 4 if curr_close < 1 else 2)

        tp1_pct = round(((tp1 - curr_close) / curr_close) * 100, 2)
        tp2_pct = round(((tp2 - curr_close) / curr_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        report_message = f"""
🏛️ **تقرير فرصة صانع السوق (SMC مخصص) - 4H** 🚀
تم رصد اختراق هيكلي وسيولة ممتازة بنجاح!

🔹 **العملة:** `${clean_symbol}`
📊 **سعر الدخول:** `{curr_close}`

🛑 **وقف الخسارة (SL):** `{stop_loss}` (`{risk_pct}%`)

🎯 **الأهداف:**
• **TP1:** `{tp1}` (`+{tp1_pct}%`) [R:R 1:2.0]
• **TP2:** `{tp2}` (`+{tp2_pct}%`) [R:R 1:3.5]

💡 **تفاصيل الفرصة:**
✔ اختراق هادئ وفعلي لمقاومة قريبة
✔ فوليوم تداول داعم ومناسب
✔ اتجاه عام صاعد مدعوم بالمتوسط
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
    send_telegram_message("⚡ تم تحديث وضبط إعدادات البوت لتكون أكثر مرونة وسرعة في رصد الصفقات...")
    logger.info("بدء تشغيل حلقة الفحص المعدلة...")
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
            logger.info("جاري فحص العملات بالإضافة للتحسينات الجديدة...")
            for symbol in symbols:
                signal = bot.evaluate_smc_strategy(symbol)
                if signal:
                    send_telegram_message(signal)
                    logger.info(f"تم إرسال تنبيه للعملة: {symbol}")
                time.sleep(2)
            
            # تقليل وقت الانتظار قليلاً أو إبقاؤه على 30 دقيقة
            time.sleep(1200) 
        except Exception as e:
            logger.error(f"حدث خطأ في حلقة الفحص: {e}")
            time.sleep(60)

bot_thread = threading.Thread(target=bot_worker, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
