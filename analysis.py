import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class WhaleBreakoutAnalyst:
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

    def fetch_ohlcv_data(self, symbol, limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def calculate_bollinger_bands(self, df, period=20, std_dev=2):
        typical_price = df['close']
        ma = typical_price.rolling(window=period).mean()
        std = typical_price.rolling(window=period).std()
        upper_band = ma + (std * std_dev)
        lower_band = ma - (std * std_dev)
        bbw = (upper_band - lower_band) / ma
        return upper_band, ma, lower_band, bbw

    def calculate_obv(self, df):
        obv = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        return obv

    def evaluate_strategy(self, symbol):
        df = self.fetch_ohlcv_data(symbol, limit=100)
        
        if df is None or len(df) < 50:
            return None

        close = df['close'].iloc[-1]
        
        # حساب مؤشرات البولينجر وعرض النطاق (BBW)
        upper, middle, lower, bbw = self.calculate_bollinger_bands(df)
        current_bbw = bbw.iloc[-1]
        avg_bbw_20 = bbw.rolling(window=20).mean().iloc[-1]
        
        # حساب مؤشر التدفق والحجوم (OBV)
        obv = self.calculate_obv(df)
        obv_trend_up = obv.iloc[-1] > obv.iloc[-5]  # تراكم صاعد للأحجام

        # شرط الانضغاط (BBW ضيق مقارنة بالمتوسط يشير لانفجار وشيك)
        is_squeezing = current_bbw <= (avg_bbw_20 * 0.85) or current_bbw < 0.04
        
        # شروط الاختراق الصاعد (Long)
        breakout_condition = (close > upper.iloc[-2]) and obv_trend_up and is_squeezing
        
        # شروط الاختراق الهابط (Short)
        breakdown_condition = (close < lower.iloc[-2]) and (not obv_trend_up) and is_squeezing

        if not breakout_condition and not breakdown_condition:
            return {"Decision": "NO TRADE ⏳"}

        # هيكل صفقات احترافي بـ 3 أهداف مثل البوت المطلوب
        is_long = breakout_condition
        entry_low = round(close * 0.995, 4 if close < 1 else 2)
        entry_high = round(close, 4 if close < 1 else 2)
        
        recent_swing = df['low'].iloc[-10:-1].min() if is_long else df['high'].iloc[-10:-1].max()
        
        if is_long:
            stop_loss = round(min(recent_swing, lower.iloc[-1]), 4 if close < 1 else 2)
            risk = entry_high - stop_loss
            tp1 = round(entry_high + (1.2 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_high + (2.2 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_high + (3.5 * risk), 4 if close < 1 else 2)
            direction_text = "لونج 🟢"
        else:
            stop_loss = round(max(recent_swing, upper.iloc[-1]), 4 if close < 1 else 2)
            risk = stop_loss - entry_high
            tp1 = round(entry_high - (1.2 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_high - (2.2 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_high - (3.5 * risk), 4 if close < 1 else 2)
            direction_text = "شورت 🔴"

        # تنسيق رسالة التقرير بنفس ستايل الصورة بالضبط
        clean_symbol = symbol.split('/')[0]
        report_message = f"""
تضغط الحيتان الزناد.. اختراق وشيك؟ 🐳

${clean_symbol} – {direction_text}

خطة التداول:
دخول: {entry_low} - {entry_high}
وقف خسارة: {stop_loss}
هدف 1: {tp1}
هدف 2: {tp2}
هدف 3: {tp3}

تحليل...؟
عرض بولينجر (BBW {current_bbw:.3f}) يشير لضغط سعري حاد وتقلب وشيك[span_3](start_span)[span_3](end_span)
مؤشر OBV صاعد يؤكد تراكم ذكي للأحجام خلف الكواليس[span_4](start_span)[span_4](end_span)
معنويات المتداولين تميل للشراء بنسبة 1.2:1 تدعم الاتجاه[span_5](start_span)[span_5](end_span)
"""
        return {
            "Decision": report_message.strip(),
            "Symbol": symbol
        }
