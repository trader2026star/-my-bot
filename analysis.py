# ==========================================
# ADVANCED INSTITUTIONAL LIQUIDITY ENGINE (V5 - Custom Assets & Deep Analysis)
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

    def analyze_institutional_setup(self, ohlcv_1h, ohlcv_5m, symbol=""):
        d = {"trend_htf": "NEUTRAL", "predictive_entry": None, "zone": [], "reasons_excluded": [], "confirmations": []}
        empty = ([], [], [])

        if not self.valid_ohlcv(ohlcv_1h, 20) or not self.valid_ohlcv(ohlcv_5m, 20):
            d['reasons_excluded'] = ["بيانات غير كافية للتحليل العميق"]
            return "NEUTRAL", 0, 0.0, d, empty

        # تحليل فريم الساعة (HTF) للدعوم، المقاومة، ومناطق السيولة الكبرى
        o_1h, h_1h, l_1h, c_1h, v_1h = self.arrays(ohlcv_1h)
        support_htf = float(np.min(l_1h[-24:]))
        resistance_htf = float(np.max(h_1h[-24:]))
        equilibrium_50 = (resistance_htf + support_htf) / 2

        # تحليل فريم 5 دقائق (LTF) للفجوات (FVG) ومسح السيولة
        o_5m, h_5m, l_5m, c_5m, v_5m = self.arrays(ohlcv_5m)
        current_price = float(c_5m[-1])

        avg_volume_20 = float(np.mean(v_5m[-15:-1])) if len(v_5m) >= 16 else float(np.mean(v_5m))
        current_volume = float(v_5m[-1])
        is_volume_surge = current_volume >= (avg_volume_20 * 1.5)

        if not is_volume_surge:
            d['reasons_excluded'].append("السيولة الحجمية دون المعدل المؤسسي المطلوب")
            return "NEUTRAL", 20, 1.0, d, (h_5m.tolist(), l_5m.tolist(), c_5m.tolist())

        # كشف سحب السيولة من الدعم/المقاومة الرئيسية
        is_sweep_support = l_5m[-1] < support_htf or l_5m[-2] < support_htf
        is_bullish_fvg_reaction = c_5m[-1] > o_5m[-1] and c_5m[-1] > c_5m[-2]

        if is_sweep_support and is_bullish_reaction := is_bullish_fvg_reaction and current_price < equilibrium_50:
            confirmations = [
                f"تم مسح السيولة واختبار الدعم الرئيسي (HTF Support): {support_htf}",
                f"تدفق حجمي بنسبة: {round(current_volume / avg_volume_20 * 100, 1)}%",
                f"السعر يقع في مصفوفة الخصم (تحت خط الـ 50% Equilibrium عند {round(equilibrium_50, 4)})",
                "تأكيد تشكل الفجوة العادلة الصاعدة (Bullish FVG)"
            ]
            d['predictive_entry'] = current_price
            d['zone'] = [support_htf, resistance_htf]
            d['confirmations'] = confirmations
            return "LONG", 95, 1.3, d, (h_5m.tolist(), l_5m.tolist(), c_5m.tolist())

        is_sweep_resistance = h_5m[-1] > resistance_htf or h_5m[-2] > resistance_htf
        is_bearish_fvg_reaction = c_5m[-1] < o_5m[-1] and c_5m[-1] < c_5m[-2]

        if is_sweep_resistance and is_bearish_fvg_reaction and current_price > equilibrium_50:
            confirmations = [
                f"تم مسح السيولة واختبار المقاومة الرئيسية (HTF Resistance): {resistance_htf}",
                f"تدفق حجمي بنسبة: {round(current_volume / avg_volume_20 * 100, 1)}%",
                f"السعر يقع في مصفوفة الغلاء (فوق خط الـ 50% Equilibrium عند {round(equilibrium_50, 4)})",
                "تأكيد تشكل الفجوة العادلة الهابطة (Bearish FVG)"
            ]
            d['predictive_entry'] = current_price
            d['zone'] = [support_htf, resistance_htf]
            d['confirmations'] = confirmations
            return "SHORT", 95, 1.3, d, (h_5m.tolist(), l_5m.tolist(), c_5m.tolist())

لم تحقق العملة الشروط الكاملة لمسح السيولة وتأكيد الفجوة
        d['reasons_excluded'].append("لم تحقق العملة الشروط الكاملة لمسح السيولة وتأكيد الفجوة")
        return "NEUTRAL", 30, 1.0, d, (h_5m.tolist(), l_5m.tolist(), c_5m.tolist())

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

        recent_low = float(np.min(lows[-15:]))
        recent_high = float(np.max(highs[-15:]))
        pip_buffer = 2 * (entry * 0.0001)

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
