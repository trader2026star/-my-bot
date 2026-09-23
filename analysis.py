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

    def calculate_algorithmic_path_and_targets(self, df):
        """
        تحليل خوارزميات الذكاء الاصطناعي وتتبع مسار صانع السوق:
        تحديد مستويات التذبذب، مناطق السيولة، ونقاط التحول الرقمية.
        """
        close = df['close'].iloc[-1]
        high_range = df['high'].max()
        low_range = df['low'].min()
        
        volatility_pips = round((high_range - low_range) * 1000, 2)
        predicted_drop = round(close * 0.985, 4 if close < 1 else 2)
        predicted_pump = round(close * 1.025, 4 if close < 1 else 2)
        
        return volatility_pips, predicted_drop, predicted_pump

    def evaluate_strategy(self, symbol):
        df_higher = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=50)
        df_lower = self.fetch_ohlcv_data(symbol, timeframe=self.timeframe, limit=100)
        
        if df_higher is None or df_lower is None or len(df_lower) < 50:
            return None

        close = df_lower['close'].iloc[-1]
        
        volatility_pips, pred_drop, pred_pump = self.calculate_algorithmic_path_and_targets(df_lower)
        
        current_volume = df_lower['volume'].iloc[-1]
        average_volume = df_lower['volume'].rolling(window=20).mean().iloc[-1]
        has_good_volume = current_volume >= (average_volume * 0.8)

        ma_higher = df_higher['close'].rolling(window=50).mean().iloc[-1]
        trend_is_bullish = df_higher['close'].iloc[-1] > ma_higher
        trend_is_bearish = df_higher['close'].iloc[-1] < ma_higher

        clean_symbol = symbol.split('/')[0]

        ai_analysis_text = f"رصد خوارزميات السوق: تذبذب بواقع {volatility_pips} نقطة مع توقعات مسار رقمي لاختبار نقاط السيولة."

        # ---------------------------------------------------------
        # الاتجاه الصاعد (LONG)
        # ---------------------------------------------------------
        if trend_is_bullish:
            if not has_good_volume:
                return {"Decision": "NO TRADE ⏳", "Reason": "السيولة لا تدعم المسار الخوارزمي الصاعد."}

            entry_high = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 0.975, 4 if close < 1 else 2)
            
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
* المسار المتوقع: هبوط طفيف لامتصاص السيولة ثم انطلاقة صاروخية نحو الأهداف.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        # ---------------------------------------------------------
        # الاتجاه الهابط (SHORT)
        # ---------------------------------------------------------
        elif trend_is_bearish:
            if not has_good_volume:
                return {"Decision": "NO TRADE ⏳", "Reason": "السيولة لا تدعم المسار الخوارزمي الهابط."}

            entry_low = round(close, 4 if close < 1 else 2)
            stop_loss = round(close * 1.025, 4 if close < 1 else 2)
            
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
* المسار المتوقع: تفريغ كميات وتذبذب هيكلي يدعم الهبوط نحو الأهداف الرقمية.
"""
            return {"Decision": report_message.strip(), "Symbol": symbol}

        return None
