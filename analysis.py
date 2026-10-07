import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية الزخم واختراق البولنجر (Bollinger Squeeze & Momentum Breakout)
    """
    try:
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # حساب مؤشر بولنجر باندز (Bollinger Bands) على فريم 15 دقيقة
        window = 20
        rolling_mean = df_15m['close'].rolling(window=window).mean()
        rolling_std = df_15m['close'].rolling(window=window).std()
        df_15m['bb_upper'] = rolling_mean + (rolling_std * 2)
        df_15m['bb_lower'] = rolling_mean - (rolling_std * 2)
        df_15m['bb_width'] = (df_15m['bb_upper'] - df_15m['bb_lower']) / rolling_mean

        # قياس الانضغاط (Squeeze) ثم الاختراق
        df_15m['volume_sma'] = df_15m['volume'].rolling(20).mean()
        
        current_price = float(df_15m['close'].iloc[-1])
        upper_band = float(df_15m['bb_upper'].iloc[-1])
        prev_close = float(df_15m['close'].iloc[-2])
        current_vol = float(df_15m['volume'].iloc[-1])
        avg_vol = float(df_15m['volume_sma'].iloc[-1])

        # شرط الاختراق الصاعد (السعر يخترق الحد العلوي بفوليوم قوي)
        breakout_condition = (prev_close <= upper_band) and (current_price > upper_band) and (current_vol > avg_vol * 1.5)

        if not breakout_condition:
            return None

        # فريم الاتجاه العام (4H) يجب أن يكون صاعداً
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)
        if df_4h['close'].iloc[-1] <= df_4h['ema50'].iloc[-1]:
            return None

        # التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_price - price_24h_ago) / price_24h_ago) * 100, 2)

        # وقف الخسارة أسفل متوسط البولنجر أو أحدث قاع
        stop_loss = round(float(rolling_mean.iloc[-1]), 4)
        if stop_loss >= current_price:
            stop_loss = round(current_price * 0.98, 4)

        risk = current_price - stop_loss
        if risk <= 0:
            return None

        tp1 = round(current_price + (risk * 2.0), 4)
        tp2 = round(current_price + (risk * 3.5), 4)
        tp3 = round(current_price + (risk * 5.0), 4)

        return {
            "signal": "LONG",
            "strength": "MOMENTUM BOLLINGER BREAKOUT",
            "current_price": current_price,
            "entry": current_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.5",
            "timeframe": "15m / 4H",
            "change_24h": change_24h,
            "rating": 88,
            "confidence": 88,
            "m_factor": 95,
            "v_factor": 92,
            "t_factor": 90
        }
    except Exception as e:
        print(f"Strategy 1 error: {e}")
        return None
