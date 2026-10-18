# ============================================================
# EXPERT CRYPTO BOT - CANDLESTICK & S/R STRATEGY ENGINE
# Based on Price Action, S/R Levels, Volume & Reversal Candles
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.5)

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
        ph, pl = [], []
        for i in range(left, len(highs) - right):
            hwindow = highs[i-left:i+right+1]
            lwindow = lows[i-left:i+right+1]
            if highs[i] == np.max(hwindow) and np.count_nonzero(hwindow == highs[i]) == 1:
                ph.append(float(highs[i]))
            if lows[i] == np.min(lwindow) and np.count_nonzero(lwindow == lows[i]) == 1:
                pl.append(float(lows[i]))
        return ph, pl

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 30)
        if raw15 is None:
            return no_trade("Invalid or insufficient OHLCV data")

        try:
            c15 = raw15[:-1]
            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)

            # 1. تحليل الشمعة الأخيرة (الجسم والذيل)
            candle_range = max(float(hi[-1] - lo[-1]), 1e-12)
            body = abs(float(cl[-1] - op[-1]))
            body_ratio = body / candle_range
            is_green = cl[-1] > op[-1]
            
            # ذيل سفلي طويل (شمعة ارتداد) أو شمعة قوية
            lower_wick = min(op[-1], cl[-1]) - lo[-1]
            upper_wick = hi[-1] - max(op[-1], cl[-1])

            # 2. فوليوم التداول مقارنة بالمتوسط
            avg_vol = float(np.mean(vol[-15:-1])) if len(vol) >= 15 else float(np.mean(vol))
            volume_ok = vol[-1] >= (avg_vol * 1.2) # ارتفاع الفوليوم

            # 3. مستويات الدعم والمقاومة من القيعان والقمم السابقة
            piv_hi, piv_lo = self._pivots(hi, lo, 2, 2)
            support_level = min(piv_lo) if piv_lo else float(np.min(lo[:-1]))
            resistance_level = max(piv_hi) if piv_hi else float(np.max(hi[:-1]))

            # شروط الدخول لونغ بناءً على الارتداد من الدعم أو اختراق مقاومة بشمعة قوية وفوليوم
            direction = "NEUTRAL"
            setup_name = ""

            # شرط الارتداد من الدعم (شمعة ارتداد بذيل سفلي أو شمعة قوية خضراء بالقرب من الدعم)
            near_support = abs(lo[-1] - support_level) <= (1.5 * atr)
            is_reversal_candle = is_green and (lower_wick > body * 1.2 or body_ratio >= 0.5)

            if near_support and is_reversal_candle and volume_ok:
                direction = "LONG"
                setup_name = "ارتداد من الدعم + شمعة قوية وفوليوم"
            elif cl[-1] > resistance_level and body_ratio >= 0.6 and volume_ok:
                direction = "LONG"
                setup_name = "اختراق مقاومة بشمعة قوية وفوليوم"

            if direction == "NEUTRAL":
                return no_trade("لم تتحقق شروط الشمعة أو الدعم/المقاومة والفوليوم")

            # وقف الخسارة أسفل الشمعة أو الدعم بقليل مع مسافة آمنة
            stop = float(min(lo[-1], support_level) - (0.3 * atr))
            risk = self.calculate_position_size(entry, stop, direction)
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": setup_name,
                "score": 92,
                "support_level": self._round(support_level),
                "resistance_level": self._round(resistance_level),
                "volume_ok": bool(volume_ok),
                "body_ratio": round(body_ratio, 2),
                "atr": self._round(atr)
            }
            return direction, self._round(entry), details

        except Exception as e:
            return no_trade(f"خطأ في التحليل: {str(e)[:50]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
