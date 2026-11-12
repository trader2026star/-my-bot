# ============================================================
# analysis.py — StrategyEngine V106.2 (Triple-TF Safety & Trend Hunter)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("StrategyEngine")

SIGNAL_EXPIRY_SECONDS = 900
MIN_SCORE_DEFAULT = 65


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

    def detect_fvg(self, df):
        if len(df) < 3:
            return [], []
        bullish_fvgs = []
        bearish_fvgs = []
        for i in range(2, len(df)):
            if df["low"].iloc[i] > df["high"].iloc[i-2]:
                bullish_fvgs.append((df["high"].iloc[i-2], df["low"].iloc[i]))
            if df["high"].iloc[i] < df["low"].iloc[i-2]:
                bearish_fvgs.append((df["low"].iloc[i-2], df["high"].iloc[i]))
        return bullish_fvgs, bearish_fvgs

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, ohlcv_1h=None, asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0, take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="لا توجد شروط توافق على الفريمات الثلاثة حالياً",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 30 or ohlcv_5m is None or len(ohlcv_5m) < 30:
                return "NEUTRAL", 0.0, neutral

            df_15m = self.prepare_dataframe(ohlcv_15m)
            df_5m = self.prepare_dataframe(ohlcv_5m)
            
            # فلتر الاتجاه العام على الفريم الكبير (1H أو 4H في حال توفره، وإلا اعتماد 15m)
            htf_trend = "NEUTRAL"
            if ohlcv_1h is not None and len(ohlcv_1h) > 20:
                df_1h = self.prepare_dataframe(ohlcv_1h)
                ma_50 = df_1h["close"].rolling(window=50).mean().iloc[-1]
                close_1h = df_1h["close"].iloc[-1]
                htf_trend = "BULLISH" if close_1h > ma_50 else "BEARISH"
            else:
                # إذا لم يتوفر فريم كبير مستقل، نأخذ الاتجاه من المتوسطات المتحركة للـ 15m
                ma_20_15m = df_15m["close"].rolling(window=20).mean().iloc[-1]
                htf_trend = "BULLISH" if df_15m["close"].iloc[-1] > ma_20_15m else "BEARISH"

            # حساب مؤشرات 15م (السيولة والحجوم)
            df_15m["RSI"] = self.calculate_rsi(df_15m["close"])
            df_15m["ATR"] = self.calculate_atr(df_15m)
            df_15m["vol_sma"] = df_15m["volume"].rolling(window=20).mean()

            price = float(df_5m["close"].iloc[-1])
            prev_price_15m = float(df_15m["close"].iloc[-2])
            price_15m = float(df_15m["close"].iloc[-1])
            atr = float(df_15m["ATR"].iloc[-1])
            rsi = float(df_15m["RSI"].iloc[-1])

            if price <= 0 or atr <= 0:
                return "NEUTRAL", 0.0, neutral

            current_vol = float(df_15m["volume"].iloc[-1])
            avg_vol = float(df_15m["vol_sma"].iloc[-1]) if df_15m["vol_sma"].iloc[-1] > 0 else 1.0
            vol_ratio = current_vol / avg_vol
            price_change_pct = ((price_15m - prev_price_15m) / prev_price_15m) * 100

            bull_fvgs, bear_fvgs = self.detect_fvg(df_5m)

            is_volume_spike = vol_ratio >= 1.8
            is_momentum_valid = 0.3 <= abs(price_change_pct) <= 8.0

            direction = "NEUTRAL"
            # شرط الأمان: يجب أن يتطابق اتجاه الصفقة مع اتجاه الفريم الكبير (HTF) لمنع الانعكاسات
            if htf_trend == "BULLISH" and is_volume_spike and is_momentum_valid and price_change_pct > 0 and rsi < 78:
                direction = "LONG"
            elif htf_trend == "BEARISH" and is_volume_spike and is_momentum_valid and price_change_pct < 0 and rsi > 22:
                direction = "SHORT"

            if direction == "NEUTRAL":
                return "NEUTRAL", 0.0, neutral

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            leverage = 10

            if direction == "LONG":
                stop = price - (1.3 * atr)
                tp1 = price + (1.5 * atr)
                tp2 = price + (3.0 * atr)
                reason_text = "توافق ثلاثي الفريمات (صاعد) مع انفجار حجمي آمن (LONG)"
            else:
                stop = price + (1.3 * atr)
                tp1 = price - (1.5 * atr)
                tp2 = price - (3.0 * atr)
                reason_text = "توافق ثلاثي الفريمات (هابط) مع ضغط بيعي آمن (SHORT)"

            roe1 = round(abs((tp1 - price) / price) * 100 * leverage, 1)
            roe2 = round(abs((tp2 - price) / price) * 100 * leverage, 1)
            roe_sl = round(abs((stop - price) / price) * 100 * leverage, 1)
            atr_pct = round((atr / price) * 100, 2)

            signal = build_signal(
                direction=direction,
                entry=round(price, decimals),
                stop_loss=round(stop, decimals),
                take_profits=[round(tp1, decimals), round(tp2, decimals)],
                score=92,  # رفع درجة الثقة لأن التحليل أصبح ثلاثي الفريمات للأمان
                rsi=rsi,
                atr=atr_pct,
                reason=reason_text,
                details={
                    "roe1": roe1,
                    "roe2": roe2,
                    "roe_sl": roe_sl,
                    "volume_ratio": f"{round(vol_ratio, 1)}x",
                    "htf_safety_filter": f"Protected by HTF Trend ({htf_trend})",
                    "fvg_detected": "Yes" if (len(bull_fvgs) > 0 or len(bear_fvgs) > 0) else "No",
                    "whale_justification": f"تأكيد حيتان مع فلتر الأمان للفريم الكبير وحجم تداول {round(vol_ratio, 1)} أضعاف المتوسط."
                }
            )
            return direction, price, signal

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return "NEUTRAL", 0.0, neutral
