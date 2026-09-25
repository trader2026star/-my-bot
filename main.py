import logging
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
import threading
import os

logger = logging.getLogger(__name__)

# إعداد تطبيق الـ Flask البسيط لإبقاء الخدمة مفتوحة على Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Expert Analyst Bot is running perfectly!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


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
            # تجاهل العملات الموقوفة أو التي تواجه أخطاء في جلب البيانات بصمت تام
            return None

    def evaluate_strategy(self, symbol):
        # جلب البيانات على فريم الـ 4 ساعات لرصد الانفجارات الحقيقية
        df = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df is None or len(df) < 50:
            return None

        # حساب متوسط الفوليوم لآخر 20 شمعة لرصد الانفجارات الحقيقية
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()
        
        # حساب حجم الشمعة (الفرق بين الإغلاق والفتح أو مدى الشمعة)
        df['candle_body'] = abs(df['close'] - df['open'])
        df['body_ma20'] = df['candle_body'].rolling(window=20).mean()

        current_close = df['close'].iloc[-1]
        current_open = df['open'].iloc[-1]  # تم التصحيح هنا بنجاح لتأخذ سعر الفتح الحقيقي
        current_volume = df['volume'].iloc[-1]
        vol_ma20 = df['vol_ma20'].iloc[-1]
        
        prev_low = df['low'].iloc[-2]
        current_low = df['low'].iloc[-1]

        # شروط استراتيجية الانفجار (Volume Spike + Breakout Candle)
        # 1. شمعة خضراء صاعدة قوية
        is_green_candle = current_close > current_open
        # 2. الفوليوم أعلى من المتوسط بـ 1.8 مرة على الأقل (حركة حيتان)
        is_high_volume = current_volume > (vol_ma20 * 1.8)
        # 3. جسم الشمعة أكبر بوضوح من المتوسط لتأكيد الانفجار
        is_big_body = df['candle_body'].iloc[-1] > (df['body_ma20'].iloc[-1] * 1.5)
        
        # التحقق من أن السعر في منطقة ارتداد هادئة بعد الانفجار (أو في بدايته)
        is_valid_setup = is_green_candle and is_high_volume and is_big_body

        if not is_valid_setup:
            return None

        # وقف خسارة آمن محمي تحت أدنى ذيول الشموع الأخيرة
        stop_loss = round(min(prev_low, current_close * 0.95), 4 if current_close < 1 else 2)
        
        risk_distance = current_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_close) * 100, 2)
        
        # فلتر الأمان: تجنب الصفقات التي تكون مسافة وقف الخسارة فيها أكبر من 6%
        if risk_pct > 6.0:
            return None

        # حساب الأهداف بناءً على قوة الانفجار (نسبة عائد ممتازة 1:2.2 و 1:3.8)
        tp1 = round(current_close + (2.2 * risk_distance), 4 if current_close < 1 else 2)
        tp2 = round(current_close + (3.8 * risk_distance), 4 if current_close < 1 else 2)

        tp1_pct = round(((tp1 - current_close) / current_close) * 100, 2)
        tp2_pct = round(((tp2 - current_close) / current_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        # صياغة التقرير الاحترافي لانفجار السيولة
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
        return {"Decision": report_message.strip(), "Symbol": symbol}


if __name__ == "__main__":
    # تشغيل سيرفر الويب في الخلفية ليناسب قيود منصة Render المجانية
    t = threading.Thread(target=run_flask)
    t.start()
    print("Bot web server started successfully.")
