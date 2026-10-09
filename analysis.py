# ==========================================
# TREND FOLLOWING STRATEGY BASED ON MARKET STRUCTURE (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# Inspired by Smart Money & Trend Trading Rules
# ==========================================

import pandas as pd
import numpy as np

class StrategyEngine:
    def __init__(self, df=None):
        self.df = df # يستقبل بيانات الشمعات التاريخية (OHLCV) من المنصة

    def analyze_market_trend(self, closes):
        """
        التحقق من الاتجاه بناءً على حركة السعر (قمم وقيعان)
        """
        if len(closes) < 10:
            return "SIDEWAYS"
        
        # مقارنة النصف الأخير بالنصف الأول لمعرفة الاتجاه العام
        recent_trend = closes[-1] - closes[0]
        if recent_trend > 0:
            return "LONG" # اتجاه صاعد -> شراء فقط
        else:
            return "SHORT" # اتجاه هابط -> بيع فقط

    def calculate_risk_management(self, entry_price, direction, swing_level):
        """
        حساب وقف الخسارة والأهداف بناءً على الهيكل الحقيقي للسوق والاتجاه
        """
        direction = direction.upper()
        
        if direction == 'LONG':
            # وقف الخسارة تحت قاع السيولة الحقيقي أو مسافة أمان تحميه
            stop_loss = swing_level if (swing_level and swing_level < entry_price) else entry_price * (0.985)
            risk_distance = entry_price - stop_loss
            
            # أهداف صاعدة متدرجة ونظيفة
            tp1 = entry_price + (risk_distance * 1.5)
            tp2 = entry_price + (risk_distance * 2.5)
            tp3 = entry_price + (risk_distance * 4.0)
            
        elif direction == 'SHORT':
            # وقف الخسارة فوق قمة السيولة الحقيقية أو مسافة أمان تحميه
            stop_loss = swing_level if (swing_level and swing_level > entry_price) else entry_price * (1.015)
            risk_distance = stop_loss - entry_price
            
            # أهداف هابطة متدرجة ونظيفة
            tp1 = entry_price - (risk_distance * 1.5)
            tp2 = entry_price - (risk_distance * 2.5)
            tp3 = entry_price - (risk_distance * 4.0)
        else:
            raise ValueError("Invalid direction: must be LONG or SHORT")

        return round(stop_loss, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4)
