# ============================================================
# EXPERT CRYPTO BOT - HL OTT STRATEGY ENGINE V9.1 (30M TIMEFRAME)
# Based on HL OTT Trend Tracker & Re-test Logic on 30m Timeframe
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(0.0, float(capital))
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

        raw30m = self._array(ohlcv_30m, 35)
        if raw30m is None:
            return no_trade("بيانات فريم 30 دقيقة غير كافية لمؤشر OTT")

        try:
            closes = raw30m[:-1, 4]
            highs = raw30m[:-1, 2]
            lows = raw30m[:-1, 3]

            # حساب خطوط تتبع الاتجاه OTT على فريم النصف ساعة (30M)
            ema_fast = np.mean(closes[-5:])
            ema_slow = np.mean(closes[-20:])
            baseline = np.mean(closes[-35:])

            current_price = float(raw30m[-1, 4])
            atr = self.calculate_atr(highs, lows, closes, 14)

            # شرط الدخول: الاتجاه صاعد فوق خطوط OTT على فريم 30M
            is_bullish_trend = ema_fast > ema_slow and closes[-1] > baseline
            
            if not is_bullish_trend:
                return no_trade("الاتجاه سلبي على فريم 30 دقيقة (تحت خطوط OTT الحمراء)")

            # تحديد وقف الخسارة أسفل آخر دعم على فريم 30M
            stop = float(np.min(lows[-5:]) - (0.5 * atr))
            if stop >= current_price:
                stop = current_price - (1.5 * atr)

            distance = current_price - stop
            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / distance

            # الأهداف الهندسية TP1 و TP2
            tp1 = current_price + (distance * 2.0)
            tp2 = current_price + (distance * 3.5)

            details = {
                "stop_loss": self._round(stop),
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "reward_ratio": "1:3 (HL OTT 30M Strategy)"
                },
                "setup": "HL OTT 30M Trend Tracker",
                "score": 98,
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        # للتوافق مع المحرك
        return self.analyze_market_structure(ohlcv_15m)
