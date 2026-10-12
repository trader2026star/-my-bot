# ==========================================
# BREAKOUT + RETEST STRATEGY ENGINE + STORM 101 WHALE DETECTION
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
        if len(closes) < 12:
            return "NEUTRAL"
        recent_high = float(np.max(highs[-6:-1]))
        recent_low = float(np.min(lows[-6:-1]))
        
        fast = float(np.mean(closes[-5:]))
        slow = float(np.mean(closes[-12:-5]))
        
        if fast > slow and closes[-1] > recent_high * 0.99:
            return "LONG"
        if fast < slow and closes[-1] < recent_low * 1.01:
            return "SHORT"
        return "NEUTRAL"

    def _storm101_whale_check(self, opens, highs, lows, closes, volumes, direction):
        """
        منهجية STORM 101: رصد تجميع الحيتان، كشف التلاعب، وتتبع حجم التداول المخفي الاستباقي[span_1](start_span)[span_1](end_span)
        """
        if len(closes) < 10:
            return False, "بيانات غير كافية لفحص الحيتان"
            
        avg_vol = float(np.mean(volumes[-15:-2])) if len(volumes) >= 15 else float(np.mean(volumes[:-2]))
        recent_vol = float(volumes[-2])
        
        # رصد الحجم المخفي المرتفع غير المبرر كلاسيكياً
        is_hidden_volume = recent_vol >= avg_vol * 1.4
        
        if direction == "LONG":
            # كشف تجميع الحيتان: هبوط مظلل أو ضغط سعري يعقبه فوليوم مخفي وارتداد قوي للأعلى[span_2](start_span)[span_2](end_span)
            is_accumulation = lows[-2] <= float(np.min(lows[-6:-2])) and closes[-2] > opens[-2]
            if is_hidden_volume and is_accumulation:
                return True, "STORM 101: رصد تجميع الحيتان وحجم التداول المخفي عند القاع استعداداً للصعود[span_3](start_span)[span_3](end_span)"
        elif direction == "SHORT":
            # كشف تصريف الحيتان: صعود وهمي يعقبه فوليوم مخفي وهبوط قوي للأسفل[span_4](start_span)[span_4](end_span)
            is_distribution = highs[-2] >= float(np.max(highs[-6:-2])) and closes[-2] < opens[-2]
            if is_hidden_volume and is_distribution:
                return True, "STORM 101: رصد تصريف الحيتان وحجم التداول المخفي عند القمة استعداداً للهبوط[span_5](start_span)[span_5](end_span)"
                
        return False, "لا توجد بصمات واضحة لتجميع/تصريف الحيتان"

    def _break_retest(self, opens, highs, lows, closes, volumes, direction):
        if len(closes) < 8:
            return False, None, "بيانات شموع غير كافية"

        search_start = max(3, len(closes) - 6)
        for i in range(search_start, len(closes) - 1):
            prior_start = max(0, i - 20)
            prior_high = float(np.max(highs[prior_start:i]))
            prior_low = float(np.min(lows[prior_start:i]))
            candle_range = max(float(highs[i] - lows[i]), 1e-12)
            body = abs(float(closes[i] - opens[i]))
            volume_base = float(np.mean(volumes[max(0, i-12):i])) if i > 0 else 0.0
            volume_ok = volume_base <= 0 or volumes[i] >= volume_base * 0.9

            if direction == "LONG":
                broke = closes[i] > prior_high and closes[i] > opens[i]
                if not broke or not volume_ok or body / candle_range < 0.35:
                    continue
                level = prior_high
                j = len(closes) - 1
                tolerance = max(level * 0.003, (highs[j] - lows[j]) * 0.25)
                retested = lows[j] <= level + tolerance and lows[j] >= level - tolerance * 2
                rejected = closes[j] > level and closes[j] >= opens[j]
                if retested and rejected:
                    return True, level, "كسر مقاومة وإعادة اختبار صاعد ناجحة"

            elif direction == "SHORT":
                broke = closes[i] < prior_low and closes[i] < opens[i]
                if not broke or not volume_ok or body / candle_range < 0.35:
                    continue
                level = prior_low
                j = len(closes) - 1
                tolerance = max(level * 0.003, (highs[j] - lows[j]) * 0.25)
                retested = highs[j] >= level - tolerance and highs[j] <= level + tolerance * 2
                rejected = closes[j] < level and closes[j] <= opens[j]
                if retested and rejected:
                    return True, level, "كسر دعم وإعادة اختبار هابط ناجحة"

        return False, None, "لم يكتمل كسر المستوى وإعادة الاختبار"

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None, symbol=""):
        details = {
            "trend_4h": "NEUTRAL", "trend_1h": "NEUTRAL",
            "break_retest": False, "break_level": None,
            "bos": "NONE", "mss": "NONE", "sweep": "NONE",
            "fvg": "NONE", "ob_type": "NONE", "ob_zone": None,
            "volume_ratio": 0.0, "vwap_price": 0.0,
            "support": None, "resistance": None,
            "retest_advice": "بيانات غير كافية",
            "entry_valid": False, "btc_trend": "UNKNOWN",
            "confirmations": [], "reasons_excluded": []
        }

        if symbol and not self.is_valid_symbol(symbol):
            details["reasons_excluded"].append(f"تم استبعاد العملة لكونها وهمية أو تحتوي على رموز أسهم: {symbol}")
            return "NEUTRAL", 0, 0.0, details, ([], [], [])

        if not all(self.valid_ohlcv(x, 20) for x in (ohlcv_4h, ohlcv_1h, ohlcv_15m)):
            details["reasons_excluded"].append("بيانات غير كافية أو غير صالحة")
            return "NEUTRAL", 0, 0.0, details, ([], [], [])

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h)
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h)
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)

        trend4 = self._trend(h4[:-1], l4[:-1], c4[:-1])
        trend1 = self._trend(h1[:-1], l1[:-1], c1[:-1])
        details["trend_4h"], details["trend_1h"] = trend4, trend1

        confirmations, excluded = [], []
        score = 20
        direction = "NEUTRAL"

        if trend4 != "NEUTRAL" and trend4 == trend1:
            direction = trend1
            score += 20
            confirmations.append("اتجاه 4H و1H متوافق (Trend Alignment)")
        else:
            excluded.append("اتجاه 4H و1H غير متوافق أو غير واضح")

        br_ok, br_level, br_reason = self._break_retest(
            o15[:-1], h15[:-1], l15[:-1], c15[:-1], v15[:-1], direction
        ) if direction != "NEUTRAL" else (False, None, "الاتجاه العام غير واضح")
        
        details["break_retest"] = br_ok
        details["break_level"] = br_level
        if br_ok:
            score += 25
            confirmations.append(br_reason)
        else:
            excluded.append(br_reason)

        # دمج تحقق STORM 101 للحيتان والحجم المخفي
        if direction != "NEUTRAL":
            storm_ok, storm_msg = self._storm101_whale_check(
                o15[:-1], h15[:-1], l15[:-1], c15[:-1], v15[:-1], direction
            )
            if storm_ok:
                score += 15
                confirmations.append(storm_msg)
            else:
                excluded.append(storm_msg)

        bos = "NONE"
        if len(c1) >= 12:
            ref_hi = float(np.max(h1[-9:-2]))
            ref_lo = float(np.min(l1[-9:-2]))
            if c1[-2] > ref_hi:
                bos = "BULLISH_BOS"
            elif c1[-2] < ref_lo:
                bos = "BEARISH_BOS"
        details["bos"] = bos
        
        if (direction == "LONG" and bos == "BULLISH_BOS") or (direction == "SHORT" and bos == "BEARISH_BOS"):
            score += 10
            confirmations.append(f"SMC - كسر هيكل متوافق مع الاتجاه: {bos}")
        else:
            excluded.append("لا يوجد كسر هيكل ساعة داعم للاتجاه")

        avg_vol = float(np.mean(v15[-22:-2])) if len(v15) >= 22 else float(np.mean(v15[:-2]))
        latest_vol = float(v15[-2])
        volume_ratio = round(latest_vol / avg_vol, 2) if avg_vol > 0 else 0.0
        details["volume_ratio"] = volume_ratio
        if volume_ratio >= 1.25:
            score += 10
            confirmations.append(f"فوليوم 15M قوي ({volume_ratio}x)")
        else:
            excluded.append(f"الفوليوم غير كافٍ ({volume_ratio}x)")

        n = min(24, len(c1) - 1)
        typical = (h1[-n-1:-1] + l1[-n-1:-1] + c1[-n-1:-1]) / 3
        vwap_vol = v1[-n-1:-1]
        vwap = float(np.sum(typical * vwap_vol) / np.sum(vwap_vol)) if np.sum(vwap_vol) > 0 else float(c1[-2])
        details["vwap_price"] = vwap
        last_price = float(c15[-2])
        
        if direction == "LONG" and last_price > vwap:
            score += 5
            confirmations.append("السعر أعلى VWAP المرجعي")
        elif direction == "SHORT" and last_price < vwap:
            score += 5
            confirmations.append("السعر أسفل VWAP المرجعي")
        else:
            excluded.append("موقع السعر بالنسبة لـ VWAP غير مناسب للاتجاه")

        score = int(max(0, min(100, score)))
        bos_ok = (
            (direction == "LONG" and bos == "BULLISH_BOS") or
            (direction == "SHORT" and bos == "BEARISH_BOS")
        )
        entry_valid = (
            direction in ("LONG", "SHORT")
            and br_ok
            and volume_ratio >= 1.25
            and bos_ok
        )
        
        if not entry_valid or score < 75:
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
            stop = min(float(np.min(lows[-5:])), entry - 1.3 * atr)
            risk = entry - stop
            if risk <= 0:
                raise ValueError("Invalid LONG stop")
            tp1, tp2, tp3 = entry + 1.5*risk, entry + 2.5*risk, entry + 4*risk
        elif direction in ("SHORT", "SELL"):
            stop = max(float(np.max(highs[-5:])), entry + 1.3 * atr)
            risk = stop - entry
            if risk <= 0:
                raise ValueError("Invalid SHORT stop")
            tp1, tp2, tp3 = entry - 1.5*risk, entry - 2.5*risk, entry - 4*risk
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
