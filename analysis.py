# ============================================================
# analysis.py — StrategyEngine V125.2 Stage-Protected + Momentum
# Multi-Market: Crypto + Stocks/ETFs + Forex + Metals
# Signal-only: LONG / SHORT + Symbol Momentum Fade + Guard Alerts.
# ============================================================

import logging
import uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400
MIN_SCORE_DEFAULT = 82


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_signal_id():
    return uuid.uuid4().hex[:16]


def build_signal(direction, entry_low, entry_high, stop_loss, take_profits,
                 score, rsi, atr, reason, details=None):
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
    """Stage-protected pullback & momentum-confirmed signal engine.

    Combines:
    1. Stage-protected pullback setups with clean-path PoC filter and 1.0R/1.8R/3.0R targets.
    2. Controlled momentum breakout/breakdown setups after BOS/MSS with strict RSI caps and 0.85R TP1.
    3. Coin-specific momentum-fade checks for both LONG and SHORT.
    4. Open-position evaluator for Break-Even, profit protection, TP hits, momentum shifts, and stop hits.
    """

    def __init__(self, capital=10000.0, risk_per_trade=0.01,
                 min_score=MIN_SCORE_DEFAULT):
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
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return (100 - (100 / (1 + rs))).replace([np.inf, -np.inf], np.nan).fillna(50)

    def calculate_atr(self, df, period=14):
        h = pd.to_numeric(df["high"], errors="coerce")
        l = pd.to_numeric(df["low"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().replace([np.inf, -np.inf], np.nan).fillna(0)

    def calculate_ema(self, series, period):
        return pd.to_numeric(series, errors="coerce").ewm(span=period, adjust=False, min_periods=period).mean()

    def calculate_adx(self, df, period=14):
        try:
            h = pd.to_numeric(df["high"], errors="coerce")
            l = pd.to_numeric(df["low"], errors="coerce")
            c = pd.to_numeric(df["close"], errors="coerce")
            plus_dm_raw = h.diff()
            minus_dm_raw = l.diff()
            plus_dm = pd.Series(
                np.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), plus_dm_raw, 0.0),
                index=df.index,
            )
            minus_dm = pd.Series(
                np.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), minus_dm_raw, 0.0),
                index=df.index,
            )
            tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
            minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
            adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            return adx.replace([np.inf, -np.inf], np.nan).fillna(25.0)
        except Exception:
            return pd.Series([25.0] * len(df), index=df.index)

    def calculate_macd(self, series, fast=12, slow=26, signal=9):
        s = pd.to_numeric(series, errors="coerce")
        exp1 = s.ewm(span=fast, adjust=False).mean()
        exp2 = s.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def calculate_fib_and_poc(self, df, direction, lookback=40):
        try:
            sub = df.tail(lookback)
            hi = float(sub["high"].max())
            lo = float(sub["low"].min())
            rng = max(hi - lo, 1e-9)
            if direction == "LONG":
                fib_382 = hi - 0.382 * rng
                fib_500 = hi - 0.500 * rng
                fib_618 = hi - 0.618 * rng
            else:
                fib_382 = lo + 0.382 * rng
                fib_500 = lo + 0.500 * rng
                fib_618 = lo + 0.618 * rng

            bins = 24
            edges = np.linspace(lo, hi, bins + 1)
            vol_profile = np.zeros(bins, dtype=float)
            closes = sub["close"].to_numpy(dtype=float)
            vols = sub["volume"].to_numpy(dtype=float)
            for c_val, v_val in zip(closes, vols):
                idx = min(bins - 1, max(0, int(np.searchsorted(edges, c_val, side="right") - 1)))
                vol_profile[idx] += max(0.0, float(v_val))
            poc_idx = int(np.argmax(vol_profile))
            poc_price = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

            return {
                "fib_382": fib_382,
                "fib_500": fib_500,
                "fib_618": fib_618,
                "poc": poc_price,
                "range_high": hi,
                "range_low": lo,
            }
        except Exception:
            return {"fib_382": 0.0, "fib_500": 0.0, "fib_618": 0.0, "poc": 0.0}

    def has_engulfing(self, df, direction):
        try:
            if len(df) < 2:
                return False
            prev_o = float(df["open"].iloc[-2])
            prev_c = float(df["close"].iloc[-2])
            curr_o = float(df["open"].iloc[-1])
            curr_c = float(df["close"].iloc[-1])
            if direction == "LONG":
                return prev_c < prev_o and curr_c > curr_o and curr_c >= prev_o and curr_o <= prev_c
            return prev_c > prev_o and curr_c < curr_o and curr_c <= prev_o and curr_o >= prev_c
        except Exception:
            return False

    def has_close_confirmation(self, df, direction):
        try:
            if df is None or len(df) < 3:
                return {"ok": False, "score": 0, "body_ratio": 0.0, "reason": "Insufficient candles"}
            c_last = float(df["close"].iloc[-1])
            o_last = float(df["open"].iloc[-1])
            h_last = float(df["high"].iloc[-1])
            l_last = float(df["low"].iloc[-1])
            c_prev = float(df["close"].iloc[-2])
            rng_last = max(h_last - l_last, 1e-9)
            body_last = abs(c_last - o_last)
            body_ratio = body_last / rng_last

            if direction == "LONG":
                bull_close = c_last > o_last and c_last >= c_prev and body_ratio >= 0.42
                strong_body = body_ratio >= 0.58
                score = (10 if bull_close else 0) + (5 if strong_body else 0)
                return {
                    "ok": bull_close,
                    "score": score,
                    "body_ratio": round(body_ratio, 2),
                    "reason": "Strong bullish close confirmed" if bull_close else "Weak/wick-heavy candle close",
                }
            else:
                bear_close = c_last < o_last and c_last <= c_prev and body_ratio >= 0.42
                strong_body = body_ratio >= 0.58
                score = (10 if bear_close else 0) + (5 if strong_body else 0)
                return {
                    "ok": bear_close,
                    "score": score,
                    "body_ratio": round(body_ratio, 2),
                    "reason": "Strong bearish close confirmed" if bear_close else "Weak/wick-heavy candle close",
                }
        except Exception:
            return {"ok": False, "score": 0, "body_ratio": 0.0, "reason": "Close check error"}

    def prepare_dataframe(self, candles):
        if candles is None or len(candles) == 0:
            return pd.DataFrame()
        try:
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            return df
        except Exception as exc:
            logger.error("prepare_dataframe error: %s", exc)
            return pd.DataFrame()

    def _swings(self, df, left=2, right=2):
        if len(df) < left + right + 5:
            return [], []
        highs, lows = [], []
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        last_confirmed = len(df) - right - 1
        for i in range(left, last_confirmed + 1):
            if h[i] >= np.max(h[i-left:i+right+1]) and h[i] > np.max(h[i-left:i]):
                highs.append((i, h[i]))
            if l[i] <= np.min(l[i-left:i+right+1]) and l[i] < np.min(l[i-left:i]):
                lows.append((i, l[i]))
        return highs, lows

    def _structure(self, df, direction):
        highs, lows = self._swings(df)
        close = float(df["close"].iloc[-1])
        if len(highs) < 2 or len(lows) < 2:
            return {"ok": False, "score": 0, "bos": False, "mss": False, "sweep": False,
                    "swing_high": float(df["high"].tail(20).max()),
                    "swing_low": float(df["low"].tail(20).min()), "reason": "Swing structure insufficient"}

        prev_h, last_h = highs[-2][1], highs[-1][1]
        prev_l, last_l = lows[-2][1], lows[-1][1]
        recent = df.tail(8)
        sweep = False
        bos = False
        mss = False

        if direction == "LONG":
            higher_structure = last_h >= prev_h and last_l >= prev_l * 0.996
            bos = close > prev_h or close > last_h
            sweep = float(recent["low"].min()) < prev_l and close > prev_l
            mss = sweep and close > float(recent["high"].iloc[:-1].max()) if len(recent) > 2 else False
            score = (16 if higher_structure else 0) + (12 if bos else 0) + (12 if sweep else 0) + (8 if mss else 0)
            ok = (higher_structure and (bos or sweep)) or mss
            reason = []
            if higher_structure: reason.append("Higher-High/Higher-Low")
            if bos: reason.append("Bullish BOS")
            if sweep: reason.append("Liquidity sweep below swing")
            if mss: reason.append("Bullish MSS")
        else:
            lower_structure = last_h <= prev_h * 1.004 and last_l <= prev_l
            bos = close < prev_l or close < last_l
            sweep = float(recent["high"].max()) > prev_h and close < prev_h
            mss = sweep and close < float(recent["low"].iloc[:-1].min()) if len(recent) > 2 else False
            score = (16 if lower_structure else 0) + (12 if bos else 0) + (12 if sweep else 0) + (8 if mss else 0)
            ok = (lower_structure and (bos or sweep)) or mss
            reason = []
            if lower_structure: reason.append("Lower-High/Lower-Low")
            if bos: reason.append("Bearish BOS")
            if sweep: reason.append("Liquidity sweep above swing")
            if mss: reason.append("Bearish MSS")

        return {"ok": ok, "score": min(48, score), "bos": bos, "mss": mss, "sweep": sweep,
                "swing_high": last_h, "swing_low": last_l,
                "reason": "، ".join(reason) if reason else "No clean structure confirmation"}

    def _bias(self, df, direction):
        if len(df) < 60:
            return {"ok": False, "score": 0, "rsi": 50, "reason": "Bias data insufficient"}
        close = float(df["close"].iloc[-1])
        e20 = float(self.calculate_ema(df["close"], 20).iloc[-1])
        e50 = float(self.calculate_ema(df["close"], 50).iloc[-1])
        ema200_series = self.calculate_ema(df["close"], 200) if len(df) >= 200 else pd.Series([np.nan])
        ema200 = float(ema200_series.iloc[-1]) if not ema200_series.empty and pd.notna(ema200_series.iloc[-1]) else 0.0
        atr_d = float(self.calculate_atr(df).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])

        adx_series = self.calculate_adx(df)
        adx = float(adx_series.iloc[-1]) if not adx_series.empty else 25.0
        _, _, macd_hist = self.calculate_macd(df["close"])
        hist_val = float(macd_hist.iloc[-1]) if not macd_hist.empty else 0.0

        reasons = []
        score = 0
        ema200_support = False

        if direction == "LONG":
            trend_ok = close >= e20 * 0.996 and e20 >= e50 * 0.996 and adx >= 22
            momentum_ok = hist_val > 0
            if close >= e20 * 0.996: score += 9
            if e20 >= e50 * 0.996: score += 9
            if ema200 > 0:
                if close >= ema200:
                    score += 6
                    if abs(close - ema200) <= max(atr_d * 1.5, close * 0.015):
                        ema200_support = True
                        score += 5
                        reasons.append("Daily EMA200 support bounce")
                    else:
                        reasons.append("Above Daily EMA200")
                else:
                    score -= 10
                    reasons.append("Below Daily EMA200")
            if adx >= 24:
                score += 10; reasons.append(f"Strong Trend ADX({adx:.1f})")
            elif adx >= 22:
                score += 6; reasons.append(f"Moderate Trend ADX({adx:.1f})")
            else:
                trend_ok = False; reasons.append(f"Weak Sideways ADX({adx:.1f})")
            if hist_val > 0:
                score += 8; reasons.append("MACD Bullish Momentum")
            else:
                score -= 8; reasons.append("MACD Momentum weak/negative")
            if 42 <= rsi <= 68: score += 5
            ok = trend_ok and momentum_ok
        else:
            trend_ok = close <= e20 * 1.004 and e20 <= e50 * 1.004 and adx >= 22
            momentum_ok = hist_val < 0
            if close <= e20 * 1.004: score += 9
            if e20 <= e50 * 1.004: score += 9
            if ema200 > 0:
                if close <= ema200:
                    score += 6
                    if abs(close - ema200) <= max(atr_d * 1.5, close * 0.015):
                        ema200_support = True
                        score += 5
                        reasons.append("Daily EMA200 resistance rejection")
                    else:
                        reasons.append("Below Daily EMA200")
                else:
                    score -= 10
                    reasons.append("Above Daily EMA200")
            if adx >= 24:
                score += 10; reasons.append(f"Strong Trend ADX({adx:.1f})")
            elif adx >= 22:
                score += 6; reasons.append(f"Moderate Trend ADX({adx:.1f})")
            else:
                trend_ok = False; reasons.append(f"Weak Sideways ADX({adx:.1f})")
            if hist_val < 0:
                score += 8; reasons.append("MACD Bearish Momentum")
            else:
                score -= 8; reasons.append("MACD Momentum weak/positive")
            if 32 <= rsi <= 58: score += 5
            ok = trend_ok and momentum_ok

        return {"ok": ok, "score": score, "rsi": rsi, "adx": adx, "ema20": e20, "ema50": e50,
                "ema200": ema200, "ema200_confluence": ema200_support,
                "reason": "، ".join(reasons) if reasons else "Bias conflict"}

    def _value_entry(self, df, direction):
        if len(df) < 30:
            return {"ok": False, "score": 0, "rsi": 50, "atr": 0, "position": 0.5,
                    "extension": 0, "reason": "Entry timeframe insufficient"}
        atr = float(self.calculate_atr(df).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        close = float(df["close"].iloc[-1])
        hi = float(df["high"].tail(40).max())
        lo = float(df["low"].tail(40).min())
        rng = max(hi - lo, atr, close * 1e-9)
        position = (close - lo) / rng
        ema20 = float(self.calculate_ema(df["close"], 20).iloc[-1])
        extension = abs(close - ema20) / max(atr, close * 1e-9)
        _, _, h1_macd_hist = self.calculate_macd(df["close"])
        h1_hist = float(h1_macd_hist.iloc[-1]) if not h1_macd_hist.empty else 0.0
        h1_hist_prev = float(h1_macd_hist.iloc[-2]) if len(h1_macd_hist) >= 2 else h1_hist
        score = 0
        reasons = []
        momentum_aligned = True

        if direction == "LONG":
            if 0.25 <= position <= 0.55:
                score += 16; reasons.append("Discount/value zone")
            elif 0.55 < position <= 0.62:
                score += 7; reasons.append("Moderate value zone")
            else:
                score -= 18; reasons.append("Premium/late location")
            if 42 <= rsi <= 63:
                score += 12; reasons.append("RSI supports controlled entry")
            elif rsi > 70:
                score -= 22; reasons.append("Overbought")
            if h1_hist < 0:
                momentum_aligned = False
                score -= 12; reasons.append("1H counter-momentum")
            if h1_hist < h1_hist_prev and h1_hist < 0:
                momentum_aligned = False
                score -= 10; reasons.append("1H momentum fading")
            if extension <= 1.6:
                score += 9; reasons.append("Not overextended from EMA20")
            elif extension > 2.4:
                score -= 20; reasons.append("Extended from EMA20")
        else:
            if 0.45 <= position <= 0.75:
                score += 16; reasons.append("Premium/value zone")
            elif 0.38 <= position < 0.45:
                score += 7; reasons.append("Moderate value zone")
            else:
                score -= 18; reasons.append("Discount/late location")
            if 37 <= rsi <= 58:
                score += 12; reasons.append("RSI supports controlled short")
            elif rsi < 30:
                score -= 22; reasons.append("Oversold")
            if h1_hist > 0:
                momentum_aligned = False
                score -= 12; reasons.append("1H counter-momentum")
            if h1_hist > h1_hist_prev and h1_hist > 0:
                momentum_aligned = False
                score -= 10; reasons.append("1H bearish momentum fading")
            if extension <= 1.6:
                score += 9; reasons.append("Not overextended from EMA20")
            elif extension > 2.4:
                score -= 20; reasons.append("Extended from EMA20")

        fib_poc = self.calculate_fib_and_poc(df, direction, lookback=40)
        fib_mid = fib_poc.get("fib_500", 0.0)
        poc_val = fib_poc.get("poc", 0.0)
        tol = max(atr * 0.85, close * 0.004)
        fib_hit = fib_mid > 0 and abs(close - fib_mid) <= tol
        poc_hit = poc_val > 0 and abs(close - poc_val) <= tol
        engulf = self.has_engulfing(df, direction)
        close_conf = self.has_close_confirmation(df, direction)

        if fib_hit:
            score += 7; reasons.append("Fib 50% confluence")
        if poc_hit:
            score += 6; reasons.append("Volume PoC confluence")
        if engulf:
            score += 7; reasons.append("Engulfing candle")
        if close_conf.get("ok"):
            score += close_conf.get("score", 0); reasons.append("1H close confirmed")
        else:
            score -= 8; reasons.append("Weak 1H close")

        look = df.tail(12)
        move = (float(look["close"].iloc[-1]) - float(look["close"].iloc[0])) / max(float(look["close"].iloc[0]), 1e-9) * 100
        if abs(move) > 8.5:
            score -= 18; reasons.append("Recent 12-bar impulse strong")

        vmean = float(df["volume"].tail(20).mean())
        vlast = float(df["volume"].iloc[-1])
        if vmean > 0 and vlast >= vmean * 1.15:
            score += 6; reasons.append("Volume confirmation")

        return {"ok": (score >= 24) and momentum_aligned, "score": max(-20, score), "rsi": rsi, "atr": atr,
                "position": position, "extension": extension, "move12": move,
                "range_high": hi, "range_low": lo,
                "fib_poc": fib_poc, "engulfing": engulf, "close_confirmed": close_conf.get("ok", False),
                "reason": "، ".join(reasons)}

    def _entry_confirmation(self, df, direction):
        if df is None or len(df) < 20:
            return {"ok": True, "score": 0, "close_confirmed": False, "reason": "15M unavailable"}
        close = float(df["close"].iloc[-1])
        op = float(df["open"].iloc[-1])
        hi = float(df["high"].iloc[-1])
        lo = float(df["low"].iloc[-1])
        atr = float(self.calculate_atr(df).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        prev_hi = float(df["high"].tail(8).iloc[:-1].max())
        prev_lo = float(df["low"].tail(8).iloc[:-1].min())
        close_conf = self.has_close_confirmation(df, direction)
        score = 0
        reasons = []
        if direction == "LONG":
            if close > op: score += 6; reasons.append("15M bullish close")
            if lo < prev_lo and close > prev_lo: score += 10; reasons.append("15M sell-side sweep/reclaim")
            if close > prev_hi: score += 8; reasons.append("15M micro BOS")
            if self.has_engulfing(df, "LONG"): score += 6; reasons.append("15M bullish engulfing")
            if close_conf.get("ok"): score += 8; reasons.append("15M close confirmed")
            if 42 <= rsi <= 65: score += 5; reasons.append("15M RSI controlled")
        else:
            if close < op: score += 6; reasons.append("15M bearish close")
            if hi > prev_hi and close < prev_hi: score += 10; reasons.append("15M buy-side sweep/reclaim")
            if close < prev_lo: score += 8; reasons.append("15M micro BOS")
            if self.has_engulfing(df, "SHORT"): score += 6; reasons.append("15M bearish engulfing")
            if close_conf.get("ok"): score += 8; reasons.append("15M close confirmed")
            if 35 <= rsi <= 58: score += 5; reasons.append("15M RSI controlled")
        body = abs(close - op)
        if atr > 0 and body > 1.7 * atr:
            score -= 16; reasons.append("15M candle extended")
        ok_15m = close_conf.get("ok", False) and (score >= 16)
        return {"ok": ok_15m, "score": score, "atr": atr, "rsi": rsi,
                "close_confirmed": close_conf.get("ok", False),
                "reason": "، ".join(reasons) if reasons else "15M confirmation weak"}

    def _anti_exhaustion_filter(self, df1h, df15m, direction):
        try:
            if df1h is None or len(df1h) < 15:
                return True, "OK"

            rsi_1h = float(self.calculate_rsi(df1h["close"]).iloc[-1])
            close_1h = float(df1h["close"].iloc[-1])
            low_1h_recent = float(df1h["low"].tail(6).min())
            high_1h_recent = float(df1h["high"].tail(6).max())

            rsi_15m = float(self.calculate_rsi(df15m["close"]).iloc[-1]) if (df15m is not None and len(df15m) >= 15) else 50.0
            m15_bouncing = False
            m15_pulling_back = False

            if df15m is not None and len(df15m) >= 4:
                c1 = float(df15m["close"].iloc[-1])
                o1 = float(df15m["open"].iloc[-1])
                c2 = float(df15m["close"].iloc[-2])
                o2 = float(df15m["open"].iloc[-2])
                m15_bouncing = (c1 > o1 and c2 > o2) or (rsi_15m > 42 and c1 > c2)
                m15_pulling_back = (c1 < o1 and c2 < o2) or (rsi_15m < 58 and c1 < c2)

            if direction == "SHORT":
                if rsi_1h < 35 or rsi_15m < 32:
                    return False, "Oversold exhaustion on 1H/15M"
                if m15_bouncing and rsi_15m > 36:
                    return False, "Active 15M bounce against SHORT"
                if low_1h_recent > 0 and ((close_1h - low_1h_recent) / close_1h) < 0.006:
                    return False, "Too close to recent 1H support"
            else:
                if rsi_1h > 67 or rsi_15m > 70:
                    return False, "Overbought exhaustion on 1H/15M"
                if m15_pulling_back and rsi_15m < 64:
                    return False, "Active 15M pullback against LONG"
                if high_1h_recent > 0 and ((high_1h_recent - close_1h) / close_1h) < 0.006:
                    return False, "Too close to recent 1H resistance"

            return True, "Timing clean"
        except Exception:
            return True, "OK"

    def _clean_path_to_tp1(self, direction, entry_price, tp1, fib_poc, atr):
        """Rejects setups where an opposing PoC sits too close between entry and TP1."""
        poc = float((fib_poc or {}).get("poc", 0.0))
        if poc <= 0 or atr <= 0:
            return True
        if direction == "SHORT":
            if tp1 < poc < entry_price and (entry_price - poc) < max(0.8 * atr, 0.015 * entry_price):
                return False
        else:
            if entry_price < poc < tp1 and (poc - entry_price) < max(0.8 * atr, 0.015 * entry_price):
                return False
        return True

    def _trade_plan(self, df1h, entry_price, atr, direction, structure):
        if entry_price <= 0 or atr <= 0:
            return None
        swing_low = float(structure.get("swing_low", df1h["low"].tail(20).min()))
        swing_high = float(structure.get("swing_high", df1h["high"].tail(20).max()))
        if direction == "LONG":
            structural = swing_low - 0.7 * atr
            atr_stop = entry_price - 2.0 * atr
            stop = min(structural, atr_stop)
            risk = entry_price - stop
            if risk <= 0:
                return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 4.5:
                return None
            if risk_pct < 0.8:
                stop = entry_price - 1.6 * atr
                risk = entry_price - stop
            entry_low = max(0.0, entry_price - 0.10 * atr)
            entry_high = entry_price + 0.05 * atr
            tps = [entry_price + 1.0 * risk, entry_price + 1.8 * risk, entry_price + 3.0 * risk]
        else:
            structural = swing_high + 0.7 * atr
            atr_stop = entry_price + 2.0 * atr
            stop = max(structural, atr_stop)
            risk = stop - entry_price
            if risk <= 0:
                return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 4.5:
                return None
            if risk_pct < 0.8:
                stop = entry_price + 1.6 * atr
                risk = stop - entry_price
            entry_low = entry_price - 0.05 * atr
            entry_high = entry_price + 0.10 * atr
            tps = [entry_price - 1.0 * risk, entry_price - 1.8 * risk, entry_price - 3.0 * risk]

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop,
            "tp1": tps[0],
            "tp2": tps[1],
            "tp3": tps[2],
            "risk_pct": risk / entry_price * 100,
        }

    def _momentum_continuation_candidate(self, daily, h4, h1, m15, asset_type):
        """Captures clean BOS/MSS breakouts & breakdowns with strict exhaustion caps."""
        if len(daily) < 55 or len(h4) < 40 or len(h1) < 35:
            return None

        price = float(h1["close"].iloc[-1])
        atr_1h = float(self.calculate_atr(h1).iloc[-1])
        rsi_1h = float(self.calculate_rsi(h1["close"]).iloc[-1])
        rsi_15m = float(self.calculate_rsi(m15["close"]).iloc[-1]) if (m15 is not None and not m15.empty and len(m15) >= 15) else rsi_1h
        if price <= 0 or atr_1h <= 0:
            return None

        for direction in ("LONG", "SHORT"):
            bias = self._bias(daily, direction)
            struct = self._structure(h4, direction)
            if not bias["ok"] or not (struct.get("bos") or struct.get("mss")):
                continue

            close_1h = self.has_close_confirmation(h1, direction)
            if not close_1h.get("ok"):
                continue

            conf_15m = self._entry_confirmation(m15, direction) if (m15 is not None and not m15.empty) else {"ok": True, "score": 0, "close_confirmed": True, "reason": "15M N/A"}
            if m15 is not None and not m15.empty and not conf_15m.get("ok"):
                continue

            if direction == "LONG":
                if rsi_1h > 74 or rsi_15m > 76:
                    continue
                stop = max(float(struct["swing_low"]) - 0.5 * atr_1h, price - 2.2 * atr_1h)
                risk = price - stop
                risk_pct = (risk / price) * 100
                if risk <= 0 or risk_pct < 0.8 or risk_pct > 4.5:
                    continue
                tp1 = price + 0.85 * risk
                tp2 = price + 1.60 * risk
                tp3 = price + 2.60 * risk
                if not (stop < price < tp1):
                    continue
                entry_low = max(0.0, price - 0.15 * atr_1h)
                entry_high = price + 0.05 * atr_1h
            else:
                if rsi_1h < 26 or rsi_15m < 24:
                    continue
                stop = min(float(struct["swing_high"]) + 0.5 * atr_1h, price + 2.2 * atr_1h)
                risk = stop - price
                risk_pct = (risk / price) * 100
                if risk <= 0 or risk_pct < 0.8 or risk_pct > 4.5:
                    continue
                tp1 = price - 0.85 * risk
                tp2 = price - 1.60 * risk
                tp3 = price - 2.60 * risk
                if not (tp1 < price < stop):
                    continue
                entry_low = price - 0.05 * atr_1h
                entry_high = price + 0.15 * atr_1h

            fib_poc = self.calculate_fib_and_poc(h1, direction, lookback=40)
            if not self._clean_path_to_tp1(direction, price, tp1, fib_poc, atr_1h):
                continue

            score = int(round(min(100, max(self.min_score, bias["score"] + struct["score"] + close_1h["score"] + conf_15m.get("score", 0) - 4))))
            quality = "A+" if score >= 92 else "A" if score >= 85 else "B+"
            decimals = 10 if price < 0.0001 else 8 if price < 0.01 else 7 if price < 0.1 else 6 if price < 1 else 4 if price < 100 else 2
            reason = f"{direction} | V125.2 Momentum Break: 1D trend + {struct['reason']} + confirmed close"
            sig = build_signal(
                direction,
                round(entry_low, decimals),
                round(entry_high, decimals),
                round(stop, decimals),
                [round(tp1, decimals), round(tp2, decimals), round(tp3, decimals)],
                score,
                rsi_1h,
                atr_1h,
                reason,
                {
                    "quality": quality,
                    "setup_type": "MOMENTUM",
                    "timeframes": "1D + 4H + 1H + 15M" if (m15 is not None and not m15.empty) else "1D + 4H + 1H",
                    "position_in_range": 0.5,
                    "extension_atr": 0.0,
                    "move12": 0.0,
                    "structure": struct,
                    "confirmation_15m": conf_15m,
                    "fib_poc": fib_poc,
                    "engulfing": self.has_engulfing(h1, direction),
                    "close_confirmed": True,
                    "ema200": round(bias.get("ema200", 0.0), decimals),
                    "ema200_confluence": bias.get("ema200_confluence", False),
                    "risk_pct": round(risk_pct, 2),
                    "asset_type": asset_type,
                    "entry_timing": "momentum_break_confirmed",
                },
            )
            return direction, price, sig

        return None

    def check_momentum_at_tp1(self, candles1h):
        try:
            df = self.prepare_dataframe(candles1h)
            if df.empty or len(df) < 10:
                return "NEUTRAL", "بيانات غير كافية لفحص الزخم"
            rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
            mean_v = float(df["volume"].tail(10).mean())
            last_v = float(df["volume"].iloc[-1])
            if rsi > 68:
                return "OVERBOUGHT", "⚠️ RSI مرتفع؛ أمّن جزءاً من الربح وانقل الوقف للدخول."
            if rsi < 32:
                return "OVERSOLD", "⚠️ RSI منخفض في الشورت؛ أمّن جزءاً من الربح وانقل الوقف للدخول."
            if mean_v > 0 and last_v > mean_v * 1.4:
                return "STRONG", "🚀 الزخم والحجم داعمان؛ انقل الوقف للدخول وتابع الهدف التالي."
            return "NORMAL", "⚖️ الزخم مستقر؛ انقل الوقف للدخول لتفادي انعكاس الربح."
        except Exception:
            return "NORMAL", "⚖️ الزخم مستقر."

    def evaluate_open_position(self, direction, entry_price, stop_loss, take_profits,
                               current_price, candles_15m=None):
        """Monitors an active trade to emit actionable post-entry & profit-protection alerts."""
        try:
            entry = float(entry_price)
            sl = float(stop_loss)
            curr = float(current_price)
            tps = [float(x) for x in (take_profits or [])]
            tp1 = tps[0] if len(tps) > 0 else None
            tp2 = tps[1] if len(tps) > 1 else None
            tp3 = tps[2] if len(tps) > 2 else None

            m15 = self.prepare_dataframe(candles_15m)
            rsi_15m = float(self.calculate_rsi(m15["close"]).iloc[-1]) if len(m15) >= 15 else 50.0
            _, _, hist_series = self.calculate_macd(m15["close"]) if len(m15) >= 26 else (None, None, pd.Series([0.0]))
            hist_now = float(hist_series.iloc[-1]) if not hist_series.empty else 0.0
            hist_prev = float(hist_series.iloc[-2]) if len(hist_series) >= 2 else hist_now

            if direction == "LONG":
                risk = max(entry - sl, 1e-9)
                progress_r = (curr - entry) / risk
                if curr <= sl:
                    return {"action": "STOP_HIT", "message": "🛑 تم كسر وقف الخسارة؛ إغلاق الصفقة ومنع مطاردة الخسارة."}
                if tp3 is not None and curr >= tp3:
                    return {"action": "TP3_REACHED", "message": "🏆 تم الوصول إلى TP3؛ يُنصح بجني كامل الربح أو تأمين ما تبقى."}
                if tp2 is not None and curr >= tp2:
                    return {"action": "TP2_REACHED", "message": "🥈 تم الوصول إلى TP2؛ أمّن غالبية الربح وارفع الوقف فوق نقطة الدخول."}
                if tp1 is not None and curr >= tp1:
                    return {"action": "TP1_REACHED", "message": "🥇 تم الوصول إلى TP1؛ انقل الوقف لنقطة الدخول (Break-Even) فوراً."}
                if progress_r >= 0.65:
                    if rsi_15m > 70 or (hist_now < hist_prev and hist_now < 0):
                        return {"action": "PROTECT_GAIN", "message": "⚠️ الصفقة في ربح جيد والزخم بدأ يضعف؛ انقل الوقف للدخول أو احجز ربحاً."}
                    return {"action": "MOVE_TO_BE", "message": "🛡️ الصفقة اقتربت من هدفها؛ يُفضل نقل الوقف لنقطة الدخول لحماية الربح."}
            else:
                risk = max(sl - entry, 1e-9)
                progress_r = (entry - curr) / risk
                if curr >= sl:
                    return {"action": "STOP_HIT", "message": "🛑 تم كسر وقف الخسارة؛ إغلاق الصفقة ومنع مطاردة الخسارة."}
                if tp3 is not None and curr <= tp3:
                    return {"action": "TP3_REACHED", "message": "🏆 تم الوصول إلى TP3؛ يُنصح بجني كامل الربح أو تأمين ما تبقى."}
                if tp2 is not None and curr <= tp2:
                    return {"action": "TP2_REACHED", "message": "🥈 تم الوصول إلى TP2؛ أمّن غالبية الربح واخفض الوقف أسفل نقطة الدخول."}
                if tp1 is not None and curr <= tp1:
                    return {"action": "TP1_REACHED", "message": "🥇 تم الوصول إلى TP1؛ انقل الوقف لنقطة الدخول (Break-Even) فوراً."}
                if progress_r >= 0.65:
                    if rsi_15m < 30 or (hist_now > hist_prev and hist_now > 0):
                        return {"action": "PROTECT_GAIN", "message": "⚠️ صفقة الشورت في ربح جيد والزخم المعاكس بدأ يظهر؛ أمّن الربح أو انقل الوقف للدخول."}
                    return {"action": "MOVE_TO_BE", "message": "🛡️ صفقة الشورت في مسار جيد؛ يُفضل نقل الوقف لنقطة الدخول لحماية الربح."}

            return {"action": "HOLD", "message": "⏳ الصفقة ضمن المسار المحدد."}
        except Exception:
            return {"action": "HOLD", "message": "⏳ الصفقة قيد المتابعة."}

    def _make_neutral(self, reason="لا توجد فرصة مكتملة", score=0, rsi=50, atr=0, details=None):
        return build_signal("NEUTRAL", 0, 0, 0, [], score, rsi, atr, reason, details or {})

    def analyze_market_structure(self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None,
                                 asset_type="crypto", ohlcv_15m=None):
        neutral = self._make_neutral()
        try:
            daily = self.prepare_dataframe(ohlcv_daily)
            h4 = self.prepare_dataframe(ohlcv_4h)
            h1 = self.prepare_dataframe(ohlcv_1h)
            m15 = self.prepare_dataframe(ohlcv_15m)
            if len(daily) < 55 or len(h4) < 40 or len(h1) < 35:
                return "NEUTRAL", 0.0, self._make_neutral("بيانات غير كافية")

            long_d = self._bias(daily, "LONG")
            short_d = self._bias(daily, "SHORT")
            long_h4 = self._structure(h4, "LONG")
            short_h4 = self._structure(h4, "SHORT")
            long_h1 = self._value_entry(h1, "LONG")
            short_h1 = self._value_entry(h1, "SHORT")

            candidates = []
            for direction, bias, struct, value in [
                ("LONG", long_d, long_h4, long_h1),
                ("SHORT", short_d, short_h4, short_h1),
            ]:
                if not bias["ok"] or not struct["ok"] or not value["ok"]:
                    continue
                if not value.get("close_confirmed", False):
                    continue
                conf = self._entry_confirmation(m15, direction)
                if not m15.empty and not conf["ok"]:
                    continue
                score = int(round(min(100, max(0, bias["score"] + struct["score"] + value["score"] + conf["score"]))))
                if value["position"] > 0.62 if direction == "LONG" else value["position"] < 0.38:
                    continue
                if value["extension"] > 2.4 or abs(value["move12"]) > 10:
                    continue
                timing_ok, _ = self._anti_exhaustion_filter(h1, m15, direction)
                if not timing_ok:
                    continue
                if score < self.min_score:
                    continue
                price = float(h1["close"].iloc[-1])
                plan = self._trade_plan(h1, price, value["atr"], direction, struct)
                if not plan:
                    continue
                if not self._clean_path_to_tp1(direction, price, plan["tp1"], value.get("fib_poc", {}), value["atr"]):
                    continue
                if direction == "LONG" and not (plan["stop_loss"] < price < plan["tp1"]):
                    continue
                if direction == "SHORT" and not (plan["tp1"] < price < plan["stop_loss"]):
                    continue
                candidates.append((score, direction, bias, struct, value, conf, plan, price))

            if candidates:
                score, direction, bias, struct, value, conf, plan, price = max(candidates, key=lambda x: x[0])
                quality = "A+" if score >= 92 else "A" if score >= 85 else "B+"
                reason = (
                    f"{direction} | V125.2 Pullback: 1D trend + 4H structure + 1H value/PoC-clean + "
                    f"confirmed close | {struct['reason']}"
                )
                decimals = 10 if price < 0.0001 else 8 if price < 0.01 else 7 if price < 0.1 else 6 if price < 1 else 4 if price < 100 else 2
                signal = build_signal(
                    direction,
                    round(plan["entry_low"], decimals),
                    round(plan["entry_high"], decimals),
                    round(plan["stop_loss"], decimals),
                    [round(plan["tp1"], decimals), round(plan["tp2"], decimals), round(plan["tp3"], decimals)],
                    score,
                    value["rsi"], value["atr"], reason,
                    {
                        "quality": quality,
                        "setup_type": "PULLBACK",
                        "timeframes": "1D + 4H + 1H + 15M" if not m15.empty else "1D + 4H + 1H",
                        "position_in_range": round(value["position"], 3),
                        "extension_atr": round(value["extension"], 2),
                        "move12": round(value["move12"], 2),
                        "structure": struct,
                        "confirmation_15m": conf,
                        "fib_poc": value.get("fib_poc", {}),
                        "engulfing": value.get("engulfing", False),
                        "close_confirmed": value.get("close_confirmed", False),
                        "ema200": round(bias.get("ema200", 0.0), decimals),
                        "ema200_confluence": bias.get("ema200_confluence", False),
                        "risk_pct": round(plan["risk_pct"], 2),
                        "asset_type": asset_type,
                        "entry_timing": "stage_protected_confirmed",
                    },
                )
                return direction, price, signal

            mom_res = self._momentum_continuation_candidate(daily, h4, h1, m15, asset_type)
            if mom_res is not None:
                return mom_res

            diagnostics = {
                "daily_long": long_d, "daily_short": short_d,
                "4h_long": long_h4, "4h_short": short_h4,
                "1h_long": long_h1, "1h_short": short_h1,
                "15m": "available" if not m15.empty else "unavailable",
            }
            best_value = long_h1 if long_h1.get("score", -999) >= short_h1.get("score", -999) else short_h1
            return "NEUTRAL", 0.0, self._make_neutral(
                "لا توجد صفقة: الاتجاه أو منطقة الدخول أو تأكيد الإغلاق غير مكتمل",
                max(0, min(100, int(best_value.get("score", 0)))),
                best_value.get("rsi", 50), best_value.get("atr", 0), diagnostics
            )
        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral
