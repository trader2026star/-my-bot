# ============================================================
# MY EXPERT CRYPTO BOT - SMC & Order Block Strategy Engine
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("SMCEngine")


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
            return no_trade("بيانات الفريمات غير مكتملة")

        d1 = self._array(ohlcv_1d, 20)
        h4 = self._array(ohlcv_4h, 20)
        h1 = self._array(ohlcv_1h, 20)
        m15 = self._array(ohlcv_15m, 25)

        if d1 is None or h4 is None or h1 is None or m15 is None:
            return no_trade("بيانات الشموع غير صالحة للتحليل")

        # التحقق من اتجاه البيتكوين العام
        btc_bullish = True
        if btc_ohlcv_1d is not None:
            btc_d1 = self._array(btc_ohlcv_1d, 20)
            if btc_d1 is not None:
                btc_close = float(btc_d1[-2, 4])
                btc_ma20 = float(np.mean(btc_d1[:-1, 4][-20:]))
                btc_bullish = btc_close >= btc_ma20

        daily_close = float(d1[-2, 4])
        daily_ma20 = float(np.mean(d1[:-1, 4][-20:]))
        
        h4_close = float(h4[-2, 4])
        h4_ma10 = float(np.mean(h4[:-1, 4][-10:]))

        # بيانات الشمعة الحالية والسابقة على 15m
        open_ = float(m15[-2, 1])
        close = float(m15[-2, 4])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])
        volume = float(m15[-2, 5])

        # البحث عن مناطق الـ Order Block (آخر شمعة هابطة قبل صفر قوي للشراء أو العكس)
        # الكتلة الشرائية (+OB): البحث عن قاع قتلي شكل منطقة دعم قوية في آخر 15 شمعة
        recent_lows = m15[-15:-2, 3]
        strong_support = float(np.min(recent_lows))
        
        recent_highs = m15[-15:-2, 2]
        strong_resistance = float(np.max(recent_highs))

        avg_vol = float(np.mean(m15[-15:-2, 5]))
        volume_ok = avg_vol > 0 and volume >= avg_vol * 1.1
        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)

        is_daily_bullish = daily_close >= daily_ma20
        is_h4_bullish = h4_close >= h4_ma10

        is_daily_bearish = daily_close < daily_ma20
        is_h4_bearish = h4_close < h4_ma10

        # استراتيجية Long بناءً على ارتداد السعر من منطقة Order Block / FVG صاعدة
        near_ob_support = low <= strong_support * 1.012
        is_bullish_displacement = close > open_ and (close - open_) >= (high - low) * 0.55

        if is_daily_bullish and is_h4_bullish and btc_bullish:
            if (near_ob_support or low <= strong_support * 1.02) and is_bullish_displacement and volume_ok:
                score = 96
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
                    "reason": "ارتداد مثالي من منطقة Order Block ودعم قوي (+OB / FVG Rejection LONG)",
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
                    "smc_note": "الدخول مع إعادة اختبار منطقة السيولة والـ Order Block السفلي"
                }
                return "LONG", self._round(close), details

        # استراتيجية Short بناءً على رفض السعر لمنطقة مقاومة / Order Block هابطة
        near_ob_resistance = high >= strong_resistance * 0.988
        is_bearish_displacement = close < open_ and (open_ - close) >= (high - low) * 0.55

        if is_daily_bearish and is_h4_bearish and not btc_bullish:
            if (near_ob_resistance or high >= strong_resistance * 0.98) and is_bearish_displacement and volume_ok:
                score = 96
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
                    "reason": "رفض سعري من منطقة Order Block ومقاومة عليا (-OB / Supply Rejection SHORT)",
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
                    "smc_note": "الدخول مع إعادة اختبار منطقة العرض العلوية (Supply Zone)"
                }
                return "SHORT", self._round(close), details

        return no_trade("السعر لم يصل لمنطقة Order Block أو FVG المستهدفة بعد")
