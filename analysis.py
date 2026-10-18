# ============================================================
# EXPERT CRYPTO BOT - H4 SCALPING: CANDLE x MA 10 STRATEGY
# Based on Candlestick Close Above/Below MA 10 on H4 timeframe
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=1.5):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.0)

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
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    @staticmethod
    def _sma(values, period=10):
        v = np.asarray(values, dtype=float)
        if len(v) < period:
            return None
        return float(np.mean(v[-period:]))

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

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h=None, ohlcv_15m=None, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        # الاعتماد الأساسي على فريم الـ H4 كما في الاستراتيجية
        raw4 = self._array(ohlcv_4h, 15)
        if raw4 is None:
            return no_trade("بيانات فريم H4 غير كافية")

        try:
            c4 = raw4[:-1] # استبعاد الشمعة الحالية غير المكتملة
            closes = c4[:, 4]
            highs = c4[:, 2]
            lows = c4[:, 3]
            
            if len(closes) < 12:
                return no_trade("عدد الشموع قليل لحساب موفينج 10")

            # حساب مؤشر المتوسط المتحرك MA 10
            ma_10 = self._sma(closes, 10)
            if ma_10 is None:
                return no_trade("فشل حساب MA 10")

            current_close = float(closes[-1])
            prev_close = float(closes[-2])
            atr = self.calculate_atr(highs, lows, closes, 14)

            direction = "NEUTRAL"
            setup_name = ""

            # شرط الشراء: الشمعة أغلقت فوق الموفينج (Candle closes ABOVE MA)
            if prev_close <= ma_10 and current_close > ma_10:
                direction = "LONG"
                setup_name = "H4 Scalping: Candle Closed ABOVE MA 10 (BUY)"
            
            # شرط البيع: الشمعة أغلقت تحت الموفينج (Candle closes BELOW MA)
            elif prev_close >= ma_10 and current_close < ma_10:
                direction = "SHORT"
                setup_name = "H4 Scalping: Candle Closed BELOW MA 10 (SELL)"

            if direction == "NEUTRAL":
                return no_trade("لم يحدث تقاطع أو إغلاق فوق/تحت الموفينج 10 بعد")

            # تحديد وقف الخسارة والأهداف بدقة (بناءً على نسبة الـ ATR أو مسافة متوازنة)
            distance = max(atr * 1.5, current_close * 0.005)
            if direction == "LONG":
                stop = current_close - distance
            else:
                stop = current_close + distance

            risk = self.calculate_position_size(current_close, stop, direction)
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر للصفقة")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": setup_name,
                "score": 95,
                "ma_10_value": self._round(ma_10),
                "atr": self._round(atr)
            }
            return direction, self._round(current_close), details

        except Exception as exc:
            return no_trade(f"خطأ في التحليل: {str(exc)[:50]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
