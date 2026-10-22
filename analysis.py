# ============================================================
# MY EXPERT CRYPTO BOT - PATTERN RECOGNITION ENGINE (V11.3)
# Safer closed-candle analysis, multi-timeframe bias, SMC checks,
# pattern validation, conservative scoring, ATR-based risk levels.
# NOTE: No strategy guarantees profit. Backtest before live trading.
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=40):
        """Validate OHLCV arrays. Expects [open, high, low, close, volume] or CCXT 6-col rows."""
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            # CCXT layout: timestamp, open, high, low, close, volume
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]):  # high < low
                return None
            if np.any(a[:, 1] > a[:, 2]) or np.any(a[:, 1] < a[:, 3]):
                return None
            if np.any(a[:, 4] > a[:, 2]) or np.any(a[:, 4] < a[:, 3]):
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
        if not np.isfinite(value):
            return 0.0
        if value == 0:
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
        if not len(tr):
            return 0.0
        return float(np.mean(tr[-period:]))

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

    def detect_swings(self, highs, lows, window=3):
        """Confirmed pivots only: each pivot has window candles on both sides."""
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
    def _closed_array(data, minimum=40):
        arr = StrategyEngine._array(data, minimum)
        # Inputs from CCXT commonly include the still-forming last candle.
        # Drop it consistently; caller must supply chronological OHLCV.
        return None if arr is None else arr[:-1]

    def _bias(self, data, minimum=30):
        arr = self._closed_array(data, minimum)
        if arr is None or len(arr) < 25:
            return "NEUTRAL"
        c = arr[:, 4]
        e20, e50 = self._ema(c, 20), self._ema(c, 50)
        # Need both trend and slope confirmation; short history can still be neutral.
        if len(c) >= 50 and c[-1] > e20[-1] > e50[-1] and e20[-1] > e20[-4]:
            return "BULLISH"
        if len(c) >= 50 and c[-1] < e20[-1] < e50[-1] and e20[-1] < e20[-4]:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_smc_advanced(self, closed_candles, atr):
        """Return cautious SMC evidence from closed candles; flags are not independent proof."""
        a = np.asarray(closed_candles, dtype=float)
        result = {"sweep": False, "bos": False, "choch": False, "fvg": False,
                  "ob": False, "eq_levels": False, "details": [],
                  "fvg_zone": None, "ob_zone": None, "sweep_direction": None}
        if a.ndim != 2 or len(a) < 25 or atr <= 0:
            return result
        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        # Use an earlier reference window, excluding the most recent 3 candles.
        ref_h, ref_l = h[-23:-3], l[-23:-3]
        if len(ref_h) < 10:
            return result

        tol = max(0.10 * atr, 1e-12)
        eqh = any(abs(ref_h[i] - ref_h[j]) <= tol for i in range(len(ref_h)) for j in range(i + 1, len(ref_h)))
        eql = any(abs(ref_l[i] - ref_l[j]) <= tol for i in range(len(ref_l)) for j in range(i + 1, len(ref_l)))
        result["eq_levels"] = bool(eqh or eql)
        if eqh:
            result["details"].append("EQH liquidity pool candidate")
        if eql:
            result["details"].append("EQL liquidity pool candidate")

        prev_high, prev_low = float(np.max(ref_h)), float(np.min(ref_l))
        if h[-1] > prev_high and c[-1] < prev_high:
            result["sweep"], result["sweep_direction"] = True, "SHORT"
            result["details"].append("Bearish liquidity sweep: wick above range, close back below")
        elif l[-1] < prev_low and c[-1] > prev_low:
            result["sweep"], result["sweep_direction"] = True, "LONG"
            result["details"].append("Bullish liquidity sweep: wick below range, close back above")

        ph, pl = self.detect_swings(h[:-1], l[:-1], window=2)
        last_close = float(c[-1])
        broken_high = next((x[1] for x in reversed(ph) if x[0] >= len(h) - 25), None)
        broken_low = next((x[1] for x in reversed(pl) if x[0] >= len(l) - 25), None)
        if broken_high is not None and last_close > broken_high:
            result["bos"] = True
            result["details"].append("Bullish BOS: close above confirmed swing high")
        if broken_low is not None and last_close < broken_low:
            result["bos"] = True
            result["details"].append("Bearish BOS: close below confirmed swing low")

        # CHoCH is only a candidate if recent structure suggests the opposite side was prevailing.
        if len(ph) >= 2 and len(pl) >= 2:
            prev_highs = [x[1] for x in ph[-3:]]
            prev_lows = [x[1] for x in pl[-3:]]
            if len(prev_lows) >= 2 and prev_lows[-1] < prev_lows[-2] and broken_high is not None and last_close > broken_high:
                result["choch"] = True
                result["details"].append("Potential bullish CHoCH after lower-low structure")
            elif len(prev_highs) >= 2 and prev_highs[-1] > prev_highs[-2] and broken_low is not None and last_close < broken_low:
                result["choch"] = True
                result["details"].append("Potential bearish CHoCH after higher-high structure")

        # Recent 3-candle FVGs; retain zone and reject fully mitigated gaps.
        start = max(2, len(a) - 8)
        for i in range(len(a) - 1, start - 1, -1):
            if l[i] > h[i-2] and l[i] - h[i-2] >= 0.15 * atr:
                zlo, zhi = float(h[i-2]), float(l[i])
                if np.min(l[i+1:]) > zlo if i + 1 < len(a) else True:
                    result["fvg"], result["fvg_zone"] = True, [zlo, zhi]
                    result["details"].append(f"Bullish FVG candidate [{zlo:.8g}, {zhi:.8g}]")
                    break
            if h[i] < l[i-2] and l[i-2] - h[i] >= 0.15 * atr:
                zlo, zhi = float(h[i]), float(l[i-2])
                if np.max(h[i+1:]) < zhi if i + 1 < len(a) else True:
                    result["fvg"], result["fvg_zone"] = True, [zlo, zhi]
                    result["details"].append(f"Bearish FVG candidate [{zlo:.8g}, {zhi:.8g}]")
                    break

        # Candidate OB: last opposite candle before a strong displacement that breaks a swing.
        body = np.abs(c - o)
        avg_body = float(np.mean(body[-20:-1])) if len(body) > 20 else float(np.mean(body[:-1]))
        if avg_body > 0:
            for i in range(len(a)-1, max(2, len(a)-6), -1):
                bull_disp = c[i] > o[i] and body[i] >= 1.8 * avg_body and c[i] > np.max(h[max(0, i-5):i])
                bear_disp = c[i] < o[i] and body[i] >= 1.8 * avg_body and c[i] < np.min(l[max(0, i-5):i])
                if bull_disp:
                    for j in range(i-1, max(-1, i-4), -1):
                        if c[j] < o[j]:
                            result["ob"], result["ob_zone"] = True, [float(l[j]), float(h[j])]
                            result["details"].append("Bullish OB candidate: last bearish candle before displacement")
                            break
                elif bear_disp:
                    for j in range(i-1, max(-1, i-4), -1):
                        if c[j] > o[j]:
                            result["ob"], result["ob_zone"] = True, [float(l[j]), float(h[j])]
                            result["details"].append("Bearish OB candidate: last bullish candle before displacement")
                            break
                if result["ob"]:
                    break
        return result

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        debug = []

        def no_trade(reason, **extra):
            out = {"reason": reason, "debug_trace": debug}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw15 = self._array(ohlcv_15m, 40)
        if raw15 is None or len(raw15) < 41:
            return no_trade("بيانات 15M غير صالحة أو لا تكفي بعد استبعاد الشمعة المفتوحة")

        a = raw15[:-1]  # exclude live candle for all signal calculations
        o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        current_price = float(raw15[-1, 4])  # last reported price; may be live-candle close
        atr = self.calculate_atr(h, l, c, 14)
        if not np.isfinite(atr) or atr <= 0 or current_price <= 0:
            return no_trade("ATR أو السعر غير صالح")

        rsi = self.calculate_rsi(c)
        _, _, macd_hist = self.calculate_macd(c)
        avg_vol = float(np.mean(v[-20:]))
        vol_ratio = float(v[-1] / avg_vol) if avg_vol > 0 else 0.0
        ph, pl = self.detect_swings(h, l, 3)
        debug.append(f"15M ATR={atr:.8g}, RSI={rsi:.1f}, volume_ratio={vol_ratio:.2f}")

        # Detect a recent pattern with sensible spacing and a neckline pivot between shoulders.
        pattern = None
        direction = None
        neckline = base = 0.0
        quality = 0
        age = 999
        if len(pl) >= 3 and len(ph) >= 2:
            left, head, right = pl[-3], pl[-2], pl[-1]
            if left[0] < head[0] < right[0] and head[1] < left[1] and head[1] < right[1] and right[0]-left[0] >= 6:
                if abs(left[1]-right[1]) <= 1.5*atr:
                    necks = [x for x in ph if left[0] < x[0] < right[0]]
                    if necks:
                        pattern, direction = "INV_HEAD_SHOULDERS", "LONG"
                        neckline, base, quality = max(x[1] for x in necks), min(left[1], right[1], head[1]), 22
                        age = len(a)-1-right[0]
        if pattern is None and len(pl) >= 2:
            left, right = pl[-2], pl[-1]
            if right[0]-left[0] >= 5 and abs(left[1]-right[1]) <= 1.25*atr:
                necks = [x for x in ph if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "DOUBLE_BOTTOM", "LONG"
                    neckline, base, quality = max(x[1] for x in necks), min(left[1], right[1]), 18
                    age = len(a)-1-right[0]
        if pattern is None and len(ph) >= 3 and len(pl) >= 2:
            left, head, right = ph[-3], ph[-2], ph[-1]
            if left[0] < head[0] < right[0] and head[1] > left[1] and head[1] > right[1] and right[0]-left[0] >= 6:
                if abs(left[1]-right[1]) <= 1.5*atr:
                    necks = [x for x in pl if left[0] < x[0] < right[0]]
                    if necks:
                        pattern, direction = "HEAD_SHOULDERS", "SHORT"
                        neckline, base, quality = min(x[1] for x in necks), max(left[1], right[1], head[1]), 22
                        age = len(a)-1-right[0]
        if pattern is None and len(ph) >= 2:
            left, right = ph[-2], ph[-1]
            if right[0]-left[0] >= 5 and abs(left[1]-right[1]) <= 1.25*atr:
                necks = [x for x in pl if left[0] < x[0] < right[0]]
                if necks:
                    pattern, direction = "DOUBLE_TOP", "SHORT"
                    neckline, base, quality = min(x[1] for x in necks), max(left[1], right[1]), 18
                    age = len(a)-1-right[0]
        if pattern is None:
            return no_trade("لم يُكتشف نموذج هندسي مكتمل بشروط القمم والقيعان", rsi=round(rsi, 2))
        if age > 16:
            return no_trade(f"النموذج قديم: {age} شمعة منذ آخر pivot مؤكد", pattern=pattern, age=age)

        # Breakout/retest state: recent close crosses neckline, with direction-aware candle confirmation.
        recent_c = c[-6:]
        state = "FORMING"
        if direction == "LONG":
            broke = np.any(recent_c > neckline)
            retest = l[-1] <= neckline + 0.25*atr and c[-1] > neckline and c[-1] > o[-1]
            breakout = c[-1] > neckline + 0.35*atr and c[-1] > o[-1]
            if retest and broke:
                state = "RETEST_CONFIRMED"
            elif breakout:
                state = "BREAKOUT_CONFIRMED"
            elif c[-1] < base - 0.35*atr:
                state = "INVALIDATED"
        else:
            broke = np.any(recent_c < neckline)
            retest = h[-1] >= neckline - 0.25*atr and c[-1] < neckline and c[-1] < o[-1]
            breakout = c[-1] < neckline - 0.35*atr and c[-1] < o[-1]
            if retest and broke:
                state = "RETEST_CONFIRMED"
            elif breakout:
                state = "BREAKOUT_CONFIRMED"
            elif c[-1] > base + 0.35*atr:
                state = "INVALIDATED"
        debug.append(f"Pattern={pattern}, direction={direction}, age={age}, state={state}, neckline={neckline:.8g}")
        if state not in ("RETEST_CONFIRMED", "BREAKOUT_CONFIRMED"):
            return no_trade(f"النموذج غير مؤهل أو أُبطل: {state}", pattern=pattern, state=state)

        # Reject chasing; current price must be close to neckline.
        if abs(current_price-neckline) > 1.5*atr:
            return no_trade("تم رفض الإشارة: السعر ابتعد عن خط العنق وأصبح الدخول متأخرًا", pattern=pattern, state=state)

        smc = self.analyze_smc_advanced(a, atr)
        debug.extend(smc["details"])
        bias4 = self._bias(ohlcv_4h, 30) if ohlcv_4h is not None else "NEUTRAL"
        bias1 = self._bias(ohlcv_1h, 30) if ohlcv_1h is not None else "NEUTRAL"
        btc_bias = self._bias(btc_ohlcv_1h, 30) if btc_ohlcv_1h is not None else "NEUTRAL"
        debug.append(f"Bias: 4H={bias4}, 1H={bias1}, BTC1H={btc_bias}")

        # Score is a rule-based quality score, not a probability of winning.
        score = quality
        score += 15 if state == "RETEST_CONFIRMED" else 10
        if vol_ratio >= 1.25:
            score += 8
        elif vol_ratio >= 1.0:
            score += 4
        if direction == "LONG":
            if rsi >= 45 and rsi <= 68: score += 5
            if macd_hist > 0: score += 5
        else:
            if rsi >= 32 and rsi <= 55: score += 5
            if macd_hist < 0: score += 5
        if smc["sweep"] and smc["sweep_direction"] == direction: score += 8
        if smc["bos"]: score += 5
        if smc["choch"]: score += 3
        if smc["fvg"]: score += 3
        if smc["ob"]: score += 3
        if smc["eq_levels"]: score += 2
        expected_bias = "BULLISH" if direction == "LONG" else "BEARISH"
        for bias, pts in ((bias4, 10), (bias1, 8), (btc_bias, 7)):
            if bias == expected_bias: score += pts
            elif bias != "NEUTRAL": score -= pts * 0.65
        score = int(max(0, min(100, round(score))))
        debug.append(f"Rule-based quality score={score}/100 (not win probability)")
        # Hard conflict block: don't send a countertrend signal against both 4H and BTC.
        if bias4 != "NEUTRAL" and btc_bias != "NEUTRAL" and bias4 != expected_bias and btc_bias != expected_bias:
            return no_trade("تعارض قوي: اتجاه 4H والبيتكوين ضد الإشارة", score=score, pattern=pattern)
        if score < 65:
            return no_trade(f"التقييم أقل من الحد الأدنى 65/100: {score}", score=score, pattern=pattern)

        # ATR / pattern-structure stop. Cap excessive risk distance relative to entry.
        if direction == "LONG":
            structural_stop = base - 0.25*atr
            stop = min(structural_stop, current_price - 1.2*atr)
            risk_dist = current_price - stop
            if risk_dist <= 0 or risk_dist > 3.0*atr:
                return no_trade("مسافة وقف الخسارة غير مناسبة بالنسبة إلى ATR", score=score)
            tp1, tp2, tp3 = current_price + risk_dist*1.5, current_price + risk_dist*2.0, current_price + risk_dist*3.0
        else:
            structural_stop = base + 0.25*atr
            stop = max(structural_stop, current_price + 1.2*atr)
            risk_dist = stop - current_price
            if risk_dist <= 0 or risk_dist > 3.0*atr:
                return no_trade("مسافة وقف الخسارة غير مناسبة بالنسبة إلى ATR", score=score)
            tp1, tp2, tp3 = current_price - risk_dist*1.5, current_price - risk_dist*2.0, current_price - risk_dist*3.0
        if min(current_price, stop, tp1, tp2, tp3) <= 0:
            return no_trade("السعر أو الوقف أو الأهداف غير صالحة", score=score)

        risk_usd = self.total_capital*self.risk_per_trade
        qty = risk_usd/risk_dist
        details = {
            "reason": "Signal qualified; rule-based score is not a win probability",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.0",
                "risk_distance": self._round(risk_dist),
                "note": "Quantity is theoretical; account for contract size, leverage, fees and slippage on BingX."
            },
            "setup": f"{pattern} ({state})",
            "pattern_name": pattern,
            "neckline": self._round(neckline),
            "pattern_base_level": self._round(base),
            "state": state,
            "score": score,
            "atr": self._round(atr),
            "rsi": round(rsi, 2),
            "volume_ratio": round(vol_ratio, 2),
            "timeframe_bias": {"4h": bias4, "1h": bias1, "btc_1h": btc_bias},
            "smc": smc,
            "smc_note": " | ".join(smc["details"]) if smc["details"] else "No SMC confirmation detected",
            "debug_trace": debug
        }
        return direction, self._round(current_price), details

    def analyze_market_structure(self, ohlcv_30m, ohlcv_4h=None, ohlcv_1h=None, btc_ohlcv_1h=None):
        # Compatibility wrapper: the third argument is treated as the signal timeframe.
        return self.analyze_multi_timeframe(ohlcv_4h, ohlcv_1h, ohlcv_30m, btc_ohlcv_1h)

    def calculate_risk_management(self, entry_price, stop_loss, direction="LONG"):
        entry, stop = float(entry_price), float(stop_loss)
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return {"allowed_risk_usd": 0.0, "tokens_to_buy": 0.0, "risk_distance": 0.0}
        if direction.upper() == "LONG" and stop >= entry:
            return {"allowed_risk_usd": 0.0, "tokens_to_buy": 0.0, "risk_distance": 0.0}
        if direction.upper() == "SHORT" and stop <= entry:
            return {"allowed_risk_usd": 0.0, "tokens_to_buy": 0.0, "risk_distance": 0.0}
        dist = abs(entry-stop)
        risk_usd = self.total_capital*self.risk_per_trade
        qty = risk_usd/dist if dist > 0 else 0.0
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "risk_distance": round(dist, 8),
            "note": "Theoretical quantity; contract size, leverage, fees and slippage are not included."
        }
