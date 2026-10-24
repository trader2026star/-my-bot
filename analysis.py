# ============================================================
# MY EXPERT CRYPTO BOT - INSTITUTIONAL ICT/SMC ENGINE (V19.0)
# Multi-Timeframe Logic:
# 1D Bias -> Discount/Premium Check -> Liquidity Sweep -> 1H OB/FVG -> 15M Execution
# Full Support for LONG & SHORT
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.05)

    @staticmethod
    def _array(data, minimum=15):
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
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-period:])) if len(tr) > 0 else 0.0

    def _get_daily_bias_and_range(self, ohlcv_1d):
        """1. تحديد الانحياز اليومي + نطاق التداول (Dealing Range)"""
        arr = self._array(ohlcv_1d, minimum=12)
        if arr is None:
            return "NEUTRAL", 0.0, 0.0, 0.0

        closes = arr[:, 4]
        highs = arr[:, 2]
        lows = arr[:, 3]

        swing_high = np.max(highs[-12:-1])
        swing_low = np.min(lows[-12:-1])
        range_mid = (swing_high + swing_low) / 2.0

        bias = "NEUTRAL"
        if closes[-1] > swing_high:
            bias = "BULLISH"
        elif closes[-1] < swing_low:
            bias = "BEARISH"
        else:
            bias = "BULLISH" if closes[-1] >= range_mid else "BEARISH"

        return bias, swing_high, swing_low, range_mid

    def _check_premium_discount(self, current_price, swing_high, swing_low, bias):
        """2. فحص مناطق الخصم والعلاوة (Discount & Premium Zone Filter)"""
        total_range = swing_high - swing_low
        if total_range <= 0:
            return False

        # تحديد النسبة المئوية للسعر داخل النطاق (0 = أدنى قاع، 1 = أعلى قمة)
        price_position = (current_price - swing_low) / total_range

        # في صفقات الشراء: نشتري فقط من منطقة الخصم (Discount < 0.50)
        if bias == "BULLISH" and price_position <= 0.50:
            return True
        # في صفقات البيع: نبيع فقط من منطقة العلاوة (Premium > 0.50)
        elif bias == "BEARISH" and price_position >= 0.50:
            return True

        return False

    def _check_4h_bos_and_sweep(self, ohlcv_4h, bias):
        """3. كشف كسر الهيكل (BOS/CHoCH) مع التأكد من سحب السيولة (Liquidity Sweep)"""
        arr = self._array(ohlcv_4h, minimum=15)
        if arr is None:
            return False, "No Structure"

        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        if bias == "BULLISH":
            prev_high = np.max(highs[-10:-3])
            prev_low = np.min(lows[-10:-3])
            
            # سحب سيولة للقاع السابق ثم الإغلاق أعلاه (Sweep) أو كسر قمة سابقة (BOS/CHoCH)
            swept_liquidity = np.min(lows[-3:]) < prev_low
            bos_confirmed = closes[-1] > prev_high or closes[-2] > prev_high

            if bos_confirmed or swept_liquidity:
                note = "CHoCH/BOS + Liquidity Sweep" if swept_liquidity else "BOS Confirmed"
                return True, note

        elif bias == "BEARISH":
            prev_high = np.max(highs[-10:-3])
            prev_low = np.min(lows[-10:-3])

            swept_liquidity = np.max(highs[-3:]) > prev_high
            bos_confirmed = closes[-1] < prev_low or closes[-2] < prev_low

            if bos_confirmed or swept_liquidity:
                note = "CHoCH/BOS + Liquidity Sweep" if swept_liquidity else "BOS Confirmed"
                return True, note

        return False, "No Sweep/BOS"

    def _check_1h_ob_and_fvg(self, ohlcv_1h, bias):
        """4. كشف FVG غير مغلقة (Unmitigated) و Order Block حقيقي"""
        arr = self._array(ohlcv_1h, minimum=15)
        if arr is None:
            return False, 0.0

        opens, highs, lows, closes = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
        has_fvg = False
        ob_level = 0.0

        if bias == "BULLISH":
            for i in range(len(arr) - 2, max(2, len(arr) - 8), -1):
                if lows[i] > highs[i - 2]:
                    mitigated = any(lows[k] < highs[i - 2] for k in range(i + 1, len(arr)))
                    if not mitigated:
                        has_fvg = True
                        break

            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] < opens[i]:
                    ob_level = float(lows[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.min(lows[-6:-1]))

        elif bias == "BEARISH":
            for i in range(len(arr) - 2, max(2, len(arr) - 8), -1):
                if highs[i] < lows[i - 2]:
                    mitigated = any(highs[k] > lows[i - 2] for k in range(i + 1, len(arr)))
                    if not mitigated:
                        has_fvg = True
                        break

            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] > opens[i]:
                    ob_level = float(highs[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.max(highs[-6:-1]))

        return has_fvg, ob_level

    def _check_15m_trigger(self, ohlcv_15m, bias):
        """5. التفعيل على الشمعة المغلقة (arr[-2]) لتأكيد تدفق السيولة"""
        arr = self._array(ohlcv_15m, minimum=15)
        if arr is None:
            return False

        o, h, l, c, v = arr[-2, 1], arr[-2, 2], arr[-2, 3], arr[-2, 4], arr[-2, 5]
        candle_range = h - l
        if candle_range <= 0 or v <= 0:
            return False

        body_ratio = abs(c - o) / candle_range

        if bias == "BULLISH":
            return bool(body_ratio >= 0.35 and c > o)
        elif bias == "BEARISH":
            return bool(body_ratio >= 0.35 and c < o)

        return False

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason}

        # 1. الانحياز اليومي والنطاق
        daily_bias, swing_high, swing_low, range_mid = self._get_daily_bias_and_range(ohlcv_1d)
        if daily_bias not in ["BULLISH", "BEARISH"]:
            return no_trade("الانحياز اليومي غير واضح")

        raw15 = self._array(ohlcv_15m, 15)
        if raw15 is None:
            return no_trade("بيانات 15M غير كافية")
        current_price = float(raw15[-1, 4])

        # 2. فلتر منطقة الخصم والعلاوة (Discount / Premium Check)
        if not self._check_premium_discount(current_price, swing_high, swing_low, daily_bias):
            zone_type = "Discount" if daily_bias == "BULLISH" else "Premium"
            return no_trade(f"السعر ليس في منطقة الـ {zone_type} المناسبة للدخول")

        # 3. كسر الهيكل وسحب السيولة على 4H
        has_structure, structure_note = self._check_4h_bos_and_sweep(ohlcv_4h, daily_bias)
        if not has_structure:
            return no_trade("لم يتم كسر الهيكل أو سحب السيولة على 4H")

        # 4. الـ OB والـ FVG غير المغلقة على 1H
        has_fvg, ob_level = self._check_1h_ob_and_fvg(ohlcv_1h, daily_bias)
        if not has_fvg:
            return no_trade("لا توجد فجوة سعرية (FVG) نشطة وغير مغلقة على 1H")

        # 5. شمعة التفعيل المغلقة على 15M
        if not self._check_15m_trigger(ohlcv_15m, daily_bias):
            return no_trade("شمعة 15M المغلقة لم تعطِ إشارة تدفق سيولة مؤكدة")

        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)
        if atr <= 0:
            atr = current_price * 0.005

        risk_usd = self.total_capital * self.risk_per_trade

        if daily_bias == "BULLISH":
            direction = "LONG"
            stop = min(ob_level - (0.3 * atr), current_price - (1.2 * atr))
            risk_dist = current_price - stop
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")

            tp1 = current_price + (risk_dist * 1.2)
            tp2 = current_price + (risk_dist * 1.8)
            tp3 = current_price + (risk_dist * 2.5)

        else: # BEARISH
            direction = "SHORT"
            stop = max(ob_level + (0.3 * atr), current_price + (1.2 * atr))
            risk_dist = stop - current_price
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")

            tp1 = current_price - (risk_dist * 1.2)
            tp2 = current_price - (risk_dist * 1.8)
            tp3 = current_price - (risk_dist * 2.5)

        qty = risk_usd / risk_dist

        zone_name = "Discount Zone (خصم)" if daily_bias == "BULLISH" else "Premium Zone (علاوة)"

        details = {
            "reason": f"Institutional ICT Alignment ({direction})",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.5"
            },
            "setup": "Institutional ICT Alignment (Discount/Premium + Sweep)",
            "score": 99,
            "smc_note": f"1D Bias: {daily_bias} ({zone_name}) | 4H: {structure_note} | 1H OB & Unmitigated FVG | 15M Trigger Validated"
        }

        return direction, self._round(current_price), details
