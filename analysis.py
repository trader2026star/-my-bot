# ============================================================
# analysis.py — StrategyEngine V131.0 High-Quality Two-Target Engine
# Multi-Market: Crypto + Stocks/ETFs + Forex + Metals
# Stricter 15M confirmation, anti-chase guard, and realistic TP1 & TP2.
# ============================================================

import logging
import uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400
MIN_SCORE_DEFAULT = 78


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
    """High-quality two-target engine focused on realistic TP1 & TP2 hits
    with stricter confirmation and anti-chase protection."""

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

    def detect_regime_state(self, df_daily, df_h4):
        try:
            if df_daily is None or len(df_daily) < 55:
                return "SIDEWAYS", 20.0
            close = float(df_daily["close"].iloc[-1])
            ema20 = float(self.calculate_ema(df_daily["close"], 20).iloc[-1])
            ema50 = float(self.calculate_ema(df_daily["close"], 50).iloc[-1])
            adx = float(self.calculate_adx(df_daily).iloc[-1])
            _, _, hist_s = self.calculate_macd(df_daily["close"])
            hist = float(hist_s.iloc[-1]) if not hist_s.empty else 0.0

            h4_adx = float(self.calculate_adx(df_h4).iloc[-1]) if (df_h4 is not None and len(df_h4) >= 20) else adx
            effective_adx = max(adx, h4_adx * 0.85)

            if effective_adx < 16.0:
                return "SIDEWAYS", effective_adx
            if close > ema20 and ema20 >= ema50 * 0.992 and hist >= 0:
                return "BULLISH", effective_adx
            if close < ema20 and ema20 <= ema50 * 1.008 and hist <= 0:
                return "BEARISH", effective_adx
            return "SIDEWAYS", effective_adx
        except Exception:
            return "SIDEWAYS", 20.0

    def _key_levels(self, h4, h1, price, atr):
        try:
            h1_sub = h1.tail(36)
            h4_sub = h4.tail(24)

            lows_1h = h1_sub["low"].to_numpy(dtype=float)
            highs_1h = h1_sub["high"].to_numpy(dtype=float)
            lows_4h = h4_sub["low"].to_numpy(dtype=float)
            highs_4h = h4_sub["high"].to_numpy(dtype=float)

            below_lows = [v for v in np.concatenate([lows_1h[-18:], lows_4h[-10:]]) if v < price]
            key_support = float(np.percentile(below_lows, 65)) if below_lows else float(price - 1.5 * atr)

            above_highs = sorted([v for v in np.concatenate([highs_1h, highs_4h]) if v > price])
            if len(above_highs) >= 2:
                res_low = float(above_highs[0])
                res_high = float(max(above_highs[min(len(above_highs) - 1, 2)], res_low + 0.6 * atr))
            elif len(above_highs) == 1:
                res_low = float(above_highs[0])
                res_high = float(res_low + 0.8 * atr)
            else:
                res_low = float(price + 1.1 * atr)
                res_high = float(price + 1.8 * atr)

            return {
                "key_support": key_support,
                "resistance_low": res_low,
                "resistance_high": res_high,
            }
        except Exception:
            return {
                "key_support": max(0.0, price - 1.5 * atr),
                "resistance_low": price + 1.1 * atr,
                "resistance_high": price + 1.8 * atr,
            }

    def calculate_fib_and_poc(self, df, direction, lookback=36):
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

            bins = 20
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
            if df is None or len(df) < 2:
                return {"ok": False, "score": 0, "body_ratio": 0.0, "reason": "Insufficient candles"}
            c_last = float(df["close"].iloc[-1])
            o_last = float(df["open"].iloc[-1])
            h_last = float(df["high"].iloc[-1])
            l_last = float(df["low"].iloc[-1])
            rng_last = max(h_last - l_last, 1e-9)
            body_last = abs(c_last - o_last)
            body_ratio = body_last / rng_last

            if direction == "LONG":
                bull_close = c_last > o_last and body_ratio >= 0.38
                strong_body = body_ratio >= 0.58
                score = (12 if bull_close else 0) + (6 if strong_body else 0)
                return {
                    "ok": bull_close,
                    "score": score,
                    "body_ratio": round(body_ratio, 2),
                    "reason": "Bullish candle close" if bull_close else "Weak bullish close",
                }
            else:
                bear_close = c_last < o_last and body_ratio >= 0.38
                strong_body = body_ratio >= 0.58
                score = (12 if bear_close else 0) + (6 if strong_body else 0)
                return {
                    "ok": bear_close,
                    "score": score,
                    "body_ratio": round(body_ratio, 2),
                    "reason": "Bearish candle close" if bear_close else "Weak bearish close",
                }
        except Exception:
            return {"ok": False, "score": 0, "body_ratio": 0.0, "reason": "Close check error"}

    def _is_dead_flat(self, df, atr):
        try:
            if df is None or len(df) < 15 or atr <= 0:
                return False
            sub = df.tail(10)
            hi = float(sub["high"].max())
            lo = float(sub["low"].min())
            return ((hi - lo) / atr) < 1.65
        except Exception:
            return False

    def _is_overextended_move(self, df, atr, direction):
        """Blocks chasing stretched moves right before a pullback."""
        try:
            if df is None or len(df) < 6 or atr <= 0:
                return False
            c_now = float(df["close"].iloc[-1])
            o_now = float(df["open"].iloc[-1])
            c_prev3 = float(df["close"].iloc[-4])
            ema20 = float(self.calculate_ema(df["close"], 20).iloc[-1])
            if direction == "LONG":
                if abs(c_now - o_now) > 2.1 * atr and c_now > o_now:
                    return True
                if (c_now - c_prev3) > 3.2 * atr or (c_now - ema20) > 2.6 * atr:
                    return True
            else:
                if abs(c_now - o_now) > 2.1 * atr and c_now < o_now:
                    return True
                if (c_prev3 - c_now) > 3.2 * atr or (ema20 - c_now) > 2.6 * atr:
                    return True
            return False
        except Exception:
            return False

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
            return {"ok": True, "score": 14, "bos": False, "mss": False, "sweep": False,
                    "swing_high": float(df["high"].tail(18).max()),
                    "swing_low": float(df["low"].tail(18).min()), "reason": "Range/swing baseline"}

        prev_h, last_h = highs[-2][1], highs[-1][1]
        prev_l, last_l = lows[-2][1], lows[-1][1]
        recent = df.tail(8)
        sweep = False
        bos = False
        mss = False

        if direction == "LONG":
            higher_structure = last_h >= prev_h * 0.995 and last_l >= prev_l * 0.99
            bos = close > prev_h or close > last_h
            sweep = float(recent["low"].min()) < prev_l and close > prev_l
            mss = sweep and close > float(recent["high"].iloc[:-1].max()) if len(recent) > 2 else False
            score = (18 if higher_structure else 0) + (14 if bos else 0) + (15 if sweep else 0) + (10 if mss else 0)
            ok = higher_structure or bos or sweep or mss
            reason = []
            if sweep: reason.append("Sell-side sweep")
            if mss: reason.append("Bullish MSS")
            if higher_structure: reason.append("HH/HL")
            if bos: reason.append("Bullish BOS")
        else:
            lower_structure = last_h <= prev_h * 1.01 and last_l <= prev_l * 1.005
            bos = close < prev_l or close < last_l
            sweep = float(recent["high"].max()) > prev_h and close < prev_h
            mss = sweep and close < float(recent["low"].iloc[:-1].min()) if len(recent) > 2 else False
            score = (18 if lower_structure else 0) + (14 if bos else 0) + (15 if sweep else 0) + (10 if mss else 0)
            ok = lower_structure or bos or sweep or mss
            reason = []
            if sweep: reason.append("Buy-side sweep")
            if mss: reason.append("Bearish MSS")
            if lower_structure: reason.append("LH/LL")
            if bos: reason.append("Bearish BOS")

        return {"ok": ok, "score": min(50, max(10, score)), "bos": bos, "mss": mss, "sweep": sweep,
                "swing_high": last_h, "swing_low": last_l,
                "reason": "، ".join(reason) if reason else "Directional structure"}

    def _bias(self, df, direction):
        if len(df) < 55:
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
            trend_ok = close >= e20 * 0.985 or e20 >= e50 * 0.985
            if close >= e20 * 0.985: score += 10
            if e20 >= e50 * 0.985: score += 10
            if ema200 > 0:
                if close >= ema200:
                    score += 6
                    if abs(close - ema200) <= max(atr_d * 1.5, close * 0.015):
                        ema200_support = True
                        score += 4
                        reasons.append("Daily EMA200 support")
                    else:
                        reasons.append("Above Daily EMA200")
                else:
                    reasons.append("Below Daily EMA200")
            if adx >= 20:
                score += 9; reasons.append(f"ADX({adx:.1f})")
            else:
                score += 5; reasons.append(f"Range ADX({adx:.1f})")
            if hist_val >= 0:
                score += 8; reasons.append("MACD Bullish")
            else:
                reasons.append("MACD soft")
            if 35 <= rsi <= 75: score += 5
            ok = trend_ok and (adx >= 12 or hist_val >= 0)
        else:
            trend_ok = close <= e20 * 1.015 or e20 <= e50 * 1.015
            if close <= e20 * 1.015: score += 10
            if e20 <= e50 * 1.015: score += 10
            if ema200 > 0:
                if close <= ema200:
                    score += 6
                    if abs(close - ema200) <= max(atr_d * 1.5, close * 0.015):
                        ema200_support = True
                        score += 4
                        reasons.append("Daily EMA200 resistance")
                    else:
                        reasons.append("Below Daily EMA200")
                else:
                    reasons.append("Above Daily EMA200")
            if adx >= 20:
                score += 9; reasons.append(f"ADX({adx:.1f})")
            else:
                score += 5; reasons.append(f"Range ADX({adx:.1f})")
            if hist_val <= 0:
                score += 8; reasons.append("MACD Bearish")
            else:
                reasons.append("MACD soft")
            if 25 <= rsi <= 65: score += 5
            ok = trend_ok and (adx >= 12 or hist_val <= 0)

        return {"ok": ok, "score": score, "rsi": rsi, "adx": adx, "ema20": e20, "ema50": e50,
                "ema200": ema200, "ema200_confluence": ema200_support,
                "reason": "، ".join(reasons) if reasons else "Neutral bias"}

    def _momentum_breakout_detector(self, daily, h4, h1, m15, asset_type, regime):
        """Detects high-conviction Momentum Breakout setups with mandatory 15M alignment."""
        try:
            if len(h4) < 35 or len(h1) < 30:
                return None

            price = float(h1["close"].iloc[-1])
            atr_1h = float(self.calculate_atr(h1).iloc[-1])
            rsi_1h = float(self.calculate_rsi(h1["close"]).iloc[-1])
            rsi_15m = float(self.calculate_rsi(m15["close"]).iloc[-1]) if (m15 is not None and len(m15) >= 15) else rsi_1h
            if price <= 0 or atr_1h <= 0:
                return None

            ema20_1h = float(self.calculate_ema(h1["close"], 20).iloc[-1])
            ema50_1h = float(self.calculate_ema(h1["close"], 50).iloc[-1]) if len(h1) >= 50 else ema20_1h
            _, _, macd_h1 = self.calculate_macd(h1["close"])
            hist_1h = float(macd_h1.iloc[-1]) if not macd_h1.empty else 0.0

            vol_mean = float(h1["volume"].tail(20).mean())
            vol_last = float(h1["volume"].iloc[-1])
            vol_spike = vol_mean > 0 and vol_last >= (vol_mean * 1.35)

            levels = self._key_levels(h4, h1, price, atr_1h)
            key_sup = levels["key_support"]
            res_low = levels["resistance_low"]
            res_high = levels["resistance_high"]

            # 1) Bullish Momentum Breakout Setup
            bull_close = self.has_close_confirmation(h1, "LONG")
            conf_15m_long = self._entry_confirmation(m15, "LONG")
            m15_ok_long = True if (m15 is None or m15.empty) else conf_15m_long.get("ok", False)
            prev_hi_1h = float(h1["high"].tail(12).iloc[:-1].max())
            is_bull_breakout = (
                (price >= prev_hi_1h * 0.996)
                and (price > ema20_1h)
                and (ema20_1h >= ema50_1h * 0.995)
                and (hist_1h > 0)
                and not self._is_overextended_move(h1, atr_1h, "LONG")
            )
            if is_bull_breakout and bull_close.get("ok") and m15_ok_long and (54 <= rsi_1h <= 76) and (rsi_15m <= 78):
                entry_low = max(key_sup, price - 0.70 * atr_1h)
                entry_high = price + 0.05 * atr_1h
                if entry_low > entry_high:
                    entry_low = price - 0.30 * atr_1h
                entry_mid = (entry_low + entry_high) / 2.0

                raw_sl = min(key_sup - 0.50 * atr_1h, entry_mid - 1.75 * atr_1h)
                max_sl = entry_mid * 0.95
                stop_loss = max(raw_sl, max_sl)
                risk = entry_mid - stop_loss
                if risk > 0 and (risk / entry_mid * 100) <= 5.0:
                    tp1 = max(res_low, entry_mid + 0.75 * risk)
                    tp2 = max(res_high, entry_mid + 1.35 * risk)
                    tp3 = entry_mid + 2.00 * risk
                    if stop_loss < entry_mid < tp1 < tp2:
                        score = 78 + (6 if vol_spike else 0) + (5 if bull_close.get("body_ratio", 0) >= 0.58 else 0) + (4 if conf_15m_long.get("ok") else 0)
                        score = min(98, score)
                        quality = "A+" if score >= 88 else "A"
                        decimals = 10 if price < 0.0001 else 8 if price < 0.01 else 7 if price < 0.1 else 6 if price < 1 else 4 if price < 100 else 2
                        fib_poc = self.calculate_fib_and_poc(h1, "LONG", lookback=36)
                        bias = self._bias(daily, "LONG")
                        struct = self._structure(h4, "LONG")
                        reason = f"LONG | V131.0 Bullish Momentum (TP1/TP2): Breakout + 15M + Vol({'ON' if vol_spike else 'OK'})"
                        sig = build_signal(
                            "LONG",
                            round(entry_low, decimals),
                            round(entry_high, decimals),
                            round(stop_loss, decimals),
                            [round(tp1, decimals), round(tp2, decimals), round(tp3, decimals)],
                            score,
                            rsi_1h,
                            atr_1h,
                            reason,
                            {
                                "quality": quality,
                                "setup_type": "BULLISH_MOMENTUM_SETUP",
                                "target_focus": "TP1 + TP2",
                                "regime": regime,
                                "key_support": round(key_sup, decimals),
                                "resistance_low": round(res_low, decimals),
                                "resistance_high": round(res_high, decimals),
                                "timeframes": "1D + 4H + 1H + 15M" if (m15 is not None and not m15.empty) else "1D + 4H + 1H",
                                "position_in_range": 0.68,
                                "extension_atr": round(abs(price - ema20_1h) / atr_1h, 2),
                                "move12": 0.0,
                                "structure": struct,
                                "fib_poc": fib_poc,
                                "engulfing": self.has_engulfing(h1, "LONG"),
                                "close_confirmed": True,
                                "ema200": round(bias.get("ema200", 0.0), decimals),
                                "ema200_confluence": bias.get("ema200_confluence", False),
                                "risk_pct": round((risk / entry_mid) * 100, 2),
                                "asset_type": asset_type,
                                "entry_timing": "momentum_breakout_15m_confirmed",
                            },
                        )
                        return "LONG", price, sig

            # 2) Bearish Momentum Breakdown Setup
            bear_close = self.has_close_confirmation(h1, "SHORT")
            conf_15m_short = self._entry_confirmation(m15, "SHORT")
            m15_ok_short = True if (m15 is None or m15.empty) else conf_15m_short.get("ok", False)
            prev_lo_1h = float(h1["low"].tail(12).iloc[:-1].min())
            is_bear_breakdown = (
                (price <= prev_lo_1h * 1.004)
                and (price < ema20_1h)
                and (ema20_1h <= ema50_1h * 1.005)
                and (hist_1h < 0)
                and not self._is_overextended_move(h1, atr_1h, "SHORT")
            )
            if is_bear_breakdown and bear_close.get("ok") and m15_ok_short and (24 <= rsi_1h <= 46) and (rsi_15m >= 22):
                entry_low = price - 0.05 * atr_1h
                entry_high = min(res_low, price + 0.70 * atr_1h)
                if entry_high < entry_low:
                    entry_high = price + 0.30 * atr_1h
                entry_mid = (entry_low + entry_high) / 2.0

                raw_sl = max(res_low + 0.50 * atr_1h, entry_mid + 1.75 * atr_1h)
                min_sl = entry_mid * 1.05
                stop_loss = min(raw_sl, min_sl)
                risk = stop_loss - entry_mid
                if risk > 0 and (risk / entry_mid * 100) <= 5.0:
                    tp1 = min(key_sup, entry_mid - 0.75 * risk)
                    tp2 = entry_mid - 1.35 * risk
                    tp3 = entry_mid - 2.00 * risk
                    if tp2 < tp1 < entry_mid < stop_loss:
                        score = 78 + (6 if vol_spike else 0) + (5 if bear_close.get("body_ratio", 0) >= 0.58 else 0) + (4 if conf_15m_short.get("ok") else 0)
                        score = min(98, score)
                        quality = "A+" if score >= 88 else "A"
                        decimals = 10 if price < 0.0001 else 8 if price < 0.01 else 7 if price < 0.1 else 6 if price < 1 else 4 if price < 100 else 2
                        fib_poc = self.calculate_fib_and_poc(h1, "SHORT", lookback=36)
                        bias = self._bias(daily, "SHORT")
                        struct = self._structure(h4, "SHORT")
                        reason = f"SHORT | V131.0 Bearish Momentum (TP1/TP2): Breakdown + 15M + Vol({'ON' if vol_spike else 'OK'})"
                        sig = build_signal(
                            "SHORT",
                            round(entry_low, decimals),
                            round(entry_high, decimals),
                            round(stop_loss, decimals),
                            [round(tp1, decimals), round(tp2, decimals), round(tp3, decimals)],
                            score,
                            rsi_1h,
                            atr_1h,
                            reason,
                            {
                                "quality": quality,
                                "setup_type": "BEARISH_MOMENTUM_SETUP",
                                "target_focus": "TP1 + TP2",
                                "regime": regime,
                                "key_support": round(key_sup, decimals),
                                "resistance_low": round(res_low, decimals),
                                "resistance_high": round(res_high, decimals),
                                "timeframes": "1D + 4H + 1H + 15M" if (m15 is not None and not m15.empty) else "1D + 4H + 1H",
                                "position_in_range": 0.32,
                                "extension_atr": round(abs(price - ema20_1h) / atr_1h, 2),
                                "move12": 0.0,
                                "structure": struct,
                                "fib_poc": fib_poc,
                                "engulfing": self.has_engulfing(h1, "SHORT"),
                                "close_confirmed": True,
                                "ema200": round(bias.get("ema200", 0.0), decimals),
                                "ema200_confluence": bias.get("ema200_confluence", False),
                                "risk_pct": round((risk / entry_mid) * 100, 2),
                                "asset_type": asset_type,
                                "entry_timing": "momentum_breakdown_15m_confirmed",
                            },
                        )
                        return "SHORT", price, sig

            return None
        except Exception as exc:
            logger.debug("Momentum breakout detector warning: %s", exc)
            return None

    def _value_entry(self, df, direction, regime="SIDEWAYS"):
        if len(df) < 30:
            return {"ok": False, "score": 0, "rsi": 50, "atr": 0, "position": 0.5,
                    "extension": 0, "reason": "Entry timeframe insufficient"}
        atr = float(self.calculate_atr(df).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        close = float(df["close"].iloc[-1])
        hi = float(df["high"].tail(36).max())
        lo = float(df["low"].tail(36).min())
        rng = max(hi - lo, atr, close * 1e-9)
        position = (close - lo) / rng
        ema20 = float(self.calculate_ema(df["close"], 20).iloc[-1])
        extension = abs(close - ema20) / max(atr, close * 1e-9)
        score = 0
        reasons = []

        if direction == "LONG":
            if regime == "SIDEWAYS":
                if position <= 0.42:
                    score += 18; reasons.append("Range bottom edge")
                elif position <= 0.58:
                    score += 8; reasons.append("Mid-low range")
                else:
                    score -= 16; reasons.append("Too high in sideways range")
            else:
                if position <= 0.70:
                    score += 16; reasons.append("Trend value zone")
                else:
                    score -= 14; reasons.append("High range")

            if 40 <= rsi <= 70:
                score += 12; reasons.append("RSI supportive")
            elif rsi > 75:
                score -= 18; reasons.append("Overbought")
            if extension <= 2.0:
                score += 9; reasons.append("Near EMA20")
            elif extension > 2.7:
                score -= 15; reasons.append("Extended")
        else:
            if regime == "SIDEWAYS":
                if position >= 0.58:
                    score += 18; reasons.append("Range top edge")
                elif position >= 0.42:
                    score += 8; reasons.append("Mid-high range")
                else:
                    score -= 16; reasons.append("Too low in sideways range")
            else:
                if position >= 0.30:
                    score += 16; reasons.append("Trend short zone")
                else:
                    score -= 14; reasons.append("Low range")

            if 30 <= rsi <= 60:
                score += 12; reasons.append("RSI supportive")
            elif rsi < 25:
                score -= 18; reasons.append("Oversold")
            if extension <= 2.0:
                score += 9; reasons.append("Near EMA20")
            elif extension > 2.7:
                score -= 15; reasons.append("Extended")

        fib_poc = self.calculate_fib_and_poc(df, direction, lookback=36)
        engulf = self.has_engulfing(df, direction)
        close_conf = self.has_close_confirmation(df, direction)

        if engulf:
            score += 8; reasons.append("Engulfing")
        if close_conf.get("ok"):
            score += close_conf.get("score", 0); reasons.append("1H close OK")
        else:
            score -= 6; reasons.append("Weak 1H close")

        look = df.tail(12)
        move = (float(look["close"].iloc[-1]) - float(look["close"].iloc[0])) / max(float(look["close"].iloc[0]), 1e-9) * 100
        if abs(move) > 13.0:
            score -= 14; reasons.append("Over-stretched move")

        return {"ok": score >= 20, "score": max(-15, score), "rsi": rsi, "atr": atr,
                "position": position, "extension": extension, "move12": move,
                "range_high": hi, "range_low": lo,
                "fib_poc": fib_poc, "engulfing": engulf, "close_confirmed": close_conf.get("ok", False),
                "reason": "، ".join(reasons)}

    def _entry_confirmation(self, df, direction):
        if df is None or len(df) < 15:
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
            if close > op: score += 8; reasons.append("15M bullish close")
            if lo < prev_lo and close > prev_lo: score += 10; reasons.append("15M sweep reclaim")
            if close > prev_hi: score += 9; reasons.append("15M breakout")
            if self.has_engulfing(df, "LONG"): score += 7; reasons.append("15M engulfing")
            if close_conf.get("ok"): score += 8; reasons.append("15M close OK")
            if 40 <= rsi <= 74: score += 5; reasons.append("15M RSI OK")
        else:
            if close < op: score += 8; reasons.append("15M bearish close")
            if hi > prev_hi and close < prev_hi: score += 10; reasons.append("15M sweep reject")
            if close < prev_lo: score += 9; reasons.append("15M breakdown")
            if self.has_engulfing(df, "SHORT"): score += 7; reasons.append("15M engulfing")
            if close_conf.get("ok"): score += 8; reasons.append("15M close OK")
            if 26 <= rsi <= 60: score += 5; reasons.append("15M RSI OK")
        body = abs(close - op)
        if atr > 0 and body > 2.0 * atr:
            score -= 10; reasons.append("15M candle stretched")
        ok_15m = close_conf.get("ok", False) and (score >= 12)
        return {"ok": ok_15m, "score": score, "atr": atr, "rsi": rsi,
                "close_confirmed": close_conf.get("ok", False),
                "reason": "، ".join(reasons) if reasons else "15M confirmation weak"}

    def _adaptive_two_target_plan(self, df1h, entry_price, atr, direction, structure, regime, levels):
        if entry_price <= 0 or atr <= 0:
            return None
        swing_low = float(structure.get("swing_low", df1h["low"].tail(18).min()))
        swing_high = float(structure.get("swing_high", df1h["high"].tail(18).max()))
        tp1_r = 0.60 if regime == "SIDEWAYS" else 0.70
        tp2_r = 1.15 if regime == "SIDEWAYS" else 1.35

        if direction == "LONG":
            structural = min(swing_low, levels["key_support"]) - 0.55 * atr
            atr_stop = entry_price - 1.75 * atr
            stop = min(structural, atr_stop)
            risk = entry_price - stop
            if risk <= 0:
                return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 5.0:
                return None
            if risk_pct < 0.7:
                stop = entry_price - 1.45 * atr
                risk = entry_price - stop
            entry_low = max(0.0, entry_price - 0.15 * atr)
            entry_high = entry_price + 0.05 * atr
            tps = [entry_price + tp1_r * risk, entry_price + tp2_r * risk, entry_price + 1.85 * risk]
        else:
            structural = max(swing_high, levels["resistance_low"]) + 0.55 * atr
            atr_stop = entry_price + 1.75 * atr
            stop = max(structural, atr_stop)
            risk = stop - entry_price
            if risk <= 0:
                return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 5.0:
                return None
            if risk_pct < 0.7:
                stop = entry_price + 1.45 * atr
                risk = stop - entry_price
            entry_low = entry_price - 0.05 * atr
            entry_high = entry_price + 0.15 * atr
            tps = [entry_price - tp1_r * risk, entry_price - tp2_r * risk, entry_price - 1.85 * risk]

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop,
            "tp1": tps[0],
            "tp2": tps[1],
            "tp3": tps[2],
            "risk_pct": risk / entry_price * 100,
        }

    def check_momentum_at_tp1(self, candles1h):
        try:
            df = self.prepare_dataframe(candles1h)
            if df.empty or len(df) < 10:
                return "NEUTRAL", "بيانات غير كافية لفحص الزخم"
            rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
            if rsi > 70 or rsi < 30:
                return "EXTREME", "⚠️ وصلت لـ TP1 والزخم مرتفع؛ انقل الوقف للدخول وخذ ربحك عند TP2."
            return "NORMAL", "⚖️ وصلت لـ TP1؛ انقل الوقف للدخول واستهدف TP2 كهدف أساسي."
        except Exception:
            return "NORMAL", "⚖️ انقل الوقف للدخول واستهدف TP2."

    def evaluate_open_position(self, direction, entry_price, stop_loss, take_profits,
                               current_price, candles_15m=None):
        try:
            entry = float(entry_price)
            sl = float(stop_loss)
            curr = float(current_price)
            tps = [float(x) for x in (take_profits or [])]
            tp1 = tps[0] if len(tps) > 0 else None
            tp2 = tps[1] if len(tps) > 1 else None

            if direction == "LONG":
                if curr <= sl:
                    return {"action": "STOP_HIT", "message": "🛑 ضرب وقف الخسارة؛ إغلاق الصفقة والتركيز على الفرصة التالية."}
                if tp2 is not None and curr >= tp2:
                    return {"action": "TP2_REACHED", "message": "🎯 تم الوصول للهدف الثاني (TP2)؛ أقفل الصفقة واحجز ربحك."}
                if tp1 is not None and curr >= tp1:
                    return {"action": "TP1_REACHED", "message": "🥇 تم الوصول للهدف الأول (TP1)؛ انقل الوقف للدخول (Break-Even) وانتظر TP2."}
            else:
                if curr >= sl:
                    return {"action": "STOP_HIT", "message": "🛑 ضرب وقف الخسارة؛ إغلاق الصفقة والتركيز على الفرصة التالية."}
                if tp2 is not None and curr <= tp2:
                    return {"action": "TP2_REACHED", "message": "🎯 تم الوصول للهدف الثاني (TP2)؛ أقفل الصفقة واحجز ربحك."}
                if tp1 is not None and curr <= tp1:
                    return {"action": "TP1_REACHED", "message": "🥇 تم الوصول للهدف الأول (TP1)؛ انقل الوقف للدخول (Break-Even) وانتظر TP2."}

            return {"action": "HOLD", "message": "⏳ الصفقة في طريقها نحو TP1 ثم TP2."}
        except Exception:
            return {"action": "HOLD", "message": "⏳ الصفقة قيد المتابعة."}

    def _make_neutral(self, reason="لا توجد فرصة مكتملة حالياً", score=0, rsi=50, atr=0, details=None):
        return build_signal("NEUTRAL", 0, 0, 0, [], score, rsi, atr, reason, details or {})

    def analyze_market_structure(self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None,
                                 asset_type="crypto", ohlcv_15m=None):
        neutral = self._make_neutral()
        try:
            daily = self.prepare_dataframe(ohlcv_daily)
            h4 = self.prepare_dataframe(ohlcv_4h)
            h1 = self.prepare_dataframe(ohlcv_1h)
            m15 = self.prepare_dataframe(ohlcv_15m)
            if len(daily) < 55 or len(h4) < 35 or len(h1) < 30:
                return "NEUTRAL", 0.0, self._make_neutral("بيانات غير كافية")

            regime, adx_val = self.detect_regime_state(daily, h4)
            regime_min_score = (self.min_score + 4) if regime == "SIDEWAYS" else self.min_score

            long_d = self._bias(daily, "LONG")
            short_d = self._bias(daily, "SHORT")
            long_h4 = self._structure(h4, "LONG")
            short_h4 = self._structure(h4, "SHORT")
            long_h1 = self._value_entry(h1, "LONG", regime=regime)
            short_h1 = self._value_entry(h1, "SHORT", regime=regime)

            price = float(h1["close"].iloc[-1])
            atr_1h = float(self.calculate_atr(h1).iloc[-1])
            levels = self._key_levels(h4, h1, price, atr_1h)

            candidates = []
            for direction, bias, struct, value in [
                ("LONG", long_d, long_h4, long_h1),
                ("SHORT", short_d, short_h4, short_h1),
            ]:
                if regime == "BULLISH" and direction == "SHORT":
                    continue
                if regime == "BEARISH" and direction == "LONG":
                    continue
                if not struct["ok"] or not value["ok"]:
                    continue
                if not value.get("close_confirmed", False):
                    continue
                if self._is_overextended_move(h1, value["atr"], direction):
                    continue
                conf = self._entry_confirmation(m15, direction)
                if not m15.empty and not conf["ok"]:
                    continue
                bias_pts = bias["score"] if bias["ok"] else 8
                score = int(round(min(100, max(0, bias_pts + struct["score"] + value["score"] + conf["score"]))))
                if score < regime_min_score:
                    continue
                if self._is_dead_flat(h1, value["atr"]):
                    continue
                plan = self._adaptive_two_target_plan(h1, price, value["atr"], direction, struct, regime, levels)
                if not plan:
                    continue
                if direction == "LONG" and not (plan["stop_loss"] < price < plan["tp1"]):
                    continue
                if direction == "SHORT" and not (plan["tp1"] < price < plan["stop_loss"]):
                    continue
                candidates.append((score, direction, bias, struct, value, conf, plan, price))

            if candidates:
                score, direction, bias, struct, value, conf, plan, price = max(candidates, key=lambda x: x[0])
                quality = "A+" if score >= 88 else "A" if score >= 82 else "B+"
                reason = f"{direction} | V131.0 [{regime}] TP1/TP2: {struct['reason']} + close confirmed"
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
                        "setup_type": "ADAPTIVE_TWO_TARGET",
                        "target_focus": "TP1 + TP2",
                        "regime": regime,
                        "adx": round(adx_val, 1),
                        "key_support": round(levels["key_support"], decimals),
                        "resistance_low": round(levels["resistance_low"], decimals),
                        "resistance_high": round(levels["resistance_high"], decimals),
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
                        "entry_timing": "adaptive_confirmed",
                    },
                )
                return direction, price, signal

            mom_setup = self._momentum_breakout_detector(daily, h4, h1, m15, asset_type, regime)
            if mom_setup is not None:
                return mom_setup

            diagnostics = {
                "daily_long": long_d, "daily_short": short_d,
                "4h_long": long_h4, "4h_short": short_h4,
                "1h_long": long_h1, "1h_short": short_h1,
                "15m": "available" if not m15.empty else "unavailable",
                "regime": regime,
            }
            best_value = long_h1 if long_h1.get("score", -999) >= short_h1.get("score", -999) else short_h1
            return "NEUTRAL", 0.0, self._make_neutral(
                f"لا توجد صفقة عالية الجودة في وضع [{regime}] حالياً (TP1/TP2)",
                max(0, min(100, int(best_value.get("score", 0)))),
                best_value.get("rsi", 50), best_value.get("atr", 0), diagnostics
            )
        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral
