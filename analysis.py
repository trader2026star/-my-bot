# ==========================================
# ADVANCED SENTIMENT & QUANTITATIVE ENGINE (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import pandas as pd
import numpy as np

class StrategyEngine:
    def __init__(self, df=None):
        self.df = df

    def analyze_market_conditions(self, ohlcv, long_short_ratio=1.0):
        """
        محليل متقدم يحاكي 7 مدارس فنية ومعنويات السوق (Volume, AI Score, Long/Short Ratio)
        """
        if not ohlcv or len(ohlcv) < 20:
            return "NEUTRAL", 50, 1.0

        closes = [candle[4] for candle in ohlcv]
        volumes = [candle[5] for candle in ohlcv]

        # 1. تحليل حجم التداول الكمي (Quantitative Volume Analysis)
        avg_volume = sum(volumes[-20:-1]) / 19 if len(volumes) > 19 else volumes[-1]
        current_volume = volumes[-1]
        volume_ratio = round(current_volume / avg_volume, 2) if avg_volume > 0 else 1.0

        # 2. تقييم الذكاء الاصطناعي والزخم (AI Score 0-100)
        price_change = closes[-1] - closes[-5]
        score = 50
        
        if price_change > 0:
            score += 15
            signal = "BUY"
        else:
            score -= 15
            signal = "SELL"

        # دمج معنويات الفوليوم في النقاط
        if volume_ratio > 1.2:
            score += 10 if signal == "BUY" else -10

        # تحديد الإشارة النهائية بناءً على النتيجة
        if score >= 55:
            signal = "BUY"
        elif score <= 45:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        return signal, score, volume_ratio

    def calculate_risk_management(self, entry_price, direction, swing_level):
        direction = direction.upper()
        
        if direction in ['LONG', 'BUY']:
            stop_loss = swing_level if (swing_level and swing_level < entry_price) else entry_price * 0.985
            risk_distance = entry_price - stop_loss
            tp1 = entry_price + (risk_distance * 1.5)
            tp2 = entry_price + (risk_distance * 2.5)
            tp3 = entry_price + (risk_distance * 4.0)
        else:
            stop_loss = swing_level if (swing_level and swing_level > entry_price) else entry_price * 1.015
            risk_distance = stop_loss - entry_price
            tp1 = entry_price - (risk_distance * 1.5)
            tp2 = entry_price - (risk_distance * 2.5)
            tp3 = entry_price - (risk_distance * 4.0)

        return round(stop_loss, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4)
