# ============================================================
# MY EXPERT CRYPTO BOT - V25.0 Demand/Supply Mitigation Elite
# Exact Strategy: Order Block / Demand Zone Identification, Mitigation & Retest
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("MitigationEngine")


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
            return a
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
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

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
        except Exception:
            return 0.0

    @staticmethod
    def _find_demand_zone(arr):
        """البحث عن آخر شمعة هابطة قوية تسببت في دفع السعر للأعلى (Demand Order Block)"""
        if len(arr) < 15:
            return None, None
        for i in range(len(arr) - 3, 5, -1):
            prev_candle = arr[i]      # الشمعة الهابطة
            next_candle = arr[i + 1]  # شمعة الانفجار الصاعد
            # شروط بلوك الطلب: الشمعة السابقة حمراء والتي تليها خضراء قوية اخترقت القمة
            if prev_candle[4] < prev_candle[1] and next_candle[4] > next_candle[1]:
                zone_low = float(min(prev_candle[3], next_candle[3]))
                zone_high = float(max(prev_candle[1], prev_candle[2]))
                if zone_high > zone_low:
                    return zone_low, zone_high
        # افتراضي بناءً على أدنى قاع حديث إذا لم يُوجد بلوك صريح
        recent_low = float(np.min(arr[-10:-2, 3]))
        recent_high = float(np.mean(arr[-10:-2, 4]))
        return recent_low, recent_high * 0.995

    @staticmethod
    def _find_supply_zone(arr):
        """البحث عن آخر شمعة صاعدة قبل الانفجار الهابط (Supply Order Block)"""
        if len(arr) < 15:
            return None, None
        for i in range(len(arr) - 3, 5, -1):
            prev_candle = arr[i]
            next_candle = arr[i + 1]
            if prev_candle[4] > prev_candle[1] and next_candle[4] < next_candle[1]:
                zone_low = float(min(prev_candle[3], next_candle[3]))
                zone_high = float(max(prev_candle[2], next_candle[2]))
                if zone_high > zone_low:
                    return zone_low, zone_high
        recent_high = float(np.max(arr[-10:-2, 2]))
        recent_low = float(np.mean(arr[-10:-2, 4]))
        return recent_low * 1.005, recent_high

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"trade_valid": False, "reason": reason, "score": 0}

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات الفريمات غير مكتملة")

        m15 = self._array(ohlcv_15m, 25)
        d1 = self._array(ohlcv_1d, 20)
        h4 = self._array(ohlcv_4h, 20)
        
        if m15 is None or d1 is None or h4 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل")

        daily_close = float(d1[-2, 4])
        daily_ma20 = float(np.mean(d1[:-1, 4][-20:]))
        
        close = float(m15[-2, 4])
        open_ = float(m15[-2, 1])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])
        volume = float(m15[-2, 5])

        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)
        if atr <= 0:
            return no_trade("تعذر حساب ATR")

        is_bullish_trend = daily_close >= daily_ma20
        is_bearish_trend = daily_close < daily_ma20

        # استخراج منطقة الطلب أو العرض حسب الشارت تماماً
        demand_low, demand_high = self._find_demand_zone(m15)
        supply_low, supply_high = self._find_supply_zone(m15)

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        # تطبيق استراتيجية الشارت: ملامسة المنطقة (Mitigation/Retest) + ارتداد مؤكد
        if is_bullish_trend and demand_low is not None:
            # التحقق مما إذا كان السعر قد دخل في منطقة الطلب (Demand Zone Retest)
            in_demand_zone = (demand_low * 0.995 <= low <= demand_high * 1.005) or (demand_low * 0.995 <= close <= demand_high * 1.005)
            strong_rejection = (close > open_) and (body_ratio >= 0.35) # شمعة ارتداد خضراء من المنطقة

            if not in_demand_zone:
                return no_trade("السعر لم يقم بإعادة اختبار (Mitigation) لمنطقة الطلب بعد")
            if not strong_rejection:
                return no_trade("السعر داخل منطقة الطلب لكن لم تظهر شمعة ارتداد مؤكدة بعد")

            score = 88
            stop = float(demand_low - (1.2 * atr))  # وقف الخسارة تحت منطقة الطلب مباشرة كما في الاستراتيجية
            risk_dist = close - stop
            max_allowed_risk = close * 0.045

            if not np.isfinite(risk_dist) or risk_dist <= 0 or risk_dist > max_allowed_risk:
                return no_trade("مسافة وقف الخسارة غير صالحة أو بعيدة جداً")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist
            effective_risk_usd = qty * risk_dist

            tp1 = close + (risk_dist * 1.5)
            tp2 = close + (risk_dist * 2.5)
            tp3 = close + (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "Exact Strategy: Demand Zone Mitigation & Rejection Retest",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V25.0 Demand Mitigation LONG",
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"Demand Retest LONG | Zone=[{self._round(demand_low)} - {self._round(demand_high)}] | Score={score}"
            }
            return "LONG", self._round(close), details

        elif is_bearish_trend and supply_low is not None:
            in_supply_zone = (supply_low * 0.995 <= high <= supply_high * 1.005) or (supply_low * 0.995 <= close <= supply_high * 1.005)
            strong_rejection_bear = (close < open_) and (body_ratio >= 0.35)

            if not in_supply_zone:
                return no_trade("السعر لم يقم بإعادة اختبار (Mitigation) لمنطقة العرض بعد")
            if not strong_rejection_bear:
                return no_trade("السعر داخل منطقة العرض لكن لم تظهر شمعة رفض هابط مؤكدة بعد")

            score = 88
            stop = float(supply_high + (1.2 * atr))
            risk_dist = stop - close
            max_allowed_risk = close * 0.045

            if not np.isfinite(risk_dist) or risk_dist <= 0 or risk_dist > max_allowed_risk:
                return no_trade("مسافة وقف الخسارة للبيع غير صالحة أو بعيدة جداً")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist
            effective_risk_usd = qty * risk_dist

            tp1 = close - (risk_dist * 1.5)
            tp2 = close - (risk_dist * 2.5)
            tp3 = close - (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "Exact Strategy: Supply Zone Mitigation & Rejection Retest",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V25.0 Supply Mitigation SHORT",
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"Supply Retest SHORT | Zone=[{self._round(supply_low)} - {self._round(supply_high)}] | Score={score}"
            }
            return "SHORT", self._round(close), details

        else:
            return no_trade("السعر ليس في منطقة إعادة اختبار (Mitigation Zone) مطابقة للاستراتيجية")
