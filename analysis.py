# ============================================================
# EXPERT CRYPTO BOT - TRADER ACADEMY LESSON 2 STRATEGY ENGINE
# Support/Resistance Reversal + Confirmation Candle + Volume + Strict SL/TP
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.5)

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

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 35)
        if raw15 is None:
            return no_trade("بيانات الشموع غير كافية")

        try:
            c15 = raw15[:-1]
            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            atr = self.calculate_atr(hi, lo, cl, 14)

            # 1. تحديد مستوى الدعم القوي من القيعان السابقة
            piv_lo = self._pivots(hi, lo, 3, 3)
            if not piv_lo:
                return no_trade("لا توجد مستويات دعم واضحة")
            support_level = min(piv_lo[-3:]) if len(piv_lo) >= 3 else min(piv_lo)

            # 2. تطبيق تفاصيل الدرس: شمعة الارتداد + شمعة التأكيد
            # الشمعة السابقة (i-1): شمعة ارتداد بذيل سفلي قرب الدعم
            # الشمعة الحالية (i): شمعة تأكيد صاعدة تخترق قمة الشمعة السابقة
            prev_lo = lo[-2]
            prev_hi = hi[-2]
            prev_op = op[-2]
            prev_cl = cl[-2]
            
            curr_op = op[-1]
            curr_cl = cl[-1]

            # الشرط أ: هل الشمعة السابقة ارتدت من قرب الدعم ولها ذيل سفلي طويل؟
            near_support = prev_lo <= (support_level + 1.5 * atr)
            lower_wick = min(prev_op, prev_cl) - prev_lo
            prev_body = abs(prev_cl - prev_op)
            is_reversal_candle = lower_wick > prev_body * 0.8 or prev_lo <= support_level

            # الشرط ب: شمعة التأكيد (تنتظر اختراق قمة شمعة الارتداد صعوداً)
            confirmation_level = prev_hi
            is_confirmed_breakout = curr_cl > confirmation_level and curr_cl > curr_op

            # الشرط ج: فوليوم التداول مؤكد
            avg_vol = float(np.mean(vol[-15:-1])) if len(vol) >= 15 else float(np.mean(vol))
            volume_ok = vol[-1] >= (avg_vol * 1.2) or vol[-2] >= (avg_vol * 1.2)

            if not (near_support and is_reversal_candle and is_confirmed_breakout and volume_ok):
                return no_trade("بانتظار تأكيد الارتداد واختراق مستوى التأكيد مع الفوليوم")

            # 3. إدارة الصفقة بدقة طبقاً لأمثلة الدرس
            entry = float(curr_cl) # الدخول الافتراضي بعد التأكيد
            stop = float(support_level - (0.25 * atr)) # وقف الخسارة أسفل الدعم
            
            risk = self.calculate_position_size(entry, stop, "LONG")
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "ارتداد من دعم + شمعة تأكيد صاعدة وفوليوم",
                "score": 95,
                "support_level": self._round(support_level),
                "confirmation_level": self._round(confirmation_level),
                "volume_ok": True,
                "atr": self._round(atr)
            }
            return "LONG", self._round(entry), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:50]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
