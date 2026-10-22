# ============================================================
# MY EXPERT CRYPTO BOT - PATTERN RECOGNITION ENGINE (V11.5)
# Optimized Sensitivity: Balanced filtering to trigger quality trades
# while preserving core SMC and risk management rules.
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=35):
        """Validate OHLCV arrays."""
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]):
                return None
            return a
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

    @staticmethod
    def _ema(values, period):
        arr = np.asarray(values, dtype=float)
        if len(arr) == 0:
            return np.asarray([], dtype=float)
        alpha = 2.0 / (period + 1.0)
        out = np.empty(len(arr), dtype=float)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
        return out

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-period:])) if len(tr) > 0 else 0.0

    def calculate_rsi(self, closes, period=14):
        c = np.asarray(closes, dtype=float).reshape(-1)
        if len(c) < period + 1:
            return 50.0
        d = np.diff(c)[-period:]
        gain, loss = float(np.mean(np.maximum(d, 0))), float(np.mean(np.maximum(-d, 0)))
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        if gain == 0:
            return 0.0
        rs = gain / loss
        return float(100 - 100 / (1 + rs))

    def calculate_macd(self, closes):
        c = np.asarray(closes, dtype=float).reshape(-1)
        if len(c) < 35 or not np.all(np.isfinite(c)):
            return 0.0, 0.0, 0.0
        line = self._ema(c, 12) - self._ema(c, 26)
        signal = self._ema(line, 9)
        hist = line - signal
        return float(line[-1]), float(signal[-1]), float(hist[-1])

    def detect_swings(self, highs, lows, window=2):
        """Pivot detection with a flexible window (window=2)."""
        highs = np.asarray(highs, dtype=float).reshape(-1)
        lows = np.asarray(lows, dtype=float).reshape(-1)
        n = min(len(highs), len(lows))
        ph, pl = [], []
        if window < 1 or n < (2 * window + 1):
            return ph, pl
        for i in range(window, n - window):
            left_h, right_h = highs[i-window:i], highs[i+1:i+window+1]
            left_l, right_l = lows[i-window:i], lows[i+1:i+window+1]
            if highs[i] > np.max(left_h) and highs[i] >= np.max(right_h):
                ph.append((i, float(highs[i])))
            if lows[i] < np.min(left_l) and lows[i] <= np.min(right_l):
                pl.append((i, float(lows[i])))
        return ph, pl

    @staticmethod
    def _closed_array(data, minimum=35):
        arr = StrategyEngine._array(data, minimum)
        return None if arr is None else arr[:-1]

    def _bias(self, data, minimum=25):
        arr = self._closed_array(data, minimum)
        if arr is None or len(arr) < 20:
            return "NEUTRAL"
        c = arr[:, 4]
        e20, e50 = self._ema(c, 20), self._ema(c, 50)
        if len(c) >= 20 and c[-1] > e20[-1]:
            return "BULLISH"
        if len(c) >= 20 and c[-1] < e20[-1]:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_smc_advanced(self, closed_candles, atr):
        a = np.asarray(closed_candles, dtype=float)
        result = {"sweep": False, "bos": False, "choch": False, "fvg": False,
                  "ob": False, "eq_levels": False, "details": [], "sweep_direction": None}
        if a.ndim != 2 or len(a) < 20 or atr <= 0:
            return result
        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        ref_h, ref_l = h[-20:-2], l[-20:-2]
        if len(ref_h) < 8:
            return result

        prev_high, prev_low = float(np.max(ref_h)), float(np.min(ref_l))
        if h[-1] > prev_high and c[-1] < prev_high:
            result["sweep"], result["sweep_direction"] = True, "SHORT"
            result["details"].append("Bearish Liquidity Sweep")
        elif l[-1] < prev_low and c[-1] > prev_low:
            result["sweep"], result["sweep_direction"] = True, "LONG"
            result["details"].append("Bullish Liquidity Sweep")

        ph, pl = self.detect_swings(h[:-1], l[:-1], window=2)
        last_close = float(c[-1])
        if ph and last_close > ph[-1][1]:
            result["bos"] = True
            result["details"].append("Bullish BOS")
        if pl and last_close < pl[-1][1]:
            result["bos"] = True
            result["details"].append("Bearish BOS")

        for i in range(len(a) - 1, max(2, len(a) - 6), -1):
            if l[i] > h[i-2]:
                result["fvg"] = True
                result["details"].append("Bullish FVG")
                break
            if h[i] < l[i-2]:
                result["fvg"] = True
                result["details"].append("Bearish FVG")
                break

        return result

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        debug = []

        def no_trade(reason, **extra):
            out = {"reason": reason, "debug_trace": debug}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 35)
        if raw15 is None or len(raw15) < 36:
            return no_trade("بيانات 15M غير كافية")

        a = raw15[:-1]
        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        current_price = float(raw15[-1, 4])
        atr = self.calculate_atr(h, l, c, 14)
        if not np.isfinite(atr) or atr <= 0 or current_price <= 0:
            return no_trade("ATR أو السعر غير صالح")

        rsi = self.calculate_rsi(c)
        _, _, macd_hist = self.calculate_macd(c)
        avg_vol = float(np.mean(v[-15:]))
        vol_ratio = float(v[-1] / avg_vol) if avg_vol > 0 else 1.0
        ph, pl = self.detect_swings(h, l, window=2)

        pattern = None
        direction = None
        neckline = base = 0.0
        quality = 0
        age = 999

        # --- A. Inverse Head & Shoulders ---
        if len(pl) >= 3 and len(ph) >= 2:
            left, head, right = pl[-3], pl[-2], pl[-1]
            if left[0] < head[0] < right[0] and head[1] < left[1] and head[1] < right[1]:
                necks = [x for x in ph if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "INV_HEAD_SHOULDERS", "LONG"
                    neckline, base, quality = max(x[1] for x in necks), head[1], 25
                    age = len(a) - 1 - right[0]

        # --- B. Double Bottom ---
        if pattern is None and len(pl) >= 2:
            left, right = pl[-2], pl[-1]
            if abs(left[1] - right[1]) <= 1.8 * atr:
                necks = [x for x in ph if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "DOUBLE_BOTTOM", "LONG"
                    neckline, base, quality = max(x[1] for x in necks), min(left[1], right[1]), 20
                    age = len(a) - 1 - right[0]

        # --- C. Head & Shoulders ---
        if pattern is None and len(ph) >= 3 and len(pl) >= 2:
            left, head, right = ph[-3], ph[-2], ph[-1]
            if left[0] < head[0] < right[0] and head[1] > left[1] and head[1] > right[1]:
                necks = [x for x in pl if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "HEAD_SHOULDERS", "SHORT"
                    neckline, base, quality = min(x[1] for x in necks), head[1], 25
                    age = len(a) - 1 - right[0]

        # --- D. Double Top ---
        if pattern is None and len(ph) >= 2:
            left, right = ph[-2], ph[-1]
            if abs(left[1] - right[1]) <= 1.8 * atr:
                necks = [x for x in pl if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "DOUBLE_TOP", "SHORT"
                    neckline, base, quality = min(x[1] for x in necks), max(left[1], right[1]), 20
                    age = len(a) - 1 - right[0]

        if pattern is None:
            return no_trade("لم يُكتشف نموذج هندسي على فريم 15M")

        # مرونة أكبر في عمر النموذج (حتى 25 شمعة)
        if age > 25:
            return no_trade(f"النموذج قديم: {age} شمعة", pattern=pattern)

        # فحص كسر خط العنق
        recent_c = c[-8:]
        state = "FORMING"
        if direction == "LONG":
            if np.any(recent_c > neckline):
                state = "BREAKOUT_CONFIRMED"
                if l[-1] <= neckline + 0.35 * atr and c[-1] > neckline:
                    state = "RETEST_CONFIRMED"
        else:
            if np.any(recent_c < neckline):
                state = "BREAKOUT_CONFIRMED"
                if h[-1] >= neckline - 0.35 * atr and c[-1] < neckline:
                    state = "RETEST_CONFIRMED"

        if state not in ("RETEST_CONFIRMED", "BREAKOUT_CONFIRMED"):
            return no_trade(f"النموذج غير مؤهل للاختراق: {state}", pattern=pattern)

        # مرونة في مسافة الدخول الابتعاد عن خط العنق حتى 2.2 * ATR
        if abs(current_price - neckline) > 2.2 * atr:
            return no_trade("الدخول متأخر جداً عن خط العنق", pattern=pattern)

        smc = self.analyze_smc_advanced(a, atr)
        bias4 = self._bias(ohlcv_4h) if ohlcv_4h is not None else "NEUTRAL"
        bias1 = self._bias(ohlcv_1h) if ohlcv_1h is not None else "NEUTRAL"
        btc_bias = self._bias(btc_ohlcv_1h) if btc_ohlcv_1h is not None else "NEUTRAL"

        # نظام تقييم مرن (Score)
        score = quality
        score += 15 if state == "RETEST_CONFIRMED" else 10
        if vol_ratio >= 1.1: score += 10
        if smc["sweep"] and smc["sweep_direction"] == direction: score += 12
        if smc["bos"]: score += 8
        if smc["fvg"]: score += 5

        expected_bias = "BULLISH" if direction == "LONG" else "BEARISH"
        if bias4 == expected_bias: score += 10
        if bias1 == expected_bias: score += 8
        if btc_bias == expected_bias: score += 7

        score = int(max(0, min(100, round(score))))
        debug.append(f"Optimized Score: {score}/100")

        # عتبة قبول متوازنة ومرنة (55/100 بدلاً من 68) لضمان ظهور صفقات ممتازة
        if score < 55:
            return no_trade(f"التقييم {score}/100 أقل من العتبة المرنة (55)", score=score)

        # حساب الوقف والأهداف
        if direction == "LONG":
            stop = min(base - 0.2 * atr, current_price - 1.2 * atr)
            risk_dist = current_price - stop
            tp1, tp2, tp3 = current_price + risk_dist * 1.5, current_price + risk_dist * 2.2, current_price + risk_dist * 3.5
        else:
            stop = max(base + 0.2 * atr, current_price + 1.2 * atr)
            risk_dist = stop - current_price
            tp1, tp2, tp3 = current_price - risk_dist * 1.5, current_price - risk_dist * 2.2, current_price - risk_dist * 3.5

        if risk_dist <= 0:
            return no_trade("مسافة الوقف غير صالحة")

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "Signal Qualified with Optimized Filter",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.2"
            },
            "setup": f"{pattern} ({state})",
            "pattern_name": pattern,
            "neckline": self._round(neckline),
            "state": state,
            "score": score,
            "atr": self._round(atr),
            "rsi": round(rsi, 2),
            "timeframe_bias": {"4h": bias4, "1h": bias1, "btc_1h": btc_bias},
            "smc_note": " | ".join(smc["details"]) if smc["details"] else "SMC Normal",
            "debug_trace": debug
        }
        return direction, self._round(current_price), details

    def analyze_market_structure(self, ohlcv_30m, ohlcv_4h=None, ohlcv_1h=None, btc_ohlcv_1h=None, **kwargs):
        return self.analyze_multi_timeframe(ohlcv_4h, ohlcv_1h, ohlcv_30m, btc_ohlcv_1h)

    def calculate_risk_management(self, entry_price, stop_loss, direction="LONG"):
        entry, stop = float(entry_price), float(stop_loss)
        dist = abs(entry - stop)
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / dist if dist > 0 else 0.0
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "risk_distance": round(dist, 8)
        }
