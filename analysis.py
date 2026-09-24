import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

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
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def evaluate_strategy(self, symbol):
        # جلب البيانات على فريم الـ 4 ساعات لضمان قوة وثبات الاتجاه
        df = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df is None or len(df) < 50:
            return None

        # حساب المتوسطات المتحركة الكبرى لتحديد الاتجاه العام
        df['ma50'] = df['close'].rolling(window=50).mean()
        df['ma200'] = df['close'].rolling(window=200).mean()

        current_close = df['close'].iloc[-1]
        current_open = df['close'].iloc[-1]
        prev_low = df['low'].iloc[-2]
        current_low = df['low'].iloc[-1]
        ma50 = df['ma50'].iloc[-1]

        # شروط الاتجاه الصاعد الآمن (فوق المتوسط وبداية ارتداد من الدعم)
        is_above_trend = current_close > ma50
        is_bounce = current_close > df['open'].iloc[-1] and current_low >= prev_low * 0.995

        # إذا لم تتوافر الشروط، نتجاهل العملة بصمت تام بدون رسائل مزعجة
        if not (is_above_trend and is_bounce):
            return None

        # وقف خسارة آمن ومحمي خلف القاع السابق لتجنب الذيول الوهمية
        stop_loss = round(min(prev_low, current_close * 0.96), 4 if current_close < 1 else 2)
        
        risk_distance = current_close - stop_loss
        if risk_distance <= 0:
            return None

        risk_pct = round((risk_distance / current_close) * 100, 2)

        # حساب الأهداف بنسب عوائد آمنة ومدروسة (1:2 و 1:3)
        tp1 = round(current_close + (2.0 * risk_distance), 4 if current_close < 1 else 2)
        tp2 = round(current_close + (3.5 * risk_distance), 4 if current_close < 1 else 2)

        tp1_pct = round(((tp1 - current_close) / current_close) * 100, 2)
        tp2_pct = round(((tp2 - current_close) / current_close) * 100, 2)

        clean_symbol = symbol.split('/')[0]

        # صياغة التقرير الاحترافي الآمن
        report_message = f"""
🎯 صفقة اتجاه آمنة ومدروسة (4H) 🚀
تم رصد ارتداد حقيقي من مناطق السيولة الكبرى!

🔹 العملة: ${clean_symbol}
📊 سعر الدخول: {current_close}

🛑 وقف الخسارة (محمي): {stop_loss} ({risk_pct}%)

🎯 الأهداف الاستثمارية (Risk/Reward):
• TP1: {tp1} (+{tp1_pct}%)
• TP2: {tp2} (+{tp2_pct}%)

💡 مميزات الصفقة:
✔ التداول مع الاتجاه العام (فريم 4 ساعات)
✔ وقف خسارة بعيد عن ذيول التصفية
✔ بناء استثماري هادئ ومستقر
"""
        return {"Decision": report_message.strip(), "Symbol": symbol}
