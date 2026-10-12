# ==========================================
# BREAKOUT + STORM 101 WHALE DETECTION (HIGH FREQUENCY VERSION)
# File: analysis.py
# Compatible with current BingX/Telegram main.py
# ==========================================

import numpy as np


class StrategyEngine:
    def __init__(self):
        pass

    @staticmethod
    def is_valid_symbol(symbol):
        """منع العملات الوهمية أو الرموز التي تحتوي على أسهم تجريبية مثل AAPL أو رموز غير صالحة"""
        if not symbol or not isinstance(symbol, str):
            return True 
        symbol_upper = symbol.upper()
        
        blocked_keywords = ["AAPL", "TSLA", "GOOG", "AMZN", "MSFT", "TEST", "DEMO", "FAKE"]
        for kw in blocked_keywords:
            if kw in symbol_upper:
                return False
        
        if "NCSK" in symbol_upper or len(symbol_upper) > 30:
            return False
            
        return True

    @staticmethod
    def valid_ohlcv(data, minimum=20):
        if not isinstance(data, (list, tuple)) or len(data) < minimum:
            return False
        try:
            for candle in data:
                if len(candle) < 6:
                    return False
                values = [float(candle[i]) for i in range(1, 6)]
                if not all(np.isfinite(v) for v in values):
                    return False
                if float(candle[2]) < float(candle[3]):
                    return False
            return True
        except (TypeError, ValueError, IndexError):
            return False

    @staticmethod
    def arrays(data):
        opens = np.array([float(c[1]) for c in data], dtype=float)
        highs = np.array([float(c[2]) for c in data], dtype=float)
        lows = np.array([float(c[3]) for c in data], dtype=float)
        closes = np.array([float(c[4]) for c in data], dtype=float)
        volumes = np.array([max(0.0, float(c[5])) for c in data], dtype=float)
        return opens, highs, lows, closes, volumes

    def calculate_atr(self, highs, lows, closes, period=14):
        highs, lows, closes = map(lambda x: np.asarray(x, dtype=float),
                                  (highs, lows, closes))
        n = min(len(highs), len(lows), len(closes))
        if n < 2:
            return 0.0
        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(np.abs(highs[1:] - closes[:-1]),
                       np.abs(lows[1:] - closes[:-1]))
        )
        return float(np.mean(tr[-period:])) if len(tr) else 0.0

    @staticmethod
    def _trend(highs, lows, closes):
        highs, lows, closes = map(lambda x: np.asarray(x, dtype=float),
                                  (highs, lows, closes))
        if len(closes) < 8:
            return "NEUTRAL"
            
        fast = float(np.mean(closes[-3:]))
        slow = float(np.mean(closes[-8:-3]))
        
        if fast >= slow:
            return "LONG"
        else:
            return "SHORT"

    def _storm101_whale_check(self, opens, highs, lows, closes, volumes, direction):
        """
        منهجية STORM 101: خفيفة ومرنة لزيادة التفاعل وعدم حجب الصفقات
        """
        if len(closes) < 10:
            return True, "STORM 101: بيانات كافية للدخول"
            
        avg_vol = float(np.mean(volumes[-15:-2])) if len(volumes) >= 15 else float(np.mean(volumes[:-2]))
        recent_vol = float(volumes[-2])
        
        is_hidden_volume = recent_vol >= avg_vol * 1.1
        
        if direction == "LONG" and is_hidden_volume:
            return True, "STORM 101: رصد سيولة شرائية وتجميع حيتان"
        elif direction == "SHORT" and is_hidden_volume:
            return True, "STORM 101: رصد سيولة بيعية وتصريف حيتان"
                
        return True, "STORM 101: سيولة مقبولة للدخول"

    def _break_retest(self, opens, highs, lows, closes, volumes, direction):
        """
        كسر مباشر لمستوى الدعم أو المقاومة لآخر 10 شمعات بدون انتظار إعادة الاختبار
        """
        if len(closes) < 8:
            return False, None, "بيانات غير كافية"

        prior_high = float(np.max(highs[-10:-2]))
        prior_low = float(np.min(lows[-10:-2]))
        last_close = closes[-2]

        if direction == "LONG" and last_close >= prior_high * 0.998:
            return True, prior_high, "كسر مقاومة مباشر (Breakout)"

        elif direction == "SHORT" and last_close <= prior_low * 1.002:
            return True, prior_low, "كسر دعم مباشر (Breakdown)"

        return False, None, "لا يوجد كسر حالي"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None, symbol=""):
        details = {
            "trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL",
            "break_retest": False, "break_level": None,
            "bos": "NONE", "mss": "NONE", "sweep": "NONE",
            "fvg": "NONE", "ob_type": "NONE", "ob_zone": None,
            "volume_ratio": 0.0, "vwap_price": 0.0,
            "support": None, "resistance": None,
            "retest_advice": "جاهز للدخول",
            "entry_valid": False, "btc_trend": "UNKNOWN",
            "confirmations": [], "reasons_excluded": []
        }

        if symbol and not self.is_valid_symbol(symbol):
            details["reasons_excluded"].append(f"تم استبعاد العملة لكونها غير صالحة: {symbol}")
            return "NEUTRAL", 0, 0.0, details, ([], [], [])

        if not all(self.valid_ohlcv(x, 20) for x in (ohlcv_4h, ohlcv_1h, ohlcv_15m)):
            details["reasons_excluded"].append("بيانات غير كافية")
            return "NEUTRAL", 0, 0.0, details, ([], [], [])

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h)
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h)
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)

        trend1 = self._trend(h1[:-1], l1[:-1], c1[:-1])
        details["trend_4h"], details["trend_1h"] = trend1, trend1

        confirmations, excluded = [], []
        score = 30
        direction = trend1

        if direction != "NEUTRAL":
            score += 20
            confirmations.append("اتجاه 1H واضح")

        br_ok, br_level, br_reason = self._break_retest(
            o15[:-1], h15[:-1], l15[:-1], c15[:-1], v15[:-1], direction
        )
        
        details["break_retest"] = br_ok
        details["break_level"] = br_level
        if br_ok:
            score += 30
            confirmations.append(br_reason)

        storm_ok, storm_msg = self._storm101_whale_check(
            o15[:-1], h15[:-1], l15[:-1], c15[:-1], v15[:-1], direction
        )
        if storm_ok:
            score += 20
            confirmations.append(storm_msg)

        avg_vol = float(np.mean(v15[-22:-2])) if len(v15) >= 22 else float(np.mean(v15[:-2]))
        latest_vol = float(v15[-2])
        volume_ratio = round(latest_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        details["volume_ratio"] = volume_ratio

        # شرط الدخول أصبح مرناً جداً (Score >= 45)
        entry_valid = (
            direction in ("LONG", "SHORT")
            and (br_ok or volume_ratio >= 0.9)
            and score >= 45
        )
        
        if not entry_valid:
            signal = "NEUTRAL"
        else:
            signal = direction

        details["entry_valid"] = bool(entry_valid)
        details["confirmations"] = confirmations
        details["reasons_excluded"] = excluded

        return signal, score, volume_ratio, details, (h1.tolist(), l1.tolist(), c1.tolist())

    def calculate_risk_management(self, entry_price, direction, highs, lows, closes=None):
        entry = float(entry_price)
        direction = str(direction).upper()
        highs, lows = np.asarray(highs, float), np.asarray(lows, float)
        closes = np.asarray(closes if closes is not None else (highs + lows) / 2.0, float)
        n = min(len(highs), len(lows), len(closes))
        if entry <= 0 or n < 5:
            raise ValueError("Insufficient candles or invalid entry price")

        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        atr = self.calculate_atr(highs, lows, closes)
        if atr <= 0:
            atr = entry * 0.01

        if direction in ("LONG", "BUY"):
            stop = min(float(np.min(lows[-5:])), entry - 1.2 * atr)
            risk = entry - stop
            if risk <= 0:
                stop = entry * 0.99
                risk = entry - stop
            tp1, tp2, tp3 = entry + 1.2*risk, entry + 2.0*risk, entry + 3.2*risk
        elif direction in ("SHORT", "SELL"):
            stop = max(float(np.max(highs[-5:])), entry + 1.2 * atr)
            risk = stop - entry
            if risk <= 0:
                stop = entry * 1.01
                risk = stop - entry
            tp1, tp2, tp3 = entry - 1.2*risk, entry - 2.0*risk, entry - 3.2*risk
            if tp3 <= 0:
                tp3 = max(entry * 0.01, tp2 - risk)
        else:
            raise ValueError("Direction must be LONG or SHORT")

        sl_pct = round(abs(entry - stop) / entry * 100, 3)
        tp1_pct = round(abs(tp1 - entry) / entry * 100, 3)
        rr = round(tp1_pct / max(sl_pct, 0.001), 2)

        return (
            round(float(stop), 10), round(float(tp1), 10),
            round(float(tp2), 10), round(float(tp3), 10),
            sl_pct, tp1_pct, rr
        )
