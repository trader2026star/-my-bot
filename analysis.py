# ============================================================
# MY EXPERT CRYPTO BOT - V123.0
# TREND + PULLBACK + RE-ACCUMULATION + ENTRY TIMING ENGINE
#
# LONG ONLY
# Signal-only: DOES NOT execute exchange orders.
#
# Core philosophy:
#   Daily Bias
#       ->
#   4H Structure
#       ->
#   1H Pullback
#       ->
#   Reclaim / MSS
#       ->
#   Timed Entry
#
# HARD PROTECTION:
#   - Anti-Chase Shield
#   - Late Trend Shield
#   - Extended Price Shield
#   - Near High Shield
#   - Weak R:R Shield
#   - Incomplete candle protection
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("V123_SwingTimingEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, **kwargs):
        try:
            self.total_capital = max(1.0, float(capital))
        except Exception:
            self.total_capital = 10000.0

        try:
            self.risk_per_trade = float(risk_per_trade)
        except Exception:
            self.risk_per_trade = 0.01

        self.risk_per_trade = max(0.001, min(0.02, self.risk_per_trade))

        self.min_score = int(kwargs.get("min_score", 72))
        self.max_stop_pct = float(kwargs.get("max_stop_pct", 0.07))
        self.min_stop_pct = float(kwargs.get("min_stop_pct", 0.008))

    # ========================================================
    # BASIC HELPERS
    # ========================================================

    def _safe_float(self, value, default=0.0):
        try:
            value = float(value)
            if math.isfinite(value):
                return value
        except Exception:
            pass
        return default

    def _clip(self, value, low, high):
        return max(low, min(high, value))

    def _to_array(self, ohlcv):
        try:
            arr = np.asarray(ohlcv, dtype=float)
            if arr.ndim != 2 or arr.shape[1] < 6:
                return None
            return arr
        except Exception:
            return None

    def _completed(self, ohlcv, minimum=40):
        """
        Ignore the currently forming candle.
        """
        arr = self._to_array(ohlcv)

        if arr is None or len(arr) < minimum:
            return None

        # Remove current candle because exchange OHLCV may still be forming.
        arr = arr[:-1]

        if len(arr) < minimum:
            return None

        return arr

    def _ema(self, values, period):
        values = np.asarray(values, dtype=float)

        if len(values) < period:
            return float(np.mean(values))

        alpha = 2.0 / (period + 1.0)
        ema = values[0]

        for value in values[1:]:
            ema = alpha * value + (1.0 - alpha) * ema

        return float(ema)

    def _rsi(self, closes, period=14):
        closes = np.asarray(closes, dtype=float)

        if len(closes) <= period:
            return 50.0

        delta = np.diff(closes)

        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(delta)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss <= 1e-12:
            return 100.0

        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def _atr(self, arr, period=14):
        if len(arr) <= period:
            return max(float(arr[-1, 4]) * 0.01, 1e-8)

        highs = arr[:, 2]
        lows = arr[:, 3]
        closes = arr[:, 4]

        prev_close = closes[:-1]

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - prev_close)
        tr3 = np.abs(lows[1:] - prev_close)

        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        if len(tr) < period:
            return max(float(closes[-1]) * 0.01, 1e-8)

        return float(np.mean(tr[-period:]))

    def _volume_ratio(self, arr, period=20):
        if len(arr) < period + 2:
            return 1.0

        volumes = arr[:, 5]

        avg = np.mean(volumes[-period-1:-1])

        if avg <= 0:
            return 1.0

        return float(volumes[-1] / avg)

    def _slope_pct(self, closes, lookback=8):
        if len(closes) < lookback + 1:
            return 0.0

        old = float(closes[-lookback - 1])
        new = float(closes[-1])

        if old <= 0:
            return 0.0

        return (new / old - 1.0) * 100.0

    def _range_high(self, arr, bars):
        bars = min(bars, len(arr))
        return float(np.max(arr[-bars:, 2]))

    def _range_low(self, arr, bars):
        bars = min(bars, len(arr))
        return float(np.min(arr[-bars:, 3]))

    def _bullish_candle(self, arr):
        o = float(arr[-1, 1])
        c = float(arr[-1, 4])
        return c > o

    # ========================================================
    # SWING DETECTION
    # ========================================================

    def _find_recent_swing_low(self, arr, lookback=24):
        data = arr[-min(len(arr), lookback):]

        if len(data) < 5:
            return float(np.min(data[:, 3]))

        lows = data[:, 3]

        candidates = []

        for i in range(2, len(lows) - 2):
            if (
                lows[i] <= lows[i - 1]
                and lows[i] <= lows[i - 2]
                and lows[i] <= lows[i + 1]
                and lows[i] <= lows[i + 2]
            ):
                candidates.append((i, lows[i]))

        if candidates:
            return float(candidates[-1][1])

        return float(np.min(lows))

    def _find_recent_swing_high(self, arr, lookback=24):
        data = arr[-min(len(arr), lookback):]

        if len(data) < 5:
            return float(np.max(data[:, 2]))

        highs = data[:, 2]

        candidates = []

        for i in range(2, len(highs) - 2):
            if (
                highs[i] >= highs[i - 1]
                and highs[i] >= highs[i - 2]
                and highs[i] >= highs[i + 1]
                and highs[i] >= highs[i + 2]
            ):
                candidates.append((i, highs[i]))

        if candidates:
            return float(candidates[-1][1])

        return float(np.max(highs))

    # ========================================================
    # DAILY REGIME
    # ========================================================

    def _daily_analysis(self, arr):
        closes = arr[:, 4]

        price = float(closes[-1])

        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema(closes, min(200, len(closes)))

        rsi = self._rsi(closes, 14)

        slope20 = self._slope_pct(closes[-40:], 8)

        bullish = (
            price > ema20
            and ema20 >= ema50 * 0.995
            and slope20 > -1.0
        )

        strong = (
            price > ema50
            and ema20 >= ema50
            and slope20 > 0
        )

        score = 0

        if price > ema20:
            score += 5

        if price > ema50:
            score += 4

        if ema20 >= ema50:
            score += 3

        if slope20 > 0:
            score += 2

        if 45 <= rsi <= 68:
            score += 1

        score = self._clip(score, 0, 15)

        return {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "slope": slope20,
            "bullish": bullish,
            "strong": strong,
            "score": score,
        }

    # ========================================================
    # 4H STRUCTURE
    # ========================================================

    def _four_hour_analysis(self, arr):
        closes = arr[:, 4]

        price = float(closes[-1])

        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)

        atr = self._atr(arr, 14)

        rsi = self._rsi(closes, 14)

        swing_high = self._find_recent_swing_high(arr, 30)
        swing_low = self._find_recent_swing_low(arr, 30)

        recent_high = self._range_high(arr, 40)
        recent_low = self._range_low(arr, 40)

        bullish_structure = (
            price > ema20
            and ema20 >= ema50 * 0.99
        )

        higher_low = swing_low > recent_low * 0.995

        structure_score = 0

        if price > ema20:
            structure_score += 5

        if ema20 >= ema50:
            structure_score += 4

        if higher_low:
            structure_score += 3

        if 45 <= rsi <= 70:
            structure_score += 2

        if self._slope_pct(closes, 10) > 0:
            structure_score += 1

        structure_score = self._clip(structure_score, 0, 15)

        return {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "atr": atr,
            "rsi": rsi,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "higher_low": higher_low,
            "bullish": bullish_structure,
            "score": structure_score,
        }

    # ========================================================
    # 1H TIMING ENGINE
    # ========================================================

    def _one_hour_analysis(self, arr):
        closes = arr[:, 4]
        highs = arr[:, 2]
        lows = arr[:, 3]

        price = float(closes[-1])

        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)

        atr = self._atr(arr, 14)
        rsi = self._rsi(closes, 14)

        volume_ratio = self._volume_ratio(arr, 20)

        # --------------------------------------------
        # Recent impulse
        # --------------------------------------------

        impulse_low = self._range_low(arr[-36:], 36)

        impulse_high = self._range_high(arr[-36:], 36)

        impulse_range = max(impulse_high - impulse_low, atr)

        # Position inside recent impulse
        position = (price - impulse_low) / impulse_range
        position = self._clip(position, 0, 1)

        # How far from recent high?
        distance_high_pct = (
            (impulse_high - price) / price * 100.0
            if price > 0
            else 0.0
        )

        # --------------------------------------------
        # Pullback detection
        # --------------------------------------------

        local_high = self._range_high(arr[-18:], 18)

        pullback_low = self._range_low(arr[-10:], 10)

        pullback_depth = (
            (local_high - pullback_low) / max(local_high, 1e-8)
        ) * 100.0

        pullback_atr = (
            (local_high - pullback_low) / max(atr, 1e-8)
        )

        # --------------------------------------------
        # Reclaim / MSS
        # --------------------------------------------

        previous_high = self._range_high(arr[-5:-1], 4)

        reclaim = (
            price > previous_high
            and price > ema20
        )

        # Alternative reclaim:
        # current candle breaks previous candle high
        candle_reclaim = (
            float(arr[-1, 4]) > float(arr[-2, 2])
            and float(arr[-1, 4]) > float(arr[-1, 1])
        )

        reclaim = reclaim or candle_reclaim

        # --------------------------------------------
        # Extension from EMA20 in ATR
        # --------------------------------------------

        extension_atr = (
            (price - ema20) / max(atr, 1e-8)
        )

        # --------------------------------------------
        # Recent acceleration
        # --------------------------------------------

        return_6 = 0.0
        return_12 = 0.0

        if len(closes) >= 7:
            return_6 = (
                closes[-1] / closes[-7] - 1.0
            ) * 100.0

        if len(closes) >= 13:
            return_12 = (
                closes[-1] / closes[-13] - 1.0
            ) * 100.0

        # --------------------------------------------
        # Green candle quality
        # --------------------------------------------

        candle_range = max(
            float(highs[-1] - lows[-1]),
            1e-8
        )

        candle_body = abs(
            float(closes[-1] - arr[-1, 1])
        )

        body_ratio = candle_body / candle_range

        bullish_candle = self._bullish_candle(arr)

        # --------------------------------------------
        # Timing score
        # --------------------------------------------

        timing_score = 0

        # Pullback quality
        if 0.7 <= pullback_atr <= 4.5:
            timing_score += 7
        elif 0.4 <= pullback_atr <= 6.0:
            timing_score += 4

        # Entry location
        if 0.35 <= position <= 0.70:
            timing_score += 6
        elif 0.25 <= position <= 0.78:
            timing_score += 3

        # Reclaim
        if reclaim:
            timing_score += 5

        # RSI
        if 45 <= rsi <= 65:
            timing_score += 3
        elif 40 <= rsi <= 70:
            timing_score += 1

        # Volume
        if 1.10 <= volume_ratio <= 2.50:
            timing_score += 2
        elif volume_ratio >= 0.90:
            timing_score += 1

        # Candle
        if bullish_candle and body_ratio >= 0.45:
            timing_score += 2

        timing_score = self._clip(timing_score, 0, 25)

        return {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "atr": atr,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "local_high": local_high,
            "pullback_low": pullback_low,
            "pullback_depth": pullback_depth,
            "pullback_atr": pullback_atr,
            "impulse_low": impulse_low,
            "impulse_high": impulse_high,
            "position": position,
            "distance_high_pct": distance_high_pct,
            "extension_atr": extension_atr,
            "return_6": return_6,
            "return_12": return_12,
            "reclaim": reclaim,
            "body_ratio": body_ratio,
            "bullish_candle": bullish_candle,
            "timing_score": timing_score,
        }

    # ========================================================
    # ANTI-CHASE / LATE ENTRY SHIELD
    # ========================================================

    def _anti_chase(self, daily, four_h, one_h):
        reasons = []

        price = one_h["price"]

        # 1. Excessive extension from EMA20
        if one_h["extension_atr"] > 2.25:
            reasons.append(
                "السعر ممتد أكثر من 2.25 ATR فوق EMA20"
            )

        # 2. Very close to recent high
        if one_h["distance_high_pct"] < 1.0:
            if not one_h["reclaim"]:
                reasons.append(
                    "السعر قريب جداً من القمة بدون Retest/Reclaim"
                )

        # 3. Fast vertical rise
        if one_h["return_6"] > 8.0:
            reasons.append(
                "ارتفاع سريع جداً خلال آخر 6 شموع"
            )

        if one_h["return_12"] > 14.0:
            reasons.append(
                "حركة ممتدة جداً خلال آخر 12 شمعة"
            )

        # 4. RSI exhaustion
        if one_h["rsi"] > 72:
            reasons.append(
                "RSI مرتفع واحتمال مطاردة السعر"
            )

        # 5. No meaningful pullback
        if one_h["pullback_atr"] < 0.50:
            reasons.append(
                "لا يوجد Pullback حقيقي قبل الدخول"
            )

        # 6. Position too high in impulse
        if one_h["position"] > 0.86:
            reasons.append(
                "السعر في الجزء الأخير من الحركة الصاعدة"
            )

        # 7. Daily also too stretched
        daily_extension = (
            (daily["price"] - daily["ema20"])
            / max(
                daily["price"] * 0.01,
                1e-8
            )
        )

        if daily_extension > 3.5:
            reasons.append(
                "الـ Daily ممتد بشكل واضح"
            )

        # Hard rejection
        hard_block = False

        if len(reasons) >= 2:
            hard_block = True

        # Critical single conditions
        if one_h["extension_atr"] > 3.0:
            hard_block = True

        if one_h["rsi"] > 76:
            hard_block = True

        if one_h["position"] > 0.92:
            hard_block = True

        if (
            one_h["return_6"] > 12
            and not one_h["reclaim"]
        ):
            hard_block = True

        return {
            "blocked": hard_block,
            "reasons": reasons,
            "count": len(reasons),
        }

    # ========================================================
    # PHASE DETECTION
    # ========================================================

    def _phase(self, daily, four_h, one_h, shield):
        if shield["blocked"]:
            if (
                one_h["position"] > 0.86
                or one_h["extension_atr"] > 2.25
            ):
                return "LATE_TREND"

            return "EXTENDED"

        if (
            one_h["pullback_atr"] >= 0.7
            and one_h["pullback_atr"] <= 4.5
            and one_h["reclaim"]
        ):
            return "PULLBACK_RECLAIM"

        if (
            one_h["pullback_atr"] >= 0.7
            and not one_h["reclaim"]
        ):
            return "PULLBACK_WAITING"

        if (
            daily["bullish"]
            and four_h["bullish"]
            and one_h["position"] < 0.70
        ):
            return "RE_ACCUMULATION"

        return "TREND"

    # ========================================================
    # RISK MANAGEMENT
    # ========================================================

    def calculate_risk_management(
        self,
        entry,
        stop_loss,
        capital=None,
        risk_per_trade=None
    ):
        entry = self._safe_float(entry)
        stop_loss = self._safe_float(stop_loss)

        if entry <= 0 or stop_loss <= 0:
            return {
                "risk_pct": 0.0,
                "risk_amount": 0.0,
                "position_size": 0.0,
            }

        capital = (
            self.total_capital
            if capital is None
            else max(1.0, float(capital))
        )

        risk_pct = (
            self.risk_per_trade
            if risk_per_trade is None
            else float(risk_per_trade)
        )

        risk_pct = self._clip(risk_pct, 0.001, 0.02)

        stop_pct = abs(entry - stop_loss) / entry

        risk_amount = capital * risk_pct

        position_size = (
            risk_amount / stop_pct
            if stop_pct > 0
            else 0.0
        )

        return {
            "risk_pct": stop_pct * 100.0,
            "risk_amount": risk_amount,
            "position_size": position_size,
        }

    # ========================================================
    # MAIN ANALYSIS
    # ========================================================

    def analyze_market_structure(
        self,
        ohlcv_daily,
        ohlcv_4h=None,
        ohlcv_1h=None,
        asset_type="crypto"
    ):
        try:
            daily = self._completed(
                ohlcv_daily,
                minimum=60
            )

            four_h = self._completed(
                ohlcv_4h,
                minimum=50
            )

            one_h = self._completed(
                ohlcv_1h,
                minimum=50
            )

            if (
                daily is None
                or four_h is None
                or one_h is None
            ):
                return {
                    "signal": "NO TRADE",
                    "score": 0,
                    "reason": "بيانات MTF غير كافية",
                }

            # --------------------------------------------
            # MTF analysis
            # --------------------------------------------

            d = self._daily_analysis(daily)
            h4 = self._four_hour_analysis(four_h)
            h1 = self._one_hour_analysis(one_h)

            # --------------------------------------------
            # Direction protection
            # --------------------------------------------

            if not d["bullish"]:
                return {
                    "signal": "NO TRADE",
                    "score": 30,
                    "phase": "DAILY_NOT_BULLISH",
                    "reason": "التحيز اليومي غير صاعد",
                }

            if not h4["bullish"]:
                return {
                    "signal": "NO TRADE",
                    "score": 40,
                    "phase": "4H_NOT_BULLISH",
                    "reason": "هيكل 4H غير مناسب للشراء",
                }

            # --------------------------------------------
            # Anti chase
            # --------------------------------------------

            shield = self._anti_chase(
                d,
                h4,
                h1
            )

            phase = self._phase(
                d,
                h4,
                h1,
                shield
            )

            # --------------------------------------------
            # Timing score
            # --------------------------------------------

            score = (
                d["score"]
                + h4["score"]
                + h1["timing_score"]
            )

            # Normalize because components total 55
            score = int(
                round(
                    (score / 55.0) * 100.0
                )
            )

            # --------------------------------------------
            # Hard timing requirements
            # --------------------------------------------

            timing_failures = []

            if h1["pullback_atr"] < 0.50:
                timing_failures.append(
                    "لا يوجد Pullback كافٍ"
                )

            if not h1["reclaim"]:
                timing_failures.append(
                    "لا يوجد Reclaim/MSS واضح"
                )

            if h1["position"] > 0.82:
                timing_failures.append(
                    "السعر مرتفع داخل الحركة"
                )

            if h1["extension_atr"] > 2.25:
                timing_failures.append(
                    "السعر ممتد عن EMA20"
                )

            if h1["rsi"] > 72:
                timing_failures.append(
                    "RSI مرتفع"
                )

            # --------------------------------------------
            # Anti chase ALWAYS wins
            # --------------------------------------------

            if shield["blocked"]:
                return {
                    "signal": "NO TRADE",
                    "score": min(score, 68),
                    "phase": phase,
                    "anti_chase": True,
                    "anti_chase_reasons": shield["reasons"],
                    "reason": "تم رفض الدخول بواسطة Anti-Chase Shield",
                    "price": h1["price"],
                    "rsi": h1["rsi"],
                    "volume_ratio": h1["volume_ratio"],
                    "pullback_depth": h1["pullback_depth"],
                    "pullback_atr": h1["pullback_atr"],
                    "extension_atr": h1["extension_atr"],
                    "distance_to_high_pct": h1["distance_high_pct"],
                }

            # --------------------------------------------
            # Require timing confirmation
            # --------------------------------------------

            if timing_failures:
                return {
                    "signal": "NO TRADE",
                    "score": min(score, 71),
                    "phase": phase,
                    "anti_chase": False,
                    "reason": " / ".join(timing_failures),
                    "price": h1["price"],
                    "rsi": h1["rsi"],
                    "volume_ratio": h1["volume_ratio"],
                    "pullback_depth": h1["pullback_depth"],
                    "pullback_atr": h1["pullback_atr"],
                    "extension_atr": h1["extension_atr"],
                    "distance_to_high_pct": h1["distance_high_pct"],
                }

            # --------------------------------------------
            # Entry
            # --------------------------------------------

            price = h1["price"]
            atr = h1["atr"]

            reclaim_level = max(
                h1["ema20"],
                self._range_high(one_h[-5:-1], 4)
            )

            entry_low = min(
                price,
                reclaim_level + atr * 0.05
            )

            entry_high = price

            # --------------------------------------------
            # Structural stop
            # --------------------------------------------

            structural_low = min(
                h1["pullback_low"],
                h4["swing_low"]
            )

            stop_loss = (
                structural_low
                - atr * 0.30
            )

            if stop_loss >= price:
                stop_loss = price - atr * 1.5

            risk_pct = (
                abs(price - stop_loss)
                / price
            ) * 100.0

            # Reject excessive stop
            if risk_pct > self.max_stop_pct * 100.0:
                return {
                    "signal": "NO TRADE",
                    "score": min(score, 70),
                    "phase": "RISK_TOO_HIGH",
                    "reason": (
                        f"وقف هيكلي واسع {risk_pct:.2f}%"
                    ),
                    "price": price,
                    "risk_pct": risk_pct,
                }

            # Avoid ridiculously tight stop
            if risk_pct < self.min_stop_pct * 100.0:
                stop_loss = price - max(
                    atr * 0.9,
                    price * 0.008
                )

                risk_pct = (
                    abs(price - stop_loss)
                    / price
                ) * 100.0

            # --------------------------------------------
            # Targets
            # --------------------------------------------

            resistance_1 = max(
                h1["local_high"],
                h4["swing_high"]
            )

            risk = price - stop_loss

            tp1 = max(
                resistance_1,
                price + risk * 1.5
            )

            tp2 = max(
                price + risk * 2.5,
                tp1 + risk * 0.7
            )

            tp3 = max(
                price + risk * 3.5,
                tp2 + risk * 0.8
            )

            rr1 = (
                (tp1 - price) / risk
                if risk > 0 else 0
            )

            rr2 = (
                (tp2 - price) / risk
                if risk > 0 else 0
            )

            rr3 = (
                (tp3 - price) / risk
                if risk > 0 else 0
            )

            # --------------------------------------------
            # R:R protection
            # --------------------------------------------

            if rr1 < 1.25:
                return {
                    "signal": "NO TRADE",
                    "score": min(score, 70),
                    "phase": "WEAK_RR",
                    "reason": "الهدف الأول قريب جداً من الدخول",
                    "price": price,
                    "risk_pct": risk_pct,
                    "rr_tp1": rr1,
                }

            # --------------------------------------------
            # Final score
            # --------------------------------------------

            bonus = 0

            if h1["reclaim"]:
                bonus += 5

            if (
                1.0 <= h1["volume_ratio"] <= 2.5
            ):
                bonus += 2

            if (
                45 <= h1["rsi"] <= 62
            ):
                bonus += 2

            score = self._clip(
                score + bonus,
                0,
                100
            )

            if score < self.min_score:
                return {
                    "signal": "NO TRADE",
                    "score": score,
                    "phase": phase,
                    "reason": "التوقيت لم يصل للحد المطلوب",
                    "price": price,
                    "risk_pct": risk_pct,
                }

            # --------------------------------------------
            # Position sizing
            # --------------------------------------------

            rm = self.calculate_risk_management(
                price,
                stop_loss
            )

            # --------------------------------------------
            # Final signal
            # --------------------------------------------

            return {
                "signal": "LONG",

                "score": int(score),

                "phase": "PULLBACK_RECLAIM",

                "anti_chase": False,

                "price": price,

                "entry": price,
                "entry_low": entry_low,
                "entry_high": entry_high,

                "stop_loss": stop_loss,

                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,

                "risk_pct": risk_pct,

                "rr_tp1": rr1,
                "rr_tp2": rr2,
                "rr_tp3": rr3,

                "position_size": rm["position_size"],
                "risk_amount": rm["risk_amount"],

                "rsi": h1["rsi"],
                "volume_ratio": h1["volume_ratio"],

                "atr": atr,
                "atr_pct": (
                    atr / price * 100.0
                    if price > 0 else 0
                ),

                "pullback_depth": h1["pullback_depth"],
                "pullback_atr": h1["pullback_atr"],

                "extension_atr": h1["extension_atr"],

                "distance_to_high_pct": (
                    h1["distance_high_pct"]
                ),

                "reclaim": h1["reclaim"],

                "daily_bias": "BULLISH",
                "daily_score": d["score"],

                "four_hour_bias": "BULLISH",
                "four_hour_score": h4["score"],

                "one_hour_score": h1["timing_score"],

                "swing_high": h4["swing_high"],
                "swing_low": h4["swing_low"],

                "reason": (
                    "Daily bullish + 4H structure + "
                    "real pullback + 1H reclaim/MSS + "
                    "entry timing confirmed"
                ),
            }

        except Exception as e:
            logger.exception(
                "V123 analysis error: %s",
                e
            )

            return {
                "signal": "NO TRADE",
                "score": 0,
                "phase": "ERROR",
                "reason": f"Analysis error: {e}",
            }

    # ========================================================
    # COMPATIBILITY WRAPPER
    # ========================================================

    def analyze_multi_timeframe(
        self,
        ohlcv_daily,
        ohlcv_4h=None,
        ohlcv_1h=None,
        asset_type="crypto"
    ):
        return self.analyze_market_structure(
            ohlcv_daily,
            ohlcv_4h,
            ohlcv_1h,
            asset_type
        )

    # ========================================================
    # SIMPLE ALIAS FOR EXISTING MAIN FILES
    # ========================================================

    def analyze(
        self,
        ohlcv_daily,
        ohlcv_4h=None,
        ohlcv_1h=None,
        asset_type="crypto"
    ):
        return self.analyze_market_structure(
            ohlcv_daily,
            ohlcv_4h,
            ohlcv_1h,
            asset_type
        )
