# ==========================================
# MY EXPERT CRYPTO BOT — Advanced Protection Engine (V2)
# Enhanced ICT OTE + Volatility Filter + ATR Buffer Guard
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
    def _detect_ict_ote(cls, highs, lows, closes):
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 35:
            return "NEUTRAL", None, 0.0, 0.0, 0.0

        swing_high = float(np.max(h[-35:]))
        swing_low = float(np.min(l[-35:]))
        current_price = float(c[-1])
        
        diff = swing_high - swing_low
        if diff <= 0:
            return "NEUTRAL", None, swing_low, swing_high, 0.0

        volatility_ratio = diff / current_price
        if volatility_ratio > 0.40:
            return "NEUTRAL", None, swing_low, swing_high, volatility_ratio

        ote_618_bull = swing_high - (diff * 0.618)
        ote_786_bull = swing_high - (diff * 0.786)

        ote_618_bear = swing_low + (diff * 0.618)
        ote_786_bear = swing_low + (diff * 0.786)

        if ote_786_bull <= current_price <= ote_618_bull:
            return "LONG", float((ote_618_bull + ote_786_bull) / 2), swing_low, swing_high, volatility_ratio

        if ote_618_bear <= current_price <= ote_786_bear:
            return "SHORT", float((ote_618_bear + ote_786_bear) / 2), swing_low, swing_high, volatility_ratio

        return "NEUTRAL", None, swing_low, swing_high, volatility_ratio

    @classmethod
    def _detect_strong_confirmation(cls, opens, highs, lows, closes, direction):
        o = np.asarray(opens, dtype=float)
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 5:
            return False, "بيانات غير كافية للتأكيد"

        if direction == 'LONG':
            if c[-1] > o[-1] and c[-1] > c[-2]:
                return True, "تم تأكيد الارتداد بشمعة صاعدة قوية داخل نطاق OTE"
        elif direction == 'SHORT':
            if c[-1] < o[-1] and c[-1] < c[-2]:
                return True, "تم تأكيد الارتداد بشمعة هابطة قوية داخل نطاق OTE"

        return False, "لم يتم تأكيد شمعة الانعكاس بعد"

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
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h[:-1])
        o, h, l, c, v = self.arrays(ohlcv_15m[:-1])

        direction, ote_target, swing_low, swing_high, vol_ratio = self._detect_ict_ote(h, l, c)
        
        if direction == "NEUTRAL":
            d['reasons_excluded'].append("السعر لم يصل لمنطقة OTE أو التذبذب غير مناسب")
            return "NEUTRAL", 30, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        confirmed, conf_msg = self._detect_strong_confirmation(o, h, l, c, direction)
        if not confirmed:
            d['reasons_excluded'].append(conf_msg)
            return "NEUTRAL", 40, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        confirmations = [
            f"معدل تذبذب الموجة مستقر وآمن ({round(vol_ratio * 100, 1)}%)",
            f"تحديد القمة ({swing_high}) والقاع ({swing_low}) بنجاح",
            f"تم تأكيد الارتداد داخل منطقة فيبوناتشي الذهبي OTE (61.8% - 78.6%)",
            conf_msg
        ]

        d['predictive_entry'] = ote_target
        d['ote_zone'] = [swing_low, swing_high]

        score = 95
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

        recent_low = float(np.min(lows[-20:]))
        recent_high = float(np.max(highs[-20:]))
        buffer = 0.5 * atr  # مسافة الأمان لحماية الوقف

        if direction in ('LONG', 'BUY'):
            stop = min(entry - 2.5 * atr, recent_low - buffer)
            risk = entry - stop
            t1, t2, t3 = entry + 2.0 * risk, entry + 3.5 * risk, entry + 5.0 * risk
        else:
            stop = max(entry + 2.5 * atr, recent_high + buffer)
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
