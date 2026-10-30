# ============================================================
# MY EXPERT CRYPTO & TradFi CFD BOT - Analysis Engine (v63.2_PRO)
# ============================================================
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger("StrategyEngine")

class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01):
        self.capital = capital
        self.risk_per_trade = risk_per_trade

    def calculate_atr(self, df, period=14):
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            tr1 = high - low
            tr2 = np.abs(high - close.shift())
            tr3 = np.abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            return atr.iloc[-1]
        except Exception:
            return 0.0

    def calculate_cmf(self, df, period=20):
        """
        حساب تدفق الأموال (Chaikin Money Flow - CMF) لقياس سيولة الحيتان والشراء/البيع المؤسسي.
        """
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            volume = df['volume']
            
            mf_multiplier = ((close - low) - (high - close)) / (high - low + 1e-9)
            mf_volume = mf_multiplier * volume
            cmf = mf_volume.rolling(window=period).sum() / (volume.rolling(window=period).sum() + 1e-9)
            return float(cmf.iloc[-1])
        except Exception:
            return 0.0

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
        """
        تحليل بنية السوق والزخم والسيولة بناءً على الشموع للإطارين 5m و 15m.
        """
        default_details = {
            "trade_valid": False,
            "trigger_price": 0.0,
            "stop_loss": 0.0,
            "atr": 0.0,
            "entry_zone": {},
            "risk_management": {},
            "reason": "بيانات غير كافية أو السوق في حالة تذبذب عرضي."
        }

        try:
            if not ohlcv_5m or not ohlcv_15m or len(ohlcv_5m) < 50 or len(ohlcv_15m) < 50:
                return "NEUTRAL", 0.0, default_details

            # تحويل البيانات إلى DataFrames
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            current_price = float(df_5m['close'].iloc[-1])

            # حساب المتوسطات ومؤشرات الزخم
            df_5m['ema20'] = df_5m['close'].ewm(span=20, adjust=False).mean()
            df_5m['ema50'] = df_5m['close'].ewm(span=50, adjust=False).mean()

            vwap_baseline = float(df_5m['ema20'].iloc[-1])
            atr_val = float(self.calculate_atr(df_5m, period=14))
            cmf_val = float(self.calculate_cmf(df_5m, period=20))

            if atr_val <= 0:
                atr_val = current_price * 0.005  # قيمة افتراضية آمنة في حال انعدام الـ ATR

            # شروط الدخول بناءً على الاتجاه والسيولة (Smart Money / Trend Following)
            is_bullish_trend = current_price > vwap_baseline and df_5m['ema20'].iloc[-1] > df_5m['ema50'].iloc[-1]
            is_bearish_trend = current_price < vwap_baseline and df_5m['ema20'].iloc[-1] < df_5m['ema50'].iloc[-1]

            direction = "NEUTRAL"
            trade_valid = False
            reason = ""

            # اعتماد صفقات الشراء (LONG) عند إيجابية الزخم وسيولة المؤسسات
            if is_bullish_trend and cmf_val > -0.05:
                direction = "LONG"
                trade_valid = True
                stop_loss = round(current_price - (2.5 * atr_val), 4)
                tp1 = round(current_price + (1.5 * atr_val), 4)
                tp2 = round(current_price + (3.0 * atr_val), 4)
                reason = "ارتكاز السعر فوق المتوسط المتحرك مع تدفق سيولة إيجابي ومؤشرات هيكلية صاعدة."

            # اعتماد صفقات البيع (SHORT) عند سلبية الزخم وضغط البيع
            elif is_bearish_trend and cmf_val < 0.05:
                direction = "SHORT"
                trade_valid = True
                stop_loss = round(current_price + (2.5 * atr_val), 4)
                tp1 = round(current_price - (1.5 * atr_val), 4)
                tp2 = round(current_price - (3.0 * atr_val), 4)
                reason = "كسر المتوسطات الهابطة مع ضغط بيعي مؤسسي وسيولة سلبية."
            else:
                stop_loss = round(current_price - (2.0 * atr_val), 4) if is_bullish_trend else round(current_price + (2.0 * atr_val), 4)
                tp1 = current_price
                tp2 = current_price
                reason = "السوق في مرحلة ترشيح أو توقف مؤقت (Consolidation) - لا توجد إشارة واضحة."

            details = {
                "trade_valid": trade_valid,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(atr_val, 4),
                "entry_zone": {
                    "vwap_baseline": round(vwap_baseline, 4),
                    "z_score": round(cmf_val, 4)
                },
                "risk_management": {
                    "take_profit_1": tp1,
                    "take_profit_2": tp2
                },
                "reason": reason
            }

            return direction, current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
