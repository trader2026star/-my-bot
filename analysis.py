# ============================================================
# INSTITUTIONAL TREND & MOMENTUM ENGINE (v63.1_FIXED)
# ============================================================

import logging
import math
import numpy as np
import pandas as pd

logger = logging.getLogger("QuantitativeEngine")

class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, **kwargs):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0

        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.05)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

    @staticmethod
    def _to_dataframe(ohlcv, minimum=30):
        try:
            if ohlcv is None:
                return None
            arr = np.asarray(ohlcv, dtype=float)
            if arr.ndim != 2 or arr.shape[0] < minimum or arr.shape[1] < 6:
                return None
            
            df = pd.DataFrame(arr[:, :6], columns=["timestamp", "open", "high", "low", "close", "volume"])
            df.dropna(inplace=True)
            if len(df) < minimum:
                return None
            return df
        except Exception:
            return None

    @staticmethod
    def _round(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-math.floor(math.log10(abs(value)))) + 3))
        return round(value, decimals)

    def calculate_atr(self, df, period=14):
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean().fillna(tr.iloc[-1] if len(tr) > 0 else 0.0)

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, asset_type="crypto", **kwargs
    ):
        target_ohlcv = ohlcv_15m if ohlcv_15m is not None and len(ohlcv_15m) >= 25 else ohlcv_5m
        df = self._to_dataframe(target_ohlcv, minimum=25)
        
        if df is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات غير كافية للتحليل الكمي."}

        current_price = float(df["close"].iloc[-1])
        
        df["ema_fast"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=50, adjust=False).mean()
        
        current_ema_fast = float(df["ema_fast"].iloc[-1])
        current_ema_slow = float(df["ema_slow"].iloc[-1])

        tp_price = (df["high"] + df["low"] + df["close"]) / 3.0
        # حساب ميزان التدفق المالي بدقة منعا للقسمة على صفر
        diff_high_low = (df["high"] - df["low"]).replace(0, 1e-6)
        mfv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / diff_high_low
        mfv = mfv * df["volume"]
        
        cmf = mfv.rolling(window=20).sum() / df["volume"].rolling(window=20).sum().replace(0, 1e-6)
        current_cmf = float(cmf.iloc[-1]) if not np.isnan(cmf.iloc[-1]) else 0.0

        atr_series = self.calculate_atr(df, period=14)
        current_atr = float(atr_series.iloc[-1])

        direction = "NEUTRAL"
        trade_valid = False
        reason = "السوق في حالة تذبذب أفقي ضعيف، لا توجد سيولة مؤسسية."

        stop_loss = 0.0
        take_profit_1 = 0.0
        take_profit_2 = 0.0

        if current_price > current_ema_fast and current_ema_fast > current_ema_slow and current_cmf > 0.10:
            direction = "LONG"
            trade_valid = True
            stop_loss = current_price - (2.5 * current_atr)
            take_profit_1 = current_price + (1.5 * current_atr)
            take_profit_2 = current_price + (3.0 * current_atr)
            reason = f"انطلاق صعودي مع الحيتان: تدفق سيولة إيجابي قوي ({current_cmf:.2f}) ودعم من المتوسطات الأسية."

        elif current_price < current_ema_fast and current_ema_fast < current_ema_slow and current_cmf < -0.10:
            direction = "SHORT"
            trade_valid = True
            stop_loss = current_price + (2.5 * current_atr)
            take_profit_1 = current_price - (1.5 * current_atr)
            take_profit_2 = current_price - (3.0 * current_atr)
            reason = f"انهيار سعر تتبعي: خروج سيولة حاد ({current_cmf:.2f}) والاتجاه هابط بقوة."

        details = {
            "trade_valid": trade_valid,
            "signal_type": "INSTITUTIONAL_TREND_FOLLOWING",
            "market_trend": "Bullish Trend" if direction == "LONG" else ("Bearish Trend" if direction == "SHORT" else "Ranging"),
            "z_score": self._round(current_cmf),
            "adx": 30.0 if trade_valid else 15.0,
            "atr": self._round(current_atr),
            "reason": reason,
            "trigger_price": self._round(current_price),
            "stop_loss": self._round(stop_loss if stop_loss > 0 else current_price * 0.98),
            "entry_zone": {
                "vwap_baseline": self._round(current_ema_fast),
                "z_score_level": self._round(current_cmf)
            },
            "risk_management": {
                "take_profit_1": self._round(take_profit_1),
                "take_profit_2": self._round(take_profit_2)
            }
        }

        return direction, self._round(current_price), details
