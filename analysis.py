# ============================================================
# MY EXPERT CRYPTO BOT - STRICT ANALYST ENGINE V16.2
# Strict RSI Limits + Body Ratio Guard + Dynamic ATR Buffer
# ============================================================
import numpy as np


class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01, reward_ratio=2.0):
        self.total_capital = max(0.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.02)
        self.reward_ratio = max(float(reward_ratio), 1.5)

    @staticmethod
    def _array(data, minimum=30):
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]):
                return None
            return a
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _round(value):
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    @staticmethod
    def _ema(values, period):
        values = np.asarray(values, dtype=float)
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1.0)
        out = float(values[0])
        for x in values[1:]:
            out = alpha * float(x) + (1.0 - alpha) * out
        return out

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-min(max(1, int(period)), len(tr)):])) if len(tr) else 0.0

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        try:
            entry, stop = float(entry_price), float(stop_loss_price)
            direction = str(direction).upper()
        except (TypeError, ValueError):
            return None
        if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or stop <= 0:
            return None
        if direction not in ("LONG", "SHORT") or self.total_capital <= 0:
            return None
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            return None
        distance = abs(entry - stop)
        if distance <= 0:
            return None
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / distance
        notional = qty * entry
        target = entry + distance * self.reward_ratio if direction == "LONG" else entry - distance * self.reward_ratio
        if target <= 0 or not np.isfinite(notional):
            return None
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "total_trade_value_usd": round(notional, 2),
            "take_profit_target": self._round(target),
            "reward_ratio": self.reward_ratio,
            "risk_percent": round(self.risk_per_trade * 100, 3),
        }

    def _trend(self, candles):
        closes = candles[:, 4]
        if len(closes) < 30:
            return "NEUTRAL"
        fast_now = self._ema(closes[-30:], 9)
        slow_now = self._ema(closes[-30:], 21)
        if fast_now is None or slow_now is None:
            return "NEUTRAL"
        if fast_now > slow_now and closes[-1] > slow_now:
            return "BULLISH"
        if fast_now < slow_now and closes[-1] < slow_now:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _rsi(closes, period=14):
        c = np.asarray(closes, dtype=float)
        d = np.diff(c)
        if len(d) < period:
            return 50.0
        gains = np.maximum(d, 0.0)
        losses = np.maximum(-d, 0.0)
        ag = float(np.mean(gains[-period:]))
        al = float(np.mean(losses[-period:]))
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return float(100.0 - 100.0 / (1.0 + ag / al))

    @staticmethod
    def _pivots(highs, lows, left=3, right=3):
        ph, pl = [], []
        for i in range(left, len(highs) - right):
            hwindow = highs[i-left:i+right+1]
            lwindow = lows[i-left:i+right+1]
            if highs[i] == np.max(hwindow) and np.count_nonzero(hwindow == highs[i]) == 1:
                ph.append((i, float(highs[i])))
            if lows[i] == np.min(lwindow) and np.count_nonzero(lwindow == lows[i]) == 1:
                pl.append((i, float(lows[i])))
        return ph, pl

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        def no_trade(reason, **extra):
            out = {"reason": reason}
            out.update(extra)
            return "NEUTRAL", 0, out

        raw4 = self._array(ohlcv_4h, 30)
        raw1 = self._array(ohlcv_1h, 30)
        raw15 = self._array(ohlcv_15m, 50)
        if raw4 is None or raw1 is None or raw15 is None:
            return no_trade("Invalid or insufficient OHLCV data")

        try:
            c4, c1, c15 = raw4[:-1], raw1[:-1], raw15[:-1]
            trend4, trend1 = self._trend(c4), self._trend(c1)
            if trend4 != trend1 or trend1 == "NEUTRAL":
                return no_trade("Multi-timeframe trend disagreement", trend_4h=trend4, trend_1h=trend1)

            btc_trend = "NOT_PROVIDED"
            if btc_ohlcv_1h is not None:
                btc = self._array(btc_ohlcv_1h, 30)
                if btc is not None:
                    btc_trend = self._trend(btc[:-1])
                    if btc_trend != trend1:
                        return no_trade("BTC trend filter mismatch")

            op, hi, lo, cl, vol = (c15[:, i] for i in (1, 2, 3, 4, 5))
            entry = float(cl[-1])
            atr = self.calculate_atr(hi, lo, cl, 14)
            rsi = self._rsi(cl, 14)

            direction = "LONG" if trend1 == "BULLISH" else "SHORT"

            # 🛑 1. حظر الشراء في القمم (منع LONG لو الـ RSI أعلى من 62)
            if direction == "LONG" and (rsi > 62.0 or rsi < 45.0):
                return no_trade("RSI Overbought/Unfavorable for LONG", rsi=round(rsi, 1))
            if direction == "SHORT" and (rsi < 38.0 or rsi > 55.0):
                return no_trade("RSI Oversold/Unfavorable for SHORT", rsi=round(rsi, 1))

            # 🛑 2. فلتر جسم الشمعة لمنع الشمعات الضعيفة والترددية
            candle_range = max(float(hi[-1] - lo[-1]), 1e-12)
            body_ratio = abs(float(cl[-1] - op[-1])) / candle_range
            if body_ratio < 0.45:
                return no_trade("Candle body too weak (indecision candle)")

            piv_hi, piv_lo = self._pivots(hi, lo, 3, 3)
            if len(piv_hi) < 2 or len(piv_lo) < 2:
                return no_trade("Insufficient swing pivots")

            # BOS Detection
            bos = False
            break_level = None
            for i in range(len(cl) - 15, len(cl) - 1):
                if direction == "LONG" and piv_hi:
                    lvl = piv_hi[-1][1]
                    if cl[i] > lvl and cl[i-1] <= lvl:
                        bos, break_level = True, float(lvl)
                elif direction == "SHORT" and piv_lo:
                    lvl = piv_lo[-1][1]
                    if cl[i] < lvl and cl[i-1] >= lvl:
                        bos, break_level = True, float(lvl)

            if not bos:
                return no_trade("No confirmed BOS setup")

            # Retest validation
            retest = False
            for j in range(len(cl) - 4, len(cl)):
                if direction == "LONG" and lo[j] <= break_level + 0.1 * atr and cl[-1] > break_level:
                    retest = True
                elif direction == "SHORT" and hi[j] >= break_level - 0.1 * atr and cl[-1] < break_level:
                    retest = True

            if not retest:
                return no_trade("Waiting for valid structure retest")

            # 🛑 3. توسيع الستوب حمايةً من التذبذب اللحظي
            if direction == "LONG":
                stop = min(lo[-5:]) - 0.35 * atr
            else:
                stop = max(hi[-5:]) + 0.35 * atr

            risk = self.calculate_position_size(entry, stop, direction)
            if not risk:
                return no_trade("Risk calculation failed")

            details = {
                "stop_loss": self._round(stop),
                "risk_management": risk,
                "setup": "Strict Balanced SMC BOS + Retest",
                "score": 90,
                "trend_4h": trend4,
                "trend_1h": trend1,
                "btc_trend": btc_trend,
                "bos": True,
                "breakout_level": self._round(break_level),
                "retest_confirmed": True,
                "rsi": round(rsi, 1),
                "atr": self._round(atr)
            }
            return direction, self._round(entry), details

        except Exception as e:
            return no_trade(f"Error: {str(e)[:50]}")

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        return self.analyze_market_structure(ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h)
