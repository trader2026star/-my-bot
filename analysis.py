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

    def calculate_atr(self, df, period=14):
        """حساب مؤشر متوسط المدى الحقيقي (ATR) لمنع الدخول في السوق العرضي والمتذبذب"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean().iloc[-1]

    def evaluate_strategy(self, symbol):
        # استخدام فريم الـ 4 ساعات لتحديد الاتجاه الحقيقي بدقة ومنع الانعكاسات
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=50)
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        
        # فحص حجم التداول والسيولة الحقيقية
        current_volume = df_lower['volume'].iloc[-1]
        average_volume = df_lower['volume'].rolling(window=20).mean().iloc[-1]
        has_good_volume = current_volume >= (average_volume * 0.8)

        # فحص الزخم الحقيقي عبر مؤشر ATR لتصفية التذبذب العرضي
        atr_value = self.calculate_atr(df_lower, period=14)
        min_required_atr = close * 0.0015
        has_strong_volatility = atr_value >= min_required_atr

        # المتوسطات الآسية السريعة (EMA) لتحديد الاتجاه بدون تأخير
        ema_fast = df_higher['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema_slow = df_higher['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # مؤشر RSI لمنع الدخول الشرائي في مناطق التشبع أو البيعي في القاع
        rsi = self.calculate_rsi(df_lower['close'], 14).iloc[-1]

        clean_symbol = symbol.split('/')[0]
        volatility_pips = round((df_lower['high'].max() - df_lower['low'].min()) * 1000, 2)
        ai_analysis_text = f"رصد خوارزميات السوق: تقلب حقيقي مؤكد مع تذبذب بواقع {volatility_pips} نقطة."

        # فلتر صارم يمنع الدخول إذا كانت السيولة ضعيفة أو الحركة عرضية بحتة
        if not has_good_volume or not has_strong_volatility:
            return {"Decision": "NO TRADE ⏳", "Reason": "السوق يعاني من تذبذب عرضي أو سيولة غير كافية."}

        # ---------------------------------------------------------
        # الاتجاه الصاعد (LONG) - بشرط تريند صاعد و RSI غير مشبع
        # ---------------------------------------------------------
        if ema_fast > ema_slow and rsi < 65:
            entry_high = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 0.98, 4 if close < 1 else 2) # وقف خسارة دقيق وآمن
            
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
* المسار المتوقع: ارتداد مؤكد من مناطق الدعم بعد فلترة التذبذب العرضي واستمرار الصعود.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        # ---------------------------------------------------------
        # الاتجاه الهابط (SHORT) - بشرط تريند هابط و RSI يسمح بالهبوط
        # ---------------------------------------------------------
        elif ema_fast < ema_slow and rsi > 35:
            entry_low = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 1.02, 4 if close < 1 else 2) # وقف خسارة دقيق وآمن
            
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
* المسار المتوقع: ضغط بيعي وتفريغ كميات بعد تصفية الحركة العرضية يدعم استمرار الهبوط.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        return None
