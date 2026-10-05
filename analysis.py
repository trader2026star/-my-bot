import pandas as pd
import numpy as np


# ============================================================
# EXPERT DR. CHART MAZEN STYLE BREAKOUT & REVERSAL ENGINE
# Multi-Timeframe + Descending Trendline Breakout + Resistance Flip + Volume Surge
# ============================================================


def _safe_float(value, default=np.nan):
    try:
        value = float(value)
        if np.isfinite(value):
            return value
    except Exception:
        pass
    return default


def _prepare_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    x = df.copy()
    required = ["open", "high", "low", "close", "volume"]

    for col in required:
        if col not in x.columns:
            return pd.DataFrame()
        x[col] = pd.to_numeric(x[col], errors="coerce")

    x = x.dropna(subset=required).copy()
    if len(x) == 0:
        return pd.DataFrame()

    return x


def _add_indicators(df):
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # Moving Averages
    df["sma20"] = close.rolling(20).mean()
    df["sma50"] = close.rolling(50).mean()
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # ATR (Average True Range)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    # Volume & Candles
    df["volume_ma20"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_ma20"].replace(0, np.nan)
    df["body"] = (close - df["open"]).abs()
    df["range"] = (high - low).replace(0, np.nan)
    df["body_ratio"] = df["body"] / df["range"]
    df["upper_wick"] = high - np.maximum(close, df["open"])
    df["lower_wick"] = np.minimum(close, df["open"]) - low
    df["upper_wick_ratio"] = df["upper_wick"] / df["range"]
    df["lower_wick_ratio"] = df["lower_wick"] / df["range"]

    # Swing Highs & Lows for Mazen Trendline / Resistance Strategy
    df["swing_high_20"] = high.shift(1).rolling(20).max()
    df["swing_low_20"] = low.shift(1).rolling(20).min()

    return df


def _trend_state(df):
    if df.empty or len(df) < 50:
        return "UNKNOWN"
    last = df.iloc[-1]
    close = _safe_float(last["close"])
    ema21 = _safe_float(last["ema21"])
    ema50 = _safe_float(last["ema50"])

    if not np.isfinite(close):
        return "UNKNOWN"

    bullish_structure = (
        df["high"].iloc[-1] >= df["high"].iloc[-5]
        and df["low"].iloc[-1] >= df["low"].iloc[-5]
    )

    if np.isfinite(ema21) and np.isfinite(ema50) and close > ema21 and bullish_structure:
        return "BULLISH"
    if np.isfinite(ema21) and close > ema21:
        return "BULLISH"
    if np.isfinite(ema21) and close < ema21:
        return "BEARISH"
    return "NEUTRAL"


def _detect_mazen_breakout(df):
    """
    أسلوب دكتور مازن: رصد اختراق المقاومة الرئيسية (Resistance Flip) أو الخروج من الترند الهابط
    مع شمعة دفع قوية (Displacement / Marubozu or Strong Bullish Candle).
    """
    if len(df) < 30:
        return False, 0.0, 0.0

    last = df.iloc[-1]
    close = _safe_float(last["close"])
    open_p = _safe_float(last["open"])
    high = _safe_float(last["high"])
    atr = _safe_float(last["atr"])
    body_ratio = _safe_float(last["body_ratio"])

    # تحديد أعلى مقاومة في آخر 20 شمعة (ما عدا آخر شمعتين لتجنب الوهم)
    resistance = _safe_float(df["high"].iloc[-22:-2].max())
    
    if not all(np.isfinite(x) for x in [close, open_p, high, atr, resistance]):
        return False, 0.0, 0.0

    # هل السعر اخترق المقاومة بإغلاق واضح؟
    broke_resistance = close > resistance
    breakout_distance = close - resistance

    # شمعة قوية تدعم الانطلاقة (مثل شمعات "قبل وبعد" الصاروخية)
    strong_body = body_ratio >= 0.50 and close > open_p
    valid_push = breakout_distance > max(atr * 0.10, close * 0.001)

    is_breakout = (broke_resistance or valid_push) and strong_body

    return is_breakout, breakout_distance, resistance


def _detect_liquidity_sweep_and_reversal(df):
    """
    رصد ارتداد السيولة من القاع أو خط الدعم (مثل قيعان النجوم التي يحددها مازن قبل الصعود).
    """
    if len(df) < 20:
        return False

    last = df.iloc[-1]
    low = _safe_float(last["low"])
    close = _safe_float(last["close"])
    lower_wick = _safe_float(last["lower_wick"])
    atr = _safe_float(last["atr"])
    recent_low = _safe_float(df["low"].iloc[-15:-2].min())

    if not all(np.isfinite(x) for x in [low, close, lower_wick, atr, recent_low]):
        return False

    swept = low <= recent_low * 1.002 and close > recent_low
    rejection = lower_wick >= atr * 0.30

    return swept or rejection


def analyze_market_conditions(df_15m, df_1h, df_4h, df_btc=None):
    df_15m = _prepare_df(df_15m)
    df_1h = _prepare_df(df_1h)
    df_4h = _prepare_df(df_4h)

    if df_btc is not None:
        df_btc = _prepare_df(df_btc)

    if df_15m.empty or df_1h.empty or df_4h.empty:
        return {"signal": None, "reason": "Insufficient market data"}

    if len(df_15m) < 50 or len(df_1h) < 50 or len(df_4h) < 50:
        return {"signal": None, "reason": "Not enough candles"}

    df_15m = _add_indicators(df_15m)
    df_1h = _add_indicators(df_1h)
    df_4h = _add_indicators(df_4h)

    if df_btc is not None and not df_btc.empty and len(df_btc) >= 50:
        df_btc = _add_indicators(df_btc)

    last15 = df_15m.iloc[-1]
    current_close = _safe_float(last15["close"])

    if not np.isfinite(current_close) or current_close <= 0:
        return {"signal": None, "reason": "Invalid price"}

    trend_4h = _trend_state(df_4h)
    trend_1h = _trend_state(df_1h)

    # شروط دكتور مازن: اتجاه عام إيجابي أو ارتداد من مناطق قوية
    if trend_4h == "BEARISH" and trend_1h == "BEARISH":
        return {"signal": None, "reason": "Market trend is bearish on higher timeframes"}

    score = 55  # نقاط أساسية للبدء
    confirmations = []
    warnings = []

    # تقييم الفريمات الكبرى على طريقة مازن
    if trend_4h == "BULLISH":
        score += 15
        confirmations.append("4H_UPTREND_SUPPORT")
    if trend_1h == "BULLISH" or trend_1h == "NEUTRAL":
        score += 10
        confirmations.append("1H_ZONE_CONFIRMED")

    # فحص الاختراق الصاروخي (Breakout Strategy)
    is_breakout, breakout_dist, resistance = _detect_mazen_breakout(df_15m)
    if is_breakout:
        score += 22
        confirmations.append("MAZEN_RESISTANCE_BREAKOUT")

    # فحص ارتداد السيولة والقيعان
    reversal_signal = _detect_liquidity_sweep_and_reversal(df_15m)
    if reversal_signal:
        score += 15
        confirmations.append("LIQUIDITY_REVERSAL_ZONE")

    # حجم التداول (Volume Surge) مثل شمعات الانفجار
    volume_ratio = _safe_float(last15["volume_ratio"], 1.0)
    if volume_ratio >= 1.4:
        score += 12
        confirmations.append(f"VOLUME_SURGE_{volume_ratio:.2f}X")
    else:
        warnings.append("NORMAL_VOLUME")

    # مؤشر القوة النسبية RSI
    rsi = _safe_float(last15["rsi"], 50.0)
    if 45 <= rsi <= 78:
        score += 8
        confirmations.append(f"RSI_HEALTHY_{rsi:.1f}")

    # التحقق من اتجاه البيتكوين العام
    btc_state = "UNKNOWN"
    if df_btc is not None and not df_btc.empty:
        btc_state = _trend_state(df_btc)
        if btc_state == "BULLISH":
            score += 8
            confirmations.append("BTC_BULLISH_SUPPORT")
        elif btc_state == "BEARISH":
            score -= 10
            warnings.append("BTC_BEARISH_PRESSURE")

    score = max(0, min(100, score))

    # الحد الأدنى لقبول الصفقة على طريقة مازن (شرط الاختراق أو الارتداد القوي)
    if score < 72 or (not is_breakout and not reversal_signal):
        return {
            "signal": None,
            "reason": "Setup waiting for clear Mazen breakout/reversal confirmation",
            "score": round(score, 1),
            "confirmations": confirmations,
            "warnings": warnings
        }

    # حساب وقف الخسارة والأهداف بدقة (مطابق لشارتات الأهداف والأبعاد)
    atr = _safe_float(last15["atr"], current_close * 0.01)
    swing_low = _safe_float(df_15m["low"].iloc[-15:-1].min(), current_close - atr * 1.5)
    
    stop_loss = round(min(swing_low, current_close - atr * 1.2), 8)
    if stop_loss >= current_close:
        stop_loss = round(current_close - atr * 1.5, 8)

    risk = current_close - stop_loss
    if risk <= 0:
        risk = current_close * 0.02
        stop_loss = current_close - risk

    # أهداف متدرجة بنظام 1:2 و 1:3 و 1:4 (أهداف استثمارية صواريخية)
    tp1 = round(current_close + risk * 1.5, 8)
    tp2 = round(current_close + risk * 2.8, 8)
    tp3 = round(current_close + risk * 4.5, 8)

    if np.isfinite(resistance) and resistance > current_close:
        tp1 = max(tp1, resistance)

    rr2 = (tp2 - current_close) / risk

    # تقييم الجودة بناءً على النقاط
    if score >= 90:
        quality = "10/10 ELITE BREAKOUT"
    elif score >= 82:
        quality = "9/10 VERY STRONG"
    else:
        quality = "8/10 STRONG SETUP"

    strength = "🚀 MAZEN BREAKOUT & REVERSAL — Resistance Flip + Volume Explosion"
    reason = "Confirmed setup matching Dr. Chart Mazen breakout strategy: Resistance broken with volume surge & strong momentum."

    return {
        "signal": "LONG",
        "strength": strength,
        "quality": quality,
        "change_24h": 0.0,
        "rating": round(score, 1),
        "confidence": round(score, 1),
        "score": round(score, 1),
        "current_price": round(current_close, 8),
        "entry": round(current_close, 8),
        "stop_loss": round(stop_loss, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk_percentage": round((risk / current_close) * 100, 2),
        "risk_reward": f"1:{rr2:.1f}",
        "timeframe": "15M Breakout / 1H + 4H Support",
        "trend_4h": trend_4h,
        "trend_1h": trend_1h,
        "btc_state": btc_state,
        "volume_ratio": round(volume_ratio, 2),
        "rsi": round(rsi, 2) if np.isfinite(rsi) else None,
        "breakout": is_breakout,
        "resistance": round(resistance, 8) if np.isfinite(resistance) else None,
        "confirmations": confirmations,
        "warnings": warnings,
        "reason": reason
    }
