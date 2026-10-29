# ============================================================
# MY EXPERT CRYPTO BOT - V23.2 Direct Analyst & Pending Engine
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

    def analyze_market_structure(
        self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
        ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs
    ):
        # التحقق من توفر بيانات أساسية على الأقل للرد وعدم التجاهل
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

        # تحديد الاتجاه العام للعملة بناءً على الفريمات الكبرى
        score_long = (20 if daily_trend >= 0 else 0) + (18 if h4_trend >= 0 else 0) + (12 if h1_trend >= 0 else 0)
        score_short = (20 if daily_trend <= 0 else 0) + (18 if h4_trend <= 0 else 0) + (12 if h1_trend <= 0 else 0)

        side = "LONG" if score_long >= score_short else "SHORT"
        
        # حساب سعر الانتظار الآمن والأهداف ووقف الخسارة بشكل دائم لا يرفض أبداً
        if side == "LONG":
            safe_entry = bull_ob if bull_ob > 0 else close - (0.5 * atr)
            stop_loss = safe_entry - (1.5 * atr)
            risk = safe_entry - stop_loss
            tp1 = safe_entry + (risk * 2.0)
            tp2 = safe_entry + (risk * 3.5)
            tp3 = safe_entry + (risk * 5.0)
            trend_text = "صاعد (Bullish)"
        else:
            safe_entry = bear_ob if bear_ob > 0 else close + (0.5 * atr)
            stop_loss = safe_entry + (1.5 * atr)
            risk = stop_loss - safe_entry
            tp1 = safe_entry - (risk * 2.0)
            tp2 = safe_entry - (risk * 3.5)
            tp3 = safe_entry - (risk * 5.0)
            trend_text = "هابط (Bearish)"

        details = {
            "trade_valid": True,
            "signal_type": "DIRECT_USER_QUERY",
            "reason": f"تحليل الاتجاه العام للعملة: {trend_text}. تم تحديد نقطة الانتظار الآمنة والأهداف.",
            "score": int(max(score_long, score_short)),
            "score_label": "مفعل ومتاح للمتابعة",
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "waiting_price": self._round(safe_entry),
                "note": "انتظر وصول السعر لهذه المنطقة لتكون آمنة للدخول وضع تنبيهاً عليها"
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
            },
            "market_context": {
                "trend": trend_text,
                "daily_trend": daily_trend,
                "h4_trend": h4_trend,
                "h1_trend": h1_trend
            },
            "smc_note": "تحليل استباقي دائم: البوت يعطيك الاتجاه والدخول الآمن والأهداف والوقف فوراً عند كل سؤال."
        }
        
        return side, self._round(close), details

    def analyze_multi_timeframe(self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
                                ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs):
        return self.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h,
            ohlcv_1d=ohlcv_1d, btc_ohlcv_1d=btc_ohlcv_1d, **kwargs
        )
