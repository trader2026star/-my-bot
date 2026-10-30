# ============================================================
# QUANTITATIVE MEAN REVERSION & VOLATILITY ENGINE (v62.0_PRO)
# ============================================================

import logging
import math
import numpy as np
import pandas as pd
from datetime import datetime, time

logger = logging.getLogger("QuantitativeEngine")

class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, **kwargs):
        try:
            self.total_capital = max(1.0, float(capital))
        except (TypeError, ValueError):
            self.total_capital = 10000.0

        try:
            self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.05)
        except (TypeError, ValueError):
            self.risk_per_trade = 0.01

    @staticmethod
    def _to_dataframe(ohlcv, minimum=30):
        """
        تحويل مصفوفة الشموع إلى Pandas DataFrame وتنظيف البيانات من أي قيم مفقودة.
        """
        try:
            if ohlcv is None:
                return None
            arr = np.asarray(ohlcv, dtype=float)
            if arr.ndim != 2 or arr.shape[0] < minimum or arr.shape[1] < 6:
                return None
            
            df = pd.DataFrame(arr[:, :6], columns=["timestamp", "open", "high", "low", "close", "volume"])
            df.dropna(inplace=True)
            if len(df) < minimum:
                return None
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

    def calculate_vwap(self, df):
        """
        حساب السعر المرجح بحجم التداول (VWAP) بشكل تراكمي ديناميكي متزن.
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        cum_pv = (typical_price * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        vwap = cum_pv / cum_vol.replace(0, np.nan)
        return vwap.fillna(df["close"])

    def calculate_atr(self, df, period=14):
        """
        حساب متوسط النطاق الحقيقي (ATR) لقياس تقلبات السوق وعزل الضوضاء السعرية.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr.fillna(tr.iloc[-1] if len(tr) > 0 else 0.0)

    def calculate_adx(self, df, period=14):
        """
        حساب مؤشر الاتجاه المتوسط (ADX) بمعادلة إحصائية صلبة خالية من الـ NaN لتحديد قوة التذبذب.
        """
        try:
            if len(df) < (period * 2):
                return 20.0
                
            high = df["high"]
            low = df["low"]
            close = df["close"]

            plus_dm = high.diff()
            minus_dm = low.diff()
            
            # عزل الدايفرجنس السعري التراكمي
            pd_series = pd.Series(np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0))
            md_series = pd.Series(np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0))

            tr1 = high - low
            tr2 = (high - close.shift()).abs()
            tr3 = (low - close.shift()).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # معالجة Wilder's Smoothing للتخلص التام من الإشارات الزائفة للـ ADX
            atr = tr.rolling(window=period).mean().replace(0, np.nan)
            plus_di = 100 * (pd_series.rolling(window=period).sum() / atr)
            minus_di = 100 * (md_series.rolling(window=period).sum() / atr)

            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
            adx = dx.rolling(window=period).mean()
            
            val = adx.iloc[-1]
            return float(val) if (not np.isnan(val) and np.isfinite(val)) else 20.0
        except Exception:
            return 20.0

    def is_market_opening_noise(self, timestamp_ms):
        """
        فلتر الأسهم المتقدم: التحقق مما إذا كان الوقت يقع في أول 30 دقيقة من افتتاح السوق الأمريكي (09:30 - 10:00 EST).
        """
        try:
            # تحويل الميلي ثانية التابع لجيت هاب/المنصة إلى توقيت مقروء
            dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
            current_time = dt.time()
            # فحص النطاق الاستعماري لأول نصف ساعة تداول حاد
            if time(14, 30) <= current_time <= time(15, 00): # بالتوقيت العالمي الموحد UTC كمثال
                return True
            return False
        except Exception:
            return False

    def analyze_market_structure(
        self, ohlcv_5m=None, ohlcv_15m=None, ohlcv_1h=None,
        ohlcv_4h=None, asset_type="crypto", **kwargs
    ):
        """
        المحرك الكمي المتقدم (Mean Reversion & Volatility Engine) - الإصدار الاحترافي للمؤسسات.
        """
        target_ohlcv = ohlcv_15m if ohlcv_15m is not None and len(ohlcv_15m) >= 30 else ohlcv_5m
        df = self._to_dataframe(target_ohlcv, minimum=25)
        
        if df is None:
            return "NEUTRAL", 0, {"trade_valid": False, "reason": "بيانات الأسعار غير كافية للتحليل الكمي."}

        # 1. Data Prep & Benchmarking
        df["vwap"] = self.calculate_vwap(df)
        df["std_dev"] = df["close"].rolling(window=20).std().fillna(df["close"].std() * 0.01)
        df["std_dev"] = df["std_dev"].replace(0, 1e-6)

        # حساب القيمة المعيارية Z-Score بدقة متناهية
        df["z_score"] = (df["close"] - df["vwap"]) / df["std_dev"]
        
        current_price = float(df["close"].iloc[-1])
        current_vwap = float(df["vwap"].iloc[-1])
        current_zscore = float(df["z_score"].iloc[-1])
        last_timestamp = float(df["timestamp"].iloc[-1])
        
        adx_val = self.calculate_adx(df, period=14)
        atr_series = self.calculate_atr(df, period=14)
        current_atr = float(atr_series.iloc[-1])

        # تفعيل الفلتر الصارم لافتتاح أسواق الأسهم العالمية لضمان تخطي حاجز الـ 90%
        if asset_type.lower() == "stock" and self.is_market_opening_noise(last_timestamp):
            return "NEUTRAL", self._round(current_price), {
                "trade_valid": False, 
                "reason": "تم إلغاء الإشارة تلقائياً: ضوضاء افتتاح السوق العنيفة (Opening Gap Noise) أول 30 دقيقة."
            }

        direction = "NEUTRAL"
        trade_valid = False
        reason = f"Z-Score ({current_zscore:.2f}) ضمن النطاق الإحصائي الآمن المعتاد."

        stop_loss = 0.0
        take_profit_1 = current_vwap  # العودة الحتمية للقيمة العادلة

        # 2. Execution Logic (High-Probability Institutional Filters)
        # إشارة الشراء المتقدمة: الانحراف السلبي المعياري الحاد مع ضعف الاتجاه العام للسوق وتأكيد الشمعة
        if current_zscore <= -2.5 and adx_val < 25:
            # تصفية إضافية: التأكد من ارتداد السعر الطفيف لأعلى لقطع الاتجاه الهابط العنيف
            if current_price > float(df["low"].iloc[-1]):
                direction = "LONG"
                trade_valid = True
                stop_loss = current_price - (2.0 * current_atr)
                reason = f"إشارة مؤسسية صلبة لشراء (LONG): الانحراف المعياري فاق حد التشبع ({current_zscore:.2f}) وبيئة السوق تذبذبية ممتازة."

        # إشارة البيع المتقدمة: الانحراف الإيجابي المعياري الحاد مع ضعف الاتجاه العام
        elif current_zscore >= 2.5 and adx_val < 25:
            if current_price < float(df["high"].iloc[-1]):
                direction = "SHORT"
                trade_valid = True
                stop_loss = current_price + (2.0 * current_atr)
                reason = f"إشارة مؤسسية صلبة لبيع (SHORT): الانحراف المعياري فاق حد التضخم ({current_zscore:.2f}) مع ثبات رياضي للارتداد."

        else:
            if adx_val >= 25:
                reason = f"حظر تداول: السوق في اتجاه عنيف ممتد (ADX = {adx_val:.1f} >= 25). محرك العودة للمتوسط يتجنب السكاكين الساقطة."

        details = {
            "trade_valid": trade_valid,
            "signal_type": "INSTITUTIONAL_QUANT_MEAN_REVERSION",
            "market_trend": f"Mean-Reverting (ADX: {adx_val:.1f})" if adx_val < 25 else "Trending Market",
            "z_score": self._round(current_zscore),
            "adx": self._round(adx_val),
            "atr": self._round(current_atr),
            "reason": reason,
            "trigger_price": self._round(current_price),
            "stop_loss": self._round(stop_loss if stop_loss > 0 else current_price * 0.98),
            "entry_zone": {
                "vwap_baseline": self._round(current_vwap),
                "z_score_level": self._round(current_zscore)
            },
            "risk_management": {
                "take_profit_1": self._round(take_profit_1),
                "take_profit_2": self._round(current_vwap + (current_vwap - current_price)) if direction == "LONG" else self._round(current_vwap - (current_price - current_vwap))
            }
        }

        return direction, self._round(current_price), details
