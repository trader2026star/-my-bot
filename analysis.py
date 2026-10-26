# ============================================================
# MY EXPERT CRYPTO BOT - V18.0 Sniper Elite LONG ONLY
# MTF: 1D Bias -> 4H Structure -> 1H Volume Profile -> 15M Trigger
# Signal-only: does NOT place exchange orders.
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0
        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

    @staticmethod
    def _array(data, minimum=20):
        """Validate standard CCXT OHLCV rows: timestamp, open, high, low, close, volume."""
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
            if np.any(np.diff(a[:, 0]) < 0):
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
    def _closed(data, minimum=20):
        """Conservatively exclude the newest candle because it may still be forming."""
        arr = StrategyEngine._array(data, minimum=minimum + 1)
        if arr is None or len(arr) < minimum + 1:
            return None
        closed = arr[:-1]
        return closed if len(closed) >= minimum else None

    def calculate_atr(self, highs, lows, closes, period=14):
        try:
            h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
            n = min(len(h), len(l), len(c))
            if n < 2:
                return 0.0
            h, l, c = h[-n:], l[-n:], c[-n:]
            tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
            if len(tr) == 0:
                return 0.0
            return float(np.mean(tr[-max(1, int(period)):]))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _swing_levels(arr, lookback=12):
        recent = arr[-(lookback + 1):-1] if len(arr) > lookback else arr[:-1]
        if len(recent) < 3:
            return None, None
        return float(np.max(recent[:, 2])), float(np.min(recent[:, 3]))

    def _get_daily_bias(self, ohlcv_1d):
        arr = self._closed(ohlcv_1d, minimum=20)
        if arr is None:
            return False
        closes = arr[:, 4]
        ma20 = float(np.mean(closes[-20:]))
        # Mild trend confirmation avoids treating one candle above MA as enough.
        return bool(closes[-1] > ma20 and closes[-1] >= closes[-4])

    def _check_4h_structure(self, ohlcv_4h):
        arr = self._closed(ohlcv_4h, minimum=20)
        if arr is None:
            return False
        closes = arr[:, 4]
        ma10 = float(np.mean(closes[-10:]))
        swing_high, swing_low = self._swing_levels(arr, 12)
        bullish_momentum = closes[-1] > ma10 and closes[-1] >= closes[-4]
        bullish_break = swing_high is not None and closes[-1] > swing_high
        # Permit a rising structure above the mean, or a confirmed close above recent swing high.
        return bool(bullish_momentum or bullish_break)

    def calculate_volume_profile(self, ohlcv, bins=35):
        """Approximate candle-range volume profile. It is not trade-by-trade exchange volume."""
        arr = self._closed(ohlcv, minimum=20)
        if arr is None:
            return None, None, None
        bins = max(10, min(100, int(bins)))
        highs, lows, volumes = arr[:, 2], arr[:, 3], arr[:, 5]
        min_price, max_price = float(np.min(lows)), float(np.max(highs))
        if not np.isfinite(min_price + max_price) or max_price <= min_price:
            return None, None, None

        edges = np.linspace(min_price, max_price, bins + 1)
        bin_volumes = np.zeros(bins, dtype=float)
        for h, l, v in zip(highs, lows, volumes):
            if v <= 0:
                continue
            candle_range = h - l
            if candle_range <= 0:
                idx = min(bins - 1, max(0, int(np.searchsorted(edges, l, side="right") - 1)))
                bin_volumes[idx] += v
                continue
            first = max(0, min(bins - 1, int(np.searchsorted(edges, l, side="right") - 1)))
            last = max(0, min(bins - 1, int(np.searchsorted(edges, h, side="left"))))
            for b in range(first, last + 1):
                overlap = max(0.0, min(h, edges[b + 1]) - max(l, edges[b]))
                if overlap > 0:
                    bin_volumes[b] += v * overlap / candle_range

        total_vol = float(np.sum(bin_volumes))
        if total_vol <= 0:
            return None, None, None
        poc_idx = int(np.argmax(bin_volumes))
        poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

        target = total_vol * 0.70
        lo_idx = hi_idx = poc_idx
        included = float(bin_volumes[poc_idx])
        while included < target and (lo_idx > 0 or hi_idx < bins - 1):
            below = bin_volumes[lo_idx - 1] if lo_idx > 0 else -1.0
            above = bin_volumes[hi_idx + 1] if hi_idx < bins - 1 else -1.0
            if hi_idx < bins - 1 and (above >= below or lo_idx == 0):
                hi_idx += 1
                included += float(bin_volumes[hi_idx])
            elif lo_idx > 0:
                lo_idx -= 1
                included += float(bin_volumes[lo_idx])
            else:
                break
        val = float(edges[lo_idx])
        vah = float(edges[hi_idx + 1])
        return poc, val, vah

    @staticmethod
    def _bullish_fvg(arr):
        # Three-candle imbalance: low of current candle above high two candles earlier.
        if len(arr) < 3:
            return None
        a, c = arr[-3], arr[-1]
        if c[3] > a[2]:
            return float(a[2]), float(c[3])
        return None

    @staticmethod
    def _bullish_order_block(arr):
        # Latest bearish candle in a short lookback; use its range as a candidate zone only.
        start = max(0, len(arr) - 8)
        for i in range(len(arr) - 2, start - 1, -1):
            row = arr[i]
            if row[4] < row[1]:
                return float(row[3]), float(row[2])
        return None

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        debug = []

        def no_trade(reason, extra=None):
            details = {
                "reason": reason,
                "debug_trace": list(debug),
                "trade_valid": False,
                "score": 0,
                "setup": "V18 Sniper Elite LONG Only",
            }
            if extra:
                details.update(extra)
            return "NEUTRAL", 0, details

        # Require all four timeframes; missing higher-timeframe data must not silently bypass filters.
        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات أحد الفريمات الأربعة غير متوفرة")

        d1 = self._closed(ohlcv_1d, minimum=20)
        h4 = self._closed(ohlcv_4h, minimum=20)
        h1 = self._closed(ohlcv_1h, minimum=20)
        m15 = self._closed(ohlcv_15m, minimum=20)
        if any(x is None for x in (d1, h4, h1, m15)):
            return no_trade("عدد الشموع المغلقة غير كافٍ أو بيانات OHLCV غير صالحة")

        daily_close = float(d1[-1, 4])
        daily_ma20 = float(np.mean(d1[-20:, 4]))
        daily_rising = daily_close >= float(d1[-4, 4])
        if not (daily_close > daily_ma20 and daily_rising):
            debug.append("1D: الانحياز الصاعد غير مؤكد")
            return no_trade("الانحياز اليومي ليس صاعدًا بما يكفي")

        h4_close = float(h4[-1, 4])
        h4_ma10 = float(np.mean(h4[-10:, 4]))
        h4_swing_high, h4_swing_low = self._swing_levels(h4, 12)
        h4_bullish = h4_close > h4_ma10 and h4_close >= float(h4[-4, 4])
        h4_bos = h4_swing_high is not None and h4_close > h4_swing_high
        if not (h4_bullish or h4_bos):
            debug.append("4H: الزخم/الهيكل غير صاعد")
            return no_trade("هيكل 4 ساعات لا يدعم صفقة LONG")

        poc, val, vah = self.calculate_volume_profile(h1)
        if poc is None or val is None or vah is None:
            return no_trade("تعذر حساب Volume Profile على فريم الساعة")

        close = float(m15[-1, 4])
        open_ = float(m15[-1, 1])
        high = float(m15[-1, 2])
        low = float(m15[-1, 3])
        volume = float(m15[-1, 5])
        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, close - open_) / candle_range
        avg_volume = float(np.mean(m15[-16:-1, 5]))
        volume_spike = avg_volume > 0 and volume >= avg_volume * 1.20

        atr = self.calculate_atr(m15[:, 2], m15[:, 3], m15[:, 4], 14)
        if atr <= 0 or not np.isfinite(atr):
            return no_trade("تعذر حساب ATR بصورة صالحة")

        # A usable LONG location is near PoC/VAL or a nearby bullish OB/FVG zone.
        near_profile = (val * 0.997 <= close <= poc * 1.012)
        fvg = self._bullish_fvg(m15)
        ob = self._bullish_order_block(h1)
        near_fvg = bool(fvg and fvg[0] <= close <= fvg[1] + 0.25 * atr)
        near_ob = bool(ob and ob[0] - 0.15 * atr <= close <= ob[1] + 0.15 * atr)
        location_ok = near_profile or near_fvg or near_ob

        # Liquidity sweep: prior low is taken intrabar and price closes back above it.
        recent_lows = m15[-8:-1, 3]
        sweep_level = float(np.min(recent_lows)) if len(recent_lows) else low
        liquidity_sweep = bool(low < sweep_level and close > sweep_level)

        # Basic local bullish structure confirmation (close above previous 5-candle highs).
        prior_high = float(np.max(m15[-6:-1, 2]))
        micro_bos = close > prior_high
        strong_bullish = close > open_ and body_ratio >= 0.45
        not_chasing = close <= poc * 1.025 and close <= vah * 1.005
        momentum_ok = close >= float(m15[-3, 4])

        score = 0
        score += 20  # daily bias confirmed
        score += 15 if h4_bos else (10 if h4_bullish else 0)
        score += 15 if near_profile else (8 if near_ob or near_fvg else 0)
        score += 15 if liquidity_sweep else 0
        score += 15 if micro_bos else 0
        score += 10 if volume_spike else 0
        score += 10 if strong_bullish and momentum_ok else 0
        score = min(100, int(score))
        debug.extend([
            f"1D bullish bias: yes; close={self._round(daily_close)} MA20={self._round(daily_ma20)}",
            f"4H bullish={h4_bullish}; BOS={h4_bos}",
            f"1H PoC={self._round(poc)} VAL={self._round(val)} VAH={self._round(vah)}",
            f"15M sweep={liquidity_sweep}; microBOS={micro_bos}; volumeSpike={volume_spike}; bodyRatio={body_ratio:.2f}",
        ])

        # Quality gates: no signal simply because a score looks high.
        if not location_ok:
            return no_trade("السعر ليس داخل منطقة دخول مناسبة قرب PoC/OB/FVG", {
                "score": score, "smc_note": "الموقع غير مناسب؛ لا تطارد السعر"
            })
        if not not_chasing:
            return no_trade("السعر امتد بعيدًا عن منطقة القيمة؛ تجنب مطاردة الحركة", {
                "score": score, "smc_note": "السعر بعيد عن منطقة الدخول"
            })
        if not strong_bullish or not momentum_ok:
            return no_trade("تأكيد شمعة 15M والزخم الصاعد غير مكتمل", {
                "score": score, "smc_note": "انتظار إغلاق صاعد أقوى"
            })
        if not volume_spike and not liquidity_sweep and not micro_bos:
            return no_trade("لا يوجد تأكيد كافٍ للحجم أو سحب السيولة أو كسر الهيكل", {
                "score": score, "smc_note": "تأكيد السيولة/الهيكل غير كافٍ"
            })
        if score < 65:
            return no_trade("درجة جودة الإشارة أقل من الحد الأدنى 65/100", {
                "score": score, "smc_note": "التأكيدات المستقلة غير كافية"
            })

        # Structural stop: below recent swing/VAL, with ATR buffer; cap risk distance to avoid oversized stops.
        recent_swing_low = float(np.min(m15[-8:, 3]))
        structural_floor = min(recent_swing_low, val)
        stop = min(structural_floor - 0.25 * atr, close - 1.2 * atr)
        risk_dist = close - stop
        if not np.isfinite(risk_dist) or risk_dist <= 0:
            return no_trade("مسافة وقف الخسارة غير صالحة", {"score": score})
        risk_pct = risk_dist / close
        if risk_pct > 0.08:
            return no_trade("مسافة وقف الخسارة أكبر من 8%؛ مخاطرة الصفقة غير مناسبة", {
                "score": score, "risk_distance_pct": round(risk_pct * 100, 2)
            })

        # Position size is a spot-equivalent quantity estimate. Contract multipliers/limits must be checked separately.
        risk_usd = self.total_capital * self.risk_per_trade
        qty_by_risk = risk_usd / risk_dist
        max_notional = self.total_capital * 3.0  # conservative notional cap, not a leverage recommendation
        qty_by_notional = max_notional / close
        qty = min(qty_by_risk, qty_by_notional)
        effective_risk = qty * risk_dist

        # R-multiple targets; round and ensure ordering.
        tp1 = close + risk_dist * 1.0
        tp2 = close + risk_dist * 1.8
        tp3 = close + risk_dist * 2.5
        if not (stop < close < tp1 < tp2 < tp3):
            return no_trade("فشل التحقق من ترتيب مستويات الدخول والوقف والأهداف", {"score": score})

        notes = (
            f"1D Bias صاعد | 4H BOS={'نعم' if h4_bos else 'لا'} | "
            f"PoC={self._round(poc)} VAL={self._round(val)} VAH={self._round(vah)} | "
            f"Sweep={'نعم' if liquidity_sweep else 'لا'} | "
            f"Micro BOS={'نعم' if micro_bos else 'لا'} | Volume Spike={'نعم' if volume_spike else 'لا'}"
        )
        details = {
            "reason": "V18 Sniper Elite: MTF LONG confirmation",
            "trade_valid": True,
            "stop_loss": self._round(stop),
            "risk_distance": self._round(risk_dist),
            "risk_distance_pct": round(risk_pct * 100, 3),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "estimated_risk_usd": round(effective_risk, 2),
                "tokens_to_buy": round(qty, 8),
                "estimated_position_notional_usd": round(qty * close, 2),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": "1:2.5",
            },
            "setup": "V18 MTF Volume Profile + Structure + Liquidity LONG",
            "score": score,
            "smc_note": notes,
            "levels": {
                "poc": self._round(poc),
                "val": self._round(val),
                "vah": self._round(vah),
                "bullish_fvg": [self._round(fvg[0]), self._round(fvg[1])] if fvg else None,
                "bullish_order_block": [self._round(ob[0]), self._round(ob[1])] if ob else None,
                "liquidity_sweep": liquidity_sweep,
                "micro_bos": micro_bos,
            },
            "debug_trace": list(debug),
            "warning": "تقدير فني وليس ضمانًا للربح. حجم الكمية تقديري ويجب التحقق من مواصفات عقد BingX.",
        }
        return "LONG", self._round(close), details
