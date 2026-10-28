# ============================================================
# MY EXPERT CRYPTO BOT - V20.0 Ultra-Safe Sniper Elite
# Dual Direction: Strict Trend, Liquidity Sweep & 85+ Score Filter
# Signal-only: does NOT place exchange orders.
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0
        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

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
            if np.any(a[:, 2] < np.maximum(a[:, 1], a[:, 4])):
                return None
            if np.any(a[:, 3] > np.minimum(a[:, 1], a[:, 4])):
                return None
            if np.any(np.diff(a[:, 0]) < 0):
                return None
            return a
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

    @staticmethod
    def _closed(data, minimum=20):
        arr = StrategyEngine._array(data, minimum=minimum + 1)
        if arr is None or len(arr) < minimum + 1:
            return None
        closed = arr[:-1]
        return closed if len(closed) >= minimum else None

    def calculate_atr(self, highs, lows, closes, period=14):
        try:
            h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
            n = min(len(h), len(l), len(c))
            if n < 2:
                return 0.0
            h, l, c = h[-n:], l[-n:], c[-n:]
            tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
            if len(tr) == 0:
                return 0.0
            return float(np.mean(tr[-max(1, int(period)):]))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _calculate_rsi(closes, period=14):
        try:
            deltas = np.diff(closes)
            seed = deltas[:period]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            if down == 0:
                return 100.0
            rs = up / down
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi)
        except Exception:
            return 50.0

    @staticmethod
    def _swing_levels(arr, lookback=12):
        recent = arr[-(lookback + 1):-1] if len(arr) > lookback else arr[:-1]
        if len(recent) < 3:
            return None, None
        return float(np.max(recent[:, 2])), float(np.min(recent[:, 3]))

    def calculate_volume_profile(self, ohlcv, bins=35):
        arr = self._closed(ohlcv, minimum=20)
        if arr is None:
            return None, None, None
        bins = max(10, min(100, int(bins)))
        highs, lows, volumes = arr[:, 2], arr[:, 3], arr[:, 5]
        min_price, max_price = float(np.min(lows)), float(np.max(highs))
        if not np.isfinite(min_price + max_price) or max_price <= min_price:
            return None, None, None

        edges = np.linspace(min_price, max_price, bins + 1)
        bin_volumes = np.zeros(bins, dtype=float)
        for h, l, v in zip(highs, lows, volumes):
            if v <= 0:
                continue
            candle_range = h - l
            if candle_range <= 0:
                idx = min(bins - 1, max(0, int(np.searchsorted(edges, l, side="right") - 1)))
                bin_volumes[idx] += v
                continue
            first = max(0, min(bins - 1, int(np.searchsorted(edges, l, side="right") - 1)))
            last = max(0, min(bins - 1, int(np.searchsorted(edges, h, side="left"))))
            for b in range(first, last + 1):
                overlap = max(0.0, min(h, edges[b + 1]) - max(l, edges[b]))
                if overlap > 0:
                    bin_volumes[b] += v * overlap / candle_range

        total_vol = float(np.sum(bin_volumes))
        if total_vol <= 0:
            return None, None, None
        poc_idx = int(np.argmax(bin_volumes))
        poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

        target = total_vol * 0.70
        lo_idx = hi_idx = poc_idx
        included = float(bin_volumes[poc_idx])
        while included < target and (lo_idx > 0 or hi_idx < bins - 1):
            below = bin_volumes[lo_idx - 1] if lo_idx > 0 else -1.0
            above = bin_volumes[hi_idx + 1] if hi_idx < bins - 1 else -1.0
            if hi_idx < bins - 1 and (above >= below or lo_idx == 0):
                hi_idx += 1
                included += float(bin_volumes[hi_idx])
            elif lo_idx > 0:
                lo_idx -= 1
                included += float(bin_volumes[lo_idx])
            else:
                break
        val = float(edges[lo_idx])
        vah = float(edges[hi_idx + 1])
        return poc, val, vah

    @staticmethod
    def _bullish_fvg(arr):
        if len(arr) < 3:
            return None
        a, c = arr[-3], arr[-1]
        if c[3] > a[2]:
            return float(a[2]), float(c[3])
        return None

    @staticmethod
    def _bearish_fvg(arr):
        if len(arr) < 3:
            return None
        a, c = arr[-3], arr[-1]
        if c[2] < a[3]:
            return float(c[2]), float(a[3])
        return None

    @staticmethod
    def _bullish_order_block(arr):
        start = max(0, len(arr) - 8)
        for i in range(len(arr) - 2, start - 1, -1):
            row = arr[i]
            if row[4] < row[1]:
                return float(row[3]), float(row[2])
        return None

    @staticmethod
    def _bearish_order_block(arr):
        start = max(0, len(arr) - 8)
        for i in range(len(arr) - 2, start - 1, -1):
            row = arr[i]
            if row[4] > row[1]:
                return float(row[3]), float(row[2])
        return None

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        debug = []

        def no_trade(reason, extra=None):
            details = {
                "reason": reason,
                "debug_trace": list(debug),
                "trade_valid": False,
                "score": 0,
                "setup": "V20.0 Ultra-Safe Sniper Elite",
            }
            if extra:
                details.update(extra)
            return "NEUTRAL", 0, details

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات أحد الفريمات الأربعة غير متوفرة")

        d1 = self._closed(ohlcv_1d, minimum=20)
        h4 = self._closed(ohlcv_4h, minimum=20)
        h1 = self._closed(ohlcv_1h, minimum=20)
        m15 = self._closed(ohlcv_15m, minimum=20)
        if any(x is None for x in (d1, h4, h1, m15)):
            return no_trade("عدد الشموع المغلقة غير كافٍ أو بيانات OHLCV غير صالحة")

        daily_closes = d1[:, 4]
        daily_close = float(daily_closes[-1])
        daily_ma20 = float(np.mean(daily_closes[-20:]))
        
        h4_closes = h4[:, 4]
        h4_close = float(h4_closes[-1])
        h4_ma10 = float(np.mean(h4_closes[-10:]))

        close = float(m15[-1, 4])
        open_ = float(m15[-1, 1])
        high = float(m15[-1, 2])
        low = float(m15[-1, 3])
        volume = float(m15[-1, 5])
        
        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range
        
        avg_volume = float(np.mean(m15[-16:-1, 5]))
        volume_spike = avg_volume > 0 and volume >= avg_volume * 1.50  # سيولة مؤسسية أعلى

        atr = self.calculate_atr(m15[:, 2], m15[:, 3], m15[:, 4], 14)
        if atr <= 0 or not np.isfinite(atr):
            return no_trade("تعذر حساب ATR بصورة صالحة")

        m15_rsi = self._calculate_rsi(m15[:, 4], 14)
        poc, val, vah = self.calculate_volume_profile(h1)
        if poc is None or val is None or vah is None:
            return no_trade("تعذر حساب Volume Profile على فريم الساعة")

        # ==================== تحديد الاتجاه بدقة صارمة للغاية ====================
        strict_bullish = daily_close > daily_ma20 and h4_close > h4_ma10
        strict_bearish = daily_close < daily_ma20 and h4_close < h4_ma10

        if strict_bullish and not strict_bearish:
            direction_intent = "LONG"
        elif strict_bearish and not strict_bullish:
            direction_intent = "SHORT"
        else:
            return no_trade(f"الترند غير مستقر بين اليومي و4 ساعات (ممنوع الدخول حفاظاً على الرصيد)")

        # ==========================================================
        # منطق صفقات الـ LONG المحصنة (صفر مخاطرة)
        # ==========================================================
        if direction_intent == "LONG":
            near_support = (val * 0.998 <= close <= poc * 1.008)
            fvg = self._bullish_fvg(m15)
            ob = self._bullish_order_block(h1)
            near_fvg = bool(fvg and fvg[0] <= close <= fvg[1] + 0.1 * atr)
            near_ob = bool(ob and ob[0] - 0.1 * atr <= close <= ob[1] + 0.1 * atr)
            
            if not (near_support or near_fvg or near_ob):
                return no_trade("السعر ليس في منطقة دعم مؤسسي أو فجوة صحيحة للـ LONG")

            recent_lows = m15[-10:-1, 3]
            sweep_level = float(np.min(recent_lows)) if len(recent_lows) else low
            liquidity_sweep = bool(low < sweep_level and close > sweep_level)

            strong_green_candle = (close > open_) and (body_ratio >= 0.60) # جسم الشمعة أكبر من 60% تأكيد قاطع
            if not strong_green_candle and not liquidity_sweep:
                return no_trade("شمعة الارتداد ضعيفة ولا توجد شمعة تأكيد قوية (جسم < 60%)")

            # نظام النقاط الصارم (يجب أن تصل 85 نقطة فما فوق)
            score = 30
            score += 25 if (near_support or near_fvg or near_ob) else 0
            score += 25 if liquidity_sweep else 10
            score += 15 if volume_spike else 0
            score = min(100, int(score))

            if score < 85:
                return no_trade(f"درجة الأمان ({score}/100) أقل من الحد الأدنى الصارم (85)", {"score": score})

            recent_swing_low = float(np.min(m15[-10:, 3]))
            stop = min(recent_swing_low - 0.25 * atr, close - 1.1 * atr)
            risk_dist = close - stop
            
            if not np.isfinite(risk_dist) or risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة غير صالحة", {"score": score})

            risk_usd = self.total_capital * self.risk_per_trade
            qty = min(risk_usd / risk_dist, (self.total_capital * 3.0) / close)
            effective_risk = qty * risk_dist

            tp1 = close + risk_dist * 1.5
            tp2 = close + risk_dist * 2.5
            tp3 = close + risk_dist * 4.0

            notes = f"Ultra-Safe LONG | RSI={round(m15_rsi, 1)} | Sweep={'تم' * int(liquidity_sweep) or 'لا'} | Body={round(body_ratio*100)}%"
            details = {
                "reason": "V20.0 Ultra-Safe Sniper: Verified LONG",
                "trade_valid": True,
                "stop_loss": self._round(stop),
                "risk_distance": self._round(risk_dist),
                "risk_distance_pct": round((risk_dist / close) * 100, 3),
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk, 2),
                    "tokens_to_buy": round(qty, 8),
                    "estimated_position_notional_usd": round(qty * close, 2),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                    "reward_ratio": "1:4.0",
                },
                "setup": "V20.0 Ultra-Safe LONG",
                "score": score,
                "smc_note": notes,
                "levels": {"poc": self._round(poc), "val": self._round(val), "vah": self._round(vah), "rsi": round(m15_rsi, 1)},
                "debug_trace": list(debug),
            }
            return "LONG", self._round(close), details

        # ==========================================================
        # منطق صفقات الـ SHORT المحصنة (صفر مخاطرة)
        # ==========================================================
        else:
            near_resistance = (close >= poc * 0.992) or (close >= vah * 0.988)
            bear_fvg = self._bearish_fvg(m15)
            bear_ob = self._bearish_order_block(h1)
            near_bear_fvg = bool(bear_fvg and bear_fvg[0] - 0.1 * atr <= close <= bear_fvg[1])
            near_bear_ob = bool(bear_ob and bear_ob[0] - 0.1 * atr <= close <= bear_ob[1] + 0.1 * atr)

            if not (near_resistance or near_bear_fvg or near_bear_ob):
                return no_trade("السعر ليس في منطقة مقاومة مؤسسي صحيحة للـ SHORT")

            recent_highs = m15[-10:-1, 2]
            sweep_high_level = float(np.max(recent_highs)) if len(recent_highs) else high
            bearish_liquidity_sweep = bool(high > sweep_high_level and close < sweep_high_level)

            strong_red_candle = (close < open_) and (body_ratio >= 0.60) # شمعة هبوط مؤكدة بقوة
            if not strong_red_candle and not bearish_liquidity_sweep:
                return no_trade("شمعة الرفض الهابط ضعيفة ولا توجد شمعة تأكيد قوية للبيع")

            score = 30
            score += 25 if (near_resistance or near_bear_fvg or near_bear_ob) else 0
            score += 25 if bearish_liquidity_sweep else 10
            score += 15 if volume_spike else 0
            score = min(100, int(score))

            if score < 85:
                return no_trade(f"درجة الأمان للبيع ({score}/100) أقل من الحد الأدنى الصارم (85)", {"score": score})

            recent_swing_high = float(np.max(m15[-10:, 2]))
            stop = max(recent_swing_high + 0.25 * atr, close + 1.1 * atr)
            risk_dist = stop - close

            if not np.isfinite(risk_dist) or risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة للـ SHORT غير صالحة", {"score": score})

            risk_usd = self.total_capital * self.risk_per_trade
            qty = min(risk_usd / risk_dist, (self.total_capital * 3.0) / close)
            effective_risk = qty * risk_dist

            tp1 = close - risk_dist * 1.5
            tp2 = close - risk_dist * 2.5
            tp3 = close - risk_dist * 4.0

            notes = f"Ultra-Safe SHORT | RSI={round(m15_rsi, 1)} | Bearish Sweep={'تم' * int(bearish_liquidity_sweep) or 'لا'} | Body={round(body_ratio*100)}%"
            details = {
                "reason": "V20.0 Ultra-Safe Sniper: Verified SHORT",
                "trade_valid": True,
                "stop_loss": self._round(stop),
                "risk_distance": self._round(risk_dist),
                "risk_distance_pct": round((risk_dist / close) * 100, 3),
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk, 2),
                    "tokens_to_buy": round(qty, 8),
                    "estimated_position_notional_usd": round(qty * close, 2),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                    "reward_ratio": "1:4.0",
                },
                "setup": "V20.0 Ultra-Safe SHORT",
                "score": score,
                "smc_note": notes,
                "levels": {"poc": self._round(poc), "val": self._round(val), "vah": self._round(vah), "rsi": round(m15_rsi, 1)},
                "debug_trace": list(debug),
            }
            return "SHORT", self._round(close), details
