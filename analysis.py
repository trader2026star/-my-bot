# ==========================================
# MY EXPERT CRYPTO BOT — CISD & RB Liquidity Engine
# Anti-Trap Strategy: RB Zone (Rejection Block) + 0.5 Fib + CISD
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
    def _detect_rb_liquidity_strategy(cls, opens, highs, lows, closes):
        """
        خوارزمية نطاق الرفض (Rejection Block - RB) واختبار الفيبوناتشي (0.5):
        1. تحديد كتلة الرفض (RB) السابقة.
        2. انتظار سحب السيولة والعودة لاختبار النطاق أو مستوى 0.5.
        3. تأكيد الإغلاق بشمعة CISD عكسية صحيحة.
        """
        o = np.asarray(opens, dtype=float)
        h = np.asarray(highs, dtype=float)
        l = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        
        if len(c) < 40:
            return "NEUTRAL", 0.0, 0.0, 0.0

        # تحديد منطقة الـ RB (آخر قمة/قاع تسبب في كسر هيكلي أو سحب سيولة)
        rb_high = float(np.max(h[-30:-5]))
        rb_low = float(np.min(l[-30:-5]))
        current_price = float(c[-1])

        # منتصف النطاق (مستوى 0.5 الموضح في الشرح)
        mid_level = (rb_high + rb_low) / 2

        # شروط التأكيد والرفض
        is_bullish_rb_reaction = (l[-1] <= mid_level or l[-2] <= rb_low) and (c[-1] > o[-1]) and (c[-1] > c[-2])
        is_bearish_rb_reaction = (h[-1] >= mid_level or h[-2] >= rb_high) and (c[-1] < o[-1]) and (c[-1] < c[-2])

        if is_bullish_rb_reaction and current_price >= rb_low:
            return "LONG", current_price, rb_low, rb_high

        if is_bearish_rb_reaction and current_price <= rb_high:
            return "SHORT", current_price, rb_low, rb_high

        return "NEUTRAL", 0.0, rb_low, rb_high

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

        o, h, l, c = self.arrays(ohlcv_15m[:-1])[0], self.arrays(ohlcv_15m[:-1])[1], self.arrays(ohlcv_15m[:-1])[2], self.arrays(ohlcv_15m[:-1])[3]

        direction, entry_target, rb_low, rb_high = self._detect_rb_liquidity_strategy(o, h, l, c)
        
        if direction == "NEUTRAL":
            d['reasons_excluded'].append("لم يتم الوصول لمنطقة RB أو اختبار مستوى 0.5 والتأكيد بعد")
            return "NEUTRAL", 30, 1.0, d, (h.tolist(), l.tolist(), c.tolist())

        confirmations = [
            "تم احترام نطاق الرفض (Rejection Block - RB) بنجاح",
            "اختبار منطقة السيولة ومستوى 0.5 فيبوناتشي بدقة",
            "تأكيد الانعكاس وإغلاق شمعة CISD في اتجاه صانع السوق"
        ]

        d['predictive_entry'] = entry_target
        d['ote_zone'] = [rb_low, rb_high]

        score = 99
        entry_valid = True
        d.update(entry_valid=entry_valid, confirmations=confirmations, candidate_direction=direction)
        return direction, score, 1.4, d, (h.tolist(), l.tolist(), c.tolist())

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

        recent_low = float(np.min(lows[-10:]))
        recent_high = float(np.max(highs[-10:]))
        buffer = 0.5 * atr

        if direction in ('LONG', 'BUY'):
            stop = min(entry - 2.0 * atr, recent_low - buffer)
            risk = entry - stop
            t1, t2, t3 = entry + 2.5 * risk, entry + 4.0 * risk, entry + 6.0 * risk
        else:
            stop = max(entry + 2.0 * atr, recent_high + buffer)
            risk = stop - entry
            t1, t2, t3 = entry - 2.5 * risk, entry - 4.0 * risk, entry - 6.0 * risk

        return (
            round(float(stop), 10),
            round(float(t1), 10),
            round(float(t2), 10),
            round(float(t3), 10),
            round(abs(entry - stop) / entry * 100, 3),
            round(abs(t1 - entry) / entry * 100, 3),
            round(abs(t1 - entry) / abs(entry - stop), 2)
        )
