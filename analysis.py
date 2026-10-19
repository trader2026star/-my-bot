# ============================================================
# EXPERT CRYPTO BOT - TOP-DOWN SMC ENGINE V8.0
# Hierarchical Analysis: Higher TF (4H/1H Direction & Key Levels) -> Lower TF (15M Entry)
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=30):
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

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw4h = self._array(ohlcv_4h, 25)
        raw1h = self._array(ohlcv_1h, 30)
        raw15m = self._array(ohlcv_15m, 30)

        if raw4h is None or raw1h is None or raw15m is None:
            return no_trade("بيانات الفريمات غير كافية للتحليل الهرمي")

        try:
            # الخطوة 1: الفريم العالي (Higher Timeframe - 4H) لتحديد الاتجاه العام (Broad View)
            closes_4h = raw4h[:-1, 4]
            ema_4h_fast = np.mean(closes_4h[-10:])
            ema_4h_slow = np.mean(closes_4h[-25:])
            
            if ema_4h_fast <= ema_4h_slow:
                return no_trade("اتجاه الفريم العالي 4H هابط - لا يمكن الشراء")

            # الخطوة 2: فريم التحليل المتوسط (Analysis Timeframe - 1H) وتحديد المستويات الرئيسية
            highs_1h = raw1h[:-1, 2]
            lows_1h = raw1h[:-1, 3]
            key_support = float(np.min(lows_1h[-20:]))
            key_resistance = float(np.max(highs_1h[-20:]))

            current_price = float(raw15m[-2, 4])

            # الخطوة 3: فريم الدخول والتنفيذ (Lower Timeframe - 15M) للبحث عن منطقة الطلب والارتداد
            hi15, lo15, cl15, vol15 = (raw15m[:-1, i] for i in (2, 3, 4, 5))
            
            # التأكد من توافق الفريمات وأن السعر قريب من مستوى دعم أو منطقة طلب
            near_support = current_price <= (key_support * 1.03) or cl15[-1] > lo15[-1]
            if not near_support:
                return no_trade("السعر لم يصل لمستوى الدعم الرئيسي على الفريم العالي بعد")

            atr = self.calculate_atr(hi15, lo15, cl15, 14)
            stop = float(key_support - (0.5 * atr))
            
            if stop >= current_price:
                return no_trade("مستوى وقف الخسارة غير آمن")

            distance = current_price - stop
            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / distance

            tp1 = current_price + (distance * 2.0)
            tp2 = current_price + (distance * 3.5)

            details = {
                "stop_loss": self._round(stop),
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "reward_ratio": "1:3 (Top-Down Aligned)"
                },
                "setup": "Top-Down Analysis (4H Trend + 1H Key Level + 15M Entry)",
                "score": 99,
                "key_level": self._round(key_support),
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)
