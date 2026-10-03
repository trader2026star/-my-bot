import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze_market_conditions(df_15m, df_1h, df_4h):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    # 1. فحص الصعود خلال 24 ساعة (فريم 1 ساعة)
    change_24h = 0.0
    if len(df_1h) >= 24:
        price_now = df_1h['close'].iloc[-1]
        price_24h_ago = df_1h['close'].iloc[-24]
        change_24h = ((price_now - price_24h_ago) / price_24h_ago) * 100

    # شرط المعيار: صعود إيجابي في 24 ساعة
    if change_24h <= 1.5:
        return {"signal": None, "reason": "24h change too low"}

    close = df_15m['close'].iloc[-1]
    
    # أدوات التحليل الفني المتقدمة (متوسطات + RSI + ATR)
    sma_20 = df_15m['close'].rolling(window=20).mean().iloc[-1]
    sma_50 = df_15m['close'].rolling(window=50).mean().iloc[-1]
    
    rsi_series = calculate_rsi(df_15m['close'])
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

    # فحص الفوليوم (Volume Analysis)
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    current_volume = df_15m['volume'].iloc[-1]
    v_ratio = (current_volume / avg_volume) if avg_volume > 0 and not pd.isna(avg_volume) else 1.0

    # حساب الـ ATR لحساب الأهداف ووقف الخسارة بدقة
    high_low = df_15m['high'] - df_15m['low']
    atr = high_low.rolling(window=14).mean().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = close * 0.01

    # حساب مؤشرات العوامل (M, V, T) نفس نظام البوتات المدفوعة
    # M: الزخم (Momentum & RSI)
    m_score = int(min(max((current_rsi / 100) * 80 + 30, 50), 95))
    
    # V: فوليوم التداول (Volume Strength)
    v_score = int(min(max(v_ratio * 45 + 30, 50), 98))
    
    # T: قوة الاتجاه (Trend & Moving Averages)
    t_score = 70
    if close > sma_20 and sma_20 > sma_50:
        t_score = 90
    elif close > sma_20:
        t_score = 80
    elif close < sma_20:
        t_score = 55

    # التقييم الشامل (Rating & Confidence)
    overall_rating = round((m_score * 0.4) + (v_score * 0.3) + (t_score * 0.3), 1)
    confidence = round((overall_rating + t_score) / 2, 1)

    # معيار: تقييم شامل أعلى من 70%
    if overall_rating < 70.0:
        return {"signal": None, "reason": f"Rating {overall_rating} below 70% threshold"}

    strength = "صفقة قوية جداً 🚀" if overall_rating >= 80 else "صفقة قوية 📈"

    # حساب مستويات الأسعار ودقة الأهداف بناءً على أداة الـ ATR والتقلب
    entry_price = close
    stop_loss = entry_price - (atr * 1.5)
    risk = entry_price - stop_loss
    
    # الأهداف الثلاثة بنسب متدرجة واحترافية
    tp1 = entry_price + (risk * 1.6)
    tp2 = entry_price + (risk * 2.8)
    tp3 = entry_price + (risk * 4.2)

    risk_reward = f"1:{(round(risk * 3 / risk, 1) if risk > 0 else 1.8)}"

    return {
        "signal": "LONG",
        "strength": strength,
        "change_24h": round(change_24h, 2),
        "rating": overall_rating,
        "confidence": confidence,
        "entry": round(entry_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_reward": "1:2.4",
        "timeframe": "1-2 ساعة",
        "m_factor": m_score,
        "v_factor": v_score,
        "t_factor": t_score,
        "reason": "Passed Advanced Multi-Tool Criteria"
    }
