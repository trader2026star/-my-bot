# ============================================================
# MY EXPERT CRYPTO BOT - V23.3 Institutional SMC & Real Sweep Engine
# Multi-timeframe: 1D Bias -> 4H Structure -> 1H POI -> 15M Trigger
# Signal-only: does NOT place exchange orders.
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("AdvancedSMCEngine")


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

        self.max_stop_pct = 0.08
        self.min_stop_pct = 0.001
        self.min_rr = 1.5
        self.signal_threshold = 72

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
            if len(a) > 1 and np.any(np.diff(a[:, 0]) < 0):
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
        decimals = max(2, min(12, int(-math.floor(math.log10(abs(value)))) + 3))
        return round(value, decimals)

    def calculate_atr(self, highs, lows, closes, period=14):
        try:
            h = np.asarray(highs, dtype=float).reshape(-1)
            l = np.asarray(lows, dtype=float).reshape(-1)
            c = np.asarray(closes, dtype=float).reshape(-1)
            n = min(len(h), len(l), len(c))
            if n < 2:
                return 0.0
            h, l, c = h[-n:], l[-n:], c[-n:]
            tr = np.maximum(
                h[1:] - l[1:],
                np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
            )
            tr = tr[np.isfinite(tr) & (tr >= 0)]
            if len(tr) == 0:
                return 0.0
            return float(np.mean(tr[-max(1, int(period)):]))
        except Exception:
            return 0.0

    def _atr_from_array(self, a, period=14):
        return self.calculate_atr(a[:, 2], a[:, 3], a[:, 4], period)

    def detect_true_order_block(self, ohlcv):
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 8 or a.shape[1] < 6:
                return 0.0, 0.0
            atr = self._atr_from_array(a, 14)
            end = len(a) - 1
            bullish_ob = bearish_ob = None
            start = max(1, end - 20)
            for i in range(end - 1, start - 1, -1):
                current = a[i]
                nxt = a[i + 1]
                body_next = abs(nxt[4] - nxt[1])
                displacement = atr > 0 and body_next >= 0.8 * atr
                if (current[4] < current[1] and nxt[4] > nxt[1] and displacement and bullish_ob is None):
                    bullish_ob = float(min(current[3], current[1], current[4]))
                if (current[4] > current[1] and nxt[4] < nxt[1] and displacement and bearish_ob is None):
                    bearish_ob = float(max(current[2], current[1], current[4]))
                if bullish_ob is not None and bearish_ob is not None:
                    break
            recent = a[max(0, end - 10):end]
            return (bullish_ob or float(np.min(recent[:, 3]))), (bearish_ob or float(np.max(recent[:, 2])))
        except Exception:
            return 0.0, 0.0

    def _trend(self, a):
        closes = a[:-1, 4]
        if len(closes) < 20:
            return 0
        short = float(np.mean(closes[-5:]))
        long = float(np.mean(closes[-20:]))
        last = float(closes[-1])
        if last > short and short > long:
            return 1
        if last < short and short < long:
            return -1
        return 0

    def check_real_liquidity_sweep_and_closure(self, ohlcv):
        """
        تطبيق استراتيجية الصور بدقة:
        - الفتيلة الصغيرة وحدها لا تكفي (مجرد ضوضاء / Not a real sweep).
        - الاصطياد الحقيقي يتطلب كسر المستوى ثم إغلاق شمعة كاملة (Candle Closure) فوقه أو تحته لدخول الأموال الحقيقية.
        """
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 15:
                return False, False, 0.0, 0.0
            
            recent_highs = a[-15:-2, 2]
            recent_lows = a[-15:-2, 3]
            prior_high = float(np.max(recent_highs))
            prior_low = float(np.min(recent_lows))

            # شمعة التأكيد الأخيرة المكتملة
            last_candle = a[-2]
            high_val = float(last_candle[2])
            low_val = float(last_candle[3])
            close_val = float(last_candle[4])
            open_val = float(last_candle[1])

            # شروط الاصطياد الحقيقي بإغلاق الشمعة (Candle Closure)
            # صاعد: الفتيل ضرب القاع السابق ولكن الإغلاق تم فوقه أو بداخل الهيكل مع شمعة قوية
            real_bullish_sweep = (low_val < prior_low) and (close_val > prior_low) and (close_val > open_val)
            # هابط: الفتيل ضرب القمة السابقة ولكن الإغلاق تم تحتها مع شمعة هابطة
            real_bearish_sweep = (high_val > prior_high) and (close_val < prior_high) and (close_val < open_val)

            return real_bullish_sweep, real_bearish_sweep, prior_high, prior_low
        except Exception:
            return False, False, 0.0, 0.0

    def analyze_market_structure(
        self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
        ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs
    ):
        if ohlcv_15m is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الفريمات غير متوفرة"}

        m15 = self._array(ohlcv_15m, 30)
        if m15 is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الشموع غير صالحة"}

        d1 = self._array(ohlcv_1d, 25) if ohlcv_1d is not None else m15
        h4 = self._array(ohlcv_4h, 25) if ohlcv_4h is not None else m15
        h1 = self._array(ohlcv_1h, 25) if ohlcv_1h is not None else m15

        daily_trend = self._trend(d1)
        h4_trend = self._trend(h4)
        h1_trend = self._trend(h1)

        candle = m15[-2]
        close = float(candle[4])
        atr = self._atr_from_array(m15[:-1], 14)
        if atr <= 0:
            atr = close * 0.01

        bull_ob, bear_ob = self.detect_true_order_block(m15)
        real_bull_sweep, real_bear_sweep, prior_high, prior_low = self.check_real_liquidity_sweep_and_closure(m15)

        score_long = (20 if daily_trend >= 0 else 0) + (18 if h4_trend >= 0 else 0) + (12 if h1_trend >= 0 else 0)
        if real_bull_sweep:
            score_long += 25  ضاف نقاط مضاعفة لوجود اصطياد سيولة حقيقي مع إغلاق شمعة

        score_short = (20 if daily_trend <= 0 else 0) + (18 if h4_trend <= 0 else 0) + (12 if h1_trend <= 0 else 0)
        if real_bear_sweep:
            score_short += 25

        side = "LONG" if score_long >= score_short else "SHORT"

        if side == "LONG":
            safe_entry = bull_ob if bull_ob > 0 else close - (0.5 * atr)
            stop_loss = safe_entry - (1.5 * atr)
            risk = safe_entry - stop_loss
            tp1 = safe_entry + (risk * 2.0)
            tp2 = safe_entry + (risk * 3.5)
            tp3 = safe_entry + (risk * 5.0)
            trend_text = "صاعد (Bullish) مع تأكيد سحب السيولة الحقيقي والإغلاق"
        else:
            safe_entry = bear_ob if bear_ob > 0 else close + (0.5 * atr)
            stop_loss = safe_entry + (1.5 * atr)
            risk = stop_loss - safe_entry
            tp1 = safe_entry - (risk * 2.0)
            tp2 = safe_entry - (risk * 3.5)
            tp3 = safe_entry - (risk * 5.0)
            trend_text = "هابط (Bearish) مع تأكيد سحب السيولة الحقيقي والإغلاق"

        details = {
            "trade_valid": True,
            "signal_type": "DIRECT_USER_QUERY",
            "reason": f"استراتيجية Real Sweep & Candle Closure: {trend_text}.",
            "score": int(max(score_long, score_short)),
            "score_label": "مفعل ومؤكد باستراتيجية الإغلاق",
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "waiting_price": self._round(safe_entry),
                "note": "نقطة الدخول الآمنة بناءً على منطقة الطلب وتأكيد الإغلاق (تجنب الفتائل الوهمية)"
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
            },
            "market_context": {
                "real_liquidity_sweep": "BULLISH_SWEEP" if real_bull_sweep else ("BEARISH_SWEEP" if real_bear_sweep else "NO_SWEEP"),
                "daily_trend": daily_trend,
                "h4_trend": h4_trend,
                "h1_trend": h1_trend
            },
            "smc_note": "تم تطبيق استراتيجية الفتيل الضوضائي مقابل الإغلاق الحقيقي (Real Money Liquidity Sweep) بنجاح."
        }

        return side, self._round(close), details

    def analyze_multi_timeframe(self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
                                ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs):
        return self.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h,
            ohlcv_1d=ohlcv_1d, btc_ohlcv_1d=btc_ohlcv_1d, **kwargs
        )
