# ============================================================
# MY EXPERT CRYPTO BOT - Smart Scenario SMC Engine (v45.0)
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("SmartScenarioEngine")

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

        h1_closes = h1[:, 4]
        trend_bullish = h1_closes[-1] > h1_closes[-10]
        trend_bearish = h1_closes[-1] < h1_closes[-10]
        market_trend_str = "صاعد (Bullish)" if trend_bullish else ("هابط (Bearish)" if trend_bearish else "عرضي (Sideways)")

        current_close = float(m5[-1, 4])
        recent_highs = m5[-20:-2, 2]
        recent_lows = m5[-20:-2, 3]
        prior_high = float(np.max(recent_highs))
        prior_low = float(np.min(recent_lows))
        rsi_current = self.calculate_rsi(m5[:, 4], 14)

        # 1. تحديد أي السيناريوهين هو الأقرب بناءً على موقع السعر الحالي
        dist_to_high = abs(prior_high - current_close)
        dist_to_low = abs(current_close - prior_low)

        # إذا كان السعر أقرب للقمة أو الاتجاه صاعد قوي -> سيناريو الاختراق هو الأقرب
        if dist_to_high <= dist_to_low or trend_bullish:
            closest_scenario = "BREAKOUT"  # سيناريو الاختراق
            trigger_price = prior_high * 1.0015  # سعر تأكيد الاختراق فوق المقاومة
            ideal_entry = trigger_price
            stop_loss = prior_high * 0.995       # الوقف تحت مستوى الاختراق
            tp1 = trigger_price * 1.015          # الهدف الأول (1.5%)
            tp2 = trigger_price * 1.035          # الهدف الثاني (3.5%)
            scenario_desc = f"السيناريو الأقرب هو 'اختراق المقاومة'. ينصح بالدخول عند كسر وتأكيد السعر الموضح."
        else:
            closest_scenario = "SUPPORT_RETEST"  # سيناريو الشراء من الدعم
            trigger_price = prior_low * 1.001    # سعر الدعم المؤكد للارتداد
            ideal_entry = trigger_price
            stop_loss = prior_low * 0.993        # الوقف تحت القاع
            tp1 = current_close                  # الهدف الأول عند السعر الحالي
            tp2 = prior_high                     # الهدف الثاني عند القمة السابقة
            scenario_desc = f"السيناريو الأقرب هو 'الارتداد من الدعم'. ينصح بالشراء بالقرب من منطقة الدعم."

        details = {
            "trade_valid": False,
            "signal_type": closest_scenario,
            "market_trend": market_trend_str,
            "rsi": self._round(rsi_current),
            "reason": scenario_desc,
            "closest_scenario": closest_scenario,
            "trigger_price": self._round(trigger_price),
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "ideal_entry": self._round(ideal_entry),
                "support_level": self._round(prior_low),
                "resistance_level": self._round(prior_high)
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2)
            }
        }
        return "LONG" if trend_bullish else "SHORT", self._round(current_close), details
