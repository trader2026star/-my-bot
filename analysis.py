# ================================================================
# MY EXPERT CRYPTO BOT — SMART MONEY / LIQUIDITY ENGINE
# OHLCV-based implementation inspired by public SAUDI PRO feature themes.
# This does NOT reproduce private/proprietary SAUDI PRO algorithms.
# ================================================================

import numpy as np


class StrategyEngine:
    """Multi-timeframe OHLCV analysis. Heuristic signals; no profit guarantee."""

    def __init__(self):
        self.min_candles = 20

    @staticmethod
    def is_valid_symbol(symbol):
        if not symbol or not isinstance(symbol, str) or len(symbol) > 40:
            return False
        s = symbol.upper()
        blocked = ("AAPL", "TSLA", "GOOG", "AMZN", "MSFT", "NFLX", "NVDA", "META", "TEST", "DEMO", "FAKE", "NCSK")
        return not any(word in s for word in blocked)

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            previous_ts = -1.0
            for candle in data:
                if len(candle) < 6:
                    return False
                ts, o, h, low, close, volume = map(float, candle[:6])
                if not all(np.isfinite(x) for x in (ts, o, h, low, close, volume)):
                    return False
                if min(o, h, low, close) <= 0 or volume < 0 or h < max(o, close) or low > min(o, close) or h < low:
                    return False
                if ts <= previous_ts:
                    return False
                previous_ts = ts
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        # returns opens, highs, lows, closes, volumes
        return tuple(np.asarray([float(row[i]) for row in data], dtype=float) for i in (1, 2, 3, 4, 5))

    @staticmethod
    def _ema_series(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period or period < 1:
            return np.asarray([], dtype=float)
        alpha = 2.0 / (period + 1.0)
        out = np.empty(len(values), dtype=float)
        out[0] = values[0]
        for i in range(1, len(values)):
            out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
        return out

    @classmethod
    def _ema(cls, values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        return float(cls._ema_series(values, period)[-1])

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
        if len(c) < 22:
            return "NEUTRAL"
        ema8, ema21 = cls._ema(c, 8), cls._ema(c, 21)
        atr = cls.calculate_atr(highs, lows, c)
        if ema8 is None or ema21 is None or atr <= 0:
            return "NEUTRAL"
        separation = abs(ema8 - ema21) / max(c[-1], 1e-12)
        if ema8 > ema21 and c[-1] > ema8 and separation >= 0.00035:
            return "LONG"
        if ema8 < ema21 and c[-1] < ema8 and separation >= 0.00035:
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
    def _macd(cls, closes):
        c = np.asarray(closes, dtype=float)
        if len(c) < 35:
            return {"state": "UNKNOWN", "histogram": 0.0}
        fast, slow = cls._ema_series(c, 12), cls._ema_series(c, 26)
        line = fast - slow
        signal = cls._ema_series(line, 9)
        hist = float(line[-1] - signal[-1])
        prev_hist = float(line[-2] - signal[-2])
        state = "BULLISH" if hist > 0 and hist >= prev_hist else "BEARISH" if hist < 0 and hist <= prev_hist else "MIXED"
        return {"state": state, "histogram": hist}

    @staticmethod
    def _adx(highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < period + 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        up = h[1:] - h[:-1]
        down = l[:-1] - l[1:]
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        dx_values = []
        # Rolling Wilder-style smoothing; avoids the prior single-candle ADX=100 error.
        for i in range(period - 1, len(tr)):
            tr_sum = float(np.sum(tr[i - period + 1:i + 1]))
            plus_sum = float(np.sum(plus_dm[i - period + 1:i + 1]))
            minus_sum = float(np.sum(minus_dm[i - period + 1:i + 1]))
            if tr_sum <= 0:
                continue
            plus_di = 100.0 * plus_sum / tr_sum
            minus_di = 100.0 * minus_sum / tr_sum
            denom = plus_di + minus_di
            dx_values.append(100.0 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0)
        return round(float(np.mean(dx_values[-period:])), 2) if dx_values else 0.0

    @staticmethod
    def _rsi(closes, period=14):
        c = np.asarray(closes, dtype=float)
        if len(c) < period + 1:
            return 50.0
        changes = np.diff(c)
        gains = np.maximum(changes, 0.0)
        losses = np.maximum(-changes, 0.0)
        avg_gain = float(np.mean(gains[-period:]))
        avg_loss = float(np.mean(losses[-period:]))
        if avg_loss <= 1e-12:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    @staticmethod
    def _vwap(highs, lows, closes, volumes, period=20):
        h, l, c, v = (np.asarray(x, dtype=float) for x in (highs, lows, closes, volumes))
        n = min(len(h), len(l), len(c), len(v), period)
        if n < 3:
            return 0.0
        typical = (h[-n:] + l[-n:] + c[-n:]) / 3.0
        vol = v[-n:]
        total = float(np.sum(vol))
        return float(np.sum(typical * vol) / total) if total > 0 else float(c[-1])

    @classmethod
    def _detect_structure(cls, opens, highs, lows, closes):
        o, h, l, c = (np.asarray(x, dtype=float) for x in (opens, highs, lows, closes))
        n = min(map(len, (o, h, l, c)))
        out = {"bos": "NONE", "mss": "NONE", "sweep": "NONE", "fvg": "NONE", "fvg_zone": None,
               "ob_type": "NONE", "ob_zone": None, "support": None, "resistance": None,
               "body_ratio": 0.0, "displacement": False}
        if n < 12:
            return out
        o, h, l, c = o[-n:], h[-n:], l[-n:], c[-n:]
        lookback = min(12, n - 2)
        prior_high = float(np.max(h[-lookback-1:-1]))
        prior_low = float(np.min(l[-lookback-1:-1]))
        out["support"], out["resistance"] = prior_low, prior_high
        candle_range = max(float(h[-1] - l[-1]), float(c[-1]) * 1e-9)
        body_ratio = abs(float(c[-1] - o[-1])) / candle_range
        out["body_ratio"] = round(body_ratio, 3)
        if c[-1] > prior_high and c[-1] > o[-1] and body_ratio >= 0.30:
            out["bos"] = "BULLISH_BOS"
        elif c[-1] < prior_low and c[-1] < o[-1] and body_ratio >= 0.30:
            out["bos"] = "BEARISH_BOS"
        # Sweep = wick through a known swing then close back on the safe side.
        if l[-1] < prior_low and c[-1] > prior_low:
            out["sweep"] = "SELL_SIDE_SWEEP"
        elif h[-1] > prior_high and c[-1] < prior_high:
            out["sweep"] = "BUY_SIDE_SWEEP"
        # Classic three-candle FVG check.
        if l[-1] > h[-3] and (l[-1] - h[-3]) / max(c[-1], 1e-12) >= 0.00025:
            out["fvg"], out["fvg_zone"] = "BULLISH_FVG", [float(h[-3]), float(l[-1])]
        elif h[-1] < l[-3] and (l[-3] - h[-1]) / max(c[-1], 1e-12) >= 0.00025:
            out["fvg"], out["fvg_zone"] = "BEARISH_FVG", [float(h[-1]), float(l[-3])]
        prev_move = float(c[-3] - c[-7])
        if prev_move < 0 and out["bos"] == "BULLISH_BOS":
            out["mss"] = "BULLISH_MSS"
        elif prev_move > 0 and out["bos"] == "BEARISH_BOS":
            out["mss"] = "BEARISH_MSS"
        atr = cls.calculate_atr(h, l, c)
        displacement = abs(float(c[-1] - o[-1])) >= 1.15 * atr if atr > 0 else False
        out["displacement"] = bool(displacement)
        # Approximate OB: last opposite candle immediately before a displacement/BOS sequence.
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
        o, h, l, c, v = (np.asarray(x, dtype=float) for x in (opens, highs, lows, closes, volumes))
        n = min(map(len, (o, h, l, c, v)))
        if n < 15:
            return False, None, "بيانات غير كافية للكسر/إعادة الاختبار", "NONE"
        o, h, l, c, v = (x[-n:] for x in (o, h, l, c, v))
        price = float(current_price) if current_price is not None and np.isfinite(current_price) and current_price > 0 else float(c[-1])
        atr = cls.calculate_atr(h, l, c)
        tolerance = max((atr / max(c[-1], 1e-12)) * 0.22 if atr > 0 else 0.0, 0.0015)
        lookback = min(10, n - 7)
        level_high = float(np.max(h[-lookback-1:-1]))
        level_low = float(np.min(l[-lookback-1:-1]))
        candle_range = max(float(h[-1] - l[-1]), float(c[-1]) * 1e-9)
        body_ratio = abs(float(c[-1] - o[-1])) / candle_range
        if direction == "LONG":
            fresh = c[-1] > level_high and c[-1] > o[-1] and body_ratio >= 0.30
            extension = (price - level_high) / max(atr, price * 1e-9)
            if price < level_high * (1.0 - tolerance):
                return False, level_high, "السعر الحالي رجع تحت مستوى الاختراق؛ لا شراء", "NONE"
            if fresh and extension <= 1.6:
                return True, level_high, "اختراق صاعد بإغلاق مؤكد والسعر ما زال فوق المستوى", "BREAKOUT"
            if extension > 1.6:
                return False, level_high, "السعر ممتد بعد الاختراق؛ تجنب مطاردة الحركة", "NONE"
            for j in range(n - 2, max(2, n - 7) - 1, -1):
                left = max(0, j - 10)
                if j - left < 5:
                    continue
                old_level = float(np.max(h[left:j]))
                if c[j] <= old_level or c[j] <= o[j]:
                    continue
                touched = l[-1] <= old_level * (1.0 + tolerance)
                reclaimed = c[-1] >= old_level and c[-1] > o[-1]
                current_holds = price >= old_level * (1.0 - tolerance)
                not_chased = (price - old_level) / max(atr, price * 1e-9) <= 1.6
                if touched and reclaimed and current_holds and not_chased:
                    return True, old_level, "إعادة اختبار ناجحة لمستوى اختراق سابق", "RETEST"
            return False, level_high, "لا يوجد اختراق حديث أو إعادة اختبار مؤكدة", "NONE"
        if direction == "SHORT":
            fresh = c[-1] < level_low and c[-1] < o[-1] and body_ratio >= 0.30
            extension = (level_low - price) / max(atr, price * 1e-9)
            if price > level_low * (1.0 + tolerance):
                return False, level_low, "السعر الحالي رجع فوق مستوى الكسر؛ لا بيع", "NONE"
            if fresh and extension <= 1.6:
                return True, level_low, "كسر هابط بإغلاق مؤكد والسعر ما زال تحت المستوى", "BREAKOUT"
            if extension > 1.6:
                return False, level_low, "السعر ممتد بعد الكسر؛ تجنب مطاردة الحركة", "NONE"
            for j in range(n - 2, max(2, n - 7) - 1, -1):
                left = max(0, j - 10)
                if j - left < 5:
                    continue
                old_level = float(np.min(l[left:j]))
                if c[j] >= old_level or c[j] >= o[j]:
                    continue
                touched = h[-1] >= old_level * (1.0 - tolerance)
                rejected = c[-1] <= old_level and c[-1] < o[-1]
                current_holds = price <= old_level * (1.0 + tolerance)
                not_chased = (old_level - price) / max(atr, price * 1e-9) <= 1.6
                if touched and rejected and current_holds and not_chased:
                    return True, old_level, "إعادة اختبار ناجحة لمستوى كسر سابق", "RETEST"
            return False, level_low, "لا يوجد كسر حديث أو إعادة اختبار مؤكدة", "NONE"
        return False, None, "الاتجاه غير واضح", "NONE"

    def _volume_impulse_check(self, opens, highs, lows, closes, volumes, direction):
        ratio = self._volume_ratio(volumes)
        candle_range = max(float(highs[-1] - lows[-1]), 1e-12)
        body_ratio = abs(float(closes[-1] - opens[-1])) / candle_range
        aligned = closes[-1] > opens[-1] if direction == "LONG" else closes[-1] < opens[-1]
        return bool(ratio >= 1.20 and body_ratio >= 0.35 and aligned)

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m,
                                ohlcv_btc_1h=None, symbol="", current_price=None, order_book=None):
        details = {
            "trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL", "trend_15m": "NEUTRAL",
            "break_retest": False, "break_level": None, "setup_type": "NONE",
            "bos": "NONE", "mss": "NONE", "sweep": "NONE", "fvg": "NONE", "fvg_zone": None,
            "ob_type": "NONE", "ob_zone": None, "support": None, "resistance": None,
            "volume_ratio": 0.0, "vwap_price": 0.0, "rsi": 50.0, "macd": "UNKNOWN", "adx": 0.0,
            "entry_valid": False, "btc_trend": "UNKNOWN", "confirmations": [],
            "reasons_excluded": [], "momentum": False, "retest_bos_valid": False,
            "candidate_direction": None, "current_price": current_price,
            "orderbook_pressure": "UNAVAILABLE", "orderbook_imbalance": 1.0,
        }
        empty = ([], [], [])
        if symbol and not self.is_valid_symbol(symbol):
            details["reasons_excluded"] = [f"رمز غير صالح: {symbol}"]
            return "NEUTRAL", 0, 0.0, details, empty
        for label, data in (("4H", ohlcv_4h), ("1H", ohlcv_1h), ("15M", ohlcv_15m)):
            if not self.valid_ohlcv(data, 20):
                details["reasons_excluded"] = [f"بيانات {label} غير كافية أو غير صالحة"]
                return "NEUTRAL", 0, 0.0, details, empty
        # Remove the latest candle to avoid reading a candle that may still be forming.
        d4, d1, d15 = ohlcv_4h[:-1], ohlcv_1h[:-1], ohlcv_15m[:-1]
        o4, h4, l4, c4, v4 = self.arrays(d4)
        o1, h1, l1, c1, v1 = self.arrays(d1)
        o15, h15, l15, c15, v15 = self.arrays(d15)
        trend4, trend1, trend15 = self._trend(h4, l4, c4), self._trend(h1, l1, c1), self._trend(h15, l15, c15)
        details.update({"trend_4h": trend4, "trend_1h": trend1, "trend_15m": trend15})
        if self.valid_ohlcv(ohlcv_btc_1h, 20):
            _, bh, bl, bc, _ = self.arrays(ohlcv_btc_1h[:-1])
            details["btc_trend"] = self._trend(bh, bl, bc)

        volume_ratio = self._volume_ratio(v15)
        details["volume_ratio"] = volume_ratio
        details.update(self._detect_structure(o15, h15, l15, c15))
        details["vwap_price"] = self._vwap(h15, l15, c15, v15)
        details["rsi"] = self._rsi(c15)
        macd = self._macd(c15)
        details["macd"], details["macd_histogram"] = macd["state"], macd["histogram"]
        details["adx"] = self._adx(h15, l15, c15)
        # Live order-book imbalance is a snapshot, not proof of whale intent or executed flow.
        try:
            bids = (order_book or {}).get("bids") or []
            asks = (order_book or {}).get("asks") or []
            bid_notional = sum(float(level[0]) * float(level[1]) for level in bids[:15] if len(level) >= 2)
            ask_notional = sum(float(level[0]) * float(level[1]) for level in asks[:15] if len(level) >= 2)
            if bid_notional > 0 and ask_notional > 0:
                imbalance = bid_notional / ask_notional
                details["orderbook_imbalance"] = round(float(imbalance), 3)
                details["orderbook_pressure"] = "BUY_PRESSURE" if imbalance >= 1.15 else ("SELL_PRESSURE" if imbalance <= 0.87 else "BALANCED")
        except (TypeError, ValueError, IndexError):
            pass

        direction = trend1
        if direction not in ("LONG", "SHORT"):
            details["reasons_excluded"] = ["اتجاه الساعة غير واضح"]
            return "NEUTRAL", 0, volume_ratio, details, (h15.tolist(), l15.tolist(), c15.tolist())
        details["candidate_direction"] = direction
        excluded, confirmations = [], []
        if trend4 != direction:
            details["reasons_excluded"] = ["اتجاه 4H لا يؤكد اتجاه 1H"]
            return "NEUTRAL", 0, volume_ratio, details, (h15.tolist(), l15.tolist(), c15.tolist())
        confirmations.append("توافق اتجاه 4H و1H")
        if trend15 == direction:
            confirmations.append("اتجاه 15M متوافق")
        else:
            excluded.append("اتجاه 15M ليس في نفس الاتجاه")

        br_ok, br_level, br_reason, setup_type = self._break_retest(
            o15, h15, l15, c15, v15, direction, current_price=current_price
        )
        details.update({"break_retest": br_ok, "break_level": br_level, "retest_advice": br_reason,
                        "setup_type": setup_type, "retest_bos_valid": bool(br_ok and setup_type == "RETEST")})
        expected_bos = "BULLISH_BOS" if direction == "LONG" else "BEARISH_BOS"
        expected_sweep = "SELL_SIDE_SWEEP" if direction == "LONG" else "BUY_SIDE_SWEEP"
        expected_fvg = "BULLISH_FVG" if direction == "LONG" else "BEARISH_FVG"
        expected_ob = "BULLISH_OB" if direction == "LONG" else "BEARISH_OB"
        structure_ok = details["bos"] == expected_bos or details["retest_bos_valid"]
        if details["bos"] == expected_bos:
            confirmations.append("BOS يؤكد الهيكل")
        elif details["retest_bos_valid"]:
            confirmations.append("إعادة اختبار مؤكدة")
        else:
            excluded.append("لا يوجد BOS أو إعادة اختبار صالحة")
        if details["mss"] == ("BULLISH_MSS" if direction == "LONG" else "BEARISH_MSS"):
            confirmations.append("MSS يؤيد تغير الهيكل")
        if details["sweep"] == expected_sweep:
            confirmations.append("سحب سيولة في صالح الاتجاه")
        if details["fvg"] == expected_fvg:
            confirmations.append("FVG في اتجاه الصفقة")
        if details["ob_type"] == expected_ob and details["ob_zone"]:
            confirmations.append("منطقة Order Block متوافقة")
        if not br_ok:
            excluded.append(br_reason)

        aligned_candle = c15[-1] > o15[-1] if direction == "LONG" else c15[-1] < o15[-1]
        recent_momentum = c15[-1] > c15[-2] and c15[-1] > c15[-4] if direction == "LONG" else c15[-1] < c15[-2] and c15[-1] < c15[-4]
        momentum = bool(aligned_candle and (recent_momentum or (details["body_ratio"] >= 0.45 and br_ok)))
        details["momentum"] = momentum
        if momentum:
            confirmations.append("شمعة وزخم متوافقان")
        else:
            excluded.append("الزخم غير مؤكد")
        if volume_ratio >= 1.20:
            confirmations.append(f"حجم تداول {volume_ratio}x من المتوسط")
        else:
            excluded.append(f"حجم التداول أقل من 1.20x ({volume_ratio}x)")

        macd_aligned = macd["state"] == ("BULLISH" if direction == "LONG" else "BEARISH")
        if macd_aligned:
            confirmations.append("MACD يؤكد الزخم")
        else:
            excluded.append("MACD لا يؤكد الاتجاه بوضوح")
        vwap = details["vwap_price"]
        vwap_aligned = c15[-1] >= vwap if direction == "LONG" else c15[-1] <= vwap
        if vwap_aligned:
            confirmations.append("السعر في الجانب المناسب من VWAP")
        else:
            excluded.append("السعر على الجانب غير المناسب من VWAP")
        btc = details["btc_trend"]
        btc_aligned = btc == direction
        btc_conflict = btc in ("LONG", "SHORT") and btc != direction
        if btc_aligned:
            confirmations.append("اتجاه BTC متوافق")
        elif btc_conflict:
            excluded.append("اتجاه BTC معاكس")

        book_pressure = details["orderbook_pressure"]
        book_aligned = (direction == "LONG" and book_pressure == "BUY_PRESSURE") or (direction == "SHORT" and book_pressure == "SELL_PRESSURE")
        book_conflict = (direction == "LONG" and book_pressure == "SELL_PRESSURE") or (direction == "SHORT" and book_pressure == "BUY_PRESSURE")
        if book_aligned:
            confirmations.append(f"ضغط دفتر الأوامر متوافق ({details['orderbook_imbalance']}x)")
        elif book_conflict:
            excluded.append("ضغط دفتر الأوامر يعاكس الاتجاه؛ انتبه لاحتمال الامتصاص")

        # Balanced confluence score; it is NOT a win probability.
        score = 0
        score += 15 if trend4 == direction and trend1 == direction else 0
        score += 8 if trend15 == direction else 0
        score += 15 if details["bos"] == expected_bos else (10 if details["retest_bos_valid"] else 0)
        score += 8 if details["sweep"] == expected_sweep else 0
        score += 8 if details["fvg"] == expected_fvg else 0
        score += 5 if details["ob_type"] == expected_ob and details["ob_zone"] else 0
        score += 10 if br_ok else 0
        score += 10 if volume_ratio >= 1.50 else (7 if volume_ratio >= 1.20 else 0)
        score += 8 if momentum else 0
        score += 8 if macd_aligned else 0
        score += 5 if vwap_aligned else 0
        score += 5 if btc_aligned else (0 if btc_conflict else 2)
        score += 4 if book_aligned else (-4 if book_conflict else 0)
        # ADX is a strength filter, not directional proof.
        score += 5 if details["adx"] >= 20 else 0
        if details["rsi"] >= 78 and direction == "LONG":
            score -= 6
            excluded.append("RSI مرتفع؛ احتمال مطاردة الحركة")
        if details["rsi"] <= 22 and direction == "SHORT":
            score -= 6
            excluded.append("RSI منخفض؛ احتمال تأخر البيع")

        # Require core setup + independent evidence. No artificial 100 score when gates fail.
        entry_valid = bool(
            br_ok and structure_ok and volume_ratio >= 1.20 and momentum and macd_aligned
            and not btc_conflict and len(confirmations) >= 4 and score >= 70
        )
        if not br_ok or not structure_ok or volume_ratio < 1.20 or not momentum or not macd_aligned or btc_conflict:
            score = min(score, 68)
        elif len(confirmations) < 4:
            score = min(score, 74)
        score = int(max(0, min(100, score)))
        if not entry_valid:
            excluded.append("بوابة التنفيذ لم تكتمل؛ لا توجد إشارة دخول")
        details["entry_valid"] = entry_valid
        details["confirmations"] = confirmations
        details["reasons_excluded"] = excluded
        details["candidate_direction"] = direction
        return (direction if entry_valid else "NEUTRAL"), score, volume_ratio, details, (h15.tolist(), l15.tolist(), c15.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs, lows = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float)
        closes = (highs + lows) / 2.0 if closes is None else np.asarray(closes, dtype=float)
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
        recent_low, recent_high = float(np.min(lows[-12:])), float(np.max(highs[-12:]))
        if direction in ("LONG", "BUY"):
            structural_stop = recent_low - 0.12 * atr
            stop = min(entry - 1.15 * atr, structural_stop) if structural_stop < entry else entry - 1.4 * atr
            risk = entry - stop
            if risk <= 0:
                raise ValueError("Invalid long stop distance")
            targets = (entry + 1.5*risk, entry + 2.5*risk, entry + 3.5*risk)
        elif direction in ("SHORT", "SELL"):
            structural_stop = recent_high + 0.12 * atr
            stop = max(entry + 1.15 * atr, structural_stop) if structural_stop > entry else entry + 1.4 * atr
            risk = stop - entry
            if risk <= 0:
                raise ValueError("Invalid short stop distance")
            targets = (entry - 1.5*risk, entry - 2.5*risk, entry - 3.5*risk)
            if targets[-1] <= 0:
                raise ValueError("Calculated short target is non-positive")
        else:
            raise ValueError("Direction must be LONG or SHORT")
        sl_pct = abs(entry - stop) / entry * 100.0
        tp1_pct = abs(targets[0] - entry) / entry * 100.0
        rr = abs(targets[0] - entry) / abs(entry - stop)
        return (round(float(stop), 10), *(round(float(x), 10) for x in targets),
                round(float(sl_pct), 3), round(float(tp1_pct), 3), round(float(rr), 2))
