# ==========================================
# MY EXPERT CRYPTO BOT
# BREAKOUT + RETEST + EDGE ALGO + SMC
# File: analysis.py
# Compatible with existing main.py / BingX / Render
# ==========================================

import numpy as np


class StrategyEngine:
    def __init__(self):
        self.min_candles = 20

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str):
            return False

        symbol_upper = symbol.upper()
        blocked = [
            "AAPL", "TSLA", "GOOG", "AMZN", "MSFT",
            "NFLX", "NVDA", "META", "TEST", "DEMO",
            "FAKE", "NCSK"
        ]

        if any(word in symbol_upper for word in blocked):
            return False

        if len(symbol_upper) > 30:
            return False

        return True

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)):
            return False

        if len(data) < minimum:
            return False

        try:
            previous_timestamp = -1

            for candle in data:
                if len(candle) < 6:
                    return False

                timestamp = float(candle[0])
                o, h, l, c, v = map(float, candle[1:6])

                values = [timestamp, o, h, l, c, v]

                if not all(np.isfinite(x) for x in values):
                    return False

                if min(o, h, l, c) <= 0 or v < 0:
                    return False

                if h < max(o, c) or l > min(o, c):
                    return False

                if h < l:
                    return False

                if timestamp <= previous_timestamp:
                    return False

                previous_timestamp = timestamp

            return True

        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        opens = np.array([float(x[1]) for x in data], dtype=float)
        highs = np.array([float(x[2]) for x in data], dtype=float)
        lows = np.array([float(x[3]) for x in data], dtype=float)
        closes = np.array([float(x[4]) for x in data], dtype=float)
        volumes = np.array([max(0.0, float(x[5])) for x in data],
                           dtype=float)

        return opens, highs, lows, closes, volumes

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)

        if len(values) < period:
            return None

        alpha = 2.0 / (period + 1.0)
        result = float(values[0])

        for value in values[1:]:
            result = alpha * float(value) + (1 - alpha) * result

        return result

    @staticmethod
    def calculate_atr(highs, lows, closes, period=14):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        n = min(len(highs), len(lows), len(closes))

        if n < 2:
            return 0.0

        highs = highs[-n:]
        lows = lows[-n:]
        closes = closes[-n:]

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )

        if len(tr) == 0:
            return 0.0

        return float(np.mean(tr[-period:]))

    @classmethod
    def _trend(cls, highs, lows, closes):
        """تحديد الاتجاه من بيانات الفريم نفسه."""
        closes = np.asarray(closes, dtype=float)

        if len(closes) < 20:
            return "NEUTRAL"

        fast = cls._ema(closes[-40:], 5)
        slow = cls._ema(closes[-40:], 20)
        last = float(closes[-1])

        if fast is None or slow is None:
            return "NEUTRAL"

        if fast > slow and last > fast:
            return "LONG"

        if fast < slow and last < fast:
            return "SHORT"

        return "NEUTRAL"

    @staticmethod
    def _volume_ratio(volumes):
        """مقارنة آخر شمعة مغلقة بمتوسط الشموع السابقة."""
        volumes = np.asarray(volumes, dtype=float)

        if len(volumes) < 10:
            return 0.0

        # استبعاد الشمعة الأخيرة من المتوسط المرجعي
        baseline = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]

        if len(baseline) == 0:
            return 0.0

        avg = float(np.mean(baseline))
        latest = float(volumes[-1])

        if avg <= 0:
            return 0.0

        return round(latest / avg, 2)

    @staticmethod
    def _break_retest(opens, highs, lows, closes, volumes, direction):
        """
        اكتشاف اختراق مؤكد أو إعادة اختبار قريبة من المستوى.
        كل البيانات هنا يجب أن تكون لشموع مغلقة.
        """
        n = min(
            len(opens), len(highs), len(lows),
            len(closes), len(volumes)
        )

        if n < 12:
            return False, None, "بيانات غير كافية"

        opens = np.asarray(opens[-n:], dtype=float)
        highs = np.asarray(highs[-n:], dtype=float)
        lows = np.asarray(lows[-n:], dtype=float)
        closes = np.asarray(closes[-n:], dtype=float)

        # الشموع السابقة لتحديد المستوى، دون شمعة الإشارة
        prior_high = float(np.max(highs[-10:-1]))
        prior_low = float(np.min(lows[-10:-1]))

        o = float(opens[-1])
        h = float(highs[-1])
        l = float(lows[-1])
        c = float(closes[-1])

        candle_range = max(h - l, c * 0.0001)
        body_ratio = abs(c - o) / candle_range

        if direction == "LONG":
            if c > prior_high and c > o:
                if body_ratio >= 0.35:
                    return True, prior_high, "BULLISH_BOS: اختراق مقاومة بإغلاق صاعد"

            # إعادة اختبار محتملة، بشرط أن يكون الإغلاق فوق المستوى
            distance = abs(c - prior_high) / prior_high

            if (
                distance <= 0.0025
                and c >= prior_high
                and c > o
            ):
                return True, prior_high, "إعادة اختبار مقاومة مع ارتداد صاعد"

            return False, prior_high, "لا يوجد اختراق أو إعادة اختبار مؤكدة"

        if direction == "SHORT":
            if c < prior_low and c < o:
                if body_ratio >= 0.35:
                    return True, prior_low, "BEARISH_BOS: كسر دعم بإغلاق هابط"

            distance = abs(c - prior_low) / prior_low

            if (
                distance <= 0.0025
                and c <= prior_low
                and c < o
            ):
                return True, prior_low, "إعادة اختبار دعم مع ارتداد هابط"

            return False, prior_low, "لا يوجد كسر أو إعادة اختبار مؤكدة"

        return False, None, "الاتجاه غير واضح"

    @staticmethod
    def _detect_structure(opens, highs, lows, closes):
        """اكتشاف مبسط لـ BOS وMSS وعمليات سحب السيولة."""
        result = {
            "bos": "NONE",
            "mss": "NONE",
            "sweep": "NONE",
            "fvg": "NONE",
            "ob_type": "NONE",
            "ob_zone": None,
            "support": None,
            "resistance": None,
        }

        n = min(len(opens), len(highs), len(lows), len(closes))

        if n < 12:
            return result

        o = np.asarray(opens[-n:], dtype=float)
        h = np.asarray(highs[-n:], dtype=float)
        l = np.asarray(lows[-n:], dtype=float)
        c = np.asarray(closes[-n:], dtype=float)

        # مستويات الهيكل السابق
        prior_high = float(np.max(h[-11:-2]))
        prior_low = float(np.min(l[-11:-2]))

        last_o = float(o[-1])
        last_h = float(h[-1])
        last_l = float(l[-1])
        last_c = float(c[-1])

        result["support"] = prior_low
        result["resistance"] = prior_high

        if last_c > prior_high and last_c > last_o:
            result["bos"] = "BULLISH_BOS"

        elif last_c < prior_low and last_c < last_o:
            result["bos"] = "BEARISH_BOS"

        # سحب السيولة: تجاوز مستوى سابق ثم إغلاق داخله
        if last_l < prior_low and last_c > prior_low:
            result["sweep"] = "SELL_SIDE_SWEEP"

        elif last_h > prior_high and last_c < prior_high:
            result["sweep"] = "BUY_SIDE_SWEEP"

        # FVG: فجوة بين الشمعة الحالية والشمعة التي سبقتها
        if n >= 3:
            if l[-1] > h[-3]:
                result["fvg"] = "BULLISH_FVG"

            elif h[-1] < l[-3]:
                result["fvg"] = "BEARISH_FVG"

        # MSS مبسط: انعكاس الاتجاه المحلي السابق
        previous_direction = "NEUTRAL"

        if c[-2] > c[-6]:
            previous_direction = "LONG"
        elif c[-2] < c[-6]:
            previous_direction = "SHORT"

        if (
            previous_direction == "SHORT"
            and result["bos"] == "BULLISH_BOS"
        ):
            result["mss"] = "BULLISH_MSS"

        elif (
            previous_direction == "LONG"
            and result["bos"] == "BEARISH_BOS"
        ):
            result["mss"] = "BEARISH_MSS"

        # نطاق تقريبي للشمعة المعاكسة قبل اندفاع سعري
        if n >= 4:
            atr = float(np.mean((h[-14:] - l[-14:]))) if n >= 14 else float(np.mean(h - l))
            candle_move = abs(c[-1] - c[-2])

            if atr > 0 and candle_move >= 1.2 * atr:
                for j in range(n - 2, max(-1, n - 7), -1):
                    if result["bos"] == "BULLISH_BOS" and c[j] < o[j]:
                        result["ob_type"] = "BULLISH_OB"
                        result["ob_zone"] = [
                            float(l[j]), float(h[j])
                        ]
                        break

                    if result["bos"] == "BEARISH_BOS" and c[j] > o[j]:
                        result["ob_type"] = "BEARISH_OB"
                        result["ob_zone"] = [
                            float(l[j]), float(h[j])
                        ]
                        break

        return result

    def _storm101_whale_check(
        self, opens, highs, lows, closes, volumes, direction
    ):
        """
        فحص نشاط حجم التداول واتساع الشمعة.
        لا يثبت وجود حيتان؛ يعتمد على OHLCV فقط.
        """
        ratio = self._volume_ratio(volumes)

        if len(closes) < 10:
            return False, "بيانات غير كافية لفحص النشاط"

        candle_range = float(highs[-1] - lows[-1])
        body = abs(float(closes[-1] - opens[-1]))
        body_ratio = body / max(candle_range, 1e-12)

        if ratio >= 1.5 and body_ratio >= 0.45:
            return True, "نشاط تداول مرتفع مع شمعة ذات جسم واضح"

        if ratio >= 1.25:
            return True, "حجم التداول أعلى من المتوسط"

        return False, "حجم التداول لا يقدم تأكيدًا كافيًا"

    def analyze_multi_timeframe(
        self,
        ohlcv_4h,
        ohlcv_1h,
        ohlcv_15m,
        ohlcv_btc_1h=None,
        symbol=""
    ):
        details = {
            "trend_4h": "NEUTRAL",
            "trend_1h": "NEUTRAL",
            "break_retest": False,
            "break_level": None,
            "bos": "NONE",
            "mss": "NONE",
            "sweep": "NONE",
            "fvg": "NONE",
            "ob_type": "NONE",
            "ob_zone": None,
            "volume_ratio": 0.0,
            "vwap_price": 0.0,
            "support": None,
            "resistance": None,
            "retest_advice": "انتظار تأكيد فعلي",
            "entry_valid": False,
            "btc_trend": "UNKNOWN",
            "confirmations": [],
            "reasons_excluded": [],
        }

        empty_arrays = ([], [], [])

        if symbol and not self.is_valid_symbol(symbol):
            details["reasons_excluded"].append(
                f"رمز غير صالح: {symbol}"
            )
            return "NEUTRAL", 0, 0.0, details, empty_arrays

        for label, data in (
            ("4H", ohlcv_4h),
            ("1H", ohlcv_1h),
            ("15M", ohlcv_15m),
        ):
            if not self.valid_ohlcv(data, 20):
                details["reasons_excluded"].append(
                    f"بيانات {label} غير كافية أو غير صالحة"
                )
                return "NEUTRAL", 0, 0.0, details, empty_arrays

        # استبعاد آخر شمعة لأنها قد تكون قيد التكوين
        d4 = ohlcv_4h[:-1]
        d1 = ohlcv_1h[:-1]
        d15 = ohlcv_15m[:-1]

        o4, h4, l4, c4, v4 = self.arrays(d4)
        o1, h1, l1, c1, v1 = self.arrays(d1)
        o15, h15, l15, c15, v15 = self.arrays(d15)

        trend4 = self._trend(h4, l4, c4)
        trend1 = self._trend(h1, l1, c1)

        details["trend_4h"] = trend4
        details["trend_1h"] = trend1

        btc_trend = "UNKNOWN"

        if self.valid_ohlcv(ohlcv_btc_1h, 20):
            btc_closed = ohlcv_btc_1h[:-1]
            _, bh, bl, bc, _ = self.arrays(btc_closed)
            btc_trend = self._trend(bh, bl, bc)

        details["btc_trend"] = btc_trend

        volume_ratio = self._volume_ratio(v15)
        details["volume_ratio"] = volume_ratio

        structure = self._detect_structure(o15, h15, l15, c15)
        details.update(structure)

        confirmations = []
        excluded = []

        # نحتاج إلى اتجاه واضح على فريم الساعة
        direction = trend1

        if direction not in ("LONG", "SHORT"):
            excluded.append("اتجاه الساعة غير واضح")
            details["reasons_excluded"] = excluded
            return "NEUTRAL", 0, volume_ratio, details, (
                h1.tolist(), l1.tolist(), c1.tolist()
            )

        # لا ندخل عكس اتجاه الأربع ساعات
        if trend4 != direction:
            excluded.append(
                "اتجاه 4H لا يؤكد اتجاه 1H"
            )
            details["reasons_excluded"] = excluded
            return "NEUTRAL", 0, volume_ratio, details, (
                h1.tolist(), l1.tolist(), c1.tolist()
            )

        confirmations.append("اتجاه 4H و1H متوافق")

        br_ok, br_level, br_reason = self._break_retest(
            o15, h15, l15, c15, v15, direction
        )

        details["break_retest"] = br_ok
        details["break_level"] = br_level
        details["retest_advice"] = br_reason

        expected_bos = (
            "BULLISH_BOS" if direction == "LONG"
            else "BEARISH_BOS"
        )

        if details["bos"] == expected_bos:
            confirmations.append("تأكيد كسر هيكل السوق BOS")
        else:
            excluded.append("لا يوجد BOS مؤكد على 15M")

        if not br_ok:
            excluded.append(br_reason)

        if volume_ratio >= 1.25:
            confirmations.append(
                f"حجم التداول أعلى من المتوسط ({volume_ratio}x)"
            )
        else:
            excluded.append(
                f"حجم التداول ضعيف نسبيًا ({volume_ratio}x)"
            )

        # زخم آخر الشموع المغلقة
        momentum = False

        if len(c15) >= 5:
            if direction == "LONG":
                momentum = (
                    c15[-1] > c15[-2]
                    and c15[-1] > c15[-4]
                )
            else:
                momentum = (
                    c15[-1] < c15[-2]
                    and c15[-1] < c15[-4]
                )

        if momentum:
            confirmations.append("الزخم يؤيد اتجاه الصفقة")
        else:
            excluded.append("الزخم الحالي غير مؤكد")

        # توافق BTC عامل مساعد وليس إثباتًا لاتجاه العملة
        btc_aligned = btc_trend == direction

        if btc_aligned:
            confirmations.append("اتجاه BTC متوافق")
        elif btc_trend in ("LONG", "SHORT"):
            excluded.append("اتجاه BTC غير متوافق")
        else:
            excluded.append("تعذر تحديد اتجاه BTC")

        storm_ok, storm_reason = self._storm101_whale_check(
            o15, h15, l15, c15, v15, direction
        )

        if storm_ok:
            confirmations.append(storm_reason)
        else:
            excluded.append(storm_reason)

        # درجة محسوبة من شروط محددة، وليست رقمًا ثابتًا.
        score = 0
        score += 20  # توافق 4H و1H
        score += 25 if details["bos"] == expected_bos else 0
        score += 20 if br_ok else 0
        score += 15 if volume_ratio >= 1.25 else 0
        score += 10 if momentum else 0
        score += 5 if btc_aligned else 0
        score += 5 if storm_ok else 0
        score = min(100, score)

        # لا تُرسل إشارة إذا غاب الاختراق الحقيقي أو الفوليوم
        entry_valid = (
            br_ok
            and details["bos"] == expected_bos
            and volume_ratio >= 1.25
            and momentum
            and len(confirmations) >= 4
        )

        if not entry_valid:
            excluded.append(
                "شروط الدخول الكاملة غير متحققة؛ لا توجد إشارة تنفيذ"
            )

        details["entry_valid"] = bool(entry_valid)
        details["confirmations"] = confirmations
        details["reasons_excluded"] = excluded

        signal = direction if entry_valid else "NEUTRAL"

        return signal, score, volume_ratio, details, (
            h1.tolist(), l1.tolist(), c1.tolist()
        )

    def calculate_risk_management(
        self, entry_price, direction, highs, lows, closes=None
    ):
        entry = float(entry_price)
        direction = str(direction).upper()

        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)

        if closes is None:
            closes = (highs + lows) / 2.0

        closes = np.asarray(closes, dtype=float)

        n = min(len(highs), len(lows), len(closes))

        if not np.isfinite(entry) or entry <= 0 or n < 5:
            raise ValueError("Invalid entry price or insufficient candles")

        highs = highs[-n:]
        lows = lows[-n:]
        closes = closes[-n:]

        if not (
            np.all(np.isfinite(highs))
            and np.all(np.isfinite(lows))
            and np.all(np.isfinite(closes))
        ):
            raise ValueError("Invalid OHLC values")

        atr = self.calculate_atr(highs, lows, closes)

        if not np.isfinite(atr) or atr <= 0:
            atr = entry * 0.01

        # تجنب وقف شديد الضيق أو غير متناسب مع السعر
        risk_distance = max(1.5 * atr, entry * 0.005)

        if direction in ("LONG", "BUY"):
            stop = entry - risk_distance
            risk = entry - stop

            tp1 = entry + 1.5 * risk
            tp2 = entry + 2.5 * risk
            tp3 = entry + 4.0 * risk

        elif direction in ("SHORT", "SELL"):
            stop = entry + risk_distance
            risk = stop - entry

            tp1 = entry - 1.5 * risk
            tp2 = entry - 2.5 * risk
            tp3 = entry - 4.0 * risk

            if tp3 <= 0:
                raise ValueError(
                    "Calculated short target is non-positive"
                )

        else:
            raise ValueError("Direction must be LONG or SHORT")

        sl_pct = abs(entry - stop) / entry * 100
        tp1_pct = abs(tp1 - entry) / entry * 100
        rr = (tp1 - entry) / risk if direction in (
            "LONG", "BUY"
        ) else (entry - tp1) / risk

        return (
            round(float(stop), 10),
            round(float(tp1), 10),
            round(float(tp2), 10),
            round(float(tp3), 10),
            round(float(sl_pct), 3),
            round(float(tp1_pct), 3),
            round(float(rr), 2),
        )
