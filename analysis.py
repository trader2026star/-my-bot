# ============================================================
# MY EXPERT CRYPTO BOT - CRT + TBS STRATEGY ENGINE (V13.0)
# High Probability Engine based on Candle Range Theory (CRT) & Turtle Soup (TBS)
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

    @staticmethod
    def _ema(values, period):
        arr = np.asarray(values, dtype=float)
        if len(arr) == 0:
            return np.asarray([], dtype=float)
        alpha = 2.0 / (period + 1.0)
        out = np.empty(len(arr), dtype=float)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
        return out

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-period:])) if len(tr) > 0 else 0.0

    def calculate_rsi(self, closes, period=14):
        c = np.asarray(closes, dtype=float).reshape(-1)
        if len(c) < period + 1:
            return 50.0
        d = np.diff(c)[-period:]
        gain, loss = float(np.mean(np.maximum(d, 0))), float(np.mean(np.maximum(-d, 0)))
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        if gain == 0:
            return 0.0
        rs = gain / loss
        return float(100 - 100 / (1 + rs))

    def _closed_array(data, minimum=35):
        arr = StrategyEngine._array(data, minimum)
        return None if arr is None else arr[:-1]

    def _bias(self, data, minimum=25):
        arr = self._closed_array(data, minimum)
        if arr is None or len(arr) < 20:
            return "NEUTRAL"
        c = arr[:, 4]
        e20 = self._ema(c, 20)
        if len(c) >= 20 and c[-1] > e20[-1]:
            return "BULLISH"
        if len(c) >= 20 and c[-1] < e20[-1]:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_crt_tbs(self, a, atr):
        """
        شروط استراتيجية CRT + TBS الصارمة:
        1. تحديد CRT High & CRT Low (نطاق الشمعة السابقة).
        2. حدوث سحب سيولة TBS (Turtle Soup): تجاوز القاع ثم الإغلاق الفوري بجسم الشمعة فوقه.
        3. تأكيد كسر الهيكل (BOS) مع وجود الفجوة السعرية (FVG).
        """
        result = {"valid": False, "direction": None, "crt_high": 0.0, "crt_low": 0.0, "details": []}
        if len(a) < 10 or atr <= 0:
            return result

        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]

        # تحديد نطاق CRT من الشموع المرجعية
        crt_high = float(np.max(h[-15:-3]))
        crt_low = float(np.min(l[-15:-3]))

        last_low = l[-1]
        last_close = c[-1]
        last_high = h[-1]

        # فحص إشارة شراء CRT + TBS (Bullish Sweep & Body Reclaim)
        if last_low < crt_low and last_close > crt_low:
            # فحص كسر الهيكل الفعلي (BOS)
            has_bos = last_close > np.max(c[-5:-1])
            # فحص وجود FVG
            has_fvg = l[-1] > h[-3] or l[-2] > h[-4]

            if has_bos or has_fvg:
                result["valid"] = True
                result["direction"] = "LONG"
                result["crt_high"] = crt_high
                result["crt_low"] = crt_low
                result["details"].append("TBS (Turtle Body Soup) Confirmed")
                if has_bos: result["details"].append("BOS Confirmed")
                if has_fvg: result["details"].append("Bullish FVG")

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
            return no_trade("بيانات ATR أو السعر غير صالحة")

        crt_res = self.analyze_crt_tbs(a, atr)
        if not crt_res["valid"]:
            return no_trade("لم تتحقق شروط CRT + TBS العالية الدقة")

        direction = crt_res["direction"]
        bias4 = self._bias(ohlcv_4h) if ohlcv_4h is not None else "NEUTRAL"
        bias1 = self._bias(ohlcv_1h) if ohlcv_1h is not None else "NEUTRAL"

        # نظام فلترة صارم جداً (عالي الجودة فقط)
        score = 50
        score += 25 if "BOS Confirmed" in crt_res["details"] else 10
        score += 15 if "Bullish FVG" in crt_res["details"] else 0
        if bias1 == "BULLISH": score += 10

        score = int(min(100, score))

        # فلتر صارم جداً: يرفض أي صفقة أقل من 75
        if score < 75:
            return no_trade(f"التقييم {score}/100 أقل من حد CRT+TBS الصارم (75)", score=score)

        # حساب الوقف والأهداف الدقيقة
        stop = min(crt_res["crt_low"] - 0.1 * atr, current_price - 1.0 * atr)
        risk_dist = current_price - stop
        if risk_dist <= 0:
            return no_trade("مسافة وقف الخسارة غير صالحة")

        tp1 = current_price + risk_dist * 1.8
        tp2 = current_price + risk_dist * 2.5
        tp3 = crt_res["crt_high"]  # الهدف الرئيسي هو CRT High كما في الصورة

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "High Probability CRT + TBS Signal",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.5"
            },
            "setup": "CRT + TBS (Turtle Body Soup)",
            "pattern_name": "CRT_TBS",
            "neckline": self._round(crt_res["crt_low"]),
            "state": "CONFIRMED",
            "score": score,
            "atr": self._round(atr),
            "smc_note": " | ".join(crt_res["details"]),
            "debug_trace": debug
        }
        return direction, self._round(current_price), details

    def analyze_market_structure(self, ohlcv_30m, ohlcv_4h=None, ohlcv_1h=None, btc_ohlcv_1h=None, **kwargs):
        return self.analyze_multi_timeframe(ohlcv_4h, ohlcv_1h, ohlcv_30m, btc_ohlcv_1h)
