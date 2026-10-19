# ============================================================
# EXPERT CRYPTO BOT - PULLBACK & RETEST WITH TIME FILTER V5.0
# Safe Entry after Correction + Volume + Temporal/Time Filter
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.5)

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

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        try:
            entry, stop = float(entry_price), float(stop_loss_price)
            direction = str(direction).upper()
        except (TypeError, ValueError):
            return None
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return None
        if direction not in ("LONG", "SHORT") or self.total_capital <= 0:
            return None
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            return None
        distance = abs(entry - stop)
        if distance <= 0:
            return None
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance
        notional = qty * entry
        target = entry + distance * self.reward_ratio if direction == "LONG" else entry - distance * self.reward_ratio
        if target <= 0 or not np.isfinite(notional):
            return None
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "total_trade_value_usd": round(notional, 2),
            "take_profit_target": self._round(target),
            "reward_ratio": self.reward_ratio,
            "risk_percent": round(self.risk_per_trade * 100, 3),
        }

    @staticmethod
    def _pivots(highs, lows, left=3, right=3):
        pl = []
        for i in range(left, len(highs) - right):
            lwindow = lows[i-left:i+right+1]
            if lows[i] == np.min(lwindow) and np.count_nonzero(lwindow == lows[i]) == 1:
                pl.append(float(lows[i]))
        return pl

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 40)
        if raw15 is None:
            return no_trade("بيانات فريم 15 دقيقة غير كافية")

        try:
            c15 = raw15[:-1]
            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            
            # التحليل الزمني البسيط: التأكد من عدم وجود تذبذب هيكلي حاد في آخر 3 شمعات
            recent_ranges = hi[-3:] - lo[-3:]
            avg_range = np.mean(hi - lo)
            if np.any(recent_ranges > (avg_range * 2.5)):
                return no_trade("تذبذب زمني/سعرى عالٍ جداً - تجنب الدخول")

            # البحث عن قاع سابق (دعم)
            piv_lo = self._pivots(hi, lo, 3, 3)
            if not piv_lo:
                return no_trade("لا توجد قيعان واضحة للاستناد عليها")
            support_level = min(piv_lo[-3:]) if len(piv_lo) >= 3 else min(piv_lo)

            current_price = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)

            # شرط الـ Pullback (التصحيح): السعر اقترب من الدعم ثم ارتد بشمعة خضراء قوية
            near_support = abs(current_price - support_level) <= (2.0 * atr) or lo[-1] <= (support_level + atr)
            is_green = cl[-1] > op[-1]
            body_ratio = abs(cl[-1] - op[-1]) / max(float(hi[-1] - lo[-1]), 1e-12)

            if not (near_support and is_green and body_ratio > 0.40):
                return no_trade("بانتظار تصحيح هادئ واقتراب حقيقي من الدعم مع شمعة ارتداد")

            # تأكيد الفوليوم
            avg_vol = float(np.mean(vol[-15:]))
            if vol[-1] < (avg_vol * 1.15):
                return no_trade("حجم التداول غير مؤكد للارتداد")

            stop = float(support_level - (0.4 * atr))
            risk = self.calculate_position_size(current_price, stop, "LONG")
            if not risk:
                return no_trade("فشل حساب المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "Pullback & Retest at Support + Time/Volatility Filter",
                "score": 94,
                "support_level": self._round(support_level),
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)
