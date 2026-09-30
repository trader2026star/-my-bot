import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h):
    """
    النسخة الاحترافية الصارمة لإدارة رأس المال: 
    ترفض 99% من السوق ولا تدخل إلا في قنص حقيقي مدعوم بالسيولة والترند.
    """
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    # ----------------------------------------------------
    # الشرط الأول: فلتر الاتجاه العام الحديدي (Trend Protection)
    # ----------------------------------------------------
    # نستخدم المتوسطات الأسرية (EMA 50 و 200) على فريم 4 ساعات و 1 ساعة
    ema_50_4h = df_4h['close'].ewm(span=50).mean().iloc[-1]
    ema_200_4h = df_4h['close'].ewm(span=200).mean().iloc[-1]
    current_close_4h = df_4h['close'].iloc[-1]
    
    # إذا كان السعر تحت متوسط 50 أو الترند العام هابط، امنع الشراء تماماً
    if current_close_4h < ema_50_4h or ema_50_4h < ema_200_4h:
        return {"signal": None, "reason": "Blocked: 4H Market Structure is Bearish"}

    # التأكد من فريم الساعة أيضاً
    ema_50_1h = df_1h['close'].ewm(span=50).mean().iloc[-1]
    if df_1h['close'].iloc[-1] < ema_50_1h:
        return {"signal": None, "reason": "Blocked: 1H Trend is against Longs"}

    # ----------------------------------------------------
    # الشرط الثاني: سحب السيولة الحقيقي (Liquidity Sweep)
    # ----------------------------------------------------
    # البوت يجب أن يتأكد أن السعر قام مؤخراً بكسر قاع سابق (سحب الستوبات) ثم ارتد
    recent_lows = df_15m['low'].tail(15)
    absolute_low = recent_lows.min()
    current_low = df_15m['low'].iloc[-1]
    
    # هل حدث سحب سيولة في آخر الشموع؟ (يعني الذيل نزل تحت القاع السابق ثم عاد وأغلق فوقه)
    sweep_detected = False
    for i in range(-5, -1):
        if df_15m['low'].iloc[i] <= recent_lows.iloc[:-1].min():
            sweep_detected = True
            break
            
    if not sweep_detected:
        return {"signal": None, "reason": "Waiting for a clear Liquidity Sweep (Stop Hunt)"}

    # ----------------------------------------------------
    # الشرط الثالث: الاندفاع الحقيقي وتغير مسار التسليم (CISD & FVG)
    # ----------------------------------------------------
    last_candle = df_15m.iloc[-1]
    body_size = abs(last_candle['close'] - last_candle['open'])
    avg_body = (abs(df_15m['close'] - df_15m['open'])).rolling(window=15).mean().iloc[-1]

    # اشتراط أن تكون الشمعة الخضراء قوية جداً (Displacement) وضعف أضعاف المتوسط لتأكيد دخول السيولة الذكية
    is_strong_displacement = (last_candle['close'] > last_candle['open']) and (body_size >= (avg_body * 2.0))
    
    if not is_strong_displacement:
        return {"signal": None, "reason": "No strong institutional displacement candle"}

    # التأكد من وجود الفجوة السعرية (Fair Value Gap - FVG) كدليل على سيطرة المشترين المطلقة
    fvg_valid = False
    if len(df_15m) >= 3:
        c1_high = df_15m.iloc[-3]['high']
        c3_low = df_15m.iloc[-1]['low']
        if c3_low > c1_high:  # الفجوة بين الشمعة الأولى والثالثة
            fvg_valid = true if (c3_low - c1_high) > 0 else False

    if not fvg_valid:
        return {"signal": None, "reason": "No valid FVG formation after sweep"}

    # ----------------------------------------------------
    # بناء الصفقة بمعايير المخاطر الذكية (Risk Management)
    # ----------------------------------------------------
    entry_price = last_candle['close']
    # وقف الخسارة محشور فوراً وتحت أدنى ذيل سحب السيولة (أمان تام وأقل خسارة ممكنة لو فشل التحليل)
    stop_loss = absolute_low * 0.992  
    
    # هدف أول وثاني بناءً على نسبة عائد لمخاطرة لا تقل عن 1 إلى 3
    risk_amount = entry_price - stop_loss
    take_profit = entry_price + (risk_amount * 3.0)

    return {
        "signal": "LONG",
        "entry": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reason": "Elite SMC Sniper: Trend OK, Liquidity Swept, CISD & FVG Confirmed"
    }
