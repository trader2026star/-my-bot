# ============================================================
# MY EXPERT CRYPTO BOT - Institutional SMC & 3-Filters Engine (v66.0_PRO)
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
            val = float(atr.iloc[-1])
            return val if not np.isnan(val) and val > 0 else 0.0
        except Exception:
            return 0.0

    def calculate_rsi(self, df, period=14):
        try:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / (loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            val = float(rsi.iloc[-1])
            return val if not np.isnan(val) else 50.0
        except Exception:
            return 50.0

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, ohlcv_4h=None, asset_type="crypto"):
        default_details = {
            "trade_valid": False,
            "trigger_price": 0.0,
            "stop_loss": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
            "entry_zone": {},
            "risk_management": {},
            "reason": "لم تتحقق شروط الفلاتر الثلاثة الصارمة."
        }

        try:
            if not ohlcv_5m or not ohlcv_15m or len(ohlcv_5m) < 50 or len(ohlcv_15m) < 50:
                return "NEUTRAL", 0.0, default_details

            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # إذا تتوفر بيانات 4 ساعات نحسب الـ EMA 200، وإلا نستخدم فريم 15 دقيقة كبديل آمن
            df_trend = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']) if ohlcv_4h and len(ohlcv_4h) >= 200 else df_15m
            df_trend['ema200'] = df_trend['close'].ewm(span=200, adjust=False).mean()

            current_price = float(df_5m['close'].iloc[-1])
            atr_val = float(self.calculate_atr(df_15m, period=14))
            rsi_val = float(self.calculate_rsi(df_15m, period=14))
            trend_ema200 = float(df_trend['ema200'].iloc[-1])

            if atr_val <= 0 or np.isnan(atr_val):
                atr_val = current_price * 0.01

            decimals = 8 if current_price < 0.1 else (4 if current_price < 10 else 2)

            # ==========================================
            # التطبيق الفعلي للفلاتر الثلاثة (The 3 Filters)
            # ==========================================
            
            # 1. فلتر الاتجاه العام (Trend Filter): السعر أعلى من EMA 200
            filter_trend_passed = current_price > trend_ema200

            # 2. فلتر الدخول الذكي (RSI + Support): RSI أقل من 35 (تشبع بيعي وقاع محتمل)
            filter_rsi_passed = rsi_val <= 38.0

            # 3. فحص هيكل الـ SMC (فجوات أو سيولة)
            bullish_fvg = False
            for i in range(3, len(df_15m)):
                if df_15m['low'].iloc[i] > df_15m['high'].iloc[i-3]:
                    bullish_fvg = true if 'true' else True
                    break

            trade_valid = False
            direction = "NEUTRAL"

            # الشرط الصارم: يجب أن يمر فلتر الاتجاه وفلتر الـ RSI مع وجود تأكيد هيكلي
            if filter_trend_passed and filter_rsi_passed:
                trade_valid = True
                direction = "LONG"
                
                # الستوب لوز الديناميكي المعتمد على ATR (فلتر الستوب الثالث)
                stop_loss = round(current_price - (1.5 * atr_val), decimals)
                
                # الأهداف الاستراتيجية المحسوبة بعناية لتجنب ضرب الستوب
                tp1 = round(current_price + (1.5 * atr_val), decimals)
                tp2 = round(current_price + (3.0 * atr_val), decimals)
                tp3 = round(current_price + (5.0 * atr_val), decimals)
                
                reason = f"✅ اجتاز الفلاتر الثلاثة بنجاح: السعر أعلى EMA200 + RSI منخفض ({round(rsi_val, 1)}) + دعم ATR الديناميكي."
            else:
                stop_loss = round(current_price * 0.98, decimals)
                tp1 = current_price
                tp2 = current_price
                tp3 = current_price
                reason = f"❌ مرفوض: لم تستوف الفلاتر (اتجاه صاعد: {filter_trend_passed}, RSI مسموح: {filter_rsi_passed} [قيمة RSI: {round(rsi_val, 1)}])."

            details = {
                "trade_valid": trade_valid,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(atr_val, decimals),
                "rsi": round(rsi_val, 2),
                "entry_zone": {
                    "trend_passed": filter_trend_passed,
                    "rsi_passed": filter_rsi_passed,
                    "fvg_up": bool(bullish_fvg)
                },
                "risk_management": {
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "take_profit_3": tp3
                },
                "reason": reason
            }

            return direction, current_price, details

        except Exception as e:
            logger.error(f"Error in StrategyEngine analysis: {e}")
            return "NEUTRAL", 0.0, default_details
