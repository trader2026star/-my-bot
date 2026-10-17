# ==========================================
# MY EXPERT CRYPTO BOT - SELECTIVE ENGINE V15
# SMC + TWO-WAY LIQUIDITY SQUEEZE ENGINE (LONG & SHORT)
# BOS/MSS + FVG/OB + LIQUIDATIONS + VOLUME SURGE
# ==========================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = float(capital)
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
        result = float(values[0])
        for value in values[1:]:
            result = alpha * float(value) + (1.0 - alpha) * result
        return result

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-min(int(period), len(tr)):])) if len(tr) else 0.0

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
        if direction == "LONG" and stop >= entry:
            return None
        if direction == "SHORT" and stop <= entry:
            return None
        distance = abs(entry - stop)
        if distance <= 0 or not 0 < self.risk_per_trade <= 0.02:
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
        fast = self._ema(closes[-30:], 8)
        slow = self._ema(closes[-30:], 21)
        prior = self._ema(closes[-31:-1], 8) if len(closes) >= 31 else fast
        if fast is None or slow is None:
            return "NEUTRAL"
        if fast > slow and closes[-1] > slow and fast >= prior:
            return "BULLISH"
        if fast < slow and closes[-1] < slow and fast <= prior:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _rsi(closes, period=14):
        d = np.diff(np.asarray(closes, dtype=float))
        if len(d) < period:
            return 50.0
        gains, losses = np.maximum(d, 0), np.maximum(-d, 0)
        ag, al = float(np.mean(gains[-period:])), float(np.mean(losses[-period:]))
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return float(100 - 100 / (1 + ag / al))

    @staticmethod
    def _volume_ratio(volumes, period=14):
        v = np.asarray(volumes, dtype=float)
        if len(v) < period + 1:
            return 0.0
        baseline = float(np.mean(v[-period-1:-1]))
        return float(v[-1] / baseline) if baseline > 0 else 0.0

    @staticmethod
    def _pivots(highs, lows, left=2, right=2):
        ph, pl = [], []
        for i in range(left, len(highs) - right):
            if highs[i] >= np.max(highs[i-left:i+right+1]) and highs[i] > np.max(highs[i-left:i]):
                ph.append((i, float(highs[i])))
            if lows[i] <= np.min(lows[i-left:i+right+1]) and lows[i] < np.min(lows[i-left:i]):
                pl.append((i, float(lows[i])))
        return ph, pl

    @staticmethod
    def calculate_liquidation_levels(swing_price, direction="LONG", leverages=[25, 50, 100]):
        liq_levels = []
        for lev in leverages:
            maintenance_margin = 0.005
            if direction == "LONG":
                liq = swing_price * (1 - (1 / lev) + maintenance_margin)
            else:
                liq = swing_price * (1 + (1 / lev) - maintenance_margin)
            liq_levels.append({"leverage": f"{lev}x", "price": liq})
        return liq_levels

    @staticmethod
    def _find_fvgs(candles):
        zones = []
        for i in range(2, len(candles)):
            older_high = float(candles[i-2, 2])
            older_low = float(candles[i-2, 3])
            newer_high = float(candles[i, 2])
            newer_low = float(candles[i, 3])
            if newer_low > older_high:
                zones.append({"type": "BULLISH", "low": older_high, "high": newer_low, "index": i})
            elif newer_high < older_low:
                zones.append({"type": "BEARISH", "low": newer_high, "high": older_low, "index": i})
        return zones

    @staticmethod
    def _find_order_block(candles, direction, break_index, lookback=8):
        start = max(0, break_index - lookback)
        for i in range(break_index - 1, start - 1, -1):
            op, hi, lo, cl = map(float, candles[i, 1:5])
            if direction == "LONG" and cl < op:
                return {"low": lo, "high": hi, "index": i}
            if direction == "SHORT" and cl > op:
                return {"low": lo, "high": hi, "index": i}
        return None

    @staticmethod
    def _zone_near_price(zone, price, atr, max_atr=1.5):
        if not zone:
            return False
        if zone["low"] <= price <= zone["high"]:
            return True
        distance = min(abs(price - zone["low"]), abs(price - zone["high"]))
        return distance <= atr * max_atr

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        neutral = ("NEUTRAL", 0, {})
        raw4 = self._array(ohlcv_4h, 27)
        raw1 = self._array(ohlcv_1h, 27)
        raw15 = self._array(ohlcv_15m, 36)
        if raw4 is None or raw1 is None or raw15 is None:
            return "NEUTRAL", 0, {"reason": "Insufficient or invalid OHLCV data"}

        try:
            c4, c1, c15 = raw4[:-1], raw1[:-1], raw15[:-1]
            if min(len(c4), len(c1), len(c15)) < 25:
                return "NEUTRAL", 0, {"reason": "Not enough closed candles"}

            trend4, trend1 = self._trend(c4), self._trend(c1)
            if trend4 == "NEUTRAL" or trend1 == "NEUTRAL" or trend4 != trend1:
                return "NEUTRAL", 0, {"reason": "Higher timeframe trend unclear or conflicting", "trend_4h": trend4, "trend_1h": trend1}

            btc_trend = "NOT_PROVIDED"
            if btc_ohlcv_1h is not None:
                raw_btc = self._array(btc_ohlcv_1h, 27)
                if raw_btc is None:
                    return "NEUTRAL", 0, {"reason": "BTC context unavailable/invalid"}
                btc_trend = self._trend(raw_btc[:-1])
                if btc_trend == "NEUTRAL" or btc_trend != trend1:
                    return "NEUTRAL", 0, {"reason": "BTC trend conflicts with setup", "btc_trend": btc_trend, "trend_1h": trend1}

            op, hi, lo, cl, vol = c15[:, 1], c15[:, 2], c15[:, 3], c15[:, 4], c15[:, 5]
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)
            if entry <= 0 or atr <= 0 or not np.isfinite(atr):
                return "NEUTRAL", 0, {"reason": "Invalid price or ATR"}

            atr_pct = atr / entry
            volume_ratio = self._volume_ratio(vol, 14)
            rsi = self._rsi(cl, 14)
            piv_hi, piv_lo = self._pivots(hi, lo)
            if len(piv_hi) < 2 or len(piv_lo) < 2:
                return "NEUTRAL", 0, {"reason": "Not enough confirmed swing points"}

            eligible_hi = [(i, p) for i, p in piv_hi if i < len(cl) - 4]
            eligible_lo = [(i, p) for i, p in piv_lo if i < len(cl) - 4]
            if not eligible_hi or not eligible_lo:
                return neutral
            swing_high_i, swing_high = eligible_hi[-1]
            swing_low_i, swing_low = eligible_lo[-1]
            prior_high = eligible_hi[-2][1] if len(eligible_hi) >= 2 else swing_high
            prior_low = eligible_lo[-2][1] if len(eligible_lo) >= 2 else swing_low

            direction = "LONG" if trend1 == "BULLISH" else "SHORT"
            level = swing_high if direction == "LONG" else swing_low
            lookback_start = max(1, len(cl) - 7)
            break_index = None
            bos = False
            mss = False
            for i in range(lookback_start, len(cl) - 1):
                if direction == "LONG" and cl[i] > swing_high and cl[i-1] <= swing_high:
                    break_index, bos = i, True
                    mss = swing_high < prior_high and cl[i] > swing_high
                elif direction == "SHORT" and cl[i] < swing_low and cl[i-1] >= swing_low:
                    break_index, bos = i, True
                    mss = swing_low > prior_low and cl[i] < swing_low

            if not bos or break_index is None or break_index >= len(cl) - 1:
                return "NEUTRAL", 0, {"reason": "No recent closed-candle BOS", "trend_4h": trend4, "trend_1h": trend1}

            # ----------------------------------------------------
            # 1. فحص التصفيات الإجبارية للطرفين (Long/Short Liquidations)
            # ----------------------------------------------------
            liq_levels = self.calculate_liquidation_levels(swing_low if direction == "LONG" else swing_high, direction)
            sweep_low = bool(lo[-1] < swing_low and cl[-1] > swing_low)
            sweep_high = bool(hi[-1] > swing_high and cl[-1] < swing_high)
            liquidity_sweep = sweep_low if direction == "LONG" else sweep_high

            hit_liq_zone = False
            for l_info in liq_levels:
                l_price = l_info["price"]
                if direction == "LONG" and lo[-1] <= l_price and cl[-1] > l_price:
                    hit_liq_zone = True
                    break
                elif direction == "SHORT" and hi[-1] >= l_price and cl[-1] < l_price:
                    hit_liq_zone = True
                    break

            # ----------------------------------------------------
            # 2. فحص السكويز بالاتجاهين (Short Squeeze & Long Liquidation Cascade)
            # ----------------------------------------------------
            is_squeeze_triggered = False
            if direction == "LONG":
                # Short Squeeze: كسر المقاومة مع اندفاع سيولة وفوليوم لضغط صفقات البيع
                if cl[-1] > swing_high and volume_ratio >= 1.5 and rsi >= 55:
                    is_squeeze_triggered = True
            elif direction == "SHORT":
                # Long Cascade / Squeeze: كسر الدعم مع اندفاع سيولة لضغط صفقات الشراء
                if cl[-1] < swing_low and volume_ratio >= 1.5 and rsi <= 45:
                    is_squeeze_triggered = True

            tolerance = min(0.003, max(0.0005, atr_pct * 0.20))
            if direction == "LONG":
                retest = lo[-1] <= level * (1 + tolerance) and cl[-1] > level and cl[-1] > op[-1] and cl[-1] >= cl[-2]
                momentum_ok = 52 <= rsi <= 70
            else:
                retest = hi[-1] >= level * (1 - tolerance) and cl[-1] < level and cl[-1] < op[-1] and cl[-1] <= cl[-2]
                momentum_ok = 30 <= rsi <= 48

            if not retest and not is_squeeze_triggered:
                return "NEUTRAL", 0, {"reason": "BOS found but retest or squeeze confirmation failed", "breakout_level": self._round(level)}
            if volume_ratio < 1.25:
                return "NEUTRAL", 0, {"reason": "Volume confirmation failed", "volume_ratio": round(volume_ratio, 2)}
            if not momentum_ok:
                return "NEUTRAL", 0, {"reason": "Momentum filter failed", "rsi": round(rsi, 1)}

            fvg_zones = self._find_fvgs(c15)
            expected_zone = "BULLISH" if direction == "LONG" else "BEARISH"
            fvg = next((z for z in reversed(fvg_zones) if z["type"] == expected_zone and z["index"] >= break_index - 2), None)
            ob = self._find_order_block(c15, direction, break_index)
            fvg_ok = self._zone_near_price(fvg, entry, atr, 1.5)
            ob_ok = self._zone_near_price(ob, entry, atr, 1.5)

            if not (fvg_ok or ob_ok or is_squeeze_triggered):
                return "NEUTRAL", 0, {"reason": "No nearby aligned FVG/Order Block or Squeeze trigger", "volume_ratio": round(volume_ratio, 2)}

            if direction == "LONG":
                recent_structural_low = float(np.min(lo[-6:]))
                stop = min(recent_structural_low, entry - 1.2 * atr) - 0.1 * atr
            else:
                recent_structural_high = float(np.max(hi[-6:]))
                stop = max(recent_structural_high, entry + 1.2 * atr) + 0.1 * atr

            distance = abs(entry - stop)
            risk_pct = distance / entry
            if distance <= 0 or distance > 3.5 * atr or risk_pct > 0.05:
                return "NEUTRAL", 0, {"reason": "Stop distance unsuitable", "risk_percent": round(risk_pct * 100, 2)}

            risk = self.calculate_position_size(entry, stop, direction)
            if not risk:
                return "NEUTRAL", 0, {"reason": "Risk management rejected setup"}

            # احتساب النقاط وتصنيف نمط الإشارة (LONG/SHORT Liquidity Squeeze)
            score = 65 + 8 + 5
            if volume_ratio >= 1.5:
                score += 5
            if fvg_ok:
                score += 4
            if ob_ok:
                score += 4
            if liquidity_sweep:
                score += 4
            if hit_liq_zone:
                score += 5
            if is_squeeze_triggered:
                score += 5
            if btc_trend == trend1:
                score += 4
            score = min(score, 98)

            squeeze_type = "Short Squeeze (Buying Surge)" if direction == "LONG" else "Long Cascade (Selling Surge)"

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": f"SMC + {squeeze_type}",
                "score": int(score),
                "trend_4h": trend4,
                "trend_1h": trend1,
                "btc_trend": btc_trend,
                "bos": bool(bos),
                "mss": bool(mss),
                "squeeze_triggered": bool(is_squeeze_triggered),
                "liquidity_sweep": bool(liquidity_sweep),
                "hit_liquidation_zone": bool(hit_liq_zone),
                "volume_ratio": round(volume_ratio, 2),
                "rsi": round(rsi, 1),
                "atr": self._round(atr),
                "breakout_level": self._round(level),
                "fvg": ({"type": fvg["type"], "low": self._round(fvg["low"]), "high": self._round(fvg["high"])} if fvg else None),
                "order_block": ({"low": self._round(ob["low"]), "high": self._round(ob["high"])} if ob else None),
                "signal_type": "CLOSED_CANDLE_CONFIRMED"
            }
            return direction, self._round(entry), details

        except (ValueError, TypeError, IndexError, FloatingPointError) as exc:
            return "NEUTRAL", 0, {"reason": "Analysis validation error", "error": str(exc)[:120]}

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
