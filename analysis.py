# ============================================================
# analysis.py — StrategyEngine V122.0
# MTF Swing Accumulation Engine
#
# LONG ONLY
# Timeframes:
#   1D  -> Market Bias
#   4H  -> Structure
#   1H  -> Accumulation / Entry
#
# Signal-only:
#   Does NOT place exchange orders.
# ============================================================

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400
MIN_SCORE_DEFAULT = 70


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_signal_id():
    return uuid.uuid4().hex[:16]


def build_signal(
    direction,
    entry_low,
    entry_high,
    stop_loss,
    take_profits,
    score,
    rsi,
    atr,
    reason,
    details=None,
):
    return {
        "signal_id": _new_signal_id(),
        "created_at": _now_iso(),
        "expires_at_seconds": SIGNAL_EXPIRY_SECONDS,
        "direction": direction,
        "entry_low": float(entry_low),
        "entry_high": float(entry_high),
        "stop_loss": float(stop_loss),
        "take_profits": [float(tp) for tp in take_profits],
        "score": int(score),
        "rsi": float(rsi),
        "atr": float(atr),
        "reason": str(reason),
        "details": details or {},
    }


class StrategyEngine:
    def __init__(
        self,
        capital=10000.0,
        risk_per_trade=0.01,
        min_score=MIN_SCORE_DEFAULT,
    ):
        self.capital = max(1.0, float(capital))

        # Conservative risk clamp.
        self.risk_per_trade = min(
            0.02,
            max(0.005, float(risk_per_trade))
        )

        self.min_score = int(min_score)

    # ========================================================
    # BASIC INDICATORS
    # ========================================================

    def calculate_rsi(self, series, period=14):
        s = pd.to_numeric(series, errors="coerce")

        delta = s.diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1.0 / period,
            min_periods=period,
            adjust=False,
        ).mean()

        avg_loss = loss.ewm(
            alpha=1.0 / period,
            min_periods=period,
            adjust=False,
        ).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)

        rsi = 100 - (100 / (1 + rs))

        return rsi.replace([np.inf, -np.inf], np.nan).fillna(50)

    def calculate_atr(self, df, period=14):
        h = pd.to_numeric(df["high"], errors="coerce")
        l = pd.to_numeric(df["low"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")

        tr = pd.concat(
            [
                h - l,
                (h - c.shift()).abs(),
                (l - c.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return tr.ewm(
            alpha=1.0 / period,
            min_periods=period,
            adjust=False,
        ).mean()

    def calculate_ema(self, series, period):
        return pd.to_numeric(series, errors="coerce").ewm(
            span=period,
            adjust=False,
            min_periods=period,
        ).mean()

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def prepare_dataframe(self, candles):
        if candles is None:
            return pd.DataFrame()

        if len(candles) == 0:
            return pd.DataFrame()

        try:
            df = pd.DataFrame(
                candles,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )

            for col in [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]:
                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce",
                )

            df = df.dropna()

            df = df.drop_duplicates(
                subset=["timestamp"]
            )

            df = df.sort_values(
                "timestamp"
            ).reset_index(drop=True)

            if len(df) == 0:
                return pd.DataFrame()

            return df

        except Exception as exc:
            logger.error(
                "prepare_dataframe error: %s",
                exc,
            )
            return pd.DataFrame()

    # ========================================================
    # MARKET BIAS
    # ========================================================

    def _daily_bias(self, df):
        if len(df) < 35:
            return {
                "bullish": False,
                "score": 0,
                "reason": "Daily data insufficient",
            }

        close = float(df["close"].iloc[-1])

        ema20 = self.calculate_ema(
            df["close"],
            20,
        )

        ema50 = self.calculate_ema(
            df["close"],
            50,
        )

        rsi_series = self.calculate_rsi(
            df["close"]
        )

        rsi = float(rsi_series.iloc[-1])

        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        score = 0
        reasons = []

        # Price above EMA20
        if close > e20:
            score += 10
            reasons.append("السعر فوق EMA20")

        # EMA20 above EMA50
        if e20 > e50:
            score += 10
            reasons.append("EMA20 فوق EMA50")

        # RSI healthy bullish zone
        if 48 <= rsi <= 68:
            score += 8
            reasons.append("RSI يومي صحي")

        # Recent structure
        recent_high = float(
            df["high"].tail(10).max()
        )

        previous_high = float(
            df["high"].iloc[-20:-10].max()
        )

        if recent_high >= previous_high:
            score += 7
            reasons.append("تحسن في القمم اليومية")

        bullish = (
            score >= 22
            and close > e20
        )

        return {
            "bullish": bullish,
            "score": score,
            "rsi": rsi,
            "ema20": e20,
            "ema50": e50,
            "reason": "، ".join(reasons),
        }

    # ========================================================
    # 4H STRUCTURE
    # ========================================================

    def _four_hour_structure(self, df):
        if len(df) < 35:
            return {
                "bullish": False,
                "score": 0,
                "reason": "4H data insufficient",
            }

        close = float(df["close"].iloc[-1])

        ema20 = self.calculate_ema(
            df["close"],
            20,
        )

        ema50 = self.calculate_ema(
            df["close"],
            50,
        )

        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        recent = df.tail(12)

        recent_high = float(
            recent["high"].max()
        )

        previous = df.iloc[-24:-12]

        previous_high = float(
            previous["high"].max()
        )

        recent_low = float(
            recent["low"].min()
        )

        previous_low = float(
            previous["low"].min()
        )

        score = 0
        reasons = []

        if close > e20:
            score += 8
            reasons.append("4H فوق EMA20")

        if e20 > e50:
            score += 7
            reasons.append("4H EMA20 > EMA50")

        # Break / reclaim of previous range
        if close >= previous_high * 0.995:
            score += 10
            reasons.append("4H استعادة منطقة مقاومة سابقة")

        # Higher-low style behavior
        if recent_low >= previous_low * 0.97:
            score += 7
            reasons.append("4H يحافظ على قاع أعلى نسبيًا")

        bullish = (
            score >= 22
            and close > e20
        )

        return {
            "bullish": bullish,
            "score": score,
            "recent_high": recent_high,
            "previous_high": previous_high,
            "recent_low": recent_low,
            "previous_low": previous_low,
            "ema20": e20,
            "ema50": e50,
            "reason": "، ".join(reasons),
        }

    # ========================================================
    # 1H ACCUMULATION / ENTRY
    # ========================================================

    def _one_hour_entry(self, df):
        if len(df) < 30:
            return {
                "valid": False,
                "score": 0,
                "reason": "1H data insufficient",
            }

        close = float(df["close"].iloc[-1])

        ema20 = self.calculate_ema(
            df["close"],
            20,
        )

        ema50 = self.calculate_ema(
            df["close"],
            50,
        )

        rsi_series = self.calculate_rsi(
            df["close"]
        )

        atr_series = self.calculate_atr(
            df
        )

        rsi = float(rsi_series.iloc[-1])
        atr = float(atr_series.iloc[-1])

        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        if atr <= 0 or close <= 0:
            return {
                "valid": False,
                "score": 0,
                "reason": "Invalid ATR/price",
            }

        score = 0
        reasons = []

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if 42 <= rsi <= 62:
            score += 10
            reasons.append("RSI 1H في منطقة صحية")

        elif 35 <= rsi < 42:
            score += 6
            reasons.append("RSI منخفض مع فرصة ارتداد")

        elif rsi > 72:
            score -= 8
            reasons.append("RSI مرتفع جدًا")

        # ----------------------------------------------------
        # EMA structure
        # ----------------------------------------------------

        if close > e20:
            score += 7
            reasons.append("السعر فوق EMA20")

        if e20 > e50:
            score += 7
            reasons.append("EMA20 فوق EMA50")

        # ----------------------------------------------------
        # Recent range / accumulation
        # ----------------------------------------------------

        recent = df.tail(18)

        range_high = float(
            recent["high"].max()
        )

        range_low = float(
            recent["low"].min()
        )

        range_size = range_high - range_low

        if range_size <= 0:
            return {
                "valid": False,
                "score": 0,
                "reason": "Invalid 1H range",
            }

        position_in_range = (
            close - range_low
        ) / range_size

        # Prefer lower/middle part of range,
        # not buying an extended breakout.
        if 0.25 <= position_in_range <= 0.68:
            score += 10
            reasons.append("السعر داخل منطقة تجميع مناسبة")

        elif position_in_range < 0.25:
            score += 7
            reasons.append("السعر قريب من قاع النطاق")

        elif position_in_range > 0.82:
            score -= 8
            reasons.append("السعر مرتفع داخل النطاق")

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        volume = pd.to_numeric(
            df["volume"],
            errors="coerce",
        )

        current_volume = float(
            volume.iloc[-1]
        )

        avg_volume = float(
            volume.tail(20).mean()
        )

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 1.0
        )

        if volume_ratio >= 1.30:
            score += 10
            reasons.append("ارتفاع واضح في الحجم")

        elif volume_ratio >= 1.05:
            score += 5
            reasons.append("الحجم مقبول")

        # ----------------------------------------------------
        # Recent candle momentum
        # ----------------------------------------------------

        last_open = float(
            df["open"].iloc[-1]
        )

        last_high = float(
            df["high"].iloc[-1]
        )

        last_low = float(
            df["low"].iloc[-1]
        )

        candle_range = last_high - last_low

        if candle_range > 0:
            close_position = (
                close - last_low
            ) / candle_range

            if (
                close > last_open
                and close_position >= 0.60
            ):
                score += 8
                reasons.append(
                    "شمعة 1H إيجابية بإغلاق قوي"
                )

        # ----------------------------------------------------
        # Avoid excessive extension from EMA20
        # ----------------------------------------------------

        extension_pct = (
            abs(close - e20) / close * 100
        )

        if extension_pct <= 3.0:
            score += 5
            reasons.append("السعر غير ممتد عن EMA20")

        elif extension_pct > 7.0:
            score -= 8
            reasons.append("السعر ممتد عن EMA20")

        # ----------------------------------------------------
        # Accumulation validity
        # ----------------------------------------------------

        valid = (
            score >= 32
            and close > e50 * 0.985
            and rsi < 70
        )

        return {
            "valid": valid,
            "score": score,
            "rsi": rsi,
            "atr": atr,
            "ema20": e20,
            "ema50": e50,
            "range_high": range_high,
            "range_low": range_low,
            "position_in_range": position_in_range,
            "volume_ratio": volume_ratio,
            "extension_pct": extension_pct,
            "reason": "، ".join(reasons),
        }

    # ========================================================
    # RISK / ENTRY
    # ========================================================

    def _build_trade_plan(
        self,
        df1h,
        entry_price,
        atr,
        score,
    ):
        if entry_price <= 0 or atr <= 0:
            return None

        recent_low = float(
            df1h["low"].tail(14).min()
        )

        # Structure-based stop.
        structure_stop = recent_low * 0.985

        # ATR-based stop.
        atr_stop = entry_price - (1.8 * atr)

        # We want a stop that is not extremely tight.
        stop_loss = min(
            structure_stop,
            atr_stop,
        )

        # Prevent absurdly large stop distances.
        risk_pct = (
            (entry_price - stop_loss)
            / entry_price
            * 100
        )

        # If stop is too close, use a minimum ATR protection.
        if risk_pct < 1.2:
            stop_loss = entry_price - (1.5 * atr)

        # If stop becomes too wide, use 3 ATR maximum.
        max_risk_pct = 8.0

        risk_pct = (
            (entry_price - stop_loss)
            / entry_price
            * 100
        )

        if risk_pct > max_risk_pct:
            stop_loss = entry_price * (
                1.0 - max_risk_pct / 100.0
            )

        risk = entry_price - stop_loss

        if risk <= 0:
            return None

        # ----------------------------------------------------
        # Entry zone
        # ----------------------------------------------------

        entry_low = entry_price - (0.25 * atr)
        entry_high = entry_price + (0.15 * atr)

        if entry_low <= 0:
            entry_low = entry_price * 0.995

        # ----------------------------------------------------
        # Targets
        # ----------------------------------------------------

        tp1 = entry_price + (1.5 * risk)
        tp2 = entry_price + (2.5 * risk)
        tp3 = entry_price + (4.0 * risk)

        rr_final = (
            (tp3 - entry_price)
            / risk
        )

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk": risk,
            "risk_pct": risk_pct,
            "rr_final": rr_final,
        }

    # ========================================================
    # MAIN ANALYSIS
    # ========================================================

    def analyze_market_structure(
        self,
        ohlcv_daily,
        ohlcv_4h=None,
        ohlcv_1h=None,
        asset_type="crypto",
    ):
        neutral = build_signal(
            direction="NEUTRAL",
            entry_low=0.0,
            entry_high=0.0,
            stop_loss=0.0,
            take_profits=[],
            score=0,
            rsi=50.0,
            atr=0.0,
            reason=(
                "لا توجد فرصة LONG مكتملة "
                "وفق شروط Swing Accumulation"
            ),
            details={},
        )

        try:
            # ------------------------------------------------
            # Validate all timeframes
            # ------------------------------------------------

            if (
                ohlcv_daily is None
                or ohlcv_4h is None
                or ohlcv_1h is None
            ):
                return "NEUTRAL", 0.0, neutral

            if (
                len(ohlcv_daily) < 40
                or len(ohlcv_4h) < 35
                or len(ohlcv_1h) < 30
            ):
                return "NEUTRAL", 0.0, neutral

            daily = self.prepare_dataframe(
                ohlcv_daily
            )

            h4 = self.prepare_dataframe(
                ohlcv_4h
            )

            h1 = self.prepare_dataframe(
                ohlcv_1h
            )

            if (
                len(daily) < 35
                or len(h4) < 30
                or len(h1) < 25
            ):
                return "NEUTRAL", 0.0, neutral

            # ------------------------------------------------
            # Analyze each timeframe
            # ------------------------------------------------

            daily_info = self._daily_bias(
                daily
            )

            h4_info = self._four_hour_structure(
                h4
            )

            h1_info = self._one_hour_entry(
                h1
            )

            # ------------------------------------------------
            # Hard protection
            # ------------------------------------------------

            if not daily_info["bullish"]:
                return "NEUTRAL", 0.0, build_signal(
                    direction="NEUTRAL",
                    entry_low=0,
                    entry_high=0,
                    stop_loss=0,
                    take_profits=[],
                    score=0,
                    rsi=daily_info.get("rsi", 50),
                    atr=0,
                    reason="Daily bias غير صاعد",
                    details={
                        "daily": daily_info,
                        "4h": h4_info,
                        "1h": h1_info,
                    },
                )

            if not h4_info["bullish"]:
                return "NEUTRAL", 0.0, build_signal(
                    direction="NEUTRAL",
                    entry_low=0,
                    entry_high=0,
                    stop_loss=0,
                    take_profits=[],
                    score=0,
                    rsi=daily_info.get("rsi", 50),
                    atr=0,
                    reason="4H structure غير صاعد",
                    details={
                        "daily": daily_info,
                        "4h": h4_info,
                        "1h": h1_info,
                    },
                )

            if not h1_info["valid"]:
                return "NEUTRAL", 0.0, build_signal(
                    direction="NEUTRAL",
                    entry_low=0,
                    entry_high=0,
                    stop_loss=0,
                    take_profits=[],
                    score=0,
                    rsi=h1_info.get("rsi", 50),
                    atr=h1_info.get("atr", 0),
                    reason="1H لم يؤكد منطقة دخول مناسبة",
                    details={
                        "daily": daily_info,
                        "4h": h4_info,
                        "1h": h1_info,
                    },
                )

            # ------------------------------------------------
            # Composite score
            #
            # Daily max 35
            # 4H max 32
            # 1H max 50-ish
            #
            # Normalize into 0-100.
            # ------------------------------------------------

            raw_score = (
                float(daily_info["score"])
                + float(h4_info["score"])
                + float(h1_info["score"])
            )

            # The practical max is approximately 117.
            score = int(
                round(
                    min(
                        100,
                        max(
                            0,
                            (raw_score / 117.0) * 100.0,
                        ),
                    )
                )
            )

            # Minimum threshold.
            if score < self.min_score:
                return "NEUTRAL", 0.0, build_signal(
                    direction="NEUTRAL",
                    entry_low=0,
                    entry_high=0,
                    stop_loss=0,
                    take_profits=[],
                    score=score,
                    rsi=h1_info["rsi"],
                    atr=h1_info["atr"],
                    reason=(
                        f"التقييم {score}/100 أقل "
                        f"من الحد الأدنى {self.min_score}"
                    ),
                    details={
                        "daily": daily_info,
                        "4h": h4_info,
                        "1h": h1_info,
                    },
                )

            # ------------------------------------------------
            # Entry price
            # ------------------------------------------------

            price = float(
                h1["close"].iloc[-1]
            )

            atr = float(
                h1_info["atr"]
            )

            trade = self._build_trade_plan(
                h1,
                price,
                atr,
                score,
            )

            if not trade:
                return "NEUTRAL", 0.0, neutral

            # ------------------------------------------------
            # Score-based quality labels
            # ------------------------------------------------

            if score >= 88:
                quality = "A+ | فرصة قوية جدًا"
            elif score >= 82:
                quality = "A | فرصة قوية"
            elif score >= 76:
                quality = "B+ | فرصة جيدة"
            else:
                quality = "B | فرصة مشروطة"

            reason_parts = [
                "Daily Bias صاعد",
                "4H Structure صاعد",
                "1H Accumulation/Entry confirmed",
            ]

            if h1_info["volume_ratio"] >= 1.30:
                reason_parts.append(
                    "Volume confirmation"
                )

            if h1_info["rsi"] < 45:
                reason_parts.append(
                    "RSI منخفض نسبيًا"
                )

            reason = " | ".join(
                reason_parts
            )

            decimals = (
                8
                if price < 0.1
                else (
                    6
                    if price < 1
                    else (
                        4
                        if price < 100
                        else 2
                    )
                )
            )

            signal = build_signal(
                direction="LONG",
                entry_low=round(
                    trade["entry_low"],
                    decimals,
                ),
                entry_high=round(
                    trade["entry_high"],
                    decimals,
                ),
                stop_loss=round(
                    trade["stop_loss"],
                    decimals,
                ),
                take_profits=[
                    round(
                        trade["tp1"],
                        decimals,
                    ),
                    round(
                        trade["tp2"],
                        decimals,
                    ),
                    round(
                        trade["tp3"],
                        decimals,
                    ),
                ],
                score=score,
                rsi=h1_info["rsi"],
                atr=atr,
                reason=reason,
                details={
                    "quality": quality,
                    "timeframes": "1D + 4H + 1H",
                    "daily_score": daily_info["score"],
                    "four_hour_score": h4_info["score"],
                    "one_hour_score": h1_info["score"],
                    "volume_ratio": round(
                        h1_info["volume_ratio"],
                        2,
                    ),
                    "entry_position": round(
                        h1_info["position_in_range"],
                        3,
                    ),
                    "risk_pct": round(
                        trade["risk_pct"],
                        2,
                    ),
                    "rr_tp1": 1.5,
                    "rr_tp2": 2.5,
                    "rr_tp3": round(
                        trade["rr_final"],
                        2,
                    ),
                    "leverage": "3x-5x",
                },
            )

            return (
                "LONG",
                price,
                signal,
            )

        except Exception as exc:
            logger.exception(
                "Analysis error: %s",
                exc,
            )

            return (
                "NEUTRAL",
                0.0,
                neutral,
            )

    # ========================================================
    # OPTIONAL COMPATIBILITY METHOD
    # ========================================================

    def calculate_risk_management(
        self,
        entry_price,
        atr,
        direction="LONG",
    ):
        """
        Compatibility helper for future/main.py usage.
        Signal-only. No order execution.
        """

        try:
            entry_price = float(entry_price)
            atr = float(atr)

            if entry_price <= 0 or atr <= 0:
                return {}

            if direction.upper() == "LONG":
                stop = entry_price - (
                    1.8 * atr
                )

                risk = entry_price - stop

                return {
                    "direction": "LONG",
                    "entry": entry_price,
                    "stop_loss": stop,
                    "tp1": entry_price + (
                        1.5 * risk
                    ),
                    "tp2": entry_price + (
                        2.5 * risk
                    ),
                    "tp3": entry_price + (
                        4.0 * risk
                    ),
                    "risk_amount_per_unit": risk,
                    "risk_percent": (
                        risk / entry_price * 100
                    ),
                }

            return {}

        except Exception as exc:
            logger.error(
                "calculate_risk_management error: %s",
                exc,
            )
            return {}
