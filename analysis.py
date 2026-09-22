import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class SmartMoneyTradingAnalyst:
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

    def calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(period).mean()

    def calculate_rsi(self, df, period=14):
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_market_trend(self):
        try:
            btc_df = self.fetch_ohlcv_data('BTC/USDT:USDT', limit=60)
            if btc_df is not None and len(btc_df) >= 50:
                btc_close = btc_df['close'].iloc[-1]
                btc_sma50 = btc_df['close'].rolling(window=50).mean().iloc[-1]
                return "BULLISH" if btc_close > btc_sma50 else "BEARISH"
        except Exception:
            pass
        return "NEUTRAL"

    def evaluate_strategy(self, symbol, account_balance=1000.0, risk_percentage=0.01):
        df = self.fetch_ohlcv_data(symbol, limit=100)
        
        if df is None or len(df) < 50:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "INSUFFICIENT DATA / ERROR",
                "Score": 50,
                "Quality": "WEAK",
                "Timeframe": self.timeframe,
                "Details": "Data Error (< 50 candles)"
            }

        close = df['close'].iloc[-1]
        open_price = df['open'].iloc[-1]
        volume_recent = df['volume'].iloc[-5:].mean()
        
        # فحص السيولة/الفوليوم الأساسي (تم رفع الحد الأدنى لزيادة الموثوقية)
        has_volume = (volume_recent * close >= 80000)
        
        # حساب المؤشرات وهيكل السوق بدقة أعلى
        sma_fast = df['close'].rolling(window=9).mean().iloc[-1]
        sma_slow = df['close'].rolling(window=21).mean().iloc[-1]
        sma_trend = df['close'].rolling(window=50).mean().iloc[-1]
        atr = self.calculate_atr(df).iloc[-1]
        rsi_series = self.calculate_rsi(df)
        current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

        if pd.isna(atr) or atr == 0:
            atr = close * 0.01

        recent_low = df['low'].iloc[-15:-1].min()
        recent_high = df['high'].iloc[-15:-1].max()
        
        bullish_ob_low = df[['open', 'close']].iloc[-4].min() 
        bearish_ob_high = df[['open', 'close']].iloc[-4].max() 

        # فحص سحب السيولة الحقيقي المطور
        liquidity_sweep_bull = (df['low'].iloc[-3:-1].min() < recent_low) and (close > recent_low)
        liquidity_sweep_bear = (df['high'].iloc[-3:-1].max() > recent_high) and (close < recent_high)
        has_liquidity = bool(liquidity_sweep_bull or liquidity_sweep_bear)

        bullish_mss = (df['close'].iloc[-1] > df['high'].iloc[-3]) and (sma_fast > sma_slow)
        bearish_mss = (df['close'].iloc[-1] < df['low'].iloc[-3]) and (sma_fast < sma_slow)
        has_mss = bool(bullish_mss or bearish_mss)

        # إضافة فلتر الزخم: التأكد أن الشمعة الحالية قوية وليست دوجي أو انعكاسية ضعيفة
        candle_body = abs(close - open_price)
        avg_body = abs(df['close'] - df['open']).rolling(window=10).mean().iloc[-1]
        has_strong_momentum = candle_body >= (avg_body * 0.8)

        has_structure = (close > sma_trend) if bullish_mss else (close < sma_trend if bearish_mss else False)
        has_ob = True 

        btc_trend = self.get_market_trend()
        has_btc_alignment = True
        if bullish_mss and btc_trend == "BEARISH":
            has_btc_alignment = False
        elif bearish_mss and btc_trend == "BULLISH":
            has_btc_alignment = False

        # حساب المؤكدات
        confluences_count = 0
        if has_structure: confluences_count += 1
        if has_btc_alignment: confluences_count += 1
        if has_strong_momentum: confluences_count += 1
        if has_liquidity: confluences_count += 1
        
        avg_volume_20 = df['volume'].rolling(window=20).mean().iloc[-1]
        if volume_recent > avg_volume_20: confluences_count += 1
        
        entry = round(close, 5 if close < 1 else 2)
        if bullish_mss:
            stop_loss = round(min(recent_low, bullish_ob_low) - (0.2 * atr), 5 if close < 1 else 2)
            risk = entry - stop_loss
            tp1 = round(entry + (2.0 * (risk if risk > 0 else atr)), 5 if close < 1 else 2)
        else:
            stop_loss = round(max(recent_high, bearish_ob_high) + (0.2 * atr), 5 if close < 1 else 2)
            risk = stop_loss - entry
            tp1 = round(entry - (2.0 * (risk if risk > 0 else atr)), 5 if close < 1 else 2)

        reward_tp1 = abs(tp1 - entry)
        rr_ratio = reward_tp1 / risk if risk > 0 else 0
        sl_pass = abs(entry - stop_loss) / entry <= 0.07

        details_report = f"""
⏱️ Timeframe: {self.timeframe}
Structure: {'YES' if has_structure else 'NO'}
OB: {'YES' if has_ob else 'NO'}
MSS: {'YES' if has_mss else 'NO'}
Liquidity: {'YES' if has_liquidity else 'NO'}
Volume: {'YES' if has_volume else 'NO'}
BTC: {'YES' if has_btc_alignment else 'NO'}
Momentum: {'YES' if has_strong_momentum else 'NO'}
Confluence: {confluences_count}/5
SL: {'PASS' if sl_pass else 'FAIL'}
"""

        is_bullish = bullish_mss and has_structure and has_btc_alignment and has_strong_momentum
        is_bearish = bearish_mss and has_structure and has_btc_alignment and has_strong_momentum

        if not has_volume or not has_strong_momentum:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "LOW VOLUME OR WEAK MOMENTUM",
                "Score": 42,
                "Quality": "WEAK",
                "Timeframe": self.timeframe,
                "Details": details_report
            }

        if not is_bullish and not is_bearish:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": "NO SMC STRUCTURE / CONSOLIDATION",
                "Score": 52,
                "Quality": "WEAK",
                "Timeframe": self.timeframe,
                "Details": details_report
            }

        if confluences_count < 4 or not sl_pass or rr_ratio < 1.5:
            return {
                "Decision": "NO TRADE ⏳",
                "Reason": f"INSUFFICIENT CONFLUENCES ({confluences_count}/5) OR R:R",
                "Score": 58,
                "Quality": "WEAK",
                "Timeframe": self.timeframe,
                "Details": details_report
            }

        decision = "MARKET LONG 🟢" if bullish_mss else "MARKET SHORT 🔴"
        tp2 = round(entry + (3.5 * risk) if bullish_mss else entry - (3.5 * risk), 5 if close < 1 else 2)
        score = min(98, 70 + (confluences_count * 6))
        quality = "🟢 STRONG"
        
        risk_amount = account_balance * risk_percentage
        position_size = round((risk_amount / risk) * entry / (1 if bullish_mss else 2), 2)
        position_size = max(10.0, min(position_size, account_balance * 4))

        return {
            "Decision": decision,
            "Entry": entry,
            "Stop Loss": stop_loss,
            "TP1": tp1,
            "TP2": tp2,
            "Score": score,
            "Quality": quality,
            "Position Size (USDT)": position_size,
            "Leverage": 1 if bullish_mss else 2,
            "Reason": "High-Probability SMC Setup",
            "Timeframe": self.timeframe,
            "Details": details_report
        }
