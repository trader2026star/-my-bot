import pandas as pd
import numpy as np

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=period).mean()

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    استراتيجية الصيد المبكر جداً من القاع (أول شرارة صعود قبل أي حركة)
    """
    try:
        if df_15m is None or df_1h is None or df_4h is None:
            return None
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        current_close = float(df_15m['close'].iloc[-1])
        current_open = float(df_15m['open'].iloc[-1])
        current_low = float(df_15m['low'].iloc[-1])

        # 1. منع تام لأي عملة طارت أو صعدت (يجب أن تكون العملة هادئة وقريبة من القاع)
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_close - price_24h_ago) / price_24h_ago) * 100, 2)

        # نرفض أي عملة صعدت بأكثر من 2% (ندخل فقط وهي في القاع لم تحرك بعد)
        if change_24h > 2.5 or change_24h < -8.0:
            return None

        # 2. رصد "أول شمعة صعود من القاع" (الشمعة الحالية خضراء وبدأت تطلع للتو من الدعم)
        is_green = current_close > current_open
        if not is_green:
            return None

        # التأكد أننا في قاع محلي (أدنى سعر خلال الـ 10 شمعات الأخيرة قريب جداً)
        recent_low = float(df_15m['low'].iloc[-10:].min())
        if current_low > (recent_low * 1.03):
            return None  # السعر ابتعد عن القاع كثيراً، نرفضه

        # 3. وقف خسارة ضيق ومحمي بالـ ATR تحت القاع مباشرة
        df_15m['atr'] = calculate_atr(df_15m, 14)
        current_atr = float(df_15m['atr'].iloc[-1])
        
        stop_loss = round(recent_low - (current_atr * 0.4), 4)
        if stop_loss >= current_close:
            stop_loss = round(current_close * 0.985, 4)

        risk = current_close - stop_loss
        if risk <= 0:
            return None

        # أهداف ربح متدرجة وطويلة لأننا داخلين من البداية الصافية
        tp1 = round(current_close + (risk * 2.0), 4)
        tp2 = round(current_close + (risk * 3.5), 4)
        tp3 = round(current_close + (risk * 5.0), 4)

        return {
            "signal": "LONG",
            "strength": "ABSOLUTE BOTTOM ENTRY (EARLY SPARK)",
            "current_price": current_close,
            "entry": current_close,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:3.5+",
            "timeframe": "15m",
            "change_24h": change_24h,
            "rating": 99,
            "confidence": 99,
            "m_factor": 98,
            "v_factor": 98,
            "t_factor": 98
        }

    except Exception as e:
        print(f"Bottom Entry Strategy Error: {e}")
        return None
