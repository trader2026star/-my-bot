# ============================================================
# analysis.py — StrategyEngine V78.0 (Support Bounce -> Resistance Target)
# LONG ONLY | Entry from a tested support zone, targets = resistance zones
# Interface is identical to V76/V77, so main.py's connection logic is unchanged.
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
MIN_RR_TP1 = 1.2              # first resistance must offer at least this R:R


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

    def calculate_adx(self, df, period=14):
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

    # ---------------- Support / Resistance engine ----------------
    def find_pivots(self, df, order=3):
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        pivots = []
        for i in range(order, len(df) - order):
            wh = highs[i - order:i + order + 1]
            wl = lows[i - order:i + order + 1]
            if highs[i] >= wh.max() and highs[i] > highs[i - 1]:
                pivots.append((i, float(highs[i]), "H"))
            if lows[i] <= wl.min() and lows[i] < lows[i - 1]:
                pivots.append((i, float(lows[i]), "L"))
        return pivots

    def build_zones(self, pivots, tol):
        """Cluster pivot prices (highs and lows) into S/R zones."""
        if not pivots:
            return []
        pts = sorted(pivots, key=lambda p: p[1])
        zones, cur = [], [pts[0]]

        def flush(c):
            prices = [p[1] for p in c]
            zones.append({
                "low": min(prices), "high": max(prices),
                "level": sum(prices) / len(prices),
                "touches": len(c), "last_idx": max(p[0] for p in c),
            })

        for p in pts[1:]:
            if p[1] - cur[0][1] <= tol:
                cur.append(p)
            else:
                flush(cur)
                cur = [p]
        flush(cur)
        return zones

    def detect_volume(self, df):
        if len(df) < 22:
            return False, 0.0
        avg = float(df["volume"].iloc[-21:-1].mean())
        current = float(df["volume"].iloc[-1])
        ratio = current / avg if avg > 0 else 0.0
        return bool(ratio >= 1.2), round(ratio, 2)

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
                  and 25 <= rsi_last <= 75)
        return ok, rsi_last

    def htf_trend_ok(self, ohlcv_1h):
        """1h filter for support buys: only block a clear 1h downtrend
        (close < EMA50, EMA20 < EMA50, EMA50 falling). Range or uptrend is allowed.
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
            ema50_s = close.ewm(span=50, adjust=False).mean()
            ema50, ema50_prev = float(ema50_s.iloc[-1]), float(ema50_s.iloc[-6])
            downtrend = (float(close.iloc[-1]) < ema50 and ema20 < ema50 and ema50 < ema50_prev)
            return bool(not downtrend)
        except Exception:
            return False

    # ---------------- Risk (structure-based stop) ----------------
    def calculate_risk_from_levels(self, entry, stop, exchange_min_notional=10.0):
        entry, stop = float(entry), float(stop)
        distance = entry - stop
        if entry <= 0 or distance <= 0:
            return {"valid": False, "reason": "stop >= entry"}
        pct = distance / entry
        if pct < 0.002:
            return {"valid": False, "reason": "stop distance too small"}
        if pct > 0.08:
            return {"valid": False, "reason": "support stop too far (%.1f%%)" % (pct * 100)}

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
            rsi_prev = float(df["RSI"].iloc[-2])
            ema21, ema55 = float(last["EMA21"]), float(last["EMA55"])
            adx, pdi, mdi = float(last["ADX"]), float(last["PDI"]), float(last["MDI"])

            if (price <= 0 or atr <= 0 or
                    not np.isfinite([price, atr, rsi, rsi_prev, ema21, ema55, adx, pdi, mdi]).all()):
                neutral["reason"] = "invalid computed indicators"
                return "NEUTRAL", 0.0, neutral

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            reasons = []

            # ---- General filters ----
            atr_pct = atr / price
            if atr_pct < 0.002 or atr_pct > 0.06:
                reasons.append("volatility out of range (%.2f%%)" % (atr_pct * 100))

            # ---- Build S/R zones ----
            tol = max(0.5 * atr, price * 0.0015)
            zones = self.build_zones(self.find_pivots(df, 3), tol)

            recent = df.iloc[-3:]
            recent_low = float(recent["low"].min())
            recent_close_min = float(recent["close"].min())

            cands = [z for z in zones
                     if z["touches"] >= 2
                     and z["level"] <= price
                     and price - z["high"] <= 1.2 * atr
                     and recent_low <= z["high"] + 0.2 * atr
                     and recent_close_min >= z["low"] - 0.25 * atr]
            support = (max(cands, key=lambda z: (z["touches"], -abs(price - z["level"])))
                       if cands else None)
            if support is None:
                reasons.append("no tested support zone being retested")

            # ---- Rejection / confirmation on last closed candle ----
            rng_last = max(high - low, 1e-12)
            body_last = abs(price - opn)
            bullish = price > opn
            ti = int(recent["low"].values.argmin())          # index of touch candle in `recent`
            trow = recent.iloc[ti]
            trng = max(float(trow["high"]) - float(trow["low"]), 1e-12)
            lower_wick = (min(float(trow["open"]), float(trow["close"])) - float(trow["low"])) / trng
            follow = bool(bullish and body_last >= 0.5 * rng_last and price > float(trow["high"]))
            wick_reject = bool(lower_wick >= 0.30)
            if support is not None:
                if not bullish:
                    reasons.append("last candle not bullish (no bounce confirmation)")
                elif not (wick_reject or follow):
                    reasons.append("weak rejection (no wick / follow-through)")
            if rsi >= 62:
                reasons.append("RSI too high for support entry (%.0f)" % rsi)
            elif rsi < rsi_prev:
                reasons.append("RSI still falling")

            volume_ok, volume_ratio = self.detect_volume(df)
            candle_ok, rsi_5m = self.confirm_5m(ohlcv_5m, drop_last_candle=drop_last_candle)

            # ---- Stop (below support) and targets (resistance zones) ----
            stop = None
            targets, sources, rr1 = [], [], 0.0
            res_info = []
            if support is not None and not reasons:
                stop = min(support["low"] - 0.35 * atr,
                           recent_low - 0.15 * atr,
                           price - 0.8 * atr)
                risk_dist = price - stop

                resist = sorted([z for z in zones if z["low"] > price + 0.3 * atr],
                                key=lambda z: z["level"])
                blocked = False
                for z in resist[:6]:
                    tp_price = z["low"] - 0.1 * atr
                    if tp_price <= price:
                        continue
                    rr = (tp_price - price) / risk_dist
                    if not targets and rr < MIN_RR_TP1:
                        if z["touches"] >= 2:
                            blocked = True
                            reasons.append("strong resistance too close (R:R %.2f < %.1f)" % (rr, MIN_RR_TP1))
                            break
                        continue  # weak, close resistance: ignore as a target
                    if targets and tp_price - targets[-1] < 0.5 * atr:
                        continue
                    targets.append(tp_price)
                    sources.append("resistance")
                    res_info.append({"level": round(z["level"], decimals), "touches": z["touches"]})
                    if len(targets) == 3:
                        break
                if not blocked and not targets:
                    reasons.append("no resistance target with R:R >= %.1f" % MIN_RR_TP1)
                if targets:
                    rr1 = (targets[0] - price) / risk_dist
                    if len(targets) < 2:
                        targets.append(max(price + 2.2 * risk_dist, targets[0] + 0.5 * risk_dist))
                        sources.append("R-multiple")
                    if len(targets) < 3:
                        targets.append(targets[-1] + max(targets[-1] - targets[-2], 0.8 * risk_dist))
                        sources.append("R-multiple")

            # ---- Score ----
            score = 0
            if support is not None:
                t = support["touches"]
                score += 20 if t == 2 else (28 if t == 3 else 35)
                score += 15 if lower_wick >= 0.4 else 8
                score += 15 if rr1 >= 1.5 else (8 if rr1 >= MIN_RR_TP1 else 0)
                rsi_dip = float(df["RSI"].iloc[-6:].min()) < 40
                score += 10 if (rsi_dip and rsi >= rsi_prev) else (5 if rsi < 55 else 0)
                score += 10 if volume_ok else 0
                score += 10 if candle_ok else 0
                score += 5 if ema21 > ema55 else 0
            score = int(min(100, max(0, score)))

            if support is not None and not reasons and score < self.min_score:
                reasons.append("score below threshold (%d<%d)" % (score, self.min_score))

            # ---- Risk sizing ----
            risk = {}
            if not reasons and stop is not None and len(targets) == 3:
                risk = self.calculate_risk_from_levels(price, stop)
                if not risk.get("valid"):
                    reasons.append("risk rejected: " + risk.get("reason", "unknown"))

            if not reasons and risk.get("valid"):
                max_entry = price + MAX_CHASE_R * (price - stop)
                signal = build_signal(
                    direction="LONG",
                    entry=round(price, decimals),
                    stop_loss=round(stop, decimals),
                    take_profits=[round(tp, decimals) for tp in targets],
                    score=score,
                    rsi=rsi,
                    atr=atr,
                    reason="Support Bounce -> Resistance (touches=%d, R:R TP1=%.1f)" % (
                        support["touches"], rr1),
                    details={
                        "trigger_price": round(price, decimals),
                        "max_entry": round(max_entry, decimals),
                        "volume_ratio": volume_ratio,
                        "rsi_5m": round(rsi_5m, 2),
                        "adx": round(adx, 1),
                        "risk_pct": round(risk["risk_pct"], 3),
                        "notional": round(risk["notional"], 2),
                        "triggers": ["support_bounce"],
                        "support_zone": {
                            "low": round(support["low"], decimals),
                            "high": round(support["high"], decimals),
                            "touches": support["touches"],
                        },
                        "resistances": res_info,
                        "tp_sources": sources,
                        "entry_zone": {
                            "wick_rejection": wick_reject,
                            "follow_through": follow,
                            "volume_confirmed": volume_ok,
                            "confirmed_5m": candle_ok,
                        },
                    },
                )
                return "LONG", price, signal

            neutral["score"] = score
            neutral["rsi"] = rsi
            neutral["atr"] = atr
            neutral["reason"] = " | ".join(reasons) if reasons else "conditions not met"
            neutral["details"] = {"trigger_price": round(price, decimals),
                                  "volume_ratio": volume_ratio, "adx": round(adx, 1)}
            return "NEUTRAL", price, neutral

        except Exception as exc:
            logger.exception("analysis error: %s", exc)
            neutral["reason"] = "exception: {}".format(exc)
            return "NEUTRAL", 0.0, neutral
