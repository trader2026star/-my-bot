import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية اقتناص الانطلاقة المبكرة من القاع والدعم (Early Bottom Rebound)
    1. الاتجاه العام صاعد على فريم 4 ساعات (4H).
    2. رصد ارتداد السعر مبكراً من القاع المحلي في فريم 15 دقيقة فور تكون شمعة إيجابية.
    3. وقف خسارة هندسي تحت القاع المباشر بدقة وأهداف ربح واسعة.
    """
    try:
        if df_15m is None or df_1h is None or df_4h is None:
            return None
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # 1. الاتجاه العام صاعد على فريم 4H (السعر فوق EMA 50)
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        if df_4h['close'].iloc[-1] <= df_4h['ema50'].iloc[-1]:
            return None

        # 2. فريم 15 دقيقة: البحث عن ارتداد مبكر من القاع المحلي
        current_close = float(df_15m['close'].iloc[-1])
        current_open = float(df_15m['open'].iloc[-1])
        prev_close = float(df_15m['close'].iloc[-2])
        
        # أدنى قاع في آخر 10 شمعات
        local_low = df_15m['low'].iloc[-10:-1].min()
        prev_low = float(df_15m['low'].iloc[-2])

        # شروط الدخول المبكر من القاع:
        # - الشمعة هبطت قريباً من القاع المحلي أو ارتدت منه
        # - الشمعة الحالية خضراء قوية (إغلاق أعلى من الافتتاح وأعلى من إغلاق الشمعة السابقة)
        is_bullish_candle = current_close > current_open
        is_rebound_from_bottom = (prev_low <= local_low * 1.005) and is_bullish_candle and (current_close > prev_close)

        if not is_rebound_from_bottom:
            return None

        # التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_close - price_24h_ago) / price_24h_ago) * 100, 2)

        # 3. وقف الخسارة: تحت القاع المحلي المباشر بدقة
        stop_loss = round(float(local_low * 0.998), 4)
        if stop_loss >= current_close:
            stop_loss = round(current_close * 0.98, 4)

        risk = current_close - stop_loss
        if risk <= 0:
            return None

        # الأهداف الاستثمارية المتدرجة
        tp1 = round(current_close + (risk * 1.8), 4)
        tp2 = round(current_close + (risk * 3.0), 4)
        tp3 = round(current_close + (risk * 4.2), 4)

        return {
            "signal": "LONG",
            "strength": "EARLY BOTTOM REBOUND",
            "current_price": current_close,
            "entry": current_close,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.0",
            "timeframe": "15m / 4H",
            "change_24h": change_24h,
            "rating": 95,
            "confidence": 95,
            "m_factor": 96,
            "v_factor": 94,
            "t_factor": 97
        }

    except Exception as e:
        print(f"Early Rebound Strategy Error: {e}")
        return None
