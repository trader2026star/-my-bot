# ============================================================
# analysis.py — StrategyEngine V80.0 (True Bottom & CHoCH / SMC)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900
MIN_SCORE_DEFAULT = 75        
MAX_CHASE_R = 0.35            
MIN_RR_TP1 = 1.4              


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_signal_id():
    return uuid.uuid4().hex[:16]


def build_signal(direction, entry, stop_loss, take_profits, score,
                 rsi, atr, reason, details=None):
    return {
        "signal_id": _new_signal_id(),
        "created_at": _now_iso(),
        "expires_at_seconds": SIGNAL_EXPIRY_SECONDS,
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


def is_signal_expired(signal):
    try:
        created = datetime.fromisoformat(signal["created_at"])
        age = (datetime.now(timezone.utc) - created).total_seconds()
        return age > signal.get("expires_at_seconds", SIGNAL_EXPIRY_SECONDS)
    except Exception:
        return True


class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01,
                 min_score=MIN_SCORE_DEFAULT, max_leverage=5.0):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
        self.max_leverage = max(1.0, float(max_leverage))

    def update_capital(self, new_capital):
        self.capital = max(1.0, float(new_capital))

    def calculate_rsi(self, series, period=14):
        s = pd.to_numeric(series, errors="coerce")
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        al = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        out = 100 - 100 / (1 + rs)
        out = out.mask((al == 0) & (ag > 0), 100)
        out = out.mask((ag == 0) & (al > 0), 0)
        return out

    def calculate_atr(self, df, period=14):
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat(
            [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
        ).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    def prepare_dataframe(self, candles):
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(candles, columns=cols)
        for col in cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=cols)
        df = df[(df["high"] >= df["low"]) & (df["close"] > 0) & (df["volume"] >= 0)]
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def detect_true_bottom_and_choch(self, df):
        if len(df) < 25:
            return False, 0.0, "insufficient data"

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        recent_high = highs[-20:-5].max()
        last_close = closes[-1]
        
        broken_high = last_close > recent_high
        min_idx = np.argmin(lows[-15:])
        true_bottom = float(lows[-15:][min_idx])
        holding_above = last_close > true_bottom

        if broken_high and holding_above:
            return True, true_bottom, "True Bottom & CHoCH Confirmed"

        return False, 0.0, "No structural CHoCH / True Bottom setup"

    def htf_trend_ok(self, ohlcv_1h):
        try:
            if ohlcv_1h is None or len(ohlcv_1h) < 55:
                return True
            df = self.prepare_dataframe(ohlcv_1h)
            if len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            close = df["close"]
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            return bool(float(close.iloc[-1]) >= ema50 * 0.98)
        except Exception:
            return True

    def calculate_risk_from_levels(self, entry, stop, exchange_min_notional=10.0):
        entry, stop = float(entry), float(stop)
        distance = entry - stop
        if entry <= 0 or distance <= 0:
            return {"valid": False, "reason": "stop >= entry"}
        pct = distance / entry
        if pct < 0.002 or pct > 0.08:
            return {"valid": False, "reason": "stop distance out of bounds"}

        risk_cash = self.capital * self.risk_per_trade
        qty = risk_cash / distance
        notional = qty * entry
        max_notional = self.capital * self.max_leverage
        if notional > max_notional:
            notional = max_notional
            qty = notional / entry
        if notional < exchange_min_notional:
            return {"valid": False, "reason": "notional below exchange minimum"}
        return {"valid": True, "risk_pct": pct * 100, "risk_amount": risk_cash,
                "position_size": qty, "notional": notional, "distance": distance}

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0,
            take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="conditions not met",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                neutral["reason"] = "insufficient 15m data"
                return "NEUTRAL", 0.0, neutral

            if ohlcv_1h is not None and not self.htf_trend_ok(ohlcv_1h):
                neutral["reason"] = "HTF trend is bearish (blocked by 1H EMA filter)"
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 60:
                neutral["reason"] = "insufficient clean candles"
                return "NEUTRAL", 0.0, neutral

            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)

            last = df.iloc[-1]
            price = float(last["close"])
            atr, rsi = float(last["ATR"]), float(last["RSI"])

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

            structure_ok, swing_low, setup_reason = self.detect_true_bottom_and_choch(df)
            if not structure_ok:
                neutral["reason"] = "no true bottom / CHoCH structure broken"
                return "NEUTRAL", price, neutral

            stop = swing_low - (0.2 * atr)
            if stop >= price:
                stop = price - (0.8 * atr)

            risk_dist = price - stop
            tp1 = price + (1.5 * risk_dist)
            tp2 = price + (2.5 * risk_dist)
            tp3 = price + (4.0 * risk_dist)
            targets = [tp1, tp2, tp3]

            rr1 = (tp1 - price) / risk_dist
            if rr1 < MIN_RR_TP1:
                neutral["reason"] = "R:R too low"
                return "NEUTRAL", price, neutral

            score = 85
            risk = self.calculate_risk_from_levels(price, stop)
            if not risk.get("valid"):
                neutral["reason"] = "risk rejected"
                return "NEUTRAL", price, neutral

            max_entry = price + MAX_CHASE_R * (price - stop)

            signal = build_signal(
                direction="LONG",
                entry=round(price, decimals),
                stop_loss=round(stop, decimals),
                take_profits=[round(tp, decimals) for tp in targets],
                score=score,
                rsi=rsi,
                atr=atr,
                reason=setup_reason + " + HTF Filter Passed",
                details={
                    "trigger_price": round(price, decimals),
                    "max_entry": round(max_entry, decimals),
                    "risk_pct": round(risk["risk_pct"], 3),
                    "notional": round(risk["notional"], 2),
                    "triggers": ["true_bottom_choch_smc", "htf_ema_filter"],
                },
            )
            return "LONG", price, signal

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = f"exception: {exc}"
            return "NEUTRAL", 0.0, neutral
