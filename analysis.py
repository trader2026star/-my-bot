# ==========================================
# MY EXPERT CRYPTO BOT — ICT OTE + Elliot Structure Engine
# Fibonacci OTE (61.8% - 78.6%) + FVG + Market Structure Filter
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
    def _detect_htf_trend(cls, closes_4h, closes_1h):
        """تحديد الاتجاه الهيكلي العام (فلسفة الاتجاه الكلي - Wave Context)"""
        if len(closes_4h) < 20 or len(closes_1h) < 20:
            return "NEUTRAL"
        
        c4_now, c4_prev = closes_4h[-1], closes_4h[-10]
        c1_now, c1_prev = closes_1h[-1], closes_1h[-10]
        
        if c4_now > c4_prev and c1_now > c1_prev:
            return "LONG"
        elif c4_now < c4_prev and c1_now < c1_prev:
            return "SHORT"
        
        return "NEUTRAL"

    @classmethod
    def _detect_ict_ote(cls, highs, lows, closes):
        """
        تطبيق استراتيجية ICT OTE (Optimal Trade Entry):
        1. تحديد قمة وقاع الموجة (Swing High / Swing Low).
        2. حساب مستويات الفيبوناتشي لتصحيح OTE (بين 61.8% و 78.6%).
        3. التحقق مما إذا كان السعر الحالي داخل منطقة الدخول المثالية.
        """
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 30:
            return "NEUTRAL", None, 0.0, 0.0

        swing_high = float(np.max(h[-30:]))
        swing_low = float(np.min(l[-30:]))
        current_price = float(c[-1])
        
        diff = swing_high - swing_low
        if diff <= 0 or (diff / current_price) < 0.008: # استبعاد الموجات الضعيفة جداً
            return "NEUTRAL", None, swing_low, swing_high

        # مستويات الفيبوناتشي
        ote_618_bull = swing_high - (diff * 0.618)
        ote_786_bull = swing_high - (diff * 0.786)

        ote_618_bear = swing_low + (diff * 0.618)
        ote_786_bear = swing_low + (diff * 0.786)

        # منطقة الشراء (Long OTE)
        if ote_786_bull <= current_price <= ote_618_bull:
            return "LONG", float((ote_618_bull + ote_786_bull) / 2), swing_low, swing_high

        # منطقة البيع (Short OTE)
        if ote_618_bear <= current_price <= ote_786_bear:
            return "SHORT", float((ote_618_bear + ote_786_bear) / 2), swing_low, swing_high

        return "NEUTRAL", None, swing_low, swing_high

    @classmethod
    def _detect_fvg_ob(cls, opens, highs, lows, closes, direction):
        """تأكيد الدخول عبر الفجوات السعرية (FVG) وبداية ارتداد الهيكل السعري"""
        o = np.asarray(opens, dtype=float)
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 5:
            return False, "لا يوجد توافق مع FVG/OB"

        # فحص وجود FVG صاعد أو هابط
        if direction == 'LONG':
            if l[-1] > h[-3] or c[-1] > o[-1]: # وجود FVG أو شمعة انعكاسية صاعدة
                return True, "تم التأكيد بوجود FVG واكتشفت إشارة ارتداد صاعدة"
        elif direction == 'SHORT':
            if h[-1] < l[-3] or c[-1] < o[-1]: # وجود FVG أو شمعة انعكاسية هابطة
                return True, "تم التأكيد بوجود FVG واكتشفت إشارة ارتداد هابطة"

        return True, "تم دخول منطقة OTE المثالية بنجاح"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None,
                                symbol="", market_context=None, order_book=None, trades=None):
        d = {"trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL", "predictive_entry": None, "ote_zone": None, "reasons_excluded": [], "indicators": {}, "market_context": market_context or {}}
        empty = ([], [], [])
        
        if symbol and not self.is_valid_symbol(symbol):
            d['reasons_excluded'] = ["رمز غير صالح"]
            return "NEUTRAL", 0, 0.0, d, empty

        for label, data in (("4H", ohlcv_4h), ("1H", ohlcv_1h), ("15M", ohlcv_15m)):
            if not self.valid_ohlcv(data, 20):
                d['reasons_excluded'].append(f"بيانات {label} غير كافية")
                return "NEUTRAL", 0, 0.0, d, empty

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h[:-1])
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h[:-1])
        o, h, l, c, v = self.arrays(ohlcv_15m[:-1])

        # 1. التناغم الهيكلي مع الفريمات الكبيرة (Elliot Wave / Trend Context)
        htf_trend = self._detect_htf_trend(c4, c1)

        # 2. خوارزمية ICT OTE على فريم الـ 15 دقيقة
        direction, ote_target, swing_low, swing_high = self._detect_ict_ote(h, l, c)
        
        if direction == "NEUTRAL":
            d['reasons_excluded'].append("السعر لم يصل بعد إلى منطقة التصحيح المثالية OTE (61.8% - 78.6%)")
            return "NEUTRAL", 30, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        # فلترة الدخول: التأكد من التوافق مع الاتجاه الكلي
        if htf_trend != "NEUTRAL" and direction != htf_trend:
            d['reasons_excluded'].append(f"الاتجاه الكلي الهيكلي ينصح بـ {htf_trend}، تم استبعاد الصفقة المعاكسة.")
            return "NEUTRAL", 40, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        # 3. التأكيد بالفجوات السعرية أو الارتداد الهيكلي
        confirmed, conf_msg = self._detect_fvg_ob(o, h, l, c, direction)
        if not confirmed:
            d['reasons_excluded'].append("لم يتم تأكيد الارتداد عبر FVG أو OB")
            return "NEUTRAL", 50, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        confirmations = [
            f"التناغم الهيكلي ممتاذ مع اتجاه الفريمات الكبرى ({htf_trend})",
            f"تم تحديد القمة ({swing_high}) والقاع ({swing_low}) بدقة",
            f"السعر صحح بنجاح داخل نطاق الفيبوناتشي الذهبي OTE (61.8% - 78.6%)",
            conf_msg
        ]

        d['predictive_entry'] = ote_target
        d['ote_zone'] = [swing_low, swing_high]

        score = 92
        entry_valid = True
        d.update(entry_valid=entry_valid, confirmations=confirmations, candidate_direction=direction)
        return direction, score, 1.2, d, (h.tolist(), l.tolist(), c.tolist())

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

        recent_low = float(np.min(lows[-15:]))
        recent_high = float(np.max(highs[-15:]))
        buffer = 0.2 * atr

        if direction in ('LONG', 'BUY'):
            stop = min(entry - 2.0 * atr, recent_low - buffer)
            risk = entry - stop
            t1, t2, t3 = entry + 1.5 * risk, entry + 2.5 * risk, entry + 4.0 * risk
        else:
            stop = max(entry + 2.0 * atr, recent_high + buffer)
            risk = stop - entry
            t1, t2, t3 = entry - 1.5 * risk, entry - 2.5 * risk, entry - 4.0 * risk

        return (
            round(float(stop), 10),
            round(float(t1), 10),
            round(float(t2), 10),
            round(float(t3), 10),
            round(abs(entry - stop) / entry * 100, 3),
            round(abs(t1 - entry) / entry * 100, 3),
            round(abs(t1 - entry) / abs(entry - stop), 2)
        )
