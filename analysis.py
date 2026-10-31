# ============================================================
# MY EXPERT CRYPTO BOT - Bullish Divergence Engine (v68.1_CLEAN)
# ============================================================
import numpy as np
import pandas as pd
import pandas_ta as ta
import logging

logger = logging.getLogger("StrategyEngine")

class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01):
        self.capital = capital
        self.risk_per_trade = risk_per_trade

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
        default_details = {
            "trade_valid": False,
            "trigger_price": 0.0,
            "stop_loss": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
            "entry_zone": {},
            "risk_management": {},
            "reason": "السوق حالياً مستقر ولا توجد إشارة دايفيرجنس حقيقية متحققة."
        }

        try:
            if not ohlcv_15m or len(ohlcv_15m) < 40:
                return "NEUTRAL", 0.0, default_details

            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df_15m['RSI'] = ta.rsi(df_15m['close'], length=14)
            df_15m['ATR'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14)

            if len(df_15m) < 20 or df_15m['RSI'].isna().iloc[-1] or df_15m['ATR'].isna().iloc[-1]:
                return "NEUTRAL", 0.0, default_details

            current_price = float(df_15m['close'].iloc[-1])
            current_atr = float(df_15m['ATR'].iloc[-1])
            decimals = 8 if current_price < 0.1 else (4 if current_price < 10 else 2)

            if current_atr <= 0 or np.isnan(current_atr):
                current_atr = current_price * 0.01

            c_low = float(df_15m['low'].iloc[-2])
            c_rsi = float(df_15m['RSI'].iloc[-2])

            is_bullish_divergence = False
            lookback = 15
            
            if c_rsi < 35:
                for i in range(3, lookback):
                    prev_low = float(df_15m['low'].iloc[-i])
                    prev_rsi = float(df_15m['RSI'].iloc[-i])

                    if c_low < prev_low and c_rsi > prev_rsi:
                        if prev_rsi < 40:
                            is_bullish_divergence = True
                            break

            if is_bullish_divergence and ohlcv_5m and len(ohlcv_5m) > 10:
                df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_5m['RSI'] = ta.rsi(df_5m['close'], length=14)
                
                if df_5m['RSI'].iloc[-1] > 70:
                    is_bullish_divergence = False

            if is_bullish_divergence:
                stop_loss = round(c_low - (current_atr * 1.2), decimals)
                
                target_1 = round(current_price + (current_atr * 1.5), decimals)
                target_2 = round(current_price + (current_atr * 3.0), decimals)
                target_3 = round(current_price + (current_atr * 5.0), decimals)

                if stop_loss >= current_price:
                    stop_loss = round(current_price - (current_atr * 1.5), decimals)

                details = {
                    "trade_valid": True,
                    "trigger_price": current_price,
                    "stop_loss": stop_loss,
                    "atr": round(current_atr, decimals),
                    "rsi": round(c_rsi, 2),
                    "entry_zone": {
                        "divergence_detected": True,
                        "validated_via_5m": True
                    },
                    "risk_management": {
                        "take_profit_1": target_1,
                        "take_profit_2": target_2,
                        "take_profit_3": target_3
                    },
                    "reason": f"🚨 تم رصد تأكيد دايفيرجنس إيجابي حقيقي (Bullish Divergence) بين القاع الحالي والقيعان السابقة على فريم 15 دقيقة."
                }
                return "LONG", current_price, details
            else:
                details = default_details.copy()
                details["rsi"] = round(df_15m['RSI'].iloc[-1], 2)
                details["atr"] = round(current_atr, decimals)
                return "NEUTRAL", current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
