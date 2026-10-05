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

    real_breakout = breakout_distance > max(
        atr * 0.08,
        close * 0.0008
    )

    healthy_body = body_ratio >= 0.45

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
    تقييم حجم التداول.
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
    حساب وقف الخسارة بناءً على قاع سوينغ سابق و ATR دون وضعه فوق سعر الدخول.
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

    df_15m = _add_indicators(df_15m)
    df_1h = _add_indicators(df_1h)
    df_4h = _add_indicators(df_4h)

    if df_btc is not None and not df_btc.empty:
        if len(df_btc) >= 60:
            df_btc = _add_indicators(df_btc)

    last15 = df_15m.iloc[-1]

    current_close = _safe_float(last15["close"])

    if not np.isfinite(current_close) or current_close <= 0:
        return {
            "signal": None,
            "reason": "Invalid current price"
        }

    trend_4h = _trend_state(df_4h)
    trend_1h = _trend_state(df_1h)
    trend_15m = _trend_state(df_15m)

    if trend_4h != "BULLISH":
        return {
            "signal": None,
            "reason": f"4H trend not bullish ({trend_4h})",
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m
        }

    if trend_1h == "BEARISH":
        return {
            "signal": None,
            "reason": "1H trend is bearish",
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m
        }

    score = 0
    confirmations = []
    warnings = []

    if trend_4h == "BULLISH":
        score += 18
        confirmations.append("4H_BULLISH")

    if trend_1h == "BULLISH":
        score += 14
        confirmations.append("1H_BULLISH")

    elif trend_1h == "NEUTRAL":
        score += 6
        confirmations.append("1H_NEUTRAL")

    if trend_15m == "BULLISH":
        score += 10
        confirmations.append("15M_BULLISH")

    sweep, sweep_type = _detect_liquidity_sweep(
        df_15m
    )

    if sweep:
        score += 15
        confirmations.append("LIQUIDITY_SWEEP")

    bos = _detect_bos(df_15m)

    if bos:
        score += 15
        confirmations.append("BOS")

    breakout, breakout_distance = _detect_breakout(
        df_15m
    )

    if breakout:
        score += 12
        confirmations.append("REAL_BREAKOUT")
    else:
        warnings.append("NO_VALID_BREAKOUT")

    volume_quality, volume_ratio = _volume_quality(
        df_15m
    )

    if volume_quality == "STRONG":
        score += 12
        confirmations.append(
            f"VOLUME_STRONG_{volume_ratio:.2f}X"
        )

    elif volume_quality == "NORMAL":
        score += 5
        confirmations.append(
            f"VOLUME_NORMAL_{volume_ratio:.2f}X"
        )

    elif volume_quality == "EXTREME":
        score += 3
        warnings.append(
            f"EXTREME_VOLUME_{volume_ratio:.2f}X"
        )

    else:
        warnings.append("WEAK_VOLUME")

    momentum_ok, rsi = _momentum_quality(
        df_15m
    )

    if momentum_ok:
        score += 8
        confirmations.append(
            f"MOMENTUM_RSI_{rsi:.1f}"
        )

    elif np.isfinite(rsi) and rsi > 78:
        warnings.append(
            f"RSI_OVERHEATED_{rsi:.1f}"
        )

    fvg, fvg_low, fvg_high = _detect_fvg(
        df_15m
    )

    if fvg:
        score += 5
        confirmations.append("BULLISH_FVG")

    ob, ob_low, ob_high = _detect_order_block(
        df_15m
    )

    if ob:
        score += 5
        confirmations.append("BULLISH_ORDER_BLOCK")

    btc_state = "UNKNOWN"

    if (
        df_btc is not None
        and not df_btc.empty
        and len(df_btc) >= 60
    ):

        btc_state = _trend_state(df_btc)

        if btc_state == "BULLISH":
            score += 8
            confirmations.append("BTC_BULLISH")

        elif btc_state == "NEUTRAL":
            score += 3
            confirmations.append("BTC_NEUTRAL")

        elif btc_state == "BEARISH":
            score -= 12
            warnings.append("BTC_BEARISH")

    ema_distance = _distance_from_ema(
        df_15m
    )

    if ema_distance > 4.0:
        score -= 12
        warnings.append(
            f"PRICE_TOO_FAR_FROM_EMA_{ema_distance:.1f}ATR"
        )

    elif ema_distance > 3.0:
        score -= 6
        warnings.append(
            f"PRICE_EXTENDED_{ema_distance:.1f}ATR"
        )

    last_range = _safe_float(
        last15["range"]
    )

    atr = _safe_float(
        last15["atr"]
    )

    upper_wick_ratio = _safe_float(
        last15["upper_wick_ratio"]
    )

    body_ratio = _safe_float(
        last15["body_ratio"]
    )

    if (
        np.isfinite(last_range)
        and np.isfinite(atr)
        and atr > 0
        and last_range > atr * 3.5
    ):
        score -= 10
        warnings.append("EXHAUSTION_CANDLE")

    if (
        np.isfinite(upper_wick_ratio)
        and upper_wick_ratio > 0.50
    ):
        score -= 7
        warnings.append("HEAVY_UPPER_WICK")

    if (
        np.isfinite(body_ratio)
        and body_ratio < 0.35
    ):
        score -= 5
        warnings.append("WEAK_CANDLE_BODY")

    resistance = _safe_float(
        df_15m["high"].iloc[-15:-2].max()
    )

    stop_loss = _calculate_stop_loss(
        df_15m,
        current_close
    )

    if stop_loss is None:
        return {
            "signal": None,
            "reason": "Unable to calculate safe stop loss"
        }

    risk = current_close - stop_loss

    if risk <= 0:
        return {
            "signal": None,
            "reason": "Invalid risk calculation"
        }

    risk_percentage = (
        risk / current_close
    ) * 100

    if risk_percentage > 6.0:
        return {
            "signal": None,
            "reason": (
                f"Stop too wide ({risk_percentage:.2f}%)"
            ),
            "score": round(max(0, min(100, score)), 1)
        }

    if risk_percentage < 0.30:
        score -= 5
        warnings.append(
            "STOP_TOO_TIGHT"
        )

    tp1, tp2, tp3 = _calculate_targets(
        current_close,
        stop_loss,
        resistance
    )

    if tp1 is None:
        return {
            "signal": None,
            "reason": "Unable to calculate targets"
        }

    strong_structure = (
        bos
        or sweep
    )

    real_setup = (
        trend_4h == "BULLISH"
        and
        trend_1h != "BEARISH"
        and
        breakout
        and
        volume_quality in ["STRONG", "NORMAL"]
        and
        strong_structure
    )

    if not real_setup:
        missing = []

        if trend_4h != "BULLISH":
            missing.append("4H_TREND")

        if trend_1h == "BEARISH":
            missing.append("1H_TREND")

        if not breakout:
            missing.append("BREAKOUT")

        if volume_quality == "WEAK":
            missing.append("VOLUME")

        if not strong_structure:
            missing.append(
                "BOS_OR_LIQUIDITY_SWEEP"
            )

        return {
            "signal": None,
            "reason": (
                "Setup rejected: "
                + ", ".join(missing)
            ),
            "score": round(
                max(0, min(100, score)),
                1
            ),
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m,
            "volume_ratio": round(
                volume_ratio, 2
            ),
            "btc_state": btc_state,
            "confirmations": confirmations,
            "warnings": warnings
        }

    score = max(
        0,
        min(100, score)
    )

    if score >= 90:
        quality = "10/10 ELITE"

    elif score >= 82:
        quality = "9/10 VERY STRONG"

    elif score >= 74:
        quality = "8/10 STRONG"

    elif score >= 66:
        quality = "7/10 VALID"

    else:
        quality = "REJECT"

    if score >= 90:

        minimum_elite_confirmations = sum([
            trend_4h == "BULLISH",
            trend_1h == "BULLISH",
            trend_15m == "BULLISH",
            bos,
            sweep,
            breakout,
            volume_quality == "STRONG",
            momentum_ok,
            fvg,
            ob,
            btc_state == "BULLISH"
        ])

        if minimum_elite_confirmations < 7:
            score = min(score, 89)
            quality = "9/10 VERY STRONG"

    rr1 = (
        tp1 - current_close
    ) / risk

    rr2 = (
        tp2 - current_close
    ) / risk

    rr3 = (
        tp3 - current_close
    ) / risk

    change_24h = 0.0

    if len(df_1h) >= 25:

        old_close = _safe_float(
            df_1h["close"].iloc[-25]
        )

        if (
            np.isfinite(old_close)
            and old_close > 0
        ):
            change_24h = (
                (current_close - old_close)
                / old_close
            ) * 100

    strength = (
        "🚀 LONG — "
        "Multi-Timeframe Breakout + "
        "Liquidity + BOS + Volume Confirmation"
    )

    if sweep and bos:
        strength += " 🔥 LIQUIDITY SWEEP + BOS"

    if fvg:
        strength += " ⚡ FVG"

    if ob:
        strength += " 🏦 ORDER BLOCK"

    reason_parts = [
        "4H bullish",
        "1H confirmed",
        "15M breakout",
    ]

    if sweep:
        reason_parts.append(
            "liquidity sweep"
        )

    if bos:
        reason_parts.append(
            "BOS"
        )

    if volume_quality in [
        "STRONG",
        "NORMAL"
    ]:
        reason_parts.append(
            f"volume {volume_ratio:.2f}x"
        )

    if momentum_ok:
        reason_parts.append(
            f"RSI {rsi:.1f}"
        )

    if fvg:
        reason_parts.append(
            "bullish FVG"
        )

    if ob:
        reason_parts.append(
            "order block"
        )

    if btc_state == "BULLISH":
        reason_parts.append(
            "BTC confirmation"
        )

    reason = (
        "Confirmed institutional-style LONG setup: "
        + ", ".join(reason_parts)
    )

    return {

        "signal": "LONG",

        "strength": strength,

        "quality": quality,

        "change_24h": round(
            change_24h,
            2
        ),

        "rating": round(
            score,
            1
        ),

        "confidence": round(
            score,
            1
        ),

        "score": round(
            score,
            1
        ),

        "current_price": round(
            current_close,
            8
        ),

        "entry": round(
            current_close,
            8
        ),

        "stop_loss": round(
            stop_loss,
            8
        ),

        "tp1": round(
            tp1,
            8
        ),

        "tp2": round(
            tp2,
            8
        ),

        "tp3": round(
            tp3,
            8
        ),

        "risk_percentage": round(
            risk_percentage,
            2
        ),

        "risk_reward": (
            f"1:{rr2:.1f}"
        ),

        "rr_tp1": round(
            rr1,
            2
        ),

        "rr_tp2": round(
            rr2,
            2
        ),

        "rr_tp3": round(
            rr3,
            2
        ),

        "timeframe": "15M entry / 1H + 4H trend",

        "trend_4h": trend_4h,

        "trend_1h": trend_1h,

        "trend_15m": trend_15m,

        "btc_state": btc_state,

        "volume_ratio": round(
            volume_ratio,
            2
        ),

        "rsi": round(
            rsi,
            2
        ) if np.isfinite(rsi) else None,

        "liquidity_sweep": sweep,

        "liquidity_type": sweep_type,

        "bos": bos,

        "breakout": breakout,

        "breakout_distance": round(
            breakout_distance,
            8
        ),

        "fvg": fvg,

        "order_block": ob,

        "ob_low": (
            round(ob_low, 8)
            if ob_low is not None
            else None
        ),

        "ob_high": (
            round(ob_high, 8)
            if ob_high is not None
            else None
        ),

        "resistance": (
            round(resistance, 8)
            if np.isfinite(resistance)
            else None
        ),

        "confirmations": confirmations,

        "warnings": warnings,

        "confirmation_count": len(
            confirmations
        ),

        "m_factor": min(
            100,
            int(score + 2)
        ),

        "v_factor": min(
            100,
            int(
                70
                + min(
                    volume_ratio * 8,
                    30
                )
            )
        ),

        "t_factor": min(
            100,
            int(
                (
                    (
                        trend_4h == "BULLISH"
                    )
                    * 40
                    +
                    (
                        trend_1h == "BULLISH"
                    )
                    * 30
                    +
                    (
                        trend_15m == "BULLISH"
                    )
                    * 30
                )
            )
        ),

        "reason": reason
    }
