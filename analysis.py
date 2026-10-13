# ==========================================
# MY EXPERT CRYPTO BOT - STRATEGY ENGINE
# BREAKOUT + RETEST + EDGE ALGO + SMC + PRICE CHASING FILTER + STRICT WARNING FILTER
# ==========================================

import numpy as np


class StrategyEngine:
    """OHLCV-only multi-timeframe strategy with price chasing protection and strict warning filters."""

    def __init__(self):
        self.min_candles = 20

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str) or len(symbol) > 30:
            return False
        s = symbol.upper()
        blocked = ("AAPL", "TSLA", "GOOG", "AMZN", "MSFT", "NFLX", "NVDA",
                   "META", "TEST", "DEMO", "FAKE", "NCSK")
        return not any(word in s for word in blocked)

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            prev_ts = -1.0
            for candle in data:
                if len(candle) < 6:
                    return False
                ts, o, h, l, c, v = map(float, candle[:6])
                if not all(np.isfinite(x) for x in (ts, o, h, l, c, v)):
                    return False
                if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l:
                    return False
                if ts <= prev_ts:
                    return False
                prev_ts = ts
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        return tuple(np.asarray([float(x[i]) for x in data], dtype=float) for i in (1, 2, 3, 4, 5))

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1.0)
        result = float(values[0])
        for value in values[1:]:
            result = alpha * float(value) + (1.0 - alpha) * result
        return result

    @staticmethod
    def calculate_atr(highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        tr = tr[np.isfinite(tr)]
        return float(np.mean(tr[-max(1, int(period)):])) if len(tr) else 0.0

    @classmethod
    def _trend(cls, highs, lows, closes):
        c = np.asarray(closes, dtype=float)
        if len(c) < 20:
            return "NEUTRAL"
        fast, slow = cls._ema(c[-min(40, len(c)):], 8), cls._ema(c[-min(60, len(c)):], 21)
        atr = cls.calculate_atr(highs, lows, c)
        if fast is None or slow is None or atr <= 0:
            return "NEUTRAL"
        if fast > slow and c[-1] > fast and (fast - slow) / c[-1] >= 0.0005:
            return "LONG"
        if fast < slow and c[-1] < fast and (slow - fast) / c[-1] >= 0.0005:
            return "SHORT"
        return "NEUTRAL"

    @staticmethod
    def _volume_ratio(volumes):
        v = np.asarray(volumes, dtype=float)
        if len(v) < 10:
            return 0.0
        baseline = v[-21:-1] if len(v) >= 21 else v[:-1]
        avg = float(np.mean(baseline)) if len(baseline) else 0.0
        return round(float(v[-1] / avg), 2) if avg > 0 else 0.0

    @classmethod
    def _detect_structure(cls, opens, highs, lows, closes):
        o, h, l, c = (np.asarray(x, dtype=float) for x in (opens, highs, lows, closes))
        n = min(map(len, (o, h, l, c)))
        out = {"bos": "NONE", "mss": "NONE", "sweep": "NONE", "fvg": "NONE",
               "fvg_zone": None, "ob_type": "NONE", "ob_zone": None,
               "support": None, "resistance": None}
        if n < 12:
            return out
        o, h, l, c = o[-n:], h[-n:], l[-n:], c[-n:]
        lookback = min(12, n - 2)
        prior_high = float(np.max(h[-lookback-1:-1]))
        prior_low = float(np.min(l[-lookback-1:-1]))
        out["support"], out["resistance"] = prior_low, prior_high
        last_range = max(float(h[-1] - l[-1]), float(c[-1]) * 1e-9)
        body_ratio = abs(float(c[-1] - o[-1])) / last_range
        if c[-1] > prior_high and c[-1] > o[-1] and body_ratio >= 0.35:
            out["bos"] = "BULLISH_BOS"
        elif c[-1] < prior_low and c[-1] < o[-1] and body_ratio >= 0.35:
            out["bos"] = "BEARISH_BOS"
        if l[-1] < prior_low and c[-1] > prior_low:
            out["sweep"] = "SELL_SIDE_SWEEP"
        elif h[-1] > prior_high and c[-1] < prior_high:
            out["sweep"] = "BUY_SIDE_SWEEP"
        if l[-1] > h[-3] and (l[-1] - h[-3]) / c[-1] >= 0.0003:
            out["fvg"] = "BULLISH_FVG"
            out["fvg_zone"] = [float(h[-3]), float(l[-1])]
        elif h[-1] < l[-3] and (l[-3] - h[-1]) / c[-1] >= 0.0003:
            out["fvg"] = "BEARISH_FVG"
            out["fvg_zone"] = [float(h[-1]), float(l[-3])]
        prev_move = float(c[-3] - c[-7])
        if prev_move < 0 and out["bos"] == "BULLISH_BOS":
            out["mss"] = "BULLISH_MSS"
        elif prev_move > 0 and out["bos"] == "BEARISH_BOS":
            out["mss"] = "BEARISH_MSS"
        atr = cls.calculate_atr(h, l, c)
        displacement = abs(float(c[-1] - o[-1])) >= 1.15 * atr if atr > 0 else False
        if displacement and out["bos"] != "NONE":
            for j in range(n - 2, max(-1, n - 7), -1):
                if out["bos"] == "BULLISH_BOS" and c[j] < o[j]:
                    out["ob_type"], out["ob_zone"] = "BULLISH_OB", [float(l[j]), float(h[j])]
                    break
                if out["bos"] == "BEARISH_BOS" and c[j] > o[j]:
                    out["ob_type"], out["ob_zone"] = "BEARISH_OB", [float(l[j]), float(h[j])]
                    break
        return out

    @classmethod
    def _break_retest(cls, opens, highs, lows, closes, volumes, direction, current_price=None):
        """Detect breakout/retest with live price chasing protection and strict candle quality filters."""
        o, h, l, c, v = (np.asarray(x, dtype=float) for x in (opens, highs, lows, closes, volumes))
        n = min(map(len, (o, h, l, c, v)))
        if n < 15:
            return False, None, "بيانات غير كافية لاكتشاف الكسر وإعادة الاختبار"
        o, h, l, c, v = (x[-n:] for x in (o, h, l, c, v))
        atr = cls.calculate_atr(h, l, c)
        tolerance = max((atr / max(c[-1], 1e-12)) * 0.25 if atr > 0 else 0, 0.0020)
        lookback = min(10, n - 7)
        level_high = float(np.max(h[-lookback-1:-1]))
        level_low = float(np.min(l[-lookback-1:-1]))
        
        last_open, last_close = float(o[-1]), float(c[-1])
        last_high, last_low = float(h[-1]), float(l[-1])
        candle_total_range = max(last_high - last_low, 1e-12)
        body_size = abs(last_close - last_open)
        body_ratio = body_size / candle_total_range
        
        upper_wick = last_high - max(last_open, last_close)
        lower_wick = min(last_open, last_close) - last_low
        
        if direction == "LONG" and upper_wick > body_size * 0.8:
            return False, level_high, "شمعة الاختراق بها ذيل علوي كبير (رفض السعر / فيك أوت)"
        if direction == "SHORT" and lower_wick > body_size * 0.8:
            return False, level_low, "شمعة الكسر بها ذيل سفلي كبير (رفض السعر / فيك أوت)"

        base_level = level_high if direction == "LONG" else level_low

        if current_price is not None and current_price > 0:
            curr = float(current_price)
            if direction == "LONG" and curr > base_level:
                if (curr - base_level) / base_level > 0.015:
                    return False, base_level, "السعر الحالي ابتعد كثيراً عن مستوى الكسر (تجنب المطاردة)"
            elif direction == "SHORT" and curr < base_level:
                if (base_level - curr) / base_level > 0.015:
                    return False, base_level, "السعر الحالي ابتعد كثيراً عن مستوى الكسر (تجنب المطاردة)"

        if direction == "LONG":
            fresh = c[-1] > level_high and c[-1] > o[-1] and body_ratio >= 0.40
            extension = (c[-1] - level_high) / max(atr, c[-1] * 1e-9)
            if fresh and extension <= 1.6:
                return True, level_high, "اختراق صاعد حديث بإغلاق قوي؛ الامتداد ضمن الحد"
            if extension > 1.6:
                return False, level_high, "السعر ممتد بعد الاختراق؛ تجنب مطاردة الحركة"

            first_j = max(2, n - 6)
            for j in range(n - 2, first_j - 1, -1):
                left = max(0, j - 10)
                if j - left < 5:
                    continue
                old_level = float(np.max(h[left:j]))
                broke = c[j] > old_level and c[j] > o[j]
                if not broke:
                    continue
                retest_now = (l[-1] <= old_level * (1 + tolerance)
                              and c[-1] >= old_level
                              and c[-1] > o[-1]
                              and (old_level - l[-1]) / max(old_level, 1e-12) <= 0.012)
                if retest_now:
                    return True, old_level, "إعادة اختبار ناجحة لمستوى اختراق سابق"
            return False, level_high, "لا يوجد اختراق حديث أو إعادة اختبار مؤكدة"

        if direction == "SHORT":
            fresh = c[-1] < level_low and c[-1] < o[-1] and body_ratio >= 0.40
            extension = (level_low - c[-1]) / max(atr, c[-1] * 1e-9)
            if fresh and extension <= 1.6:
                return True, level_low, "كسر هابط حديث بإغلاق قوي؛ الامتداد ضمن الحد"
            if extension > 1.6:
                return False, level_low, "السعر ممتد بعد الكسر؛ تجنب مطاردة الحركة"

            first_j = max(2, n - 6)
            for j in range(n - 2, first_j - 1, -1):
                left = max(0, j - 10)
                if j - left < 5:
                    continue
                old_level = float(np.min(l[left:j]))
                broke = c[j] < old_level and c[j] < o[j]
                if not broke:
                    continue
                retest_now = (h[-1] >= old_level * (1 - tolerance)
                              and c[-1] <= old_level
                              and c[-1] < o[-1]
                              and (h[-1] - old_level) / max(old_level, 1e-12) <= 0.012)
                if retest_now:
                    return True, old_level, "إعادة اختبار ناجحة لمستوى كسر سابق"
            return False, level_low, "لا يوجد كسر حديث أو إعادة اختبار مؤكدة"
        return False, None, "الاتجاه غير واضح"

    def _storm101_whale_check(self, opens, highs, lows, closes, volumes, direction):
        ratio = self._volume_ratio(volumes)
        if len(closes) < 10:
            return False, "بيانات غير كافية لفحص الحجم والزخم"
        candle_range = max(float(highs[-1] - lows[-1]), 1e-12)
        body_ratio = abs(float(closes[-1] - opens[-1])) / candle_range
        aligned = closes[-1] > opens[-1] if direction == "LONG" else closes[-1] < opens[-1]
        if ratio >= 1.5 and body_ratio >= 0.45 and aligned:
            return True, "حجم مرتفع مع شمعة اندفاع متوافقة"
        if ratio >= 1.25 and aligned and body_ratio >= 0.35:
            return True, "حجم أعلى من المتوسط مع إغلاق متوافق"
        return False, "الحجم أو جسم الشمعة لا يقدم تأكيدًا كافيًا"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m,
                                ohlcv_btc_1h=None, symbol="", current_price=None):
        details = {
            "trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL", "break_retest": False,
            "break_level": None, "bos": "NONE", "mss": "NONE", "sweep": "NONE",
            "fvg": "NONE", "fvg_zone": None, "ob_type": "NONE", "ob_zone": None,
            "volume_ratio": 0.0, "vwap_price": 0.0, "support": None, "resistance": None,
            "retest_advice": "انتظار تأكيد فعلي", "entry_valid": False, "btc_trend": "UNKNOWN",
            "confirmations": [], "reasons_excluded": [], "momentum": False,
        }
        empty = ([], [], [])
        if symbol and not self.is_valid_symbol(symbol):
            details["reasons_excluded"] = [f"رمز غير صالح: {symbol}"]
            return "NEUTRAL", 0, 0.0, details, empty
        for label, data in (("4H", ohlcv_4h), ("1H", ohlcv_1h), ("15M", ohlcv_15m)):
            if not self.valid_ohlcv(data, 20):
                details["reasons_excluded"].append(f"بيانات {label} غير كافية أو غير صالحة")
                return "NEUTRAL", 0, 0.0, details, empty
        d4, d1, d15 = ohlcv_4h[:-1], ohlcv_1h[:-1], ohlcv_15m[:-1]
        o4, h4, l4, c4, v4 = self.arrays(d4)
        o1, h1, l1, c1, v1 = self.arrays(d1)
        o15, h15, l15, c15, v15 = self.arrays(d15)
        trend4, trend1 = self._trend(h4, l4, c4), self._trend(h1, l1, c1)
        details["trend_4h"], details["trend_1h"] = trend4, trend1
        if self.valid_ohlcv(ohlcv_btc_1h, 20):
            _, bh, bl, bc, _ = self.arrays(ohlcv_btc_1h[:-1])
            details["btc_trend"] = self._trend(bh, bl, bc)
        volume_ratio = self._volume_ratio(v15)
        details["volume_ratio"] = volume_ratio
        details.update(self._detect_structure(o15, h15, l15, c15))
        confirmations, excluded = [], []
        direction = trend1
        if direction not in ("LONG", "SHORT"):
            details["reasons_excluded"] = ["اتجاه الساعة غير واضح"]
            return "NEUTRAL", 0, volume_ratio, details, (h1.tolist(), l1.tolist(), c1.tolist())
        if trend4 != direction:
            details["reasons_excluded"] = ["اتجاه 4H لا يؤكد اتجاه 1H"]
            return "NEUTRAL", 0, volume_ratio, details, (h1.tolist(), l1.tolist(), c1.tolist())
        details["candidate_direction"] = direction
        confirmations.append("توافق الاتجاه على 4H و1H")
        
        br_ok, br_level, br_reason = self._break_retest(o15, h15, l15, c15, v15, direction, current_price=current_price)
        details["break_retest"], details["break_level"], details["retest_advice"] = br_ok, br_level, br_reason
        details["retest_bos_valid"] = bool(br_ok and br_reason.startswith("إعادة اختبار ناجحة"))
        expected_bos = "BULLISH_BOS" if direction == "LONG" else "BEARISH_BOS"
        structure_ok = details["bos"] == expected_bos or details["retest_bos_valid"]
        if details["bos"] == expected_bos:
            confirmations.append("BOS يؤكد الاتجاه على 15M")
        elif details["retest_bos_valid"]:
            confirmations.append("كسر هيكلي سابق ثم إعادة اختبار مؤكدة")
        else:
            excluded.append("لا يوجد BOS حديث أو كسر سابق أعقبه إعادة اختبار")
        if details["mss"] in (("BULLISH_MSS" if direction == "LONG" else "BEARISH_MSS"),):
            confirmations.append("MSS يؤيد التحول الهيكلي")
        if details["sweep"] == ("SELL_SIDE_SWEEP" if direction == "LONG" else "BUY_SIDE_SWEEP"):
            confirmations.append("سحب سيولة متوافق مع الاتجاه")
        if not br_ok:
            excluded.append(br_reason)
        if volume_ratio >= 1.15:
            confirmations.append(f"حجم تداول مرتفع نسبيًا ({volume_ratio}x)")
        else:
            excluded.append(f"حجم التداول دون حد التأكيد ({volume_ratio}x)")
        momentum = False
        if len(c15) >= 5:
            momentum = (c15[-1] > c15[-2] and c15[-1] > c15[-4]) if direction == "LONG" else (c15[-1] < c15[-2] and c15[-1] < c15[-4])
            last_range = max(float(h15[-1] - l15[-1]), float(c15[-1]) * 1e-9)
            last_body = abs(float(c15[-1] - o15[-1])) / last_range
            candle_aligned = c15[-1] > o15[-1] if direction == "LONG" else c15[-1] < o15[-1]
            if br_ok and details["retest_bos_valid"] and candle_aligned and last_body >= 0.30:
                momentum = True
        details["momentum"] = momentum
        if momentum:
            confirmations.append("الزخم قصير المدى متوافق")
        else:
            excluded.append("الزخم قصير المدى غير مؤكد")
        btc = details["btc_trend"]
        btc_aligned = btc == direction
        if btc_aligned:
            confirmations.append("اتجاه BTC متوافق")
        elif btc in ("LONG", "SHORT"):
            excluded.append("اتجاه BTC معاكس أو غير متوافق")
        else:
            excluded.append("تعذر تحديد اتجاه BTC")
        activity_ok, activity_reason = self._storm101_whale_check(o15, h15, l15, c15, v15, direction)
        if activity_ok:
            confirmations.append(activity_reason)
        else:
            excluded.append(activity_reason)
        score = 20
        score += 20 if structure_ok else 0
        score += 15 if br_ok else 0
        score += 10 if volume_ratio >= 1.15 else 0
        score += 10 if momentum else 0
        score += 5 if btc_aligned else 0
        score += 5 if details["mss"] != "NONE" else 0
        score += 5 if details["sweep"] != "NONE" else 0
        score += 5 if details["fvg"] != "NONE" else 0
        score += 5 if details["ob_zone"] is not None else 0
        if not br_ok or not structure_ok or volume_ratio < 1.15 or not momentum:
            score = min(score, 69)
        elif len(confirmations) < 3:
            score = min(score, 74)
            
        # شرط صارم جداً: منع الموافقة إذا وُجدت أي ملاحظة أو تحذير فني سلبي
        has_warnings = len(excluded) > 0 and not any("إعادة اختبار" in x for x in confirmations)
        
        entry_valid = bool(
            br_ok 
            and structure_ok 
            and volume_ratio >= 1.15 
            and momentum 
            and len(confirmations) >= 3 
            and not has_warnings
        )
        
        if not entry_valid and "شروط التنفيذ الكاملة غير متحققة؛ لا توجد إشارة تنفيذ" not in excluded:
            excluded.append("شروط التنفيذ الكاملة غير متحققة أو توجد تحذيرات فنية؛ لا توجد إشارة تنفيذ")
            
        details["entry_valid"] = entry_valid
        details["confirmations"] = confirmations
        details["reasons_excluded"] = excluded
        details["candidate_direction"] = direction
        return (direction if entry_valid else "NEUTRAL"), score, volume_ratio, details, (h1.tolist(), l1.tolist(), c1.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs, lows = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float)
        if closes is None:
            closes = (highs + lows) / 2.0
        closes = np.asarray(closes, dtype=float)
        n = min(len(highs), len(lows), len(closes))
        if not np.isfinite(entry) or entry <= 0 or n < 5:
            raise ValueError("Invalid entry price or insufficient candles")
        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        if not (np.all(np.isfinite(highs)) and np.all(np.isfinite(lows)) and np.all(np.isfinite(closes))):
            raise ValueError("Invalid OHLC values")
        if np.any(highs <= 0) or np.any(lows <= 0) or np.any(highs < lows):
            raise ValueError("Invalid high/low values")
        atr = self.calculate_atr(highs, lows, closes)
        if not np.isfinite(atr) or atr <= 0:
            atr = entry * 0.01
        recent_low = float(np.min(lows[-10:]))
        recent_high = float(np.max(highs[-10:]))
        if direction in ("LONG", "BUY"):
            structural_stop = recent_low - 0.15 * atr
            stop = min(entry - 1.2 * atr, structural_stop) if structural_stop < entry else entry - 1.5 * atr
            risk = entry - stop
            if risk <= 0:
                raise ValueError("Invalid long stop distance")
            tp1, tp2, tp3 = entry + 1.5*risk, entry + 2.5*risk, entry + 4.0*risk
        elif direction in ("SHORT", "SELL"):
            structural_stop = recent_high + 0.15 * atr
            stop = max(entry + 1.2 * atr, structural_stop) if structural_stop > entry else entry + 1.5 * atr
            risk = stop - entry
            if risk <= 0:
                raise ValueError("Invalid short stop distance")
            tp1, tp2, tp3 = entry - 1.5*risk, entry - 2.5*risk, entry - 4.0*risk
            if tp3 <= 0:
                raise ValueError("Calculated short target is non-positive")
        else:
            raise ValueError("Direction must be LONG or SHORT")
        sl_pct = abs(entry-stop)/entry*100.0
        tp1_pct = abs(tp1-entry)/entry*100.0
        rr = abs(tp1-entry)/abs(entry-stop)
        return (round(float(stop), 10), round(float(tp1), 10), round(float(tp2), 10),
                round(float(tp3), 10), round(float(sl_pct), 3), round(float(tp1_pct), 3), round(float(rr), 2))
