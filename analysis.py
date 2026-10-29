# ============================================================
# MY EXPERT CRYPTO BOT - Ultimate SMC & Market Guard Engine (v40.0)
# Strict adherence to 5 conditions: Market Guard, Sweep, FVG/OB, RSI Div, Risk Management.
# ============================================================

import logging
import math
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger("StrictSMCEngine")


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
    def _to_dataframe(ohlcv):
        try:
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
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

    def check_market_guard(self, btc_ohlcv_15m):
        """1. فلتر حماية السوق: التحقق من استقرار البيتكوين وعدم وجود هبوط عنيف (Crash)"""
        if btc_ohlcv_15m is None:
            return False, "بيانات البيتكوين غير متوفرة لفحص الحماية."
        
        df_btc = self._to_dataframe(btc_ohlcv_15m)
        if df_btc is None or len(df_btc) < 10:
            return False, "بيانات الـ BTC غير كافية."

        # حساب التغير في آخر شمعتين أو تذبذب العائد
        btc_returns = df_btc['close'].pct_change().tail(3)
        if (btc_returns < -0.015).any():  # هبوط بأكثر من 1.5% بشكل مفاجئ
            return False, "فلتر الحماية مفعل: تم رصد هبوط حاد أو تذبذب عنيف في الـ BTC."
        
        return True, "البيتكوين مستقر وآمن."

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, btc_ohlcv_15m=None, **kwargs
    ):
        # 1. تطبيق فلتر حماية السوق (Market Guard)
        guard_passed, guard_msg = self.check_market_guard(btc_ohlcv_15m)
        if not guard_passed:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": guard_msg}

        if ohlcv_5m is None or ohlcv_15m is None or ohlcv_1h is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الأطر الزمنية غير متوفرة بالكامل."}

        df_5m = self._to_dataframe(ohlcv_5m)
        df_15m = self._to_dataframe(ohlcv_15m)
        df_1h = self._to_dataframe(ohlcv_1h)

        if df_5m is None or df_15m is None or df_1h is None or len(df_15m) < 30:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الشموع غير صالحة أو غير كافية."}

        # 2. فلتر الاتجاه والسيولة (Trend on 1H & Liquidity Sweep on 15M/5M)
        # التحقق من أن اتجاه 1H صاعد (قاع وقمة صاعدة)
        closes_1h = df_1h['close'].values
        trend_1h_bullish = closes_1h[-1] > closes_1h[-10] and closes_1h[-5] > closes_1h[-15]
        if not trend_1h_bullish:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "الاتجاه العام على فريم 1H ليس صاعداً (لم يتحقق هيكل MSS)."}

        # رصد صيد السيولة (Liquidity Sweep) على فريم 15M
        recent_lows = df_15m['low'].iloc[-15:-2].values
        prior_low = float(np.min(recent_lows))
        
        current_candle = df_15m.iloc[-2]
        low_val = current_candle['low']
        close_val = current_candle['close']
        open_val = current_candle['open']

        # شرط صيد السيولة: كسر القاع السابق ثم الارتداد والإغلاق فوقه
        liquidity_sweep = (low_val < prior_low) and (close_val > prior_low) and (close_val > open_val)
        if not liquidity_sweep:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد عملية صيد سيولة حقيقية (Sweep) على فريم 15M."}

        # 3. منطقة الدخول الفنية (Fair Value Gap - FVG & Order Block - OB)
        # البحث عن فجوة سعرية (FVG) في الشموع الثلاثة الأخيرة
        fvg_detected = False
        ob_level = prior_low
        for i in range(len(df_15m) - 4, len(df_15m) - 1):
            prev_high = df_15m['high'].iloc[i - 1]
            next_low = df_15m['low'].iloc[i + 1]
            if next_low > prev_high:  # FVG صاعد
                fvg_detected = True
                ob_level = df_15m['low'].iloc[i]  # حدود الـ Order Block

        if not fvg_detected:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "لم يتم رصد فجوة سعرية (FVG) متزامنة مع منطقة الطلب."}

        # 4. تأكيد الزخم (Bullish Divergence على مؤشر RSI بـ 14 على فريم 5M)
        df_5m['rsi'] = ta.rsi(df_5m['close'], length=14)
        rsi_values = df_5m['rsi'].dropna().values
        price_values = df_5m['close'].dropna().values

        if len(rsi_values) < 10:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات مؤشر RSI غير كافية على فريم 5M."}

        # فحص الانحراف الإيجابي البسيط (السعر يصنع قاعاً أقل، وRSI يصنع قاعاً أعلى)
        bullish_divergence = (price_values[-1] < price_values[-5]) and (rsi_values[-1] > rsi_values[-5])
        if not bullish_divergence:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "شروط الزخم لم تكتمل: لا يوجد انحراف إيجابي (Bullish Divergence) على مؤشر RSI."}

        # 5. إدارة المخاطر الذكية (Stop Loss & Take Profits & Breakeven)
        entry_price = close_val
        stop_loss = prior_low - (prior_low * 0.002)  # أسفل قاع صيد السيولة بمسافة أمان 0.2%
        
        # الأهداف الذكية
        recent_high = float(np.max(df_15m['high'].iloc[-20:-2].values))
        tp1 = recent_high  # أقرب قمة رئيسية مقاومة
        
        risk = entry_price - stop_loss
        if risk <= 0:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "خطأ في حساب مسافة المخاطرة."}

        tp2 = entry_price + (risk * 2.5)  # عائد إلى مخاطرة لا يقل عن 1:2.5

        # حساب حجم الصفقة لإدارة رأس المال
        risk_amount_usd = self.total_capital * self.risk_per_trade
        position_size = risk_amount_usd / risk

        details = {
            "trade_valid": True,
            "signal_type": "ULTIMATE_SMC_MARKET_GUARD_LONG",
            "reason": "تم تحقق الشروط الـ 5 مجتمعة: حماية السوق مستقرة، صيد سيولة حقيقي، FVG مع OB، انحراف RSI إيجابي، وإدارة مخاطر ذكية.",
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
