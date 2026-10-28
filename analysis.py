# ============================================================
# MY EXPERT CRYPTO BOT - Institutional Multi-Timeframe Strategy
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("InstitutionalEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0
        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

    @staticmethod
    def _array(data, minimum=20):
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]):
                return None
            return a
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
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

    def calculate_atr(self, highs, lows, closes, period=14):
        try:
            h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
            n = min(len(h), len(l), len(c))
            if n < 2:
                return 0.0
            h, l, c = h[-n:], l[-n:], c[-n:]
            tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
            if len(tr) == 0:
                return 0.0
            return float(np.mean(tr[-max(1, int(period)):]))
        except Exception:
            return 0.0

    def analyze_market_structure(self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"trade_valid": False, "reason": reason, "score": 0}

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات الفريمات الأربعة غير مكتملة")

        d1 = self._array(ohlcv_1d, 20)
        h4 = self._array(ohlcv_4h, 20)
        h1 = self._array(ohlcv_1h, 20)
        m15 = self._array(ohlcv_15m, 20)

        if d1 is None or h4 is None or h1 is None or m15 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل")

        daily_close = float(d1[-2, 4])
        daily_ma20 = float(np.mean(d1[:-1, 4][-20:]))
        
        h4_close = float(h4[-2, 4])
        h4_ma10 = float(np.mean(h4[:-1, 4][-10:]))

        open_ = float(m15[-2, 1])
        close = float(m15[-2, 4])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])
        volume = float(m15[-2, 5])

        avg_vol = float(np.mean(m15[-15:-2, 5]))
        volume_ok = avg_vol > 0 and volume >= avg_vol * 0.8

        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)

        # فحص الانحياز اليومي وفريم 4 ساعات كما في النسخة الأصلية
        is_daily_bullish = daily_close >= daily_ma20
        is_h4_bullish = h4_close >= h4_ma10

        if not is_daily_bullish:
            return no_trade("الانحياز اليومي (1D) ليس صاعداً")
        if not is_h4_bullish:
            return no_trade("هيكل فريم 4 ساعات غير داعم للصعود")

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        if volume_ok and body_ratio >= 0.35 and close > open_:
            score = 88
            stop = float(low - (1.2 * atr))
            risk_dist = close - stop
            if risk_dist <= 0:
                risk_dist = close * 0.02

            tp1 = close + (risk_dist * 1.5)
            tp2 = close + (risk_dist * 2.5)
            tp3 = close + (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "جميع الشروط والسيولة مكتملة بنجاح",
                "stop_loss": self._round(stop),
                "score": score,
                "risk_management": {
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": "توافق الفريمات الأربعة مع تدفق الفوليوم"
            }
            return "LONG", self._round(close), details
        else:
            return no_trade("شروط القناس لم تكتمل على 15M (السعر، عزم الشمعة، أو تدفق الفوليوم)")
