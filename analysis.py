import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h, df_btc=None):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    confirmations = []

    # ==========================================
    ساعدة 1: هيكل الأسعار على الـ 4 ساعات (4H Market Structure)
    # ==========================================
    df_4h['sma_20'] = df_4h['close'].rolling(window=20).mean()
    # حساب القمم والقيعان البسيطة على الـ 4 ساعات لتحديد الاتجاه (HH/HL vs LH/LL)
    highs_4h = df_4h['high'].rolling(window=5).max()
    lows_4h = df_4h['low'].rolling(window=5).min()
    
    is_4h_bullish = (df_4h['close'].iloc[-1] > df_4h['sma_20'].iloc[-1]) and (df_4h['close'].iloc[-1] > lows_4h.iloc[-2])
    is_4h_bearish = (df_4h['close'].iloc[-1] < df_4h['sma_20'].iloc[-1]) and (df_4h['close'].iloc[-1] < highs_4h.iloc[-2])
    
    if is_4h_bearish:
        return {"signal": None, "reason": "4H Market structure is clearly bearish"}
    
    if is_4h_bullish:
        confirmations.append("4H BULLISH STRUCTURE")
    else:
        confirmations.append("4H NEUTRAL STRUCTURE")

    # ==========================================
    # ثانياً: هيكل الساعة (1H Structure Confirmation & BOS)
    # ==========================================
    # تحديد آخر Swing High و Swing Low على الإطار الزمني 1 ساعة
    df_1h['swing_high'] = df_1h['high'].rolling(window=5).max()
    df_1h['swing_low'] = df_1h['low'].rolling(window=5).min()
    
    prev_1h_high = df_1h['swing_high'].iloc[-2]
    current_1h_close = df_1h['close'].iloc[-1]
    
    # كسر حقيقي لقمة سابقة (BOS)
    is_1h_bos = current_1h_close > prev_1h_high
    if is_1h_bos:
        confirmations.append("1H BOS (Break of Structure)")

    # ==========================================
    # ثالثاً: 15M First Ignition & Compression
    # ==========================================
    current_volume = df_15m['volume'].iloc[-1]
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    
    if avg_volume == 0 or current_volume < avg_volume * 1.35:
        return {"signal": None, "reason": "Volume expansion not met"}
    
    confirmations.append("VOLUME EXPANSION")

    current_close = df_15m['close'].iloc[-1]
    current_open = df_15m['open'].iloc[-1]
    current_high = df_15m['high'].iloc[-1]
    current_low = df_15m['low'].iloc[-1]

    body_size = current_close - current_open
    total_range = current_high - current_low

    if total_range == 0 or body_size <= 0:
        return {"signal": None, "reason": "Candle is not bullish"}

    # الإغلاق قريب من الهايت، وعدم وجود ذيل علوي ضخم
    upper_wick = current_high - max(current_close, current_open)
    if upper_wick > body_size * 0.8:
        return {"signal": None, "reason": "Large upper wick rejection"}

    if (body_size / total_range) < 0.45:
        return {"signal": None, "reason": "Candle body lacks strength"}

    confirmations.append("15M FIRST IGNITION")

    # التحقق من عدم وجود عدة شموع صاعدة متتالية قبل شمعة الانفجار (تجنب المطاردة)
    consecutive_green = 0
    for i in range(2, 6):
        if df_15m['close'].iloc[-i] > df_15m['open'].iloc[-i]:
            consecutive_green += 1
        else:
            break

    if consecutive_green >= 3:
        return {"signal": None, "reason": "Too many prior consecutive green candles (Late entry)"}

    # البحث عن تجميع أو ضغط (Compression) في الشموع السابقة (شموع ذات مدى ضيق)
    prev_ranges = [df_15m['high'].iloc[-i] - df_15m['low'].iloc[-i] for i in range(2, 5)]
    avg_prev_range = np.mean(prev_ranges)
    has_compression = avg_prev_range < (total_range * 0.8)
    if has_compression:
        confirmations.append("COMPRESSION BEFORE BREAKOUT")

    # ==========================================
    # رابعاً: رصد السيولة والسحب (Liquidity & Sweep)
    # ==========================================
    recent_lows = df_15m['low'].iloc[-6:-1]
    lowest_recent = recent_lows.min()
    has_liquidity_sweep = current_low < lowest_recent and current_close > lowest_recent
    if has_liquidity_sweep:
        confirmations.append("LIQUIDITY SWEEP")

    # ==========================================
    # خامساً: فحص موقع المقاومة القريبة (Resistance Location)
    # ==========================================
    recent_resistance = df_15m['high'].rolling(window=15).max().iloc[-2]
    distance_to_resistance_pct = ((recent_resistance - current_close) / current_close) * 100
    
    if 0 < distance_to_resistance_pct < 0.8:
        return {"signal": None, "reason": "Too close to immediate resistance"}
    
    confirmations.append("GOOD RISK/REWARD")

    # ==========================================
    * سادساً: التحقق الذكي لتغير 24 ساعة (24H Change Logic)
    # ==========================================
    change_24h = ((current_close - df_1h['close'].iloc[-24]) / df_1h['close'].iloc[-24]) * 100
    
    if change_24h > 15.0:
        return {"signal": None, "reason": "24h change is overly extended (>15%)"}
    
    if change_24h > 3.5 and not has_compression:
        return {"signal": None, "reason": "24h gain is high without proper accumulation structure"}

    # ==========================================
    # سابعاً: دعم اتجاه البيتكوين (BTC Confirmation)
    # ==========================================
    btc_supportive = True
    if df_btc is not None and not df_btc.empty:
        btc_sma = df_btc['close'].rolling(window=20).mean().iloc[-1]
        btc_current = df_btc['close'].iloc[-1]
        if btc_current < btc_sma * 0.985:
            btc_supportive = False
            if not (has_liquidity_sweep and is_1h_bos):
                return {"signal": None, "reason": "BTC trend is strongly bearish"}
        if btc_supportive:
            confirmations.append("BTC SUPPORTIVE")

    # ==========================================
    # ثامناً وتاسعاً: حساب السكور الديناميكي والثقة (Dynamic Score & Confidence)
    # ==========================================
    score = 0
    if is_4h_bullish: score += 15
    elif not is_4h_bearish: score += 10
    
    if is_1h_bos: score += 20
    score += 15 # للـ Ignition الحالي
    score += 15 # لتمدد الفوليوم
    if has_liquidity_sweep: score += 10
    if has_compression: score += 10
    score += 5  # موقع المقاومة المناسب
    if btc_supportive: score += 5
    score += 5  # جودة المخاطر

    if score < 70:
        return {"signal": None, "reason": f"Score too low for execution ({score})"}

    if score >= 90:
        quality_label = "ELITE"
    elif score >= 80:
        quality_label = "HIGH"
    else:
        quality_label = "VALID"

    confidence = min(round(float(score), 1), 99.0)

    # ==========================================
    # عاشرًا: حساب وقف الخسارة الذكي (Smart Stop Loss with ATR Buffer)
    # ==========================================
    recent_swing_low = df_15m['low'].iloc[-6:].min()
    if has_liquidity_sweep:
        stop_loss = current_low - ((current_high - current_low) * 0.2)
    else:
        # حساب ATR تقريبي بسيط (متوسط المدى للشموع الأخيرة)
        ranges = df_15m['high'] - df_15m['low']
        atr_approx = ranges.rolling(window=14).mean().iloc[-1] if len(ranges) >= 14 else (current_high - current_low)
        stop_loss = recent_swing_low - (atr_approx * 0.5)

    entry_price = current_close
    if entry_price <= stop_loss:
        stop_loss = entry_price * 0.985

    risk = entry_price - stop_loss

    # ==========================================
    # حادي عشر: الأهداف الربحية ونسبة العائد للمخاطرة (TP & Risk/Reward)
    # ==========================================
    tp1 = entry_price + (risk * 1.5)
    tp2 = entry_price + (risk * 3.0)
    tp3 = entry_price + (risk * 4.5)

    # ==========================================
    # رابع عشر: تجميع الأسباب والكونفلوشنز للتقرير
    # ==========================================
    strength_desc = f"Structure + Volume Confirmation ({quality_label}) 🚀"

    return {
        "signal": "LONG",
        "strength": strength_desc,
        "confluences": confirmations,
        "change_24h": round(change_24h, 2),
        "rating": float(score),
        "confidence": confidence,
        "current_price": round(current_close, 5),
        "entry": round(entry_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_reward": "1:4.5",
        "timeframe": "1-3 ساعات",
        "m_factor": int(score),
        "v_factor": int(score),
        "t_factor": int(score),
        "reason": " / ".join(confirmations) if confirmations else "Early Ignition Breakout Setup"
    }
