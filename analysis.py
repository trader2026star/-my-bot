# ==========================================
# ADVANCED DAILY & WEEKLY SWEEP ENGINE
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
        if not isinstance(data, (list, tuple)) or len(data) < 5:
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
        التحقق من أوقات التداول الثلاثة المطلوبة:
        1. وقت افتتاح الشمعة اليومية (بداية اليوم UTC)
        2. وقت افتتاح جلسة لندن (07:00 UTC / 10:00 صباحاً مكة)
        3. وقت افتتاح جلسة نيويورك (12:00 UTC / 03:00 عصراً مكة)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute

        # 1. نافذة افتتاح الشمعة اليومية
        if hour == 0 and minute <= 45:
            return True, "افتتاح الشمعة اليومية"
        
        # 2. نافذة افتتاح جلسة لندن
        elif 7 <= hour < 10:
            return True, "جلسة افتتاح لندن"
        
        # 3. نافذة افتتاح جلسة نيويورك
        elif 12 <= hour < 15:
            return True, "جلسة افتتاح نيويورك"
        
        return False, "خارج أوقات الأوقات الثلاثة المحددة"

    @staticmethod
    def _trend(highs, lows, closes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        if len(closes) < 4:
            return "NEUTRAL"

        ref_high = float(np.max(highs[-4:-1]))
        ref_low = float(np.min(lows[-4:-1]))
        last_close = float(closes[-1])

        if last_close > ref_high:
            return "LONG"
        if last_close < ref_low:
            return "SHORT"

        return "NEUTRAL"

    def analyze_multi_timeframe(
        self, ohlcv_weekly, ohlcv_daily, ohlcv_15m
    ):
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

        if not all(
            self.valid_ohlcv(x)
            for x in (ohlcv_weekly, ohlcv_daily, ohlcv_15m)
        ):
            return "NEUTRAL", 0, 0.0, empty_details, ([], [], [])

        # 1. فحص الوقت المحدد (الأوقات الثلاثة للبورصة)
        is_allowed_time, time_desc = self.get_allowed_trading_window()
        confirmations = [f"التوقيت الحالي: {time_desc}"]
        excluded = []

        if not is_allowed_time:
            excluded.append("الوقت الحالي ليس ضمن الأوقات الثلاثة المحددة للافتتاح")
            return "NEUTRAL", 0, 0.0, empty_details, ([], [], [])

        # 2. تحديد الاتجاه من الإطار الأسبوعي (Weekly)
        ow, hw, lw, cw, vw = self.arrays(ohlcv_weekly)
        trend_weekly = self._trend(hw[:-1], lw[:-1], cw[:-1])
        confirmations.append(f"اتجاه الإطار الأسبوعي (Weekly): {trend_weekly}")

        # 3. استخراج قمة وقاع الشمعة اليومية السابقة بدقة ([-2])
        od, hd, ld, cd, vd = self.arrays(ohlcv_daily)
        daily_high = float(hd[-2])
        daily_low = float(ld[-2])
        confirmations.append(f"مستويات اليوم السابق - القمة: {daily_high:.8g} | القاع: {daily_low:.8g}")

        # 4. فحص فريم الـ 15 دقيقة (15M) بدقة للشمعة
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)
        
        # الشمعة الأخيرة المغلقة على فريم الـ 15 دقيقة
        last_open_15m = o15[-2]
        last_high_15m = h15[-2]
        last_low_15m = l15[-2]
        last_close_15m = c15[-2]

        sweep = "NONE"
        direction = "NEUTRAL"
        score = 50

        # شرط البيع: الشمعة تجاوزت قمة اليوم السابق وأغلقت هابطة (شمعة رفض بذيل علوي)
        if last_high_15m >= daily_high and last_close_15m < last_open_15m:
            sweep = "BEARISH_REJECTION_AT_DAILY_HIGH"
            if trend_weekly in ("SHORT", "NEUTRAL"):
                direction = "SHORT"
                score += 35
                confirmations.append("تم رصد كنس للسيولة وشمعة رفض هابطة مؤكدة عند قمة اليوم السابق")

        # شرط الشراء: الشمعة كسر قاع اليوم السابق وأغلقت صاعدة (شمعة ارتداد بذيل سفلي)
        elif last_low_15m <= daily_low and last_close_15m > last_open_15m:
            sweep = "BULLISH_REJECTION_AT_DAILY_LOW"
            if trend_weekly in ("LONG", "NEUTRAL"):
                direction = "LONG"
                score += 35
                confirmations.append("تم رصد كنس للسيولة وشمعة شراء صاعدة مؤكدة عند قاع اليوم السابق")
        else:
            excluded.append("لم تظهر شمعة رفض/ارتداد واضحة على فريم 15M عند قمة أو قاع اليوم السابق")

        score = int(max(0, min(100, round(score))))
        entry_valid = (direction in ("LONG", "SHORT") and score >= 75)

        if not entry_valid:
            excluded.append("شروط شمعة الرفض أو الشراء عند أطراف الشمعة اليومية السابقة لم تكتمل بعد")

        details = {
            "trend_weekly": trend_weekly,
            "daily_high": daily_high,
            "daily_low": daily_low,
            "sweep": sweep,
            "retest_advice": "تأكد من إغلاق شمعة الـ 15M بالكامل وتحديد الرفض قبل التنفيذ",
            "entry_valid": bool(entry_valid),
            "confirmations": confirmations,
            "reasons_excluded": excluded
        }

        return (
            direction, score, 1.5, details,
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

        # حساب الأهداف:
        # TP1 = 50% من منتصف النطاق
        # TP2 = الطرف المقابل الكامل للشمعة اليومية السابقة
        if direction in ("LONG", "BUY"):
            stop = daily_low if daily_low > 0 else entry * 0.98
            mid_range = entry + ((daily_high - entry) / 2.0) if daily_high > entry else entry * 1.02
            
            tp1 = mid_range
            tp2 = daily_high if daily_high > entry else entry * 1.04
            tp3 = tp2

        elif direction in ("SHORT", "SELL"):
            stop = daily_high if daily_high > 0 else entry * 1.02
            mid_range = entry - ((entry - daily_low) / 2.0) if daily_low < entry else entry * 0.98

            tp1 = mid_range
            tp2 = daily_low if daily_low < entry else entry * 0.96
            tp3 = tp2

        else:
            raise ValueError("الاتجاه يجب أن يكون LONG أو SHORT")

        sl_pct = round(abs(entry - stop) / entry * 100, 3)
        tp1_pct = round(abs(tp1 - entry) / entry * 100, 3)
        rr_ratio = 2.0

        return (
            round(float(stop), 10),
            round(float(tp1), 10),
            round(float(tp2), 10),
            round(float(tp3), 10),
            sl_pct,
            tp1_pct,
            rr_ratio
        )
