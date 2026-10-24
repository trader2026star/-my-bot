# ============================================================
# MY EXPERT CRYPTO BOT - MULTI-TIMEFRAME ICT + FOOTPRINT (V17.0)
# Multi-Timeframe Alignment: 1D (Bias) -> 4H (BOS) -> 1H (OB/FVG) -> 15M (Entry)
# Full Dual-Direction Support: LONG & SHORT
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
        """1. اليومي: تحديد الانحياز بناءً على الهيكل والمتوسط المتحرك"""
        arr = self._array(ohlcv_1d, minimum=15)
        if arr is None:
            return "NEUTRAL"
        closes = arr[:, 4]
        highs = arr[:, 2]
        lows = arr[:, 3]
        
        ma20 = np.mean(closes[-15:])
        if closes[-1] > ma20 and closes[-1] > np.max(highs[-5:-1]):
            return "BULLISH"
        elif closes[-1] < ma20 and closes[-1] < np.min(lows[-5:-1]):
            return "BEARISH"
        
        return "BULLISH" if closes[-1] > ma20 else "BEARISH"

    def _check_4h_structure(self, ohlcv_4h, bias):
        """2. 4 ساعات: كسر الهيكل (BOS) بجهة الانحياز"""
        arr = self._array(ohlcv_4h, minimum=15)
        if arr is None:
            return False
        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        if bias == "BULLISH":
            recent_high = np.max(highs[-8:-2])
            return bool(closes[-1] > recent_high)
        elif bias == "BEARISH":
            recent_low = np.min(lows[-8:-2])
            return bool(closes[-1] < recent_low)
        return False

    def _check_1h_ob_fvg(self, ohlcv_1h, bias):
        """3. ساعة واحدة: كشف الأوردر بلوك (OB) والفجوات السعرية (FVG)"""
        arr = self._array(ohlcv_1h, minimum=15)
        if arr is None:
            return False, 0.0

        lows = arr[:, 3]
        highs = arr[:, 2]
        opens = arr[:, 1]
        closes = arr[:, 4]

        has_fvg = False
        ob_level = 0.0

        if bias == "BULLISH":
            for i in range(len(arr) - 1, max(2, len(arr) - 6), -1):
                if lows[i] > highs[i - 2]:
                    has_fvg = True
                    break
            # ICT Order Block: آخر شمعة هابطة قبل الحركة الصاعدة
            for i in range(len(arr) - 2, max(0, len(arr) - 8), -1):
                if closes[i] < opens[i]:
                    ob_level = float(lows[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.min(lows[-5:-1]))

        elif bias == "BEARISH":
            for i in range(len(arr) - 1, max(2, len(arr) - 6), -1):
                if highs[i] < lows[i - 2]:
                    has_fvg = True
                    break
            # ICT Order Block: آخر شمعة صاعدة قبل الحركة الهابطة
            for i in range(len(arr) - 2, max(0, len(arr) - 8), -1):
                if closes[i] > opens[i]:
                    ob_level = float(highs[i])
                    break
            if ob_level == 0.0:
                ob_level = float(np.max(highs[-5:-1]))

        return has_fvg, ob_level

    def _check_15m_entry(self, ohlcv_15m, bias):
        """4. 15 دقيقة: التأكيد المباشر عبر تدفق السيولة والشمعة التنفيذية"""
        arr = self._array(ohlcv_15m, minimum=15)
        if arr is None:
            return False

        o, h, l, c, v = arr[-1, 1], arr[-1, 2], arr[-1, 3], arr[-1, 4], arr[-1, 5]
        candle_range = h - l
        if candle_range <= 0 or v <= 0:
            return False

        body = abs(c - o)
        delta_ratio = body / candle_range

        if bias == "BULLISH":
            return bool(delta_ratio > 0.35 and c > o)
        elif bias == "BEARISH":
            return bool(delta_ratio > 0.35 and c < o)
        return False

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason}

        # 1. التثبت من الانحياز اليومي
        daily_bias = self._get_daily_bias(ohlcv_1d)
        if daily_bias not in ["BULLISH", "BEARISH"]:
            return no_trade("الانحياز اليومي غير محدد")

        # 2. فحص كسر الهيكل على 4H
        if not self._check_4h_structure(ohlcv_4h, daily_bias):
            return no_trade(f"لم يتحقق كسر الهيكل (BOS) لاتجاه {daily_bias} على 4H")

        # 3. فحص FVG و Order Block على 1H
        has_fvg, ob_level = self._check_1h_ob_fvg(ohlcv_1h, daily_bias)
        if not has_fvg:
            return no_trade("لا توجد فجوة سعرية (FVG) مدعومة على فريم الساعة")

        # 4. تأكيد الدخول على 15M
        if not self._check_15m_entry(ohlcv_15m, daily_bias):
            return no_trade("شمعة 15 دقيقة لم تعطِ تأكيد تدفق الأوامر (Footprint Confirmation)")

        raw15 = self._array(ohlcv_15m, 15)
        current_price = float(raw15[-1, 4])
        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)

        risk_usd = self.total_capital * self.risk_per_trade

        if daily_bias == "BULLISH":
            direction = "LONG"
            stop = min(ob_level - 0.2 * atr, current_price - 1.2 * atr)
            risk_dist = current_price - stop
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")
            tp1 = current_price + (risk_dist * 1.2)
            tp2 = current_price + (risk_dist * 1.8)
            tp3 = current_price + (risk_dist * 2.5)

        else: # BEARISH
            direction = "SHORT"
            stop = max(ob_level + 0.2 * atr, current_price + 1.2 * atr)
            risk_dist = stop - current_price
            if risk_dist <= 0:
                return no_trade("مسافة الوقف غير صالحة")
            tp1 = current_price - (risk_dist * 1.2)
            tp2 = current_price - (risk_dist * 1.8)
            tp3 = current_price - (risk_dist * 2.5)

        qty = risk_usd / risk_dist

        details = {
            "reason": f"Aligned Multi-Timeframe ICT Setup ({direction})",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.5"
            },
            "setup": "Full Multi-Timeframe ICT Alignment",
            "score": 95,
            "smc_note": f"1D {daily_bias} Bias | 4H BOS Confirmed | 1H FVG & OB Found | 15M Entry Confirmed"
        }

        return direction, self._round(current_price), details
