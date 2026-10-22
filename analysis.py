# ============================================================
# MY EXPERT CRYPTO BOT - PATTERN RECOGNITION ENGINE (V11.1)
# Supports: Inv H&S, Double Bottom, Head & Shoulders, Double Top
# Features: Dynamic ATR Tolerance, Strict Retest/Breakout Logic,
#           Real SMC (Sweep, BOS, CHoCH, FVG, OB), Multi-TF (4H, 1H, 15M, BTC),
#           Calibrated Scoring (0-100), Robust Risk Management & Debug Logs.
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
            if np.any(a[:, 2] < a[:, 3]):  # High < Low invalid
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

    def detect_swings(self, highs, lows, window=3):
        """تحديد النقاط المحورية (Pivot Highs & Lows) بدقة زمنية صحيحة"""
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

    def analyze_smc_structure(self, closed_candles, atr):
        """تحليل فعلي للسيولة ومفاهيم الـ SMC من البيانات السعرية المغلقة"""
        highs = closed_candles[:, 2]
        lows = closed_candles[:, 3]
        closes = closed_candles[:, 4]
        opens = closed_candles[:, 0]
        
        smc_data = {
            "liquidity_sweep": False,
            "bos": False,
            "choch": False,
            "fvg_detected": False,
            "order_block": False,
            "details": []
        }

        if len(closes) < 15:
            return smc_data

        recent_high = max(highs[-15:-3])
        recent_low = min(lows[-15:-3])
        last_high = highs[-1]
        last_low = lows[-1]
        last_close = closes[-1]
        last_open = opens[-1]

        # 1. Liquidity Sweep: اختراق وهمي لقمة أو قاع سابق ثم إغلاق عكسي
        if last_high > recent_high and last_close < recent_high:
            smc_data["liquidity_sweep"] = True
            smc_data["details"].append("Bearish Liquidity Sweep above recent highs")
        elif last_low < recent_low and last_close > recent_low:
            smc_data["liquidity_sweep"] = True
            smc_data["details"].append("Bullish Liquidity Sweep below recent lows")

        # 2. BOS / CHoCH: كسر البنية وتغيير اتجاه السوق
        prev_swing_highs, prev_swing_lows = self.detect_swings(highs[:-1], lows[:-1], window=2)
        if prev_swing_highs and last_close > prev_swing_highs[-1][1]:
            smc_data["bos"] = True
            smc_data["details"].append("Bullish BOS confirmed")
        elif prev_swing_lows and last_close < prev_swing_lows[-1][1]:
            smc_data["bos"] = True
            smc_data["details"].append("Bearish BOS confirmed")

        # 3. Fair Value Gap (FVG): فراغ سعري بين الشمعة i-2 وشمعة i
        for i in range(len(closed_candles) - 5, len(closed_candles) - 1):
            if i >= 2:
                # Bullish FVG
                if lows[i] > highs[i-2] and (lows[i] - highs[i-2]) > (0.3 * atr):
                    smc_data["fvg_detected"] = True
                    smc_data["details"].append(f"Bullish FVG found at index {i}")
                # Bearish FVG
                elif highs[i] < lows[i-2] and (lows[i-2] - highs[i]) > (0.3 * atr):
                    smc_data["fvg_detected"] = True
                    smc_data["details"].append(f"Bearish FVG found at index {i}")

        # 4. Order Blocks (OB): الشمعة المعاكسة قبل حركة دافعة قوية
        body_sizes = np.abs(closes - opens)
        avg_body = np.mean(body_sizes[-10:]) if len(body_sizes) >= 10 else np.mean(body_sizes)
        if body_sizes[-1] > (1.5 * avg_body):
            smc_data["order_block"] = True
            smc_data["details"].append("Strong impulse candle indicating institutional Order Block origin")

        return smc_data

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, btc_ohlcv_1h=None):
        debug_logs = []
        def log_debug(msg):
            debug_logs.append(msg)

        def no_trade(reason, **extra):
            out = {"reason": reason, "debug_trace": debug_logs}
            out.update(extra)
            return "NEUTRAL", 0, out

        # 1. التحقق من صحة بيانات فريم 15M (الأساسي لتحديد النموذج ودخول الصفقات)
        raw_15m = self._array(ohlcv_15m, 40)
        if raw_15m is None:
            return no_trade("بيانات فريم 15M غير كافية أو غير صالحة")

        closed_candles = raw_15m[:-1]
        current_live_candle = raw_15m[-1]
        current_price = float(current_live_candle[4])

        highs = closed_candles[:, 2]
        lows = closed_candles[:, 3]
        closes = closed_candles[:, 4]
        volumes = closed_candles[:, 5]

        atr = self.calculate_atr(highs, lows, closes, 14)
        if atr <= 0:
            return no_trade("مؤشر ATR غير صلب على فريم 15M")

        rsi = self.calculate_rsi(closes)
        _, _, macd_hist = self.calculate_macd(closes)
        avg_volume = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        recent_vol = float(volumes[-1])

        piv_highs, piv_lows = self.detect_swings(highs, lows, window=3)
        log_debug(f"15M Pivots detected - Highs: {len(piv_highs)}, Lows: {len(piv_lows)}")

        detected_pattern = None
        pattern_type = None
        neckline = 0.0
        pattern_base_level = 0.0
        pattern_quality_score = 0

        # --- A. Inverse Head & Shoulders (LONG) ---
        if len(piv_lows) >= 3 and len(piv_highs) >= 2:
            l3, l2, l1 = piv_lows[-3], piv_lows[-2], piv_lows[-1]
            if l2[1] < l3[1] and l2[1] < l1[1]:  # الرأس هو الأخفض
                sh_diff = abs(l3[1] - l1[1])
                if sh_diff <= (2.0 * atr):
                    h_between = [h[1] for h in piv_highs if l3[0] < h[0] < l1[0]]
                    if h_between:
                        neckline = float(max(h_between))
                        detected_pattern = "INV_HEAD_SHOULDERS"
                        pattern_type = "LONG"
                        pattern_base_level = float(l1[1])
                        pattern_quality_score = 25

        # --- B. Double Bottom (LONG) ---
        if not detected_pattern and len(piv_lows) >= 2:
            l2, l1 = piv_lows[-2], piv_lows[-1]
            diff_bottoms = abs(l2[1] - l1[1])
            if diff_bottoms <= (1.8 * atr):
                h_between = [h[1] for h in piv_highs if l2[0] < h[0] < l1[0]]
                if h_between:
                    neckline = float(max(h_between))
                    detected_pattern = "DOUBLE_BOTTOM"
                    pattern_type = "LONG"
                    pattern_base_level = float(min(l2[1], l1[1]))
                    pattern_quality_score = 20

        # --- C. Head & Shoulders (SHORT) ---
        if not detected_pattern and len(piv_highs) >= 3 and len(piv_lows) >= 2:
            h3, h2, h1 = piv_highs[-3], piv_highs[-2], piv_highs[-1]
            if h2[1] > h3[1] and h2[1] > h1[1]:  # الرأس هو الأعلى
                sh_diff = abs(h3[1] - h1[1])
                if sh_diff <= (2.0 * atr):
                    l_between = [l[1] for l in piv_lows if h3[0] < l[0] < h1[0]]
                    if l_between:
                        neckline = float(min(l_between))
                        detected_pattern = "HEAD_SHOULDERS"
                        pattern_type = "SHORT"
                        pattern_base_level = float(h1[1])
                        pattern_quality_score = 25

        # --- D. Double Top (SHORT) ---
        if not detected_pattern and len(piv_highs) >= 2:
            h2, h1 = piv_highs[-2], piv_highs[-1]
            diff_tops = abs(h2[1] - h1[1])
            if diff_tops <= (1.8 * atr):
                l_between = [l[1] for l in piv_lows if h2[0] < l[0] < h1[0]]
                if l_between:
                    neckline = float(min(l_between))
                    detected_pattern = "DOUBLE_TOP"
                    pattern_type = "SHORT"
                    pattern_base_level = float(max(h2[1], h1[1]))
                    pattern_quality_score = 20

        if not detected_pattern:
            return no_trade("لم يتم اكتشاف نموذج هندسي مكتمل على فريم 15M")

        log_debug(f"Pattern Detected: {detected_pattern} ({pattern_type}) | Neckline: {neckline}")

        # --- التحقق الصارم من الاختراق وإعادة الاختبار باستخدام الشموع المغلقة ---
        atr_margin = 0.5 * atr
        state = "FORMING"
        last_closed_close = float(closes[-1])
        last_closed_high = float(highs[-1])
        last_closed_low = float(lows[-1])

        if pattern_type == "LONG":
            has_broken = any(c > neckline for c in closes[-5:])
            if has_broken:
                # إعادة اختبار ناجحة أو اختراق قوي مؤكد بشمعة إغلاق
                retesting = (last_closed_low <= neckline + atr_margin) and (last_closed_close > neckline)
                if retesting:
                    state = "RETEST_CONFIRMED"
                elif last_closed_close > neckline + (0.5 * atr):
                    state = "BREAKOUT_CONFIRMED"
            elif last_closed_close <= pattern_base_level - atr_margin:
                state = "INVALIDATED"

        elif pattern_type == "SHORT":
            has_broken = any(c < neckline for c in closes[-5:])
            if has_broken:
                retesting = (last_closed_high >= neckline - atr_margin) and (last_closed_close < neckline)
                if retesting:
                    state = "RETEST_CONFIRMED"
                elif last_closed_close < neckline - (0.5 * atr):
                    state = "BREAKOUT_CONFIRMED"
            elif last_closed_close >= pattern_base_level + atr_margin:
                state = "INVALIDATED"

        log_debug(f"Pattern State Evaluated: {state}")
        if state in ("FORMING", "INVALIDATED"):
            return no_trade(f"حالة النموذج غير مؤهلة أو تم إبطاله: {state}")

        # منع الدخول المتاخر إذا ابتعد السعر كثيراً عن خط العنق أو منطقة إعادة الاختبار
        distance_from_neckline = abs(current_price - neckline)
        if distance_from_neckline > (2.5 * atr):
            return no_trade("الدخول متأخر جداً، السعر ابتعد كثيراً عن مستوى خط العنق")

        # --- تحليل السيولة ومفاهيم SMC الفعلي ---
        smc_res = self.analyze_smc_structure(closed_candles, atr)
        log_debug(f"SMC Analysis: {smc_res['details']}")

        # --- تحليل الأطر الزمنية العليا (4H & 1H & BTC 1H) ---
        tf_4h_bias = "NEUTRAL"
        if ohlcv_4h is not None:
            arr_4h = self._array(ohlcv_4h, 20)
            if arr_4h is not None:
                c_4h = arr_4h[:, 4]
                tf_4h_bias = "BULLISH" if c_4h[-1] > np.mean(c_4h[-10:]) else "BEARISH"

        tf_1h_bias = "NEUTRAL"
        if ohlcv_1h is not None:
            arr_1h = self._array(ohlcv_1h, 20)
            if arr_1h is not None:
                c_1h = arr_1h[:, 4]
                tf_1h_bias = "BULLISH" if c_1h[-1] > np.mean(c_1h[-10:]) else "BEARISH"

        btc_bias = "NEUTRAL"
        if btc_ohlcv_1h is not None:
            btc_arr = self._array(btc_ohlcv_1h, 20)
            if btc_arr is not None:
                btc_c = btc_arr[:, 4]
                btc_bias = "BULLISH" if btc_c[-1] > np.mean(btc_c[-10:]) else "BEARISH"

        # --- نظام التقييم الواقعي (Score 0-100) ---
        score = pattern_quality_score  # الأساس (20-25)

        # 1. جودة الدخول (إعادة اختبار مؤكدة مقابل اختراق) (+20 كحد أقصى)
        if state == "RETEST_CONFIRMED":
            score += 20
            entry_mode = "RETEST ENTRY"
        else:
            score += 12
            entry_mode = "BREAKOUT ENTRY"

        # 2. مؤشرات الحجم والزخم (+15)
        if recent_vol > avg_volume:
            score += 8
        if pattern_type == "LONG" and (rsi < 68 or macd_hist > 0):
            score += 7
        elif pattern_type == "SHORT" and (rsi > 32 or macd_hist < 0):
            score += 7

        # 3. مفاهيم SMC المحققة فعلياً (+20 كحد أقصى)
        if smc_res["liquidity_sweep"]:
            score += 8
        if smc_res["bos"]:
            score += 7
        if smc_res["fvg_detected"] or smc_res["order_block"]:
            score += 5

        # 4. توافق الأطر الزمنية والبيتكوين (+20 كحد أقصى)
        tf_alignment_count = 0
        if pattern_type == "LONG":
            if tf_4h_bias == "BULLISH": tf_alignment_count += 1
            if tf_1h_bias == "BULLISH": tf_alignment_count += 1
            if btc_bias == "BULLISH": tf_alignment_count += 1
        else:
            if tf_4h_bias == "BEARISH": tf_alignment_count += 1
            if tf_1h_bias == "BEARISH": tf_alignment_count += 1
            if btc_bias == "BEARISH": tf_alignment_count += 1

        score += (tf_alignment_count * 6)

        # خصم درجات عند تعارض الفريمات الكبرى بقوة
        if (pattern_type == "LONG" and tf_4h_bias == "BEARISH" and btc_bias == "BEARISH") or \
           (pattern_type == "SHORT" and tf_4h_bias == "BULLISH" and btc_bias == "BULLISH"):
            score -= 15

        score = int(max(0, min(100, score)))
        log_debug(f"Final Calibrated Score: {score}/100")

        # عتبة القبول الصارمة لتفادي الدخول العشوائي
        if score < 65:
            return no_trade(f"درجة التقييم غير كافية للتنفيذ: {score}/100 (الحد الأدنى 65)", score=score)

        # --- إدارة المخاطر وحساب وقف الخسارة والأهداف بدقة ---
        if pattern_type == "LONG":
            stop_loss = float(pattern_base_level - (0.6 * atr))
            if stop_loss >= current_price:
                stop_loss = current_price - (1.5 * atr)
            risk_dist = current_price - stop_loss
            tp1 = current_price + (risk_dist * 1.5)
            tp2 = current_price + (risk_dist * 2.5)
            tp3 = current_price + (risk_dist * 4.0)
        else:
            stop_loss = float(pattern_base_level + (0.6 * atr))
            if stop_loss <= current_price:
                stop_loss = current_price + (1.5 * atr)
            risk_dist = stop_loss - current_price
            tp1 = current_price - (risk_dist * 1.5)
            tp2 = current_price - (risk_dist * 2.5)
            tp3 = current_price - (risk_dist * 4.0)

        if risk_dist <= 0:
            return no_trade("مسافة وقف الخسارة غير منطقية أو سلبية")

        reward_ratio = abs(tp2 - current_price) / risk_dist
        if reward_ratio < 1.4:
            return no_trade(f"نسبة العائد للمخاطرة غير مجدية: 1:{round(reward_ratio, 1)}")

        risk_usd = self.total_capital * self.risk_per_trade
        position_size = risk_usd / risk_dist

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
            "smc_note": " | ".join(smc_res["details"]) if smc_res["details"] else "SMC Structure Verified",
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
