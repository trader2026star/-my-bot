# ============================================================
# MY EXPERT CRYPTO BOT - Flexible Analytical SMC Engine (v44.0)
# Comprehensive On-Demand Analysis & Structured Levels
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("FlexibleAnalyticalEngine")

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
        current_open = float(m5[-1, 1])
        current_high = float(m5[-1, 2])
        current_low = float(m5[-1, 3])

        recent_highs = m5[-20:-2, 2]
        recent_lows = m5[-20:-2, 3]
        prior_high = float(np.max(recent_highs))
        prior_low = float(np.min(recent_lows))
        rsi_current = self.calculate_rsi(m5[:, 4], 14)

        # محاولة رصد شروط صفقات النخبة (LONG / SHORT) إن وجدت بالكامل
        if trend_bullish:
            sweep_triggered = (current_low < prior_low) and (current_close > prior_low)
            if sweep_triggered:
                entry_price = current_close
                stop_loss = prior_low - (prior_low * 0.002)
                tp1 = prior_high
                risk = entry_price - stop_loss
                tp2 = entry_price + (max(risk, entry_price * 0.005) * 2)
                details = {
                    "trade_valid": True,
                    "signal_type": "SMC_LONG_SETUP",
                    "market_trend": market_trend_str,
                    "rsi": self._round(rsi_current),
                    "reason": "تأكيد صيد السيولة (Sweep) الصاعد مع ارتداد إيجابي واكتملت شروط الـ SMC.",
                    "stop_loss": self._round(stop_loss),
                    "entry_zone": {"ideal_entry": self._round(entry_price), "breakout_level": self._round(prior_high)},
                    "risk_management": {"take_profit_1": self._round(tp1), "take_profit_2": self._round(tp2)}
                }
                return "LONG", self._round(entry_price), details

        elif trend_bearish:
            sweep_triggered = (current_high > prior_high) and (current_close < prior_high)
            if sweep_triggered:
                entry_price = current_close
                stop_loss = prior_high + (prior_high * 0.002)
                tp1 = prior_low
                risk = stop_loss - entry_price
                tp2 = entry_price - (max(risk, entry_price * 0.005) * 2)
                details = {
                    "trade_valid": True,
                    "signal_type": "SMC_SHORT_SETUP",
                    "market_trend": market_trend_str,
                    "rsi": self._round(rsi_current),
                    "reason": "تأكيد صيد السيولة (Sweep) الهابط للقمة مع تفاعل سلبي.",
                    "stop_loss": self._round(stop_loss),
                    "entry_zone": {"ideal_entry": self._round(entry_price), "breakout_level": self._round(prior_low)},
                    "risk_management": {"take_profit_1": self._round(tp1), "take_profit_2": self._round(tp2)}
                }
                return "SHORT", self._round(entry_price), details

        # ==========================================
        # في حال لم تكتمل شروط الصفقة المثالية 100%، نعطي تحليلاً هيكلياً شاملاً ومستويات الاختراق والدخول
        # ==========================================
        base_dir = "LONG" if trend_bullish or (not trend_bearish) else "SHORT"
        
        # حساب مستويات اختراق واقعية وأهداف بناءً على القمم والقيعان الحالية
        if base_dir == "LONG":
            breakout_price = prior_high * 1.001  # سعر الاختراق فوق المقاومة بقليل
            ideal_entry = current_close
            stop_loss = prior_low * 0.998        # وقف الخسارة تحت القاع الأخير
            tp1 = prior_high
            tp2 = prior_high * 1.025
            reason_text = f"الاتجاه العام على فريم 1H هو '{market_trend_str}'. السعر يتحرك لاختبار مستويات السيولة. ننتظر الاختراق المؤكد أو الشراء من مناطق الدعم."
        else:
            breakout_price = prior_low * 0.999   # سعر كسر الدعم للبيع
            ideal_entry = current_close
            stop_loss = prior_high * 1.002       # وقف الخسارة فوق القمة
            tp1 = prior_low
            tp2 = prior_low * 0.975
            reason_text = f"الاتجاه العام على فريم 1H هو '{market_trend_str}'. الضغوط البيعية مستمرة، ونراقب مستويات الكسر."

        details = {
            "trade_valid": False,  # تحليل توجيهي استباقي مفصل وليس صفقة عمياء
            "signal_type": f"ANALYTICAL_{base_dir}_VIEW",
            "market_trend": market_trend_str,
            "rsi": self._round(rsi_current),
            "reason": reason_text,
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "ideal_entry": self._round(ideal_entry),
                "breakout_level": self._round(breakout_price),
                "support_level": self._round(prior_low),
                "resistance_level": self._round(prior_high)
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2)
            }
        }
        return base_dir, self._round(ideal_entry), details
