# ============================================================
# MY EXPERT CRYPTO BOT - Pure Python SMC & Market Guard Engine (v41.0)
# No external complex TA dependencies, 100% stable on Render.
# ============================================================

import logging
import math
import numpy as np

logger = logging.getLogger("PureSMCEngine")


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
    def _array(ohlcv, minimum=20):
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

    def calculate_rsi(self, closes, period=14):
        """حساب مؤشر RSI برمجياً بكل دقة وبدون مكتبات خارجية"""
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
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi)
        except Exception:
            return 50.0

    def check_market_guard(self, btc_ohlcv_15m):
        """1. فلتر حماية السوق: فحص استقرار البيتكوين"""
        if btc_ohlcv_15m is None:
            return True, "بيانات الحماية غير متوفرة، المتابعة بحذر."
        btc_arr = self._array(btc_ohlcv_15m, 10)
        if btc_arr is None:
            return True, "بيانات الـ BTC غير صالحة."
        
        btc_closes = btc_arr[:, 4]
        last_return = (btc_closes[-1] - btc_closes[-2]) / btc_closes[-2]
        if last_return < -0.015:  # هبوط حاد بأكثر من 1.5%
            return False, "فلتر الحماية مفعل: تم رصد هبوط حاد في الـ Bitcoin."
        return True, "البيتكوين مستقر."

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, btc_ohlcv_15m=None, **kwargs
    ):
        # 1. فلتر حماية السوق
        guard_passed, guard_msg = self.check_market_guard(btc_ohlcv_15m)
        if not guard_passed:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": guard_msg}

        if ohlcv_5m is None or ohlcv_15m is None or ohlcv_1h is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الأطر الزمنية ناقصة."}

        m5 = self._array(ohlcv_5m, 20)
        m15 = self._array(ohlcv_15m, 20)
        h1 = self._array(ohlcv_1h, 15)

        if m5 is None or m15 is None or h1 is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الشموع غير كافية."}

        # 2. فلتر الاتجاه وصيد السيولة (Trend & Sweep)
        h1_closes = h1[:, 4]
        trend_bullish = h1_closes[-1] > h1_closes[-10]
        if not trend_bullish:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "اتساق فريم 1H ليس صاعداً."}

        recent_lows = m15[-15:-2, 3]
        prior_low = float(np.min(recent_lows))
        
        current_low = float(m15[-2, 3])
        current_close = float(m15[-2, 4])
        current_open = float(m15[-2, 1])

        liquidity_sweep = (current_low < prior_low) and (current_close > prior_low) and (current_close > current_open)
        if not liquidity_sweep:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد صيد سيولة (Sweep) حقيقي على فريم 15M."}

        # 3. الفجوة السعرية (FVG) وكتل الطلب (OB)
        fvg_detected = False
        ob_level = prior_low
        for i in range(len(m15) - 4, len(m15) - 1):
            prev_high = m15[i - 1, 2]
            next_low = m15[i + 1, 3]
            if next_low > prev_high:
                fvg_detected = True
                ob_level = m15[i, 3]

        if not fvg_detected:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد فجوة سعرية (FVG) متزامنة."}

        # 4. تأكيد الزخم (الانحراف الإيجابي البسيط عبر RSI المحسوب برمجياً)
        rsi_current = self.calculate_rsi(m5[:, 4], 14)
        rsi_prev = self.calculate_rsi(m5[:-3, 4], 14)
        price_current = float(m5[-1, 4])
        price_prev = float(m5[-4, 4])

        bullish_divergence = (price_current < price_prev) and (rsi_current > rsi_prev)
        if not bullish_divergence and rsi_current > 45: # شرط تكميلي للزخم
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "شروط الزخم والانحراف الإيجابي لم تكتمل على فريم 5M."}

        # 5. إدارة المخاطر والأهداف
        entry_price = current_close
        stop_loss = prior_low - (prior_low * 0.002)
        
        recent_high = float(np.max(m15[-15:-2, 2]))
        tp1 = recent_high
        
        risk = entry_price - stop_loss
        if risk <= 0:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "مخاطرة غير صالحة."}

        tp2 = entry_price + (risk * 2.5)
        risk_amount_usd = self.total_capital * self.risk_per_trade
        position_size = risk_amount_usd / risk

        details = {
            "trade_valid": True,
            "signal_type": "PURE_PYTHON_SMC_LONG",
            "reason": "تم تحقق كافة الشروط الصارمة بنجاح تام (حماية السوق، صيد السيولة، FVG، واعتدال الزخم).",
            "score": 100,
            "stop_loss": self._round(stop_loss),
            "entry_zone": {
                "ideal_entry": self._round(entry_price),
                "order_block": self._round(ob_level),
                "waiting_price": self._round(entry_price),
            },
            "risk_management": {
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "breakeven_trigger": self._round(tp1),
                "position_size_units": self._round(position_size),
                "risk_usd": self._round(risk_amount_usd)
            }
        }

        return "LONG", self._round(entry_price), details
