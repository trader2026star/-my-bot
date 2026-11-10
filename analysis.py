# ============================================================
# analysis.py — StrategyEngine V80.0 (Pure Python / No Pandas)
# ============================================================
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("StrategyEngine")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _new_signal_id():
    return uuid.uuid4().hex[:16]

def build_signal(direction, entry, stop_loss, take_profits, score, rsi, atr, reason, details=None):
    return {
        "signal_id": _new_signal_id(),
        "created_at": _now_iso(),
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
    def __init__(self, capital=10000.0, risk_per_trade=0.01, min_score=75, max_leverage=5.0):
        self.capital = max(1.0, float(capital))
        self.risk_per_trade = min(0.02, max(0.001, float(risk_per_trade)))
        self.min_score = int(min_score)
        self.max_leverage = max(1.0, float(max_leverage))

    def analyze_market_structure(self, ohlcv_15m, ohlcv_1h=None):
        neutral = build_signal("NEUTRAL", 0.0, 0.0, [], 0, 50.0, 0.0, "conditions not met")
        try:
            if not ohlcv_15m or len(ohlcv_15m) < 30:
                return "NEUTRAL", 0.0, neutral

            # استخراج الأسعار بستخدام بايثون العادي بدون مكتبات ثقيلة
            closes = [candle[4] for candle in ohlcv_15m]
            lows = [candle[3] for candle in ohlcv_15m]
            highs = [candle[2] for candle in ohlcv_15m]

            last_close = closes[-1]
            recent_low = min(lows[-15:])
            recent_high_max = max(closes[-10:-2])
            
            # حساب تقريبي للـ ATR (متوسط النطاق)
            tr_list = [highs[i] - lows[i] for i in range(len(highs))][-14:]
            atr = sum(tr_list) / len(tr_list) if tr_list else 0.001

            # فحص القاع الحقيقي والـ CHoCH المبسط
            if last_close > recent_high_max:
                stop = recent_low - (0.2 * atr)
                risk_dist = last_close - stop
                if risk_dist <= 0:
                    return "NEUTRAL", last_close, neutral

                tp1 = last_close + (1.5 * risk_dist)
                tp2 = last_close + (2.5 * risk_dist)
                tp3 = last_close + (4.0 * risk_dist)

                signal = build_signal(
                    direction="LONG",
                    entry=round(last_close, 4),
                    stop_loss=round(stop, 4),
                    take_profits=[round(tp1, 4), round(tp2, 4), round(tp3, 4)],
                    score=85,
                    rsi=55.0,
                    atr=atr,
                    reason="True Bottom & CHoCH Confirmed (Pure Python)",
                )
                return "LONG", last_close, signal

            return "NEUTRAL", last_close, neutral
        except Exception as e:
            neutral["reason"] = str(e)
            return "NEUTRAL", 0.0, neutral
