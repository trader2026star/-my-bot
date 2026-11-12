# ============================================================
# analysis.py — StrategyEngine V108.0 (Multi-Target Pro Sniper)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900
MIN_SCORE_DEFAULT = 75


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_signal_id():
    return uuid.uuid4().hex[:16]


def build_signal(direction, entry_low, entry_high, stop_loss, take_profits, score,
                 rsi, atr, reason, details=None):
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
    def __init__(self, capital=10000.0, risk_per_trade=0.01, min_score=MIN_SCORE_DEFAULT):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)

    def calculate_rsi(self, series, period=14):
        s = pd.to_numeric(series, errors="coerce")
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        al = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    def calculate_atr(self, df, period=14):
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    def prepare_dataframe(self, candles):
        if not candles or len(candles) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        for col in ["timestamp", "open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna().drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, ohlcv_1h=None, asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry_low=0.0, entry_high=0.0, stop_loss=0.0, take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="لا توجد شروط متطابقة مع استراتيجية الأهداف المتعددة حالياً",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 40 or ohlcv_5m is None or len(ohlcv_5m) < 40:
                return "NEUTRAL", 0.0, neutral

            df_15m = self.prepare_dataframe(ohlcv_15m)
            df_5m = self.prepare_dataframe(ohlcv_5m)

            # مؤشرات فريم 15د لتحديد الزخم العام
            df_15m["RSI"] = self.calculate_rsi(df_15m["close"])
            df_15m["ATR"] = self.calculate_atr(df_15m)
            df_15m["vol_sma"] = df_15m["volume"].rolling(window=20).mean()

            price = float(df_15m["close"].iloc[-1])
            prev_price = float(df_15m["close"].iloc[-2])
            rsi = float(df_15m["RSI"].iloc[-1])
            atr = float(df_15m["ATR"].iloc[-1])

            if price <= 0 or atr <= 0:
                return "NEUTRAL", 0.0, neutral

            current_vol = float(df_15m["volume"].iloc[-1])
            avg_vol = float(df_15m["vol_sma"].iloc[-1]) if df_15m["vol_sma"].iloc[-1] > 0 else 1.0
            vol_ratio = current_vol / avg_vol
            price_change_pct = ((price - prev_price) / prev_price) * 100

            # فلتر فريم الساعة للأمان
            htf_trend = "BULLISH"
            if ohlcv_1h is not None and len(ohlcv_1h) >= 25:
                df_1h = self.prepare_dataframe(ohlcv_1h)
                ma_50 = df_1h["close"].rolling(window=30).mean().iloc[-1]
                htf_trend = "BULLISH" if float(df_1h["close"].iloc[-1]) > ma_50 else "BEARISH"

            # شروط الاكتشاف (انفجار حجمي + تحرك سعري يتوافق مع الصور)
            is_spike = vol_ratio >= 1.7
            is_valid_move = abs(price_change_pct) >= 0.4

            direction = "NEUTRAL"
            if htf_trend == "BULLISH" and is_spike and is_valid_move and price_change_pct > 0 and 40 <= rsi <= 78:
                direction = "LONG"
            elif htf_trend == "BEARISH" and is_spike and is_valid_move and price_change_pct < 0 and 22 <= rsi <= 60:
                direction = "SHORT"

            if direction == "NEUTRAL":
                return "NEUTRAL", 0.0, neutral

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

            # بناء منطقة الدخول المزدوجة والأهداف الـ 4 تماماً مثل صور "عز حائل"
            if direction == "LONG":
                entry_low = price * 0.998
                entry_high = price * 1.002
                stop_loss = price - (1.6 * atr)
                tp1 = price + (1.2 * atr)
                tp2 = price + (2.4 * atr)
                tp3 = price + (4.0 * atr)
                tp4 = price + (6.0 * atr)
                reason_text = "رصد إشارة شراء (شراء 15m) مع أهداف متسلسلة واختراق سيولة"
            else:
                entry_low = price * 0.998
                entry_high = price * 1.002
                stop_loss = price + (1.6 * atr)
                tp1 = price - (1.2 * atr)
                tp2 = price - (2.4 * atr)
                tp3 = price - (4.0 * atr)
                tp4 = price - (6.0 * atr)
                reason_text = "رصد إشارة بيع (بيع 15m) مع أهداف هابطة متسلسلة"

            tps = [round(tp1, decimals), round(tp2, decimals), round(tp3, decimals), round(tp4, decimals)]
            atr_pct = round((atr / price) * 100, 2)

            signal = build_signal(
                direction=direction,
                entry_low=round(entry_low, decimals),
                entry_high=round(entry_high, decimals),
                stop_loss=round(stop_loss, decimals),
                take_profits=tps,
                score=91,
                rsi=rsi,
                atr=atr_pct,
                reason=reason_text,
                details={
                    "volume_ratio": f"{round(vol_ratio, 1)}x",
                    "strategy_style": "عز حائل برو (15m Multi-Target)",
                    "market_structure": "اختراق هيكلي مع تأكيد الحجوم"
                }
            )
            return direction, price, signal

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return "NEUTRAL", 0.0, neutral
