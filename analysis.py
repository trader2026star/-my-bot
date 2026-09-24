import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='15m'):
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
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def evaluate_strategy(self, symbol):
        # جلب البيانات اللحظية على الفريم المحدد لاكتشاف أول شمعة انطلاق
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=50)
        
        if df_lower is None or len(df_lower) < 30:
            return None

        current_close = df_lower['close'].iloc[-1]
        prev_close = df_lower['close'].iloc[-2]
        
        current_open = df_lower['open'].iloc[-1]
        current_volume = df_lower['volume'].iloc[-1]
        avg_volume = df_lower['volume'].rolling(window=20).mean().iloc[-1]

        # 1. شرط "أول شمعة صعود قوية" (شمعة خضراء تبدأ الانطلاقة الآن)
        is_green_candle = current_close > current_open
        # أن تكون الشمعة الحالية أكبر وذات زخم بداية مقارنة بالسابقة وبحجم تداول مرتفع مفاجئ
        body_size = abs(current_close - current_open)
        avg_body_size = abs(df_lower['close'] - df_lower['open']).rolling(window=10).mean().iloc[-1]
        
        # الشروط لاصطياد أول شمعة بدقة بدون تأخير:
        # - شمعة خضراء صاعدة
        # - جسم الشمعة أكبر من المتوسط (بداية زخم حقيقي)
        # - حجم التداول أعلى من المتوسط المتحرك للحجوم (دخول سيولة فورية)
        is_first_breakout = is_green_candle and (body_size > avg_body_size * 1.2) and (current_volume > avg_volume * 1.5)

        if not is_first_breakout:
            return None

        # 2. قياس مسافة وقف الخسارة بدقة تحت قاع شمعة الانطلاقة مباشرة
        stop_loss = round(min(df_lower['low'].iloc[-1], current_close * 0.98), 4 if current_close < 1 else 2)
        
        risk_distance = current_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_close) * 100, 2)

        # 3. حساب الأهداف بمضاعفات المخاطرة والعائد الدقيقة (1:1.8, 1:3.0, 1:4.5)
        tp1 = round(current_close + (1.8 * risk_distance), 4 if current_close < 1 else 2)
        tp2 = round(current_close + (3.0 * risk_distance), 4 if current_close < 1 else 2)
        tp3 = round(current_close + (4.5 * risk_distance), 4 if current_close < 1 else 2)

        tp1_pct = round(((tp1 - current_close) / current_close) * 100, 2)
        tp2_pct = round(((tp2 - current_close) / current_close) * 100, 2)
        tp3_pct = round(((tp3 - current_close) / current_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        # صياغة التقرير لاقتناص البدايات المبكرة
        report_message = f"""
قناص البدايات المبكرة ⚡
(اقتناص العملة من أول شمعة انطلاق) 🤖

${clean_symbol} إشارة دخول مبكرة جداً 🚀
تم رصد أول شمعة صعود بزخم عالي وسيولة مفاجئة!

📊 بيانات التداول:
• سعر الدخول المبكر: {current_close}

🛑 وقف الخسارة: {stop_loss}
• المسافة: {risk_pct}%

🎯 الأهداف (Risk/Reward):
TP1: {tp1} (1:1.8 | +{tp1_pct}%)
TP2: {tp2} (1:3.0 | +{tp2_pct}%)
TP3: {tp3} (1:4.5 | +{tp3_pct}%)

📈 أدوات التأكيد المطبقة:
✔ اصطياد شمعة الانطلاق الأولى فوراً
✔ فلتر حجم التداول المفاجئ (Volume Spike)
✔ إدارة المخاطر الدقيقة ومضاعفات العائد
"""
        return {"Decision": report_message.strip(), "Symbol": symbol}
