import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class SmartMoneyTradingAnalyst:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def fetch_ohlcv_data(self, symbol, timeframe='4h', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ في جلب بيانات {symbol}: {e}")
            return None

    def calculate_indicators(self, df):
        # حساب المتوسطات المتحركة والتقلب (ATR)
        df['sma_fast'] = df['close'].rolling(window=9).mean()
        df['sma_slow'] = df['close'].rolling(window=21).mean()
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        # حساب متوسط الحجم للتأكد من السيولة
        df['volume_mean'] = df['volume'].rolling(20).mean()
        return df

    def evaluate_strategy(self, symbol, account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        
        if df is None or len(df) < 30:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "INSUFFICIENT DATA / ERROR",
                "Score": 50,
                "Quality": "WEAK"
            }

        df = self.calculate_indicators(df)
        last_row = df.iloc[-1]
        close = last_row['close']
        atr = last_row['atr']
        
        if pd.isna(atr) or atr == 0:
            atr = close * 0.01

        sma_fast = last_row['sma_fast']
        sma_slow = last_row['sma_slow']
        volume = last_row['volume']
        volume_mean = last_row['volume_mean']

        # منطق فحص السوق الحقيقي (بدون عشوائية)
        # شرط وجود سيولة وفوليوم جيد + تقاطع اتجاهي واضح
        has_volume_support = volume > (volume_mean * 0.75)
        is_bullish = sma_fast > sma_slow

        # إذا الشروط غير متوفرة، يتم استبعاد الصفقة بـ NO TRADE بدقة
        if not has_volume_support or pd.isna(sma_fast) or pd.isna(sma_slow):
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "SCORE BELOW THRESHOLD / NO SETUP",
                "Score": 50,
                "Quality": "WEAK"
            }

        score = 75
        quality = "🟢 STRONG"
        
        if is_bullish:
            decision = "MARKET LONG 🟢"
            reason = "Balanced Bullish Setup"
            entry = round(close, 5 if close < 1 else 2)
            stop_loss = round(entry - (1.5 * atr), 5 if close < 1 else 2)
            tp1 = round(entry + (2.0 * atr), 5 if close < 1 else 2)
            tp2 = round(entry + (3.5 * atr), 5 if close < 1 else 2)
            leverage = 1
        else:
            decision = "MARKET SHORT 🔴"
            reason = "Balanced Bearish Setup"
            entry = round(close, 5 if close < 1 else 2)
            stop_loss = round(entry + (1.5 * atr), 5 if close < 1 else 2)
            tp1 = round(entry - (2.0 * atr), 5 if close < 1 else 2)
            tp2 = round(entry - (3.5 * atr), 5 if close < 1 else 2)
            leverage = 2

        # حساب حجم العقد (Position Size) بناءً على إدارة المخاطر بدقة
        risk_amount = account_balance * risk_percentage
        risk_per_unit = abs(entry - stop_loss)
        
        if risk_per_unit > 0:
            position_size = round((risk_amount / risk_per_unit) * entry / leverage, 2)
        else:
            position_size = round(account_balance * 0.2, 2)

        position_size = max(10.0, min(position_size, account_balance * leverage * 2))

        return {
            "Decision": decision,
            "Entry": entry,
            "Stop Loss": stop_loss,
            "TP1": tp1,
            "TP2": tp2,
            "Score": score,
            "Quality": quality,
            "Position Size (USDT)": position_size,
            "Leverage": leverage,
            "Reason": reason
        }
