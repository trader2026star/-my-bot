# ============================================================
# MY EXPERT CRYPTO BOT - VOLUME PROFILE & PoC ENGINE (V16.1 - Sniper Mode)
# Strategy: Strict Volume Profile, PoC Bounce & Value Area
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

    def calculate_volume_profile(self, ohlcv, bins=35):
        arr = self._array(ohlcv, minimum=15)
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

        raw15 = self._array(ohlcv_15m, 20)
        if raw15 is None:
            return no_trade("بيانات 15 دقيقة غير صالحة")
            
        current_price = float(raw15[-1, 4])
        
        source_ohlcv = ohlcv_1h if ohlcv_1h is not None else ohlcv_15m
        poc, val, vah = self.calculate_volume_profile(source_ohlcv)
        if poc is None:
            return no_trade("تعذر حساب نقاط ملف الحجم (Volume Profile)")

        last_candle = raw15[-1]
        o, h, l, c, v = last_candle[1], last_candle[2], last_candle[3], last_candle[4], last_candle[5]
        
        # الشروط الصارمة جداً (القناص): نطاق ضيق جداً (0.5%) + شمعة زخم قوية (60% من حجم الشمعة صاعد)
        candle_range = h - l if h > l else 1.0
        is_strong_bullish = c > o and ((c - o) / candle_range) >= 0.60
        near_key_node = (current_price <= poc * 1.005) and (current_price >= val * 0.995)
        
        if not (near_key_node and is_strong_bullish):
            return no_trade("السعر ليس في نقطة الارتداد الدقيقة أو عزم الشمعة ضعيف")

        atr = self.calculate_atr(raw15[:, 2], raw15[:, 3], raw15[:, 4], 14)
        stop = min(val - 0.5 * atr, current_price - 1.5 * atr)
        risk_dist = current_price - stop
        if risk_dist <= 0:
            return no_trade("مسافة الوقف غير صالحة")

        tp_target = current_price + (risk_dist * 2.5)
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / risk_dist

        details = {
            "reason": "Sniper Volume Profile PoC Bounce Strategy",
            "stop_loss": self._round(stop),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(qty, 8),
                "take_profit_1": self._round(current_price + (risk_dist * 1.0)),
                "take_profit_2": self._round(current_price + (risk_dist * 1.8)),
                "take_profit_3": self._round(tp_target),
                "reward_ratio": "1:2.5"
            },
            "setup": "Strict PoC & Value Area Sniper",
            "score": 98,
            "smc_note": f"Sniper PoC: {self._round(poc)} | VAL: {self._round(val)} | VAH: {self._round(vah)}"
        }

        return "LONG", self._round(current_price), details
