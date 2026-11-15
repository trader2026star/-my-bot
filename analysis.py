# ============================================================ #
# analysis.py — StrategyEngine V123.0 (Anti-Late-Entry Edition) #
# MTF Swing Accumulation & Early Detection Engine            #
#                                                              #
# LONG ONLY                                                    #
# Timeframes:                                                  #
# 1D -> Market Bias                                            #
# 4H -> Structure                                              #
# 1H -> Early Accumulation / Discount Entry                    #
# ============================================================ #

import logging
import uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400
MIN_SCORE_DEFAULT = 72


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
        self.risk_per_trade = min(0.02, max(0.005, float(risk_per_trade)))
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
            alpha=1.0 / period, min_periods=period, adjust=False
        ).mean()
        avg_loss = loss.ewm(
            alpha=1.0 / period, min_periods=period, adjust=False
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
            alpha=1.0 / period, min_periods=period, adjust=False
        ).mean()

    def calculate_ema(self, series, period):
        return pd.to_numeric(series, errors="coerce").ewm(
            span=period, adjust=False, min_periods=period
        ).mean()

    # ========================================================
    # DATA PREPARATION
    # ========================================================
    def prepare_dataframe(self, candles):
        if candles is None or len(candles) == 0:
            return pd.DataFrame()
        try:
            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            for col in ["timestamp", "open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().drop_duplicates(subset=["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        except Exception as exc:
            logger.error("prepare_dataframe error: %s", exc)
            return pd.DataFrame()

    # ========================================================
    # MARKET BIAS (1D)
    # ========================================================
    def _daily_bias(self, df):
        if len(df) < 35:
            return {"bullish": False, "score": 0, "reason": "Daily data insufficient"}
        close = float(df["close"].iloc[-1])
        ema20 = self.calculate_ema(df["close"], 20)
        ema50 = self.calculate_ema(df["close"], 50)
        rsi_series = self.calculate_rsi(df["close"])
        rsi = float(rsi_series.iloc[-1])
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        score = 0
        reasons = []

        if close > e20:
            score += 10
            reasons.append("السعر فوق EMA20")
        if e20 > e50:
            score += 10
            reasons.append("EMA20 فوق EMA50")
        if 45 <= rsi <= 68:
            score += 8
            reasons.append("RSI يومي صحي")

        bullish = score >= 20 and close > e20
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
            return {"bullish": False, "score": 0, "reason": "4H data insufficient"}
        close = float(df["close"].iloc[-1])
        ema20 = self.calculate_ema(df["close"], 20)
        ema50 = self.calculate_ema(df["close"], 50)
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        recent = df.tail(12)
        recent_low = float(recent["low"].min())
        previous_low = float(df.iloc[-24:-12]["low"].min())

        score = 0
        reasons = []

        if close > e20:
            score += 8
            reasons.append("4H فوق EMA20")
        if e20 > e50:
            score += 7
            reasons.append("4H EMA20 > EMA50")
        if recent_low >= previous_low * 0.97:
            score += 10
            reasons.append("4H يحافظ على قاع أعلى (Higher Low)")

        bullish = score >= 20 and close > e20
        return {
            "bullish": bullish,
            "score": score,
            "recent_low": recent_low,
            "previous_low": previous_low,
            "ema20": e20,
            "ema50": e50,
            "reason": "، ".join(reasons),
        }

    # ========================================================
    # 1H EARLY ACCUMULATION & ENTRY (Anti-Late-Entry)
    # Strategy: Fibo 50%-0.618 + Volume Profile PoC + Bullish Engulfing
    # ========================================================
    def _one_hour_entry(self, df):
        if len(df) < 30:
            return {"valid": False, "score": 0, "reason": "1H data insufficient"}

        close = float(df["close"].iloc[-1])
        ema20 = self.calculate_ema(df["close"], 20)
        ema50 = self.calculate_ema(df["close"], 50)
        rsi_series = self.calculate_rsi(df["close"])
        atr_series = self.calculate_atr(df)

        rsi = float(rsi_series.iloc[-1])
        atr = float(atr_series.iloc[-1])
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        if atr <= 0 or close <= 0:
            return {"valid": False, "score": 0, "reason": "Invalid ATR/price"}

        score = 0
        reasons = []

        # 1. نطاق الأسعار الفتروي لحساب الفيبوناتشي ومستويات الخصم
        recent = df.tail(24)
        range_high = float(recent["high"].max())
        range_low = float(recent["low"].min())
        range_size = range_high - range_low

        if range_size <= 0:
            return {"valid": False, "score": 0, "reason": "Invalid 1H range"}

        # حساب مستويات الفيبوناتشي الداخلية للنطاق (0.5 و 0.618)
        fibo_50 = range_high - (0.50 * range_size)
        fibo_618 = range_high - (0.618 * range_size)

        position_in_range = (close - range_low) / range_size

        # 2. تقاطع السعر مع مستويات الفيبوناتشي الذهبية (50% - 618%) أو مناطق الخصم
        if fibo_618 <= close <= fibo_50:
            score += 18
            reasons.append("ارتداد دقيق من مستويات الذهب لفيبو (50% - 61.8%)")
        elif position_in_range <= 0.45:
            score += 14
            reasons.append("السعر في منطقة الخصم (Discount Zone)")
        elif position_in_range > 0.65:
            score -= 25
            reasons.append("رفض: السعر تجاوز منتصف النطاق (تجنب الدخول المتأخر)")

        # 3. RSI تجميعي (تجنب التشبع الشرائي المنتهي)
        if 40 <= rsi <= 58:
            score += 12
            reasons.append("RSI في نطاق تجميعي مثالي")
        elif rsi > 68:
            score -= 25
            reasons.append("رفض: RSI مرتفع وزخم منتهي")

        # 4. دمج بروفايل الحجم ونقطة التحكم (Volume Profile PoC Approximation)
        volume = pd.to_numeric(df["volume"], errors="coerce")
        # حساب السعر الأكثر تداولاً (منطقة التحكم PoC تقريبياً بناءً على تركز الفوليوم مع الأسعار)
        df_recent = recent.copy()
        df_recent["price_zone"] = pd.qcut(df_recent["close"], q=5, labels=False, duplicates="drop")
        volume_by_zone = df_recent.groupby("price_zone")["volume"].sum()
        poc_zone = volume_by_zone.idxmax() if not volume_by_zone.empty else 2
        
        current_zone = pd.qcut(pd.Series([close]), q=5, labels=False, duplicates="drop", retbins=False)
        # إذا كان السعر الحالي قرب نقطة التحكم في الحجم أو تحتها بقليل مع دعم
        if current_zone.iloc[0] <= poc_zone:
            score += 15
            reasons.append("السعر يتفاعل مع نقطة التحكم في الحجم (PoC)")

        # 5. نموذج شمعة الابتلاع الشرائي (Bullish Engulfing Confirmation)
        prev_open = float(df["open"].iloc[-2])
        prev_close = float(df["close"].iloc[-2])
        last_open = float(df["open"].iloc[-1])
        
        is_prev_bearish = prev_close < prev_open
        is_last_bullish = close > last_open
        is_engulfing = is_last_bullish and (close >= prev_open) and (last_open <= prev_close)

        if is_engulfing and is_prev_bearish:
            score += 16
            reasons.append("تكون نموذج شمعة الابتلاع الشرائي (Bullish Engulfing)")
        elif close > last_open:
            score += 6
            reasons.append("شمعة انعكاسية صاعدة")

        # 6. فلتر معدل التغير (Rate of Change 5 bars) لمنع مطاردة الصفقات المتأخرة
        price_5bar_ago = float(df["close"].iloc[-6]) if len(df) >= 6 else close
        roc_5bar = (close - price_5bar_ago) / price_5bar_ago * 100

        if roc_5bar > 4.2:
            score -= 30
            reasons.append("رفض: صعود سريع سابق (تم تفويت البداية - تجنب الدخول المتأخر)")
        elif -2.0 <= roc_5bar <= 2.5:
            score += 10
            reasons.append("حركة هادئة في بداية الزخم")

        # شروط الصلاحية الصارمة للتنفيذ
        valid = (
            score >= 42
            and position_in_range <= 0.55
            and roc_5bar < 3.8
            and rsi < 65
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
            "roc_5bar": roc_5bar,
            "reason": "، ".join(reasons),
        }

    # ========================================================
    # RISK / ENTRY PLAN
    # ========================================================
    def _build_trade_plan(self, df1h, entry_price, atr, score):
        if entry_price <= 0 or atr <= 0:
            return None
        recent_low = float(df1h["low"].tail(14).min())
        structure_stop = recent_low * 0.985
        atr_stop = entry_price - (1.6 * atr)
        stop_loss = min(structure_stop, atr_stop)

        risk_pct = (entry_price - stop_loss) / entry_price * 100
        if risk_pct < 0.8:
            stop_loss = entry_price - (1.3 * atr)
        if risk_pct > 7.0:
            stop_loss = entry_price * 0.93

        risk = entry_price - stop_loss
        if risk <= 0:
            return None

        # نطاق الدخول حول الدعم ومستويات الخصم
        entry_low = entry_price - (0.25 * atr)
        entry_high = entry_price + (0.1 * atr)

        tp1 = entry_price + (1.6 * risk)
        tp2 = entry_price + (2.6 * risk)
        tp3 = entry_price + (4.2 * risk)

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
        }

    # ========================================================
    # MAIN ANALYSIS
    # ========================================================
    def analyze_market_structure(
        self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None, asset_type="crypto"
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
            reason="لا توجد فرصة تجميع مبكرة مكتملة الشروط",
            details={},
        )
        try:
            if ohlcv_daily is None or ohlcv_4h is None or ohlcv_1h is None:
                return "NEUTRAL", 0.0, neutral
            if (
                len(ohlcv_daily) < 40
                or len(ohlcv_4h) < 35
                or len(ohlcv_1h) < 30
            ):
                return "NEUTRAL", 0.0, neutral

            daily = self.prepare_dataframe(ohlcv_daily)
            h4 = self.prepare_dataframe(ohlcv_4h)
            h1 = self.prepare_dataframe(ohlcv_1h)

            if len(daily) < 35 or len(h4) < 30 or len(h1) < 25:
                return "NEUTRAL", 0.0, neutral

            daily_info = self._daily_bias(daily)
            h4_info = self._four_hour_structure(h4)
            h1_info = self._one_hour_entry(h1)

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
                    details={"daily": daily_info, "4h": h4_info, "1h": h1_info},
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
                    details={"daily": daily_info, "4h": h4_info, "1h": h1_info},
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
                    reason="1H لم يؤكد منطقة تجميع مبكرة (تم رفض دخول متأخر)",
                    details={"daily": daily_info, "4h": h4_info, "1h": h1_info},
                )

            raw_score = (
                float(daily_info["score"])
                + float(h4_info["score"])
                + float(h1_info["score"])
            )
            score = int(
                round(min(100, max(0, (raw_score / 120.0) * 100.0)))
            )

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
                    reason=f"التقييم {score}/100 أقل من الحد الأدنى {self.min_score}",
                    details={"daily": daily_info, "4h": h4_info, "1h": h1_info},
                )

            price = float(h1["close"].iloc[-1])
            atr = float(h1_info["atr"])
            trade = self._build_trade_plan(h1, price, atr, score)
            if not trade:
                return "NEUTRAL", 0.0, neutral

            if score >= 88:
                quality = "A+ | تجميع مبكر قوي جدًا (Fibo + PoC + Engulfing)"
            elif score >= 82:
                quality = "A | فرصة تجميع ممتازة"
            elif score >= 76:
                quality = "B+ | فرصة جيدة"
            else:
                quality = "B | فرصة مشروطة"

            reason_parts = [
                "Daily Bias صاعد",
                "4H Structure صاعد",
                "1H Fibo & Volume Profile Accumulation Confirmed",
            ]
            if h1_info["roc_5bar"] <= 2.0:
                reason_parts.append("دخول مبكر بدقة قبل الانفجار")

            reason = " | ".join(reason_parts)
            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

            signal = build_signal(
                direction="LONG",
                entry_low=round(trade["entry_low"], decimals),
                entry_high=round(trade["entry_high"], decimals),
                stop_loss=round(trade["stop_loss"], decimals),
                take_profits=[
                    round(trade["tp1"], decimals),
                    round(trade["tp2"], decimals),
                    round(trade["tp3"], decimals),
                ],
                score=score,
                rsi=h1_info["rsi"],
                atr=atr,
                reason=reason,
                details={
                    "quality": quality,
                    "timeframes": "1D + 4H + 1H",
                    "position_in_range": round(h1_info["position_in_range"], 3),
                    "roc_5bar": round(h1_info["roc_5bar"], 2),
                    "leverage": "3x-5x",
                },
            )
            return "LONG", price, signal

        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral

    def calculate_risk_management(self, entry_price, atr, direction="LONG"):
        try:
            entry_price = float(entry_price)
            atr = float(atr)
            if entry_price <= 0 or atr <= 0:
                return {}
            if direction.upper() == "LONG":
                stop = entry_price - (1.6 * atr)
                risk = entry_price - stop
                return {
                    "direction": "LONG",
                    "entry": entry_price,
                    "stop_loss": stop,
                    "tp1": entry_price + (1.6 * risk),
                    "tp2": entry_price + (2.6 * risk),
                    "tp3": entry_price + (4.2 * risk),
                    "risk_amount_per_unit": risk,
                    "risk_percent": (risk / entry_price * 100),
                }
            return {}
        except Exception as exc:
            logger.error("calculate_risk_management error: %s", exc)
            return {}
