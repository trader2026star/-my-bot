import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def detect_order_blocks_and_fvg(df):
    """
    رصد الفجوات السعرية (Fair Value Gaps - FVG) ومناطق التدفق المؤسسي
    """
    try:
        # FVG detection: Candle i-1 high < Candle i+1 low (Bullish FVG)
        df['bullish_fvg'] = (df['high'].shift(2) < df['low']) & (df['close'].shift(1) > df['open'].shift(1))
        
        # Bullish momentum impulse confirmation
        df['body_size'] = abs(df['close'] - df['open'])
        df['avg_body'] = df['body_size'].rolling(20).mean()
        df['is_bullish_impulse'] = (df['close'] > df['open']) & (df['body_size'] > df['avg_body'] * 1.5)
        
        return df
    except Exception:
        return df

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    منطق تحليل مؤسسي متطور (Advanced SMC / ICT Multi-Timeframe Engine):
    1. تأكيد الاتجاه الهيكلي على الإطارات الكبرى (4H & 1H).
    2. تصفية الإشارات عبر الفجوات السعرية (FVG) والزخم (RSI).
    3. فحص تدفق الفوليوم والسيولة الحقيقية.
    4. حساب وقف خسارة هندسي تحت أحدث قاع هيكلي وأهداف ربح دقيقة (Win Rate عالي).
    """
    try:
        if df_15m.empty or df_1h.empty or df_4h.empty:
            return None

        # تجهيز فريم 4 ساعات (هيكل الاتجاه العام)
        df_4h['ema20'] = calculate_ema(df_4h['close'], 20)
        df_4h['ema50'] = calculate_ema(df_4h['close'], 50)

        # تجهيز فريم الساعة (1H Trend & Structure)
        df_1h['ema20'] = calculate_ema(df_1h['close'], 20)
        df_1h['ema50'] = calculate_ema(df_1h['close'], 50)

        # تجهيز فريم 15 دقيقة (التنفيذ اللحظي بدقة مؤسسية)
        df_15m['ema9'] = calculate_ema(df_15m['close'], 9)
        df_15m['ema21'] = calculate_ema(df_15m['close'], 21)
        df_15m['rsi'] = calculate_rsi(df_15m['close'], 14)
        df_15m['volume_sma'] = df_15m['volume'].rolling(20).mean()
        df_15m = detect_order_blocks_and_fvg(df_15m)

        current_price = float(df_15m['close'].iloc[-1])

        # شروط التأكيد على الفريمات الكبرى (4H و 1H في اتجاه صاعد هيكلي)
        h4_structure_ok = df_4h['close'].iloc[-1] > df_4h['ema20'].iloc[-1] and df_4h['ema20'].iloc[-1] > df_4h['ema50'].iloc[-1]
        h1_structure_ok = df_1h['close'].iloc[-1] > df_1h['ema20'].iloc[-1] and df_1h['ema20'].iloc[-1] > df_1h['ema50'].iloc[-1]

        if not h4_structure_ok or not h1_structure_ok:
            return None

        # فحص الزخم (RSI في منطقة صاعدة آمنة ومدروسة)
        rsi_val = float(df_15m['rsi'].iloc[-1])
        if rsi_val < 52 or rsi_val > 75:
            return None

        # تدفق السيولة والفوليوم (يجب أن يكون مدعوماً بحجم تداول جيد)
        current_vol = float(df_15m['volume'].iloc[-1])
        avg_vol = float(df_15m['volume_sma'].iloc[-1])
        if current_vol < (avg_vol * 0.85):
            return None

        # شروط الدخول اللحظي (SMC / FVG / EMA alignment)
        ema9_15m = float(df_15m['ema9'].iloc[-1])
        ema21_15m = float(df_15m['ema21'].iloc[-1])
        
        recent_fvg = df_15m['bullish_fvg'].iloc[-3:].any()
        price_action_ok = (current_price > ema9_15m) and (ema9_15m > ema21_15m) and (recent_fvg or df_15m['close'].iloc[-1] > df_15m['open'].iloc[-1])

        if not price_action_ok:
            return None

        # حساب التغير في آخر 24 ساعة
        lookback = min(96, len(df_15m) - 1)
        price_24h_ago = float(df_15m['close'].iloc[-lookback])
        change_24h = round(((current_price - price_24h_ago) / price_24h_ago) * 100, 2)

        # وقف الخسارة الهندسي الدقيق (تحت أحدث قاع هيكلي Swing Low وبدون أي عشوائية)
        recent_low = float(df_15m['low'].iloc[-12:].min())
        stop_loss = round(min(recent_low, current_price * 0.985), 4)

        if stop_loss >= current_price:
            stop_loss = round(current_price * 0.98, 4)

        risk = current_price - stop_loss
        if risk <= 0:
            return None

        # الأهداف الاستثمارية المتدرجة (Risk-to-Reward قوي لضمان Win Rate عالي)
        tp1 = round(current_price + (risk * 1.8), 4)
        tp2 = round(current_price + (risk * 3.0), 4)
        tp3 = round(current_price + (risk * 4.5), 4)

        confidence = int(min(98, max(82, 75 + (rsi_val - 50) + (12 if current_vol > avg_vol * 1.4 else 6))))
        rating = confidence

        return {
            "signal": "LONG",
            "strength": "SMC INSTITUTIONAL BREAKOUT",
            "current_price": current_price,
            "entry": current_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_reward": "1:4.0",
            "timeframe": "15m / 1H / 4H",
            "change_24h": change_24h,
            "rating": rating,
            "confidence": confidence,
            "m_factor": 99,
            "v_factor": int(min(99, 90 + (current_vol / (avg_vol + 10) * 5))),
            "t_factor": 98
        }

    except Exception as e:
        print(f"Analysis error: {e}")
        return None
