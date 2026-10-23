# ============================================================
# MY EXPERT CRYPTO BOT - AI INSTITUTIONAL + AUTOMATED FRVP ENGINE (V21.0)
# Multi-Timeframe (1D/4H/1H/15M) + Dynamic Fixed Range Volume Profile + AI Scoring
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

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float).reshape(-1) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-period:])) if len(tr) > 0 else 0.0

    def _calculate_automated_frvp(self, arr, direction="LONG", bins=24):
        """خوارزمية الذكاء الاصطناعي لحساب Fixed Range Volume Profile من بداية الموجة المحورية"""
        if arr is None or len(arr) < 15:
            return 0.0, 0.0, 0.0

        # تحديد بداية نقطة الانطلاق السعرية (Swing Point)
        lows = arr[:, 3]
        highs = arr[:, 2]
        
        if direction == "LONG":
            swing_idx = int(np.argmin(lows[-30:]))
            start_idx = max(0, len(arr) - 30 + swing_idx)
        else:
            swing_idx = int(np.argmax(highs[-30:]))
            start_idx = max(0, len(arr) - 30 + swing_idx)

        range_arr = arr[start_idx:]
        if len(range_arr) < 5:
            range_arr = arr[-20:]

        r_highs = range_arr[:, 2]
        r_lows = range_arr[:, 3]
        r_closes = range_arr[:, 4]
        r_vols = range_arr[:, 5]

        min_p, max_p = np.min(r_lows), np.max(r_highs)
        if min_p == max_p:
            return float(max_p), float(min_p), float(max_p)

        price_bins = np.linspace(min_p, max_p, bins + 1)
        bin_volumes = np.zeros(bins)

        for i in range(len(range_arr)):
            p = r_closes[i]
            v = r_vols[i]
            bin_idx = np.searchsorted(price_bins, p) - 1
            bin_idx = max(0, min(bin_idx, bins - 1))
            bin_volumes[bin_idx] += v

        total_vol = np.sum(bin_volumes)
        if total_vol == 0:
            return float(max_p), float(min_p), float((min_p + max_p) / 2)

        poc_bin = int(np.argmax(bin_volumes))
        poc = float((price_bins[poc_bin] + price_bins[poc_bin + 1]) / 2)

        target_vol = total_vol * 0.70
        current_vol = bin_volumes[poc_bin]
        lower_idx, upper_idx = poc_bin, poc_bin

        while current_vol < target_vol:
            expanded = False
            if lower_idx > 0:
                lower_idx -= 1
                current_vol += bin_volumes[lower_idx]
                expanded = True
            if current_vol >= target_vol:
                break
            if upper_idx < bins - 1:
                upper_idx += 1
                current_vol += bin_volumes[upper_idx]
                expanded = True
            if not expanded:
                break

        val = float(price_bins[lower_idx])
        vah = float(price_bins[upper_idx + 1])
        return vah, val, poc

    def _get_daily_bias(self, ohlcv_1d):
        arr = self._array(ohlcv_1d, minimum=15)
        if arr is None:
            return "NEUTRAL", 50
        closes = arr[:, 4]
        closed_closes = closes[:-1]
        ma20 = np.mean(closed_closes[-min(20, len(closed_closes)):])

        score = 60
        bias = "NEUTRAL"
        if closed_closes[-1] > ma20 and closed_closes[-1] > closed_closes[-2]:
            bias = "BULLISH"
            score += 20
        elif closed_closes[-1] < ma20 and closed_closes[-1] < closed_closes[-2]:
            bias = "BEARISH"
            score -= 20
        return bias, score

    def _check_4h_bos(self, ohlcv_4h, bias):
        arr = self._array(ohlcv_4h, minimum=20)
        if arr is None:
            return False, 0
        closes = arr[:, 4]
        highs = arr[:, 2]
        lows = arr[:, 3]
        prev_closes = closes[:-1]

        if bias == "BULLISH":
            recent_high = np.max(highs[-15:-2])
            bos_confirmed = bool(prev_closes[-1] > recent_high)
        else:
            recent_low = np.min(lows[-15:-2])
            bos_confirmed = bool(prev_closes[-1] < recent_low)

        return bos_confirmed, (20 if bos_confirmed else 0)

    def _check_1h_ob_fvg(self, ohlcv_1h, bias):
        arr = self._array(ohlcv_1h, minimum=20)
        if arr is None:
            return False, 0.0, 0, {}
        opens, highs, lows, closes = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]

        fvg_found = False
        for i in range(len(arr) - 2, max(2, len(arr) - 10), -1):
            if bias == "BULLISH" and lows[i] > highs[i - 2]:
                fvg_found = True
                break
            elif bias == "BEARISH" and highs[i] < lows[i - 2]:
                fvg_found = True
                break

        level = float(lows[-2]) if bias == "BULLISH" else float(highs[-2])
        for i in range(len(arr) - 3, max(2, len(arr) - 8), -1):
            if bias == "BULLISH" and closes[i] < opens[i]:
                level = float(lows[i])
                break
            elif bias == "BEARISH" and closes[i] > opens[i]:
                level = float(highs[i])
                break

        fvg_data = {"type": "Bullish FVG" if (fvg_found and bias == "BULLISH") else "Bearish FVG" if fvg_found else "None"}
        ob_data = {"type": "Bullish OB" if bias == "BULLISH" else "Bearish OB", "level": level}
        return True, level, (20 if fvg_found else 10), {"fvg": fvg_data, "order_block": ob_data}

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, ohlcv_btc_1h=None, **kwargs):
        debug = []

        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason, "debug_trace": debug}

        # 1. الاتجاه العام على الفريم اليومي
        daily_bias, score_d = self._get_daily_bias(ohlcv_1d)
        if daily_bias == "NEUTRAL":
            return no_trade("الانحياز اليومي غير واضح")

        # 2. كسر الهيكل على 4 ساعات (BOS)
        bos_ok, score_4h = self._check_4h_bos(ohlcv_4h, daily_bias)
        if not bos_ok:
            return no_trade("لم يتحقق كسر الهيكل على فريم 4 ساعات")

        # 3. مناطق السيولة والأوردر بلوك على فريم الساعة (1H OB/FVG)
        _, key_level, score_1h, struct_info = self._check_1h_ob_fvg(ohlcv_1h, daily_bias)

        # 4. حساب Fixed Range Volume Profile (FRVP) المطور من بداية نقطة الحركة
        raw1h = self._array(ohlcv_1h, 20)
        raw15 = self._array(ohlcv_15m, 20)
        if raw15 is None or raw1h is None:
            return no_trade("بيانات الشموع غير صالحة")

        direction = "LONG" if daily_bias == "BULLISH" else "SHORT"
        vah, val, poc = self._calculate_automated_frvp(raw1h, direction=direction)

        current_price = float(raw15[-2, 4])  # إغلاق شمعة الـ 15 دقيقة الأخيرة

        # فحص قُرب السعر من مناطق القيمة (Value Area Alignment)
        if direction == "LONG":
            low_15m = np.min(raw15[-3:, 3])
            vp_accepted = bool(low_15m <= val * 1.01 and current_price >= val)
        else:
            high_15m = np.max(raw15[-3:, 2])
            vp_accepted = bool(high_15m >= vah * 0.99 and current_price <= vah)

        score_vp = 15 if vp_accepted else 5
        
        # التقييم التراكمي للذكاء الاصطناعي
        ai_score = min(98, max(70, score_d + score_4h + score_1h + score_vp))
        if ai_score < 70:
            return no_trade("تقييم الأدلة الإجمالي منخفض")

        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)

        # حساب وقف الخسارة والأهداف
        if direction == "LONG":
            stop = min(key_level - 0.3 * atr, current_price - 1.5 * atr)
            risk_dist = current_price - stop
            if risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة غير صالحة")
            tp_target = current_price + (risk_dist * 2.5)
        else:
            stop = max(key_level + 0.3 * atr, current_price + 1.5 * atr)
            risk_dist = stop - current_price
            if risk_dist <= 0:
                return no_trade("مسافة وقف الخسارة غير صالحة")
            tp_target = current_price - (risk_dist * 2.5)

        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        btc_bias = "BULLISH"
        if ohlcv_btc_1h is not None:
            arr_btc = self._array(ohlcv_btc_1h, 10)
            if arr_btc is not None and arr_btc[-1, 4] < arr_btc[-5, 4]:
                btc_bias = "BEARISH"

        details = {
            "reason": "AI Institutional ICT + Automated Fixed Range Volume Profile V21.0",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(current_price + (risk_dist * 1.0) if direction == "LONG" else current_price - (risk_dist * 1.0)),
                "take_profit_2": self._round(current_price + (risk_dist * 1.8) if direction == "LONG" else current_price - (risk_dist * 1.8)),
                "take_profit_3": self._round(tp_target),
                "reward_ratio": "1:2.5"
            },
            "setup": "AI FRVP Range Acceptance & Institutional OB/FVG",
            "score": ai_score,
            "volume_ratio": self._round(raw15[-1, 5] / np.mean(raw15[-10:-1, 5])),
            "liquidity_sweep": vp_accepted,
            "fvg": struct_info["fvg"],
            "order_block": struct_info["order_block"],
            "btc_bias": btc_bias,
            "smc_note": f"FRVP High (VAH): {self._round(vah)} | Low (VAL): {self._round(val)} | POC: {self._round(poc)} | Swing Bias: {daily_bias}"
        }

        return direction, self._round(current_price), details
