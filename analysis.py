# ============================================================
# analysis.py — StrategyEngine V77.0 (Trend Continuation)
# LONG ONLY | Trend + ADX regime + Pullback / Breakout / Sweep-Reclaim
# Interface is identical to V76.0, so main.py works unchanged.
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900   # 15 minutes
MIN_SCORE_DEFAULT = 70        # single source of truth (main.py uses engine.min_score)
MAX_CHASE_R = 0.35            # max price move above entry (in R) before signal is "late"


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

    def _true_range(self, df):
        h, l, c = df["high"], df["low"], df["close"]
        return pd.concat(
            [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
        ).max(axis=1)

    def calculate_atr(self, df, period=14):
        return self._true_range(df).ewm(
            alpha=1.0 / period, min_periods=period, adjust=False).mean()

    def calculate_adx(self, df, period=14):
        """Returns (ADX, +DI, -DI) — measures trend strength and direction."""
        up = df["high"].diff()
        down = -df["low"].diff()
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
        atr = self.calculate_atr(df, period)
        a = 1.0 / period
        plus_di = 100 * plus_dm.ewm(alpha=a, min_periods=period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=a, min_periods=period, adjust=False).mean() / atr
        denom = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / denom
        adx = dx.ewm(alpha=a, min_periods=period, adjust=False).mean()
        return adx, plus_di, minus_di

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

    # ---------------- Pattern helpers ----------------
    def detect_sweep(self, df):
        """Wick below the reference low, closing back above it (last 3 candles)."""
        if len(df) < 15:
            return False
        reference_low = float(df["low"].iloc[-12:-4].min())
        for k in (-1, -2, -3):
            row = df.iloc[k]
            if float(row["low"]) < reference_low and float(row["close"]) > reference_low:
                return bool(float(df["close"].iloc[-1]) > reference_low)
        return False

    def detect_volume(self, df):
        if len(df) < 22:
            return False, 0.0
        avg = float(df["volume"].iloc[-21:-1].mean())
        current = float(df["volume"].iloc[-1])
        ratio = current / avg if avg > 0 else 0.0
        return bool(ratio >= 1.3), round(ratio, 2)

    def confirm_5m(self, candles, drop_last_candle=True):
        if candles is None or len(candles) < 25:
            return False, 50.0
        df = self.prepare_dataframe(candles)
        if drop_last_candle and len(df) > 1:
            df = df.iloc[:-1].reset_index(drop=True)
        if len(df) < 20:
            return False, 50.0
        rsi = self.calculate_rsi(df["close"])
        rsi_last = float(rsi.iloc[-1])
        if not np.isfinite(rsi_last):
            return False, 50.0
        last, prev = df.iloc[-1], df.iloc[-2]
        ok = bool(last["close"] > last["open"]
                  and last["close"] >= prev["close"]
                  and 30 <= rsi_last <= 80)
        return ok, rsi_last

    def htf_trend_ok(self, ohlcv_1h):
        """1h filter: last closed close above EMA50 AND EMA20 >= EMA50.
        Fail-closed: missing/short data => False."""
        try:
            if ohlcv_1h is None or len(ohlcv_1h) < 55:
                return False
            df = self.prepare_dataframe(ohlcv_1h)
            if len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 50:
                return False
            close = df["close"]
            ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            return bool(float(close.iloc[-1]) > ema50 and ema20 >= ema50)
        except Exception:
            return False

    # ---------------- Risk ----------------
    def calculate_risk_management(self, entry, atr, swing_low=None,
                                  exchange_min_notional=10.0):
        entry, atr = float(entry), float(atr)
        if entry <= 0 or atr <= 0:
            return {"valid": False, "reason": "invalid price/ATR"}

        atr_stop = entry - 1.6 * atr
        stop = atr_stop
        if swing_low is not None and 0 < float(swing_low) < entry:
            stop = min(atr_stop, float(swing_low) - 0.15 * atr)

        distance = entry - stop
        if distance <= 0:
            return {"valid": False, "reason": "stop >= entry"}
        pct = distance / entry
        if distance < entry * 0.002:
            return {"valid": False, "reason": "stop distance too small"}
        if pct > 0.09:
            return {"valid": False, "reason": "stop too far"}

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

        return {
            "valid": True,
            "stop_loss": stop,
            "risk_pct": pct * 100,
            "risk_amount": risk_cash,
            "position_size": qty,
            "notional": notional,
            "take_profits": [
                entry + distance * 1.4,
                entry + distance * 2.3,
                entry + distance * 3.4,
            ],
        }

    # ---------------- Main analysis ----------------
    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m,
                                 asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0,
            take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="insufficient data or conditions not met",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                neutral["reason"] = "insufficient 15m data"
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if drop_last_candle and len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 60:
                neutral["reason"] = "insufficient clean 15m candles"
                return "NEUTRAL", 0.0, neutral

            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)
            df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()
            df["EMA55"] = df["close"].ewm(span=55, adjust=False).mean()
            df["ADX"], df["PDI"], df["MDI"] = self.calculate_adx(df)

            last = df.iloc[-1]
            price = float(last["close"])
            opn, high, low = float(last["open"]), float(last["high"]), float(last["low"])
            atr, rsi = float(last["ATR"]), float(last["RSI"])
            ema21, ema55 = float(last["EMA21"]), float(last["EMA55"])
            adx, pdi, mdi = float(last["ADX"]), float(last["PDI"]), float(last["MDI"])

            if price <= 0 or not np.isfinite([price, atr, rsi, ema21, ema55, adx, pdi, mdi]).all() or atr <= 0:
                neutral["reason"] = "invalid computed indicators"
                return "NEUTRAL", 0.0, neutral

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            base_details = {"trigger_price": round(price, decimals)}
            reasons = []

            # ---- Regime & quality filters (hard) ----
            atr_pct = atr / price
            if atr_pct < 0.002 or atr_pct > 0.06:
                reasons.append("volatility out of range (%.2f%%)" % (atr_pct * 100))

            ema55_prev = float(df["EMA55"].iloc[-6])
            trend_up = bool(ema21 > ema55 and price > ema55 and ema55 > ema55_prev)
            if not trend_up:
                reasons.append("no 15m uptrend (EMA21>EMA55, price>EMA55, rising)")

            if pdi <= mdi or adx < 18:
                reasons.append("weak trend strength (ADX %.1f)" % adx)

            rng = max(high - low, 1e-12)
            close_pos = (price - low) / rng
            upper_wick = (high - max(opn, price)) / rng
            extended = bool((price - ema21) > 2.2 * atr or rsi > 78)
            if extended:
                reasons.append("price extended (don't chase)")
            if upper_wick > 0.45:
                reasons.append("rejection wick on last candle")
            if price <= opn:
                reasons.append("last candle not bullish")

            volume_ok, volume_ratio = self.detect_volume(df)
            candle_ok, rsi_5m = self.confirm_5m(ohlcv_5m, drop_last_candle=drop_last_candle)

            # ---- Setups ----
            setups = []
            recent = df.iloc[-6:-1]
            touched = bool((recent["low"] <= recent["EMA21"] + 0.3 * atr).any())
            held = bool((recent["close"] > recent["EMA55"]).all())
            rsi_dip = bool(float(recent["RSI"].min()) < 50)
            rsi_prev = float(df["RSI"].iloc[-2])
            reclaim = bool(price > ema21 and rsi > rsi_prev and rsi >= 48)
            if trend_up and touched and held and rsi_dip and reclaim:
                setups.append("pullback")

            donchian = float(df["high"].iloc[-21:-1].max())
            if (trend_up and price > donchian and volume_ratio >= 1.5
                    and close_pos >= 0.7 and adx >= 22):
                setups.append("breakout")

            if trend_up and self.detect_sweep(df):
                setups.append("sweep_reclaim")

            if not setups:
                reasons.append("no setup (pullback/breakout/sweep)")

            # ---- Score ----
            score = 0
            if "pullback" in setups or "breakout" in setups:
                score += 35
            elif "sweep_reclaim" in setups:
                score += 25
            if len(setups) >= 2:
                score += 10
            score += 10 if adx >= 25 else (5 if adx >= 20 else 0)
            score += 10 if volume_ok else 0
            score += 10 if candle_ok else 0
            score += 10 if 45 <= rsi <= 68 else 3
            score += 5 if close_pos >= 0.6 else 0
            score = int(min(100, max(0, score)))

            if setups and score < self.min_score:
                reasons.append("score below threshold (%d<%d)" % (score, self.min_score))

            # ---- Risk ----
            risk = {}
            if not reasons:
                swing = float(df["low"].iloc[-8:].min())
                risk = self.calculate_risk_management(price, atr, swing)
                if not risk.get("valid"):
                    reasons.append("risk rejected: " + risk.get("reason", "unknown"))

            if not reasons and risk.get("valid"):
                stop = risk["stop_loss"]
                max_entry = price + MAX_CHASE_R * (price - stop)
                signal = build_signal(
                    direction="LONG",
                    entry=round(price, decimals),
                    stop_loss=round(stop, decimals),
                    take_profits=[round(tp, decimals) for tp in risk["take_profits"]],
                    score=score,
                    rsi=rsi,
                    atr=atr,
                    reason="Trend Continuation: " + " + ".join(setups),
                    details={
                        "trigger_price": round(price, decimals),
                        "max_entry": round(max_entry, decimals),
                        "volume_ratio": volume_ratio,
                        "rsi_5m": round(rsi_5m, 2),
                        "adx": round(adx, 1),
                        "risk_pct": round(risk["risk_pct"], 3),
                        "notional": round(risk["notional"], 2),
                        "triggers": setups,
                        "entry_zone": {
                            "pullback": "pullback" in setups,
                            "breakout": "breakout" in setups,
                            "sweep_reclaim": "sweep_reclaim" in setups,
                            "volume_confirmed": volume_ok,
                            "confirmed_5m": candle_ok,
                            "trend_ok": trend_up,
                        },
                    },
                )
                return "LONG", price, signal

            neutral["score"] = score
            neutral["rsi"] = rsi
            neutral["atr"] = atr
            neutral["reason"] = " | ".join(reasons) if reasons else "conditions not met"
            base_details.update({"volume_ratio": volume_ratio, "adx": round(adx, 1),
                                 "triggers": setups})
            neutral["details"] = base_details
            return "NEUTRAL", price, neutral

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = "exception: {}".format(exc)
            return "NEUTRAL", 0.0, neutral
