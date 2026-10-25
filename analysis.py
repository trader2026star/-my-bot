# ============================================================
# MY EXPERT CRYPTO BOT - MTF VOLUME PROFILE & PoC (V17.0 - Sniper Elite)
# Timeframes: 1D (Bias) -> 4H (Structure) -> 1H (Volume Profile PoC) -> 15M (Execution & Volume Spike)
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)

    @staticmethod
    def _array(data, minimum=20):
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

    def _get_daily_bias(self, ohlcv_1d):
        """1. الفريم اليومي (1D): تحديد الاتجاه العام (BULLISH Bias)"""
        arr = self._array(ohlcv_1d, minimum=15)
        if arr is None:
            return False
        closes = arr[:, 4]
        ma20 = np.mean(closes[-20:])
        return bool(closes[-1] > ma20)

    def _check_4h_structure(self, ohlcv_4h):
        """2. فريم 4 ساعات (4H): تأكيد الهيكل والزخم المتوسط"""
        arr = self._array(ohlcv_4h, minimum=20)
        if arr is None:
            return False
        closes = arr[:, 4]
        ma10 = np.mean(closes[-10:])
        return bool(closes[-1] > ma10)

    def calculate_volume_profile(self, ohlcv, bins=35):
        """3. فريم الساعة (1H): حساب ملف الحجم، نقطة التحكم (PoC)، ومنطقة القيمة (VAL)"""
        arr = self._array(ohlcv, minimum=20)
        if arr is None:
            return None, None, None
        
        highs = arr[:, 2]
        lows = arr[:, 3]
        volumes = arr[:, 5]
        
        min_price = np.min(lows)
        max_price = np.max(highs)
        if min_price == max_price:
            return None, None, None
            
        bin_edges = np.linspace(min_price, max_price, bins + 1)
        bin_volumes = np.zeros(bins)
        
        for i in range(len(arr)):
            h, l, v = highs[i], lows[i], volumes[i]
            if v <= 0:
                continue
            for b in range(bins):
                b_low, b_high = bin_edges[b], bin_edges[b+1]
                overlap = max(0.0, min(h, b_high) - max(l, b_low))
                candle_range = h - l if h > l else 1.0
                bin_volumes[b] += v * (overlap / candle_range)
                
        poc_index = np.argmax(bin_volumes)
        poc_price = (bin_edges[poc_index] + bin_edges[poc_index+1]) / 2.0
        
        total_vol = np.sum(bin_volumes)
        if total_vol <= 0:
            return float(poc_price), float(min_price), float(max_price)
            
        target_vol = total_vol * 0.70
        current_vol = bin_volumes[poc_index]
        lower_idx = poc_index
        upper_idx = poc_index
        
        while current_vol < target_vol and (lower_idx > 0 or upper_idx < bins - 1):
            vol_below = bin_volumes[lower_idx - 1] if lower_idx > 0 else -1
            vol_above = bin_volumes[upper_idx + 1] if upper_idx < bins - 1 else -1
            
            if vol_above >= vol_below and upper_idx < bins - 1:
                upper_idx += 1
                current_vol += bin_volumes[upper_idx]
            elif lower_idx > 0:
                lower_idx -= 1
                current_vol += bin_volumes[lower_idx]
            else:
                break
                
        val = bin_edges[lower_idx]
        vah = bin_edges[upper_idx + 1]
        return float(poc_price), float(val), float(vah)

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, **kwargs):
        debug = []

        def no_trade(reason):
            return "NEUTRAL", 0, {"reason": reason, "debug_trace": debug}

        # الخطوة 1: التحقق من الانحياز اليومي (1D)
        if ohlcv_1d is not None and not self._get_daily_bias(ohlcv_1d):
            return no_trade("الانحياز اليومي (1D) ليس صاعداً")

        # الخطوة 2: التحقق من هيكل 4 ساعات (4H)
        if ohlcv_4h is not None and not self._check_4h_structure(ohlcv_4h):
            return no_trade("هيكل فريم 4 ساعات غير داعم للصعود")

        # الخطوة 3: حساب ملف الحجم على فريم الساعة (1H)
        source_1h = ohlcv_1h if ohlcv_1h is not None else ohlcv_15m
        poc, val, vah = self.calculate_volume_profile(source_1h)
        if poc is None:
            return no_trade("تعذر حساب نقاط ملف الحجم (Volume Profile)")

        raw15 = self._array(ohlcv_15m, 20)
        if raw15 is None:
            return no_trade("بيانات 15 دقيقة غير صالحة")
            
        current_price = float(raw15[-1, 4])
        last_candle = raw15[-1]
        o, h, l, c, v = last_candle[1], last_candle[2], last_candle[3], last_candle[4], last_candle[5]
        
        # الخطوة 4: فريم 15 دقيقة (التنفيذ + فلتر تدفق السيولة المؤسسية Volume Spike)
        avg_volume_15m = np.mean(raw15[-15:, 5])
        has_volume_spike = v >= (avg_volume_15m * 1.25) # يجب أن يكون حجم الشمعة أعلى من المتوسط بنسبة 25%
        
        candle_range = h - l if h > l else 1.0
        is_strong_bullish = c > o and ((c - o) / candle_range) >= 0.60
        near_key_node = (current_price <= poc * 1.008) and (current_price >= val * 0.992)
        
        if not (near_key_node and is_strong_bullish and has_volume_spike):
            return no_trade("شروط القناص لم تتكتمل على 15M (السعر، عزم الشمعة، أو تدفق الفوليوم)")

        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)
        stop = min(val - 0.5 * atr, current_price - 1.5 * atr)
        risk_dist = current_price - stop
        if risk_dist <= 0:
            return no_trade("مسافة الوقف غير صالحة")

        tp_target = current_price + (risk_dist * 2.5)
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "MTF Volume Profile PoC Sniper Strategy (1D+4H+1H+15M)",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(current_price + (risk_dist * 1.0)),
                "take_profit_2": self._round(current_price + (risk_dist * 1.8)),
                "take_profit_3": self._round(tp_target),
                "reward_ratio": "1:2.5"
            },
            "setup": "Full MTF Alignment + Volume Profile PoC",
            "score": 99,
            "smc_note": f"1D/4H Aligned | 1H PoC: {self._round(poc)} | VAL: {self._round(val)} | 15M Volume Spike Confirmed"
        }

        return "LONG", self._round(current_price), details
