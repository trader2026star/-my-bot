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

    # 1. فحص الصعود خلال 24 ساعة ضمن نطاق آمن ومتزن
    change_24h = 0.0
    if len(df_1h) >= 24:
        price_now = df_1h['close'].iloc[-1]
        price_24h_ago = df_1h['close'].iloc[-24]
        change_24h = ((price_now - price_24h_ago) / price_24h_ago) * 100

    # استبعاد العملات الضعيفة أو العملات المجنونة فوق 35% لتجنب الانهيارات المفاجئة
    if change_24h <= 2.0 or change_24h > 35.0:
        return {"signal": None, "reason": "24h change out of safe bounds"}

    close = df_15m['close'].iloc[-1]
    
    # المؤشرات الفنية الأساسية
    sma_20 = df_15m['close'].rolling(window=20).mean().iloc[-1]
    sma_50 = df_15m['close'].rolling(window=50).mean().iloc[-1]
    
    rsi_series = calculate_rsi(df_15m['close'])
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

    # فحص الفوليوم والسيولة الحقيقية
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    current_volume = df_15m['volume'].iloc[-1]
    v_ratio = (current_volume / avg_volume) if avg_volume > 0 and not pd.isna(avg_volume) else 1.0

    # حساب نطاق التقلب الحقيقي (ATR)
    high_low = df_15m['high'] - df_15m['low']
    atr = high_low.rolling(window=14).mean().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = close * 0.01

    # تقييم العوامل الفنية
    m_score = int(min(max((current_rsi / 100) * 80 + 30, 50), 98))
    v_score = int(min(max(v_ratio * 45 + 30, 50), 98))
    
    t_score = 70
    if close > sma_20 and sma_20 > sma_50:
        t_score = 92
    elif close > sma_20:
        t_score = 82
    else:
        return {"signal": None, "reason": "Trend is not strictly bullish"}

    overall_rating = round((m_score * 0.4) + (v_score * 0.3) + (t_score * 0.3), 1)
    confidence = round((overall_rating + t_score) / 2, 1)

    # رفع معيار قبول الصفقات لتكون نقية وموثوقة بنسبة أعلى
    if overall_rating < 75.0:
        return {"signal": None, "reason": f"Rating {overall_rating} below strict 75% threshold"}

    strength = "صفقة قوية جداً 🚀" if overall_rating >= 85 else "صفقة قوية 📈"

    # نقطة الدخول الذكية للارتداد
    current_market_price = close
    entry_price = current_market_price - (atr * 0.4)
    
    # [درع الحماية]: توسيع وقف الخسارة لمعامل 2.2 ATR لمنع الضرب السريع
    stop_loss = entry_price - (atr * 2.2)
    risk = entry_price - stop_loss
    
    tp1 = entry_price + (risk * 1.5)
    tp2 = entry_price + (risk * 2.6)
    tp3 = entry_price + (risk * 4.0)

    risk_reward = "1:2.0"

    return {
        "signal": "LONG",
        "strength": strength,
        "change_24h": round(change_24h, 2),
        "rating": overall_rating,
        "confidence": confidence,
        "current_price": round(current_market_price, 5),
        "entry": round(entry_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_reward": risk_reward,
        "timeframe": "1-2 ساعة",
        "m_factor": m_score,
        "v_factor": v_score,
        "t_factor": t_score,
        "reason": "Passed Strict Safe-Guard Criteria"
    }
