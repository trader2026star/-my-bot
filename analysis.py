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
        1. وقت افتتاح الشمعة اليومية (حوالي الساعة 03:00 UTC / 06:00 مكة أو بدايتها)
        2. وقت افتتاح جلسة لندن (07:00 UTC / 10:00 صباحاً مكة)
        3. وقت افتتاح جلسة نيويورك (12:00 UTC / 03:00/04:30 عصراً مكة)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute

        # 1. نافذة افتتاح الشمعة اليومية (الساعة 3 فجراً بتوقيت UTC تقريباً أو بدايتها)
        if hour == 3 and minute <= 45:
            return True, "افتتاح الشمعة اليومية"
        
        # 2. نافذة افتتاح جلسة لندن (الساعة 7 إلى 9 صباحاً UTC / 10 صباحاً مكة)
        elif 7 <= hour < 10:
            return True, "جلسة افتتاح لندن"
        
        # 3. نافذة افتتاح جلسة نيويورك (الساعة 12 إلى 15 UTC / 3 عصراً مكة)
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

        # 3. استخراج قمة وقاع الشمعة اليومية (Daily Candle)
        od, hd, ld, cd, vd = self.arrays(ohlcv_daily)
        # الشمعة اليومية السابقة أو الحالية المكتملة جزئياً
        daily_high = float(hd[-2])
        daily_low = float(ld[-2])
        confirmations.append(f"مستويات اليوم - القمة: {daily_high:.8g} | القاع: {daily_low:.8g}")

        # 4. فحص فريم الـ 15 دقيقة (15M) للبحث عن كنس السيولة والرفض
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)
        
        current_price = float(c15[-1])
        last_high_15m = float(np.max(h15[-5:-1]))
        last_low_15m = float(np.min(l15[-5:-1]))

        sweep = "NONE"
        direction = "NEUTRAL"
        score = 50

        # شرط البيع: السعر كسر قمة الشمعة اليومية وحدث رفض على فريم 15 دقيقة
        if current_price >= daily_high or h15[-1] >= daily_high:
            if c15[-1] < o15[-1]:  # شمعة هابطة/رفض
                sweep = "BEARISH_REJECTION_AT_DAILY_HIGH"
                if trend_weekly == "SHORT" or trend_weekly == "NEUTRAL":
                    direction = "SHORT"
                    score += 30
                    confirmations.append("تم رصد كنس للسيولة وشمعة رفض هابطة عند قمة الشمعة اليومية")

        # شرط الشراء: السعر وصل قاع الشمعة اليومية وظهرت شمعة شراء/ارتداد عند الذيل السفلي
        elif current_price <= daily_low or l15[-1] <= daily_low:
            if c15[-1] > o15[-1]:  # شمعة صاعدة/شراء
                sweep = "BULLISH_REJECTION_AT_DAILY_LOW"
                if trend_weekly == "LONG" or trend_weekly == "NEUTRAL":
                    direction = "LONG"
                    score += 30
                    confirmations.append("تم رصد كنس للسيولة وشمعة شراء صاعدة عند قاع الشمعة اليومية")
        else:
            excluded.append("السعر لم يصل بعد لقمة أو قاع الشمعة اليومية لاختبارها")

        score = int(max(0, min(100, round(score))))
        entry_valid = (direction in ("LONG", "SHORT") and score >= 75)

        if not entry_valid:
            excluded.append("شروط شمعة الرفض أو الشراء عند أطراف الشمعة اليومية لم تكتمل بعد")

        details = {
            "trend_weekly": trend_weekly,
            "daily_high": daily_high,
            "daily_low": daily_low,
            "sweep": sweep,
            "retest_advice": "راقب شمعة الرفض أو الشراء على فريم 15M عند أطراف الشمعة اليومية",
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

        # الهدف الأول (TP1) هو 50% من نطاق الشمعة أو المسافة، والهدف الثاني (TP2) هو الـ 50% الباقية
        if direction in ("LONG", "BUY"):
            stop = daily_low if daily_low > 0 else entry * 0.98
            total_range = abs(entry - stop)
            tp1 = entry + (total_range * 0.5)  # 50% من الهدف
            tp2 = entry + total_range          # الـ 50% الثانية (الهدف الثاني الكامل)
            tp3 = tp2                          # دمج الهدف الثالث مع الثاني بناءً على استراتيجية النصفين

        elif direction in ("SHORT", "SELL"):
            stop = daily_high if daily_high > 0 else entry * 1.02
            total_range = abs(stop - entry)
            tp1 = entry - (total_range * 0.5)  # 50% من الهدف
            tp2 = entry - total_range          # الـ 50% الثانية
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
