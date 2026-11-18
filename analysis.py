# ============================================================
# analysis.py — StrategyEngine V124.0 Elite Entry Timing
# Multi-Market: Crypto + Stocks/ETFs + Forex + Metals
# Signal-only: LONG / SHORT, no automatic order execution.
# ============================================================

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
    """Timing-first multi-market signal engine.

    Principle: trend alignment alone never creates a trade.
    A trade needs direction + structure + retracement/value + momentum
    confirmation + acceptable extension/risk.
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
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).replace([np.inf, -np.inf], np.nan).fillna(50)

    def calculate_atr(self, df, period=14):
        h = pd.to_numeric(df["high"], errors="coerce")
        l = pd.to_numeric(df["low"], errors="coerce")
        c = pd.to_numeric(df["close"], errors="coerce")
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().replace([np.inf, -np.inf], np.nan).fillna(0)

    def calculate_ema(self, series, period):
        return pd.to_numeric(series, errors="coerce").ewm(span=period, adjust=False, min_periods=period).mean()

    # --- تم إضافة دوال ADX و MACD هنا بدقة بدون حذف أي كود قديم ---
    def calculate_adx(self, df, period=14):
        try:
            h = pd.to_numeric(df["high"], errors="coerce")
            l = pd.to_numeric(df["low"], errors="coerce")
            c = pd.to_numeric(df["close"], errors="coerce")
            plus_dm = h.diff()
            minus_dm = l.diff()
            plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
            minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
            tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
            minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
            adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            return adx.replace([np.inf, -np.inf], np.nan).fillna(25.0)
        except Exception:
            return pd.Series([25.0] * len(df))

    def calculate_macd(self, series, fast=12, slow=26, signal=9):
        s = pd.to_numeric(series, errors="coerce")
        exp1 = s.ewm(span=fast, adjust=False).mean()
        exp2 = s.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

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
        """Return confirmed local swing highs/lows, excluding the newest unconfirmed edge."""
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
        swing_high = last_h
        swing_low = last_l
        recent = df.tail(8)
        sweep = False
        bos = False
        mss = False

        if direction == "LONG":
            higher_structure = last_h >= prev_h and last_l >= prev_l * 0.997
            bos = close > prev_h or close > last_h
            sweep = float(recent["low"].min()) < prev_l and close > prev_l
            mss = sweep and close > float(recent["high"].iloc[:-1].max()) if len(recent) > 2 else False
            score = (18 if higher_structure else 0) + (14 if bos else 0) + (12 if sweep else 0) + (8 if mss else 0)
            ok = higher_structure or bos
            reason = []
            if higher_structure: reason.append("Higher-High/Higher-Low")
            if bos: reason.append("Bullish BOS")
            if sweep: reason.append("Liquidity sweep below swing")
            if mss: reason.append("Bullish MSS")
        else:
            lower_structure = last_h <= prev_h * 1.003 and last_l <= prev_l
            bos = close < prev_l or close < last_l
            sweep = float(recent["high"].max()) > prev_h and close < prev_h
            mss = sweep and close < float(recent["low"].iloc[:-1].min()) if len(recent) > 2 else False
            score = (18 if lower_structure else 0) + (14 if bos else 0) + (12 if sweep else 0) + (8 if mss else 0)
            ok = lower_structure or bos
            reason = []
            if lower_structure: reason.append("Lower-High/Lower-Low")
            if bos: reason.append("Bearish BOS")
            if sweep: reason.append("Liquidity sweep above swing")
            if mss: reason.append("Bearish MSS")

        return {"ok": ok, "score": min(52, score), "bos": bos, "mss": mss, "sweep": sweep,
                "swing_high": swing_high, "swing_low": swing_low,
                "reason": "، ".join(reason) if reason else "No clean structure confirmation"}

    def _bias(self, df, direction):
        if len(df) < 60:
            return {"ok": False, "score": 0, "rsi": 50, "reason": "Bias data insufficient"}
        close = float(df["close"].iloc[-1])
        e20 = float(self.calculate_ema(df["close"], 20).iloc[-1])
        e50 = float(self.calculate_ema(df["close"], 50).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        
        # --- دمج فلاتر الاتجاه (ADX) والزخم (MACD) داخل _bias بدون حذف القديم ---
        adx_series = self.calculate_adx(df)
        adx = float(adx_series.iloc[-1]) if not adx_series.empty else 25.0
        _, _, macd_hist = self.calculate_macd(df["close"])
        hist_val = float(macd_hist.iloc[-1]) if not macd_hist.empty else 0.0

        reasons = []
        score = 0

        if direction == "LONG":
            trend_ok = close > e20 and e20 >= e50 and adx >= 22
            momentum_ok = hist_val > 0

            if close > e20: score += 10
            if e20 >= e50: score += 10
            if adx >= 25:
                score += 12; reasons.append(f"Strong Trend ADX({adx:.1f})")
            elif adx >= 22:
                score += 6; reasons.append(f"Moderate Trend ADX({adx:.1f})")
            else:
                trend_ok = False; reasons.append(f"Weak Sideways ADX({adx:.1f})")

            if momentum_ok:
                score += 8; reasons.append("MACD Bullish Momentum")
            else:
                score -= 10; reasons.append("MACD Momentum weak")

            if 45 <= rsi <= 72: score += 6
            ok = trend_ok and momentum_ok
        else:
            trend_ok = close < e20 and e20 <= e50 and adx >= 22
            momentum_ok = hist_val < 0

            if close < e20: score += 10
            if e20 <= e50: score += 10
            if adx >= 25:
                score += 12; reasons.append(f"Strong Trend ADX({adx:.1f})")
            elif adx >= 22:
                score += 6; reasons.append(f"Moderate Trend ADX({adx:.1f})")
            else:
                trend_ok = False; reasons.append(f"Weak Sideways ADX({adx:.1f})")

            if momentum_ok:
                score += 8; reasons.append("MACD Bearish Momentum")
            else:
                score -= 10; reasons.append("MACD Momentum weak")

            if 28 <= rsi <= 55: score += 6
            ok = trend_ok and momentum_ok

        return {"ok": ok, "score": score, "rsi": rsi, "adx": adx, "ema20": e20, "ema50": e50,
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
        score = 0
        reasons = []
        if direction == "LONG":
            if 0.25 <= position <= 0.55:
                score += 18; reasons.append("Discount/value zone")
            elif 0.55 < position <= 0.62:
                score += 6; reasons.append("Moderate value zone")
            else:
                score -= 24; reasons.append("Premium/late location rejected")
            if 42 <= rsi <= 62:
                score += 14; reasons.append("RSI supports controlled entry")
            elif rsi > 70:
                score -= 25; reasons.append("Overbought")
            if extension <= 1.8:
                score += 10; reasons.append("Not overextended from EMA20")
            elif extension > 2.8:
                score -= 20; reasons.append("Extended from EMA20")
        else:
            if 0.45 <= position <= 0.75:
                score += 18; reasons.append("Premium/value zone")
            elif 0.38 <= position < 0.45:
                score += 6; reasons.append("Moderate value zone")
            else:
                score -= 24; reasons.append("Discount/late location rejected")
            if 38 <= rsi <= 58:
                score += 14; reasons.append("RSI supports controlled short")
            elif rsi < 30:
                score -= 25; reasons.append("Oversold")
            if extension <= 1.8:
                score += 10; reasons.append("Not overextended from EMA20")
            elif extension > 2.8:
                score -= 20; reasons.append("Extended from EMA20")

        # Detect an already explosive move even if the last 5 candles cooled down.
        look = df.tail(12)
        move = (float(look["close"].iloc[-1]) - float(look["close"].iloc[0])) / float(look["close"].iloc[0]) * 100
        if direction == "LONG" and move > 8:
            score -= 24; reasons.append("Recent 12-bar impulse too strong")
        if direction == "SHORT" and move < -8:
            score -= 24; reasons.append("Recent 12-bar impulse too strong")

        # Volume expansion is useful only as confirmation, not as a standalone entry.
        vmean = float(df["volume"].tail(20).mean())
        vlast = float(df["volume"].iloc[-1])
        if vmean > 0 and vlast >= vmean * 1.15:
            score += 6; reasons.append("Volume confirmation")

        return {"ok": score >= 24, "score": max(-20, score), "rsi": rsi, "atr": atr,
                "position": position, "extension": extension, "move12": move,
                "range_high": hi, "range_low": lo,
                "reason": "، ".join(reasons)}

    def _entry_confirmation(self, df, direction):
        if df is None or len(df) < 20:
            return {"ok": True, "score": 0, "reason": "15M unavailable; using higher-timeframe timing"}
        close = float(df["close"].iloc[-1])
        op = float(df["open"].iloc[-1])
        hi = float(df["high"].iloc[-1])
        lo = float(df["low"].iloc[-1])
        atr = float(self.calculate_atr(df).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        prev_hi = float(df["high"].tail(8).iloc[:-1].max())
        prev_lo = float(df["low"].tail(8).iloc[:-1].min())
        score = 0
        reasons = []
        if direction == "LONG":
            if close > op: score += 8; reasons.append("15M bullish close")
            if lo < prev_lo and close > prev_lo: score += 12; reasons.append("15M sell-side sweep/reclaim")
            if close > prev_hi: score += 10; reasons.append("15M micro BOS")
            if 40 <= rsi <= 68: score += 6; reasons.append("15M RSI controlled")
        else:
            if close < op: score += 8; reasons.append("15M bearish close")
            if hi > prev_hi and close < prev_hi: score += 12; reasons.append("15M buy-side sweep/reclaim")
            if close < prev_lo: score += 10; reasons.append("15M micro BOS")
            if 32 <= rsi <= 60: score += 6; reasons.append("15M RSI controlled")
        # Never accept a huge final candle as a clean entry confirmation.
        body = abs(close - op)
        if atr > 0 and body > 1.8 * atr:
            score -= 18; reasons.append("15M candle too extended")
        return {"ok": score >= 14, "score": score, "atr": atr, "rsi": rsi,
                "reason": "، ".join(reasons) if reasons else "15M confirmation weak"}

    def _trade_plan(self, df1h, entry_price, atr, direction, structure):
        if entry_price <= 0 or atr <= 0:
            return None
        swing_low = float(structure.get("swing_low", df1h["low"].tail(20).min()))
        swing_high = float(structure.get("swing_high", df1h["high"].tail(20).max()))
        if direction == "LONG":
            structural = swing_low - 0.35 * atr
            atr_stop = entry_price - 1.8 * atr
            stop = min(structural, atr_stop)
            risk = entry_price - stop
            if risk <= 0: return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 6.5: return None
            if risk_pct < 0.45:
                stop = entry_price - 1.25 * atr
                risk = entry_price - stop
            entry_low = max(0.0, entry_price - 0.20 * atr)
            entry_high = entry_price + 0.08 * atr
            tps = [entry_price + 1.5 * risk, entry_price + 2.5 * risk, entry_price + 4.0 * risk]
        else:
            structural = swing_high + 0.35 * atr
            atr_stop = entry_price + 1.8 * atr
            stop = max(structural, atr_stop)
            risk = stop - entry_price
            if risk <= 0: return None
            risk_pct = risk / entry_price * 100
            if risk_pct > 6.5: return None
            if risk_pct < 0.45:
                stop = entry_price + 1.25 * atr
                risk = stop - entry_price
            entry_low = entry_price - 0.08 * atr
            entry_high = entry_price + 0.20 * atr
            tps = [entry_price - 1.5 * risk, entry_price - 2.5 * risk, entry_price - 4.0 * risk]
        return {"entry_low": entry_low, "entry_high": entry_high, "stop_loss": stop,
                "tp1": tps[0], "tp2": tps[1], "tp3": tps[2], "risk_pct": risk / entry_price * 100}

    def check_momentum_at_tp1(self, candles1h):
        try:
            df = self.prepare_dataframe(candles1h)
            if df.empty or len(df) < 10:
                return "NEUTRAL", "بيانات غير كافية لفحص الزخم"
            rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
            mean_v = float(df["volume"].tail(10).mean())
            last_v = float(df["volume"].iloc[-1])
            if rsi > 70:
                return "OVERBOUGHT", "⚠️ RSI متشبع شرائي؛ يفضل تأمين جزء من الربح."
            if rsi < 30:
                return "OVERSOLD", "⚠️ RSI متشبع بيعي؛ يفضل تأمين جزء من الربح في الشورت."
            if mean_v > 0 and last_v > mean_v * 1.5:
                return "STRONG", "🚀 الزخم والحجم مرتفعان."
            return "NORMAL", "⚖️ الزخم مستقر."
        except Exception:
            return "NORMAL", "⚖️ الزخم مستقر."

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
                conf = self._entry_confirmation(m15, direction)
                score = int(round(min(100, max(0, bias["score"] + struct["score"] + value["score"] + conf["score"]))))
                # Hard late-entry guards.
                if value["position"] > 0.66 if direction == "LONG" else value["position"] < 0.34:
                    continue
                if value["extension"] > 2.8 or abs(value["move12"]) > 12:
                    continue
                # 15M is an enhancer when available; it cannot rescue a bad 1H location.
                if not conf["ok"] and not m15.empty:
                    continue
                if score < self.min_score:
                    continue
                price = float(h1["close"].iloc[-1])
                plan = self._trade_plan(h1, price, value["atr"], direction, struct)
                if not plan:
                    continue
                # Require TP1 to offer at least 1.5R by construction and sane direction.
                if direction == "LONG" and not (plan["stop_loss"] < price < plan["tp1"]):
                    continue
                if direction == "SHORT" and not (plan["tp1"] < price < plan["stop_loss"]):
                    continue
                candidates.append((score, direction, bias, struct, value, conf, plan, price))

            if not candidates:
                # Return the strongest diagnostic candidate even when rejected.
                diagnostics = {
                    "daily_long": long_d, "daily_short": short_d,
                    "4h_long": long_h4, "4h_short": short_h4,
                    "1h_long": long_h1, "1h_short": short_h1,
                    "15m": "available" if not m15.empty else "unavailable",
                }
                best_value = long_h1 if long_h1.get("score", -999) >= short_h1.get("score", -999) else short_h1
                return "NEUTRAL", 0.0, self._make_neutral(
                    "لا توجد صفقة: الاتجاه أو منطقة الدخول أو تأكيد 15M غير مكتمل",
                    max(0, min(100, int(best_value.get("score", 0)))),
                    best_value.get("rsi", 50), best_value.get("atr", 0), diagnostics
                )

            score, direction, bias, struct, value, conf, plan, price = max(candidates, key=lambda x: x[0])
            quality = "A+" if score >= 90 else "A" if score >= 82 else "B+"
            reason = (
                f"{direction} | 1D bias (ADX+MACD) + 4H structure + 1H value zone + "
                f"timed entry confirmation | {struct['reason']}"
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
                    "timeframes": "1D + 4H + 1H + 15M" if not m15.empty else "1D + 4H + 1H",
                    "position_in_range": round(value["position"], 3),
                    "extension_atr": round(value["extension"], 2),
                    "move12": round(value["move12"], 2),
                    "structure": struct,
                    "confirmation_15m": conf,
                    "risk_pct": round(plan["risk_pct"], 2),
                    "asset_type": asset_type,
                    "entry_timing": "confirmed",
                },
            )
            return direction, price, signal
        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral
