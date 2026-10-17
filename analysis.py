# ============================================================
# MY EXPERT CRYPTO BOT - SELECTIVE ENGINE V16
# SMC structure + liquidity pools + sweep + BOS/MSS + retest
# Compatible with the existing main.py analyze_market_structure API
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.0)

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
            if np.any(a[:, 4] < a[:, 3]) or np.any(a[:, 4] > a[:, 2]):
                return None
            if np.any(a[:, 1] < a[:, 3]) or np.any(a[:, 1] > a[:, 2]):
                return None
            return a
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1.0)
        out = float(values[0])
        for x in values[1:]:
            out = alpha * float(x) + (1.0 - alpha) * out
        return out

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-min(max(1, int(period)), len(tr)):])) if len(tr) else 0.0

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        try:
            entry, stop = float(entry_price), float(stop_loss_price)
            direction = str(direction).upper()
        except (TypeError, ValueError):
            return None
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return None
        if direction not in ("LONG", "SHORT") or self.total_capital <= 0:
            return None
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            return None
        distance = abs(entry - stop)
        if distance <= 0:
            return None
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance
        notional = qty * entry
        target = entry + distance * self.reward_ratio if direction == "LONG" else entry - distance * self.reward_ratio
        if target <= 0 or not np.isfinite(notional):
            return None
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "total_trade_value_usd": round(notional, 2),
            "take_profit_target": self._round(target),
            "reward_ratio": self.reward_ratio,
            "risk_percent": round(self.risk_per_trade * 100, 3),
        }

    def _trend(self, candles):
        closes = candles[:, 4]
        if len(closes) < 25:
            return "NEUTRAL"
        fast_now = self._ema(closes[-30:], 8)
        slow_now = self._ema(closes[-30:], 21)
        fast_prior = self._ema(closes[-35:-5], 8) if len(closes) >= 35 else self._ema(closes[:-5], 8)
        if fast_now is None or slow_now is None or fast_prior is None:
            return "NEUTRAL"
        if fast_now > slow_now and closes[-1] > slow_now and fast_now > fast_prior:
            return "BULLISH"
        if fast_now < slow_now and closes[-1] < slow_now and fast_now < fast_prior:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _rsi(closes, period=14):
        c = np.asarray(closes, dtype=float)
        d = np.diff(c)
        if len(d) < period:
            return 50.0
        # Wilder-like smoothing over the recent window
        gains = np.maximum(d, 0.0)
        losses = np.maximum(-d, 0.0)
        ag = float(np.mean(gains[-period:]))
        al = float(np.mean(losses[-period:]))
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return float(100.0 - 100.0 / (1.0 + ag / al))

    @staticmethod
    def _volume_ratio(volumes, period=14):
        v = np.asarray(volumes, dtype=float)
        if len(v) < period + 1:
            return 0.0
        baseline = float(np.mean(v[-period-1:-1]))
        return float(v[-1] / baseline) if baseline > 0 else 0.0

    @staticmethod
    def _pivots(highs, lows, left=2, right=2):
        """Confirmed pivots only; right-side candles must already be closed."""
        ph, pl = [], []
        for i in range(left, len(highs) - right):
            hwindow = highs[i-left:i+right+1]
            lwindow = lows[i-left:i+right+1]
            if highs[i] == np.max(hwindow) and np.count_nonzero(hwindow == highs[i]) == 1:
                ph.append((i, float(highs[i])))
            if lows[i] == np.min(lwindow) and np.count_nonzero(lwindow == lows[i]) == 1:
                pl.append((i, float(lows[i])))
        return ph, pl

    @staticmethod
    def _liquidity_pools(pivots, atr, tolerance_atr=0.20, min_touches=2):
        """Cluster similar confirmed swing levels into likely liquidity pools."""
        if not pivots or atr <= 0:
            return []
        tol = atr * tolerance_atr
        clusters = []
        for idx, price in pivots:
            found = None
            for group in clusters:
                center = float(np.mean([x[1] for x in group]))
                if abs(price - center) <= tol:
                    found = group
                    break
            if found is None:
                clusters.append([(idx, price)])
            else:
                found.append((idx, price))
        pools = []
        for group in clusters:
            if len(group) >= min_touches:
                prices = [x[1] for x in group]
                pools.append({"level": float(np.mean(prices)), "touches": len(group), "last_index": max(x[0] for x in group)})
        return sorted(pools, key=lambda x: x["last_index"], reverse=True)

    @staticmethod
    def _find_fvgs(candles, max_age=24):
        zones = []
        start = max(2, len(candles) - max_age)
        for i in range(start, len(candles)):
            # Classic three-candle imbalance: candle i does not overlap candle i-2.
            old_high, old_low = float(candles[i-2, 2]), float(candles[i-2, 3])
            new_high, new_low = float(candles[i, 2]), float(candles[i, 3])
            if new_low > old_high:
                zones.append({"type": "BULLISH", "low": old_high, "high": new_low, "index": i})
            elif new_high < old_low:
                zones.append({"type": "BEARISH", "low": new_high, "high": old_low, "index": i})
        return zones

    @staticmethod
    def _fvg_is_valid(zone, candles, direction):
        if not zone or zone["type"] != ("BULLISH" if direction == "LONG" else "BEARISH"):
            return False
        # Reject fully mitigated zones. A zone is considered mitigated if a later candle
        # trades through its far edge; current price can still be inside the zone.
        for j in range(zone["index"] + 1, len(candles)):
            if direction == "LONG" and candles[j, 3] <= zone["low"]:
                return False
            if direction == "SHORT" and candles[j, 2] >= zone["high"]:
                return False
        return True

    @staticmethod
    def _find_order_block(candles, direction, break_index, atr, lookback=8):
        """Find last opposite candle before a meaningful displacement/break."""
        if break_index is None or break_index <= 0 or atr <= 0:
            return None
        op, hi, lo, cl = candles[:, 1], candles[:, 2], candles[:, 3], candles[:, 4]
        displacement = abs(float(cl[break_index] - op[break_index]))
        if displacement < 0.7 * atr:
            return None
        start = max(0, break_index - lookback)
        for i in range(break_index - 1, start - 1, -1):
            if direction == "LONG" and cl[i] < op[i]:
                return {"low": float(lo[i]), "high": float(hi[i]), "index": i}
            if direction == "SHORT" and cl[i] > op[i]:
                return {"low": float(lo[i]), "high": float(hi[i]), "index": i}
        return None

    @staticmethod
    def _zone_distance_atr(zone, price, atr):
        if not zone or atr <= 0:
            return float("inf")
        if zone["low"] <= price <= zone["high"]:
            return 0.0
        return min(abs(price - zone["low"]), abs(price - zone["high"])) / atr

    @staticmethod
    def calculate_liquidation_levels(swing_price, direction="LONG", leverages=(25, 50, 100)):
        """Rough theoretical estimates only, NOT actual exchange liquidation data."""
        levels = []
        try:
            swing_price = float(swing_price)
            for lev in leverages:
                lev = float(lev)
                if swing_price <= 0 or lev <= 1:
                    continue
                mm = 0.005
                px = swing_price * (1 - 1 / lev + mm) if direction == "LONG" else swing_price * (1 + 1 / lev - mm)
                levels.append({"leverage": f"{int(lev)}x", "price": float(px), "estimate_only": True})
        except (TypeError, ValueError):
            return []
        return levels

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw4 = self._array(ohlcv_4h, 28)
        raw1 = self._array(ohlcv_1h, 28)
        raw15 = self._array(ohlcv_15m, 42)
        if raw4 is None or raw1 is None or raw15 is None:
            return no_trade("Invalid or insufficient OHLCV data")

        try:
            # Exclude the latest candle because it may still be forming.
            c4, c1, c15 = raw4[:-1], raw1[:-1], raw15[:-1]
            if min(len(c4), len(c1), len(c15)) < 27:
                return no_trade("Not enough closed candles")

            trend4, trend1 = self._trend(c4), self._trend(c1)
            if trend4 == "NEUTRAL" or trend1 == "NEUTRAL" or trend4 != trend1:
                return no_trade("4H/1H trend unclear or conflicting", trend_4h=trend4, trend_1h=trend1)

            btc_trend = "NOT_PROVIDED"
            if btc_ohlcv_1h is not None:
                btc = self._array(btc_ohlcv_1h, 28)
                if btc is None:
                    return no_trade("BTC OHLCV invalid", trend_4h=trend4, trend_1h=trend1)
                btc_trend = self._trend(btc[:-1])
                # A neutral BTC trend is not treated as bearish/bullish confirmation.
                if btc_trend != trend1:
                    return no_trade("BTC context does not confirm setup", btc_trend=btc_trend, trend_1h=trend1)

            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)
            if entry <= 0 or atr <= 0 or not np.isfinite(atr):
                return no_trade("Invalid price/ATR")
            atr_pct = atr / entry
            volume_ratio = self._volume_ratio(vol, 14)
            rsi = self._rsi(cl, 14)

            piv_hi, piv_lo = self._pivots(hi, lo, 2, 2)
            if len(piv_hi) < 2 or len(piv_lo) < 2:
                return no_trade("Not enough confirmed swing highs/lows")

            # Only pivots confirmed before the latest few bars are used as structure levels.
            usable_hi = [(i, p) for i, p in piv_hi if i <= len(cl) - 5]
            usable_lo = [(i, p) for i, p in piv_lo if i <= len(cl) - 5]
            if len(usable_hi) < 2 or len(usable_lo) < 2:
                return no_trade("No sufficiently old confirmed structure pivots")

            pools_hi = self._liquidity_pools(usable_hi, atr)
            pools_lo = self._liquidity_pools(usable_lo, atr)
            # Last confirmed swing is used for BOS; pools are separately reported as liquidity.
            swing_hi_i, swing_hi = usable_hi[-1]
            swing_lo_i, swing_lo = usable_lo[-1]
            prior_hi = usable_hi[-2][1]
            prior_lo = usable_lo[-2][1]
            direction = "LONG" if trend1 == "BULLISH" else "SHORT"

            # Search for the latest actual crossing of a confirmed swing level.
            # Use a level that existed before the crossing; don't compare every candle to
            # a pivot discovered after the move.
            break_index, break_level, bos = None, None, False
            search_from = max(1, len(cl) - 12)
            for i in range(search_from, len(cl) - 1):
                # A 2-left/2-right pivot is not knowable until two candles
                # AFTER its index have closed. Requiring pi + 2 < i prevents
                # future-candle lookahead when validating a historical BOS.
                prev_hi = [(pi, p) for pi, p in usable_hi if pi + 2 < i]
                prev_lo = [(pi, p) for pi, p in usable_lo if pi + 2 < i]
                if direction == "LONG" and prev_hi:
                    lvl = prev_hi[-1][1]
                    if cl[i] > lvl + 0.05 * atr and cl[i-1] <= lvl:
                        break_index, break_level, bos = i, float(lvl), True
                elif direction == "SHORT" and prev_lo:
                    lvl = prev_lo[-1][1]
                    if cl[i] < lvl - 0.05 * atr and cl[i-1] >= lvl:
                        break_index, break_level, bos = i, float(lvl), True

            # Detect a sweep of an actual prior swing/pool on the latest closed candle.
            # Sweep is informational confirmation; a continuation setup does not require one.
            sweep_level = None
            liquidity_sweep = False
            if direction == "LONG":
                candidates = [p[1] for p in usable_lo if p[0] < len(cl) - 1 and p[1] < cl[-2]]
                candidates += [p["level"] for p in pools_lo if p["level"] < cl[-2]]
                if candidates:
                    candidate = max(candidates)
                    if lo[-1] < candidate and cl[-1] > candidate:
                        liquidity_sweep, sweep_level = True, float(candidate)
            else:
                candidates = [p[1] for p in usable_hi if p[0] < len(cl) - 1 and p[1] > cl[-2]]
                candidates += [p["level"] for p in pools_hi if p["level"] > cl[-2]]
                if candidates:
                    candidate = min(candidates)
                    if hi[-1] > candidate and cl[-1] < candidate:
                        liquidity_sweep, sweep_level = True, float(candidate)

            # FVG/OB must be aligned, recent, not fully mitigated, and near current price.
            fvgs = self._find_fvgs(c15, max_age=24)
            expected_fvg = "BULLISH" if direction == "LONG" else "BEARISH"
            fvg_candidates = [z for z in fvgs if z["type"] == expected_fvg and self._fvg_is_valid(z, c15, direction)]
            fvg = min(fvg_candidates, key=lambda z: self._zone_distance_atr(z, entry, atr)) if fvg_candidates else None
            ob = self._find_order_block(c15, direction, break_index, atr) if break_index is not None else None
            fvg_dist = self._zone_distance_atr(fvg, entry, atr)
            ob_dist = self._zone_distance_atr(ob, entry, atr)
            fvg_ok = bool(fvg and fvg_dist <= 1.0)
            ob_ok = bool(ob and ob_dist <= 1.0)

            # Break and retest must happen in sequence: a later candle revisits the level
            # and closes back in the trend direction. A recent BOS alone is not enough.
            retest = False
            retest_index = None
            if bos and break_index is not None and break_index < len(cl) - 1:
                tol = max(0.08 * atr, break_level * 0.0004)
                for j in range(break_index + 1, len(cl)):
                    if direction == "LONG":
                        touched = lo[j] <= break_level + tol
                        rejected = cl[j] > break_level and cl[j] > op[j]
                    else:
                        touched = hi[j] >= break_level - tol
                        rejected = cl[j] < break_level and cl[j] < op[j]
                    if touched and rejected:
                        retest, retest_index = True, j
                # Require the retest to be the latest candle or the candle immediately before it;
                # otherwise the bot may chase a move after the setup already passed.
                if retest_index is None or retest_index < len(cl) - 2:
                    retest = False

            # Candle-close displacement / momentum filters.
            candle_range = max(float(hi[-1] - lo[-1]), 1e-12)
            body_ratio = abs(float(cl[-1] - op[-1])) / candle_range
            if direction == "LONG":
                momentum_ok = 50.0 <= rsi <= 68.0 and cl[-1] >= cl[-2] and cl[-1] > op[-1]
            else:
                momentum_ok = 32.0 <= rsi <= 50.0 and cl[-1] <= cl[-2] and cl[-1] < op[-1]
            volume_ok = volume_ratio >= 1.25

            # Avoid chasing: if price is too far beyond the broken level, reject.
            chase_distance = abs(entry - break_level) / atr if break_level else float("inf")
            not_chasing = chase_distance <= 1.25

            # Continuation setup requires BOS + retest. A sweep-only reversal is intentionally
            # not auto-traded in this engine; it is shown as context, not a fake confirmation.
            if not bos:
                return no_trade("No recent confirmed BOS", trend_4h=trend4, trend_1h=trend1,
                                liquidity_sweep=liquidity_sweep, sweep_level=self._round(sweep_level) if sweep_level else None)
            if not retest:
                return no_trade("BOS detected but no fresh retest; do not chase", breakout_level=self._round(break_level),
                                trend_4h=trend4, trend_1h=trend1, bos=True, liquidity_sweep=liquidity_sweep)
            if not not_chasing:
                return no_trade("Price too far from breakout level", distance_atr=round(chase_distance, 2),
                                breakout_level=self._round(break_level))
            if not volume_ok:
                return no_trade("Volume confirmation failed", volume_ratio=round(volume_ratio, 2))
            if not momentum_ok or body_ratio < 0.30:
                return no_trade("Closed-candle momentum/body confirmation failed", rsi=round(rsi, 1), body_ratio=round(body_ratio, 2))
            if not (fvg_ok or ob_ok):
                return no_trade("No fresh aligned FVG/OB near entry", fvg_distance_atr=round(fvg_dist, 2) if np.isfinite(fvg_dist) else None,
                                ob_distance_atr=round(ob_dist, 2) if np.isfinite(ob_dist) else None)

            # Structure-based stop, with ATR padding. Do not allow an unrealistically tight stop.
            if direction == "LONG":
                stop_anchor = min(float(np.min(lo[-5:])), break_level)
                stop = stop_anchor - 0.15 * atr
            else:
                stop_anchor = max(float(np.max(hi[-5:])), break_level)
                stop = stop_anchor + 0.15 * atr
            distance = abs(entry - stop)
            risk_pct = distance / entry
            if distance <= 0 or distance > 3.0 * atr or risk_pct > 0.04:
                return no_trade("Structure-based stop is too wide for this setup", risk_percent=round(risk_pct * 100, 2))

            risk = self.calculate_position_size(entry, stop, direction)
            if not risk:
                return no_trade("Risk management rejected setup")

            # Evidence-based score: no inflated starting score. Score is a ranking heuristic,
            # not a win probability. Each point source corresponds to a visible condition.
            score = 0
            score += 25 if bos else 0
            score += 20 if retest else 0
            score += 15 if volume_ratio >= 1.5 else 10
            score += 10 if momentum_ok else 0
            score += 10 if fvg_ok else 0
            score += 10 if ob_ok else 0
            score += 5 if liquidity_sweep else 0
            score += 5 if btc_trend == trend1 else 0
            score = min(95, score)

            # MSS is reported only as a structural shift against the preceding swing sequence;
            # it is not inferred just because BOS happened.
            mss = False
            if direction == "LONG":
                mss = bool(swing_hi < prior_hi and bos)
            else:
                mss = bool(swing_lo > prior_lo and bos)

            # Actual liquidity pools, if found, are displayed separately from theoretical liq estimates.
            bsl = pools_hi[0] if pools_hi else None
            ssl = pools_lo[0] if pools_lo else None
            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "SMC BOS + Retest + Volume/Momentum",
                "score": int(score),
                "trend_4h": trend4,
                "trend_1h": trend1,
                "btc_trend": btc_trend,
                "bos": bool(bos),
                "mss": bool(mss),
                "squeeze_triggered": False,
                "liquidity_sweep": bool(liquidity_sweep),
                "sweep_level": self._round(sweep_level) if sweep_level else None,
                "hit_liquidation_zone": False,
                "liquidation_levels_note": "Not measured; actual liquidation data unavailable",
                "volume_ratio": round(volume_ratio, 2),
                "rsi": round(rsi, 1),
                "atr": self._round(atr),
                "breakout_level": self._round(break_level),
                "retest_confirmed": bool(retest),
                "retest_index": int(retest_index) if retest_index is not None else None,
                "body_ratio": round(body_ratio, 2),
                "fvg": ({"type": fvg["type"], "low": self._round(fvg["low"]), "high": self._round(fvg["high"]),
                         "distance_atr": round(fvg_dist, 2)} if fvg else None),
                "order_block": ({"low": self._round(ob["low"]), "high": self._round(ob["high"]),
                                 "distance_atr": round(ob_dist, 2)} if ob else None),
                "liquidity": {
                    "buy_side_pool": ({"level": self._round(bsl["level"]), "touches": bsl["touches"]} if bsl else None),
                    "sell_side_pool": ({"level": self._round(ssl["level"]), "touches": ssl["touches"]} if ssl else None),
                },
                "signal_type": "CLOSED_CANDLE_CONFIRMED",
                "score_note": "Heuristic confluence score, not probability of profit",
            }
            return direction, self._round(entry), details

        except (ValueError, TypeError, IndexError, FloatingPointError, ZeroDivisionError) as exc:
            return no_trade("Analysis validation error", error=str(exc)[:120])

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
