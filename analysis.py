# ============================================================
# analysis.py — StrategyEngine V75.7 (Momentum & SMC Optimized)
# LONG ONLY | Flexible Divergence + BOS + Momentum Entry
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900  # 15 minutes
MIN_SCORE_DEFAULT = 65       # تخفيض بسيط لسرعة التقاط العملات الصاعدة القوية


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
        if not signal["take_profits"] or any(
            tp <= signal["entry"] for tp in signal["take_profits"]
        ):
            return False, "all TPs must be > entry for LONG"
    if is_signal_expired(signal):
        return False, "signal expired"
    return True, "ok"


class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01, min_score=MIN_SCORE_DEFAULT):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
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
        return out.fillna(50)

    def calculate_atr(self, df, period=14):
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat(
            [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
            axis=1
        ).max(axis=1)
        fallback = max(float(c.iloc[-1]) * 0.015, 1e-12)
        return tr.ewm(alpha=1.0 / period, min_periods=period,
                      adjust=False).mean().fillna(fallback)

    def prepare_dataframe(self, candles):
        df = pd.DataFrame(candles, columns=[
            "timestamp", "open", "high", "low", "close", "volume"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan).dropna()
        df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def find_swing_lows(self, low_series, order=3):
        vals = np.asarray(low_series, dtype=float)
        out = []
        for i in range(order, len(vals) - order):
            w = vals[i - order:i + order + 1]
            if vals[i] == np.min(w) and np.sum(w == vals[i]) == 1:
                out.append(i)
        return out

    def detect_divergence(self, df):
        lows = self.find_swing_lows(df["low"], self.swing_order)
        result = {
            "regular": False, "hidden": False,
            "price_previous": 0.0, "price_recent": 0.0,
            "rsi_previous": 50.0, "rsi_recent": 50.0,
        }
        if len(lows) < 2:
            return result
        p, r = lows[-2], lows[-1]
        if r - p > 35 or len(df) - 1 - r > 15:
            return result
        pp, pr = float(df["low"].iloc[p]), float(df["low"].iloc[r])
        rp, rr = float(df["RSI"].iloc[p]), float(df["RSI"].iloc[r])
        
        result.update({
            "regular": bool(pr < pp * 1.002 and rr > rp + 1.5 and rr < 70),
            "hidden": bool(pr > pp * 0.998 and rr < rp - 1.5 and rr > 25),
            "price_previous": pp, "price_recent": pr,
            "rsi_previous": rp, "rsi_recent": rr,
        })
        return result

    def detect_sweep(self, df):
        if len(df) < 15:
            return False
        reference_low = float(df["low"].iloc[-12:-4].min())
        recent = df.iloc[-4:]
        swept = bool((recent["low"] < reference_low).any())
        closed_above = bool(float(df["close"].iloc[-1]) > reference_low)
        return swept and closed_above

    def detect_bullish_structure(self, df):
        if len(df) < 12:
            return False
        prior_high = float(df["high"].iloc[-8:-1].max())
        return bool(float(df["close"].iloc[-1]) > prior_high)

    def detect_volume(self, df):
        if len(df) < 22:
            return False, 0.0
        avg = float(df["volume"].iloc[-21:-1].mean())
        current = float(df["volume"].iloc[-1])
        ratio = current / avg if avg > 0 else 0.0
        return bool(ratio >= 1.1), round(ratio, 2)

    def confirm_5m(self, candles, drop_last_candle=True):
        if candles is None or len(candles) < 25:
            return False, 50.0
        df = self.prepare_dataframe(candles)
        if drop_last_candle and len(df) > 1:
            df = df.iloc[:-1].reset_index(drop=True)
        if len(df) < 20:
            return False, 50.0
        rsi = self.calculate_rsi(df["close"])
        last, prev = df.iloc[-1], df.iloc[-2]
        ok = bool(
            last["close"] > last["open"]
            and last["close"] >= prev["close"]
            and 30 <= float(rsi.iloc[-1]) <= 80
        )
        return ok, float(rsi.iloc[-1])

    def calculate_score(self, regular, hidden, sweep, structure, rsi,
                        volume_ok, candle_ok, trend_ok):
        score = 30 if regular else (20 if hidden else 10)
        score += 15 if sweep else 0
        score += 20 if structure else 0
        score += 15 if 35 <= rsi <= 65 else 10
        score += 10 if volume_ok else 0
        score += 10 if candle_ok else 0
        score += 5 if trend_ok else 0
        return min(100, max(15, score))

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
        min_distance = entry * 0.002
        if distance < min_distance:
            return {"valid": False, "reason": "distance too small"}
        if pct > 0.09:
            return {"valid": False, "reason": "stop too far"}

        risk_cash = self.capital * self.risk_per_trade
        qty = risk_cash / distance
        notional = qty * entry
        if notional < exchange_min_notional:
            return {"valid": False, "reason": "notional < min"}

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
            price = float(df["close"].iloc[-1])
            atr = float(df["ATR"].iloc[-1])
            rsi = float(df["RSI"].iloc[-1])

            if price <= 0 or atr <= 0 or not np.isfinite([price, atr, rsi]).all():
                neutral["reason"] = "invalid computed indicators"
                return "NEUTRAL", 0.0, neutral

            div = self.detect_divergence(df)
            regular, hidden = div["regular"], div["hidden"]
            sweep = self.detect_sweep(df)
            structure = self.detect_bullish_structure(df)
            volume_ok, volume_ratio = self.detect_volume(df)
            candle_ok, rsi_5m = self.confirm_5m(
                ohlcv_5m, drop_last_candle=drop_last_candle
            )

            ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(df["close"].ewm(span=50, adjust=False).mean().iloc[-1])
            trend_ok = price > ema20 or ema20 > ema50

            score = self.calculate_score(
                regular, hidden, sweep, structure, rsi,
                volume_ok, candle_ok, trend_ok,
            )

            # تعديل الذكاء هنا: للعملات الصاعدة والقوية، الدخول يكون قريب جداً من السعر الحالي (Market / Aggressive Entry) لضمان عدم تفويت الفرصة
            conditional_target = round(price, 8) if (volume_ok or structure or regular) else round(price * 0.995, 8)

            reasons = []
            if score < self.min_score:
                reasons.append("score below threshold")
            
            # مرونة عالية في القبول (تفعيل الصفقة لو تحققت أي إشارة قوية من الدايفرجنس، الهيكل، أو السيولة مع الزخم)
            has_trigger = bool(regular or structure or sweep or hidden)
            if not has_trigger:
                reasons.append("no bullish trigger (divergence/BOS/sweep)")

            valid = bool(score >= self.min_score and has_trigger)

            risk = {}
            if valid:
                risk = self.calculate_risk_management(
                    conditional_target, atr, div["price_recent"]
                )
                if not risk.get("valid"):
                    # لو الستوب بعيد أو مش مضبوط، نعدله تلقائياً بناءً على الـ ATR الحالي
                    fallback_stop = conditional_target - (1.5 * atr)
                    fallback_dist = conditional_target - fallback_stop
                    risk = {
                        "valid": True,
                        "stop_loss": fallback_stop,
                        "risk_pct": (fallback_dist / conditional_target) * 100,
                        "risk_amount": self.capital * self.risk_per_trade,
                        "position_size": (self.capital * self.risk_per_trade) / fallback_dist,
                        "notional": ((self.capital * self.risk_per_trade) / fallback_dist) * conditional_target,
                        "take_profits": [
                            conditional_target + fallback_dist * 1.5,
                            conditional_target + fallback_dist * 2.5,
                            conditional_target + fallback_dist * 3.5,
                        ]
                    }

            decimals = 8 if price < 0.1 else (
                6 if price < 1 else (4 if price < 100 else 2)
            )

            if valid:
                tp_list = [round(tp, decimals) for tp in risk["take_profits"]]
                signal = build_signal(
                    direction="LONG",
                    entry=round(conditional_target, decimals),
                    stop_loss=round(risk["stop_loss"], decimals),
                    take_profits=tp_list,
                    score=score,
                    rsi=rsi,
                    atr=atr,
                    reason="High Momentum / SMC Long Setup Confirmed",
                    details={
                        "trigger_price": round(price, decimals),
                        "conditional_target": round(conditional_target, decimals),
                        "volume_ratio": volume_ratio,
                        "rsi_5m": round(rsi_5m, 2),
                        "risk_pct": round(risk["risk_pct"], 3),
                        "notional": round(risk["notional"], 2),
                        "entry_zone": {
                            "regular_bullish": regular,
                            "hidden_bullish": hidden,
                            "liquidity_sweep": sweep,
                            "bullish_structure": structure,
                            "volume_confirmed": volume_ok,
                            "confirmed_5m": candle_ok,
                        },
                    },
                )
                return "LONG", conditional_target, signal

            neutral["score"] = score
            neutral["rsi"] = rsi
            neutral["atr"] = atr
            neutral["reason"] = " | ".join(reasons) if reasons else "conditions not met"
            neutral["details"] = {
                "trigger_price": round(price, decimals),
                "conditional_target": round(conditional_target, decimals),
                "volume_ratio": volume_ratio,
            }
            return "NEUTRAL", price, neutral

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = "exception: {}".format(exc)
            return "NEUTRAL", 0.0, neutral
