
# ==========================================
# MY EXPERT CRYPTO BOT
# SELECTIVE SMC + BREAKOUT / RETEST + EDGE
# Version 11.0
# ==========================================

import numpy as np


class StrategyEngine:
    def __init__(
        self,
        capital=10000,
        risk_per_trade=0.01,
        reward_ratio=2.0
    ):
        self.total_capital = float(capital)
        self.risk_per_trade = min(float(risk_per_trade), 0.02)
        self.reward_ratio = float(reward_ratio)

    @staticmethod
    def _valid_ohlcv(data, minimum=25):
        try:
            a = np.asarray(data, dtype=float)
            return (
                a.ndim == 2 and a.shape[0] >= minimum
                and a.shape[1] >= 6
                and np.all(np.isfinite(a[:, :6]))
                and np.all(a[:, 1:5] > 0)
                and np.all(a[:, 2] >= a[:, 3])
                and np.all(a[:, 4] >= a[:, 3])
                and np.all(a[:, 4] <= a[:, 2])
                and np.all(a[:, 5] >= 0)
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _round(price):
        if not np.isfinite(price) or price <= 0:
            return float(price)
        decimals = max(2, min(12, int(-np.floor(np.log10(price))) + 3))
        return round(float(price), decimals)

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1)
        result = float(values[0])
        for value in values[1:]:
            result = alpha * float(value) + (1 - alpha) * result
        return result

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = map(
            lambda x: np.asarray(x, dtype=float),
            (highs, lows, closes)
        )
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(
            h[1:] - l[1:],
            np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1]))
        )
        return float(np.mean(tr[-min(period, len(tr)):])) if len(tr) else 0.0

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        entry, stop = float(entry_price), float(stop_loss_price)
        direction = str(direction).upper()

        if not np.isfinite(entry) or not np.isfinite(stop):
            return None
        if entry <= 0 or stop <= 0 or self.total_capital <= 0:
            return None
        if not 0 < self.risk_per_trade <= 0.02:
            return None
        if direction == "LONG" and stop >= entry:
            return None
        if direction == "SHORT" and stop <= entry:
            return None
        if direction not in ("LONG", "SHORT"):
            return None

        distance = abs(entry - stop)
        if distance <= 0:
            return None

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance
        target = (
            entry + distance * self.reward_ratio
            if direction == "LONG"
            else entry - distance * self.reward_ratio
        )
        if target <= 0:
            return None

        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "total_trade_value_usd": round(qty * entry, 2),
            "take_profit_target": self._round(target),
            "reward_ratio": self.reward_ratio,
            "risk_percent": round(self.risk_per_trade * 100, 3)
        }

    def calculate_risk_management(self, entry_price, stop_loss_price, direction="LONG"):
        return self.calculate_position_size(entry_price, stop_loss_price, direction)

    def _trend(self, candles):
        close = candles[:, 4]
        if len(close) < 25:
            return "NEUTRAL"

        fast = self._ema(close[-30:], 8)
        slow = self._ema(close[-30:], 21)
        previous_fast = self._ema(close[-31:-1], 8) if len(close) >= 31 else fast

        if fast > slow and close[-1] > slow and fast >= previous_fast:
            return "BULLISH"
        if fast < slow and close[-1] < slow and fast <= previous_fast:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _volume_ratio(volumes, period=14):
        if len(volumes) < period + 1:
            return 0.0
        baseline = float(np.mean(volumes[-period-1:-1]))
        return float(volumes[-1] / baseline) if baseline > 0 else 0.0

    @staticmethod
    def _rsi(closes, period=14):
        delta = np.diff(closes)
        if len(delta) < period:
            return 50.0
        gains = np.maximum(delta, 0)
        losses = np.maximum(-delta, 0)
        avg_gain = float(np.mean(gains[-period:]))
        avg_loss = float(np.mean(losses[-period:]))
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _find_fvg(candles):
        # Three-candle imbalance. Returns the most recent detected zone.
        if len(candles) < 3:
            return None
        for i in range(len(candles) - 1, 1, -1):
            older_high = float(candles[i - 2, 2])
            older_low = float(candles[i - 2, 3])
            newer_high = float(candles[i, 2])
            newer_low = float(candles[i, 3])

            if newer_low > older_high:
                return {
                    "type": "BULLISH",
                    "low": older_high,
                    "high": newer_low,
                    "index": i
                }
            if newer_high < older_low:
                return {
                    "type": "BEARISH",
                    "low": newer_high,
                    "high": older_low,
                    "index": i
                }
        return None

    @staticmethod
    def _find_order_block(candles, direction, lookback=8):
        # Simplified OB: last opposing candle before a strong structure break.
        start = max(0, len(candles) - lookback - 2)
        for i in range(len(candles) - 2, start - 1, -1):
            o, h, l, c = candles[i, 1:5]
            if direction == "LONG" and c < o:
                return {"low": float(l), "high": float(h), "index": i}
            if direction == "SHORT" and c > o:
                return {"low": float(l), "high": float(h), "index": i}
        return None

    def analyze_market_structure(
        self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None
    ):
        if not (
            self._valid_ohlcv(ohlcv_4h, 26)
            and self._valid_ohlcv(ohlcv_1h, 26)
            and self._valid_ohlcv(ohlcv_15m, 35)
        ):
            return "NEUTRAL", 0, {"reason": "Insufficient or invalid OHLCV data"}

        try:
            # Exclude the last, potentially incomplete candle.
            c4 = np.asarray(ohlcv_4h, dtype=float)[:-1]
            c1 = np.asarray(ohlcv_1h, dtype=float)[:-1]
            c15 = np.asarray(ohlcv_15m, dtype=float)[:-1]

            trend4, trend1 = self._trend(c4), self._trend(c1)

            if trend4 == "NEUTRAL" or trend1 == "NEUTRAL":
                return "NEUTRAL", 0, {
                    "reason": "Higher timeframe trend unclear",
                    "trend_4h": trend4, "trend_1h": trend1
                }

            if trend4 != trend1:
                return "NEUTRAL", 0, {
                    "reason": "4H and 1H trend mismatch",
                    "trend_4h": trend4, "trend_1h": trend1
                }

            btc_trend = "NOT_PROVIDED"
            if btc_ohlcv_1h is not None:
                if not self._valid_ohlcv(btc_ohlcv_1h, 26):
                    return "NEUTRAL", 0, {"reason": "Invalid BTC context"}
                btc = np.asarray(btc_ohlcv_1h, dtype=float)[:-1]
                btc_trend = self._trend(btc)
                if btc_trend == "NEUTRAL":
                    return "NEUTRAL", 0, {"reason": "BTC trend unclear"}
                if btc_trend != trend1:
                    return "NEUTRAL", 0, {
                        "reason": "BTC direction conflicts with setup",
                        "btc_trend": btc_trend,
                        "trend_1h": trend1
                    }

            o, h, l, c, v = (
                c15[:, 1], c15[:, 2], c15[:, 3], c15[:, 4], c15[:, 5]
            )
            entry = float(c[-1])
            atr = self.calculate_atr(h, l, c, 14)

            if entry <= 0 or atr <= 0:
                return "NEUTRAL", 0, {"reason": "ATR or price invalid"}

            atr_pct = atr / entry
            vol_ratio = self._volume_ratio(v, 14)
            rsi = self._rsi(c, 14)

            # Use older closed candles for levels; recent candles are reserved
            # for detecting a break and subsequent retest.
            level_highs = h[-30:-6]
            level_lows = l[-30:-6]
            if len(level_highs) < 15:
                return "NEUTRAL", 0, {"reason": "Insufficient structure history"}

            resistance = float(np.max(level_highs))
            support = float(np.min(level_lows))

            # Find a recent close crossing the structural level.
            breakout_index = None
            direction = "LONG" if trend1 == "BULLISH" else "SHORT"
            level = resistance if direction == "LONG" else support

            for i in range(max(1, len(c) - 6), len(c) - 1):
                if direction == "LONG":
                    if c[i - 1] <= level and c[i] > level:
                        breakout_index = i
                else:
                    if c[i - 1] >= level and c[i] < level:
                        breakout_index = i

            # Must be a later candle than the breakout candle.
            if breakout_index is None or breakout_index >= len(c) - 1:
                return "NEUTRAL", 0, {
                    "reason": "No recent confirmed structural break",
                    "trend_4h": trend4, "trend_1h": trend1,
                    "volume_ratio": round(vol_ratio, 2)
                }

            tolerance = min(0.003, max(0.0005, atr_pct * 0.20))
            last_o, last_h, last_l, last_c = map(
                float, (o[-1], h[-1], l[-1], c[-1])
            )

            if direction == "LONG":
                retest = (
                    last_l <= level * (1 + tolerance)
                    and last_c > level
                    and last_c > last_o
                    and last_c >= float(c[-2])
                )
            else:
                retest = (
                    last_h >= level * (1 - tolerance)
                    and last_c < level
                    and last_c < last_o
                    and last_c <= float(c[-2])
                )

            if not retest:
                return "NEUTRAL", 0, {
                    "reason": "Breakout found, retest not confirmed",
                    "breakout_level": self._round(level)
                }

            # Momentum and volume filters.
            if vol_ratio < 1.25:
                return "NEUTRAL", 0, {
                    "reason": "Insufficient volume confirmation",
                    "volume_ratio": round(vol_ratio, 2)
                }

            if direction == "LONG" and not 52 <= rsi <= 72:
                return "NEUTRAL", 0, {
                    "reason": "Long momentum filter failed",
                    "rsi": round(rsi, 1)
                }

            if direction == "SHORT" and not 28 <= rsi <= 48:
                return "NEUTRAL", 0, {
                    "reason": "Short momentum filter failed",
                    "rsi": round(rsi, 1)
                }

            fvg = self._find_fvg(c15)
            ob = self._find_order_block(c15, direction)

            fvg_aligned = bool(
                fvg and fvg["type"] == (
                    "BULLISH" if direction == "LONG" else "BEARISH"
                )
            )
            ob_aligned = bool(ob)

            # Conservative structural stop plus ATR buffer.
            if direction == "LONG":
                structural_stop = float(np.min(l[-6:]))
                stop = min(structural_stop, entry - 1.2 * atr) - 0.1 * atr
            else:
                structural_stop = float(np.max(h[-6:]))
                stop = max(structural_stop, entry + 1.2 * atr) + 0.1 * atr

            distance = abs(entry - stop)
            risk_pct = distance / entry

            if distance <= 0 or distance > 3.5 * atr or risk_pct > 0.05:
                return "NEUTRAL", 0, {
                    "reason": "Stop distance unsuitable",
                    "risk_percent": round(risk_pct * 100, 2)
                }

            # Selective SMC requirement: at least one supporting zone,
            # plus a confirmed retest, trend and volume/momentum agreement.
            if not (fvg_aligned or ob_aligned):
                return "NEUTRAL", 0, {
                    "reason": "No aligned FVG or Order Block",
                    "volume_ratio": round(vol_ratio, 2),
                    "rsi": round(rsi, 1)
                }

            rm = self.calculate_position_size(entry, stop, direction)
            if not rm:
                return "NEUTRAL", 0, {"reason": "Risk management rejected setup"}

            # Quality heuristic only, not a win probability.
            score = 65
            score += 10  # 4H and 1H agree
            score += 5   # confirmed closed-candle retest

            if vol_ratio >= 1.5:
                score += 5
            if vol_ratio >= 2.0:
                score += 3
            if fvg_aligned:
                score += 4
            if ob_aligned:
                score += 3
            if btc_trend == trend1:
                score += 5

            score = min(score, 95)

            details = {
                "stop_loss": self._round(stop),
                "risk_management": rm,
                "setup": "Selective SMC + Breakout/Retest",
                "score": score,
                "trend_4h": trend4,
                "trend_1h": trend1,
                "btc_trend": btc_trend,
                "volume_ratio": round(vol_ratio, 2),
                "rsi": round(rsi, 1),
                "atr": self._round(atr),
                "atr_percent": round(atr_pct * 100, 3),
                "breakout_level": self._round(level),
                "support": self._round(support),
                "resistance": self._round(resistance),
                "fvg": (
                    {
                        "type": fvg["type"],
                        "low": self._round(fvg["low"]),
                        "high": self._round(fvg["high"])
                    } if fvg else None
                ),
                "order_block": (
                    {
                        "low": self._round(ob["low"]),
                        "high": self._round(ob["high"])
                    } if ob else None
                ),
                "risk_percent": round(risk_pct * 100, 3),
                "signal_type": "CLOSED_CANDLE_CONFIRMED",
                "note": "Score is a heuristic, not a probability of profit."
            }

            return direction, self._round(entry), details

        except (ValueError, TypeError, IndexError, FloatingPointError) as exc:
            return "NEUTRAL", 0, {
                "reason": "Analysis error",
                "error": str(exc)[:120]
            }

    # Backward-compatible alias for integrations using another method name.
    def analyze_multi_timeframe(
        self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None
    ):
        return self.analyze_market_structure(
            ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h
        )
