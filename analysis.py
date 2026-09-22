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
        
        # مقاومة مفتاحية (مستوى القمة أو بالقرب منها)
        key_resistance = fib_levels['1.0'] * 0.98  
        
        # فلتر الاتجاه العام من الفريم الكبير
        ma_higher = df_higher['close'].rolling(window=50).mean().iloc[-1]
        trend_is_bullish = df_higher['close'].iloc[-1] > ma_higher

        # تطبيق سيناريوهات الخبير المشروطة:
        breakout_scenario = (close >= key_resistance) and trend_is_bullish
        correction_scenario = (support_zone_low <= close <= support_zone_high) and trend_is_bullish

        if not breakout_scenario and not correction_scenario:
            return {
                "Decision": "NO TRADE ⏳", 
                "Reason": "السعر في منطقة حيادية، بانتظار اختبار دعم فيبو أو اختراق المقاومة."
            }

        # حماية إضافية: منع مطاردة السعر إذا كان مغلقاً قرب القمة تماماً
        recent_high = df_lower['high'].rolling(window=10).max().iloc[-1]
        if close >= recent_high * 0.995 and breakout_scenario:
            return None

        # بناء خطة التداول الاحترافية مع مسافة أمان لوقف الخسارة لتفادي التذبذب
        entry_low = round(support_zone_low if correction_scenario else close * 0.995, 4 if close < 1 else 2)
        entry_high = round(support_zone_high if correction_scenario else close, 4 if close < 1 else 2)
        
        # تعديل وقف الخسارة ليبعد مسافة آمنة ومدروسة تحت القاع أو الدعم الأقوى بمسافة إضافية
        recent_low = df_lower['low'].rolling(window=10).min().iloc[-1]
        stop_loss = round(min(fib_levels['0.382'] * 0.97, recent_low * 0.985), 4 if close < 1 else 2)
        
        risk = entry_high - stop_loss
        
        # حساب الأهداف بناءً على نسب العائد للمخاطرة الآمنة
        tp1 = round(entry_high + (1.5 * risk), 4 if close < 1 else 2)
        tp2 = round(entry_high + (2.5 * risk), 4 if close < 1 else 2)
        tp3 = round(entry_high + (3.5 * risk), 4 if close < 1 else 2)

        clean_symbol = symbol.split('/')[0]
        scenario_name = "سيناريو 1: اختراق المقاومة واستمرار الصعود 🚀" if breakout_scenario else "سيناريو 2: ارتداد تصحيحي من مناطق دعم فيبوناتشي الذهبية 📊"

        report_message = f"""
تحليل فني احترافي (محدث وآمن) - دمج الفريمات وفيبوناتشي 📊

${clean_symbol} – صفقات شراء (LONG)
{scenario_name}

خطة التداول:
منطقة الدخول: {entry_low} - {entry_high}
وقف خسارة: {stop_loss} (محمي ضد التذبذب اللحظي)
الهدف الأول (TP1): {tp1}
الهدف الثاني (TP2): {tp2}
الهدف الثالث (TP3): {tp3}

ملاحظات التحليل:
- دمج الفريم اليومي مع فريم 15 دقيقة للتأكد من إيجابية الاتجاه العام.
- الارتكاز على مناطق الطلب الذهبية لفيبوناتشي (0.5 و 0.618).
- ضبط وقف الخسارة بمسافة أمان كافية لتفادي الفتل الوهمي والتذبذب.
"""
        return {
            "Decision": report_message.strip(),
            "Symbol": symbol
        }
