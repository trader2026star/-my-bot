# ============================================================ #
# analysis.py — StrategyEngine V123.5 (Combined & Optimized)   #
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

    def calculate_rsi(self, series, period=14):
        s = pd.to_numeric(series, errors="coerce")
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.replace([np.inf, -np.inf], np.nan).fillna(50)

    def calculate_atr(self, df, period=14):
        h = pd.to_numeric(df["high"], errors="coerce")
        l = pd.to_numeric(df["low"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    def calculate_ema(self, series, period):
        return pd.to_numeric(series, errors="coerce").ewm(span=period, adjust=False, min_periods=period).mean()

    def prepare_dataframe(self, candles):
        if candles is None or len(candles) == 0:
            return pd.DataFrame()
        try:
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            for col in ["timestamp", "open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().drop_duplicates(subset=["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        except Exception as exc:
            logger.error("prepare_dataframe error: %s", exc)
            return pd.DataFrame()

    def _daily_bias(self, df):
        if len(df) < 35:
            return {"bullish": False, "score": 0, "reason": "Daily data insufficient"}
        close = float(df["close"].iloc[-1])
        ema20 = self.calculate_ema(df["close"], 20)
        ema50 = self.calculate_ema(df["close"], 50)
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
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
        return {"bullish": bullish, "score": score, "rsi": rsi, "ema20": e20, "ema50": e50, "reason": "، ".join(reasons)}

    def _four_hour_structure(self, df):
        if len(df) < 35:
            return {"bullish": False, "score": 0, "reason": "4H data insufficient"}
        close = float(df["close"].iloc[-1])
        ema20 = self.calculate_ema(df["close"], 20)
        e20 = float(ema20.iloc[-1])
        recent_low = float(df.tail(12)["low"].min())

        score = 0
        reasons = []
        if close > e20:
            score += 8
            reasons.append("4H فوق EMA20")
        if recent_low >= float(df.iloc[-24:-12]["low"].min()) * 0.97:
            score += 10
            reasons.append("4H يحافظ على قاع أعلى")

        bullish = score >= 20 and close > e20
        return {"bullish": bullish, "score": score, "reason": "، ".join(reasons)}

    def _one_hour_entry(self, df):
        if len(df) < 30:
            return {"valid": False, "score": 0, "reason": "1H data insufficient"}

        close = float(df["close"].iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        atr = float(self.calculate_atr(df).iloc[-1])

        if atr <= 0 or close <= 0:
            return {"valid": False, "score": 0, "reason": "Invalid ATR/price"}

        recent = df.tail(24)
        range_high = float(recent["high"].max())
        range_low = float(recent["low"].min())
        range_size = range_high - range_low

        if range_size <= 0:
            return {"valid": False, "score": 0, "reason": "Invalid 1H range"}

        fibo_50 = range_high - (0.50 * range_size)
        fibo_618 = range_high - (0.618 * range_size)
        position_in_range = (close - range_low) / range_size

        score = 0
        reasons = []

        if fibo_618 <= close <= fibo_50:
            score += 18
            reasons.append("ارتداد دقيق من مستويات الذهب لفيبو (50%-61.8%)")
        elif position_in_range <= 0.55:
            score += 14
            reasons.append("السعر في منطقة الخصم والاتزان")

        if 40 <= rsi <= 65:
            score += 12
            reasons.append("RSI في نطاق تجميعي مثالي")

        price_5bar_ago = float(df["close"].iloc[-6]) if len(df) >= 6 else close
        roc_5bar = (close - price_5bar_ago) / price_5bar_ago * 100

        if roc_5bar > 4.2:
            score -= 25
            reasons.append("صعود سريع سابق (تجنب الدخول المتأخر)")
        elif -2.0 <= roc_5bar <= 2.5:
            score += 10
            reasons.append("حركة هادئة في بداية الزخم")

        valid = score >= 42 and position_in_range <= 0.55 and roc_5bar < 3.8 and rsi < 65
        return {
            "valid": valid,
            "score": score,
            "rsi": rsi,
            "atr": atr,
            "position_in_range": position_in_range,
            "roc_5bar": roc_5bar,
            "reason": "، ".join(reasons),
        }

    def _build_trade_plan(self, df1h, entry_price, atr):
        recent_low = float(df1h["low"].tail(14).min())
        stop_loss = min(recent_low * 0.985, entry_price - (1.6 * atr))
        risk = entry_price - stop_loss
        if risk <= 0:
            return None

        return {
            "entry_low": entry_price - (0.25 * atr),
            "entry_high": entry_price + (0.1 * atr),
            "stop_loss": stop_loss,
            "tp1": entry_price + (1.6 * risk),
            "tp2": entry_price + (2.6 * risk),
            "tp3": entry_price + (4.2 * risk),
        }

    def analyze_market_structure(self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None, asset_type="crypto"):
        neutral = build_signal("NEUTRAL", 0, 0, 0, [], 0, 50, 0, "لا توجد فرصة تجميع مبكرة مكتملة الشروط", {})
        try:
            if ohlcv_daily is None or ohlcv_4h is None or ohlcv_1h is None:
                return "NEUTRAL", 0.0, neutral
            if len(ohlcv_daily) < 40 or len(ohlcv_4h) < 35 or len(ohlcv_1h) < 30:
                return "NEUTRAL", 0.0, neutral

            daily = self.prepare_dataframe(ohlcv_daily)
            h4 = self.prepare_dataframe(ohlcv_4h)
            h1 = self.prepare_dataframe(ohlcv_1h)

            daily_info = self._daily_bias(daily)
            h4_info = self._four_hour_structure(h4)
            h1_info = self._one_hour_entry(h1)

            if not daily_info["bullish"] or not h4_info["bullish"] or not h1_info["valid"]:
                return "NEUTRAL", 0.0, build_signal(
                    "NEUTRAL", 0, 0, 0, [], 0, h1_info.get("rsi", 50), 0,
                    "شروط التحليل الهيكلي غير مكتملة",
                    {"daily": daily_info, "4h": h4_info, "1h": h1_info}
                )

            raw_score = float(daily_info["score"]) + float(h4_info["score"]) + float(h1_info["score"])
            score = int(round(min(100, max(0, (raw_score / 120.0) * 100.0))))

            if score < self.min_score:
                return "NEUTRAL", 0.0, neutral

            price = float(h1["close"].iloc[-1])
            atr = float(h1_info["atr"])
            trade = self._build_trade_plan(h1, price, atr)
            if not trade:
                return "NEUTRAL", 0.0, neutral

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            signal = build_signal(
                direction="LONG",
                entry_low=round(trade["entry_low"], decimals),
                entry_high=round(trade["entry_high"], decimals),
                stop_loss=round(trade["stop_loss"], decimals),
                take_profits=[round(trade["tp1"], decimals), round(trade["tp2"], decimals), round(trade["tp3"], decimals)],
                score=score,
                rsi=h1_info["rsi"],
                atr=atr,
                reason="Daily صاعد | 4H صاعد | 1H Fibo Accumulation Confirmed",
                details={
                    "quality": "A+ | تجميع مبكر قوي",
                    "position_in_range": round(h1_info["position_in_range"], 3),
                    "roc_5bar": round(h1_info["roc_5bar"], 2)
                }
            )
            return "LONG", price, signal
        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral

    # ========================================================
    # دالة فحص الزخم عند الهدف الأول (الخاصة بالتنبيهات)
    # ========================================================
    def check_momentum_at_tp1(self, candles_1h):
        """
        تفحص الزخم عند وصول السعر للهدف الأول (TP1):
        - إذا ضعف الزخم: تقترح الخروج وجني الأرباح.
        - إذا ظل الزخم قوياً: تقترح الاستمرار لباقي الأهداف (TP2 & TP3).
        """
        try:
            df = self.prepare_dataframe(candles_1h)
            if len(df) < 15:
                return "UNKNOWN", "بيانات غير كافية لفحص الزخم"
            
            rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
            volume = pd.to_numeric(df["volume"], errors="coerce")
            vol_ratio = float(volume.iloc[-1] / volume.tail(10).mean()) if volume.tail(10).mean() > 0 else 1.0
            last_close = float(df["close"].iloc[-1])
            prev_close = float(df["close"].iloc[-2])

            if rsi < 48 or (last_close < prev_close and vol_ratio < 0.85):
                return "EXIT", f"⚠️ <b>ضعف الزخم عند TP1 (RSI: {rsi:.1f})</b> -> يُنصح بالخروج وضمان الأرباح."
            else:
                return "CONTINUE", f"🚀 <b>الزخم قوي عند TP1 (RSI: {rsi:.1f})</b> -> استمر لباقي الأهداف (TP2 & TP3)."
        except Exception as exc:
            logger.error("check_momentum_at_tp1 error: %s", exc)
            return "UNKNOWN", "خطأ في حساب فحص الزخم"
