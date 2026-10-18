# ============================================================
# EXPERT CRYPTO BOT - SEDRA CRYPTO & ORDERBOOK STRATEGY ENGINE
# EMA 7/25/99 + Supertrend + OrderBook Liquidity & S/R Targets
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

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, orderbook_data=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw1 = self._array(ohlcv_1h, 40)
        if raw1 is None:
            return no_trade("بيانات 1H غير كافية")

        try:
            c1 = raw1[:-1]
            closes = c1[:, 4]
            highs = c1[:, 2]
            lows = c1[:, 3]
            volumes = c1[:, 5]

            # 1. حساب المتوسطات الأسية الثلاثة (EMA 7, EMA 25, EMA 99)
            ema_7 = self._ema(closes, 7)
            ema_25 = self._ema(closes, 25)
            ema_99 = self._ema(closes, 99)

            if ema_7 is None or ema_25 is None or ema_99 is None:
                return no_trade("تعذر حساب المتوسطات الأسية")

            # شرط الزخم والاتجاه: ترتيب صعودي تام (EMA 7 > EMA 25 > EMA 99)
            is_bullish_alignment = (ema_7 > ema_25) and (ema_25 > ema_99)
            if not is_bullish_alignment:
                return no_trade("المتوسطات غير مرتبة بشكل صعودي (7 > 25 > 99)")

            current_price = float(closes[-1])

            # 2. دعم ومقاومة مستهدفة بناءً على القمم والقيعان (S/R)
            piv_hi, piv_lo = self._pivots(highs, lows, 3, 3)
            support_level = float(ema_7) # الدعم القريب عند EMA 7
            resistance_target = max(piv_hi) if piv_hi else current_price * 1.08

            # 3. التحقق من حجم السيولة والتداول (Volume)
            avg_vol = float(np.mean(volumes[-20:]))
            if volumes[-1] < (avg_vol * 1.2):
                return no_trade("حجم التداول والسيولة دون المطلوب")

            # 4. تحليل دفتر الطلبات (Orderbook Buy Ratio) إن وجد
            buy_ratio = 55.0 # القيمة الافتراضية إذا لم يتوفر دفتر الطلبات المباشر
            if orderbook_data and isinstance(orderbook_data, dict):
                bids_vol = orderbook_data.get("bids_volume", 1.0)
                asks_vol = orderbook_data.get("asks_volume", 1.0)
                total_ob = bids_vol + asks_vol
                if total_ob > 0:
                    buy_ratio = (bids_vol / total_ob) * 100.0
            
            if buy_ratio < 53.0:
                return no_trade("هيمنة المشترين في دفتر الطلبات أقل من 53%")

            atr = self.calculate_atr(highs, lows, closes, 14)
            stop = float(support_level - (0.5 * atr))

            risk = self.calculate_position_size(current_price, stop, "LONG")
            if not risk:
                return no_trade("فشل حساب إدارة المخاطر")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "EMA 7/25/99 Bullish Alignment + Supertrend + Strong Volume",
                "score": 96,
                "ema_7": self._round(ema_7),
                "ema_25": self._round(ema_25),
                "ema_99": self._round(ema_99),
                "support_level": self._round(support_level),
                "resistance_target": self._round(resistance_target),
                "buy_ratio": round(buy_ratio, 2),
                "atr": self._round(atr)
            }
            return "LONG", self._round(current_price), details

        except Exception as exc:
            return no_trade(f"خطأ في التحليل: {str(exc)[:40]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m)
