# ==========================================
# ADVANCED SMC & LIQUIDITY STRATEGY (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import pandas as pd
import numpy as np

class StrategyEngine:
    def __init__(self, df_1h=None, df_4h=None):
        self.df_1h = df_1h
        self.df_4h = df_4h

    def calculate_risk_management(self, entry_price, direction, swing_level):
        """
        حساب وقف الخسارة والأهداف بناءً على أحدث قاع/قمة للسيولة (Swing Level)
        مع التسكين الاحترافي للأهداف (Risk-to-Reward Ratio)
        """
        direction = direction.upper()
        
        if direction == 'LONG':
            # وقف الخسارة يجب أن يكون تحت قاع السيولة الأخير بدقة
            stop_loss = swing_level if swing_level < entry_price else entry_price * (1 - 0.015)
            risk_distance = entry_price - stop_loss
            
            # الأهداف بناءً على مضاعفات المخاطرة (1:1.5, 1:2.5, 1:4)
            tp1 = entry_price + (risk_distance * 1.5)
            tp2 = entry_price + (risk_distance * 2.5)
            tp3 = entry_price + (risk_distance * 4.0)
            
        elif direction == 'SHORT':
            # وقف الخسارة يجب أن يكون فوق قمة السيولة الأخيرة بدقة
            stop_loss = swing_level if swing_level > entry_price else entry_price * (1 + 0.015)
            risk_distance = stop_loss - entry_price
            
            # الأهداف للانخفاض
            tp1 = entry_price - (risk_distance * 1.5)
            tp2 = entry_price - (risk_distance * 2.5)
            tp3 = entry_price - (risk_distance * 4.0)
        else:
            raise ValueError("Invalid direction: must be LONG or SHORT")

        return round(stop_loss, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4)

    def detect_liquidity_sweep_signal(self, current_high, current_low, prev_swing_high, prev_swing_low):
        """
        كشف هل حصل ضرب سيولة (Liquidity Sweep) وصيد وقوف الخسارة أم لا
        """
        signal = "NEUTRAL"
        # إذا السعر كسر القمة المؤقتة ورجع اغلق تحتها (شورت انعكاسي قوي)
        if current_high > prev_swing_high:
            signal = "SHORT_SWEEP"
        # إذا السعر كسر القاع المؤقت ورجع اغلق فوقه (لونغ انعكاسي قوي)
        elif current_low < prev_swing_low:
            signal = "LONG_SWEEP"
            
        return signal
