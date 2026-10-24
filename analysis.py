# ============================================================
# MY EXPERT CRYPTO BOT - STRICT ICT / SMC ENGINE (V18.0)
# Multi-Timeframe Institutional Flow: 1D (Bias) -> 4H (BOS) -> 1H (OB/FVG) -> 15M (Confirmation)
# Direct Support for LONG & SHORT
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

    def _get_daily_bias(self, ohlcv_1d):
        """1. تحديد انحياز الفريم اليومي بناءً على القمم والقيعان الرئيسية (Market Structure)"""
        arr = self._array(ohlcv_1d, minimum=12)
        if arr is None:
            return "NEUTRAL"
        
        closes = arr[:, 4]
        highs = arr[:, 2]
        lows = arr[:, 3]

        swing_high = np.max(highs[-10:-2])
        swing_low = np.min(lows[-10:-2])

        if closes[-1] > swing_high:
            return "BULLISH"
        elif closes[-1] < swing_low:
            return "BEARISH"
        
        # في حال التذبذب داخل النطاق، نعتمد اتجاه الشموع الأخير
        return "BULLISH" if closes[-1] >= closes[-5] else "BEARISH"

    def _check_4h_bos(self, ohlcv_4h, bias):
        """2. تأكيد كسر الهيكل (BOS) على فريم 4 ساعات بجهة الانحياز اليومي"""
        arr = self._array(ohlcv_4h, minimum=15)
        if arr is None:
            return False

        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        if bias == "BULLISH":
            prev_structure_high = np.max(highs[-12:-3])
            return bool(closes[-1] > prev_structure_high or closes[-2] > prev_structure_high)
        elif bias == "BEARISH":
            prev_structure_low = np.min(lows[-12:-3])
            return bool(closes[-1] < prev_structure_low or closes[-2] < prev_structure_low)

        return False

    def _check_1h_ob_and_fvg(self, ohlcv_1h, bias):
        """3. كشف الفجوة السعرية (FVG) غير المغلقة والـ Order Block الحقيقي على 1H"""
        arr = self._array(ohlcv_1h, minimum=15)
        if arr is None:
            return False, 0.0

        opens = arr[:, 1]
        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        has_fvg = False
        ob_level = 0.0

        if bias == "BULLISH":
            # كشف FVG صاعدة (Low الشمعة الحالي أعلى من High الشمعة قبل السابقة)
            for i in range(len(arr) - 1, max(2, len(arr) - 8), -1):
                if lows[i] > highs[i - 2]:
                    has_fvg = True
                    break

            # تحديد الـ Order Block (آخر شمعة هابطة قبل الانطلاق الصاعد)
            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] < opens[i]:
                    ob_level = float(lows[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.min(lows[-6:-1]))

        elif bias == "BEARISH":
            # كشف FVG هابطة (High الشمعة الحالي أقل من Low الشمعة قبل السابقة)
            for i in range(len(arr) - 1, max(2, len(arr) - 8), -1):
                if highs[i] < lows[i - 2]:
                    has_fvg = True
                    break

            # تحديد الـ Order Block (آخر شمعة صاعدة قبل الانهيار الهابط)
            for i in range(len(arr) - 2, max(0, len(arr) - 10), -1):
                if closes[i] > opens[i]:
                    ob_level = float(highs[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.max(highs[-6:-1]))

        return has_fvg, ob_level

    def _check_15m_trigger(self, ohlcv_15m, bias):
        """4. التأكيد والتفعيل المباشر على فريم 15 دقيقة (تدفق السيولة والشمعة التنفيذية)"""
        arr = self._array(ohlcv_15m, minimum=15)
        if arr is None:
            return False

        o, h, l, c, v = arr[-1, 1], arr[-1, 2], arr[-1, 3], arr[-1, 4], arr[-1, 5]
        candle_range = h - l
        if candle_range <= 0 or v <= 0:
            return False

        body = abs(c - o)
        body_ratio = body / candle_range

        # نطلب زَخماً حقيقياً وشمعة واضحة الاتجاه (لا تقل عن 35% من المدى)
        if bias == "BULLISH":
            return bool(body_ratio >= 0.35 and c > o)
        elif bias == "BEARISH":
            return bool(body_ratio >= 0.35 and c < o)

        return False

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason}

        # 1. الانحياز اليومي
        daily_bias = self._get_daily_bias(ohlcv_1d)
        if daily_bias not in ["BULLISH", "BEARISH"]:
            return no_trade("الانحياز اليومي (1D) غير محدد")

        # 2. كسر الهيكل على 4H
        if not self._check_4h_bos(ohlcv_4h, daily_bias):
            return no_trade(f"لم يتحقق كسر الهيكل (BOS) بجهة {daily_bias} على 4H")

        # 3. الـ OB والـ FVG على 1H
        has_fvg, ob_level = self._check_1h_ob_and_fvg(ohlcv_1h, daily_bias)
        if not has_fvg:
            return no_trade("لا توجد فجوة سعرية (FVG) نِشطة على 1H")

        # 4. شمعة التفعيل على 15M
        if not self._check_15m_trigger(ohlcv_15m, daily_bias):
            return no_trade("شمعة 15M لم تعطِ إشارة تدفق سيولة مؤكدة")

        raw15 = self._array(ohlcv_15m, 15)
        current_price = float(raw15[-1, 4])
        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)
        if atr <= 0:
            atr = current_price * 0.005 # حماية في حال عدم توفر ATR

        risk_usd = self.total_capital * self.risk_per_trade

        if daily_bias == "BULLISH":
            direction = "LONG"
            stop = min(ob_level - (0.3 * atr), current_price - (1.2 * atr))
            risk_dist = current_price - stop
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة للشرائي")

            tp1 = current_price + (risk_dist * 1.2)
            tp2 = current_price + (risk_dist * 1.8)
            tp3 = current_price + (risk_dist * 2.5)

        else: # BEARISH
            direction = "SHORT"
            stop = max(ob_level + (0.3 * atr), current_price + (1.2 * atr))
            risk_dist = stop - current_price
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة للبيعي")

            tp1 = current_price - (risk_dist * 1.2)
            tp2 = current_price - (risk_dist * 1.8)
            tp3 = current_price - (risk_dist * 2.5)

        qty = risk_usd / risk_dist

        details = {
            "reason": f"Institutional Multi-Timeframe Alignment ({direction})",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.5"
            },
            "setup": "Strict ICT/SMC Alignment",
            "score": 98,
            "smc_note": f"1D Bias: {daily_bias} | 4H BOS Confirmed | 1H OB & FVG Active | 15M Trigger Validated"
        }

        return direction, self._round(current_price), details
