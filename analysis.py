# ==========================================
# BREAKOUT + RETEST STRATEGY ENGINE
# File: analysis.py
# Compatible with current BingX/Telegram main.py
# ==========================================

import numpy as np


class StrategyEngine:
    def __init__(self):
        pass

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            for candle in data:
                if len(candle) < 6:
                    return False
                values = [float(candle[i]) for i in range(1, 6)]
                if not all(np.isfinite(v) for v in values):
                    return False
                if float(candle[2]) < float(candle[3]):
                    return False
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        opens = np.array([float(c[1]) for c in data], dtype=float)
        highs = np.array([float(c[2]) for c in data], dtype=float)
        lows = np.array([float(c[3]) for c in data], dtype=float)
        closes = np.array([float(c[4]) for c in data], dtype=float)
        volumes = np.array([max(0.0, float(c[5])) for c in data], dtype=float)
        return opens, highs, lows, closes, volumes

    def calculate_atr(self, highs, lows, closes, period=14):
        highs, lows, closes = map(lambda x: np.asarray(x, dtype=float),
                                  (highs, lows, closes))
        n = min(len(highs), len(lows), len(closes))
        if n < 2:
            return 0.0
        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(np.abs(highs[1:] - closes[:-1]),
                       np.abs(lows[1:] - closes[:-1]))
        )
        return float(np.mean(tr[-period:])) if len(tr) else 0.0

    @staticmethod
    def _trend(highs, lows, closes):
        highs, lows, closes = map(lambda x: np.asarray(x, dtype=float),
                                  (highs, lows, closes))
        if len(closes) < 12:
            return "NEUTRAL"
        # Recent confirmed swing structure and close progression.
        recent_high = float(np.max(highs[-6:-1]))
        recent_low = float(np.min(lows[-6:-1]))
        if closes[-1] > recent_high and closes[-2] <= recent_high:
            return "LONG"
        if closes[-1] < recent_low and closes[-2] >= recent_low:
            return "SHORT"
        fast = float(np.mean(closes[-5:]))
        slow = float(np.mean(closes[-12:-5]))
        if fast > slow and closes[-1] > closes[-4]:
            return "LONG"
        if fast < slow and closes[-1] < closes[-4]:
            return "SHORT"
        return "NEUTRAL"

    @staticmethod
    def _levels(highs, lows, lookback=20):
        # Exclude the newest candle; levels should exist before the breakout.
        highs, lows = np.asarray(highs, float), np.asarray(lows, float)
        if len(highs) < 5:
            return None, None
        n = min(lookback, len(highs) - 1)
        return float(np.max(highs[-n-1:-1])), float(np.min(lows[-n-1:-1]))

    def _break_retest(self, opens, highs, lows, closes, volumes, direction):
        """Check a recent level break followed by a retest and candle rejection."""
        if len(closes) < 8:
            return False, None, "بيانات شموع غير كافية"

        # Look for a recent completed break in the previous few candles,
        # then check the latest completed candle for a retest/rejection.
        search_start = max(3, len(closes) - 6)
        for i in range(search_start, len(closes) - 1):
            prior_start = max(0, i - 20)
            prior_high = float(np.max(highs[prior_start:i]))
            prior_low = float(np.min(lows[prior_start:i]))
            candle_range = max(float(highs[i] - lows[i]), 1e-12)
            body = abs(float(closes[i] - opens[i]))
            volume_base = float(np.mean(volumes[max(0, i-12):i])) if i > 0 else 0.0
            volume_ok = volume_base <= 0 or volumes[i] >= volume_base * 0.9

            if direction == "LONG":
                broke = closes[i] > prior_high and closes[i] > opens[i]
                if not broke or not volume_ok or body / candle_range < 0.35:
                    continue
                level = prior_high
                j = len(closes) - 1
                tolerance = max(level * 0.003, (highs[j] - lows[j]) * 0.25)
                retested = lows[j] <= level + tolerance and lows[j] >= level - tolerance * 2
                rejected = closes[j] > level and closes[j] >= opens[j]
                if retested and rejected:
                    return True, level, "كسر مقاومة ثم إعادة اختبار ورفض صاعد"

            elif direction == "SHORT":
                broke = closes[i] < prior_low and closes[i] < opens[i]
                if not broke or not volume_ok or body / candle_range < 0.35:
                    continue
                level = prior_low
                j = len(closes) - 1
                tolerance = max(level * 0.003, (highs[j] - lows[j]) * 0.25)
                retested = highs[j] >= level - tolerance and highs[j] <= level + tolerance * 2
                rejected = closes[j] < level and closes[j] <= opens[j]
                if retested and rejected:
                    return True, level, "كسر دعم ثم إعادة اختبار ورفض هابط"

        return False, None, "لم يكتمل كسر المستوى وإعادة الاختبار"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None):
        details = {
            "trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL",
            "break_retest": False, "break_level": None,
            "bos": "NONE", "mss": "NONE", "sweep": "NONE",
            "fvg": "NONE", "ob_type": "NONE", "ob_zone": None,
            "volume_ratio": 0.0, "vwap_price": 0.0,
            "support": None, "resistance": None,
            "retest_advice": "بيانات غير كافية",
            "entry_valid": False, "btc_trend": "UNKNOWN",
            "confirmations": [], "reasons_excluded": []
        }
        if not all(self.valid_ohlcv(x, 20) for x in (ohlcv_4h, ohlcv_1h, ohlcv_15m)):
            details["reasons_excluded"].append("بيانات غير كافية أو غير صالحة")
            return "NEUTRAL", 0, 0.0, details, ([], [], [])

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h)
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h)
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)

        # Exclude the last candle because it may still be forming.
        trend4 = self._trend(h4[:-1], l4[:-1], c4[:-1])
        trend1 = self._trend(h1[:-1], l1[:-1], c1[:-1])
        details["trend_4h"], details["trend_1h"] = trend4, trend1

        confirmations, excluded = [], []
        score = 20
        direction = "NEUTRAL"

        if trend4 != "NEUTRAL" and trend4 == trend1:
            direction = trend1
            score += 20
            confirmations.append("اتجاه 4H و1H متوافق")
        else:
            excluded.append("اتجاه 4H و1H غير متوافق أو غير واضح")

        # Level break/retest is checked on closed 15m candles.
        br_ok, br_level, br_reason = self._break_retest(
            o15[:-1], h15[:-1], l15[:-1], c15[:-1], v15[:-1], direction
        ) if direction != "NEUTRAL" else (False, None, "الاتجاه العام غير واضح")
        details["break_retest"] = br_ok
        details["break_level"] = br_level
        if br_ok:
            score += 30
            confirmations.append(br_reason)
            details["retest_advice"] = "تأكد من السبريد والسعر قبل التنفيذ"
        else:
            excluded.append(br_reason)
            details["retest_advice"] = "انتظر كسر المستوى ثم إعادة اختباره وتأكيد شمعة 15M"

        # BOS is a separate description of the latest closed 1H range break.
        bos = "NONE"
        if len(c1) >= 12:
            ref_hi = float(np.max(h1[-9:-2]))
            ref_lo = float(np.min(l1[-9:-2]))
            if c1[-2] > ref_hi:
                bos = "BULLISH_BOS"
            elif c1[-2] < ref_lo:
                bos = "BEARISH_BOS"
        details["bos"] = bos
        if (direction == "LONG" and bos == "BULLISH_BOS") or (direction == "SHORT" and bos == "BEARISH_BOS"):
            score += 10
            confirmations.append(f"كسر هيكل الساعة يدعم الاتجاه: {bos}")
        else:
            excluded.append("لا يوجد كسر هيكل ساعة داعم واضح")

        # Volume on latest completed 15m candle vs preceding 20 candles.
        avg_vol = float(np.mean(v15[-22:-2])) if len(v15) >= 22 else float(np.mean(v15[:-2]))
        latest_vol = float(v15[-2])
        volume_ratio = round(latest_vol / avg_vol, 2) if avg_vol > 0 else 0.0
        details["volume_ratio"] = volume_ratio
        if volume_ratio >= 1.1:
            score += 10
            confirmations.append(f"فوليوم 15M أعلى من المتوسط ({volume_ratio}x)")
        else:
            excluded.append(f"فوليوم 15M غير مؤكد ({volume_ratio}x)")

        # Rolling VWAP estimate based on closed 1H candles.
        n = min(24, len(c1) - 1)
        typical = (h1[-n-1:-1] + l1[-n-1:-1] + c1[-n-1:-1]) / 3
        vwap_vol = v1[-n-1:-1]
        vwap = float(np.sum(typical * vwap_vol) / np.sum(vwap_vol)) if np.sum(vwap_vol) > 0 else float(c1[-2])
        details["vwap_price"] = vwap
        last_price = float(c15[-2])
        if direction == "LONG" and last_price > vwap:
            score += 5
            confirmations.append("السعر أعلى VWAP المرجعي")
        elif direction == "SHORT" and last_price < vwap:
            score += 5
            confirmations.append("السعر أسفل VWAP المرجعي")
        else:
            excluded.append("السعر لا يدعم الاتجاه بالنسبة إلى VWAP")

        support = float(np.min(l1[-11:-1]))
        resistance = float(np.max(h1[-11:-1]))
        details["support"], details["resistance"] = support, resistance

        # Simple liquidity sweep / FVG context on completed 15m bars.
        if len(c15) >= 5:
            if h15[-2] > h15[-3] and c15[-2] < h15[-3]:
                details["sweep"] = "BEARISH_SWEEP"
            elif l15[-2] < l15[-3] and c15[-2] > l15[-3]:
                details["sweep"] = "BULLISH_SWEEP"
            if l15[-2] > h15[-4]:
                details["fvg"] = "BULLISH_FVG"
            elif h15[-2] < l15[-4]:
                details["fvg"] = "BEARISH_FVG"

        if details["sweep"] != "NONE":
            if (direction == "LONG" and details["sweep"] == "BULLISH_SWEEP") or (direction == "SHORT" and details["sweep"] == "BEARISH_SWEEP"):
                score += 5
                confirmations.append(f"سحب سيولة متوافق: {details['sweep']}")

        # BTC trend is a risk context, not a standalone entry signal.
        btc_trend = "UNKNOWN"
        if self.valid_ohlcv(ohlcv_btc_1h, 12):
            _, bh, bl, bc, _ = self.arrays(ohlcv_btc_1h)
            btc_trend = self._trend(bh[:-1], bl[:-1], bc[:-1])
            if direction == "LONG" and btc_trend == "SHORT":
                score -= 5
                excluded.append("اتجاه BTC هابط ويزيد مخاطرة LONG")
            elif direction == "SHORT" and btc_trend == "LONG":
                score -= 5
                excluded.append("اتجاه BTC صاعد ويزيد مخاطرة SHORT")
            elif direction != "NEUTRAL" and btc_trend == direction:
                score += 5
                confirmations.append("اتجاه BTC يدعم الصفقة")
        details["btc_trend"] = btc_trend

        score = int(max(0, min(100, score)))
        entry_valid = direction in ("LONG", "SHORT") and br_ok and volume_ratio >= 1.0
        if not entry_valid or score < 65:
            signal = "NEUTRAL"
            excluded.append("شروط الدخول أو التقييم لم تكتمل")
        else:
            signal = direction

        details["entry_valid"] = bool(entry_valid)
        details["confirmations"] = confirmations
        details["reasons_excluded"] = excluded

        return signal, score, volume_ratio, details, (h1.tolist(), l1.tolist(), c1.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs, lows = np.asarray(highs, float), np.asarray(lows, float)
        closes = np.asarray(closes if closes is not None else (highs + lows) / 2.0, float)
        n = min(len(highs), len(lows), len(closes))
        if entry <= 0 or n < 5:
            raise ValueError("Insufficient candles or invalid entry price")

        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        atr = self.calculate_atr(highs, lows, closes)
        if atr <= 0:
            atr = entry * 0.01

        if direction in ("LONG", "BUY"):
            stop = min(float(np.min(lows[-5:])), entry - 1.3 * atr)
            risk = entry - stop
            if risk <= 0:
                raise ValueError("Invalid LONG stop")
            tp1, tp2, tp3 = entry + 1.5*risk, entry + 2.5*risk, entry + 4*risk
        elif direction in ("SHORT", "SELL"):
            stop = max(float(np.max(highs[-5:])), entry + 1.3 * atr)
            risk = stop - entry
            if risk <= 0:
                raise ValueError("Invalid SHORT stop")
            tp1, tp2, tp3 = entry - 1.5*risk, entry - 2.5*risk, entry - 4*risk
            if tp3 <= 0:
                tp3 = max(entry * 0.01, tp2 - risk)
        else:
            raise ValueError("Direction must be LONG or SHORT")

        sl_pct = round(abs(entry - stop) / entry * 100, 3)
        tp1_pct = round(abs(tp1 - entry) / entry * 100, 3)
        rr = round(tp1_pct / max(sl_pct, 0.001), 2)

        return (
            round(float(stop), 10), round(float(tp1), 10),
            round(float(tp2), 10), round(float(tp3), 10),
            sl_pct, tp1_pct, rr
        )
