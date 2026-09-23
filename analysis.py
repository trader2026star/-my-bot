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

    def calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_algorithmic_path_and_targets(self, df):
        close = df['close'].iloc[-1]
        high_range = df['high'].max()
        low_range = df['low'].min()
        volatility_pips = round((high_range - low_range) * 1000, 2)
        return volatility_pips

    def evaluate_strategy(self, symbol):
        # فريمات زمنية أدق لتأكيد الاتجاه (الفريم الأكبر 4 ساعات وفريم التنفيذ 15 دقيقة)
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=50)
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        volatility_pips = self.calculate_algorithmic_path_and_targets(df_lower)
        
        current_volume = df_lower['volume'].iloc[-1]
        average_volume = df_lower['volume'].rolling(window=20).mean().iloc[-1]
        has_good_volume = current_volume >= (average_volume * 0.75)

        # فلتر الاتجاه الأقوى باستخدام تقاطع المتوسطات الآسية (EMA 20 & EMA 50) على فريم الـ 4 ساعات
        ema_fast = df_higher['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema_slow = df_higher['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # مؤشر RSI على الفريم اللحظي لتجنب الدخول في مناطق التشبع
        rsi = self.calculate_rsi(df_lower['close'], 14).iloc[-1]

        clean_symbol = symbol.split('/')[0]
        ai_analysis_text = f"رصد خوارزميات السوق: تذبذب بواقع {volatility_pips} نقطة مع تأكيد الزخم الرقمي."

        # ---------------------------------------------------------
        # الاتجاه الصاعد (LONG) بشرط عدم وجود تشبع شرائي وعدم كسر الاتجاه
        # ---------------------------------------------------------
        if ema_fast > ema_slow and rsi < 65:
            if not has_good_volume:
                return {"Decision": "NO TRADE ⏳", "Reason": "السيولة لا تدعم الانطلاقة الصاعدة."}

            entry_high = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 0.982, 4 if close < 1 else 2) # وقف خسارة آمن ومحسوب
            
            risk = entry_high - stop_loss
            tp1 = round(entry_high + (1.5 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_high + (2.5 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_high + (3.5 * risk), 4 if close < 1 else 2)

            report_message = f"""
تحليل بادوات الذكاء الاصطناعي 🤖

${clean_symbol} صفقة شراء 📈
الدخول 🟢 {entry_high}
وقف الخساره 🚫 {stop_loss}
الهدف 🎯 {tp1}

خطة التداول:
هدف 2: {tp2}
هدف 3: {tp3}

تحليل الكوارزميات:
* {ai_analysis_text}
* المسار المتوقع: ارتداد من مناطق السيولة الصاعدة واستمرار الزخم الإيجابي.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        # ---------------------------------------------------------
        # الاتجاه الهابط (SHORT) بشرط عدم وجود تشبع بيعي
        # ---------------------------------------------------------
        elif ema_fast < ema_slow and rsi > 35:
            if not has_good_volume:
                return {"Decision": "NO TRADE ⏳", "Reason": "السيولة لا تدعم الهبوط الخوارزمي."}

            entry_low = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 1.018, 4 if close < 1 else 2) # وقف خسارة آمن ومحسوب
            
            risk = stop_loss - entry_low
            tp1 = round(entry_low - (1.5 * risk), 4 if close < 1 else 2)
            tp2 = round(entry_low - (2.5 * risk), 4 if close < 1 else 2)
            tp3 = round(entry_low - (3.5 * risk), 4 if close < 1 else 2)

            report_message = f"""
تحليل بادوات الذكاء الاصطناعي 🤖

${clean_symbol} صفقة بيع (Short) 📉
الدخول 🔴 {entry_low}
وقف الخساره 🚫 {stop_loss}
الهدف 🎯 {tp1}

خطة التداول:
هدف 2: {tp2}
هدف 3: {tp3}

تحليل الكوارزميات:
* {ai_analysis_text}
* المسار المتوقع: ضغط بيعي واستمرار الهبوط نحو الأهداف الرقمية السفلى.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        return None
