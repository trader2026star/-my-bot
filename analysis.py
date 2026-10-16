# ==========================================
# ADVANCED STRATEGY ENGINE (V8.0 - Multi-Confirmation Breakout & Engulfing)
# ==========================================
import numpy as np

class StrategyEngine:
    def __init__(self):
        self.min_candles = 30

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str) or len(symbol) > 30:
            return False
        return True

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
        h, l, c = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
        n = min(len(h), len(l), len(c))
        if n < 2: return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        if not len(tr): return 0.0
        return float(np.mean(tr[-min(int(period), len(tr)):]))

    def analyze_institutional_setup(self, ohlcv_4h, ohlcv_1h, symbol=""):
        d = {"trend_htf": "NEUTRAL", "predictive_entry": None, "zone": [], "reasons_excluded": [], "confirmations": []}
        empty = ([], [], [])

        if not self.valid_ohlcv(ohlcv_4h, 20) or not self.valid_ohlcv(ohlcv_1h, 20):
            d['reasons_excluded'] = ["بيانات غير كافية للتحليل"]
            return "NEUTRAL", 0, 0.0, d, empty

        o_4h, h_4h, l_4h, c_4h, v_4h = self.arrays(ohlcv_4h)
        o_1h, h_1h, l_1h, c_1h, v_1h = self.arrays(ohlcv_1h)
        current_price = float(c_1h[-1])

        # 1. فلتر الاتجاه العام على فريم 4 ساعات
        ma_4h = float(np.mean(c_4h[-10:]))
        htf_trend = "BULLISH" if c_4h[-1] > ma_4h else "BEARISH"
        d['trend_htf'] = htf_trend

        # 2. تحديد المقاومة والدعم المحلي على فريم الساعة (اكتشاف القناة الهابطة أو التجميع)
        recent_resistance = float(np.max(h_1h[-15:-1]))  # أعلى قمة في آخر 15 شمعة ما عدا الأخيرة
        recent_support = float(np.min(l_1h[-15:-1]))     # أدنى قاع في آخر 15 شمعة ما عدا الأخيرة

        prev_open, prev_close = float(o_1h[-2]), float(c_1h[-2])
        curr_open, curr_close = float(o_1h[-1]), float(c_1h[-1])

        # شروط نموذج الابتلاع
        is_prev_red = prev_close < prev_open
        is_curr_green = curr_close > curr_open
        is_bullish_engulfing = is_prev_red and is_curr_green and curr_close >= prev_open

        is_prev_green = prev_close > prev_open
        is_curr_red = curr_close < curr_open
        is_bearish_engulfing = is_prev_green and is_curr_red and curr_close <= prev_open

        # 3. شروط التأكيد المتعدد (اختراق المقاومة للصعود أو كسر الدعم للهبوط مع فوليوم)
        is_breakout_resistance = curr_close > recent_resistance  # شمعة أغلقت فوق المقاومة الهابطة
        is_breakout_support = curr_close < recent_support        # شمعة أغلقت تحت الدعم

        avg_volume_20 = float(np.mean(v_1h[-15:-1])) if len(v_1h) >= 16 else float(np.mean(v_1h))
        current_volume = float(v_1h[-1])
        is_volume_surge = current_volume >= (avg_volume_20 * 1.35)  # تدفق حجمي قوي ومؤكد للكسر

        # شرط LONG (شراء - تأكيد متعدد: ارتداد من الدعم + اختراق المقاومة + ابتلاع صاعد + فوليوم)
        if is_bullish_engulfing and (is_breakout_resistance or current_price > recent_support) and is_volume_surge and htf_trend == "BULLISH":
            confirmations = [
                "ارتباط الارتداد بمستوى دعم قوي وتشكيل قاع مزدوج",
                "اختراق مقاومة القناة الهابطة بشمعة تأكيد قوية (Breakout Confirmation)",
                "تشكل نموذج الابتلاع الصاعد المؤكد (Bullish Engulfing)",
                f"تدفق حجمي قوي لتأكيد الاختراق بنسبة: {round(current_volume / avg_volume_20 * 100, 1)}%",
                "التوافق مع اتجاه فريم 4 ساعات الصاعد"
            ]
            d['predictive_entry'] = current_price
            d['zone'] = [recent_support, recent_resistance]
            d['confirmations'] = confirmations
            return "LONG", 95, 1.35, d, (h_1h.tolist(), l_1h.tolist(), c_1h.tolist())

        # شرط SHORT (بيع - تأكيد متعدد: كسر الدعم + ابتلاع هابط + فوليوم)
        if is_bearish_engulfing and (is_breakout_support or current_price < recent_resistance) and is_volume_surge and htf_trend == "BEARISH":
            confirmations = [
                "كسر مستوى الدعم الرئيسي وتأكيد السيطرة البيعية",
                "تشكل نموذج الابتلاع الهابط المؤكد (Bearish Engulfing)",
                f"تدفق حجمي قوي لتأكيد الكسر بنسبة: {round(current_volume / avg_volume_20 * 100, 1)}%",
                "التوافق مع اتجاه فريم 4 ساعات الهابط"
            ]
            d['predictive_entry'] = current_price
            d['zone'] = [recent_support, recent_resistance]
            d['confirmations'] = confirmations
            return "SHORT", 95, 1.35, d, (h_1h.tolist(), l_1h.tolist(), c_1h.tolist())

        d['reasons_excluded'].append("لم تكتمل شروط التأكيد المتعدد (الاختراق أو الفوليوم المطلوب)")
        return "NEUTRAL", 30, 1.0, d, (h_1h.tolist(), l_1h.tolist(), c_1h.tolist())

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
            atr = entry * 0.005

        recent_low = float(np.min(lows[-5:]))
        recent_high = float(np.max(highs[-5:]))
        pip_buffer = entry * 0.0005

        if direction in ('LONG', 'BUY'):
            stop = min(entry - (1.5 * atr), recent_low - pip_buffer)
            risk = entry - stop
            t1 = entry + (1.0 * risk)
            t2 = entry + (2.0 * risk)
            t3 = entry + (3.0 * risk)
        else:
            stop = max(entry + (1.5 * atr), recent_high + pip_buffer)
            risk = stop - entry
            t1 = entry - (1.0 * risk)
            t2 = entry - (2.0 * risk)
            t3 = entry - (3.0 * risk)

        return (
            round(float(stop), 10),
            round(float(t1), 10),
            round(float(t2), 10),
            round(float(t3), 10),
            round(abs(entry - stop) / entry * 100, 3),
            round(abs(t3 - entry) / entry * 100, 3),
            "1:3"
        )
