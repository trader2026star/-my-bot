# ============================================================
# analysis.py — StrategyEngine V120.0 (Swing Accumulation Style)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 86400  # صفقات سوينغ تمتد لفترة أطول
MIN_SCORE_DEFAULT = 70


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
    def __init__(self, capital=10000.0, risk_per_trade=0.02, min_score=MIN_SCORE_DEFAULT):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.03, max(0.005, float(risk_per_trade)))
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

    def analyze_market_structure(self, ohlcv_daily, ohlcv_4h=None, ohlcv_1h=None, asset_type="crypto"):
        neutral = build_signal(
            direction="NEUTRAL", entry_low=0.0, entry_high=0.0, stop_loss=0.0, take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="لا توجد فرصة تجميع سوينغ مكتملة حالياً",
        )
        try:
            if ohlcv_daily is None or len(ohlcv_daily) < 30:
                return "NEUTRAL", 0.0, neutral

            df = self.prepare_dataframe(ohlcv_daily)
            df["RSI"] = self.calculate_rsi(df["close"])
            df["ATR"] = self.calculate_atr(df)

            price = float(df["close"].iloc[-1])
            low_price = float(df["low"].min())
            rsi = float(df["RSI"].iloc[-1])
            atr = float(df["ATR"].iloc[-1])

            if price <= 0 or atr <= 0:
                return "NEUTRAL", 0.0, neutral

            # استراتيجية التجميع: البحث عن العملات القريبة من قيعانها التاريخية أو التي كوّنت قاعدة دعم قوية وتستعد للانطلاق الصاعد
            recent_drop_check = float(df["close"].iloc[-30])  # السعر قبل 30 شمعة
            is_accumulating = price <= (recent_drop_check * 1.3) and rsi < 55

            if not is_accumulating and rsi > 75:
                return "NEUTRAL", 0.0, neutral

            direction = "LONG"  # التركيز بالكامل على فرص الشراء والتجميع كما طلبت
            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))

            # حساب منطقة الدخول، وقف الخسارة تحت القاع، والأهداف البعيدة المتسلسلة
            entry_low = price * 0.99
            entry_high = price * 1.01
            stop_loss = max(price * 0.75, float(df["low"].tail(20).min()) * 0.95)  # وقف خسارة آمن تحت القاع
            
            tp1 = price * 1.25  # الهدف الأول (~25% صعود)
            tp2 = price * 1.55  # الهدف الثاني
            tp3 = price * 1.90  # الهدف الثالث

            tps = [round(tp1, decimals), round(tp2, decimals), round(tp3, decimals)]
            atr_pct = round((atr / price) * 100, 2)

            signal = build_signal(
                direction=direction,
                entry_low=round(entry_low, decimals),
                entry_high=round(entry_high, decimals),
                stop_loss=round(stop_loss, decimals),
                take_profits=tps,
                score=88,
                rsi=rsi,
                atr=atr_pct,
                reason="فرصة شراء وتجميع سوينغ (Accumulation / Swing Reversal)",
                details={"tf": "Daily Swing", "leverage": "20x"}
            )
            return direction, price, signal

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return "NEUTRAL", 0.0, neutral
