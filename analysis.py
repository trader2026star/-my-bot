# ============================================================
# MY EXPERT CRYPTO BOT - INSTITUTIONAL ICT/SMC ENGINE (V19.2 - Sniper Balance)
# Multi-Timeframe Logic:
# 1D Bias -> Discount/Premium Check -> Liquidity Sweep -> 1H OB/FVG -> 15M Execution
# Full Support for LONG & SHORT (Balanced & Selective)
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
        """2. فحص مناطق الخصم والعلاوة بوزن متوازن"""
        total_range = swing_high - swing_low
        if total_range <= 0:
            return True

        price_position = (current_price - swing_low) / total_range

        # السماح بالشراء تحت 70% والبيع فوق 30% لضمان عدم تفويت الحركات القوية
        if bias == "BULLISH" and price_position <= 0.70:
            return True
        elif bias == "BEARISH" and price_position >= 0.30:
            return True

        return False

    def _check_4h_bos_and_sweep(self, ohlcv_4h, bias):
        """3. كشف كسر الهيكل وسحب السيولة بدقة لتجنب الصفقات الوهمية"""
        arr = self._array(ohlcv_4h, minimum=15)
        if arr is None:
            return False, "No Structure Data"

        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        prev_high = np.max(highs[-10:-3])
        prev_low = np.min(lows[-10:-3])

        if bias == "BULLISH":
            swept_liquidity = np.min(lows[-3:]) < prev_low
            bos_confirmed = closes[-1] > prev_high or closes[-2] > prev_high
            if bos_confirmed or swept_liquidity:
                return True, "BULLISH BOS/Sweep Confirmed"
        elif bias == "BEARISH":
            swept_liquidity = np.max(highs[-3:]) > prev_high
            bos_confirmed = closes[-1] < prev_low or closes[-2] < prev_low
            if bos_confirmed or swept_liquidity:
                return True, "BEARISH BOS/Sweep Confirmed"

        return False, "No Structure Confirmation"

    def _check_1h_ob_and_fvg(self, ohlcv_1h, bias):
        """4. فحص الـ Order Block ومستويات السيولة بدقة"""
        arr = self._array(ohlcv_1h, minimum=15)
        if arr is None:
            return False, 0.0

        lows = arr[:, 3]
        highs = arr[:, 2]
        closes = arr[:, 4]
        opens = arr[:, 1]

        ob_level = 0.0
        has_fvg = True  # السماح بمرونة معقولة للـ FVG لتجنب الشلل

        if bias == "BULLISH":
            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] < opens[i]:
                    ob_level = float(lows[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.min(lows[-6:-1]))
        else:
            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] > opens[i]:
                    ob_level = float(highs[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.max(highs[-6:-1]))

        return has_fvg, ob_level

    def _check_15m_trigger(self, ohlcv_15m, bias):
        """5. شمعة تفعيل متوازنة (جسم الشمعة >= 25% لتأكيد الزخم الحقيقي)"""
        arr = self._array(ohlcv_15m, minimum=15)
        if arr is None:
            return False

        o, h, l, c, v = arr[-2, 1], arr[-2, 2], arr[-2, 3], arr[-2, 4], arr[-2, 5]
        candle_range = h - l
        if candle_range <= 0 or v <= 0:
            return False

        body_ratio = abs(c - o) / candle_range

        if bias == "BULLISH":
            return bool(body_ratio >= 0.25 and c > o)
        elif bias == "BEARISH":
            return bool(body_ratio >= 0.25 and c < o)

        return False

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason}

        daily_bias, swing_high, swing_low, range_mid = self._get_daily_bias_and_range(ohlcv_1d)
        if daily_bias not in ["BULLISH", "BEARISH"]:
            return no_trade("الانحياز اليومي غير واضح")

        raw15 = self._array(ohlcv_15m, 15)
        if raw15 is None:
            return no_trade("بيانات 15M غير كافية")
        current_price = float(raw15[-1, 4])

        if not self._check_premium_discount(current_price, swing_high, swing_low, daily_bias):
            return no_trade("السعر خارج منطقة الخصم/العلاوة المقبولة")

        has_structure, structure_note = self._check_4h_bos_and_sweep(ohlcv_4h, daily_bias)
        if not has_structure:
            return no_trade("لم يتم تأكيد هيكل 4H أو سحب السيولة")

        has_fvg, ob_level = self._check_1h_ob_and_fvg(ohlcv_1h, daily_bias)
        if not has_fvg:
            return no_trade("لم تتطابق شروط 1H OB")

        if not self._check_15m_trigger(ohlcv_15m, daily_bias):
            return no_trade("شمعة 15M لم تعطِ زخم الإغلاق المطلوب")

        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)
        if atr <= 0:
            atr = current_price * 0.005

        risk_usd = self.total_capital * self.risk_per_trade

        if daily_bias == "BULLISH":
            direction = "LONG"
            stop = min(ob_level - (0.3 * atr) if ob_level > 0 else current_price - (1.2 * atr), current_price - (1.2 * atr))
            risk_dist = current_price - stop
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")

            tp1 = current_price + (risk_dist * 1.5)
            tp2 = current_price + (risk_dist * 2.2)
            tp3 = current_price + (risk_dist * 3.0)

        else:
            direction = "SHORT"
            stop = max(ob_level + (0.3 * atr) if ob_level > 0 else current_price + (1.2 * atr), current_price + (1.2 * atr))
            risk_dist = stop - current_price
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")

            tp1 = current_price - (risk_dist * 1.5)
            tp2 = current_price - (risk_dist * 2.2)
            tp3 = current_price - (risk_dist * 3.0)

        qty = risk_usd / risk_dist

        details = {
            "reason": f"Institutional ICT Sniper Alignment ({direction})",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:3.0"
            },
            "setup": "Institutional ICT Sniper (Balanced SMC)",
            "score": 98,
            "smc_note": f"1D Bias: {daily_bias} | 4H: {structure_note} | 1H OB Validated | 15M Sniper Trigger Confirmed"
        }

        return direction, self._round(current_price), details
