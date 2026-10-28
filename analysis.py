# ============================================================
# MY EXPERT CRYPTO BOT - Multi-Timeframe SMC & Order Blocks Engine
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("MultiTimeframeSMCEngine")


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0
        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.05)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

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
        decimals = max(2, min(12, int(-np.floor(np.log10(abs(value)))) + 3))
        return round(value, decimals)

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
        except Exception:
            return 0.0

    def calculate_position_size(self, entry_price, stop_loss):
        try:
            risk_amount = self.total_capital * self.risk_per_trade
            risk_per_unit = abs(entry_price - stop_loss)
            if risk_per_unit <= 0:
                return 0.0, 0.0
            position_size_units = risk_amount / risk_per_unit
            position_value_usd = position_size_units * entry_price
            return self._round(position_size_units), self._round(position_value_usd)
        except Exception:
            return 0.0, 0.0

    def analyze_market_structure(self, ohlcv_15m=None, ohlcv_1h=None, ohlcv_4h=None, ohlcv_1d=None, btc_ohlcv_1d=None, **kwargs):
        def no_trade(reason):
            return "NEUTRAL", 0, {"trade_valid": False, "reason": reason, "score": 0}

        if any(x is None for x in (ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d)):
            return no_trade("بيانات الفريمات الأربعة غير مكتملة")

        d1 = self._array(ohlcv_1d, 20)
        h4 = self._array(ohlcv_4h, 20)
        h1 = self._array(ohlcv_1h, 20)
        m15 = self._array(ohlcv_15m, 25)

        if d1 is None or h4 is None or h1 is None or m15 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل")

        # 1. التحقق من اتجاه البيتكوين العام
        btc_bullish = True
        if btc_ohlcv_1d is not None:
            btc_d1 = self._array(btc_ohlcv_1d, 20)
            if btc_d1 is not None:
                btc_close = float(btc_d1[-2, 4])
                btc_ma20 = float(np.mean(btc_d1[:-1, 4][-20:]))
                btc_bullish = btc_close >= btc_ma20

        # 2. تحليل الفريم اليومي (1D) وفريم الأربع ساعات (4H) للاتجاه الهيكلي
        daily_close = float(d1[-2, 4])
        daily_ma20 = float(np.mean(d1[:-1, 4][-20:]))
        is_daily_bullish = daily_close >= daily_ma20
        is_daily_bearish = daily_close < daily_ma20

        h4_close = float(h4[-2, 4])
        h4_ma10 = float(np.mean(h4[-10:, 4]))
        is_h4_bullish = h4_close >= h4_ma10
        is_h4_bearish = h4_close < h4_ma10

        # 3. تحليل فريم الساعة (1H) للزخم وفجوات القيمة العادلة (FVG)
        h1_close = float(h1[-2, 4])
        h1_open = float(h1[-2, 1])
        is_h1_bullish = h1_close >= h1_open
        is_h1_bearish = h1_close < h1_open

        # 4. تحليل فريم 15 دقيقة (15M) لتحديد مناطق الـ Order Block والسيولة وتنفيذ الدخول
        open_ = float(m15[-2, 1])
        close = float(m15[-2, 4])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])
        volume = float(m15[-2, 5])

        # استخراج مناطق الدعم والمقاومة (Order Blocks / Strong Low & High)
        strong_support = float(np.min(m15[-15:-2, 3]))
        strong_resistance = float(np.max(m15[-15:-2, 2]))

        avg_vol = float(np.mean(m15[-15:-2, 5]))
        volume_ok = avg_vol > 0 and volume >= avg_vol * 1.1
        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        # شروط صفقات الشراء (LONG) - توافق الفريمات الأربعة مع ارتداد Order Block صاعد
        if is_daily_bullish and is_h4_bullish and is_h1_bullish and btc_bullish:
            near_support = low <= strong_support * 1.015
            is_bullish_reaction = close > open_ and body_ratio >= 0.4

            if near_support and is_bullish_reaction and volume_ok:
                score = 97
                stop = float(strong_support - (1.2 * atr))
                risk_dist = close - stop
                if risk_dist <= 0:
                    risk_dist = close * 0.025

                tp1 = close + (risk_dist * 2.0)
                tp2 = close + (risk_dist * 3.5)
                tp3 = close + (risk_dist * 5.5)
                
                units, val_usd = self.calculate_position_size(close, stop)
                
                details = {
                    "trade_valid": True,
                    "reason": "توافق الفريمات الأربعة مع ارتداد Order Block و Strong Low (LONG)",
                    "stop_loss": self._round(stop),
                    "score": score,
                    "position_sizing": {
                        "units": units,
                        "margin_usd": val_usd,
                        "risk_amount_usd": self._round(self.total_capital * self.risk_per_trade)
                    },
                    "risk_management": {
                        "take_profit_1": self._round(tp1),
                        "take_profit_2": self._round(tp2),
                        "take_profit_3": self._round(tp3),
                        "breakeven_trigger": self._round(tp1),
                        "trailing_stop_active": True
                    },
                    "smc_note": "ارتداد مثالي من منطقة الطلب (+OB) مع تأكيد الفريمات الكبرى"
                }
                return "LONG", self._round(close), details

        # شروط صفقات البيع (SHORT) - توافق الفريمات الأربعة مع رفض Order Block هابط
        if is_daily_bearish and is_h4_bearish and is_h1_bearish and not btc_bullish:
            near_resistance = high >= strong_resistance * 0.985
            is_bearish_reaction = close < open_ and body_ratio >= 0.4

            if near_resistance and is_bearish_reaction and volume_ok:
                score = 97
                stop = float(strong_resistance + (1.2 * atr))
                risk_dist = stop - close
                if risk_dist <= 0:
                    risk_dist = close * 0.025

                tp1 = close - (risk_dist * 2.0)
                tp2 = close - (risk_dist * 3.5)
                tp3 = close - (risk_dist * 5.5)
                
                units, val_usd = self.calculate_position_size(close, stop)
                
                details = {
                    "trade_valid": True,
                    "reason": "توافق الفريمات الأربعة مع رفض Order Block و Strong High (SHORT)",
                    "stop_loss": self._round(stop),
                    "score": score,
                    "position_sizing": {
                        "units": units,
                        "margin_usd": val_usd,
                        "risk_amount_usd": self._round(self.total_capital * self.risk_per_trade)
                    },
                    "risk_management": {
                        "take_profit_1": self._round(tp1),
                        "take_profit_2": self._round(tp2),
                        "take_profit_3": self._round(tp3),
                        "breakeven_trigger": self._round(tp1),
                        "trailing_stop_active": True
                    },
                    "smc_note": "رفض سعري من منطقة العرض (-OB) مع سلبية الفريمات الكبرى"
                }
                return "SHORT", self._round(close), details

        return no_trade("في انتظار تفاعل السعر مع مناطق الـ Order Block عبر الفريمات الأربعة")
