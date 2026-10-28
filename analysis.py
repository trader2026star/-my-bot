# ============================================================
# MY EXPERT CRYPTO BOT - V26.0 HTF/LTF Master (1H Direction + 5m Entry)
# Strict Multi-Timeframe Alignment: 1H Trend Direction & 5m Precision Entry
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("HTFLTFEngine")


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

    def analyze_market_structure(self, ohlcv_5m=None, ohlcv_1h=None, ohlcv_15m=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"trade_valid": False, "reason": reason, "score": 0}

        # الاعتماد على 1H لتحديد الاتجاه (Direction) و 5m للتنفيذ (Entry)
        if ohlcv_1h is None or ohlcv_5m is None:
            # توافقاً مع الدالة القديمة إذا أُرسلت الفريمات الأربعة الأساسية
            if ohlcv_15m is not None and ohlcv_1h is not None:
                ohlcv_5m = ohlcv_15m # كاحتياط إذا لم يتم توفير 5م منفصلاً
            else:
                return no_trade("بيانات فريمات الاتجاه (1H) أو الدخول (5m) غير مكتملة")

        h1 = self._array(ohlcv_1h, 20)
        m5 = self._array(ohlcv_5m, 20)

        if h1 is None or m5 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل الزمني")

        # 1. تحديد اتجاه السوق الأساسي من فريم الساعة (1H Direction) باستخدام متوسط الحركة 20
        h1_closes = h1[:-1, 4]
        h1_ma20 = float(np.mean(h1_closes[-20:]))
        h1_current_close = float(h1[-2, 4])

        is_h1_bullish = h1_current_close >= h1_ma20
        is_h1_bearish = h1_current_close < h1_ma20

        if not is_h1_bullish and not is_h1_bearish:
            return no_trade("اتجاه فريم الساعة (1H Direction) متذبذب ولا يحقق شروط الحسم")

        # 2. منطقة البحث والدخول على فريم الـ 5 دقائق (5m Entry)
        open_ = float(m5[-2, 1])
        close = float(m5[-2, 4])
        high = float(m5[-2, 2])
        low = float(m5[-2, 3])

        atr = self.calculate_atr(m5[:-1, 2], m5[:-1, 3], m5[:-1, 4], 14)
        if atr <= 0:
            return no_trade("تعذر حساب نطاق الحركة ATR على فريم 5م")

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        # استخراج مناطق السيولة والارتداد على فريم 5 دقائق
        recent_5m_low = float(np.min(m5[-10:-2, 3]))
        recent_5m_high = float(np.max(m5[-10:-2, 2]))

        if is_h1_bullish:
            # شروط الشراء: الاتجاه على 1H صاعد، والدخول على 5m بعد لمس قاع أو سيولة سفلية مع ارتداد
            near_support = (recent_5m_low * 0.998 <= low <= recent_5m_low * 1.008) or (close >= recent_5m_low)
            strong_green = (close > open_) and (body_ratio >= 0.35)

            if not near_support:
                return no_trade("السعر لم يصل لمنطقة الدخول المثالية على فريم 5m بعد")
            if not strong_green:
                return no_trade("السعر عند الدعم لكن شمعة الـ 5m لم تعطِ تأكيد صعود قوي بعد")

            score = 90
            stop = float(recent_5m_low - (1.1 * atr)) # وقف الخسارة تحت قاع الـ 5 دقائق تماماً كما في الشارت
            risk_dist = close - stop
            max_allowed_risk = close * 0.045

            if not np.isfinite(risk_dist) or risk_dist <= 0 or risk_dist > max_allowed_risk:
                return no_trade("مسافة وقف الخسارة على فريم 5m غير صالحة")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist
            effective_risk_usd = qty * risk_dist

            tp1 = close + (risk_dist * 1.5)
            tp2 = close + (risk_dist * 2.5)
            tp3 = close + (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "1H Direction Bullish + 5m Entry Liquidity Rejection",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V26.0 1H/5m Master LONG",
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"1H/5m LONG | H1 Trend=Bullish | 5m Support={self._round(recent_5m_low)}"
            }
            return "LONG", self._round(close), details

        else:
            # شروط البيع: الاتجاه على 1H هابط، والدخول على 5m من قمة أو سيولة علوية
            near_resistance = (recent_5m_high * 0.992 <= high <= recent_5m_high * 1.002) or (close <= recent_5m_high)
            strong_red = (close < open_) and (body_ratio >= 0.35)

            if not near_resistance:
                return no_trade("السعر لم يصل لمنطقة المقاومة على فريم 5m بعد")
            if not strong_red:
                return no_trade("السعر عند المقاومة لكن شمعة الـ 5m لم تعطِ تأكيد هبوط قوي بعد")

            score = 90
            stop = float(recent_5m_high + (1.1 * atr)) # وقف الخسارة فوق قمة الـ 5 دقائق تماماً كما في الشارت
            risk_dist = stop - close
            max_allowed_risk = close * 0.045

            if not np.isfinite(risk_dist) or risk_dist <= 0 or risk_dist > max_allowed_risk:
                return no_trade("مسافة وقف الخسارة على فريم 5m للبيع غير صالحة")

            risk_usd = self.total_capital * self.risk_per_trade
            qty = risk_usd / risk_dist
            effective_risk_usd = qty * risk_dist

            tp1 = close - (risk_dist * 1.5)
            tp2 = close - (risk_dist * 2.5)
            tp3 = close - (risk_dist * 4.0)

            details = {
                "trade_valid": True,
                "reason": "1H Direction Bearish + 5m Entry Liquidity Rejection",
                "stop_loss": self._round(stop),
                "score": score,
                "setup": "V26.0 1H/5m Master SHORT",
                "risk_management": {
                    "allowed_risk_usd": round(risk_usd, 2),
                    "estimated_risk_usd": round(effective_risk_usd, 2),
                    "tokens_to_buy": round(qty, 8),
                    "take_profit_1": self._round(tp1),
                    "take_profit_2": self._round(tp2),
                    "take_profit_3": self._round(tp3),
                },
                "smc_note": f"1H/5m SHORT | H1 Trend=Bearish | 5m Resistance={self._round(recent_5m_high)}"
            }
            return "SHORT", self._round(close), details
