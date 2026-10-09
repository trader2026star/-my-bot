# ==========================================
# ADVANCED QUANTITATIVE & SMART MONEY ANALYSIS (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import numpy as np
import pandas as pd

class StrategyEngine:
    def __init__(self):
        pass

    def calculate_atr(self, highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            c_prev = closes[i-1]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr_list.append(tr)
        return float(np.mean(tr_list[-period:]))

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None):
        """
        تحليل متعدد الأطر الزمنية مع تقييم نقاط دقيق (Score 0-100)
        """
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m or len(ohlcv_4h) < 15 or len(ohlcv_1h) < 15 or len(ohlcv_15m) < 15:
            return "NEUTRAL", 0, 1.0, {}, []

        # استخراج البيانات
        closes_4h = [c[4] for c in ohlcv_4h]
        closes_1h = [c[4] for c in ohlcv_1h]
        volumes_1h = [c[5] for c in ohlcv_1h]
        highs_1h = [c[2] for c in ohlcv_1h]
        lows_1h = [c[3] for c in ohlcv_1h]
        
        closes_15m = [c[4] for c in ohlcv_15m]
        highs_15m = [c[2] for c in ohlcv_15m]
        lows_15m = [c[3] for c in ohlcv_15m]

        confirmations = []
        reasons_excluded = []
        score = 50

        # 1. اتجاه 4H (الأتجاه الرئيسي)
        trend_4h = "LONG" if closes_4h[-1] > closes_4h[0] else "SHORT"
        confirmations.append(f"اتّجاه 4H الرئيسي: {trend_4h}")

        # 2. اتجاه 1H وزخم
        trend_1h = "LONG" if closes_1h[-1] > closes_1h[-5] else "SHORT"
        if trend_4h == trend_1h:
            score += 20
            confirmations.append(f"تطابق اتجاه 1H مع 4H ({trend_1h})")
        else:
            score -= 15
            reasons_excluded.append("تعارض بين اتجاه 4H و 1H")

        # 3. تحليل حجم التداول على 1H
        avg_vol = np.mean(volumes_1h[-15:-1]) if len(volumes_1h) > 15 else volumes_1h[-1]
        cur_vol = volumes_1h[-1]
        vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        
        if vol_ratio >= 1.2:
            score += 15
            confirmations.append(f"حجم تداول قوي مرتفع ({vol_ratio}x المتوسط)")
        else:
            score -= 5
            reasons_excluded.append(f"حجم تداول ضعيف أو طبيعي ({vol_ratio}x)")

        # 4. تأكيد 15M (الزخم القصير وتكوين البنية)
        momentum_15m = "LONG" if closes_15m[-1] > closes_15m[-3] else "SHORT"
        if momentum_15m == trend_1h:
            score += 15
            confirmations.append(f"توافق زخم 15M مع التريند العام")
        else:
            score -= 10
            reasons_excluded.append("زخم 15M عكس الاتجاه الحالي")

        # 5. تأثير البيتكوين كمساعد (إن وُجد)
        if ohlcv_btc_1h and len(ohlcv_btc_1h) >= 5:
            btc_trend = "LONG" if ohlcv_btc_1h[-1][4] > ohlcv_btc_1h[-5][4] else "SHORT"
            if btc_trend == trend_1h:
                score += 10
                confirmations.append("سياق حركة البيتكوين داعم للاتجاه")
            else:
                score -= 10
                reasons_excluded.append("حركة البيتكوين غير داعمة للاتجاه")

        # الحد النهائي للنقاط
        score = max(0, min(100, score))

        # تحديد الإشارة النهائية
        if score >= 75:
            signal = trend_1h
        elif score >= 65:
            signal = trend_1h  # متوسطة مشروطة
        else:
            signal = "NEUTRAL"
            reasons_excluded.append(f"التقييم الكلي ضعيف ({score}/100)")

        details = {
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "volume_ratio": vol_ratio,
            "confirmations": confirmations,
            "reasons_excluded": reasons_excluded
        }

        return signal, score, vol_ratio, details, (highs_1h, lows_1h, closes_1h)

    def calculate_risk_management(self, entry_price, direction, highs, lows):
        """
        إدارة مخاطر مبنية على الهيكل الفعلي (Swing High/Low) ومؤشر ATR
        """
        direction = direction.upper()
        atr = self.calculate_atr(highs, lows, highs) # تقريب ATR مبسط
        if atr <= 0:
            atr = entry_price * 0.015

        if direction in ['LONG', 'BUY']:
            swing_low = min(lows[-5:]) if len(lows) >= 5 else entry_price * 0.98
            stop_loss = min(swing_low, entry_price - (atr * 1.5))
            if stop_loss >= entry_price:
                stop_loss = entry_price * 0.985
            
            risk_dist = entry_price - stop_loss
            tp1 = entry_price + (risk_dist * 1.5)
            tp2 = entry_price + (risk_dist * 2.5)
            tp3 = entry_price + (risk_dist * 4.0)
        else:
            swing_high = max(highs[-5:]) if len(highs) >= 5 else entry_price * 1.02
            stop_loss = max(swing_high, entry_price + (atr * 1.5))
            if stop_loss <= entry_price:
                stop_loss = entry_price * 1.015
            
            risk_dist = stop_loss - entry_price
            tp1 = entry_price - (risk_dist * 1.5)
            tp2 = entry_price - (risk_dist * 2.5)
            tp3 = entry_price - (risk_dist * 4.0)

        # حساب النسب المئوية للمخاطرة والعائد
        sl_pct = round(abs(entry_price - stop_loss) / entry_price * 100, 2)
        tp1_pct = round(abs(tp1 - entry_price) / entry_price * 100, 2)

        return round(stop_loss, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4), sl_pct, tp1_pct
