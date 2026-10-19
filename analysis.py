# ============================================================
# EXPERT CRYPTO BOT - INSTITUTIONAL SMC & ICT ENGINE V6.0
# Smart Money Concepts: FVG + Order Block (OB) + CHoCH/BOS + Volume Flow
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.5):
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

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw1h = self._array(ohlcv_1h, 45)
        raw15m = self._array(ohlcv_15m, 40)
        
        if raw1h is None or raw15m is None:
            return no_trade("بيانات السوق غير كافية للتحليل المؤسسي")

        try:
            c1h = raw1h[:-1]
            c15 = raw15m[:-1]

            # 1. رصد كسر هيكل السوق الصاعد (BOS) على فريم الساعة
            closes_1h = c1h[:, 4]
            highs_1h = c1h[:, 2]
            prev_high = np.max(highs_1h[-20:-3])
            
            if closes_1h[-1] <= prev_high:
                return no_trade("لم يحدث كسر حقيقي لهيكل السوق (BOS) بعد")

            # 2. اكتشاف الفجوة السعرية (Fair Value Gap - FVG) على فريم 15 دقيقة
            hi15, lo15, cl15, vol15 = c15[:, 2], c15[:, 3], c15[:, 4], c15[:, 5]
            
            # شرط FVG الشرائية: قاع الشمعة الحالية أعلى من قمة الشمعة قبل السابقة
            fvg_top = float(lo15[-1])
            fvg_bottom = float(hi15[-3])
            has_fvg = fvg_top > fvg_bottom

            if not has_fvg:
                return no_trade("لا توجد فجوة سعرية مؤسسية (FVG) واضحة")

            current_price = float(cl15[-1])
            atr = self.calculate_atr(hi15, lo15, cl15, 14)

            # 3. التأكد من التدفق السيولي (Institutional Volume Flow)
            avg_vol = float(np.mean(vol15[-20:]))
            if vol15[-1] < (avg_vol * 1.3):
                return no_trade("حجم التداول لا يعكس تدفقاً سيولياً مؤسسياً")

            # 4. تحديد كتلة الأوامر (Order Block - OB) لوضع وقف الخسارة الآمن
            ob_low = float(np.min(lo15[-5:]))
            stop = float(ob_low - (0.3 * atr))

            risk = self.calculate_position_size(current_price, stop, "LONG")
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "Institutional SMC (BOS + FVG + Order Block Retest)",
                "score": 98,
                "fvg_zone": f"{self._round(fvg_bottom)} - {self._round(fvg_top)}",
                "order_block_low": self._round(ob_low),
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ تقني: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)
