# ==========================================
# INSTITUTIONAL SMC & LIQUIDITY SWEEP ENGINE
# File: analysis.py
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import numpy as np
from datetime import datetime, timezone


class StrategyEngine:
    def __init__(self):
        pass

    @staticmethod
    def valid_ohlcv(data):
        if not isinstance(data, (list, tuple)) or len(data) < 10:
            return False
        try:
            for candle in data:
                if len(candle) < 6:
                    return False
                values = [float(candle[i]) for i in range(1, 6)]
                if not all(np.isfinite(v) for v in values):
                    return False
                if float(candle[2]) < float(candle[3]):
                    return False
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(ohlcv):
        opens = np.array([float(c[1]) for c in ohlcv])
        highs = np.array([float(c[2]) for c in ohlcv])
        lows = np.array([float(c[3]) for c in ohlcv])
        closes = np.array([float(c[4]) for c in ohlcv])
        volumes = np.array([max(0.0, float(c[5])) for c in ohlcv])
        return opens, highs, lows, closes, volumes

    @staticmethod
    def get_allowed_trading_window():
        """
        التحقق من أوقات التداول الثلاثة للسيولة العالية (بتوقيت UTC):
        1. افتتاح الشمعة اليومية (00:00 UTC / 03:00 فجراً مكة) لمدة 45 دقيقة
        2. افتتاح جلسة لندن (07:00 إلى 10:00 UTC / 10:00 صباحاً إلى 1:00 ظهراً مكة)
        3. افتتاح جلسة نيويورك (12:00 إلى 15:00 UTC / 03:00 عصراً إلى 6:00 مساءً مكة)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute

        if hour == 0 and minute <= 45:
            return True, "افتتاح الشمعة اليومية (03:00 فجراً مكة)"
        elif 7 <= hour < 10:
            return True, "جلسة افتتاح لندن (من 10:00 صباحاً مكة)"
        elif 12 <= hour < 15:
            return True, "جلسة افتتاح نيويورك (من 03:00 عصراً مكة)"
        
        return False, "خارج أوقات الذروة المحددة للسيولة"

    @staticmethod
    def _trend(highs, lows, closes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        if len(closes) < 6:
            return "NEUTRAL"

        ref_high = float(np.max(highs[-6:-1]))
        ref_low = float(np.min(lows[-6:-1]))
        last_close = float(closes[-1])

        if last_close > ref_high:
            return "LONG"
        if last_close < ref_low:
            return "SHORT"

        return "NEUTRAL"

    def detect_smc_structure_15m(self, opens, highs, lows, closes, volumes, daily_high, daily_low):
        """فحص الشروط المؤسسية الكاملة على فريم 15M اعتماداً حصرياً على الشموع المكتملة"""
        n = len(closes)
        if n < 10:
            return "NONE", False, False, False, 0.0

        # الاعتماد على الشموع المكتملة تماماً لتجنب الإشارات الوهمية
        last_h = float(highs[-2])
        last_l = float(lows[-2])
        last_o = float(opens[-2])
        last_c = float(closes[-2])
        
        prev_h = float(highs[-3])
        prev_l = float(lows[-3])

        # 1. فحص كنس السيولة والرفض (Sweep & Rejection)
        bearish_sweep = (last_h >= daily_high or prev_h >= daily_high) and (last_c < last_o)
        bullish_sweep = (last_l <= daily_low or prev_l <= daily_low) and (last_c > last_o)

        # 2. فحص كسر الهيكل (CHoCH / MSS) على 15M
        recent_low_swing = float(np.min(lows[-9:-2]))
        recent_high_swing = float(np.max(highs[-9:-2]))

        bearish_choch = bearish_sweep and (last_c < recent_low_swing or float(closes[-2]) < recent_low_swing)
        bullish_choch = bullish_sweep and (last_c > recent_high_swing or float(closes[-2]) > recent_high_swing)

        # 3. فحص الـ FVG أو Order Block بناءً على الشموع المكتملة
        has_fvg = False
        if bearish_sweep and float(highs[-2]) < float(lows[-4]):
            has_fvg = True
        elif bullish_sweep and float(lows[-2]) > float(highs[-4]):
            has_fvg = True

        # 4. فحص الفوليوم
        avg_vol = float(np.mean(volumes[-11:-2])) if len(volumes) >= 11 else 1.0
        curr_vol = float(volumes[-2])
        vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        good_volume = vol_ratio >= 1.1

        signal = "NONE"
        if bearish_sweep:
            signal = "SHORT"
        elif bullish_sweep:
            signal = "LONG"

        choch_valid = (signal == "SHORT" and bearish_choch) or (signal == "LONG" and bullish_choch)

        return signal, choch_valid, has_fvg, good_volume, vol_ratio

    def analyze_multi_timeframe(self, ohlcv_weekly, ohlcv_daily, ohlcv_15m):
        empty_details = {
            "trend_weekly": "NEUTRAL",
            "daily_high": 0.0,
            "daily_low": 0.0,
            "sweep": "NONE",
            "retest_advice": "بيانات غير كافية",
            "entry_valid": False,
            "confirmations": [],
            "reasons_excluded": ["بيانات غير كافية للتحليل"]
        }

        if not all(self.valid_ohlcv(x) for x in (ohlcv_weekly, ohlcv_daily, ohlcv_15m)):
            return "NEUTRAL", 0, 0.0, empty_details, ([], [], [])

        # 1. فحص توقيت الجلسة الصارم
        is_allowed_time, time_desc = self.get_allowed_trading_window()
        confirmations = [f"التوقيت الحالي: {time_desc}"]
        excluded = []

        if not is_allowed_time:
            excluded.append("الوقت الحالي ليس ضمن الأوقات الثلاثة المحددة للافتتاح")
            return "NEUTRAL", 0, 0.0, empty_details, ([], [], [])

        # 2. تحديد الاتجاه من الفريم الأسبوعي
        ow, hw, lw, cw, vw = self.arrays(ohlcv_weekly)
        trend_weekly = self._trend(hw[:-1], lw[:-1], cw[:-1])
        confirmations.append(f"اتجاه الإطار الأسبوعي (Weekly): {trend_weekly}")

        # 3. مستويات اليوم السابق المكتملة ([-2])
        od, hd, ld, cd, vd = self.arrays(ohlcv_daily)
        daily_high = float(hd[-2])
        daily_low = float(ld[-2])
        confirmations.append(f"مستويات اليوم السابق - القمة: {daily_high:.8g} | القاع: {daily_low:.8g}")

        # 4. تحليل الهيكل المؤسسي على 15M
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)
        
        signal, choch_valid, has_fvg, good_volume, vol_ratio = self.detect_smc_structure_15m(
            o15, h15, l15, c15, v15, daily_high, daily_low
        )

        score = 40

        # ربط توافق السويب مع الاتجاه الأسبوعي لتعزيز جودة النقاط
        is_pro_trend = (signal == trend_weekly) if trend_weekly in ("LONG", "SHORT") else False

        if signal == "SHORT":
            confirmations.append("تم رصد كنس لسيولة قمة اليوم السابق مع شمعة رفض هابطة")
            score += 25
            if is_pro_trend:
                confirmations.append("السويب متوافق مع الاتجاه الهابط الرئيسي على الإطار الأسبوعي (+10 نقاط)")
                score += 10
            if choch_valid:
                confirmations.append("تأكيد كسر الهيكل (CHoCH / MSS) لصالح الهبوط")
                score += 15
            if has_fvg:
                confirmations.append("رصد فجوة سعرية اندفاعية (FVG) تدعم الهبوط")
                score += 10
            if good_volume:
                confirmations.append(f"ارتفاع الفوليوم المؤكد ({vol_ratio}x)")
                score += 10

        elif signal == "LONG":
            confirmations.append("تم رصد كنس لسيولة قاع اليوم السابق مع شمعة شراء ارتدادية")
            score += 25
            if is_pro_trend:
                confirmations.append("السويب متوافق مع الاتجاه الصاعد الرئيسي على الإطار الأسبوعي (+10 نقاط)")
                score += 10
            if choch_valid:
                confirmations.append("تأكيد كسر الهيكل (CHoCH / MSS) لصالح الصعود")
                score += 15
            if has_fvg:
                confirmations.append("رصد فجوة سعرية اندفاعية (FVG) تدعم الصعود")
                score += 10
            if good_volume:
                confirmations.append(f"ارتفاع الفوليوم المؤكد ({vol_ratio}x)")
                score += 10
        else:
            excluded.append("السعر لم يقم بكنس سيولة قمة أو قاع اليوم السابق")

        score = int(max(0, min(100, round(score))))
        
        entry_valid = (signal in ("LONG", "SHORT") and score >= 75)

        if not entry_valid:
            excluded.append("شروط التأكيد الهيكلي الفائقة (CHoCH / Volume / FVG / الاتجاه) لم تكتمل بالقدر الكافي")

        details = {
            "trend_weekly": trend_weekly,
            "daily_high": daily_high,
            "daily_low": daily_low,
            "sweep": signal,
            "retest_advice": "تأكد من تأكيد الرفض وكسر الهيكل على 15M قبل الدخول",
            "entry_valid": bool(entry_valid),
            "confirmations": confirmations,
            "reasons_excluded": excluded
        }

        return (
            signal, score, vol_ratio, details,
            (h15.tolist(), l15.tolist(), c15.tolist())
        )

    def calculate_risk_management(
        self, entry_price, direction, highs, lows, daily_high=0, daily_low=0
    ):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)

        if entry <= 0:
            raise ValueError("سعر دخول غير صالح")

        if direction in ("LONG", "BUY"):
            sweep_low = min(float(np.min(lows[-4:])), daily_low) if daily_low > 0 else float(np.min(lows[-4:]))
            stop = sweep_low * 0.998 if sweep_low < entry else entry * 0.985
            
            target_high = daily_high if daily_high > entry else entry * 1.04
            total_distance = abs(target_high - entry)
            
            tp1 = entry + (total_distance * 0.5)
            tp2 = target_high
            tp3 = target_high * 1.015  # امتداد إضافي للهدف الثالث

        elif direction in ("SHORT", "SELL"):
            sweep_high = max(float(np.max(highs[-4:])), daily_high) if daily_high > 0 else float(np.max(highs[-4:]))
            stop = sweep_high * 1.002 if sweep_high > entry else entry * 1.015
            
            target_low = daily_low if daily_low < entry else entry * 0.96
            total_distance = abs(entry - target_low)
            
            tp1 = entry - (total_distance * 0.5)
            tp2 = target_low
            tp3 = target_low * 0.985  # امتداد إضافي للهدف الثالث

        else:
            raise ValueError("الاتجاه يجب أن يكون LONG أو SHORT")

        sl_pct = round(abs(entry - stop) / entry * 100, 3)
        tp1_pct = round(abs(tp1 - entry) / entry * 100, 3)
        rr_ratio = round(abs(tp1 - entry) / max(abs(entry - stop), 0.00001), 2)

        return (
            round(float(stop), 10),
            round(float(tp1), 10),
            round(float(tp2), 10),
            round(float(tp3), 10),
            sl_pct,
            tp1_pct,
            rr_ratio
        )
