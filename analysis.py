# ==========================================
# MY EXPERT CRYPTO BOT — CISD & Liquidity Rejection Engine
# Anti-Trap Strategy: Swept Liquidity (xxx) + CISD Confirmation
# ==========================================
import numpy as np

class StrategyEngine:
    def __init__(self):
        self.min_candles = 20

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str) or len(symbol) > 30:
            return False
        s = symbol.upper()
        return not any(x in s for x in ("AAPL", "TSLA", "GOOG", "AMZN", "MSFT", "NFLX", "NVDA", "META", "TEST", "DEMO", "FAKE", "NCSK", "BULL", "BEAR"))

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            prev = -1.0
            for row in data:
                if len(row) < 6: return False
                ts, o, h, l, c, v = map(float, row[:6])
                if not all(np.isfinite(z) for z in (ts,o,h,l,c,v)): return False
                if min(o,h,l,c) <= 0 or v < 0 or h < max(o,c) or l > min(o,c) or h < l or ts <= prev: return False
                prev = ts
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        return tuple(np.asarray([float(row[i]) for row in data], dtype=float) for i in (1,2,3,4,5))

    @staticmethod
    def calculate_atr(highs, lows, closes, period=14):
        h,l,c = (np.asarray(z,dtype=float) for z in (highs,lows,closes)); n=min(len(h),len(l),len(c))
        if n < 2: return 0.0
        h,l,c=h[-n:],l[-n:],c[-n:]
        tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
        if not len(tr): return 0.0
        return float(np.mean(tr[-min(int(period),len(tr)):]))

    @classmethod
    def _detect_liquidity_rejection_cisd(cls, opens, highs, lows, closes):
        """
        خوارزمية رفض السيولة وتغير حالة التسليم (CISD):
        1. رصد اختراق القمم/القيعان ثم الرفض السريع (Liquidity Rejection).
        2. التحقق من تكون شمعة CISD عاكسة تلغي افتتاح/إغلاق الشمعة السابقة.
        """
        o = np.asarray(opens, dtype=float)
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 35:
            return "NEUTRAL", 0.0, 0.0, 0.0

        # تحديد القمم والقيعان السابقة التي تراكمت عندها السيولة (xxx)
        recent_high = float(np.max(h[-30:-2]))
        recent_low = float(np.min(l[-30:-2]))
        current_price = float(c[-1])

        # حساب نسبة الذيل لشمعة الرفض الأخيرة (Wick Ratio)
        candle_range = h[-1] - l[-1]
        lower_wick = (min(o[-1], c[-1]) - l[-1]) if candle_range > 0 else 0
        upper_wick = (h[-1] - max(o[-1], c[-1])) if candle_range > 0 else 0

        # 1. حالة الرفض الصاعد (Bullish Rejection - رفض الاستمرار أسفل القيعان) -> LONG
        # شرط سحب السيولة أسفل القاع + إغلاق صاعد أعلى قمة الشمعة السابقة (تأكيد CISD)
        is_bullish_sweep = (l[-2] < recent_low or l[-1] < recent_low)
        is_cisd_long = (c[-1] > o[-1]) and (c[-1] > o[-2]) and (lower_wick / candle_range > 0.35 if candle_range > 0 else False)

        # 2. حالة الرفض الهابط (Bearish Rejection - رفض الاستمرار أعلى القمم) -> SHORT
        # شرط سحب السيولة أعلى القمة + إغلاق هابط أسفل قاع الشمعة السابقة (تأكيد CISD)
        is_bearish_sweep = (h[-2] > recent_high or h[-1] > recent_high)
        is_cisd_short = (c[-1] < o[-1]) and (c[-1] < o[-2]) and (upper_wick / candle_range > 0.35 if candle_range > 0 else False)

        if is_bullish_sweep and is_cisd_long:
            return "LONG", current_price, recent_low, recent_high

        if is_bearish_sweep and is_cisd_short:
            return "SHORT", current_price, recent_low, recent_high

        return "NEUTRAL", 0.0, recent_low, recent_high

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None,
                                symbol="", market_context=None, order_book=None, trades=None):
        d = {"trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL", "predictive_entry": None, "ote_zone": None, "reasons_excluded": [], "indicators": {}, "market_context": market_context or {}}
        empty = ([], [], [])
        
        if symbol and not self.is_valid_symbol(symbol):
            d['reasons_excluded'] = ["رمز غير صالح أو مستبعد"]
            return "NEUTRAL", 0, 0.0, d, empty

        for label, data in (("4H", ohlcv_4h), ("1H", ohlcv_1h), ("15M", ohlcv_15m)):
            if not self.valid_ohlcv(data, 20):
                d['reasons_excluded'].append(f"بيانات {label} غير كافية")
                return "NEUTRAL", 0, 0.0, d, empty

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h[:-1])
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_11h[:-1] if False else ohlcv_1h[:-1])
        o, h, l, c, v = self.arrays(ohlcv_15m[:-1])

        # تطبيق خوارزمية رفض السيولة وCISD
        direction, entry_target, swing_low, swing_high = self._detect_liquidity_rejection_cisd(o, h, l, c)
        
        if direction == "NEUTRAL":
            d['reasons_excluded'].append("لم يتحقق شرط رفض السيولة وتأكيد شمعة CISD بعد")
            return "NEUTRAL", 30, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        confirmations = [
            "تم ضرب السيولة (xxx) والارتداد بنجاح (Liquidity Rejection)",
            "تأكيد نموذج تغير حالة التسليم (CISD) بشمعة انعكاسية قوية",
            "رفض السعر للاستمرار خارج نطاق القمم/القيعان والدخول مع صانع السوق"
        ]

        d['predictive_entry'] = entry_target
        d['ote_zone'] = [swing_low, swing_high]

        score = 98
        entry_valid = True
        d.update(entry_valid=entry_valid, confirmations=confirmations, candidate_direction=direction)
        return direction, score, 1.3, d, (h.tolist(), l.tolist(), c.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        if closes is None:
            closes = (highs + lows) / 2
        closes = np.asarray(closes, dtype=float)
        n = min(len(highs), len(lows), len(closes))
        
        if not np.isfinite(entry) or entry <= 0 or n < 5:
            raise ValueError('Invalid entry')
            
        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        atr = self.calculate_atr(highs, lows, closes)
        if not np.isfinite(atr) or atr <= 0:
            atr = entry * .01

        # الوقف يكون محصناً خلف ذيل شمعة الرفض الأخيرة مباشرة
        recent_low = float(np.min(lows[-10:]))
        recent_high = float(np.max(highs[-10:]))
        buffer = 0.4 * atr

        if direction in ('LONG', 'BUY'):
            stop = min(entry - 2.0 * atr, recent_low - buffer)
            risk = entry - stop
            t1, t2, t3 = entry + 2.0 * risk, entry + 3.5 * risk, entry + 5.0 * risk
        else:
            stop = max(entry + 2.0 * atr, recent_high + buffer)
            risk = stop - entry
            t1, t2, t3 = entry - 2.0 * risk, entry - 3.5 * risk, entry - 5.0 * risk

        return (
            round(float(stop), 10),
            round(float(t1), 10),
            round(float(t2), 10),
            round(float(t3), 10),
            round(abs(entry - stop) / entry * 100, 3),
            round(abs(t1 - entry) / entry * 100, 3),
            round(abs(t1 - entry) / abs(entry - stop), 2)
        )
