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
        # 1. دمج الفريمات: جلب بيانات الفريم الكبير (اليومي) لتحديد الاتجاه العام
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=50)
        # 2. جلب بيانات الفريم الصغير (15 دقيقة) للدخول اللحظي
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        
        # حساب مستويات فيبوناتشي
        fib_levels, high_p, low_p = self.calculate_fibonacci_levels(df_lower)
        
        # فلتر الاتجاه العام من الفريم الكبير (متوسط 50 يوم)
        ma_higher = df_higher['close'].rolling(window=50).mean().iloc[-1]
        trend_is_bullish = df_higher['close'].iloc[-1] > ma_higher
        trend_is_bearish = df_higher['close'].iloc[-1] < ma_higher

        clean_symbol = symbol.split('/')[0]

        # ---------------------------------------------------------
        # اتجاه صاعد -> صفقات شراء (LONG)
        # ---------------------------------------------------------
        if trend_is_bullish:
            support_zone_low = fib_levels['0.5']
            support_zone_high = fib_levels['0.618']
            key_resistance = fib_levels['1.0'] * 0.98  

            breakout_scenario = (close >= key_resistance)
            correction_scenario = (support_zone_low <= close <= support_zone_high)

            if not breakout_scenario and not correction_scenario:
                return {
                    "Decision": "NO TRADE ⏳", 
                    "Reason": "السعر في منطقة حيادية صاعدة، بانتظار اختبار الدعم أو الاختراق."
                }

            recent_high = df_lower['high'].rolling(window=10).max().iloc[-1]
            if close >= recent_high * 0.995 and breakout_scenario:
                return None

            entry_low = round(support_zone_low if correction_scenario else close * 0.995, 4 if close < 1 else 2)
            entry_high = round(support_zone_high if correction_scenario else close, 4 if close < 1 else 2)
            
            recent_low = df_lower['low'].rolling(window=10).min().iloc[-1]
            stop_loss = round(min(fib_levels['0.382'] * 0.97, recent_low * 0.985), 4 if close < 1 else 2)
            
            risk = entry_high - stop_loss
            tp1 = round(entry_high + (1.5 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_high + (2.5 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_high + (3.5 * risk), 4 if close < 1 else 2)

            scenario_name = "سيناريو صاعد 1: اختراق المقاومة واستمرار الصعود 🚀" if breakout_scenario else "سيناريو صاعد 2: ارتداد تصحيحي من دعم فيبوناتشي الذهبي 📊"

            report_message = f"""
تحليل فني احترافي - دمج الفريمات وفيبوناتشي 📊

${clean_symbol} – صفقات شراء (LONG) 🟢
{scenario_name}

خطة التداول:
منطقة الدخول: {entry_low} - {entry_high}
وقف خسارة: {stop_loss} (محمي ضد التذبذب)
الهدف الأول (TP1): {tp1}
الهدف الثاني (TP2): {tp2}
الهدف الثالث (TP3): {tp3}

ملاحظات التحليل:
- الاتجاه العام يومي صاعد مع دعم فريم 15 دقيقة.
- الارتكاز على مستويات فيبو الذهبية ودعم الفريمات المتعددة.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        # ---------------------------------------------------------
        # اتجاه هابط -> صفقات بيع (SHORT)
        # ---------------------------------------------------------
        elif trend_is_bearish:
            resistance_zone_low = fib_levels['0.382']
            resistance_zone_high = fib_levels['0.5']
            key_support = fib_levels['0.0'] * 1.02  

            breakdown_scenario = (close <= key_support)
            rejection_scenario = (resistance_zone_low <= close <= resistance_zone_high)

            if not breakdown_scenario and not rejection_scenario:
                return {
                    "Decision": "NO TRADE ⏳", 
                    "Reason": "السعر في منطقة حيادية هابطة، بانتظار اختبار المقاومة أو كسر الدعم."
                }

            recent_low_val = df_lower['low'].rolling(window=10).min().iloc[-1]
            if close <= recent_low_val * 1.005 and breakdown_scenario:
                return None

            entry_low = round(close if rejection_scenario else close * 1.005, 4 if close < 1 else 2)
            entry_high = round(resistance_zone_high if rejection_scenario else close, 4 if close < 1 else 2)
            
            recent_high_val = df_lower['high'].rolling(window=10).max().iloc[-1]
            stop_loss = round(max(fib_levels['0.618'] * 1.03, recent_high_val * 1.015), 4 if close < 1 else 2)
            
            risk = stop_loss - entry_low
            tp1 = round(entry_low - (1.5 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_low - (2.5 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_low - (3.5 * risk), 4 if close < 1 else 2)

            scenario_name = "سيناريو هابط 1: كسر الدعم واستمرار الهبوط 📉" if breakdown_scenario else "سيناريو هابط 2: ارتداد بيعي من مناطق المقاومة الفيبوناتشية 📊"

            report_message = f"""
تحليل فني احترافي - دمج الفريمات وفيبوناتشي 📊

${clean_symbol} – صفقات بيع (SHORT) 🔴
{scenario_name}

خطة التداول:
منطقة الدخول: {entry_low} - {entry_high}
وقف خسارة: {stop_loss} (محمي ضد التذبذب)
الهدف الأول (TP1): {tp1}
الهدف الثاني (TP2): {tp2}
الهدف الثالث (TP3): {tp3}

ملاحظات التحليل:
- الاتجاه العام يومي هابط مع استغلال ارتدادات فريم 15 دقيقة للبيع.
- الارتكاز على مناطق المقاومة الفيبوناتشية بحماية وقف خسارة آمن.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        return None
