import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='15m'):
        self.exchange_id = exchange_id
        self.timeframe = timeframe # الفريم اللحظي للدخول (مثل 15 دقيقة)
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

    def calculate_fibonacci_levels(self, df):
        """حساب مستويات فيبوناتشي بناءً على أحدث قمة وقاع للفترة المحددة"""
        high_price = df['high'].max()
        low_price = df['low'].min()
        diff = high_price - low_price
        
        # المستويات الكلاسيكية لفيبوناتشي
        levels = {
            '0.0': low_price,
            '0.236': low_price + (diff * 0.236),
            '0.382': low_price + (diff * 0.382),
            '0.5': low_price + (diff * 0.5),
            '0.618': low_price + (diff * 0.618),
            '0.786': low_price + (diff * 0.786),
            '1.0': high_price
        }
        return levels, high_price, low_price

    def evaluate_strategy(self, symbol):
        # 1. دمج الفريمات: جلب بيانات الفريم الكبير (اليومي/الأسبوعي) لتحديد الاتجاه العام ودعم السعر
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=50)
        # 2. جلب بيانات الفريم الصغير (15 دقيقة) للدخول اللحظي
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        
        # حساب مستويات فيبوناتشي على الفريم الصغير/المتوسط
        fib_levels, high_p, low_p = self.calculate_fibonacci_levels(df_lower)
        
        # تحديد منطقة الشراء المثالية (بين مستويات 0.5 و 0.618 كمناطق تصحيح قوية)
        support_zone_low = fib_levels['0.5']
        support_zone_high = fib_levels['0.618']
        
        # مقاومة مفتاحية (مثلاً مستوى القمة أو 1.0 أو قمة سابقة)
        key_resistance = fib_levels['1.0'] * 0.98  # بالقرب من القمة
        
        # فلتر الاتجاه العام من الفريم الكبير (مثلاً إغلاق أحدث شمعة يومية أعلى المتوسط المتحرك 50)
        ma_higher = df_higher['close'].rolling(window=50).mean().iloc[-1]
        trend_is_bullish = df_higher['close'].iloc[-1] > ma_higher

        # تطبيق سيناريوهات الخبير المشروطة:
        # السيناريو الأول: اختراق المقاومة واستمرار الصعود
        breakout_scenario = (close >= key_resistance) and trend_is_bullish
        
        # السيناريو الثاني: تصحيح إلى منطقة الدعم الفيبوناتشي (0.5 - 0.618) والارتداد منها
        correction_scenario = (support_zone_low <= close <= support_zone_high) and trend_is_bullish

        if not breakout_scenario and not correction_scenario:
            return {
                "Decision": "NO TRADE ⏳", 
                "Reason": "السعر في منطقة حيادية، بانتظار اختبار دعم فيبو أو اختراق المقاومة."
            }

        # بناء خطة التداول الاحترافية بـ 3 أهداف مثل التحليل المدروس
        entry_low = round(support_zone_low if correction_scenario else close * 0.995, 4 if close < 1 else 2)
        entry_high = round(support_zone_high if correction_scenario else close, 4 if close < 1 else 2)
        
        stop_loss = round(fib_levels['0.382'] * 0.98, 4 if close < 1 else 2)  # وقف الخسارة تحت دعم فيبو أقوى
        risk = entry_high - stop_loss
        
        # حساب الأهداف بناءً على نسب العائد للمخاطرة
        tp1 = round(entry_high + (1.2 * risk), 4 if close < 1 else 2)
        tp2 = round(entry_high + (2.2 * risk), 4 if close < 1 else 2)
        tp3 = round(entry_high + (3.5 * risk), 4 if close < 1 else 2)

        clean_symbol = symbol.split('/')[0]
        scenario_name = "سيناريو 1: اختراق المقاومة واستمرار الصعود 🚀" if breakout_scenario else "سيناريو 2: ارتداد تصحيحي من مناطق دعم فيبوناتشي الذهبية 📊"

        report_message = f"""
تحليل فني احترافي - دمج الفريمات وفيبوناتشي 📊

${clean_symbol} – صفقات شراء (LONG)
{scenario_name}

خطة التداول:
منطقة الدخول: {entry_low} - {entry_high}
وقف خسارة: {stop_loss}
الهدف الأول (TP1): {tp1}
الهدف الثاني (TP2): {tp2}
الهدف الثالث (TP3): {tp3}

ملاحظات التحليل:
- تم دمج الفريم اليومي مع فريم 15 دقيقة للتأكد من إيجابية الاتجاه العام[span_3](start_span)[span_3](end_span)[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span).
- الاعتماد على مستويات تصحيح فيبوناتشي (المنطقة الذهبية بين 0.5 و 0.618) لاختيار مناطق الطلب[span_6](start_span)[span_6](end_span)[span_7](start_span)[span_7](end_span)[span_8](start_span)[span_8](end_span).
- القرار مبني على سيناريوهات مشروطة بدقة لتفادي التذبذب العشوائي[span_9](start_span)[span_9](end_span)[span_10](start_span)[span_10](end_span)[span_11](start_span)[span_11](end_span).
"""
        return {
            "Decision": report_message.strip(),
            "Symbol": symbol
        }
