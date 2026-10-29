# ============================================================
# MY EXPERT CRYPTO BOT - Multi-Timeframe Advanced SMC Engine (v3.5 - Elite)
# ============================================================

import logging
import numpy as np

logger = logging.getLogger("AdvancedSMCEngine")


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

    def detect_fvg(self, ohlcv):
        """الكشف البرمجي عن فجوات القيمة العادلة (Fair Value Gaps)"""
        try:
            bullish_fvg_found = False
            bearish_fvg_found = False
            
            for i in range(len(ohlcv) - 3, len(ohlcv) - 1):
                high_prev = ohlcv[i-1, 2]
                low_next = ohlcv[i+1, 3]
                low_prev = ohlcv[i-1, 3]
                high_next = ohlcv[i+1, 2]

                if low_next > high_prev:
                    bullish_fvg_found = True
                if high_next < low_prev:
                    bearish_fvg_found = True
                    
            return bullish_fvg_found, bearish_fvg_found
        except Exception:
            return False, False

    def detect_true_order_block(self, ohlcv):
        """تحديد الـ Order Block الحقيقي"""
        try:
            bullish_ob = ohlcv[-3, 3]
            bearish_ob = ohlcv[-3, 2]
            
            for i in range(len(ohlcv) - 4, len(ohlcv) - 2):
                open_p = ohlcv[i, 1]
                close_p = ohlcv[i, 4]
                if close_p < open_p and ohlcv[i+1, 4] > ohlcv[i+1, 1]:
                    bullish_ob = min(ohlcv[i, 3], ohlcv[i+1, 3])
                if close_p > open_p and ohlcv[i+1, 4] < ohlcv[i+1, 1]:
                    bearish_ob = max(ohlcv[i, 2], ohlcv[i+1, 2])
                    
            return float(bullish_ob), float(bearish_ob)
        except Exception:
            return float(np.min(ohlcv[-10:, 3])), float(np.max(ohlcv[-10:, 2]))

    def check_liquidity_sweep(self, ohlcv, higher_tf_high=None, higher_tf_low=None):
        """كشف سحب السيولة (Stop Hunt)"""
        try:
            lows = ohlcv[-15:-2, 3]
            highs = ohlcv[-15:-2, 2]
            current_low = ohlcv[-2, 3]
            current_high = ohlcv[-2, 2]
            
            min_prev_low = np.min(lows[:-1])
            max_prev_high = np.max(highs[:-1])
            
            if higher_tf_low is not None:
                min_prev_low = min(min_prev_low, higher_tf_low)
            if higher_tf_high is not None:
                max_prev_high = max(max_prev_high, higher_tf_high)

            swept_low = current_low < min_prev_low and ohlcv[-2, 4] > ohlcv[-2, 1]
            swept_high = current_high > max_prev_high and ohlcv[-2, 4] < ohlcv[-2, 1]

            return swept_low, swept_high
        except Exception:
            return False, False

    def check_market_structure_shift(self, ohlcv):
        """التحقق من تغير الهيكل (MSS / ChoCH) على فريم التنفيذ"""
        try:
            # كسر أحدث قمة هابطة أو قاع صاعد في آخر 5 شمعات
            recent_highs = ohlcv[-6:-2, 2]
            recent_lows = ohlcv[-6:-2, 3]
            current_close = ohlcv[-2, 4]
            
            mss_bullish = current_close > np.max(recent_highs)
            mss_bearish = current_close < np.min(recent_lows)
            
            return mss_bullish, mss_bearish
        except Exception:
            return True, True  # تمرير افتراضي في حال عدم توفر البيانات الكافية

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

        btc_bullish = True
        if btc_ohlcv_1d is not None:
            btc_d1 = self._array(btc_ohlcv_1d, 20)
            if btc_d1 is not None:
                btc_bullish = float(btc_d1[-2, 4]) >= float(btc_d1[-5, 4])

        is_daily_bullish = float(d1[-2, 4]) > float(d1[-5, 4])
        is_daily_bearish = float(d1[-2, 4]) < float(d1[-5, 4])
        higher_tf_high = float(np.max(d1[-10:-1, 2]))
        higher_tf_low = float(np.min(d1[-10:-1, 3]))

        is_h4_bullish = float(h4[-2, 4]) > float(h4[-4, 4])
        is_h4_bearish = float(h4[-2, 4]) < float(h4[-4, 4])

        h1_bull_fvg, h1_bear_fvg = self.detect_fvg(h1)
        is_h1_bullish = float(h1[-2, 4]) > float(h1[-2, 1]) or h1_bull_fvg
        is_h1_bearish = float(h1[-2, 4]) < float(h1[-2, 1]) or h1_bear_fvg

        open_ = float(m15[-2, 1])
        close = float(m15[-2, 4])
        high = float(m15[-2, 2])
        low = float(m15[-2, 3])
        volume = float(m15[-2, 5])

        true_bull_ob, true_bear_ob = self.detect_true_order_block(m15)
        avg_vol = float(np.mean(m15[-15:-2, 5]))
        volume_ok = avg_vol > 0 and volume >= avg_vol * 1.05
        atr = self.calculate_atr(m15[:-1, 2], m15[:-1, 3], m15[:-1, 4], 14)

        swept_low, swept_high = self.check_liquidity_sweep(m15, higher_tf_high, higher_tf_low)
        m15_bull_fvg, m15_bear_fvg = self.detect_fvg(m15)
        mss_bull, mss_bear = self.check_market_structure_shift(m15)

        candle_range = max(high - low, close * 1e-8)
        body_ratio = max(0.0, abs(close - open_)) / candle_range

        # شروط الشراء (LONG) مع مرشح الهيكل MSS
        if is_daily_bullish and is_h4_bullish and is_h1_bullish and btc_bullish:
            is_bullish_reaction = close > open_ and body_ratio >= 0.35
            
            if (swept_low or low <= true_bull_ob * 1.015) and (is_bullish_reaction or m15_bull_fvg) and mss_bull and volume_ok:
                stop = float(true_bull_ob - (1.0 * atr))
                risk_dist = close - stop
                if risk_dist <= 0:
                    risk_dist = close * 0.02

                tp1 = close + (risk_dist * 2.0)
                tp2 = close + (risk_dist * 3.5)
                tp3 = close + (risk_dist * 5.0)
                
                # فلتر RRR: التأكد من أن نسبة العائد للمخاطرة للهدف الأول >= 1.5
                if (tp1 - close) / risk_dist < 1.5:
                    return no_trade("نسبة العائد إلى المخاطرة أقل من الحد الأدنى المقبول")

                units, val_usd = self.calculate_position_size(close, stop)
                
                details = {
                    "trade_valid": True,
                    "reason": "تأكيد Elite SMC: سيولة + OB + FVG صاعد + تأكيد تغير الهيكل (MSS) (LONG)",
                    "stop_loss": self._round(stop),
                    "score": 99,
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
                        "partial_tp_ratio": 0.5,  # إغلاق 50% عند الهدف الأول
                        "trailing_stop_active": True
                    },
                    "smc_note": "تم رصد سحب السيولة، تأكيد MSS، والانعكاس من منطقة الطلب الحقيقية"
                }
                return "LONG", self._round(close), details

        # شروط البيع (SHORT) مع مرشح الهيكل MSS
        if is_daily_bearish and is_h4_bearish and is_h1_bearish and not btc_bullish:
            is_bearish_reaction = close < open_ and body_ratio >= 0.35

            if (swept_high or high >= true_bear_ob * 0.985) and (is_bearish_reaction or m15_bear_fvg) and mss_bear and volume_ok:
                stop = float(true_bear_ob + (1.0 * atr))
                risk_dist = stop - close
                if risk_dist <= 0:
                    risk_dist = close * 0.02

                tp1 = close - (risk_dist * 2.0)
                tp2 = close - (risk_dist * 3.5)
                tp3 = close - (risk_dist * 5.0)
                
                if (close - tp1) / risk_dist < 1.5:
                    return no_trade("نسبة العائد إلى المخاطرة أقل من الحد الأدنى المقبول")

                units, val_usd = self.calculate_position_size(close, stop)
                
                details = {
                    "trade_valid": True,
                    "reason": "تأكيد Elite SMC: سيولة + OB + FVG هابط + تأكيد تغير الهيكل (MSS) (SHORT)",
                    "stop_loss": self._round(stop),
                    "score": 99,
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
                        "partial_tp_ratio": 0.5,
                        "trailing_stop_active": True
                    },
                    "smc_note": "تم رصد تفريغ مؤسسي، تأكيد MSS، والرفض من منطقة العرض"
                }
                return "SHORT", self._round(close), details

        return no_trade("في انتظار اكتمال نمط الـ MSS وسحب السيولة والـ FVG")
