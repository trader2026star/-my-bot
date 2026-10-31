# ============================================================
# MY EXPERT CRYPTO BOT - Institutional SMC Engine (v65.6_STRICT_PRO)
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

    def detect_smc_structure(self, df):
        try:
            if len(df) < 30:
                return {"bias": "NEUTRAL", "bullish_fvg": False, "bearish_fvg": False, "ob_zone": 0.0, "is_mitigated": False, "is_choch": False, "reason": "بيانات غير كافية"}

            ob_zone = 0.0
            is_mitigated = False
            for i in range(len(df)-2, 10, -1):
                if df['close'].iloc[i] < df['open'].iloc[i] and df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    ob_zone = float(df['low'].iloc[i])
                    mitigating_price = df['low'].iloc[-1]
                    if mitigating_price <= df['high'].iloc[i]:
                        is_mitigated = True
                    break

            is_bullish_structure = False
            is_choch = False
            recent_high = df['high'].iloc[-15:-2].max()
            recent_low = df['low'].iloc[-15:-2].min()
            
            if df['close'].iloc[-1] > recent_high:
                is_bullish_structure = True
                is_choch = True 

            bullish_fvg = False
            for i in range(3, len(df)):
                if df['low'].iloc[i] > df['high'].iloc[i-3]:
                    bullish_fvg = True
                    break

            bias = "NEUTRAL"
            reason = "لا يوجد تأكيد هيكلي صاعد أو هابط."
            
            if (is_mitigated or bullish_fvg) and (is_bullish_structure or ob_zone > 0):
                bias = "LONG"
                reason = "اختبار ناجح لمنطقة Order Block + فجوة صاعدة وسيولة إيجابية."
            elif is_bullish_structure:
                bias = "LONG"
                reason = "اختراق هيكلي صاعد (BOS/CHoCH)."
            elif df['close'].iloc[-1] < recent_low:
                bias = "SHORT"
                reason = "كسر هيكل هابط."

            return {
                "bias": bias,
                "bullish_fvg": bool(bullish_fvg),
                "bearish_fvg": False,
                "ob_zone": ob_zone,
                "is_mitigated": is_mitigated,
                "is_choch": is_choch,
                "reason": reason
            }
        except Exception as e:
            return {"bias": "NEUTRAL", "bullish_fvg": False, "bearish_fvg": False, "ob_zone": 0.0, "is_mitigated": False, "is_choch": False, "reason": f"خطأ برمجى: {e}"}

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
            vwap_baseline = float(df_5m['ema20'].iloc[-1])
            atr_val = float(self.calculate_atr(df_5m, period=14))
            cmf_val = float(self.calculate_cmf(df_5m, period=20))

            if atr_val <= 0 or np.isnan(atr_val):
                atr_val = current_price * 0.01

            smc = self.detect_smc_structure(df_15m)

            direction = smc["bias"]
            trade_valid = False

            decimals = 8 if current_price < 0.1 else (4 if current_price < 10 else 2)

            high_15m = float(df_15m['high'].iloc[-20:].max())
            low_15m = float(df_15m['low'].iloc[-20:].min())

            if direction == "LONG":
                trade_valid = True
                
                stop_loss = round(min(smc["ob_zone"], current_price - (1.5 * atr_val)), decimals)
                if stop_loss >= current_price or stop_loss == 0:
                    stop_loss = round(current_price * 0.98, decimals)

                tp1 = round(max(current_price + (1.5 * atr_val), current_price + (high_15m - current_price) * 0.5), decimals)
                tp2 = round(max(current_price + (3.5 * atr_val), high_15m), decimals)
                tp3 = round(max(current_price + (6.0 * atr_val), high_15m + (2.0 * atr_val)), decimals)
                
                reasons = []
                if smc["is_mitigated"]: reasons.append(f"اختبار +OB عند {round(smc['ob_zone'], decimals)}")
                if smc["is_choch"]: reasons.append("تغير شخصية الهيكل (CHoCH)")
                if smc["bullish_fvg"]: reasons.append("رصد فجوة صاعدة (FVG Up)")
                if cmf_val != 0: reasons.append(f"سيولة CMF: {round(cmf_val, 4)}")
                
                reason = " + ".join(reasons) if reasons else "تأكيد هيكلي صاعد مدعوم بالسيولة."

            elif direction == "SHORT":
                trade_valid = True
                
                stop_loss = round(max(current_price + (1.5 * atr_val), current_price + 0.005), decimals)
                if stop_loss <= current_price:
                    stop_loss = round(current_price * 1.02, decimals)

                tp1 = round(min(current_price - (1.5 * atr_val), current_price - (current_price - low_15m) * 0.5), decimals)
                tp2 = round(min(current_price - (3.5 * atr_val), low_15m), decimals)
                tp3 = round(min(current_price - (6.0 * atr_val), low_15m - (2.0 * atr_val)), decimals)
                reason = "ضغط بيعي مؤسسي مدعوم بالفجوات وهيكل هابط."
            else:
                stop_loss = round(current_price * 0.98, decimals)
                tp1 = current_price
                tp2 = current_price
                tp3 = current_price

            details = {
                "trade_valid": trade_valid,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(atr_val, decimals),
                "entry_zone": {
                    "vwap_baseline": round(vwap_baseline, decimals),
                    "z_score": round(cmf_val, 4),
                    "smc_bias": smc["bias"],
                    "fvg_up": smc["bullish_fvg"],
                    "sweep_down": smc["is_mitigated"],
                    "order_block": round(smc["ob_zone"], decimals)
                },
                "risk_management": {
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "take_profit_3": tp3
                },
                "reason": reason
            }

            return direction, current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
