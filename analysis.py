# ============================================================
# analysis.py — StrategyEngine V79.0 (SMC / ICT Engine)
# LONG ONLY | FVG, Order Blocks, CHoCH & Liquidity Sweep Logic
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900   # 15 minutes
MIN_SCORE_DEFAULT = 75        # strict institutional threshold
MAX_CHASE_R = 0.35            
MIN_RR_TP1 = 1.5              # higher R:R for institutional entries


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


def validate_signal(signal):
    required = ["signal_id", "created_at", "direction", "entry",
                "stop_loss", "take_profits", "score", "reason"]
    for key in required:
        if key not in signal:
            return False, "missing field: " + key
    if signal["direction"] not in ("LONG", "NEUTRAL"):
        return False, "invalid direction"
    if signal["direction"] == "LONG":
        if signal["entry"] <= 0:
            return False, "entry <= 0"
        if signal["stop_loss"] <= 0 or signal["stop_loss"] >= signal["entry"]:
            return False, "stop_loss must be < entry for LONG"
        tps = signal["take_profits"]
        if len(tps) != 3 or any(tp <= signal["entry"] for tp in tps):
            return False, "need 3 TPs, all > entry for LONG"
        if not (tps[0] < tps[1] < tps[2]):
            return False, "TPs must be ascending"
    if is_signal_expired(signal):
        return False, "signal expired"
    return True, "ok"


class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01,
                 min_score=MIN_SCORE_DEFAULT, max_leverage=5.0):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
        self.max_leverage = max(1.0, float(max_leverage))

    def update_capital(self, new_capital):
        self.capital = max(1.0, float(new_capital))

    # ---------------- Indicators ----------------
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

    # ---------------- SMC / ICT Detection Engine ----------------
    def detect_fvg_and_ob(self, df):
        """Detect Fair Value Gaps (FVG) and Bullish Order Blocks (OB) for LONG entries."""
        fvgs = []
        obs = []
        if len(df) < 10:
            return fvgs, obs

        for i in range(2, len(df) - 1):
            prev_high = float(df.loc[i - 2, "high"])
            curr_low = float(df.loc[i, "low"])
            curr_close = float(df.loc[i, "close"])
            curr_open = float(df.loc[i, "open"])
            prev_close = float(df.loc[i - 1, "close"])
            prev_open = float(df.loc[i - 1, "open"])

            # Bullish FVG (Gap between candle i-2 high and candle i low)
            if curr_low > prev_high:
                fvgs.append({"top": curr_low, "bottom": prev_high, "index": i})

            # Bullish Order Block (Last bearish candle before a strong bullish impulse)
            if prev_close < prev_open and curr_close > curr_open and (curr_close - curr_open) > (prev_open - prev_close):
                obs.append({"high": float(df.loc[i - 1, "high"]), "low": float(df.loc[i - 1, "low"]), "index": i - 1})

        return fvgs, obs

    def detect_choch_bos(self, df):
        """Detect Change of Character (CHoCH) or Break of Structure (BOS) indicating bullish shift."""
        if len(df) < 20:
            return False, "insufficient data for structure"
        
        recent_highs = df["high"].iloc[-15:-3].max()
        last_close = float(df["close"].iloc[-1])
        prev_low = float(df["low"].iloc[-6:-1].min())
        current_low = float(df["low"].iloc[-1])

        # Liquidity sweep: price went below recent swing low and bounced back inside
        sweep = current_low < prev_low and last_close > prev_low
        
        # Structure shift (CHoCH): breaking above recent local high or strong impulsive bullish move
        choch = last_close > recent_highs or (last_close > float(df["close"].iloc[-2]) and sweep)
        
        return bool(choch or sweep), "structure confirmed"

    def htf_trend_ok(self, ohlcv_1h):
        try:
            if ohlcv_1h is None or len(ohlcv_1h) < 55:
                return True
            df = self.prepare_dataframe(ohlcv_1h)
            if len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            close = df["close"]
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            return bool(float(close.iloc[-1]) >= ema50 * 0.99)
        except Exception:
            return True

    def calculate_risk_from_levels(self, entry, stop, exchange_min_notional=10.0):
        entry, stop = float(entry), float(stop)
        distance = entry - stop
        if entry <= 0 or distance <= 0:
            return {"valid": False, "reason": "stop >= entry"}
        pct = distance / entry
        if pct < 0.003 or pct > 0.07:
            return {"valid": False, "reason": "stop distance out of bounds (%.1f%%)" % (pct * 100)}

        risk_cash = self.capital * self.risk_per_trade
        qty = risk_cash / distance
        notional = qty * entry
        max_notional = self.capital * self.max_leverage
        if notional > max_notional:
            notional = max_notional
            qty = notional / entry
            risk_cash = qty * distance
        if notional < exchange_min_notional:
            return {"valid": False, "reason": "notional below exchange minimum"}
        return {"valid": True, "risk_pct": pct * 100, "risk_amount": risk_cash,
                "position_size": qty, "notional": notional, "distance": distance}

    # ---------------- Main analysis ----------------
    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m,
                                 asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0,
            take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="insufficient data or SMC conditions not met",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                neutral["reason"] = "insufficient 15m data"
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if drop_last_candle and len(df) > 1:
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
            reasons = []

            # ---- SMC / ICT Core Checks ----
            structure_ok, struct_reason = self.detect_choch_bos(df)
            if not structure_ok:
                reasons.append("no bullish market structure shift (CHoCH/Sweep)")

            fvgs, obs = self.detect_fvg_and_ob(df)
            # Check if price is currently mitigating an OB or filling an FVG
            zone_matched = None
            for ob in obs[-3:]:
                if ob["low"] <= price <= ob["high"] * 1.01:
                    zone_matched = ob["low"]
                    break
            if not zone_matched and fvgs:
                for fvg in fvgs[-3:]:
                    if fvg["bottom"] <= price <= fvg["top"] * 1.01:
                        zone_matched = fvg["bottom"]
                        break

            if not zone_matched and not structure_ok:
                reasons.append("price not in valid institutional OB/FVG zone")

            stop = None
            targets = []
            if reasons and not structure_ok:
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            # ---- Stop Loss & Targets based on SMC Swing Lows & R:R ----
            recent_swing_low = float(df["low"].iloc[-10:].min())
            stop = recent_swing_low - (0.2 * atr)
            if stop >= price:
                stop = price - (1.0 * atr)

            risk_dist = price - stop
            
            # Target 1, 2, 3 based on structural highs and R multiples
            swing_high = float(df["high"].iloc[-15:].max())
            tp1 = max(swing_high, price + (1.5 * risk_dist))
            tp2 = tp1 + (1.0 * risk_dist)
            tp3 = tp2 + (1.5 * risk_dist)
            targets = [tp1, tp2, tp3]

            rr1 = (tp1 - price) / risk_dist
            if rr1 < MIN_RR_TP1:
                reasons.append("R:R too low (%.2f < %.1f)" % (rr1, MIN_RR_TP1))
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            # ---- Scoring Calculation ----
            score = 70
            if structure_ok:
                score += 10
            if zone_matched:
                score += 10
            if rr1 >= 2.0:
                score += 10
            score = int(min(100, max(0, score)))

            if score < self.min_score:
                reasons.append("SMC score below threshold (%d<%d)" % (score, self.min_score))
                neutral["score"] = score
                neutral["reason"] = " | ".join(reasons)
                return "NEUTRAL", price, neutral

            # ---- Risk Sizing ----
            risk = self.calculate_risk_from_levels(price, stop)
            if not risk.get("valid"):
                neutral["reason"] = "risk rejected: " + risk.get("reason", "unknown")
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
                reason="SMC Institutional Setup (CHoCH / OB / FVG, R:R=%.1f)" % rr1,
                details={
                    "trigger_price": round(price, decimals),
                    "max_entry": round(max_entry, decimals),
                    "risk_pct": round(risk["risk_pct"], 3),
                    "notional": round(risk["notional"], 2),
                    "triggers": ["smc_ict_entry"],
                },
            )
            return "LONG", price, signal

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = "exception: {}".format(exc)
            return "NEUTRAL", 0.0, neutral
