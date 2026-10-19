# ============================================================
# EXPERT CRYPTO BOT - SMC & TRADINGVIEW POSITION ENGINE V7.0
# Multiple Targets (TP1 & TP2) + Stop Loss + R:R Calculation
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

    def calculate_position_levels(self, entry_price, stop_loss_price, direction="LONG"):
        try:
            entry, stop = float(entry_price), float(stop_loss_price)
            direction = str(direction).upper()
        except (TypeError, ValueError):
            return None
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return None
        if direction != "LONG" or self.total_capital <= 0 or stop >= entry:
            return None
        
        distance = entry - stop
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance

        # تحديد هدفين هندسيين مثل أداة تريدينج فيو (الهدف الأول 1:2 والهدف الثاني 1:3.5)
        tp1 = entry + (distance * 2.0)
        tp2 = entry + (distance * 3.5)

        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "stop_loss": self._round(stop),
            "take_profit_1": self._round(tp1),
            "take_profit_2": self._round(tp2),
            "risk_reward_ratio": "1:2.5 (Avg)"
        }

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw1h = self._array(ohlcv_1h, 45)
        raw15m = self._array(ohlcv_15m, 40)
        
        if raw1h is None or raw15m is None:
            return no_trade("بيانات السوق غير كافية")

        try:
            c1h = raw1h[:-1]
            c15 = raw15m[:-1]

            # كسر الهيكل (BOS)
            closes_1h = c1h[:, 4]
            highs_1h = c1h[:, 2]
            prev_high = np.max(highs_1h[-20:-3])
            
            if closes_1h[-1] <= prev_high:
                return no_trade("لم يحدث كسر هيكل صاعد (BOS)")

            # الفجوة السعرية FVG على فريم 15 دقيقة
            hi15, lo15, cl15, vol15 = c15[:, 2], c15[:, 3], c15[:, 4], c15[:, 5]
            fvg_top = float(lo15[-1])
            fvg_bottom = float(hi15[-3])
            if fvg_top <= fvg_bottom:
                return no_trade("لا توجد فجوة سعرية (FVG)")

            current_price = float(cl15[-1])
            atr = self.calculate_atr(hi15, lo15, cl15, 14)

            # وقف الخسارة أسفل منطقة الطلب (مثل المنطقة الحمراء في أداة التريدينج فيو)
            ob_low = float(np.min(lo15[-5:]))
            stop = float(ob_low - (0.4 * atr))

            levels = self.calculate_position_levels(current_price, stop, "LONG")
            if not levels:
                return no_trade("فشل حساب مستويات الصفقة")

            details = {
                "stop_loss": levels["stop_loss"],
                "risk_management": levels,
                "setup": "SMC FVG + TradingView Position Targets",
                "score": 99,
                "fvg_zone": f"{self._round(fvg_bottom)} - {self._round(fvg_top)}",
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)
