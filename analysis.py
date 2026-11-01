# ============================================================
# MY EXPERT CRYPTO BOT - V73.0 Institutional Advanced Engine
# LONG ONLY | FULL INDICATOR SCORING & DETAILED REJECTION
# ============================================================

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")


class StrategyEngine:
    def __init__(self, capital=10000.0, risk_per_trade=0.01):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = 80
        self.swing_order = 3

    def calculate_rsi(self, series, period=14):
        s = pd.to_numeric(series, errors="coerce")
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        al = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        out = 100 - 100 / (1 + rs)
        out = out.mask((al == 0) & (ag > 0), 100)
        out = out.mask((ag == 0) & (al > 0), 0)
        return out.fillna(50)

    def calculate_atr(self, df, period=14):
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        fallback = max(float(c.iloc[-1]) * 0.015, 1e-12)
        return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().fillna(fallback)

    def prepare_dataframe(self, candles):
        df = pd.DataFrame(candles, columns=[
            "timestamp", "open", "high", "low", "close", "volume"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan).dropna()
        df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
        return df.reset_index(drop=True)

    def find_swing_lows(self, low_series, order=3):
        vals = np.asarray(low_series, dtype=float)
        out = []
        for i in range(order, len(vals) - order):
            w = vals[i-order:i+order+1]
            if vals[i] == np.min(w) and np.sum(w == vals[i]) == 1:
                out.append(i)
        return out

    def find_swing_highs(self, high_series, order=3):
        vals = np.asarray(high_series, dtype=float)
        out = []
        for i in range(order, len(vals) - order):
            w = vals[i-order:i+order+1]
            if vals[i] == np.max(w) and np.sum(w == vals[i]) == 1:
                out.append(i)
        return out

    def detect_divergence(self, df):
        lows = self.find_swing_lows(df["low"], self.swing_order)
        result = {"regular": False, "hidden": False, "price_previous": 0.0,
                  "price_recent": 0.0, "rsi_previous": 50.0, "rsi_recent": 50.0}
        if len(lows) < 2:
            return result
        p, r = lows[-2], lows[-1]
        if r - p > 35 or len(df) - 1 - r > 12:
            return result
        pp, pr = float(df["low"].iloc[p]), float(df["low"].iloc[r])
        rp, rr = float(df["RSI"].iloc[p]), float(df["RSI"].iloc[r])
        result.update({
            "regular": bool(pr < pp * 0.999 and rr > rp + 2 and rr < 55),
            "hidden": bool(pr > pp * 1.001 and rr < rp - 2 and rr < 55),
            "price_previous": pp, "price_recent": pr,
            "rsi_previous": rp, "rsi_recent": rr
        })
        return result

    def detect_sweep(self, df):
        if len(df) < 12:
            return False
        reference_low = float(df["low"].iloc[-9:-2].min())
        candle = df.iloc[-1]
        return bool(candle["low"] < reference_low and candle["close"] > reference_low)

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
        return bool(ratio >= 1.2), round(ratio, 2)

    def confirm_5m(self, candles):
        if candles is None or len(candles) < 25:
            return False, 50.0
        df = self.prepare_dataframe(candles)
        if len(df) > 1:
            df = df.iloc[:-1].reset_index(drop=True)
        if len(df) < 20:
            return False, 50.0
        rsi = self.calculate_rsi(df["close"])
        last, prev = df.iloc[-1], df.iloc[-2]
        ok = bool(last["close"] > last["open"] and last["close"] > prev["high"]
                  and 35 <= float(rsi.iloc[-1]) <= 75)
        return ok, float(rsi.iloc[-1])

    def calculate_score(self, regular, hidden, sweep, structure, rsi,
                        volume_ok, candle_ok, trend_ok):
        score = 25 if regular else (15 if hidden else 5)
        score += 15 if sweep else 0
        score += 20 if structure else 0
        score += 15 if 30 <= rsi <= 50 else (10 if 50 < rsi <= 60 else 5)
        score += 10 if volume_ok else 0
        score += 10 if candle_ok else 0
        score += 5 if trend_ok else 0
        return min(100, max(10, score))

    def calculate_risk_management(self, entry, atr, swing_low=None):
        entry, atr = float(entry), float(atr)
        if entry <= 0 or atr <= 0:
            return {"valid": False, "reason": "بيانات السعر أو ATR غير صالحة"}
        atr_stop = entry - 1.8 * atr
        stop = atr_stop
        if swing_low is not None and 0 < float(swing_low) < entry:
            stop = min(atr_stop, float(swing_low) - 0.2 * atr)
        distance = entry - stop
        pct = distance / entry
        if distance <= 0 or pct < 0.001 or pct > 0.08:
            return {"valid": False, "reason": f"مسافة وقف الخسارة غير مناسبة ({pct*100:.2f}%)"}
        risk_cash = self.capital * self.risk_per_trade
        qty = risk_cash / distance
        return {
            "valid": True, "stop_loss": stop, "risk_pct": pct * 100,
            "risk_amount": risk_cash, "position_size": qty,
            "take_profit_1": entry + distance * 1.5,
            "take_profit_2": entry + distance * 2.5,
            "take_profit_3": entry + distance * 3.5
        }

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, asset_type="crypto"):
        default = {
            "trade_valid": False, "trigger_price": 0.0, "stop_loss": 0.0,
            "atr": 0.0, "rsi": 50.0, "score": 15, "direction": "NEUTRAL",
            "entry_zone": {}, "risk_management": {},
            "reason": "لم يتم استيفاء شروط الدخول الأساسية."
        }
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 65:
                default["reason"] = "بيانات 15M غير كافية على المنصة."
                return "NEUTRAL", 0.0, default
            
            df = self.prepare_dataframe(ohlcv_15m)
            if len(df) > 1:
                df = df.iloc[:-1].reset_index(drop=True)
            if len(df) < 60:
                default["reason"] = "بيانات الشموع المتاحة غير كافية بعد التصفية."
                return "NEUTRAL", 0.0, default

            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)
            price = float(df["close"].iloc[-1])
            atr = float(df["ATR"].iloc[-1])
            rsi = float(df["RSI"].iloc[-1])

            if price <= 0 or atr <= 0 or not np.isfinite([price, atr, rsi]).all():
                default["reason"] = "قيم الأسعار أو المؤشرات غير صالحة (NaN/Inf)."
                return "NEUTRAL", 0.0, default

            div = self.detect_divergence(df)
            regular, hidden = div["regular"], div["hidden"]
            sweep = self.detect_sweep(df)
            structure = self.detect_bullish_structure(df)
            volume_ok, volume_ratio = self.detect_volume(df)
            candle_ok, rsi_5m = self.confirm_5m(ohlcv_5m)
            
            ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(df["close"].ewm(span=50, adjust=False).mean().iloc[-1])
            trend_ok = price > ema20 and ema20 > ema50

            score = self.calculate_score(
                regular, hidden, sweep, structure, rsi,
                volume_ok, candle_ok, trend_ok
            )

            # تحديد سبب الرفض بدقة تامة
            reasons = []
            if not regular:
                reasons.append("لا يوجد دايفيرجنس إيجابي واضح")
            if not candle_ok:
                reasons.append("شمعة التأكيد على فريم 5 دقائق غير مكتملة")
            if not (sweep or structure):
                reasons.append("لم يحدث سحب سيولة (Sweep) أو كسر هيكلي صاعد (BOS)")
            if score < self.min_score:
                reasons.append(f"التقييم الفني الحالي ({score}/100) أقل من الحد الأدنى المقبول ({self.min_score})")

            valid = bool(regular and candle_ok and (sweep or structure) and score >= self.min_score)

            risk = {}
            if valid:
                risk = self.calculate_risk_management(price, atr, div["price_recent"])
                if not risk.get("valid"):
                    valid = False
                    reasons.append(risk.get("reason", "خطأ في حسابات إدارة المخاطر"))

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            rm = {}
            if valid:
                rm = {
                    k: (round(v, decimals) if isinstance(v, (int, float)) else v)
                    for k, v in risk.items()
                }

            reason_text = "تم استيفاء كافة الشروط بنجاح ودخلت الصفقة في النطاق المثالي." if valid else " | ".join(reasons)

            details = {
                "trade_valid": valid,
                "direction": "LONG" if valid else "NEUTRAL",
                "trigger_price": round(price, decimals),
                "stop_loss": rm.get("stop_loss", 0.0),
                "atr": round(atr, decimals),
                "rsi": round(rsi, 2),
                "score": score,
                "entry_zone": {
                    "divergence_detected": regular or hidden,
                    "regular_bullish": regular,
                    "hidden_bullish": hidden,
                    "liquidity_sweep": sweep,
                    "bullish_structure": structure,
                    "volume_confirmed": volume_ok,
                    "volume_ratio": volume_ratio,
                    "confirmed_5m": candle_ok,
                    "rsi_5m": round(rsi_5m, 2),
                    "trend_confirmed": trend_ok,
                    "swing_low": round(div["price_recent"], decimals) if div["price_recent"] > 0 else 0.0
                },
                "risk_management": rm,
                "reason": reason_text
            }
            return ("LONG" if valid else "NEUTRAL"), price, details
        except Exception as exc:
            logger.exception("V73 analysis error: %s", exc)
            return "NEUTRAL", 0.0, default
