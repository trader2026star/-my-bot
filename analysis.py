# ============================================================
# MY EXPERT CRYPTO BOT - V23.0 Institutional SMC Engine
# Multi-timeframe: 1D Bias -> 4H Structure -> 1H POI -> 15M Trigger
# Signal-only: does NOT place exchange orders.
#
# Compatibility:
# - StrategyEngine.analyze_market_structure(...)
# - StrategyEngine.analyze_multi_timeframe(...)
# - StrategyEngine.calculate_risk_management(...)
# - StrategyEngine.calculate_position_size(...)
# - Existing LONG/SHORT, entry, details return pattern is preserved.
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("AdvancedSMCEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, **kwargs):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0

        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

        # Conservative guardrails; these do not execute orders.
        self.max_stop_pct = 0.08
        self.min_stop_pct = 0.001
        self.min_rr = 1.5
        self.signal_threshold = 72

    @staticmethod
    def _array(data, minimum=20):
        """Validate CCXT OHLCV rows: timestamp, open, high, low, close, volume."""
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
            if np.any(a[:, 2] < np.maximum(a[:, 1], a[:, 4])):
                return None
            if np.any(a[:, 3] > np.minimum(a[:, 1], a[:, 4])):
                return None
            # Avoid malformed, duplicate, or backwards candle timestamps where available.
            if len(a) > 1 and np.any(np.diff(a[:, 0]) < 0):
                return None
            return a
        except Exception:
            return None

    @staticmethod
    def _round(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(value) or value == 0:
            return 0.0
        decimals = max(2, min(12, int(-math.floor(math.log10(abs(value)))) + 3))
        return round(value, decimals)

    @staticmethod
    def _safe_mean(values):
        try:
            x = np.asarray(values, dtype=float)
            x = x[np.isfinite(x)]
            return float(np.mean(x)) if len(x) else 0.0
        except Exception:
            return 0.0

    def calculate_atr(self, highs, lows, closes, period=14):
        try:
            h = np.asarray(highs, dtype=float).reshape(-1)
            l = np.asarray(lows, dtype=float).reshape(-1)
            c = np.asarray(closes, dtype=float).reshape(-1)
            n = min(len(h), len(l), len(c))
            if n < 2:
                return 0.0
            h, l, c = h[-n:], l[-n:], c[-n:]
            tr = np.maximum(
                h[1:] - l[1:],
                np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
            )
            tr = tr[np.isfinite(tr) & (tr >= 0)]
            if len(tr) == 0:
                return 0.0
            return float(np.mean(tr[-max(1, int(period)):]))
        except Exception:
            return 0.0

    def _atr_from_array(self, a, period=14):
        return self.calculate_atr(a[:, 2], a[:, 3], a[:, 4], period)

    @staticmethod
    def _candle_is_bullish(row):
        return float(row[4]) > float(row[1])

    @staticmethod
    def _candle_is_bearish(row):
        return float(row[4]) < float(row[1])

    def detect_fvg(self, ohlcv):
        """
        Detect unfilled three-candle Fair Value Gaps.
        Uses only completed candles (excludes the last, potentially open candle).
        Returns (bullish_found, bearish_found) for compatibility.
        """
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 5 or a.shape[1] < 6:
                return False, False
            end = len(a) - 1  # exclusive: ignore last potentially forming candle
            bullish = bearish = False
            start = max(2, end - 12)
            for i in range(start, end):
                left = a[i - 2]
                middle = a[i - 1]
                right = a[i]
                # A bullish FVG is the gap between left high and right low.
                if right[3] > left[2] and middle[4] > middle[1]:
                    bullish = True
                # A bearish FVG is the gap between right high and left low.
                if right[2] < left[3] and middle[4] < middle[1]:
                    bearish = True
            return bullish, bearish
        except Exception:
            return False, False

    def _latest_fvg(self, a, direction, lookback=30):
        """Return the most recent FVG zone (low, high), or None."""
        try:
            end = len(a) - 1  # completed candles only
            start = max(2, end - int(lookback))
            for i in range(end - 1, start - 1, -1):
                left, middle, right = a[i - 2], a[i - 1], a[i]
                if direction == "bull" and right[3] > left[2] and middle[4] > middle[1]:
                    return float(left[2]), float(right[3])
                if direction == "bear" and right[2] < left[3] and middle[4] < middle[1]:
                    return float(right[2]), float(left[3])
            return None
        except Exception:
            return None

    def detect_true_order_block(self, ohlcv):
        """
        Return approximate bullish and bearish OB reference levels.
        Prefer the last opposite-colour candle before a displacement candle.
        """
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 8 or a.shape[1] < 6:
                raise ValueError("insufficient candles")
            atr = self._atr_from_array(a, 14)
            end = len(a) - 1
            bullish_ob = bearish_ob = None
            start = max(1, end - 20)
            for i in range(end - 1, start - 1, -1):
                current = a[i]
                nxt = a[i + 1]
                body_next = abs(nxt[4] - nxt[1])
                displacement = atr > 0 and body_next >= 0.8 * atr
                if (current[4] < current[1] and nxt[4] > nxt[1]
                        and displacement and bullish_ob is None):
                    bullish_ob = float(min(current[3], current[1], current[4]))
                if (current[4] > current[1] and nxt[4] < nxt[1]
                        and displacement and bearish_ob is None):
                    bearish_ob = float(max(current[2], current[1], current[4]))
                if bullish_ob is not None and bearish_ob is not None:
                    break
            recent = a[max(0, end - 10):end]
            if bullish_ob is None:
                bullish_ob = float(np.min(recent[:, 3]))
            if bearish_ob is None:
                bearish_ob = float(np.max(recent[:, 2]))
            return bullish_ob, bearish_ob
        except Exception:
            try:
                a = np.asarray(ohlcv, dtype=float)
                return float(np.min(a[-10:, 3])), float(np.max(a[-10:, 2]))
            except Exception:
                return 0.0, 0.0

    def _liquidity_levels(self, a, lookback=20):
        end = len(a) - 1
        sample = a[max(0, end - lookback):end]
        if len(sample) < 5:
            return 0.0, 0.0
        return float(np.max(sample[:, 2])), float(np.min(sample[:, 3]))

    def check_liquidity_sweep(self, ohlcv, higher_tf_high=None, higher_tf_low=None):
        """A sweep must pierce a prior level and close back inside it."""
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 20:
                return False, False
            # Use last completed candle; exclude it from reference levels.
            candle = a[-2]
            prior = a[-22:-2]
            prior_low = float(np.min(prior[:, 3]))
            prior_high = float(np.max(prior[:, 2]))
            if higher_tf_low is not None and np.isfinite(higher_tf_low) and higher_tf_low > 0:
                prior_low = min(prior_low, float(higher_tf_low))
            if higher_tf_high is not None and np.isfinite(higher_tf_high) and higher_tf_high > 0:
                prior_high = max(prior_high, float(higher_tf_high))
            swept_low = candle[3] < prior_low and candle[4] > prior_low
            swept_high = candle[2] > prior_high and candle[4] < prior_high
            return bool(swept_low), bool(swept_high)
        except Exception:
            return False, False

    def check_market_structure_shift(self, ohlcv):
        """MSS is true only when a completed candle closes beyond recent structure."""
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or len(a) < 10:
                return False, False
            reference = a[-7:-2]
            close = float(a[-2, 4])
            return bool(close > np.max(reference[:, 2])), bool(close < np.min(reference[:, 3]))
        except Exception:
            return False, False

    def calculate_position_size(self, entry_price, stop_loss):
        """Return units and notional USD. This is not an exchange order or margin estimate."""
        try:
            entry = float(entry_price)
            stop = float(stop_loss)
            if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
                return 0.0, 0.0
            risk_amount = self.total_capital * self.risk_per_trade
            risk_per_unit = abs(entry - stop)
            if risk_per_unit <= 0:
                return 0.0, 0.0
            units = risk_amount / risk_per_unit
            notional = units * entry
            if not np.isfinite(units) or not np.isfinite(notional):
                return 0.0, 0.0
            return self._round(units), self._round(notional)
        except Exception:
            return 0.0, 0.0

    def calculate_risk_management(self, entry_price, stop_loss, direction=None, atr=None, **kwargs):
        """
        Compatibility helper. Returns a risk-management dictionary.
        Supports LONG/SHORT; does not place or modify orders.
        """
        try:
            entry = float(entry_price)
            stop = float(stop_loss)
            side = str(direction or ("LONG" if stop < entry else "SHORT")).upper()
            if entry <= 0 or stop <= 0 or not np.isfinite(entry + stop):
                return {"valid": False, "reason": "سعر الدخول أو وقف الخسارة غير صالح"}
            if side == "LONG" and stop >= entry:
                return {"valid": False, "reason": "وقف LONG يجب أن يكون أسفل الدخول"}
            if side == "SHORT" and stop <= entry:
                return {"valid": False, "reason": "وقف SHORT يجب أن يكون أعلى الدخول"}
            risk = abs(entry - stop)
            r_pct = risk / entry
            if r_pct < self.min_stop_pct or r_pct > self.max_stop_pct:
                return {"valid": False, "reason": "مسافة وقف الخسارة خارج الحدود المسموحة"}
            sign = 1.0 if side == "LONG" else -1.0
            tps = [entry + sign * risk * r for r in (2.0, 3.5, 5.0)]
            units, notional = self.calculate_position_size(entry, stop)
            return {
                "valid": True,
                "stop_loss": self._round(stop),
                "take_profit_1": self._round(tps[0]),
                "take_profit_2": self._round(tps[1]),
                "take_profit_3": self._round(tps[2]),
                "breakeven_trigger": self._round(tps[0]),
                "partial_tp_ratio": 0.5,
                "trailing_stop_active": True,
                "position_sizing": {
                    "units": units,
                    "margin_usd": notional,
                    "notional_usd": notional,
                    "risk_amount_usd": self._round(self.total_capital * self.risk_per_trade),
                },
            }
        except Exception:
            return {"valid": False, "reason": "تعذر حساب إدارة المخاطر"}

    def _trend(self, a):
        """Simple completed-candle trend proxy with EMA-like means and structure."""
        closes = a[:-1, 4]  # exclude possibly open candle
        if len(closes) < 20:
            return 0
        short = float(np.mean(closes[-5:]))
        long = float(np.mean(closes[-20:]))
        last = float(closes[-1])
        if last > short and short > long:
            return 1
        if last < short and short < long:
            return -1
        return 0

    def _volume_ratio(self, a):
        try:
            # Last completed candle against preceding 20 completed candles.
            last_vol = float(a[-2, 5])
            baseline = self._safe_mean(a[-22:-2, 5])
            return (last_vol / baseline) if baseline > 0 else 0.0
        except Exception:
            return 0.0

    def analyze_market_structure(
        self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
        ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs
    ):
        def no_trade(reason, score=0, extra=None):
            details = {"trade_valid": False, "reason": reason, "score": int(max(0, min(100, score)))}
            if extra:
                details.update(extra)
            return "NEUTRAL", 0, details

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات الفريمات الأربعة غير مكتملة")

        d1 = self._array(ohlcv_1d, 25)
        h4 = self._array(ohlcv_4h, 25)
        h1 = self._array(ohlcv_1h, 25)
        m15 = self._array(ohlcv_15m, 30)
        if any(x is None for x in (d1, h4, h1, m15)):
            return no_trade("بيانات الشموع غير صالحة أو عددها أقل من الحد المطلوب")

        # Directional context is never assumed when BTC data was requested but invalid.
        btc_trend = None
        if btc_ohlcv_1d is not None:
            btc = self._array(btc_ohlcv_1d, 25)
            if btc is None:
                return no_trade("بيانات BTC اليومية غير صالحة؛ تم إيقاف الإشارة للحماية")
            btc_trend = self._trend(btc)

        daily_trend = self._trend(d1)
        h4_trend = self._trend(h4)
        h1_trend = self._trend(h1)

        # Completed-candle data.
        candle = m15[-2]
        open_, high, low, close, volume = map(float, (candle[1], candle[2], candle[3], candle[4], candle[5]))
        if close <= 0:
            return no_trade("سعر الإغلاق غير صالح")

        atr = self._atr_from_array(m15[:-1], 14)
        if atr <= 0 or not np.isfinite(atr):
            return no_trade("تعذر حساب ATR بشكل موثوق")

        candle_range = max(high - low, close * 1e-10)
        body_ratio = abs(close - open_) / candle_range
        volume_ratio = self._volume_ratio(m15)
        volume_ok = volume_ratio >= 1.20

        # Structure / liquidity / POI.
        prior_high, prior_low = self._liquidity_levels(m15, 20)
        swept_low, swept_high = self.check_liquidity_sweep(m15)
        mss_bull, mss_bear = self.check_market_structure_shift(m15)
        bull_fvg, bear_fvg = self.detect_fvg(m15)
        bull_fvg_zone = self._latest_fvg(m15, "bull")
        bear_fvg_zone = self._latest_fvg(m15, "bear")
        bull_ob, bear_ob = self.detect_true_order_block(m15)

        # A reaction requires a real candle body; FVG alone is not an entry trigger.
        bull_reaction = close > open_ and body_ratio >= 0.40
        bear_reaction = close < open_ and body_ratio >= 0.40
        near_bull_ob = bull_ob > 0 and low <= bull_ob + 0.35 * atr and close >= bull_ob - 0.15 * atr
        near_bear_ob = bear_ob > 0 and high >= bear_ob - 0.35 * atr and close <= bear_ob + 0.15 * atr
        near_bull_fvg = bool(bull_fvg_zone and low <= bull_fvg_zone[1] and close >= bull_fvg_zone[0])
        near_bear_fvg = bool(bear_fvg_zone and high >= bear_fvg_zone[0] and close <= bear_fvg_zone[1])

        # Scoring is additive and capped, not hard-coded to 99.
        long_score = 0
        short_score = 0
        long_evidence = []
        short_evidence = []

        if daily_trend == 1:
            long_score += 20; long_evidence.append("انحياز يومي صاعد")
        elif daily_trend == -1:
            short_score += 20; short_evidence.append("انحياز يومي هابط")

        if h4_trend == 1:
            long_score += 18; long_evidence.append("اتجاه 4H صاعد")
        elif h4_trend == -1:
            short_score += 18; short_evidence.append("اتجاه 4H هابط")

        if h1_trend == 1:
            long_score += 12; long_evidence.append("اتجاه 1H صاعد")
        elif h1_trend == -1:
            short_score += 12; short_evidence.append("اتجاه 1H هابط")

        if btc_trend == 1:
            long_score += 8; long_evidence.append("سياق BTC اليومي داعم للصعود")
            short_score -= 5
        elif btc_trend == -1:
            short_score += 8; short_evidence.append("سياق BTC اليومي داعم للهبوط")
            long_score -= 5
        elif btc_trend == 0:
            # Neutral BTC is not a bullish default; it adds no points.
            long_evidence.append("BTC محايد")
            short_evidence.append("BTC محايد")

        if swept_low:
            long_score += 14; long_evidence.append("سحب سيولة أسفل القيعان")
        if swept_high:
            short_score += 14; short_evidence.append("سحب سيولة أعلى القمم")
        if mss_bull:
            long_score += 16; long_evidence.append("MSS صاعد")
        if mss_bear:
            short_score += 16; short_evidence.append("MSS هابط")
        if bull_fvg:
            long_score += 7; long_evidence.append("FVG صاعد حديث")
        if bear_fvg:
            short_score += 7; short_evidence.append("FVG هابط حديث")
        if near_bull_ob or near_bull_fvg:
            long_score += 7; long_evidence.append("السعر داخل/قرب منطقة طلب")
        if near_bear_ob or near_bear_fvg:
            short_score += 7; short_evidence.append("السعر داخل/قرب منطقة عرض")
        if bull_reaction:
            long_score += 5; long_evidence.append("شمعة ارتداد صاعدة")
        if bear_reaction:
            short_score += 5; short_evidence.append("شمعة رفض هابطة")
        if volume_ok:
            if close > open_:
                long_score += 5; long_evidence.append("حجم تداول مؤكد")
            elif close < open_:
                short_score += 5; short_evidence.append("حجم تداول مؤكد")

        long_score = int(max(0, min(100, long_score)))
        short_score = int(max(0, min(100, short_score)))

        # Stop placement uses a structural extreme plus ATR buffer.
        # Refuse entries with an implausibly tight/wide stop or poor RR geometry.
        candidates = []
        if daily_trend == h4_trend == h1_trend == 1 and long_score >= self.signal_threshold:
            if (swept_low or near_bull_ob or near_bull_fvg) and mss_bull and bull_reaction and volume_ok:
                structural_low = min(float(np.min(m15[-12:-1, 3])), bull_ob if bull_ob > 0 else low)
                stop = structural_low - 0.35 * atr
                risk = close - stop
                stop_pct = risk / close if close > 0 else 1.0
                if risk > 0 and self.min_stop_pct <= stop_pct <= self.max_stop_pct:
                    candidates.append(("LONG", long_score, stop, long_evidence))

        btc_allows_short = (btc_trend is None or btc_trend == -1)
        if daily_trend == h4_trend == h1_trend == -1 and btc_allows_short and short_score >= self.signal_threshold:
            if (swept_high or near_bear_ob or near_bear_fvg) and mss_bear and bear_reaction and volume_ok:
                structural_high = max(float(np.max(m15[-12:-1, 2])), bear_ob if bear_ob > 0 else high)
                stop = structural_high + 0.35 * atr
                risk = stop - close
                stop_pct = risk / close if close > 0 else 1.0
                if risk > 0 and self.min_stop_pct <= stop_pct <= self.max_stop_pct:
                    candidates.append(("SHORT", short_score, stop, short_evidence))

        if not candidates:
            best = max(long_score, short_score)
            if daily_trend == 0 or h4_trend == 0 or h1_trend == 0:
                reason = "لا توجد محاذاة اتجاهية كافية بين 1D و4H و1H"
            elif not volume_ok:
                reason = "حجم التداول أقل من التأكيد المطلوب"
            elif not (mss_bull or mss_bear):
                reason = "في انتظار كسر هيكل MSS مؤكد على 15M"
            else:
                reason = "لم تكتمل شروط الدخول: منطقة سعرية + شمعة تأكيد + سيولة/هيكل"
            return no_trade(reason, best, {
                "long_score": long_score,
                "short_score": short_score,
                "daily_trend": daily_trend,
                "h4_trend": h4_trend,
                "h1_trend": h1_trend,
                "btc_trend": btc_trend,
                "volume_ratio": self._round(volume_ratio),
            })

        side, score, stop, evidence = max(candidates, key=lambda item: item[1])
        risk_dist = abs(close - stop)
        sign = 1.0 if side == "LONG" else -1.0
        tp1 = close + sign * risk_dist * 2.0
        tp2 = close + sign * risk_dist * 3.5
        tp3 = close + sign * risk_dist * 5.0

        # Validate target orientation and reward/risk before emitting a signal.
        if side == "LONG" and not (stop < close < tp1 < tp2 < tp3):
            return no_trade("مستويات LONG غير منطقية؛ تم منع الإشارة", score)
        if side == "SHORT" and not (tp3 < tp2 < tp1 < close < stop):
            return no_trade("مستويات SHORT غير منطقية؛ تم منع الإشارة", score)

        units, notional = self.calculate_position_size(close, stop)
        risk_amount = self.total_capital * self.risk_per_trade
        if units <= 0 or notional <= 0 or risk_amount <= 0:
            return no_trade("تعذر حساب حجم الصفقة بأمان", score)

        details = {
            "trade_valid": True,
            "reason": "تأكيد V23 SMC متعدد الفريمات: " + " + ".join(evidence),
            "score": int(score),
            "score_label": (
                "قوي" if score >= 85 else
                "جيد" if score >= 78 else
                "مراقبة قوية"
            ),
            "long_score": long_score,
            "short_score": short_score,
            "stop_loss": self._round(stop),
            "entry_zone": {
                "low": self._round(min(close, close - sign * 0.20 * atr)),
                "high": self._round(max(close, close - sign * 0.20 * atr)),
            },
            "atr": self._round(atr),
            "volume_ratio": self._round(volume_ratio),
            "market_context": {
                "daily_trend": daily_trend,
                "h4_trend": h4_trend,
                "h1_trend": h1_trend,
                "btc_trend": btc_trend,
                "liquidity_sweep": "LOW" if swept_low else ("HIGH" if swept_high else "NONE"),
                "mss": "BULLISH" if mss_bull else ("BEARISH" if mss_bear else "NONE"),
                "bullish_fvg": bool(bull_fvg),
                "bearish_fvg": bool(bear_fvg),
                "bullish_ob": self._round(bull_ob),
                "bearish_ob": self._round(bear_ob),
                "prior_high": self._round(prior_high),
                "prior_low": self._round(prior_low),
            },
            "position_sizing": {
                "units": units,
                "margin_usd": notional,  # compatibility: actually notional, not margin
                "notional_usd": notional,
                "risk_amount_usd": self._round(risk_amount),
                "risk_per_trade": self.risk_per_trade,
                "leverage_included": False,
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "breakeven_trigger": self._round(tp1),
                "partial_tp_ratio": 0.5,
                "trailing_stop_active": True,
                "risk_reward": {"tp1": 2.0, "tp2": 3.5, "tp3": 5.0},
            },
            "smc_note": "تحليل إشاري فقط؛ لا يتم إرسال أوامر تداول تلقائية. التقييم ليس احتمال ربح.",
        }
        return side, self._round(close), details

    def analyze_multi_timeframe(self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None,
                                ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs):
        """Compatibility alias for existing main.py integrations."""
        return self.analyze_market_structure(
            ohlcv_15m=ohlcv_15m,
            ohlcv_1h=ohlcv_1h,
            ohlcv_4h=ohlcv_4h,
            ohlcv_1d=ohlcv_1d,
            btc_ohlcv_1d=btc_ohlcv_1d,
            **kwargs
        )
