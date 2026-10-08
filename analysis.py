# ==========================================
# TRADING STRATEGY & ANALYSIS MODULE (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import pandas as pd
import numpy as np

class StrategyEngine:
    def __init__(self, df_1h, df_4h):
        self.df_1h = df_1h
        self.df_4h = df_4h

    def check_market_trend(self):
        """
        Multi-timeframe trend alignment:
        Ensures 4H and 1H trends are synchronized to prevent counter-trend traps.
        """
        try:
            if self.df_1h is None or self.df_4h is None or self.df_1h.empty or self.df_4h.empty:
                return 'NEUTRAL'
            
            ema50_4h = self.df_4h['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            close_4h = self.df_4h['close'].iloc[-1]
            
            ema20_1h = self.df_1h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            close_1h = self.df_1h['close'].iloc[-1]

            if close_4h > ema50_4h and close_1h > ema20_1h:
                return 'LONG'
            elif close_4h < ema50_4h and close_1h < ema20_1h:
                return 'SHORT'
            
            return 'NEUTRAL'
        except Exception:
            return 'NEUTRAL'

    def calculate_risk_management(self, entry_price, direction, swing_low_high):
        """
        Strict Risk Controls:
        - Stop Loss placed strictly below swing low (for Long) or above swing high (for Short).
        - Multi-target Take Profits (TP1, TP2, TP3).
        """
        if direction == 'LONG':
            # وقف الخسارة تحت الـ Swing Low للونج
            stop_loss = round(swing_low_high * 0.992, 4)
            risk_amount = entry_price - stop_loss
            if risk_amount <= 0:
                risk_amount = entry_price * 0.005
                stop_loss = entry_price - risk_amount
            
            tp1 = round(entry_price + (risk_amount * 1.5), 4)
            tp2 = round(entry_price + (risk_amount * 3.0), 4)
            tp3 = round(entry_price + (risk_amount * 4.5), 4)
            
        elif direction == 'SHORT':
            # وقف الخسارة فوق الـ Swing High للشورت (زي setup الـ Wolf_Trader)
            stop_loss = round(swing_low_high * 1.008, 4)
            risk_amount = stop_loss - entry_price
            if risk_amount <= 0:
                risk_amount = entry_price * 0.005
                stop_loss = entry_price + risk_amount
                
            tp1 = round(entry_price - (risk_amount * 1.5), 4)
            tp2 = round(entry_price - (risk_amount * 3.0), 4)
            tp3 = round(entry_price - (risk_amount * 4.5), 4)
        else:
            stop_loss, tp1, tp2, tp3 = 0, 0, 0, 0
            
        return stop_loss, tp1, tp2, tp3
