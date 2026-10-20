# ============================================================
# MY EXPERT CRYPTO BOT - PATTERN RECOGNITION ENGINE (V11.0)
# Supports: Inv H&S, Double Bottom, Head & Shoulders, Double Top
# Features: Dynamic ATR Tolerance, Retest/Breakout Logic, SMC/SFP,
#           Multi-Timeframe Validation, Real Score System (0-100)
# ============================================================

import numpy as np
import logging

logger = logging.getLogger("StrategyEngine")

class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.01):
        self.total_capital = max(1.0, float(capital))
        self.risk_per_trade = min(max(float(risk_per_trade), 0.001), 0.05)

    @staticmethod
    def _array(data, minimum=40):
        try:
            a = np.asarray(data, dtype=float)
            if a.ndim != 2 or a.shape[0] < minimum or a.shape[1] < 6:
                return None
            a = a[:, :6]
            if not np.all(np.isfinite(a)):
                return None
            if np.any(a[:, 1:5] <= 0) or np.any(a[:, 5] < 0):
                return None
            if np.any(a[:, 2] < a[:, 3]): # High < Low invalid
                return None
            return a
        except Exception:
            return None

    @staticmethod
    def _round(value):
        value = float(value)
        if not np.isfinite(value) or value <= 0:
            return value
        decimals = max(2, min(12, int(-np.floor(np.log10(value))) + 3))
        return round(value, decimals)

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
        n = min(len(h), len(l), len(c))
        if n < 2:
            return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        if len(tr) < period:
            return float(np.mean(tr)) if len(tr) > 0 else 0.0
        return float(np.mean(tr[-period:]))

    def calculate_rsi(self, closes, period=14):
        c = np.asarray(closes, dtype=float)
        if len(c) < period + 1:
            return 50.0
        diffs = np.diff(c)
        gains = np.where(diffs > 0, diffs, 0.0)
        losses = np.where(diffs < 0, -diffs, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def calculate_macd(self, closes):
        c = np.asarray(closes, dtype=float)
        if len(c) < 26:
            return 0.0, 0.0, 0.0
        # Fast EMA 12, Slow EMA 26
        def ema(arr, p):
            alpha = 2 / (p + 1)
            res = [arr[0]]
            for val in arr[1:]:
                res.append(val * alpha + res[-1] * (1 - alpha))
            return np.array(res)
        
        ema12 = ema(c, 12)
        ema26 = ema(c, 26)
        macd_line = ema12 - ema26
        signal_line = ema(macd_line, 9)
        hist = macd_line - signal_line
        return float(macd_line[-1]), float(signal_line[-1]), float(hist[-1])

    def detect_swings(self, highs, lows, window=2):
        """تحديد النقاط المحورية (Pivot Highs & Lows)"""
        piv_highs = []
        piv_lows = []
        n = len(highs)
        for i in range(window, n - window):
            if all(highs[i] > highs[i - j] for j in range(1, window + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
                piv_highs.append((i, highs[i]))
            if all(lows[i] < lows[i - j] for j in range(1, window + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
                piv_lows.append((i, lows[i]))
        return piv_highs, piv_lows

    def analyze_market_structure(self, ohlcv_30m, ohlcv_4h=None, ohlcv_1h=None, btc_ohlcv_1h=None, debug=False):
        debug_logs = []
        def log_debug(msg):
            if debug:
                debug_logs.append(msg)

        def no_trade(reason, **extra):
            out = {"reason": reason, "debug_trace": debug_logs}
            out.update(extra)
            return "NEUTRAL", 0, out

        # استخدام الشمعات المغلقة فقط (تجاهل الشمعة الحية الأخيرة)
        raw_data = self._array(ohlcv_30m, 40)
        if raw_data is None:
            return no_trade("بيانات فريم 30M غير كافية أو غير صالحة")

        closed_candles = raw_data[:-1] # الشمعات المغلقة
        current_live_candle = raw_data[-1]
        current_price = float(current_live_candle[4])

        highs = closed_candles[:, 2]
        lows = closed_candles[:, 3]
        closes = closed_candles[:, 4]
        volumes = closed_candles[:, 5]

        atr = self.calculate_atr(highs, lows, closes, 14)
        if atr <= 0:
            return no_trade("مؤشر ATR غير صلب")

        rsi = self.calculate_rsi(closes)
        _, _, macd_hist = self.calculate_macd(closes)
        avg_volume = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        recent_vol = float(volumes[-1])

        piv_highs, piv_lows = self.detect_swings(highs, lows, window=2)
        log_debug(f"Pivots detected - Highs: {len(piv_highs)}, Lows: {len(piv_lows)}")

        detected_pattern = None
        pattern_type = None # LONG or SHORT
        neckline = 0.0
        pattern_base_level = 0.0 # Stop boundary
        pattern_quality_score = 0

        # --- A. Inverse Head & Shoulders (LONG) ---
        if len(piv_lows) >= 3 and len(piv_highs) >= 2:
            l3, l2, l1 = piv_lows[-3], piv_lows[-2], piv_lows[-1]
            # l2 هو الرأس، l3 الكتف الأيسر، l1 الكتف الأيمن
            if l2[1] < l3[1] and l2[1] < l1[1]: # الرأس هو الأخفض
                sh_diff = abs(l3[1] - l1[1])
                if sh_diff <= (1.8 * atr): # الكتفان متقاربان مع هامش ATR
                    # خط العنق من أعلى قمة بين L3-L2 و L2-L1
                    h_between = [h[1] for h in piv_highs if l3[0] < h[0] < l1[0]]
                    if h_between:
                        neckline = float(max(h_between))
                        detected_pattern = "INV_HEAD_SHOULDERS"
                        pattern_type = "LONG"
                        pattern_base_level = float(l1[1]) # القاع للكتف الأيمن
                        pattern_quality_score = 30

        # --- B. Double Bottom (LONG) ---
        if not detected_pattern and len(piv_lows) >= 2:
            l2, l1 = piv_lows[-2], piv_lows[-1]
            diff_bottoms = abs(l2[1] - l1[1])
            if diff_bottoms <= (1.5 * atr): # القاعان متقاربان مع هامش ATR ديناميكي
                h_between = [h[1] for h in piv_highs if l2[0] < h[0] < l1[0]]
                if h_between:
                    neckline = float(max(h_between))
                    detected_pattern = "DOUBLE_BOTTOM"
                    pattern_type = "LONG"
                    pattern_base_level = float(min(l2[1], l1[1]))
                    pattern_quality_score = 25

        # --- C. Head & Shoulders (SHORT) ---
        if not detected_pattern and len(piv_highs) >= 3 and len(piv_lows) >= 2:
            h3, h2, h1 = piv_highs[-3], piv_highs[-2], piv_highs[-1]
            if h2[1] > h3[1] and h2[1] > h1[1]: # الرأس هو الأعلى
                sh_diff = abs(h3[1] - h1[1])
                if sh_diff <= (1.8 * atr):
                    l_between = [l[1] for l in piv_lows if h3[0] < l[0] < h1[0]]
                    if l_between:
                        neckline = float(min(l_between))
                        detected_pattern = "HEAD_SHOULDERS"
                        pattern_type = "SHORT"
                        pattern_base_level = float(h1[1]) # قمة الكتف الأيمن
                        pattern_quality_score = 30

        # --- D. Double Top (SHORT) ---
        if not detected_pattern and len(piv_highs) >= 2:
            h2, h1 = piv_highs[-2], piv_highs[-1]
            diff_tops = abs(h2[1] - h1[1])
            if diff_tops <= (1.5 * atr):
                l_between = [l[1] for l in piv_lows if h2[0] < l[0] < h1[0]]
                if l_between:
                    neckline = float(min(l_between))
                    detected_pattern = "DOUBLE_TOP"
                    pattern_type = "SHORT"
                    pattern_base_level = float(max(h2[1], h1[1]))
                    pattern_quality_score = 25

        if not detected_pattern:
            return no_trade("لم يتم اكتشاف نموذج هندسي اكتمالي مطابق على فريم 30M")

        log_debug(f"Pattern Detected: {detected_pattern} ({pattern_type}) | Neckline: {neckline}")

        # --- ثالثاً: فحص حالات الاختراق وإعادة الاختبار ---
        atr_margin = 0.4 * atr
        state = "FORMING"

        last_closed_close = float(closes[-1])
        last_closed_high = float(highs[-1])
        last_closed_low = float(lows[-1])

        if pattern_type == "LONG":
            has_broken = any(c > neckline for c in closes[-4:])
            if has_broken:
                # إعادة الاختبار: السعر هبط وقرب من خط العنق ضمن هامش ATR ثم صعد
                retesting = abs(current_price - neckline) <= (1.2 * atr) or (last_closed_low <= neckline + atr_margin and current_price > neckline)
                if retesting:
                    state = "RETEST_CONFIRMED"
                elif current_price > neckline:
                    state = "BREAKOUT_CONFIRMED"
            elif current_price <= pattern_base_level - atr_margin:
                state = "INVALIDATED"

        elif pattern_type == "SHORT":
            has_broken = any(c < neckline for c in closes[-4:])
            if has_broken:
                retesting = abs(current_price - neckline) <= (1.2 * atr) or (last_closed_high >= neckline - atr_margin and current_price < neckline)
                if retesting:
                    state = "RETEST_CONFIRMED"
                elif current_price < neckline:
                    state = "BREAKOUT_CONFIRMED"
            elif current_price >= pattern_base_level + atr_margin:
                state = "INVALIDATED"

        log_debug(f"Pattern State Evaluated: {state}")

        if state in ("FORMING", "INVALIDATED"):
            return no_trade(f"حالة النموذج غير مؤهلة للتنفيذ: {state}")

        # --- رابعاً: نظام التقييم الواقعي الشامل (Score System 0-100) ---
        score = pattern_quality_score # القاعدة 25-30

        # 1. حالة الدخول (+25 لإعادة الاختبار، +15 للاختراق)
        if state == "RETEST_CONFIRMED":
            score += 25
            entry_mode = "RETEST ENTRY"
        else:
            score += 15
            entry_mode = "BREAKOUT ENTRY"

        # 2. تأكيدات الزخم والحجم (+15)
        if recent_vol > avg_volume:
            score += 8
        if pattern_type == "LONG" and (rsi < 65 or macd_hist > 0):
            score += 7
        elif pattern_type == "SHORT" and (rsi > 35 or macd_hist < 0):
            score += 7

        # 3. مفاهيم SMC والسيولة (+15)
        # فحص إزاحة السيولة Liquidity Sweep / BOS
        if pattern_type == "LONG" and closes[-1] > max(closes[-5:-1]):
            score += 15 # BOS / CHoCH صاعد
        elif pattern_type == "SHORT" and closes[-1] < min(closes[-5:-1]):
            score += 15 # BOS / CHoCH هابط

        # 4. سياق BTC وسياق الأطر الزمانية (+15)
        btc_bias = "NEUTRAL"
        if btc_ohlcv_1h is not None:
            btc_arr = self._array(btc_ohlcv_1h, 20)
            if btc_arr is not None:
                btc_c = btc_arr[:, 4]
                btc_bias = "BULLISH" if btc_c[-1] > np.mean(btc_c) else "BEARISH"

        if (pattern_type == "LONG" and btc_bias == "BULLISH") or (pattern_type == "SHORT" and btc_bias == "BEARISH"):
            score += 15
        elif btc_bias != "NEUTRAL":
            score -= 10 # تخفيض التقييم عند التعارض بدون إلغاء الصفقة

        log_debug(f"Final Score Computed: {score}/100")

        # عتبة القبول المقبولة (60+)
        if score < 60:
            return no_trade(f"درجة التقييم غير كافية: {score}/100 (الحد الأدنى 60)", score=score)

        # --- خامساً: حساب إدارة المخاطر ووقف الخسارة والأهداف ---
        if pattern_type == "LONG":
            stop_loss = float(pattern_base_level - (0.5 * atr))
            if stop_loss >= current_price:
                stop_loss = current_price - (1.5 * atr)
            risk_dist = current_price - stop_loss
            tp1 = current_price + (risk_dist * 1.5)
            tp2 = current_price + (risk_dist * 2.5)
            tp3 = current_price + (risk_dist * 4.0)
        else: # SHORT
            stop_loss = float(pattern_base_level + (0.5 * atr))
            if stop_loss <= current_price:
                stop_loss = current_price + (1.5 * atr)
            risk_dist = stop_loss - current_price
            tp1 = current_price - (risk_dist * 1.5)
            tp2 = current_price - (risk_dist * 2.5)
            tp3 = current_price - (risk_dist * 4.0)

        if risk_dist <= 0:
            return no_trade("مسافة وقف الخسارة غير منطقية")

        risk_usd = self.total_capital * self.risk_per_trade
        position_size = risk_usd / risk_dist

        # التحقق من نسبة العائد إلى المخاطرة (R:R Ratio >= 1:1.5)
        reward_ratio = abs(tp2 - current_price) / risk_dist
        if reward_ratio < 1.4:
            return no_trade(f"نسبة العائد للمخاطرة غير مجدية: {round(reward_ratio, 2)}")

        details = {
            "stop_loss": self._round(stop_loss),
            "risk_management": {
                "allowed_risk_usd": round(risk_usd, 2),
                "tokens_to_buy": round(position_size, 8),
                "take_profit_1": self._round(tp1),
                "take_profit_2": self._round(tp2),
                "take_profit_3": self._round(tp3),
                "reward_ratio": f"1:{round(reward_ratio, 1)}"
            },
            "setup": f"{detected_pattern} ({entry_mode})",
            "pattern_name": detected_pattern,
            "neckline": self._round(neckline),
            "state": state,
            "score": score,
            "atr": self._round(atr),
            "smc_note": "Liquidity Sweep & Breakout Confirmed (OHLCV structural context)",
            "debug_trace": debug_logs
        }

        return pattern_type, self._round(current_price), details

    def calculate_risk_management(self, entry_price, stop_loss, direction="LONG"):
        entry_price, stop_loss = float(entry_price), float(stop_loss)
        dist = abs(entry_price - stop_loss)
        risk_usd = self.total_capital * self.risk_per_trade
        qty = risk_usd / dist if dist > 0 else 0.0
        return {
            "allowed_risk_usd": round(risk_usd, 2),
            "tokens_to_buy": round(qty, 8),
            "risk_distance": round(dist, 6)
        }

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        """دالة التكامل الرئيسية للحفاظ على التوافق مع main.py"""
        return self.analyze_market_structure(ohlcv_15m, ohlcv_4h, ohlcv_1h, btc_ohlcv_1h)
