import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية اختراق الزخم وحجم التداول (Momentum Breakout & Volume Surge)
    1. فحص الاتجاه الصاعد على فريم الساعة (1H).
    2. رصد اختراق السعر لأعلى قمة في آخر 20 شمعة على فريم 15 دقيقة مدعوماً بفوليوم تداول عالي جداً.
    3. تحديد وقف خسارة صارم تحت شمعة الاختراق وأهداف ربح واسعة.
    """
    try:
        if df_15m is None or df_1h is None or df_4h is None:
            return None
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # 1. التأكد من الاتجاه العام على فريم 1H (السعر فوق EMA 20)
        df_1h['ema20'] = calculate_ema(df_1h['close'], 20)
        if df_1h['close'].iloc[-1] <= df_1h['ema20'].iloc[-1]:
            return None

        # 2. فريم 15 دقيقة: رصد اختراق القمة السابقة مع فوليوم قوي
        # حساب أعلى سعر في آخر 20 شمعة (باستثناء الشمعة الحالية)
        recent_high = df_15m['high'].iloc[-21:-1].max()
        current_close = float(df_15m['close'].iloc[-1])
        current_high = float(df_15m['high'].iloc[-1])
        current_open = float(df_15m['open'].iloc[-1])
        
        # متوسط الفوليوم لآخر 20 شمعة
        volume_sma = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = float(df_15m['volume'].iloc[-1])

        # شرط الاختراق: السعر اخترق أعلى قمة سابقة + الشمعة قوية خضراء + الفوليوم أعلى من المتوسط بضعف ونصف على الأقل
        is_breakout = (current_close > recent_high) and (current_close > current_open) and (current_volume > volume_sma * 1.5)

        if not is_breakout:
            return None

        # التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_close - price_24h_ago) / price_24h_ago) * 100, 2)

        # 3. وقف الخسارة: عند أدنى سعر لشمعة الاختراق أو أدنى قاع قريب
        stop_loss = round(float(df_15m['low'].iloc[-1]), 4)
        if stop_loss >= current_close:
            stop_loss = round(current_close * 0.98, 4)

        risk = current_close - stop_loss
        if risk <= 0:
            return None

        # الأهداف الاستثمارية (نسبة مخاطرة لعائد 1:3.5)
        tp1 = round(current_close + (risk * 2.0), 4)
        tp2 = round(current_close + (risk * 3.5), 4)
        tp3 = round(current_close + (risk * 5.0), 4)

        return {
            "signal": "LONG",
            "strength": "MOMENTUM VOLUME BREAKOUT",
            "current_price": current_close,
            "entry": current_close,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.5",
            "timeframe": "15m / 1H",
            "change_24h": change_24h,
            "rating": 92,
            "confidence": 92,
            "m_factor": 96,
            "v_factor": 95,
            "t_factor": 91
        }

    except Exception as e:
        print(f"Breakout Strategy Error: {e}")
        return None
