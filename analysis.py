# ============================================================
# MY EXPERT CRYPTO BOT - V22.0 Institutional Sniper Pro
# Strict Trend + Institutional Value Areas (VAL/VAH) + Candle Confirmation
# Signal-only: does NOT place exchange orders.
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

    def calculate_volume_profile(self, ohlcv, bins=35):
        arr = self._array(ohlcv, minimum=20)
        if arr is None:
            return None, None, None
        highs, lows, volumes = arr[:-1, 2], arr[:-1, 3], arr[:-1, 5]
        min_price, max_price = float(np.min(lows)), float(np.max(highs))
        if max_price <= min_price:
            return None, None, None

        edges = np.linspace(min_price, max_price, bins + 1)
        bin_volumes = np.zeros(bins, dtype=float)
        for h, l, v in zip(highs, lows, volumes):
            if v <= 0:
                continue
            candle_range = h - l
            if candle_range <= 0:
                idx = min(bins - 1, max(0, int(np.searchsorted(edges, l, side="right") - 1)))
                bin_volumes[idx] += v
                continue
            first = max(0, min(bins - 1, int(np.searchsorted(edges, l, side="right") - 1)))
            last = max(0, min(bins - 1, int(np.searchsorted(edges, h, side="left"))))
            for b in range(first, last + 1):
                overlap = max(0.0, min(h, edges[b + 1]) - max(l, edges[b]))
                if overlap > 0:
                    bin_volumes[b] += v * overlap / candle_range

        total_vol = float(np.sum(bin_volumes))
        if total_vol <= 0:
            return None, None, None
        poc_idx = int(np.argmax(bin_volumes))
        poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)
        val = float(edges[max(0, poc_idx - int(bins * 0.2))])
        vah = float(edges[min(bins, poc_idx + int(bins * 0.2))])
        return poc, val, vah

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"trade_valid": False, "reason": reason, "score": 0}

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات الفريمات غير مكتملة")

        d1 = self._array(ohlcv_1d, 20)
        h4 = self._array(ohlcv_4h, 20)
        m15 = self._array(ohlcv_15m, 20)
        if d1 is None or h4 is None or m15 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل")

        daily_close = float(d1[-2, 4])
        daily_ma20 = float(np.mean(d1[:-1, 4][-20:]))
        
        h4_close = float(h4[-2, 4])
        h4_ma10 = float(np.mean(h4[:-1, 4][-10:]))

        # بيانات الشمعة الحالية والسابقة على فريم 15 دقيقة للتأكيد
        open_ = float(m15[-2, 1])
        close = float(m15[-2, 4])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)
        poc, val, vah = self.calculate_volume_profile(ohlcv_1h)
        if not poc or not val or not vah:
            return no_trade("تعذر حساب نطاق السيولة المؤسسية")

        # قواعد الترند الصارم
        is_bullish = daily_close >= daily_ma20 and h4_close >= h4_ma10
        is_bearish = daily_close < daily_ma20 and h4_close < h4_ma10

        if not is_bullish and not is_bearish:
            return no_trade("الترند العام متذبذب ولا يحقق شروط الأمان المؤسسي")

        if is_bullish:
            # شروط الـ LONG مع تأكيد ملامسة VAL وشمعة ارتداد خضراء بجسم لا يقل عن 45%
            near_val = (val * 0.998 <= low <= val * 1.015) or (val * 0.998 <= close <= val * 1.015)
            strong_green = (close > open_) and (body_ratio >= 0.45)

            if not near_val:
                return no_trade("السعر لم يلامس منطقة القيمة الشرائية (VAL)")
            if not strong_green:
                return no_trade(f"قريب من VAL لكن شمعة الارتداد ضعيفة (جسم الشمعة: {round(body_ratio*100)}%)")

            score = 92
            stop = float(min(low, val) - (1.2 * atr))
            risk_dist = close - stop
            if risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة غير صالحة رياضياً")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist

            tp1 = close + (risk_dist * 1.5)
            tp2 = close + (risk_dist * 2.5)
            tp3 = close + (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "Institutional VAL Support & Confirmed Green Candle",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V22.0 Institutional Confirmed LONG",
                "risk_management": {
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"Confirmed LONG | VAL={self._round(val)} | Body={round(body_ratio*100)}%"
            }
            return "LONG", self._round(close), details

        else:
            # شروط الـ SHORT مع تأكيد ملامسة VAH وشمعة هبوط حمراء مؤكدة
            near_vah = (vah * 0.985 <= high <= vah * 1.002) or (vah * 0.985 <= close <= vah * 1.002)
            strong_red = (close < open_) and (body_ratio >= 0.45)

            if not near_vah:
                return no_trade("السعر لم يلامس منطقة المقاومة البيعية (VAH)")
            if not strong_red:
                return no_trade(f"قريب من VAH لكن شمعة الرفض ضعيفة (جسم الشمعة: {round(body_ratio*100)}%)")

            score = 92
            stop = float(max(high, vah) + (1.2 * atr))
            risk_dist = stop - close
            if risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة غير صالحة رياضياً")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist

            tp1 = close - (risk_dist * 1.5)
            tp2 = close - (risk_dist * 2.5)
            tp3 = close - (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "Institutional VAH Resistance & Confirmed Red Candle",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V22.0 Institutional Confirmed SHORT",
                "risk_management": {
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"Confirmed SHORT | VAH={self._round(vah)} | Body={round(body_ratio*100)}%"
            }
            return "SHORT", self._round(close), details
