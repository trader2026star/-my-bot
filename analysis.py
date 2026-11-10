# ============================================================
# analysis.py — StrategyEngine V90.0 (Advanced SMC, ICT & Classic Pro)
# LONG / SHORT Dynamic Direction + FVG + BOS + IFVG + AMD + Sweep
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900   # 15 minutes
MIN_SCORE_DEFAULT = 65        # الحد الأدنى للتقييم
MAX_CHASE_R = 0.40            # أقصى تحرك سعري مسموح


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
    return True, "ok"


class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01,
                 min_score=MIN_SCORE_DEFAULT, max_leverage=5.0):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
        self.max_leverage = max(1.0, float(max_leverage))
        self.swing_order = 3

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
        df = pd.DataFrame(candles, columns=[
            "timestamp", "open", "high", "low", "close", "volume"
        ])
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=cols)
        df = df[(df["high"] >= df["low"]) & (df["close"] > 0) & (df["volume"] >= 0)]
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    # --- SMC / ICT & Structure Analysis ---
    def detect_fair_value_gap(self, df):
        if len(df) < 3:
            return {"bullish_fvg": False, "bearish_fvg": False}
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        bullish_fvg = float(c1["high"]) < float(c3["low"])
        bearish_fvg = float(c1["load"] if "load" in c1 else c1["low"]) > float(c3["high"]) # safe check
        bearish_fvg = float(c1["low"]) > float(c3["high"])
        return {"bullish_fvg": bullish_fvg, "bearish_fvg": bearish_fvg}

    def detect_liquidity_sweep(self, df):
        if len(df) < 15:
            return {"sweep_low": False, "sweep_high": False}
        ref_low = float(df["low"].iloc[-12:-4].min())
        ref_high = float(df["high"].iloc[-12:-4].max())
        sweep_low, sweep_high = False, False
        for k in (-1, -2, -3):
            row = df.iloc[k]
            if float(row["low"]) < ref_low and float(row["close"]) > ref_low:
                sweep_low = True
            if float(row["high"]) > ref_high and float(row["close"]) < ref_high:
                sweep_high = True
        return {"sweep_low": sweep_low, "sweep_high": sweep_high}

    def detect_market_structure_break(self, df):
        if len(df) < 15:
            return {"bos_bullish": False, "bos_bearish": False}
        prior_high = float(df["high"].iloc[-13:-1].max())
        prior_low = float(df["low"].iloc[-13:-1].min())
        last = df.iloc[-1]
        bos_bullish = bool(float(last["close"]) > prior_high and float(last["close"]) > float(last["open"]))
        bos_bearish = bool(float(last["close"]) < prior_low and float(last["close"]) < float(last["open"]))
        return {"bos_bullish": bos_bullish, "bos_bearish": bos_bearish}

    def detect_volume(self, df):
        if len(df) < 22:
            return False, 0.0
        avg = float(df["volume"].iloc[-21:-1].mean())
        current = float(df["volume"].iloc[-1])
        ratio = current / avg if avg > 0 else 0.0
        return bool(ratio >= 1.2), round(ratio, 2)

    def calculate_risk_management(self, direction, entry, atr, swing_level=None):
        entry, atr = float(entry), float(atr)
        if direction == "LONG":
            stop = entry - 1.6 * atr
            if swing_level is not None and 0 < float(swing_level) < entry:
                stop = min(stop, float(swing_level) - 0.15 * atr)
            distance = entry - stop
            if distance <= 0:
                return {"valid": False}
            tps = [entry + distance * 1.4, entry + distance * 2.3, entry + distance * 3.4]
        else:
            stop = entry + 1.6 * atr
            if swing_level is not None and float(swing_level) > entry:
                stop = max(stop, float(swing_level) + 0.15 * atr)
            distance = stop - entry
            if distance <= 0:
                return {"valid": False}
            tps = [entry - distance * 1.4, entry - distance * 2.3, entry - distance * 3.4]

        risk_cash = self.capital * self.risk_per_trade
        qty = risk_cash / distance
        notional = qty * entry
        return {
            "valid": True,
            "stop_loss": stop,
            "risk_pct": (distance / entry) * 100,
            "notional": notional,
            "take_profits": tps,
        }

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m,
                                 asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0,
            take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="لا تصلح للتداول حالياً (شروط السيولة والهيكل غير متوفرة)",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_15m)
            if drop_last_candle and len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 60:
                return "NEUTRAL", 0.0, neutral

            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)
            price = float(df["close"].iloc[-1])
            atr = float(df["ATR"].iloc[-1])
            rsi = float(df["RSI"].iloc[-1])

            if price <= 0 or atr <= 0 or not np.isfinite([price, atr, rsi]).all():
                return "NEUTRAL", 0.0, neutral

            fvg = self.detect_fair_value_gap(df)
            sweep = self.detect_liquidity_sweep(df)
            bos = self.detect_market_structure_break(df)
            volume_ok, volume_ratio = self.detect_volume(df)

            long_triggers = []
            if fvg["bullish_fvg"]: long_triggers.append("Bullish_FVG")
            if sweep["sweep_low"]: long_triggers.append("Liquidity_Sweep_Low")
            if bos["bos_bullish"]: long_triggers.append("BOS_Bullish")

            short_triggers = []
            if fvg["bearish_fvg"]: short_triggers.append("Bearish_FVG")
            if sweep["sweep_high"]: long_triggers.append("Liquidity_Sweep_High")
            if bos["bos_bearish"]: short_triggers.append("BOS_Bearish")

            direction = "NEUTRAL"
            triggers = []
            score = 50

            if len(long_triggers) >= 2 or (bos["bos_bullish"] and volume_ok):
                direction = "LONG"
                triggers = long_triggers
                score = 78
            elif len(short_triggers) >= 2 or (bos["bos_bearish"] and volume_ok):
                direction = "SHORT"
                triggers = short_triggers
                score = 78

            entry = price
            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

            if direction in ("LONG", "SHORT") and score >= self.min_score:
                swing = float(df["low"].iloc[-10:].min()) if direction == "LONG" else float(df["high"].iloc[-10:].max())
                risk = self.calculate_risk_management(direction, entry, atr, swing)
                
                if risk.get("valid"):
                    signal = build_signal(
                        direction=direction,
                        entry=round(entry, decimals),
                        stop_loss=round(risk["stop_loss"], decimals),
                        take_profits=[round(tp, decimals) for tp in risk["take_profits"]],
                        score=score,
                        rsi=rsi,
                        atr=atr,
                        reason=f"يصلح للتداول | تحليل SMC + ICT ({direction}): " + " + ".join(triggers),
                        details={"triggers": triggers, "status": "يصلح"},
                    )
                    return direction, entry, signal

            neutral["score"] = score
            neutral["rsi"] = rsi
            neutral["atr"] = atr
            neutral["reason"] = "لا تصلح للتداول حالياً (بانتظار اكتمال نموذج الهيكل أو السيولة)"
            return "NEUTRAL", price, neutral

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral
