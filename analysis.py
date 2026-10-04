import pandas as pd
import numpy as np

def analyze_market_conditions(df_15m, df_1h, df_4h, df_btc=None):
    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Dataframes are empty"}

    confirmations = []

    # ==========================================
    # 1. 4H Market Structure Check
    # ==========================================
    df_4h['sma_20'] = df_4h['close'].rolling(window=20).mean()
    highs_4h = df_4h['high'].rolling(window=5).max()
    lows_4h = df_4h['low'].rolling(window=5).min()
    
    is_4h_bullish = (df_4h['close'].iloc[-1] > df_4h['sma_20'].iloc[-1]) and (df_4h['close'].iloc[-1] > lows_4h.iloc[-2])
    is_4h_bearish = (df_4h['close'].iloc[-1] < df_4h['sma_20'].iloc[-1]) and (df_4h['close'].iloc[-1] < highs_4h.iloc[-2])
    
    if is_4h_bearish:
        return {"signal": None, "reason": "4H Market structure is clearly bearish"}
    
    if is_4h_bullish:
        confirmations.append("4H BULLISH STRUCTURE")

    # ==========================================
    # 2. True Pivot Swing & 1H BOS
    # ==========================================
    def find_pivots(df, left=3, right=3):
        highs = df['high'].values
        lows = df['low'].values
        pivot_highs = []
        pivot_lows = []
        for i in range(left, len(df) - right):
            if highs[i] == max(highs[i - left:i + right + 1]):
                pivot_highs.append((i, highs[i]))
            if lows[i] == min(lows[i - left:i + right + 1]):
                pivot_lows.append((i, lows[i]))
        return pivot_highs, pivot_lows

    p_highs_1h, p_lows_1h = find_pivots(df_1h, left=2, right=2)
    last_1h_swing_high = p_highs_1h[-1][1] if p_highs_1h else df_1h['high'].iloc[-10:-2].max()
    last_1h_swing_low = p_lows_1h[-1][1] if p_lows_1h else df_1h['low'].iloc[-10:-2].min()

    current_1h_close = df_1h['close'].iloc[-1]
    is_1h_bos = current_1h_close > last_1h_swing_high
    if is_1h_bos:
        confirmations.append("1H BOS (Break of Structure)")

    # ==========================================
    # 3. 15M First Ignition, Compression & Range Check
    # ==========================================
    current_volume = df_15m['volume'].iloc[-1]
    avg_volume = df_15m['volume'].rolling(window=20).mean().iloc[-1]
    
    if avg_volume == 0 or current_volume < avg_volume * 1.3:
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

    upper_wick = current_high - max(current_close, current_open)
    if upper_wick > body_size * 0.6:
        return {"signal": None, "reason": "Large upper wick rejection"}

    if (body_size / total_range) < 0.5:
        return {"signal": None, "reason": "Candle body lacks strength"}

    # مقارنة نطاق شمعة الانفجار بمتوسط نطاق آخر 15 شمعة لتجنب الانفجار المتأخر جداً
    ranges_15m = df_15m['high'] - df_15m['low']
    avg_range_15m = ranges_15m.iloc[-16:-1].mean()
    if total_range > avg_range_15m * 3.5:
        return {"signal": None, "reason": "Ignition candle is overextended (Late)"}

    confirmations.append("15M FIRST IGNITION")

    consecutive_green = 0
    for i in range(2, 6):
        if df_15m['close'].iloc[-i] > df_15m['open'].iloc[-i]:
            consecutive_green += 1
        else:
            break

    if consecutive_green >= 3:
        return {"signal": None, "reason": "Too many prior consecutive green candles"}

    # True Compression Check (انخفاض تدريجي في الـ volatility قبل الانفجار)
    past_ranges = [ranges_15m.iloc[-i] for i in range(2, 6)]
    has_compression = np.mean(past_ranges) < (total_range * 0.85) and (max(past_ranges) - min(past_ranges) < avg_range_15m * 0.5)
    if has_compression:
        confirmations.append("COMPRESSION BEFORE BREAKOUT")

    # ==========================================
    # 4. Liquidity & Sweep Check (True Pivots)
    # ==========================================
    p_highs_15m, p_lows_15m = find_pivots(df_15m, left=2, right=1)
    recent_swing_low_15m = p_lows_15m[-1][1] if p_lows_15m else df_15m['low'].iloc[-8:-2].min()
    
    has_liquidity_sweep = current_low < recent_swing_low_15m and current_close > recent_swing_low_15m
    if has_liquidity_sweep:
        confirmations.append("LIQUIDITY SWEEP")

    # ==========================================
    # 5 & 6. Resistance Location & Risk/Reward Check
    # ==========================================
    recent_resistance = p_highs_15m[-1][1] if p_highs_15m else df_15m['high'].iloc[-15:-2].max()
    distance_to_resistance_pct = ((recent_resistance - current_close) / current_close) * 100
    
    if 0 < distance_to_resistance_pct < 0.6:
        return {"signal": None, "reason": "Too close to immediate resistance"}
    
    confirmations.append("GOOD LOCATION & RR")

    # ==========================================
    # 7. 24H Change Logic
    # ==========================================
    change_24h = ((current_close - df_1h['close'].iloc[-24]) / df_1h['close'].iloc[-24]) * 100
    if change_24h > 15.0 or (change_24h > 3.5 and not has_compression):
        return {"signal": None, "reason": "24h change overly extended or lacks accumulation"}

    # ==========================================
    # 8. BTC Trend Confirmation
    # ==========================================
    btc_supportive = False
    btc_bearish = False
    if df_btc is not None and not df_btc.empty:
        btc_sma = df_btc['close'].rolling(window=20).mean().iloc[-1]
        btc_current = df_btc['close'].iloc[-1]
        if btc_current > btc_sma:
            btc_supportive = True
            confirmations.append("BTC SUPPORTIVE")
        elif btc_current < btc_sma * 0.98:
            btc_bearish = True
            if not has_liquidity_sweep:
                return {"signal": None, "reason": "BTC trend is strongly bearish"}

    # ==========================================
    # 9. Dynamic Conditional Score Generation
    # ==========================================
    score = 0
    if is_4h_bullish: score += 15
    if is_1h_bos: score += 20
    score += 15  # 15M Ignition
    score += 15  # Volume Expansion
    if has_liquidity_sweep: score += 10
    if has_compression: score += 10
    score += 5   # Good Location
    if btc_supportive: score += 5
    score += 5   # Risk Quality baseline

    if score < 70:
        return {"signal": None, "reason": f"Score too low for execution ({score})"}

    if score >= 90:
        quality_label = "ELITE"
    elif score >= 80:
        quality_label = "HIGH"
    else:
        quality_label = "VALID"

    # ==========================================
    # 10. Stop Loss, Adaptive ATR Buffer & Risk Percent Validation
    # ==========================================
    atr_14 = ranges_15m.rolling(window=14).mean().iloc[-1] if len(ranges_15m) >= 14 else total_range
    
    if has_liquidity_sweep:
        stop_loss = recent_swing_low_15m - (atr_14 * 0.4)
    else:
        stop_loss = recent_swing_low_15m - (atr_14 * 0.5)

    entry_price = current_close
    
    if entry_price <= stop_loss:
        return {"signal": None, "reason": "Invalid structural stop loss"}

    risk_percent = abs(entry_price - stop_loss) / entry_price * 100

    # رفض الـ SL إذا كان ضيقاً جداً (Wick stop-out) أو واسعاً جداً غير اقتصادي
    min_adaptive_risk = max(0.4, (atr_14 / entry_price) * 50)
    max_adaptive_risk = 5.5

    if risk_percent < min_adaptive_risk or risk_percent > max_adaptive_risk:
        return {"signal": None, "reason": f"Risk percent out of adaptive bounds ({risk_percent:.2f}%)"}

    # ==========================================
    # 11. TP Targets & R:R Check
    # ==========================================
    risk = entry_price - stop_loss
    tp1 = entry_price + (risk * 1.5)
    tp2 = entry_price + (risk * 3.0)
    tp3 = entry_price + (risk * 4.5)

    if tp1 >= recent_resistance and distance_to_resistance_pct < 1.0:
        return {"signal": None, "reason": "Resistance blocks TP1 target"}

    # ==========================================
    # Factor Calculations (M, V, T)
    # ==========================================
    m_factor = int((15 if is_4h_bullish else 5) + (20 if is_1h_bos else 0) + (15 if has_compression else 5))
    v_factor = int(15 + (10 if has_liquidity_sweep else 0) + (10 if current_volume > avg_volume * 1.6 else 5))
    t_factor = int((15 if is_4h_bullish else 10) + (10 if btc_supportive else 5) + 5)

    # ==========================================
    # Confidence Calculation (Algorithmic Multi-factor)
    # ==========================================
    conf_base = 50
    if is_4h_bullish: conf_base += 10
    if is_1h_bos: conf_base += 15
    if has_liquidity_sweep: conf_base += 10
    if has_compression: conf_base += 8
    if btc_supportive: conf_base += 6
    confidence = min(float(conf_base), 99.0)

    strength_desc = f"First Ignition Setup ({quality_label}) 🚀"

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
        "m_factor": min(m_factor, 100),
        "v_factor": min(v_factor, 100),
        "t_factor": min(t_factor, 100),
        "reason": " / ".join(confirmations) if confirmations else "Early Ignition Breakout Setup"
    }
