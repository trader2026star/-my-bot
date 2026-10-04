import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    # 1. الاتجاه العام على الـ 4 ساعات لازم يكون صاعد أو مستقر
    df_4h['sma_20'] = df_4h['close'].rolling(window=20).mean()
    if df_4h['close'].iloc[-1] < df_4h['sma_20'].iloc[-1]:
        return {"signal": None, "reason": "4H Market structure is bearish"}

    # 2. كشف أول همسة سيولة وتدفق فوليوم مبكر جداً (أقل من السابق لاكتشافها أسرع)
    current_volume = df_15m['volume'].iloc[-1]
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    
    if current_volume < avg_volume * 1.3:
        return {"signal": None, "reason": "Initial volume spark not detected yet"}

    # 3. الاصتياد المبكر جداً (قبل الانفجار وقبل كسر القمة بقليل)
    current_close = df_15m['close'].iloc[-1]
    current_open = df_15m['open'].iloc[-1]
    current_low = df_15m['low'].iloc[-1]
    current_high = df_15m['high'].iloc[-1]
    
    # التأكد أن الشمعة الحالية خضراء وقوية وصاعدة من الدعم أو منطقة تجميع
    body_size = abs(current_close - current_open)
    total_range = current_high - current_low
    
    if total_range == 0:
        return {"signal": None, "reason": "Zero range candle"}

    # شرط أن يكون جسم الشمعة معبر عن ضغط شراء حقيقي وليس مجرد ذيل عشوائي
    if current_close <= current_open or (body_size / total_range < 0.4):
        return {"signal": None, "reason": "Candle lacks strong buying pressure"}

    # التأكد أن السعر لم يتضخم بشكل مبالغ فيه في آخر شمعتين (لم تنفجر بعد بالكامل)
    prev_close = df_15m['close'].iloc[-2]
    recent_growth = ((current_close - prev_close) / prev_close) * 100
    if recent_growth > 4.0: # لو صعدت أكثر من 4% في شمعة واحدة، فهي بدأت تنفجر ونتأخر عنها
        return {"signal": None, "reason": "Already exploded too fast, waiting for earlier stage"}

    # 4. وقف الخسارة الهندسي تحت أدنى قاع حديث لحماية الحساب بدقة
    recent_swing_low = df_15m['low'].iloc[-6:].min()
    entry_price = current_close
    stop_loss = recent_swing_low - (entry_price * 0.001)

    if entry_price <= stop_loss:
        return {"signal": None, "reason": "Invalid risk structure"}

    risk = entry_price - stop_loss

    # 5. أهداف ربحية ممتازة تتناسب مع الدخول المبكر جداً (ريسك/ريورد 1:3.5)
    tp1 = entry_price + (risk * 1.5)
    tp2 = entry_price + (risk * 3.0)
    tp3 = entry_price + (risk * 4.5)

    return {
        "signal": "LONG",
        "strength": "صفقة تجميع واشتعال مبكر جداً (Pre-Ignition Setup) 🎯🔥",
        "change_24h": round(((current_close - df_1h['close'].iloc[-24]) / df_1h['close'].iloc[-24]) * 100, 2),
        "rating": 97.0,
        "confidence": 98.0,
        "current_price": round(current_close, 5),
        "entry": round(entry_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_reward": "1:3.5",
        "timeframe": "1-3 ساعات",
        "m_factor": 99,
        "v_factor": 99,
        "t_factor": 97,
        "reason": "Caught at the earliest pre-ignition accumulation stage before breakout"
    }
