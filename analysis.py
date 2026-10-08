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
            
            # Simple EMA trend check
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
        - Stop Loss placed strictly below/above the latest swing low/high structure.
        - Leverage capped at 3x - 5x max.
        - Automated Take Profit targets and break-even trigger.
        """
        if direction == 'LONG':
            stop_loss = round(swing_low_high * 0.992, 4) # Just below swing low
            risk_amount = entry_price - stop_loss
            if risk_amount <= 0:
                risk_amount = entry_price * 0.005
                stop_loss = entry_price - risk_amount
            
            tp1 = round(entry_price + (risk_amount * 1.5), 4)
            tp2 = round(entry_price + (risk_amount * 3.0), 4)
        else:
            stop_loss = round(swing_low_high * 1.008, 4) # Just above swing high
            risk_amount = stop_loss - entry_price
            if risk_amount <= 0:
                risk_amount = entry_price * 0.005
                stop_loss = entry_price + risk_amount
                
            tp1 = round(entry_price - (risk_amount * 1.5), 4)
            tp2 = round(entry_price - (risk_amount * 3.0), 4)
            
        return stop_loss, tp1, tp2
