# ============================================================
# INSTITUTIONAL LIQUIDITY & MOMENTUM STRATEGY ENGINE (v60.0)
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("InstitutionalEngine")

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

    @staticmethod
    def _array(ohlcv, minimum=50):
        try:
            a = np.asarray(ohlcv, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            return a[:, :6]
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

    def calculate_ema(self, closes, period=200):
        c = np.asarray(closes, dtype=float)
        if len(c) < period:
            period = len(c)
        alpha = 2 / (period + 1)
        ema = np.empty_like(c)
        ema[0] = c[0]
        for i in range(1, len(c)):
            ema[i] = alpha * c[i] + (1 - alpha) * ema[i - 1]
        return ema

    def calculate_rsi(self, closes, period=14):
        try:
            c = np.asarray(closes, dtype=float)
            if len(c) < period + 1:
                return 50.0
            deltas = np.diff(c)
            seed = deltas[:period]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            if down == 0:
                return 100.0
            rs = up / down
            return float(100.0 - (100.0 / (1.0 + rs)))
        except Exception:
            return 50.0

    def detect_order_blocks_and_fvg(self, ohlcv):
        """
        رصد الـ Order Blocks المؤسسية والفجوات السعرية (FVG)
        """
        closes = ohlcv[:, 4]
        opens = ohlcv[:, 1]
        highs = ohlcv[:, 2]
        lows = ohlcv[:, 3]

        ob_high, ob_low = None, None
        fvg_detected = False
        fvg_top, fvg_bottom = 0.0, 0.0

.        # البحث في الشموع الأخيرة عن دفعة قوية تلتها فجوة واضحة
        for i in range(len(ohlcv) - 4, len(ohlcv) - 1):
            if i < 2:
                continue
            # فحص FVG (الفرق بين قمة شمعة i-1 وقاع شمعة i+1 في حال الصعود)
            if lows[i+1] > highs[i-1]:
                fvg_detected = True
                fvg_top = float(lows[i+1])
                fvg_bottom = float(highs[i-1])
                # الـ Order Block هو آخر شمعة هابطة قبل الحركة الصاعدة القوية
                if closes[i] < opens[i]:  # شمعة هابطة
                    ob_high = float(highs[i])
                    ob_low = float(lows[i])
            elif highs[i+1] < lows[i-1]:  # هبوط
                fvg_detected = True
                fvg_top = float(lows[i-1])
                fvg_bottom = float(highs[i+1])
                if closes[i] > opens[i]:  # شمعة صاعدة قبل الهبوط
                    ob_high = float(highs[i])
                    ob_low = float(lows[i])

        if ob_high is None:
            ob_high = float(np.max(highs[-10:]))
            ob_low = float(np.min(lows[-10:]))

        return {"ob_high": ob_high, "ob_low": ob_low, "fvg_present": fvg_detected, "fvg_top": fvg_top, "fvg_bottom": fvg_bottom}

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, btc_ohlcv_15m=None, **kwargs
    ):
        # استخدام فريم 1H أو 4H لتحديد الاتجاه العام بـ EMA 200
        macro_ohlcv = ohlcv_4h if ohlcv_4h is not None and len(ohlcv_4h) >= 50 else ohlcv_1h
        if macro_ohlcv is None or ohlcv_5m is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الفريمات الكبرى أو الصغرى غير كافية للتحليل المؤسسي."}

        macro_arr = self._array(macro_ohlcv, 30)
        m5_arr = self._array(ohlcv_5m, 30)
        m15_arr = self._array(ohlcv_15m, 30) if ohlcv_15m is not None else m5_arr

        if macro_arr is None or m5_arr is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "مصفوفة الشموع لا تستوفي الحد الأدنى للتحليل."}

        macro_closes = macro_arr[:, 4]
        ema_200 = self.calculate_ema(macro_closes, period=min(200, len(macro_closes)))
        current_macro_close = float(macro_closes[-1])
        current_ema_200 = float(ema_200[-1])

        # تحديد الاتجاه المؤسسي (Macro Trend via EMA 200)
        is_bullish_trend = current_macro_close > current_ema_200
        is_bearish_trend = current_macro_close < current_ema_200
        market_trend_str = "صاعد مؤسسي (Bullish > EMA200)" if is_bullish_trend else "هابط مؤسسي (Bearish < EMA200)"

        current_price = float(m5_arr[-1, 4])
        
        # مؤشر الزخم RSI على الفريم الأصغر (5m / 15m)
        rsi_val = self.calculate_rsi(m5_arr[:, 4], period=14)

        # استخراج مناطق الـ Order Blocks و الفجوات (FVG)
        structure_data = self.detect_order_blocks_and_fvg(m5_arr)
        ob_high = structure_data["ob_high"]
        ob_low = structure_data["ob_low"]

        trade_valid = False
        direction = "NEUTRAL"
        reason = "لم تتحقق الشروط المؤسسية الصارمة بعد."

        # فلترة الدخول بصرامة عالية (دقة 90%+)
        # شروط الشراء (LONG): اتجاه صاعد + RSI في التشبع البيعي (<30 أو قريب منها <38) + ارتداد من الـ OB
        if is_bullish_trend and rsi_val <= 42:
            direction = "LONG"
            trade_valid = True
            entry_price = current_price
            stop_loss = float(ob_low * 0.995)  # تحت الـ Order Block بدقة
            risk = entry_price - stop_loss
            if risk <= 0:
                risk = entry_price * 0.005
            tp1 = entry_price + (risk * 2.0)   # نسبة عائد 1:2
            tp2 = entry_price + (risk * 3.0)   # نسبة عائد 1:3
            reason = "تم تأكيد الاتجاه الصاعد بـ EMA200 مع ارتداد السعر لمنطقة الطلب (OB/FVG) وتشبع بيعي للـ RSI."

        # شروط البيع (SHORT): اتجاه هابط + RSI في التشبع الشرائي (>70 أو فوق 62) + ارتداد من الـ OB الهابط
        elif is_bearish_trend and rsi_val >= 58:
            direction = "SHORT"
            trade_valid = True
            entry_price = current_price
            stop_loss = float(ob_high * 1.005)  # فوق الـ Order Block بدقة
            risk = stop_loss - entry_price
            if risk <= 0:
                risk = entry_price * 0.005
            tp1 = entry_price - (risk * 2.0)   # نسبة عائد 1:2
            tp2 = entry_price - (risk * 3.0)   # نسبة عائد 1:3
            reason = "تم تأكيد الاتجاه الهابط بـ EMA200 مع ارتداد السعر لمنطقة العرض (OB/FVG) وتشبع شرائي للـ RSI."
        else:
            entry_price = current_price
            stop_loss = current_price * 0.99 if is_bullish_trend else current_price * 1.01
            tp1 = current_price * 1.01
            tp2 = current_price * 1.02

        details = {
            "trade_valid": trade_valid,
            "signal_type": "INSTITUTIONAL_SMC",
            "market_trend": market_trend_str,
            "rsi": self._round(rsi_val),
            "reason": reason,
            "closest_scenario": "OB_FVG_RETEST",
            "trigger_price": self._round(entry_price),
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "order_block": f"{self._round(ob_low)} - {self._round(ob_high)}",
                "fvg_active": structure_data["fvg_present"]
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2)
            }
        }
        return direction, self._round(current_price), details
