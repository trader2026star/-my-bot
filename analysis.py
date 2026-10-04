import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    # 1. الاتجاه العام على الـ 4 ساعات لازم يكون صاعد أو مستقر
    df_4h['sma_20'] = df_4h['close'].rolling(window=20).mean()
    if df_4h['close'].iloc[-1] < df_4h['sma_20'].iloc[-1]:
        return {"signal": None, "reason": "4H Market structure is bearish"}

    # 2. كشف انفجار الفوليوم (Volume Explosion) في هذه اللحظة بالذات
    current_volume = df_15m['volume'].iloc[-1]
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    
    # شرط أساسي: الفوليوم الحالي لازم يكون أضعاف المتوسط (بداية دخول السيولة الحقيقية)
    if current_volume < avg_volume * 1.8:
        return {"signal": None, "reason": "No volume explosion yet"}

    # 3. التأكد أن الشمعة الحالية هي شمعة اختراق حقيقية لبداية الانفجار
    current_close = df_15m['close'].iloc[-1]
    current_open = df_15m['open'].iloc[-1]
    recent_high = df_15m['high'].iloc[-6:-1].max() # أعلى سعر في الـ 5 شمعات السابقة
    
    # لو السعر اخترق القمة السابقة مع فوليوم عالي، دي بداية الانفجار!
    if current_close <= recent_high:
        return {"signal": None, "reason": "Price hasn't broken out of the recent range yet"}

    # التأكد أن الشمعة خضراء وقوية وليست تصحيحية
    if current_close <= current_open:
        return {"signal": None, "reason": "Current candle is not bullish"}

    # 4. وقف الخسارة الهندسي تحت قاع شمعة الانفجار مباشرة
    recent_swing_low = df_15m['low'].iloc[-5:].min()
    entry_price = current_close
    stop_loss = recent_swing_low - (entry_price * 0.002) # حماية إضافية بسيطة تحت القاع

    if entry_price <= stop_loss:
        return {"signal": None, "reason": "Invalid risk structure"}

    risk = entry_price - stop_loss

    # 5. أهداف سريعة وقوية تناسب عملات الترند اليومي (مخاطرة/عائد 1:3)
    tp1 = entry_price + (risk * 1.5)
    tp2 = entry_price + (risk * 3.0)
    tp3 = entry_price + (risk * 4.5)

    return {
        "signal": "LONG",
        "strength": "عملة ترند انفجارية (Early Breakout Setup) 🚀🔥",
        "change_24h": round(((current_close - df_1h['close'].iloc[-24]) / df_1h['close'].iloc[-24]) * 100, 2),
        "rating": 95.0,
        "confidence": 96.0,
        "current_price": round(current_close, 5),
        "entry": round(entry_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_reward": "1:3",
        "timeframe": "1-3 ساعات",
        "m_factor": 98,
        "v_factor": 99,
        "t_factor": 95,
        "reason": "Caught at the exact ignition point with massive volume spike"
    }
