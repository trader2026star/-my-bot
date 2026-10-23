# ============================================================
# MY EXPERT CRYPTO BOT - INSTITUTIONAL ICT ENGINE V18.0
# Multi-timeframe: 1D bias -> 4H structure -> 1H POI -> 15M trigger
# Compatible API: StrategyEngine.analyze_market_structure(...)
# ============================================================
import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=25):
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
            if np.any(a[:, 1] <= 0) or np.any(a[:, 4] <= 0):
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
    def _closed(data):
        """Assume latest candle may still be open; use all rows except the last."""
        arr = StrategyEngine._array(data, minimum=20)
        return arr[:-1] if arr is not None and len(arr) >= 21 else None

    @staticmethod
    def _atr(arr, period=14):
        if arr is None or len(arr) < 2:
            return 0.0
        h, l, c = arr[:, 2], arr[:, 3], arr[:, 4]
        prev = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
        # Wilder-style smoothing approximation using the latest period.
        if len(tr) < period:
            return float(np.mean(tr))
        return float(np.mean(tr[-period:]))

    @staticmethod
    def _swing_points(values, left=2, right=2, mode="high"):
        vals = np.asarray(values, dtype=float)
        points = []
        for i in range(left, len(vals) - right):
            window = vals[i-left:i+right+1]
            if mode == "high" and vals[i] >= np.max(window) and np.count_nonzero(vals[i] == window) == 1:
                points.append((i, float(vals[i])))
            elif mode == "low" and vals[i] <= np.min(window) and np.count_nonzero(vals[i] == window) == 1:
                points.append((i, float(vals[i])))
        return points

    def _daily_bias(self, arr):
        if arr is None or len(arr) < 15:
            return "NEUTRAL", {"reason": "بيانات يومية غير كافية"}
        c = arr[:, 4]
        ma = float(np.mean(c[-min(20, len(c)):]))
        highs, lows = arr[:, 2], arr[:, 3]
        sh = self._swing_points(highs, mode="high")
        sl = self._swing_points(lows, mode="low")
        structure_up = len(sh) >= 2 and len(sl) >= 2 and sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]
        structure_dn = len(sh) >= 2 and len(sl) >= 2 and sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]
        if c[-1] > ma and c[-1] > c[-2] and (structure_up or not structure_dn):
            return "BULLISH", {"ma20": self._round(ma), "structure_up": structure_up}
        if c[-1] < ma and c[-1] < c[-2] and (structure_dn or not structure_up):
            return "BEARISH", {"ma20": self._round(ma), "structure_down": structure_dn}
        return "NEUTRAL", {"ma20": self._round(ma), "reason": "اتجاه يومي غير حاسم"}

    def _structure_4h(self, arr, bias):
        if arr is None or len(arr) < 20:
            return None
        c, h, l = arr[:, 4], arr[:, 2], arr[:, 3]
        swing_highs = self._swing_points(h, mode="high")
        swing_lows = self._swing_points(l, mode="low")
        if not swing_highs or not swing_lows:
            return None
        last_close = float(c[-1])
        prior_highs = [v for i, v in swing_highs if i < len(arr) - 2]
        prior_lows = [v for i, v in swing_lows if i < len(arr) - 2]
        if not prior_highs or not prior_lows:
            return None
        high_level, low_level = prior_highs[-1], prior_lows[-1]
        if bias == "BULLISH" and last_close > high_level:
            return {"direction": "LONG", "bos": True, "level": high_level, "opposite_level": low_level}
        if bias == "BEARISH" and last_close < low_level:
            return {"direction": "SHORT", "bos": True, "level": low_level, "opposite_level": high_level}
        # Permit a fresh directional MSS only when close crosses the prior opposite swing.
        return {"direction": None, "bos": False, "level": high_level if bias == "BULLISH" else low_level,
                "opposite_level": low_level if bias == "BULLISH" else high_level}

    def _poi_1h(self, arr, direction, price):
        if arr is None or len(arr) < 20:
            return None
        o, h, l, c = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
        # Three-candle FVG; retain only zones that price has not fully crossed.
        fvg = None
        start = max(2, len(arr) - 12)
        for i in range(len(arr) - 1, start - 1, -1):
            if direction == "LONG" and l[i] > h[i-2]:
                lo, hi = float(h[i-2]), float(l[i])
                if price >= lo and price <= hi * 1.01:
                    fvg = {"low": lo, "high": hi, "type": "BULLISH FVG"}
                    break
            if direction == "SHORT" and h[i] < l[i-2]:
                lo, hi = float(h[i]), float(l[i-2])
                if price <= hi and price >= lo * 0.99:
                    fvg = {"low": lo, "high": hi, "type": "BEARISH FVG"}
                    break
        # Order block candidate: last opposite candle before a displacement candle.
        ob = None
        for i in range(len(arr) - 2, max(2, len(arr) - 10), -1):
            body = abs(c[i+1] - o[i+1])
            rng = max(h[i+1] - l[i+1], 1e-12)
            displacement = body / rng >= 0.55
            opposite = (c[i] < o[i]) if direction == "LONG" else (c[i] > o[i])
            follow_through = c[i+1] > h[i] if direction == "LONG" else c[i+1] < l[i]
            if opposite and displacement and follow_through:
                ob = {"low": float(l[i]), "high": float(h[i]), "type": "BULLISH OB" if direction == "LONG" else "BEARISH OB"}
                break
        # At least one real POI must be present; don't claim both when only one exists.
        if not fvg and not ob:
            return None
        return {"fvg": fvg, "ob": ob}

    def _trigger_15m(self, arr, direction):
        if arr is None or len(arr) < 20:
            return None
        o, h, l, c, v = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]
        # Last row of arr passed here is already a closed candle.
        last = len(arr) - 1
        base_vol = float(np.mean(v[max(0, last-15):last])) if last > 0 else 0.0
        vol_ratio = float(v[last] / base_vol) if base_vol > 0 else 0.0
        candle_range = max(float(h[last] - l[last]), 1e-12)
        body_ratio = abs(float(c[last] - o[last])) / candle_range
        if direction == "LONG":
            impulse = c[last] > o[last] and (c[last] - l[last]) / candle_range >= 0.65
            sweep = l[last] < np.min(l[max(0, last-6):last]) and c[last] > np.min(l[max(0, last-6):last])
        else:
            impulse = c[last] < o[last] and (h[last] - c[last]) / candle_range >= 0.65
            sweep = h[last] > np.max(h[max(0, last-6):last]) and c[last] < np.max(h[max(0, last-6):last])
        volume_ok = vol_ratio >= 1.10
        # Avoid treating ordinary candles as a footprint; this is OHLCV proxy only.
        confirmed = bool(impulse and volume_ok and body_ratio >= 0.35)
        return {"confirmed": confirmed, "sweep": bool(sweep), "volume_ratio": round(vol_ratio, 2),
                "close": float(c[last]), "high": float(h[last]), "low": float(l[last]),
                "open": float(o[last]), "body_ratio": round(body_ratio, 3)}

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, ohlcv_btc_1h=None, **kwargs):
        debug = []

        def no_trade(reason, extra=None):
            details = {"reason": reason, "debug_trace": debug}
            if extra:
                details.update(extra)
            return "NEUTRAL", 0.0, details

        # Normalize each series and exclude the latest potentially-open candle.
        a15 = self._closed(ohlcv_15m)
        a1h = self._closed(ohlcv_1h)
        a4h = self._closed(ohlcv_4h)
        a1d = self._closed(ohlcv_1d)
        if any(x is None for x in (a15, a1h, a4h, a1d)):
            return no_trade("بيانات OHLCV غير كافية أو غير صالحة لأحد الفريمات")

        bias, daily_info = self._daily_bias(a1d)
        debug.append(f"1D bias={bias}")
        if bias == "NEUTRAL":
            return no_trade("الانحياز اليومي محايد؛ لا توجد أفضلية واضحة")

        structure = self._structure_4h(a4h, bias)
        if not structure or not structure.get("bos"):
            return no_trade("لا يوجد كسر هيكل مؤكد على 4H في اتجاه الانحياز اليومي")
        direction = structure["direction"]
        debug.append(f"4H BOS={direction}")

        # Optional BTC context; main.py should pass BTC 1H candles.
        btc_bias = "UNAVAILABLE"
        btc_arr = self._closed(ohlcv_btc_1h) if ohlcv_btc_1h is not None else None
        if btc_arr is not None and len(btc_arr) >= 20:
            btc_close = btc_arr[:, 4]
            btc_ma = np.mean(btc_close[-20:])
            btc_bias = "BULLISH" if btc_close[-1] > btc_ma and btc_close[-1] > btc_close[-2] else (
                "BEARISH" if btc_close[-1] < btc_ma and btc_close[-1] < btc_close[-2] else "NEUTRAL")
            if (direction == "LONG" and btc_bias == "BEARISH") or (direction == "SHORT" and btc_bias == "BULLISH"):
                return no_trade("اتجاه BTC يتعارض مع الصفقة المقترحة", {"btc_bias": btc_bias})
        debug.append(f"BTC={btc_bias}")

        raw_price = float(a15[-1, 4])
        poi = self._poi_1h(a1h, direction, raw_price)
        if not poi:
            return no_trade("لا توجد منطقة FVG أو Order Block صالحة وقريبة على 1H")
        debug.append("1H POI found")

        trigger = self._trigger_15m(a15, direction)
        if not trigger or not trigger["confirmed"]:
            return no_trade("تأكيد شمعة 15M والحجم غير مكتمل")
        if direction == "LONG" and trigger["close"] <= trigger["open"]:
            return no_trade("شمعة التأكيد ليست صاعدة")
        if direction == "SHORT" and trigger["close"] >= trigger["open"]:
            return no_trade("شمعة التأكيد ليست هابطة")
        debug.append(f"15M volume={trigger['volume_ratio']}x sweep={trigger['sweep']}")

        entry = float(trigger["close"])
        atr = self._atr(a15, 14)
        if atr <= 0:
            return no_trade("تعذر حساب ATR بصورة سليمة")

        candidates = []
        if poi.get("ob"):
            candidates.append(poi["ob"]["low"] if direction == "LONG" else poi["ob"]["high"])
        if poi.get("fvg"):
            candidates.append(poi["fvg"]["low"] if direction == "LONG" else poi["fvg"]["high"])
        if direction == "LONG":
            structural_stop = min(candidates) if candidates else trigger["low"]
            stop = min(structural_stop - 0.15 * atr, entry - 1.2 * atr)
            risk_dist = entry - stop
        else:
            structural_stop = max(candidates) if candidates else trigger["high"]
            stop = max(structural_stop + 0.15 * atr, entry + 1.2 * atr)
            risk_dist = stop - entry
        if not np.isfinite(risk_dist) or risk_dist <= 0 or risk_dist / entry > 0.08:
            return no_trade("مسافة وقف الخسارة غير مناسبة؛ لا تطارد الصفقة")

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist
        sign = 1 if direction == "LONG" else -1
        tp1 = entry + sign * risk_dist
        tp2 = entry + sign * risk_dist * 1.8
        tp3 = entry + sign * risk_dist * 2.5

        score = 55
        score += 15 if structure.get("bos") else 0
        score += 10 if poi.get("fvg") else 0
        score += 8 if poi.get("ob") else 0
        score += 7 if trigger["volume_ratio"] >= 1.5 else 3
        score += 5 if trigger["sweep"] else 0
        if btc_bias == "UNAVAILABLE":
            score -= 3
        score = int(min(95, max(50, score)))
        # Require multiple confirmations, but avoid falsely presenting score as win probability.
        confirmations = sum([bool(structure.get("bos")), bool(poi.get("fvg")), bool(poi.get("ob")),
                             bool(trigger["confirmed"]), bool(trigger["sweep"]), trigger["volume_ratio"] >= 1.5])
        if confirmations < 3 or score < 75:
            return no_trade("عدد التأكيدات المستقلة غير كافٍ", {"score": score, "confirmations": confirmations})

        rm = {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "position_quantity_estimate": round(qty, 8),
            "take_profit_1": self._round(tp1),
            "take_profit_2": self._round(tp2),
            "take_profit_3": self._round(tp3),
            "reward_ratio": "1:2.5",
            "risk_distance": self._round(risk_dist),
            "note": "الكمية تقديرية قبل مراعاة مواصفات العقد والرسوم والانزلاق؛ تحقق من BingX قبل التنفيذ."
        }
        details = {
            "reason": "Institutional ICT MTF V18.0",
            "setup": "V18.0 Closed-Candle ICT/SMC",
            "direction": direction,
            "score": score,
            "confirmations": confirmations,
            "stop_loss": self._round(stop),
            "risk_management": rm,
            "daily_bias": bias,
            "btc_bias": btc_bias,
            "liquidity_sweep": trigger["sweep"],
            "volume_ratio": trigger["volume_ratio"],
            "fvg": poi.get("fvg"),
            "order_block": poi.get("ob"),
            "smc_note": f"1D={bias} | 4H BOS={direction} | 1H POI=OK | 15M volume={trigger['volume_ratio']}x | sweep={'YES' if trigger['sweep'] else 'NO'} | BTC={btc_bias}",
            "debug_trace": debug
        }
        return direction, self._round(entry), details

    def analyze_multi_timeframe(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        """Compatibility alias for deployments that call the older method name."""
        return self.analyze_market_structure(
            ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_1h, ohlcv_4h=ohlcv_4h, ohlcv_1d=ohlcv_1d, **kwargs
        )

    def calculate_risk_management(self, entry_price, stop_loss, direction="LONG"):
        entry = float(entry_price)
        stop = float(stop_loss)
        dist = entry - stop if str(direction).upper() == "LONG" else stop - entry
        if entry <= 0 or dist <= 0:
            return {}
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / dist
        sign = 1 if str(direction).upper() == "LONG" else -1
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "take_profit_1": self._round(entry + sign * dist),
            "take_profit_2": self._round(entry + sign * dist * 1.8),
            "take_profit_3": self._round(entry + sign * dist * 2.5),
            "reward_ratio": "1:2.5"
        }
