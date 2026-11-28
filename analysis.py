# ============================================================
# analysis.py — StrategyEngine V136.1 (LONG Only — 1W / 1M)
# Long-only position engine built on Monthly (1M) + Weekly (1W)
# bullish structure/trend with Daily (1D) timing.
# ============================================================

import logging
import uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400 * 7
MIN_SCORE_DEFAULT = 75
MIN_TP2_RR = 1.30


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
    """Long-only position engine on Monthly (1M) and Weekly (1W)
    with Daily (1D) timing and TP1/TP2/TP3 targets."""

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
        s = pd.to_numeric(series, errors="coerce")
        eff_period = min(period, max(2, len(s)))
        return s.ewm(span=eff_period, adjust=False, min_periods=1).mean()

    def calculate_adx(self, df, period=14):
        try:
            if df is None or len(df) < 8:
                return pd.Series([25.0] * (len(df) if df is not None else 1), index=df.index if df is not None else None)
            eff = min(period, max(3, len(df) - 2))
            h = pd.to_numeric(df["high"], errors="coerce")
            l = pd.to_numeric(df["low"], errors="coerce")
            c = pd.to_numeric(df["close"], errors="coerce")
            plus_dm_raw = h.diff()
            minus_dm_raw = -l.diff()
            plus_dm = pd.Series(
                np.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), plus_dm_raw, 0.0),
                index=df.index,
            )
            minus_dm = pd.Series(
                np.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), minus_dm_raw, 0.0),
                index=df.index,
            )
            tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1.0 / eff, min_periods=1, adjust=False).mean()
            plus_di = 100 * plus_dm.ewm(alpha=1.0 / eff, min_periods=1, adjust=False).mean() / atr.replace(0, 1e-10)
            minus_di = 100 * minus_dm.ewm(alpha=1.0 / eff, min_periods=1, adjust=False).mean() / atr.replace(0, 1e-10)
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
            adx = dx.ewm(alpha=1.0 / eff, min_periods=1, adjust=False).mean()
            return adx.replace([np.inf, -np.inf], np.nan).fillna(25.0)
        except Exception:
            return pd.Series([25.0] * len(df), index=df.index)

    def calculate_macd(self, series, fast=12, slow=26, signal=9):
        s = pd.to_numeric(series, errors="coerce")
        f_p = min(fast, max(2, len(s) // 2))
        s_p = min(slow, max(f_p + 2, len(s)))
        sig_p = min(signal, max(2, f_p))
        exp1 = s.ewm(span=f_p, adjust=False).mean()
        exp2 = s.ewm(span=s_p, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=sig_p, adjust=False).mean()
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
        if df is None or len(df) < left + right + 3:
            return [], []
        highs, lows = [], []
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        last_confirmed = len(df) - right - 1
        for i in range(left, last_confirmed + 1):
            if h[i] >= np.max(h[i-left:i+right+1]) and h[i] >= np.max(h[i-left:i]):
                highs.append((i, h[i]))
            if l[i] <= np.min(l[i-left:i+right+1]) and l[i] <= np.min(l[i-left:i]):
                lows.append((i, l[i]))
        return highs, lows

    def _macro_long_structure(self, df, label, boost_without_monthly=False):
        """Evaluates bullish structure & trend on Weekly (1W) or Monthly (1M)."""
        if df is None or len(df) < 6:
            return {"ok": False, "score": 0, "rsi": 50.0, "adx": 20.0, "reason": f"{label} data insufficient"}

        close = float(df["close"].iloc[-1])
        fast_p = 8 if label == "1W" else 4
        slow_p = 20 if label == "1W" else 10
        ema_fast = float(self.calculate_ema(df["close"], fast_p).iloc[-1])
        ema_slow = float(self.calculate_ema(df["close"], slow_p).iloc[-1])
        rsi = float(self.calculate_rsi(df["close"]).iloc[-1])
        adx = float(self.calculate_adx(df).iloc[-1])
        _, _, macd_hist = self.calculate_macd(df["close"])
        hist = float(macd_hist.iloc[-1]) if not macd_hist.empty else 0.0

        highs, lows = self._swings(df, left=2, right=1 if len(df) < 15 else 2)
        struct_ok = False
        struct_tag = ""
        if len(highs) >= 2 and len(lows) >= 2:
            prev_h, last_h = highs[-2][1], highs[-1][1]
            prev_l, last_l = lows[-2][1], lows[-1][1]
            if last_h >= prev_h * 0.99 and last_l >= prev_l * 0.985:
                struct_ok = True
                struct_tag = "HH/HL"
            elif close > prev_h:
                struct_ok = True
                struct_tag = "Bullish BOS"

        mult = 1.35 if (label == "1W" and boost_without_monthly) else 1.0
        score = 0
        reasons = []
        if close >= ema_fast * 0.97:
            score += 12 * mult
            reasons.append(f"{label} > EMA{fast_p}")
        if ema_fast >= ema_slow * 0.97:
            score += 10 * mult
            reasons.append(f"EMA{fast_p}>=EMA{slow_p}")
        if hist >= 0:
            score += 8 * mult
            reasons.append("MACD+")
        if struct_ok:
            score += 12 * mult
            reasons.append(struct_tag)
        if 38 <= rsi <= 76:
            score += 4 * mult
        ok = (close >= ema_fast * 0.96) and (struct_ok or (ema_fast >= ema_slow * 0.97 and hist >= 0))
        reasons.append(f"RSI({rsi:.1f})")
        return {
            "ok": ok,
            "score": round(score, 2),
            "rsi": rsi,
            "adx": adx,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "reason": "، ".join(reasons),
        }

    def _daily_long_timing(self, df_daily):
        """Uses Daily (1D) only for LONG timing & avoiding over-extended chase."""
        if df_daily is None or len(df_daily) < 30:
            return {"ok": False, "score": 0, "reason": "1D data insufficient"}
        close = float(df_daily["close"].iloc[-1])
        op = float(df_daily["open"].iloc[-1])
        ema20 = float(self.calculate_ema(df_daily["close"], 20).iloc[-1])
        atr_d = float(self.calculate_atr(df_daily).iloc[-1])
        rsi_d = float(self.calculate_rsi(df_daily["close"]).iloc[-1])

        score = 0
        reasons = []
        bull_d = close >= op * 0.995
        not_chasing = (close - ema20) <= max(2.4 * atr_d, close * 0.08) and rsi_d <= 76
        if bull_d:
            score += 10
            reasons.append("1D bullish/reclaim")
        if close >= ema20 * 0.97:
            score += 8
            reasons.append("1D near/above EMA20")
        if not_chasing:
            score += 8
            reasons.append("1D timing OK")
        else:
            score -= 12
            reasons.append("1D over-extended")
        ok = not_chasing and (bull_d or close >= ema20 * 0.97)
        return {"ok": ok, "score": score, "rsi": rsi_d, "atr": atr_d, "reason": "، ".join(reasons)}

    def _long_levels(self, df_w, df_m, price, atr_w):
        """Computes long-term support/resistance and TP1/TP2/TP3 from 1W & 1M."""
        try:
            w_lows = df_w["low"].tail(20).to_numpy(dtype=float) if (df_w is not None and len(df_w) >= 4) else np.array([price - 2 * atr_w])
            w_highs = df_w["high"].tail(20).to_numpy(dtype=float) if (df_w is not None and len(df_w) >= 4) else np.array([price + 2 * atr_w])
            m_lows = df_m["low"].tail(12).to_numpy(dtype=float) if (df_m is not None and len(df_m) >= 3) else w_lows
            m_highs = df_m["high"].tail(12).to_numpy(dtype=float) if (df_m is not None and len(df_m) >= 3) else w_highs

            below_w = sorted([v for v in w_lows if v < price], reverse=True)
            above_w = sorted([v for v in w_highs if v > price])
            below_m = sorted([v for v in m_lows if v < price], reverse=True)
            above_m = sorted([v for v in m_highs if v > price])

            key_sup = float(below_w[0]) if below_w else float(price - 1.6 * atr_w)
            deep_sup = float(below_m[0]) if below_m else (float(below_w[1]) if len(below_w) > 1 else float(price - 2.8 * atr_w))
            res_low = float(above_w[0]) if above_w else float(price + 1.6 * atr_w)
            res_high = float(above_m[0]) if above_m else (float(above_w[1]) if len(above_w) > 1 else float(price + 2.8 * atr_w))

            return {
                "key_support": key_sup,
                "deep_support": deep_sup,
                "resistance_low": res_low,
                "resistance_high": res_high,
            }
        except Exception:
            return {
                "key_support": max(0.0, price - 1.6 * atr_w),
                "deep_support": max(0.0, price - 2.8 * atr_w),
                "resistance_low": price + 1.6 * atr_w,
                "resistance_high": price + 2.8 * atr_w,
            }

    def _build_long_plan(self, entry_price, atr_w, levels):
        """Builds stop-loss and TP1/TP2/TP3 for LONG 1W/1M position trades."""
        if entry_price <= 0 or atr_w <= 0:
            return None
        max_risk_pct = 16.0
        min_risk_pct = 2.5

        structural_sl = min(levels["key_support"], levels["deep_support"]) - 0.35 * atr_w
        atr_sl = entry_price - 1.85 * atr_w
        stop = max(min(structural_sl, atr_sl), entry_price * (1.0 - max_risk_pct / 100.0))
        risk = entry_price - stop
        if risk <= 0 or (risk / entry_price * 100) > max_risk_pct:
            return None
        if (risk / entry_price * 100) < min_risk_pct:
            stop = entry_price * (1.0 - min_risk_pct / 100.0)
            risk = entry_price - stop

        entry_low = max(0.0, entry_price - 0.25 * atr_w)
        entry_high = entry_price + 0.05 * atr_w

        tp1_cand = entry_price + 1.00 * risk
        if levels["resistance_low"] > entry_price * 1.03 and levels["resistance_low"] < entry_price + 1.35 * risk:
            tp1 = max(tp1_cand, levels["resistance_low"])
        else:
            tp1 = tp1_cand

        tp2_cand = entry_price + 1.95 * risk
        if levels["resistance_high"] > tp1 * 1.04 and levels["resistance_high"] < entry_price + 2.60 * risk:
            tp2 = levels["resistance_high"]
        else:
            tp2 = tp2_cand

        tp3 = max(tp2 + 0.85 * risk, entry_price + 2.95 * risk)
        tp2_rr = abs(tp2 - entry_price) / max(risk, 1e-12)
        if tp2_rr < MIN_TP2_RR:
            return None

        return {
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "risk_pct": round(risk / entry_price * 100, 2),
            "tp2_rr": round(tp2_rr, 2),
        }

    def evaluate_open_position(self, direction, entry_price, stop_loss, take_profits,
                               current_price, candles_15m=None):
        try:
            entry = float(entry_price)
            sl = float(stop_loss)
            curr = float(current_price)
            tps = [float(x) for x in (take_profits or [])]
            tp1 = tps[0] if len(tps) > 0 else None
            tp2 = tps[1] if len(tps) > 1 else None

            if curr <= sl:
                return {"action": "STOP_HIT", "message": "🛑 تم كسر وقف الخسارة؛ إغلاق صفقة الشراء والتركيز على الفرصة التالية."}
            if tp2 is not None and curr >= tp2:
                return {"action": "TP2_REACHED", "message": "🎯 تم الوصول للهدف الثاني (TP2)؛ أقفل الجزء الأساسي واحجز ربحك."}
            if tp1 is not None and curr >= tp1:
                return {"action": "TP1_REACHED", "message": "🥇 تم الوصول للهدف الأول (TP1)؛ انقل الوقف للدخول (Break-Even) وتابع نحو TP2."}
            return {"action": "HOLD", "message": "⏳ صفقة الشراء طويلة المدى (1W/1M) قيد المتابعة نحو TP1 ثم TP2."}
        except Exception:
            return {"action": "HOLD", "message": "⏳ الصفقة قيد المتابعة."}

    def _make_neutral(self, reason="لا توجد فرصة شراء (LONG) أسبوعية/شهرية مكتملة حالياً", score=0, rsi=50, atr=0, details=None):
        return build_signal("NEUTRAL", 0, 0, 0, [], score, rsi, atr, reason, details or {})

    def analyze_market_structure(self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None,
                                 asset_type="crypto", ohlcv_15m=None,
                                 ohlcv_1w=None, ohlcv_1m=None):
        """LONG-only analysis on Monthly (1M) + Weekly (1W) with Daily (1D) timing."""
        neutral = self._make_neutral()
        try:
            daily = self.prepare_dataframe(ohlcv_daily)
            w1 = self.prepare_dataframe(ohlcv_1w)
            mn1 = self.prepare_dataframe(ohlcv_1m)

            if len(w1) < 8:
                return "NEUTRAL", 0.0, self._make_neutral("بيانات الفريم الأسبوعي (1W) غير كافية")

            has_monthly = len(mn1) >= 6
            ref_price = float(daily["close"].iloc[-1]) if len(daily) > 0 else float(w1["close"].iloc[-1])
            atr_w = float(self.calculate_atr(w1).iloc[-1])
            if ref_price <= 0 or atr_w <= 0:
                return "NEUTRAL", 0.0, self._make_neutral("بيانات السعر أو التذبذب الأسبوعي غير صالحة")

            levels = self._long_levels(w1, mn1, ref_price, atr_w)
            m_info = self._macro_long_structure(mn1, "1M", boost_without_monthly=False)
            w_info = self._macro_long_structure(w1, "1W", boost_without_monthly=not has_monthly)
            d_info = self._daily_long_timing(daily) if len(daily) >= 30 else {"ok": True, "score": 8, "reason": "1D N/A"}

            if has_monthly:
                macro_ok = (m_info["ok"] and w_info["ok"]) or (m_info["score"] >= 20 and w_info["ok"] and w_info["score"] >= 26)
            else:
                macro_ok = w_info["ok"] and w_info["score"] >= 32

            total_score = int(round(min(100, max(0, m_info["score"] + w_info["score"] + d_info["score"]))))
            diag_long = {
                "score": total_score,
                "1m": m_info["reason"],
                "1w": w_info["reason"],
                "1d": d_info["reason"],
            }

            if macro_ok and total_score >= self.min_score:
                plan = self._build_long_plan(ref_price, atr_w, levels)
                if plan and (plan["stop_loss"] < ref_price < plan["tp1"]):
                    quality = "A+" if total_score >= 88 else "A" if total_score >= 80 else "B+"
                    reason = f"LONG ONLY [1W/1M] | V136.1 | 1W: {w_info['reason']} | 1M: {m_info['reason']}"
                    decimals = 10 if ref_price < 0.0001 else 8 if ref_price < 0.01 else 7 if ref_price < 0.1 else 6 if ref_price < 1 else 4 if ref_price < 100 else 2

                    signal = build_signal(
                        "LONG",
                        round(plan["entry_low"], decimals),
                        round(plan["entry_high"], decimals),
                        round(plan["stop_loss"], decimals),
                        [round(plan["tp1"], decimals), round(plan["tp2"], decimals), round(plan["tp3"], decimals)],
                        total_score,
                        w_info["rsi"],
                        atr_w,
                        reason,
                        {
                            "quality": quality,
                            "trade_style": "LONG_ONLY_1W_1M",
                            "regime": "BULLISH_MACRO",
                            "adx": round(w_info["adx"], 1),
                            "tp2_rr": plan["tp2_rr"],
                            "key_support": round(levels["key_support"], decimals),
                            "deep_support": round(levels["deep_support"], decimals),
                            "resistance_low": round(levels["resistance_low"], decimals),
                            "resistance_high": round(levels["resistance_high"], decimals),
                            "timeframes": "1M + 1W + 1D (LONG ONLY)",
                            "risk_pct": plan["risk_pct"],
                            "asset_type": asset_type,
                            "1m_summary": m_info["reason"],
                            "1w_summary": w_info["reason"],
                            "1d_summary": d_info["reason"],
                        },
                    )
                    return "LONG", ref_price, signal

            return "NEUTRAL", 0.0, self._make_neutral(
                f"لا توجد فرصة شراء (LONG) أسبوعية/شهرية مكتملة حالياً ({total_score}/{self.min_score})",
                total_score,
                float(self.calculate_rsi(w1["close"]).iloc[-1]),
                atr_w,
                {"diagnostics": {"LONG": diag_long}, "best_candidate": f"LONG ({total_score}/{self.min_score})"},
            )
        except Exception as exc:
            logger.exception("Analysis error: %s", exc)
            return "NEUTRAL", 0.0, neutral
