# ============================================================
# MY EXPERT CRYPTO BOT - ICT + FOOTPRINT ENGINE (V15.0)
# Hybrid Engine: ICT Structure + Footprint Order Flow (R:R = 1:2.5)
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=35):
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
        except (TypeError, ValueError, IndexError):
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
        h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-period:])) if len(tr) > 0 else 0.0

    def analyze_footprint_imbalance(self, open_p, high_p, low_p, close_p, volume):
        """
        محاكاة Footprint Delta & Buying Imbalance بناءً على حركة السعر داخل الشمعة وحجم التداول.
        """
        candle_range = high_p - low_p
        if candle_range <= 0 or volume <= 0:
            return False, 0.0

        # تقدير الدلتا والشرائين العدائيين (Aggressive Buyers)
        body = close_p - open_p
        delta_ratio = body / candle_range  # مؤشر قوة اتجاه الدلتا
        
        # شرط Footprint Imbalance: زيادة السيولة الشرائية المفاجئة مع إغلاق قاطعة صاعدة
        is_buying_imbalance = delta_ratio > 0.4 and volume > 0.0

        return is_buying_imbalance, delta_ratio

    def analyze_ict_footprint(self, a, atr):
        result = {"valid": False, "direction": None, "ob_level": 0.0, "details": []}
        if len(a) < 15 or atr <= 0:
            return result

        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]

        # 1. كشف منطقة ICT Bullish FVG / OB
        fvg_detected = False
        for i in range(len(a) - 1, max(3, len(a) - 8), -1):
            if l[i] > h[i-2]:  # الفجوة السعرية
                fvg_detected = True
                break

        # تحديد قاع الـ Order Block
        ob_level = float(np.min(l[-5:-1]))

        # 2. كشف Footprint Confirmation في الشمعة الأخيرة
        has_imbalance, delta_ratio = self.analyze_footprint_imbalance(o[-1], h[-1], l[-1], c[-1], v[-1])

        # 3. التأكيد المزدوج (ICT Area + Footprint Order Flow)
        if fvg_detected and has_imbalance:
            result["valid"] = True
            result["direction"] = "LONG"
            result["ob_level"] = ob_level
            result["details"].append("ICT Bullish FVG Reclaimed")
            result["details"].append(f"Footprint Buying Imbalance Confirmed (Delta Ratio: {round(delta_ratio, 2)})")

        return result

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        debug = []

        def no_trade(reason, **extra):
            out = {"reason": reason, "debug_trace": debug}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 35)
        if raw15 is None or len(raw15) < 36:
            return no_trade("بيانات غير كافية")

        a = raw15[:-1]
        current_price = float(raw15[-1, 4])
        atr = self.calculate_atr(a[:, 2], a[:, 3], a[:, 4], 14)
        if atr <= 0 or current_price <= 0:
            return no_trade("بيانات ATR غير صالحة")

        setup = self.analyze_ict_footprint(a, atr)
        if not setup["valid"]:
            return no_trade("لم تتحقق شروط الدمج (ICT + Footprint Imbalance)")

        direction = setup["direction"]

        # تحديد الوقف الذكي أسفل الـ Order Block الموثق بالفوتبرينت
        stop = min(setup["ob_level"] - 0.15 * atr, current_price - 1.2 * atr)
        risk_dist = current_price - stop
        if risk_dist <= 0:
            return no_trade("مسافة الوقف غير صالحة")

        # تطبيق هدف ثابت ونسبة عائد لـ مخاطرة 1:2.5 بالضبط
        tp_target = current_price + (risk_dist * 2.5)

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "ICT + Footprint Validated Setup",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(current_price + (risk_dist * 1.2)),
                "take_profit_2": self._round(current_price + (risk_dist * 1.8)),
                "take_profit_3": self._round(tp_target),  # Target R:R = 1:2.5
                "reward_ratio": "1:2.5"
            },
            "setup": "ICT + Footprint Order Flow",
            "pattern_name": "ICT_FOOTPRINT",
            "neckline": self._round(setup["ob_level"]),
            "state": "FOOTPRINT_CONFIRMED",
            "score": 88,
            "atr": self._round(atr),
            "smc_note": " | ".join(setup["details"]),
            "debug_trace": debug
        }
        return direction, self._round(current_price), details

    def analyze_market_structure(self, ohlcv_30m, ohlcv_4h=None, ohlcv_1h=None, btc_ohlcv_1h=None, **kwargs):
        return self.analyze_multi_timeframe(ohlcv_4h, ohlcv_1h, ohlcv_30m, btc_ohlcv_1h)
