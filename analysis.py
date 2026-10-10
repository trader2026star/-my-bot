
# ==========================================
# ADVANCED SMC & ICT ENGINE
# File: analysis.py
# ==========================================

import numpy as np


class StrategyEngine:
    def __init__(self):
        pass

    @staticmethod
    def valid_ohlcv(data):
        if not isinstance(data, (list, tuple)) or len(data) < 10:
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
    def arrays(ohlcv):
        opens = np.array([float(c[1]) for c in ohlcv])
        highs = np.array([float(c[2]) for c in ohlcv])
        lows = np.array([float(c[3]) for c in ohlcv])
        closes = np.array([float(c[4]) for c in ohlcv])
        volumes = np.array([max(0.0, float(c[5])) for c in ohlcv])
        return opens, highs, lows, closes, volumes

    def calculate_atr(self, highs, lows, closes, period=14):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        n = min(len(highs), len(lows), len(closes))
        if n < 2:
            return 0.0

        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        true_ranges = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )

        if len(true_ranges) == 0:
            return 0.0

        atr = float(np.mean(true_ranges[-period:]))
        return atr if np.isfinite(atr) and atr > 0 else 0.0

    def calculate_vwap(self, highs, lows, closes, volumes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)
        volumes = np.asarray(volumes, dtype=float)

        n = min(len(highs), len(lows), len(closes), len(volumes))
        if n == 0:
            return 0.0

        # Rolling VWAP estimate using recent 24 candles.
        highs = highs[-n:][-24:]
        lows = lows[-n:][-24:]
        closes = closes[-n:][-24:]
        volumes = np.maximum(volumes[-n:][-24:], 0.0)

        total_volume = float(np.sum(volumes))
        if total_volume <= 0:
            return float(closes[-1])

        typical = (highs + lows + closes) / 3.0
        return float(np.sum(typical * volumes) / total_volume)

    @staticmethod
    def _trend(highs, lows, closes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        if len(closes) < 8:
            return "NEUTRAL"

        ref_high = float(np.max(highs[-8:-1]))
        ref_low = float(np.min(lows[-8:-1]))
        last_close = float(closes[-1])
        previous_close = float(closes[-2])

        if last_close > ref_high and previous_close <= ref_high:
            return "LONG"
        if last_close < ref_low and previous_close >= ref_low:
            return "SHORT"

        recent = closes[-6:]
        older = closes[-12:-6] if len(closes) >= 12 else closes[:-6]

        if len(older) and np.mean(recent) > np.mean(older) and recent[-1] >= recent[0]:
            return "LONG"
        if len(older) and np.mean(recent) < np.mean(older) and recent[-1] <= recent[0]:
            return "SHORT"

        return "NEUTRAL"

    def detect_ict_market_structure(self, highs, lows, closes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)

        if len(closes) < 10:
            return "NONE", "NONE"

        ref_high = float(np.max(highs[-10:-2]))
        ref_low = float(np.min(lows[-10:-2]))
        previous_close = float(closes[-2])
        current_close = float(closes[-1])

        prior_trend = self._trend(
            highs[:-2], lows[:-2], closes[:-2]
        )

        bos = "NONE"
        mss = "NONE"

        if current_close > ref_high and previous_close <= ref_high:
            bos = "BULLISH_BOS"
            if prior_trend == "SHORT":
                mss = "BULLISH_MSS"

        elif current_close < ref_low and previous_close >= ref_low:
            bos = "BEARISH_BOS"
            if prior_trend == "LONG":
                mss = "BEARISH_MSS"

        return bos, mss

    def detect_liquidity_sweep_and_fvg(self, highs, lows, opens, closes):
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        opens = np.asarray(opens, dtype=float)
        closes = np.asarray(closes, dtype=float)

        sweep = "NONE"
        fvg = "NONE"
        ob = ("NONE", None)

        n = min(len(highs), len(lows), len(opens), len(closes))
        if n < 6:
            return sweep, fvg, ob

        # Liquidity sweep: wick crosses the prior candle level,
        # then candle closes back through that level.
        if highs[-1] > highs[-2] and closes[-1] < highs[-2]:
            sweep = "BEARISH_SWEEP"
        elif lows[-1] < lows[-2] and closes[-1] > lows[-2]:
            sweep = "BULLISH_SWEEP"

        # Three-candle Fair Value Gap.
        if lows[-1] > highs[-3]:
            fvg = "BULLISH_FVG"
        elif highs[-1] < lows[-3]:
            fvg = "BEARISH_FVG"

        bodies = np.abs(closes - opens)
        average_body = float(np.mean(bodies[-6:-1]))
        current_body = float(bodies[-1])

        # Candidate Order Block: last opposite candle before displacement.
        if average_body > 0 and current_body >= average_body * 1.5:
            if closes[-1] > opens[-1]:
                for i in range(n - 2, max(-1, n - 6), -1):
                    if closes[i] < opens[i]:
                        ob = ("BULLISH_OB", (float(lows[i]), float(highs[i])))
                        break
            elif closes[-1] < opens[-1]:
                for i in range(n - 2, max(-1, n - 6), -1):
                    if closes[i] > opens[i]:
                        ob = ("BEARISH_OB", (float(lows[i]), float(highs[i])))
                        break

        return sweep, fvg, ob

    def analyze_multi_timeframe(
        self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None
    ):
        empty_details = {
            "trend_4h": "NEUTRAL",
            "trend_1h": "NEUTRAL",
            "bos": "NONE",
            "mss": "NONE",
            "sweep": "NONE",
            "fvg": "NONE",
            "ob_type": "NONE",
            "ob_zone": None,
            "volume_ratio": 0.0,
            "vwap_price": 0.0,
            "support": None,
            "resistance": None,
            "retest_advice": "بيانات غير كافية",
            "entry_valid": False,
            "btc_trend": "UNKNOWN",
            "confirmations": [],
            "reasons_excluded": ["بيانات غير كافية للتحليل"]
        }

        if not all(
            self.valid_ohlcv(x)
            for x in (ohlcv_4h, ohlcv_1h, ohlcv_15m)
        ):
            return "NEUTRAL", 0, 0.0, empty_details, ([], [], [])

        o4, h4, l4, c4, v4 = self.arrays(ohlcv_4h)
        o1, h1, l1, c1, v1 = self.arrays(ohlcv_1h)
        o15, h15, l15, c15, v15 = self.arrays(ohlcv_15m)

        # Exclude the newest potentially unfinished candle for trend/structure.
        trend_4h = self._trend(h4[:-1], l4[:-1], c4[:-1])
        trend_1h = self._trend(h1[:-1], l1[:-1], c1[:-1])

        confirmations = [
            f"اتجاه 4H: {trend_4h}",
            f"اتجاه 1H: {trend_1h}"
        ]
        excluded = []
        score = 25

        if trend_4h != "NEUTRAL" and trend_4h == trend_1h:
            direction = trend_1h
            score += 15
            confirmations.append("توافق اتجاه 4H و1H")
        else:
            direction = "NEUTRAL"
            excluded.append("لا يوجد توافق واضح بين اتجاه 4H و1H")

        # Use completed 1H candles for structural analysis.
        bos, mss = self.detect_ict_market_structure(
            h1[:-1], l1[:-1], c1[:-1]
        )

        if bos != "NONE":
            confirmations.append(f"كسر هيكل: {bos}")
            aligned_bos = (
                (direction == "LONG" and "BULLISH" in bos)
                or (direction == "SHORT" and "BEARISH" in bos)
            )
            if aligned_bos:
                score += 15
            else:
                excluded.append("كسر الهيكل لا يدعم الاتجاه الحالي")
        else:
            aligned_bos = False
            excluded.append("لا يوجد BOS واضح على فريم الساعة")

        if mss != "NONE":
            confirmations.append(f"تحول هيكل محتمل: {mss}")
            score += 5

        # Analyze 15m closed candles, excluding the newest candle.
        sweep, fvg, ob_data = self.detect_liquidity_sweep_and_fvg(
            h15[:-1], l15[:-1], o15[:-1], c15[:-1]
        )
        ob_type, ob_zone = ob_data if ob_data else ("NONE", None)

        aligned_sweep = (
            (direction == "LONG" and sweep == "BULLISH_SWEEP")
            or (direction == "SHORT" and sweep == "BEARISH_SWEEP")
        )
        if sweep != "NONE":
            confirmations.append(f"سحب سيولة مرصود: {sweep}")
            if aligned_sweep:
                score += 10
            else:
                excluded.append("سحب السيولة لا يدعم الاتجاه الحالي")
        else:
            excluded.append("لا يوجد سحب سيولة واضح على 15M")

        aligned_fvg = (
            (direction == "LONG" and fvg == "BULLISH_FVG")
            or (direction == "SHORT" and fvg == "BEARISH_FVG")
        )
        if fvg != "NONE":
            confirmations.append(f"FVG مرصودة: {fvg}")
            if aligned_fvg:
                score += 5
            else:
                excluded.append("اتجاه FVG لا يتوافق مع الصفقة")

        aligned_ob = (
            (direction == "LONG" and ob_type == "BULLISH_OB")
            or (direction == "SHORT" and ob_type == "BEARISH_OB")
        )
        if ob_zone:
            confirmations.append(
                f"منطقة OB مرشحة: {ob_type} "
                f"({ob_zone[0]:.8g}–{ob_zone[1]:.8g})"
            )
            if aligned_ob:
                score += 10
            else:
                excluded.append("منطقة OB لا تتوافق مع الاتجاه")
        else:
            excluded.append("لم يتم العثور على OB مرشحة بشروط الاندفاع")

        # Compare last completed hourly volume with preceding hourly bars.
        average_volume = (
            float(np.mean(v1[-16:-2]))
            if len(v1) >= 16 else float(np.mean(v1[:-2]))
        )
        current_volume = float(v1[-2])
        volume_ratio = (
            round(current_volume / average_volume, 2)
            if average_volume > 0 else 0.0
        )

        if 1.15 <= volume_ratio <= 3.5:
            score += 10
            confirmations.append(f"الفوليوم أعلى من المتوسط ({volume_ratio}x)")
        elif volume_ratio > 3.5:
            excluded.append(f"الفوليوم مرتفع جدًا ({volume_ratio}x)")
        else:
            excluded.append(f"الفوليوم لا يقدم تأكيدًا كافيًا ({volume_ratio}x)")

        vwap = self.calculate_vwap(h1[:-1], l1[:-1], c1[:-1], v1[:-1])
        current_price = float(c15[-2])

        if direction == "LONG" and current_price > vwap:
            score += 5
            confirmations.append("السعر أعلى VWAP المرجعي")
        elif direction == "SHORT" and current_price < vwap:
            score += 5
            confirmations.append("السعر أسفل VWAP المرجعي")
        else:
            excluded.append("السعر لا يدعم الاتجاه بالنسبة إلى VWAP")

        support = float(np.min(l1[-11:-1]))
        resistance = float(np.max(h1[-11:-1]))

        distance_pct = None
        retest_advice = "انتظر تأكيد شمعة 15M قبل التنفيذ"

        if ob_zone:
            ob_low, ob_high = sorted(ob_zone)
            ob_mid = (ob_low + ob_high) / 2.0
            distance_pct = (
                abs(current_price - ob_mid) / current_price * 100
                if current_price > 0 else None
            )

            if distance_pct is not None and distance_pct > 1.5:
                score -= 10
                retest_advice = "السعر بعيد عن OB؛ لا تطارد السعر وانتظر إعادة الاختبار"
                excluded.append(f"البعد عن منتصف OB يبلغ {distance_pct:.2f}%")
            elif ob_low <= current_price <= ob_high:
                retest_advice = "السعر داخل OB المرشحة؛ انتظر تأكيد الرفض"
            else:
                retest_advice = "راقب إعادة اختبار OB وتأكيد شمعة الدخول"

        btc_trend = "UNKNOWN"
        if self.valid_ohlcv(ohlcv_btc_1h):
            _, bh, bl, bc, _ = self.arrays(ohlcv_btc_1h)
            btc_trend = self._trend(bh[:-1], bl[:-1], bc[:-1])

            if direction == "LONG" and btc_trend == "SHORT":
                score -= 5
                excluded.append("اتجاه BTC هابط ويزيد مخاطرة LONG")
            elif direction == "SHORT" and btc_trend == "LONG":
                score -= 5
                excluded.append("اتجاه BTC صاعد ويزيد مخاطرة SHORT")
            elif direction != "NEUTRAL" and btc_trend == direction:
                score += 5
                confirmations.append(f"اتجاه BTC يدعم الصفقة: {btc_trend}")

        if (
            direction == "LONG" and resistance > current_price
            and (resistance - current_price) / current_price < 0.004
        ):
            score -= 8
            excluded.append("المقاومة قريبة من السعر")
        elif (
            direction == "SHORT" and support < current_price
            and (current_price - support) / current_price < 0.004
        ):
            score -= 8
            excluded.append("الدعم قريب من السعر")

        score = int(max(0, min(100, round(score))))

        entry_valid = (
            direction in ("LONG", "SHORT")
            and trend_4h == trend_1h
            and aligned_bos
            and aligned_sweep
            and aligned_ob
            and volume_ratio >= 1.0
            and (distance_pct is None or distance_pct <= 1.5)
        )

        if not entry_valid or score < 70:
            signal = "NEUTRAL"
            if score < 70:
                excluded.append(f"التقييم أقل من حد القبول: {score}/100")
            if not entry_valid:
                excluded.append("شروط الدخول الهيكلي لم تكتمل")
        else:
            signal = direction

        details = {
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "bos": bos,
            "mss": mss,
            "sweep": sweep,
            "fvg": fvg,
            "ob_type": ob_type,
            "ob_zone": ob_zone,
            "volume_ratio": volume_ratio,
            "vwap_price": round(float(vwap), 10),
            "support": round(support, 10),
            "resistance": round(resistance, 10),
            "retest_advice": retest_advice,
            "entry_valid": bool(entry_valid),
            "btc_trend": btc_trend,
            "confirmations": confirmations,
            "reasons_excluded": excluded
        }

        return (
            signal, score, volume_ratio, details,
            (h1.tolist(), l1.tolist(), c1.tolist())
        )

    def calculate_risk_management(
        self, entry_price, direction, highs, lows, closes=None
    ):
        # Returns: SL, TP1, TP2, TP3, SL%, TP1%, RR estimate.
        entry = float(entry_price)
        direction = str(direction).upper()
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)

        if closes is None:
            closes = (highs + lows) / 2.0
        closes = np.asarray(closes, dtype=float)

        n = min(len(highs), len(lows), len(closes))
        if entry <= 0 or n < 2:
            raise ValueError("سعر دخول غير صالح أو بيانات شموع غير كافية")

        highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
        atr = self.calculate_atr(highs, lows, closes)
        if atr <= 0:
            atr = entry * 0.01

        if direction in ("LONG", "BUY"):
            swing_low = float(np.min(lows[-5:]))
            stop = min(swing_low, entry - 1.5 * atr)
            if stop >= entry:
                stop = entry - max(1.5 * atr, entry * 0.01)

            risk = entry - stop
            tp1 = entry + risk * 1.5
            tp2 = entry + risk * 2.5
            tp3 = entry + risk * 4.0

        elif direction in ("SHORT", "SELL"):
            swing_high = float(np.max(highs[-5:]))
            stop = max(swing_high, entry + 1.5 * atr)
            if stop <= entry:
                stop = entry + max(1.5 * atr, entry * 0.01)

            risk = stop - entry
            tp1 = entry - risk * 1.5
            tp2 = entry - risk * 2.5
            tp3 = entry - risk * 4.0

            # Prevent nonsensical negative targets.
            if tp3 <= 0:
                tp3 = max(entry * 0.01, tp2 - risk)

        else:
            raise ValueError("الاتجاه يجب أن يكون LONG أو SHORT")

        sl_pct = round(abs(entry - stop) / entry * 100, 3)
        tp1_pct = round(abs(tp1 - entry) / entry * 100, 3)
        rr_ratio = round(
            max(0.0, tp1_pct - 0.1) / max(sl_pct + 0.1, 0.001), 2
        )

        return (
            round(float(stop), 10),
            round(float(tp1), 10),
            round(float(tp2), 10),
            round(float(tp3), 10),
            sl_pct,
            tp1_pct,
            rr_ratio
        )
