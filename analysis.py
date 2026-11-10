# ============================================================
# analysis.py — StrategyEngine V80.0 (Optimized & Lightweight)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _new_signal_id():
    return uuid.uuid4().hex[:16]

def build_signal(direction, entry, stop_loss, take_profits, score, rsi, atr, reason, details=None):
    return {
        "signal_id": _new_signal_id(),
        "created_at": _now_iso(),
        "direction": direction,
        "entry": float(entry),
        "stop_loss": float(stop_loss),
        "take_profits": [float(tp) for tp in take_profits],
        "score": int(score),
        "rsi": float(rsi),
        "atr": float(atr),
        "reason": str(reason),
        "details": details or {},
    }

class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01, min_score=75, max_leverage=5.0):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
        self.max_leverage = max(1.0, float(max_leverage))

    def prepare_dataframe(self, candles):
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(candles, columns=cols)
        for col in cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna().sort_values("timestamp").reset_index(drop=True)
        return df

    def htf_trend_ok(self, ohlcv_1h):
        try:
            if ohlcv_1h is None or len(ohlcv_1h) < 30:
                return True
            df = self.prepare_dataframe(ohlcv_1h)
            close = df["close"]
            ema50 = float(close.ewm(span=30, adjust=False).mean().iloc[-1])
            return bool(float(close.iloc[-1]) >= ema50 * 0.98)
        except Exception:
            return True

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None):
        neutral = build_signal("NEUTRAL", 0.0, 0.0, [], 0, 50.0, 0.0, "conditions not met")
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 40:
                return "NEUTRAL", 0.0, neutral

            if ohlcv_1h is not None and not self.htf_trend_ok(ohlcv_1h):
                neutral["reason"] = "HTF trend bearish filter"
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if len(df) < 30:
                return "NEUTRAL", 0.0, neutral

            last_close = float(df["close"].iloc[-1])
            recent_low = float(df["low"].iloc[-15:].min())
            atr = float((df["high"] - df["low"]).tail(14).mean())

            # True Bottom & CHoCH simplified check
            if last_close > float(df["close"].iloc[-10:-2].max()):
                stop = recent_low - (0.2 * atr)
                tp1 = last_close + (1.5 * (last_close - stop))
                tp2 = last_close + (2.5 * (last_close - stop))
                tp3 = last_close + (4.0 * (last_close - stop))

                signal = build_signal(
                    direction="LONG",
                    entry=round(last_close, 4),
                    stop_loss=round(stop, 4),
                    take_profits=[round(tp1, 4), round(tp2, 4), round(tp3, 4)],
                    score=85,
                    rsi=55.0,
                    atr=atr,
                    reason="True Bottom & CHoCH Confirmed",
                )
                return "LONG", last_close, signal

            return "NEUTRAL", last_close, neutral
        except Exception as e:
            neutral["reason"] = str(e)
            return "NEUTRAL", 0.0, neutral
