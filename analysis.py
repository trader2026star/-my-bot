# ============================================================
# EXPERT CRYPTO BOT - ADVANCED SMC & FVG COMPOSITE ENGINE V3.0
# Trend Filter + Smart Money Concepts + FVG + Volume Confirmation
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

    @staticmethod
    def _ema(values, period):
        v = np.asarray(values, dtype=float)
        if len(v) < period:
            return None
        alpha = 2.0 / (period + 1.0)
        out = float(v[0])
        for x in v[1:]:
            out = alpha * float(x) + (1.0 - alpha) * out
        return out

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

    def _trend(self, closes):
        if len(closes) < 50:
            return "NEUTRAL"
        ema_fast = self._ema(closes, 20)
        ema_slow = self._ema(closes, 50)
        if ema_fast is None or ema_slow is None:
            return "NEUTRAL"
        if ema_fast > ema_slow and closes[-1] > ema_slow:
            return "BULLISH"
        elif ema_fast < ema_slow and closes[-1] < ema_slow:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw4 = self._array(ohlcv_4h, 50)
        raw1 = self._array(ohlcv_1h, 50)
        raw15 = self._array(ohlcv_15m, 40)
        
        if raw4 is None or raw1 is None or raw15 is None:
            return no_trade("بيانات السوق غير كافية للتحليل")

        try:
            c4, c1, c15 = raw4[:-1], raw1[:-1], raw15[:-1]
            
            # 1. فلتر الاتجاه العام للفريمات الكبرى (يجب أن يكون صاعداً بوضوح)
            trend_4h = self._trend(c4[:, 4])
            trend_1h = self._trend(c1[:, 4])
            
            if trend_4h != "BULLISH" or trend_1h != "BULLISH":
                return no_trade("السوق غير مستقر أو غير صاعد (فلتر الاتجاه العام مانع للتداول)")

            # فلتر البيتكوين إن وجد
            if btc_ohlcv_1h is not None:
                btc_raw = self._array(btc_ohlcv_1h, 40)
                if btc_raw is not None:
                    btc_trend = self._trend(btc_raw[:-1, 4])
                    if btc_trend == "BEARISH":
                        return no_trade("اتجاه البيتكوين العام هابط - حظر الشراء")

            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)

            # 2. التحقق من قوة الشمعة الأخيرة وفوليوم التداول
            candle_range = max(float(hi[-1] - lo[-1]), 1e-12)
            body = abs(float(cl[-1] - op[-1]))
            body_ratio = body / candle_range
            is_green = cl[-1] > op[-1]

            if not is_green or body_ratio < 0.45:
                return no_trade("الشمعة ليست صاعدة قوية (جسم ضعيف)")

            avg_vol = float(np.mean(vol[-15:-1])) if len(vol) >= 15 else float(np.mean(vol))
            if vol[-1] < (avg_vol * 1.25):
                return no_trade("حجم التداول (Volume) ضعيف ولا يؤكد الصعود")

            # 3. رصد الفجوة السعرية (FVG) واختبار إعادة الارتداد
            # فجوة شرائية: قاع الشمعة الحالية أو السابقة أعلى من قمة ما قبلها
            fvg_detected = lo[-1] > hi[-3]
            if not fvg_detected:
                return no_trade("لا توجد فجوة سعرية شرائية (FVG) واضحة")

            # 4. تحديد وقف الخسارة والهدف بناءً على إدارة مخاطر صارمة
            stop = float(min(lo[-3:]) - (0.3 * atr))
            risk = self.calculate_position_size(entry, stop, "LONG")
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "Composite SMC + FVG + Trend Confirmation",
                "score": 92,
                "trend_4h": trend_4h,
                "trend_1h": trend_1h,
                "volume_confirmed": True,
                "atr": self._round(atr)
            }
            return "LONG", self._round(entry), details

        except Exception as exc:
            return no_trade(f"خطأ تقني في الخوارزمية: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
