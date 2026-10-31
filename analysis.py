# ============================================================
# MY EXPERT CRYPTO BOT - Institutional SMC Engine (v65.0_PRO)
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

    def calculate_cmf(self, df, period=period=20):
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            volume = df['volume']
            
            mf_multiplier = ((close - low) - (high - close)) / (high - low + 1e-9)
            mf_volume = mf_multiplier * volume
            cmf = mf_volume.rolling(window=period).sum() / (volume.rolling(window=period).sum() + 1e-9)
            val = float(cmf.iloc[-1])
            return val if not np.isnan(val) else 0.0
        except Exception:
            return 0.0

    def detect_smc_structure(self, df):
        """
        محرك الـ SMC الاحترافي: رصد الـ CHoCH/BOS، الـ Order Blocks المؤسسية، والـ FVG الحقيقية.
        """
        try:
            if len(df) < 30:
                return {"bias": "NEUTRAL", "bullish_fvg": False, "bearish_fvg": False, "ob_zone": 0.0, "is_mitigated": False, "reason": "بيانات غير كافية"}

            # 1. رصد الـ Order Blocks (OB): نبحث عن آخر شمعة بيعية قبل الانفجار الصعودي أو العكس
            ob_zone = 0.0
            is_mitigated = False
            for i in range(len(df)-2, 10, -1):
                # Bullish Order Block نموذجى (+OB) تماماً كما في الشارت
                if df['close'].iloc[i] < df['open'].iloc[i] and df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    ob_zone = float(df['low'].iloc[i])
                    # التحقق مما إذا كان السعر قد عاد ملامستها Mitigated أم لا
                    mitigating_price = df['low'].iloc[-1]
                    if mitigating_price <= df['high'].iloc[i]:
                        is_mitigated = True
                    break

            # 2. رصد هيكل السوق: كسر الهيكل الصاعد (BOS) نموذجى
            is_bullish_structure = False
            is_choch = False
            recent_high = df['high'].iloc[-15:-2].max()
            if df['close'].iloc[-1] > recent_high:
                is_bullish_structure = True
                # للتبسيط، نعتبر أول BOS صاعد هو CHoCH
                is_choch = True 

            # 3. رصد الفجوات السعرية (FVG) في نطاق الفحص
            bullish_fvg = False
            for i in range(3, len(df)):
                if df['low'].iloc[i] > df['high'].iloc[i-3]:
                    bullish_fvg = True
                    break

            bias = "NEUTRAL"
            reason = "لا يوجد تأكيد هيكلي صاعد أو هابط."
            if is_bullish_structure and (is_mitigated or bullish_fvg):
                bias = "BULLISH"
                reason = "اختراق BOS/CHoCH صعودي مع اختبار Order Block مدعوم بالسيولة."
            elif df['close'].iloc[-1] < recent_low and bearish_fvg:
                # هذا جزء تبسيطي للهيكل الهابط
                bias = "BEARISH"
                reason = "كسر هيكل هابط مدعوم بالفجوات (Bearish FVG)."

            return {
                "bias": bias,
                "bullish_fvg": bool(bullish_fvg),
                "bearish_fvg": bool(df['high'].iloc[-1] < df['low'].iloc[-3]), # فحص FVG هابط لحظي
                "ob_zone": ob_zone,
                "is_mitigated": is_mitigated,
                "is_choch": is_choch,
                "reason": reason
            }
        except Exception as e:
            return {"bias": "NEUTRAL", "bullish_fvg": False, "bearish_fvg": False, "ob_zone": 0.0, "is_mitigated": False, "reason": f"خطأ برمجى: {e}"}

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
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

            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            current_price = float(df_5m['close'].iloc[-1])

            df_5m['ema20'] = df_5m['close'].ewm(span=20, adjust=False).mean()
            df_5m['ema50'] = df_5m['close'].ewm(span=50, adjust=False).mean()

            vwap_baseline = float(df_5m['ema20'].iloc[-1])
            atr_val = float(self.calculate_atr(df_5m, period=14))
            cmf_val = float(self.calculate_cmf(df_5m, period=period=20))

            if atr_val <= 0 or np.isnan(atr_val):
                atr_val = current_price * 0.01

            # استدعاء تحليلات الـ SMC الاحترافية على إطار الـ 5 دقائق
            smc = self.detect_smc_structure(df_5m)

            # تحديد الاتجاه المؤسسي بناءً على الـ CHoCH/BOS والـ Order Block
            direction = smc["bias"]
            trade_valid = False
            reason = smc["reason"]

            decimals = 8 if current_price < 1 else (4 if current_price < 100 else 2)

            # منطق الدخول المؤسسي بناءً على اختبار منطقة الـ OB تماماً كما في الشارت
            if direction == "BULLISH" and cmf_val > -0.08:
                trade_valid = True
                
                # وقف الخسارة الاحترافي يوضع أسفل منطقة الـ Order Block المؤسسي (+OB) تماماً لحماية رأس المال
                stop_loss = round(min(smc["ob_zone"], current_price - (2.5 * atr_val)), decimals)
                # تأكيد حماية لمنع الوقف فوق السعر
                if stop_loss >= current_price:
                    stop_loss = round(current_price * 0.98, decimals)

                # الأهداف الاستراتيجية كما في طريقتك: TP1 عند قمة قريبة (BOS)، TP2 عند فجوات عليا (External Liquidity)
                tp1 = round(current_price + (1.5 * atr_val), decimals)
                tp2 = round(current_price + (3.0 * atr_val), decimals)
                # TP3 يتم حسابه على مسافة أبعد نموذجياً ( External Liquidity Pools)
                tp3 = round(current_price + (5.0 * atr_val), decimals)
                
                # تجميع الأسباب بتنسيق احترافي
                reasons = []
                if smc["mitigated"]: reasons.append(f"اختبار ناجح لمنطقة Order Block مؤسسي (+OB) عند {round(smc['ob_zone'], decimals)}")
                if smc["choch"]: reasons.append("تغير شخصية الهيكل (CHoCH) صعودي")
                if smc["bullish_fvg"]: reasons.append("رصد فجوة صاعدة (Bullish FVG) تدعم السيولة")
                if cmf_val > 0: reasons.append("تدفق سيولة الحيتان (CMF) إيجابي")
                
                if reasons:
                    reason = " + ".join(reasons)
                else:
                    reason = "تأكيد هيكلي مؤسسي مدعوم بالسيولة."

            elif direction == "BEARISH" and cmf_val < 0.08:
                trade_valid = True
                
                stop_loss = round(max(current_price + (2.5 * atr_val), current_price + 0.005), decimals)
                if stop_loss <= current_price:
                    stop_loss = round(current_price * 1.02, decimals)

                tp1 = round(current_price - (1.5 * atr_val), decimals)
                tp2 = round(current_price - (3.0 * atr_val), decimals)
                tp3 = round(current_price - (5.0 * atr_val), decimals)
                reason = "ضغط بيعي مؤسسي مدعوم بالفجوات وهيكل هابط."
            else:
                stop_loss = round(current_price * 0.98, decimals)
                tp1 = current_price
                tp2 = current_price
                # reason يبقى NEUTRAL أو سبب تم رصده

            details = {
                "trade_valid": trade_valid,
                "trigger_price": current_price,
                "stop_loss": stop_loss,
                "atr": round(atr_val, decimals),
                "entry_zone": {
                    "vwap_baseline": round(vwap_baseline, decimals),
                    "z_score": round(cmf_val, 4),
                    "smc_bias": smc["bias"],
                    "fvg_up": smc["bullish_fvg"],
                    "sweep_down": smc[" mititaged"], # التحقق من اختبار السيولة
                    "order_block": round(smc["ob_zone"], decimals)
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
