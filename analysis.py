import pandas as pd
import numpy as np


# ============================================================
# EXPERT LONG BREAKOUT ENGINE
# Multi-Timeframe + Liquidity + BOS + Volume + ATR + RSI
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
    """
    إضافة المؤشرات بدون الاعتماد على مكتبات خارجية.
    """

    df = df.copy()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # --------------------------------------------------------
    # Moving averages
    # --------------------------------------------------------
    df["sma20"] = close.rolling(20).mean()
    df["sma50"] = close.rolling(50).mean()

    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    df["atr"] = true_range.rolling(14).mean()

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------
    df["volume_ma20"] = volume.rolling(20).mean()
    df["volume_ma50"] = volume.rolling(50).mean()

    df["volume_ratio"] = (
        volume / df["volume_ma20"].replace(0, np.nan)
    )

    # --------------------------------------------------------
    # Candle structure
    # --------------------------------------------------------
    df["body"] = (close - df["open"]).abs()

    df["range"] = (high - low).replace(0, np.nan)

    df["body_ratio"] = df["body"] / df["range"]

    df["upper_wick"] = high - np.maximum(close, df["open"])

    df["lower_wick"] = (
        np.minimum(close, df["open"]) - low
    )

    df["upper_wick_ratio"] = (
        df["upper_wick"] / df["range"]
    )

    df["lower_wick_ratio"] = (
        df["lower_wick"] / df["range"]
    )

    # --------------------------------------------------------
    # Candle direction
    # --------------------------------------------------------
    df["bullish_candle"] = close > df["open"]

    df["bearish_candle"] = close < df["open"]

    # --------------------------------------------------------
    # Rolling highs / lows
    # --------------------------------------------------------
    df["swing_high_5"] = high.shift(1).rolling(5).max()
    df["swing_low_5"] = low.shift(1).rolling(5).min()

    df["swing_high_10"] = high.shift(1).rolling(10).max()
    df["swing_low_10"] = low.shift(1).rolling(10).min()

    df["swing_high_20"] = high.shift(1).rolling(20).max()
    df["swing_low_20"] = low.shift(1).rolling(20).min()

    return df


def _trend_state(df):
    """
    تحديد الاتجاه من هيكل السعر + EMA.
    """

    if df.empty or len(df) < 50:
        return "UNKNOWN"

    last = df.iloc[-1]

    close = _safe_float(last["close"])
    ema21 = _safe_float(last["ema21"])
    ema50 = _safe_float(last["ema50"])

    if not np.isfinite(close):
        return "UNKNOWN"

    bullish_structure = (
        df["high"].iloc[-1] > df["high"].iloc[-5]
        and
        df["low"].iloc[-1] > df["low"].iloc[-5]
    )

    bearish_structure = (
        df["high"].iloc[-1] < df["high"].iloc[-5]
        and
        df["low"].iloc[-1] < df["low"].iloc[-5]
    )

    if (
        np.isfinite(ema21)
        and np.isfinite(ema50)
        and close > ema21 > ema50
        and bullish_structure
    ):
        return "BULLISH"

    if (
        np.isfinite(ema21)
        and np.isfinite(ema50)
        and close < ema21 < ema50
        and bearish_structure
    ):
        return "BEARISH"

    if np.isfinite(ema21) and close > ema21:
        return "BULLISH"

    if np.isfinite(ema21) and close < ema21:
        return "BEARISH"

    return "NEUTRAL"


def _detect_liquidity_sweep(df):
    """
    يبحث عن:
    1) Sweep لقاع سابق ثم إغلاق أعلى منه.
    2) رفض واضح للسيولة أسفل القاع.
    """

    if len(df) < 25:
        return False, "NONE"

    last = df.iloc[-1]

    low = _safe_float(last["low"])
    close = _safe_float(last["close"])
    lower_wick = _safe_float(last["lower_wick"])
    atr = _safe_float(last["atr"])

    previous_low = _safe_float(
        df["low"].iloc[-15:-2].min()
    )

    if not all(
        np.isfinite(x)
        for x in [low, close, lower_wick, atr, previous_low]
    ):
        return False, "NONE"

    # كسر القاع ثم الرجوع فوقه
    swept = low < previous_low and close > previous_low

    strong_rejection = lower_wick >= atr * 0.25

    if swept and strong_rejection:
        return True, "BULLISH_LIQUIDITY_SWEEP"

    return False, "NONE"


def _detect_bos(df):
    """
    Break Of Structure:
    إغلاق واضح فوق قمة سابقة.
    """

    if len(df) < 25:
        return False

    last = df.iloc[-1]

    close = _safe_float(last["close"])
    previous_high = _safe_float(
        df["high"].iloc[-15:-2].max()
    )
    atr = _safe_float(last["atr"])

    if not all(
        np.isfinite(x)
        for x in [close, previous_high, atr]
    ):
        return False

    minimum_break = max(
        atr * 0.10,
        close * 0.001
    )

    return close > previous_high + minimum_break


def _detect_breakout(df):
    """
    Breakout حقيقي وليس مجرد wick.
    """

    if len(df) < 25:
        return False, 0.0

    last = df.iloc[-1]

    close = _safe_float(last["close"])
    high = _safe_float(last["high"])
    atr = _safe_float(last["atr"])
    body_ratio = _safe_float(last["body_ratio"])

    resistance = _safe_float(
        df["high"].iloc[-15:-2].max()
    )

    if not all(
        np.isfinite(x)
        for x in [
            close,
            high,
            atr,
            body_ratio,
            resistance
        ]
    ):
        return False, 0.0

    breakout_distance = close - resistance

    # السعر يجب أن يكون فوق المقاومة فعليًا
    real_breakout = breakout_distance > max(
        atr * 0.08,
        close * 0.0008
    )

    # جسم الشمعة لازم يكون محترم
    healthy_body = body_ratio >= 0.45

    # عدم وجود رفض علوي ضخم
    upper_wick_ratio = _safe_float(
        last["upper_wick_ratio"]
    )

    not_heavy_rejection = (
        np.isfinite(upper_wick_ratio)
        and upper_wick_ratio < 0.45
    )

    if (
        real_breakout
        and healthy_body
        and not_heavy_rejection
    ):
        return True, breakout_distance

    return False, breakout_distance


def _detect_fvg(df):
    """
    Bullish Fair Value Gap بسيط.
    """

    if len(df) < 5:
        return False, None, None

    c1 = df.iloc[-3]
    c3 = df.iloc[-1]

    high_1 = _safe_float(c1["high"])
    low_3 = _safe_float(c3["low"])

    if not np.isfinite(high_1) or not np.isfinite(low_3):
        return False, None, None

    if low_3 > high_1:
        return True, high_1, low_3

    return False, None, None


def _detect_order_block(df):
    """
    Order Block مبسط:
    آخر شمعة هابطة قبل displacement صاعد.
    """

    if len(df) < 8:
        return False, None, None

    last = df.iloc[-1]

    current_close = _safe_float(last["close"])
    current_atr = _safe_float(last["atr"])

    if not np.isfinite(current_close) or not np.isfinite(current_atr):
        return False, None, None

    for i in range(len(df) - 3, max(-1, len(df) - 8), -1):

        candle = df.iloc[i]

        candle_open = _safe_float(candle["open"])
        candle_close = _safe_float(candle["close"])
        candle_high = _safe_float(candle["high"])
        candle_low = _safe_float(candle["low"])

        if not all(
            np.isfinite(x)
            for x in [
                candle_open,
                candle_close,
                candle_high,
                candle_low
            ]
        ):
            continue

        bearish = candle_close < candle_open

        displacement = (
            current_close - candle_high
        ) > current_atr * 0.5

        if bearish and displacement:

            return (
                True,
                candle_low,
                candle_high
            )

    return False, None, None


def _volume_quality(df):
    """
    Volume ليس مجرد >= 1.8.
    نحاول التفريق بين:
    - volume ضعيف
    - volume صحي
    - volume انفجاري جدًا
    """

    if len(df) < 25:
        return "WEAK", 0.0

    last = df.iloc[-1]

    ratio = _safe_float(last["volume_ratio"])

    if not np.isfinite(ratio):
        return "WEAK", 0.0

    if ratio < 1.20:
        return "WEAK", ratio

    if ratio < 1.50:
        return "NORMAL", ratio

    if ratio <= 3.50:
        return "STRONG", ratio

    if ratio <= 6.0:
        return "EXTREME", ratio

    return "ABNORMAL", ratio


def _momentum_quality(df):
    if len(df) < 25:
        return False, 50.0

    last = df.iloc[-1]

    rsi = _safe_float(last["rsi"])
    close = _safe_float(last["close"])
    ema9 = _safe_float(last["ema9"])
    ema21 = _safe_float(last["ema21"])

    if not all(
        np.isfinite(x)
        for x in [rsi, close, ema9, ema21]
    ):
        return False, 50.0

    bullish = (
        close > ema9
        and
        ema9 > ema21
        and
        52 <= rsi <= 72
    )

    return bullish, rsi


def _distance_from_ema(df):
    last = df.iloc[-1]

    close = _safe_float(last["close"])
    ema21 = _safe_float(last["ema21"])
    atr = _safe_float(last["atr"])

    if not all(
        np.isfinite(x)
        for x in [close, ema21, atr]
    ):
        return np.inf

    if atr <= 0:
        return np.inf

    return abs(close - ema21) / atr


def _calculate_stop_loss(df, entry):
    """
    Dynamic SL:
    نعتمد على:
    - آخر swing low
    - ATR
    ونأخذ الأكثر منطقية.
    """

    last = df.iloc[-1]

    atr = _safe_float(last["atr"])

    swing_low = _safe_float(
        df["low"].iloc[-10:-1].min()
    )

    current_low = _safe_float(last["low"])

    if not np.isfinite(atr):
        return None

    candidates = []

    if np.isfinite(swing_low):
        candidates.append(
            swing_low - atr * 0.25
        )

    if np.isfinite(current_low):
        candidates.append(
            current_low - atr * 0.75
        )

    if not candidates:
        return None

    # نختار الوقف الذي يحمي من wick لكن لا يكون بعيدًا جدًا
    stop = min(candidates)

    if stop >= entry:
        stop = entry - atr * 1.2

    return stop


def _calculate_targets(entry, stop, resistance=None):
    risk = entry - stop

    if risk <= 0:
        return None, None, None

    tp1 = entry + risk * 1.5
    tp2 = entry + risk * 2.5
    tp3 = entry + risk * 4.0

    # لو توجد مقاومة قريبة، لا نجعل TP1 أقل منها بشكل أعمى
    if resistance is not None and np.isfinite(resistance):

        if resistance > entry:
            tp1 = max(
                tp1,
                resistance
            )

    return tp1, tp2, tp3


def analyze_market_conditions(
    df_15m,
    df_1h,
    df_4h,
    df_btc=None
):
    """
    ============================================================
    EXPERT LONG ANALYZER
    ============================================================

    الإخراج متوافق مع الكود القديم:
        signal
        strength
        change_24h
        rating
        confidence
        current_price
        entry
        stop_loss
        tp1
        tp2
        tp3
        risk_reward
        timeframe
        reason

    بالإضافة إلى معلومات التشخيص.
    """

    # =========================================================
    # 1. Prepare data
    # =========================================================

    df_15m = _prepare_df(df_15m)
    df_1h = _prepare_df(df_1h)
    df_4h = _prepare_df(df_4h)

    if df_btc is not None:
        df_btc = _prepare_df(df_btc)

    if (
        df_15m.empty
        or df_1h.empty
        or df_4h.empty
    ):
        return {
            "signal": None,
            "reason": "Insufficient market data"
        }

    if (
        len(df_15m) < 60
        or len(df_1h) < 60
        or len(df_4h) < 60
    ):
        return {
            "signal": None,
            "reason": "Not enough candles for reliable multi-timeframe analysis"
        }

    # =========================================================
    # 2. Indicators
    # =========================================================

    df_15m = _add_indicators(df_15m)
    df_1h = _add_indicators(df_1h)
    df_4h = _add_indicators(df_4h)

    if df_btc is not None and not df_btc.empty:
        if len(df_btc) >= 60:
            df_btc = _add_indicators(df_btc)

    # =========================================================
    # 3. Current price
    # =========================================================

    last15 = df_15m.iloc[-1]

    current_close = _safe_float(last15["close"])

    if not np.isfinite(current_close) or current_close <= 0:
        return {
            "signal": None,
            "reason": "Invalid current price"
        }

    # =========================================================
    # 4. Multi-Timeframe trend
    # =========================================================

    trend_4h = _trend_state(df_4h)
    trend_1h = _trend_state(df_1h)
    trend_15m = _trend_state(df_15m)

    # لا ندخل عكس 4H
    if trend_4h != "BULLISH":
        return {
            "signal": None,
            "reason": f"4H trend not bullish ({trend_4h})",
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m
        }

    # 1H يجب أن يكون bullish أو على الأقل neutral قوي
    if trend_1h == "BEARISH":
        return {
            "signal": None,
            "reason": "1H trend is bearish",
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m
        }

    # =========================================================
    # 5. Scoring engine
    # =========================================================

    score = 0
    confirmations = []
    warnings = []

    # 4H trend
    if trend_4h == "BULLISH":
        score += 18
        confirmations.append("4H_BULLISH")

    # 1H trend
    if trend_1h == "BULLISH":
        score += 14
        confirmations.append("1H_BULLISH")

    elif trend_1h == "NEUTRAL":
        score += 6
        confirmations.append("1H_NEUTRAL")

    # 15M trend
    if trend_15m == "
