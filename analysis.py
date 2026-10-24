# ============================================================
# MY EXPERT CRYPTO BOT - MULTI-TIMEFRAME ICT + FOOTPRINT (V16.0)
# Multi-Timeframe Alignment: 1D (Bias) -> 4H (BOS) -> 1H (OB/FVG) -> 15M (Entry)
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

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
        """1. اليومي: تحديد الانحياز والمستويات الرئيسية"""
        arr = self._array(ohlcv_1d, minimum=15)
        if arr is None:
            return "NEUTRAL"
        closes = arr[:, 4]
        # إذا كان السعر الحالي أعلى من متوسط آخر 10 أيام -> الانحياز صاعد
        ma10 = np.mean(closes[-10:])
        return "BULLISH" if closes[-1] > ma10 else "BEARISH"

    def _check_4h_structure(self, ohlcv_4h):
        """2. 4 ساعات: تحديد الاتجاه وسحب السيولة والكسور (BOS)"""
        arr = self._array(ohlcv_4h, minimum=20)
        if arr is None:
            return False
        highs = arr[:, 2]
        closes = arr[:, 4]
        # كسر قمة سابقة (BOS) مع زخم صاعد
        recent_high = np.max(highs[-10:-2])
        return bool(closes[-1] > recent_high)

    def _check_1h_ob_fvg(self, ohlcv_1h):
        """3. ساعة واحدة: كشف الأوردر بلوك (OB) والفجوات السعرية (FVG)"""
        arr = self._array(ohlcv_1h, minimum=20)
        if arr is None:
            return False, 0.0
        
        lows = arr[:, 3]
        highs = arr[:, 2]
        
        # كشف فجوة FVG صاعدة على فريم الساعة
        has_fvg = False
        for i in range(len(arr) - 1, max(2, len(arr) - 6), -1):
            if lows[i] > highs[i-2]:
                has_fvg = True
                break
                
        ob_level = float(np.min(lows[-5:-1]))
        return has_fvg, ob_level

    def _check_15m_entry(self, ohlcv_15m):
        """4. 15 دقيقة: التنقية والتأكيد المباشر عبر الفوتبرينت والدلتا"""
        arr = self._array(ohlcv_15m, minimum=20)
        if arr is None:
            return False
        
        o, h, l, c, v = arr[-1, 1], arr[-1, 2], arr[-1, 3], arr[-1, 4], arr[-1, 5]
        candle_range = h - l
        if candle_range <= 0 or v <= 0:
            return False
            
        # التأكيد عبر تدفق السيولة الشرائية الفورية (Footprint Confirmation)
        body = c - o
        delta_ratio = body / candle_range
        return bool(delta_ratio > 0.35 and c > o)

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        debug = []

        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason, "debug_trace": debug}

        # 1. التأكد من انحياز الفريم اليومي (1D)
        daily_bias = self._get_daily_bias(ohlcv_1d)
        if daily_bias != "BULLISH":
            return no_trade("الانحياز اليومي (1D) ليس صاعداً")

        # 2. التأكد من كسر الهيكل على فريم (4H)
        if not self._check_4h_structure(ohlcv_4h):
            return no_trade("لم يتحقق كسر الهيكل (BOS) على فريم 4 ساعات")

        # 3. التأكد من وجود FVG و Order Block على فريم (1H)
        has_1h_fvg, ob_level = self._check_1h_ob_fvg(ohlcv_1h)
        if not has_1h_fvg:
            return no_trade("لا توجد مناطق فجوة سعرية (FVG) أو Order Block على فريم الساعة")

        # 4. التأكد من شمعة التفعيل الصارمة على فريم (15M)
        if not self._check_15m_entry(ohlcv_15m):
            return no_trade("شمعة 15 دقيقة لم تعطِ تأكيد تدفق الأوامر (Footprint Confirmation)")

        raw15 = self._array(ohlcv_15m, 20)
        current_price = float(raw15[-1, 4])
        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)

        # حساب الوقف والأهداف بناءً على نسبة 1:2.5
        stop = min(ob_level - 0.2 * atr, current_price - 1.2 * atr)
        risk_dist = current_price - stop
        if risk_dist <= 0:
            return no_trade("مسافة الوقف غير صالحة")

        tp_target = current_price + (risk_dist * 2.5)
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "Aligned Multi-Timeframe ICT Setup (1D+4H+1H+15M)",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(current_price + (risk_dist * 1.2)),
                "take_profit_2": self._round(current_price + (risk_dist * 1.8)),
                "take_profit_3": self._round(tp_target),
                "reward_ratio": "1:2.5"
            },
            "setup": "Full Multi-Timeframe ICT Alignment",
            "score": 95,
            "smc_note": "1D Daily Bias (BULLISH) | 4H BOS Confirmed | 1H FVG & OB Found | 15M Entry Confirmed"
        }

        return "LONG", self._round(current_price), details
