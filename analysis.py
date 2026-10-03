import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h, df_1d=None):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    # ==========================================
    # 1. فلتر اتجاه اليوم (Daily Market Bias Filter)
    # ==========================================
    current_close_4h = df_4h['close'].iloc[-1]
    
    if df_1d is not None and not df_1d.empty:
        daily_open = df_1d['open'].iloc[-1]
    else:
        daily_open = df_4h['open'].iloc[-6] if len(df_4h) >= 6 else df_4h['open'].iloc[0]

    is_day_bullish = current_close_4h >= daily_open
    day_bias = "BULLISH 🟢" if is_day_bullish else "BEARISH 🔴"

    ema_50_4h = df_4h['close'].ewm(span=50).mean().iloc[-1]
    ema_200_4h = df_4h['close'].ewm(span=200).mean().iloc[-1]
    ema_50_1h = df_1h['close'].ewm(span=50).mean().iloc[-1]

    # ==========================================
    # 2. فحص صفقات الشراء (LONG CONDITIONS)
    # ==========================================
    long_market_approved = (
        is_day_bullish and 
        (current_close_4h > ema_50_4h) and 
        (ema_50_4h >= ema_200_4h)
    )

    if long_market_approved:
        if df_1h['close'].iloc[-1] >= ema_50_1h:
            recent_lows = df_15m['low'].tail(15)
            absolute_low = recent_lows.min()
            
            sweep_detected = False
            for i in range(-5, -1):
                if df_15m['low'].iloc[i] <= recent_lows.iloc[:-1].min():
                    sweep_detected = True
                    break
                    
            if sweep_detected:
                last_candle = df_15m.iloc[-1]
                body_size = abs(last_candle['close'] - last_candle['open'])
                avg_body = (abs(df_15m['close'] - df_15m['open'])).rolling(window=15).mean().iloc[-1]
                
                is_strong_displacement = (last_candle['close'] > last_candle['open']) and (body_size >= (avg_body * 1.3))
                
                # تخفيف فلتر الفوليوم إلى 1.1 بدل 1.3 لضمان التقاط الفرص
                avg_volume = df_15m['volume'].rolling(window=15).mean().iloc[-1]
                has_good_volume = last_candle['volume'] >= (avg_volume * 1.1)

                if is_strong_displacement and has_good_volume:
                    fvg_valid = False
                    if len(df_15m) >= 3:
                        c1_high = df_15m.iloc[-3]['high']
                        c3_low = df_15m.iloc[-1]['low']
                        if c3_low > c1_high:
                            fvg_valid = True

                    if fvg_valid:
                        entry_price = last_candle['close']
                        stop_loss = absolute_low * 0.992  
                        risk_amount = entry_price - stop_loss
                        take_profit = entry_price + (risk_amount * 3.0)

                        return {
                            "signal": "LONG",
                            "entry": entry_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "reason": f"SMC Long Sniper + Volume | Bias: {day_bias}"
                        }

    # ==========================================
    # 3. فحص صفقات البيع (SHORT CONDITIONS)
    # ==========================================
    short_market_approved = (
        not is_day_bullish and 
        (current_close_4h < ema_50_4h) and 
        (ema_50_4h <= ema_200_4h)
    )

    if short_market_approved:
        if df_1h['close'].iloc[-1] <= ema_50_1h:
            recent_highs = df_15m['high'].tail(15)
            absolute_high = recent_highs.max()
            
            sweep_detected_shorts = False
            for i in range(-5, -1):
                if df_15m['high'].iloc[i] >= recent_highs.iloc[:-1].max():
                    sweep_detected_shorts = True
                    break
                    
            if sweep_detected_shorts:
                last_candle = df_15m.iloc[-1]
                body_size = abs(last_candle['close'] - last_candle['open'])
                avg_body = (abs(df_15m['close'] - df_15m['open'])).rolling(window=15).mean().iloc[-1]
                
                is_strong_displacement_down = (last_candle['close'] < last_candle['open']) and (body_size >= (avg_body * 1.3))
                
                avg_volume = df_15m['volume'].rolling(window=15).mean().iloc[-1]
                has_good_volume = last_candle['volume'] >= (avg_volume * 1.1)

                if is_strong_displacement_down and has_good_volume:
                    fvg_valid_shorts = False
                    if len(df_15m) >= 3:
                        c1_low = df_15m.iloc[-3]['low']
                        c3_high = df_15m.iloc[-1]['high']
                        if c3_high < c1_low: 
                            fvg_valid_shorts = True

                    if fvg_valid_shorts:
                        entry_price = last_candle['close']
                        stop_loss = absolute_high * 1.008  
                        risk_amount = stop_loss - entry_price
                        take_profit = entry_price - (risk_amount * 3.0)

                        return {
                            "signal": "SHORT",
                            "entry": entry_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "reason": f"SMC Short Sniper + Volume | Bias: {day_bias}"
                        }

    return {"signal": None, "reason": f"No Setup / Filter Unmet | Bias: {day_bias}"}
