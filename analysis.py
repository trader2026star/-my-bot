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

    def calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(period).mean()

    def evaluate_strategy(self, symbol, account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
        
        if df is None or len(df) < 30:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "INSUFFICIENT DATA / ERROR",
                "Score": 50,
                "Quality": "WEAK"
            }

        close = df['close'].iloc[-1]
        volume_recent = df['volume'].iloc[-5:].mean()
        
        # فلتر السيولة: استبعاد العملات ذات التداول الضعيف جداً لتجنب التلاعب
        if volume_recent * close < 50000:  # الحد الأدنى لحجم التداول (50 ألف دولار مثلاً)
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "LOW LIQUIDITY / VOLUME",
                "Score": 40,
                "Quality": "WEAK"
            }

        sma_fast = df['close'].rolling(window=9).mean().iloc[-1]
        sma_slow = df['close'].rolling(window=21).mean().iloc[-1]
        sma_trend = df['close'].rolling(window=50).mean().iloc[-1] # فلتر اتجاه إضافي
        atr = self.calculate_atr(df).iloc[-1]

        if pd.isna(atr) or atr == 0:
            atr = close * 0.01

        # شروط فنية حقيقية بدلاً من الاعتماد العشوائي
        is_bullish = (sma_fast > sma_slow) and (close > sma_trend)
        is_bearish = (sma_fast < sma_slow) and (close < sma_trend)

        if not is_bullish and not is_bearish:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "NO CLEAR TREND / CONSOLIDATION",
                "Score": 55,
                "Quality": "WEAK"
            }

        # تحديد نقاط الدخول والأهداف بناءً على الـ ATR
        if is_bullish:
            decision = "MARKET LONG 🟢"
            reason = "Confirmed Bullish Trend (SMA & Price Action)"
            entry = round(close, 5 if close < 1 else 2)
            stop_loss = round(entry - (1.5 * atr), 5 if close < 1 else 2)
            tp1 = round(entry + (2.0 * atr), 5 if close < 1 else 2)
            tp2 = round(entry + (3.5 * atr), 5 if close < 1 else 2)
            leverage = 1
        else:
            decision = "MARKET SHORT 🔴"
            reason = "Confirmed Bearish Trend (SMA & Price Action)"
            entry = round(close, 5 if close < 1 else 2)
            stop_loss = round(entry + (1.5 * atr), 5 if close < 1 else 2)
            tp1 = round(entry - (2.0 * atr), 5 if close < 1 else 2)
            tp2 = round(entry - (3.5 * atr), 5 if close < 1 else 2)
            leverage = 2

        # حساب نسبة العائد للمخاطرة (Risk-to-Reward Ratio)
        risk = abs(entry - stop_loss)
        reward = abs(tp1 - entry)
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < 1.2:  # لو العائد أقل من المخاطرة بنسبة مقبولة، نرفض الصفقة
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "LOW RISK-TO-REWARD RATIO",
                "Score": 60,
                "Quality": "WEAK"
            }

        # تقييم السكور بناءً على قوة الـ R:R وقوة الاتجاه
        score = 80 if rr_ratio >= 1.5 else 75
        quality = "🟢 STRONG"

        # حساب حجم العقد المالي لإدارة المخاطر
        risk_amount = account_balance * risk_percentage
        risk_per_unit = risk
        
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
