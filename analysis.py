# ============================================================
# MY EXPERT CRYPTO BOT - Bi-Directional Strict SMC Engine (v43.0)
# Long & Short Setups based on 1H Trend, 5M Liquidity Sweep, FVG/OB, and RSI Divergence.
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("StrictBiDirectionalEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, **kwargs):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0

        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

    @staticmethod
    def _array(ohlcv, minimum=20):
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            return a[:, :6]
        except Exception:
            return None

    @staticmethod
    def _round(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-math.floor(math.log10(abs(value)))) + 3))
        return round(value, decimals)

    def calculate_rsi(self, closes, period=14):
        """حساب مؤشر RSI برمجياً بدقة عالية"""
        try:
            c = np.asarray(closes, dtype=float)
            if len(c) < period + 1:
                return 50.0
            deltas = np.diff(c)
            seed = deltas[:period]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            if down == 0:
                return 100.0
            rs = up / down
            return float(100.0 - (100.0 / (1.0 + rs)))
        except Exception:
            return 50.0

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, btc_ohlcv_15m=None, **kwargs
    ):
        if ohlcv_5m is None or ohlcv_1h is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات فريم 5M أو 1H غير متوفرة."}

        m5 = self._array(ohlcv_5m, 25)
        h1 = self._array(ohlcv_1h, 15)

        if m5 is None or h1 is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الشموع غير كافية."}

        # 1. تحديد اتجاه السوق (1H Frame)
        h1_closes = h1[:, 4]
        trend_bullish = h1_closes[-1] > h1_closes[-10] and h1_closes[-5] > h1_closes[-15]
        trend_bearish = h1_closes[-1] < h1_closes[-10] and h1_closes[-5] < h1_closes[-15]

        if not trend_bullish and not trend_bearish:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "السوق عرضي على فريم 1H، تم إيقاف الرادار."}

        current_close = float(m5[-1, 4])
        current_open = float(m5[-1, 1])
        current_high = float(m5[-1, 2])
        current_low = float(m5[-1, 3])

        # ==========================================
        # 2. شروط صفقات الشراء (LONG SETUP)
        # ==========================================
        if trend_bullish:
            recent_lows = m5[-20:-2, 3]
            prior_low = float(np.min(recent_lows))

            # صيد سيولة لقاع سابق (Liquidity Sweep)
            sweep_triggered = (current_low < prior_low) and (current_close > prior_low) and (current_close > current_open)
            if not sweep_triggered:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "الاتجاه صاعد، ولكن لم يحدث صيد سيولة (Sweep) لقاع سابق على 5M."}

            # رصد FVG وكتلة طلب (Order Block) صاعدة
            fvg_found = False
            ob_level = prior_low
            for i in range(len(m5) - 4, len(m5) - 1):
                prev_high = m5[i - 1, 2]
                next_low = m5[i + 1, 3]
                if next_low > prev_high:
                    fvg_found = True
                    ob_level = m5[i, 3]

            if not fvg_found:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد فجوة سعرية صاعدة (FVG) أو كتلة طلب مناسبة."}

            # انحراف إيجابي (Bullish Divergence) على مؤشر RSI
            rsi_current = self.calculate_rsi(m5[:, 4], 14)
            rsi_prev = self.calculate_rsi(m5[:-3, 4], 14)
            price_current = float(m5[-1, 4])
            price_prev = float(m5[-4, 4])

            bullish_div = (price_current < price_prev) and (rsi_current > rsi_prev)
            if not bullish_div:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "شروط الزخم لم تكتمل: لا يوجد انحراف إيجابي (Bullish Divergence) على RSI."}

            # إدارة المخاطر لصفقة الشراء
            entry_price = current_close
            stop_loss = prior_low - (prior_low * 0.002)  # تحت قاع الـ Sweep بـ 0.2%
            recent_high = float(np.max(m5[-20:-2, 2]))
            tp1 = recent_high  # الهدف الأول عند أقرب قمة رئيسية
            
            risk = entry_price - stop_loss
            if risk <= 0:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "خطأ في حساب مسافة المخاطرة."}

            tp2 = entry_price + (risk * 2.5)  # العائد إلى مخاطرة 1:2.5
            risk_usd = self.total_capital * self.risk_per_trade
            position_size = risk_usd / risk

            details = {
                "trade_valid": True,
                "signal_type": "SMC_LONG_SETUP",
                "reason": "تطابق الشروط الـ 4 الكاملة: اتجاه صاعد 1H + صيد سيولة لقاع 5M + FVG صاعد + انحراف RSI إيجابي.",
                "score": 100,
                "stop_loss": self._round(stop_loss),
                "entry_zone": {
                    "ideal_entry": self._round(entry_price),
                    "order_block": self._round(ob_level)
                },
                "risk_management": {
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "breakeven_trigger": self._round(tp1),
                    "position_size_units": self._round(position_size),
                    "risk_usd": self._round(risk_usd)
                }
            }
            return "LONG", self._round(entry_price), details

        # ==========================================
        # 3. شروط صفقات البيع (SHORT SETUP)
        # ==========================================
        elif trend_bearish:
            recent_highs = m5[-20:-2, 2]
            prior_high = float(np.max(recent_highs))

            # صيد سيولة لقمة سابقة (Liquidity Sweep للقمة الأعلى)
            sweep_triggered = (current_high > prior_high) and (current_close < prior_high) and (current_close < current_open)
            if not sweep_triggered:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "الاتجاه هابط، ولكن لم يحدث صيد سيولة (Sweep) لقمة سابقة على 5M."}

            # رصد FVG وكتلة عرض (Bearish Order Block) هابطة
            fvg_found = False
            ob_level = prior_high
            for i in range(len(m5) - 4, len(m5) - 1):
                prev_low = m5[i - 1, 3]
                next_high = m5[i + 1, 2]
                if next_high < prev_low:
                    fvg_found = True
                    ob_level = m5[i, 2]

            if not fvg_found:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد فجوة سعرية هابطة (FVG) أو كتلة عرض مناسبة."}

            # انحراف سلبي (Bearish Divergence) على مؤشر RSI
            rsi_current = self.calculate_rsi(m5[:, 4], 14)
            rsi_prev = self.calculate_rsi(m5[:-3, 4], 14)
            price_current = float(m5[-1, 4])
            price_prev = float(m5[-4, 4])

            bearish_div = (price_current > price_prev) and (rsi_current < rsi_prev)
            if not bearish_div:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "شروط الزخم لم تكتمل: لا يوجد انحراف سلبي (Bearish Divergence) على RSI."}

            # إدارة المخاطر لصفقة البيع (SL فوق قمة الـ Sweep بـ 0.2%)
            entry_price = current_close
            stop_loss = prior_high + (prior_high * 0.002)
            recent_low = float(np.min(m5[-20:-2, 3]))
            tp1 = recent_low  # الهدف الأول عند أقرب قاع رئيسي دعم
            
            risk = stop_loss - entry_price
            if risk <= 0:
                return "NEUTRAL", 0, {"trade_valid": False, "reason": "خطأ في حساب مسافة المخاطرة للبيع."}

            tp2 = entry_price - (risk * 2.5)  # العائد إلى مخاطرة 1:2.5
            risk_usd = self.total_capital * self.risk_per_trade
            position_size = risk_usd / risk

            details = {
                "trade_valid": True,
                "signal_type": "SMC_SHORT_SETUP",
                "reason": "تطابق الشروط الـ 4 الكاملة: اتجاه هابط 1H + صيد سيولة لقمة 5M + FVG هابط + انحراف RSI سلبي.",
                "score": 100,
                "stop_loss": self._round(stop_loss),
                "entry_zone": {
                    "ideal_entry": self._round(entry_price),
                    "order_block": self._round(ob_level)
                },
                "risk_management": {
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "breakeven_trigger": self._round(tp1),
                    "position_size_units": self._round(position_size),
                    "risk_usd": self._round(risk_usd)
                }
            }
            return "SHORT", self._round(entry_price), details

        return "NEUTRAL", 0, {"trade_valid": False, "reason": "لا توجد فرص مطابقة."}

    def analyze_multi_timeframe(self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
                                ohlcv_4h=None, btc_ohlcv_15m=None, **kwargs):
        return self.analyze_market_structure(
            ohlcv_5m=ohlcv_5m, ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h,
            ohlcv_4h=ohlcv_4h, btc_ohlcv_15m=btc_ohlcv_15m, **kwargs
        )
