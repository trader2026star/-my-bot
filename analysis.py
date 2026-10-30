# ============================================================
# MY EXPERT CRYPTO & TradFi CFD BOT - Analysis Engine (v63.4_FIXED_PRECISION)
# ============================================================
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger("StrategyEngine")

class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01):
        self.capital = capital
        self.risk_per_trade = risk_per_trade

    def calculate_atr(self, df, period=14):
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            tr1 = high - low
            tr2 = np.abs(high - close.shift())
            tr3 = np.abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            val = float(atr.iloc[-1])
            return val if not np.isnan(val) and val > 0 else 0.0
        except Exception:
            return 0.0

    def calculate_cmf(self, df, period=20):
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            volume = df['volume']
            
            mf_multiplier = ((close - low) - (high - close)) / (high - low + 1e-9)
            mf_volume = mf_multiplier * volume
            cmf = mf_volume.rolling(window=period).sum() / (volume.rolling(window=period).sum() + 1e-9)
            val = float(cmf.iloc[-1])
            return val if not np.isnan(val) else 0.0
        except Exception:
            return 0.0

    def detect_smart_money_elements(self, df):
        try:
            if len(df) < 10:
                return {"bullish_fvg": False, "bearish_fvg": False, "sweep_long": False, "sweep_short": False, "bias": "NEUTRAL"}

            high_1 = df['high'].iloc[-3]
            low_3 = df['low'].iloc[-1]
            bullish_fvg = low_3 > high_1

            low_1 = df['low'].iloc[-3]
            high_3 = df['high'].iloc[-1]
            bearish_fvg = high_3 < low_1

            recent_low = df['low'].iloc[-10:-2].min()
            current_low = df['low'].iloc[-1]
            current_close = df['close'].iloc[-1]
            
            recent_high = df['high'].iloc[-10:-2].max()
            current_high = df['high'].iloc[-1]

            sweep_long = current_low < recent_low and current_close > recent_low
            sweep_short = current_high > recent_high and current_close < recent_high

            bias = "NEUTRAL"
            if bullish_fvg or sweep_long:
                bias = "BULLISH"
            elif bearish_fvg or sweep_short:
                bias = "BEARISH"

            return {
                "bullish_fvg": bool(bullish_fvg),
                "bearish_fvg": bool(bearish_fvg),
                "sweep_long": bool(sweep_long),
                "sweep_short": bool(sweep_short),
                "bias": bias
            }
        except Exception:
            return {"bullish_fvg": False, "bearish_fvg": False, "sweep_long": False, "sweep_short": False, "bias": "NEUTRAL"}

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
        default_details = {
            "trade_valid": False,
            "trigger_price": 0.0,
            "stop_loss": 0.0,
            "atr": 0.0,
            "entry_zone": {},
            "risk_management": {},
            "reason": "بيانات غير كافية أو السوق في حالة تذبذب عرضي."
        }

        try:
            if not ohlcv_5m or not ohlcv_15m or len(ohlcv_5m) < 50 or len(ohlcv_15m) < 50:
                return "NEUTRAL", 0.0, default_details

            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            current_price = float(df_5m['close'].iloc[-1])

            df_5m['ema20'] = df_5m['close'].ewm(span=20, adjust=False).mean()
            df_5m['ema50'] = df_5m['close'].ewm(span=50, adjust=False).mean()

            vwap_baseline = float(df_5m['ema20'].iloc[-1])
            atr_val = float(self.calculate_atr(df_5m, period=14))
            cmf_val = float(self.calculate_cmf(df_5m, period=20))

            if atr_val <= 0 or np.isnan(atr_val):
                atr_val = current_price * 0.01

            smc_data = self.detect_smart_money_elements(df_5m)

            is_bullish_trend = current_price > vwap_baseline and df_5m['ema20'].iloc[-1] > df_5m['ema50'].iloc[-1]
            is_bearish_trend = current_price < vwap_baseline and df_5m['ema20'].iloc[-1] < df_5m['ema50'].iloc[-1]

            direction = "NEUTRAL"
            trade_valid = False
            reason = ""

            decimals = 8 if current_price < 1 else (4 if current_price < 100 else 2)

            if (is_bullish_trend or smc_data["bullish_fvg"] or smc_data["sweep_long"]) and cmf_val > -0.08:
                direction = "LONG"
                trade_valid = True
                
                stop_loss = round(current_price - (2.0 * atr_val), decimals)
                if stop_loss >= current_price:
                    stop_loss = round(current_price * 0.98, decimals)

                tp1 = round(current_price + (1.5 * atr_val), decimals)
                tp2 = round(current_price + (3.0 * atr_val), decimals)
                
                reasons_list = []
                if smc_data["sweep_long"]: reasons_list.append("شفط سيولة ناجح (Liquidity Sweep)")
                if smc_data["bullish_fvg"]: reasons_list.append("رصد فجوة سعرية صاعدة (Bullish FVG)")
                if is_bullish_trend: reasons_list.append("إيجابية المتوسطات والزخم")
                reason = " + ".join(reasons_list) if reasons_list else "دعم المؤسسات وصفقة شراء عالية الاحتمالية."

            elif (is_bearish_trend or smc_data["bearish_fvg"] or smc_data["sweep_short"]) and cmf_val < 0.08:
                direction = "SHORT"
                trade_valid = True
                
                stop_loss = round(current_price + (2.0 * atr_val), decimals)
                if stop_loss <= current_price:
                    stop_loss = round(current_price * 1.02, decimals)

                tp1 = round(current_price - (1.5 * atr_val), decimals)
                tp2 = round(current_price - (3.0 * atr_val), decimals)
                
                reasons_list = []
                if smc_data["sweep_short"]: reasons_list.append("شفط سيولة للقمم (Sweep Short)")
                if smc_data["bearish_fvg"]: reasons_list.append("رصد فجوة سعرية هابطة (Bearish FVG)")
                if is_bearish_trend: reasons_list.append("سلبية المتوسطات والزخم")
                reason = " + ".join(reasons_list) if reasons_list else "ضغط بيعي مؤسسي وصفقة بيع عالية الاحتمالية."
            else:
                stop_loss = round(current_price * 0.98, decimals)
                tp1 = current_price
                tp2 = current_price
                reason = "السوق عرضي أو السيولة متوازنة - لا توجد إشارة دخول قوية حالياً."

            details = {
                "trade_valid": trade_valid,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(atr_val, decimals),
                "entry_zone": {
                    "vwap_baseline": round(vwap_baseline, decimals),
                    "z_score": round(cmf_val, 4),
                    "smc_bias": smc_data["bias"],
                    "fvg_up": smc_data["bullish_fvg"],
                    "sweep_down": smc_data["sweep_long"]
                },
                "risk_management": {
                    "take_profit_1": tp1,
                    "take_profit_2": tp2
                },
                "reason": reason
            }

            return direction, current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
