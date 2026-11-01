# ============================================================
# MY EXPERT CRYPTO BOT - Bullish Divergence Engine (v70.0_FIXED)
# ============================================================
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger("StrategyEngine")

class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01):
        self.capital = capital
        self.risk_per_trade = risk_per_trade

    def calculate_rsi(self, series, period=14):
        try:
            delta = series.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            
            # استخدام Wilder's Smoothing الحقيقي المطابق لمنصات التداول
            avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50)
        except Exception:
            return pd.Series(50, index=series.index)

    def calculate_atr(self, df, period=14):
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            tr1 = high - low
            tr2 = np.abs(high - close.shift())
            tr3 = np.abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_series = tr.rolling(window=period).mean()
            
            atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
            current_close = float(close.iloc[-1]) if not close.empty else 1.0
            
            if pd.isna(atr_val) or atr_val <= 0:
                atr_val = current_close * 0.015
                
            return pd.Series(atr_val, index=df.index)
        except Exception:
            current_close = float(df['close'].iloc[-1]) if not df.empty and 'close' in df else 1.0
            return pd.Series(current_close * 0.015, index=df.index if not df.empty else [0])

    def find_swing_lows(self, low_series, order=2):
        """البحث عن القيعان الحقيقية (Swing Lows) بدقة عالية"""
        lows = low_series.values
        swing_indices = []
        for i in range(order, len(lows) - order):
            if lows[i] == min(lows[i - order:i + order + 1]):
                swing_indices.append(i)
        return swing_indices

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
        default_details = {
            "trade_valid": False,
            "trigger_price": 0.0,
            "stop_loss": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
            "entry_zone": {},
            "risk_management": {},
            "reason": "السوق حالياً مستقر ولا توجد إشارة دايفيرجنس إيجابي متحققة."
        }

        try:
            if not ohlcv_15m or len(ohlcv_15m) < 50:
                return "NEUTRAL", 0.0, default_details

            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df_15m['RSI'] = self.calculate_rsi(df_15m['close'], period=14)
            df_15m['ATR'] = self.calculate_atr(df_15m, period=14)

            if len(df_15m) < 30 or pd.isna(df_15m['RSI'].iloc[-1]):
                return "NEUTRAL", 0.0, default_details

            current_price = float(df_15m['close'].iloc[-1])
            current_atr = float(df_15m['ATR'].iloc[-1])
            if current_atr <= 0 or np.isnan(current_atr):
                current_atr = current_price * 0.015

            decimals = 8 if current_price < 0.1 else (4 if current_price < 10 else 2)

            # استخراج القيعان المحورية للفريم 15 دقيقة
            swing_lows = self.find_swing_lows(df_15m['low'], order=3)
            
            is_bullish_divergence = False
            c_rsi = float(df_15m['RSI'].iloc[-1])

            # فحص الدايفيرجنس بين آخر قاعين محوريين تم رصدهما
            if len(swing_lows) >= 2:
                idx_recent = swing_lows[-1]
                idx_prev = swing_lows[-2]

                price_recent = float(df_15m['low'].iloc[idx_recent])
                price_prev = float(df_15m['low'].iloc[idx_prev])

                rsi_recent = float(df_15m['RSI'].iloc[idx_recent])
                rsi_prev = float(df_15m['RSI'].iloc[idx_prev])

                # شرط الدايفيرجنس الإيجابي: السعر صنع قاع أقل، والـ RSI صنع قاع أعلى، بشرط أن نكون في مناطق قريبة من التشبع البيعي
                if price_recent < price_prev and rsi_recent > rsi_prev:
                    if rsi_recent < 50 and (idx_recent >= len(df_15m) - 5): # التأكد أن القاع حدث مؤخراً
                        is_bullish_divergence = True

            # فلترة إضافية خفيفة على فريم 5 دقائق لضمان عدم وجود تشبع شرائي مفرط
            if is_bullish_divergence and ohlcv_5m and len(ohlcv_5m) > 10:
                df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                rsi_5m = self.calculate_rsi(df_5m['close'], period=14)
                if rsi_5m.iloc[-1] > 80:
                    is_bullish_divergence = False

            stop_loss = round(current_price - (current_atr * 1.5), decimals)
            target_1 = round(current_price + (current_atr * 1.5), decimals)
            target_2 = round(current_price + (current_atr * 3.0), decimals)
            target_3 = round(current_price + (current_atr * 5.0), decimals)

            if stop_loss >= current_price:
                stop_loss = round(current_price - (current_atr * 2.0), decimals)

            details = {
                "trade_valid": is_bullish_divergence,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(current_atr, decimals),
                "rsi": round(c_rsi, 2),
                "entry_zone": {
                    "divergence_detected": is_bullish_divergence,
                    "validated_via_5m": True
                },
                "risk_management": {
                    "take_profit_1": target_1,
                    "take_profit_2": target_2,
                    "take_profit_3": target_3
                },
                "reason": f"🚨 تم رصد دايفيرجنس إيجابي (Bullish Divergence) مؤكد عبر قيعان محورية على فريم 15 دقيقة." if is_bullish_divergence else "السوق حالياً مستقر ولا توجد إشارة دايفيرجنس إيجابي متحققة."
            }
            
            direction = "LONG" if is_bullish_divergence else "NEUTRAL"
            return direction, current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
