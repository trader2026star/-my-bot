# ============================================================
# EXPERT CRYPTO BOT - DOUBLE BOTTOM + INVERSE H&S ENGINE V10.0
# Strategy: Inverse Head & Shoulders + Double Bottom & Retest
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=40):
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
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-min(max(1, int(period)), len(tr)):])) if len(tr) else 0.0

    def analyze_market_structure(self, ohlcv_30m):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw30m = self._array(ohlcv_30m, 40)
        if raw30m is None:
            return no_trade("بيانات فريم 30 دقيقة غير كافية للتحليل")

        try:
            closes = raw30m[:-1, 4]
            highs = raw30m[:-1, 2]
            lows = raw30m[:-1, 3]

            current_price = float(raw30m[-1, 4])
            atr = self.calculate_atr(highs, lows, closes, 14)

            # 1. تحديد مستويات الرأس والقاع المزدوج والكتفين
            # تقسيم الشمعات المتاحة لرصد قاع الكتف الأيسر، الرأس (القاع المزدوج)، والكتف الأيمن
            left_shoulder_low = float(np.min(lows[-35:-25]))
            head_low_1 = float(np.min(lows[-25:-18]))
            head_low_2 = float(np.min(lows[-18:-10]))
            right_shoulder_low = float(np.min(lows[-10:-3]))

            # التأكد من صحة نموذج القاع المزدوج في الرأس (Head / Double Bottom)
            is_double_bottom = abs(head_low_1 - head_low_2) / head_low_1 <= 0.015
            is_head_lowest = (head_low_1 < left_shoulder_low) and (head_low_2 < right_shoulder_low)

            if not (is_double_bottom and is_head_lowest):
                return no_trade("لم يكتمل نموذج القاع المزدوج في الرأس")

            # 2. تحديد خط العنق (Neckline)
            neckline_resistance = float(np.max(highs[-25:-10]))

            # 3. التأكد من كسر خط العنق مع إعادة الاختبار (Breakout & Retest)
            max_recent_high = float(np.max(highs[-5:]))
            has_broken_neckline = max_recent_high > neckline_resistance
            is_retesting = abs(current_price - neckline_resistance) / neckline_resistance <= 0.012

            if not (has_broken_neckline and is_retesting):
                return no_trade("لم يحدث إعادة اختبار (Retest) لخط العنق بعد الاختراق")

            # 4. حساب أهداف الصفقة ووقف الخسارة أسفل الكتف الأيمن
            stop = float(right_shoulder_low - (0.3 * atr))
            if stop >= current_price:
                stop = current_price - (1.5 * atr)

            pattern_height = neckline_resistance - min(head_low_1, head_low_2)
            tp1 = current_price + pattern_height
            tp2 = current_price + (pattern_height * 1.618)

            distance = current_price - stop
            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / distance if distance > 0 else 0

            details = {
                "stop_loss": self._round(stop),
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "reward_ratio": "1:2.5 (Double Bottom + Inv H&S)"
                },
                "setup": "Inverse H&S + Double Bottom (Neckline Retest)",
                "neckline": self._round(neckline_resistance),
                "right_shoulder": self._round(right_shoulder_low),
                "score": 99,
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_15m)
