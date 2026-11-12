# ============================================================
# analysis.py — StrategyEngine V107.0 (Structure Break & Flag Sniper)
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
        """كشف الفجوات السعرية (FVG) في آخر 10 شموع"""
        bull_fvg, bear_fvg = False, False
        if len(df) < 10:
            return bull_fvg, bear_fvg
        sub = df.tail(10).reset_index(drop=True)
        for i in range(2, len(sub)):
            if sub["low"].iloc[i] > sub["high"].iloc[i - 2]:
                bull_fvg = True
            if sub["high"].iloc[i] < sub["low"].iloc[i - 2]:
                bear_fvg = True
        return bull_fvg, bear_fvg

    def detect_structure_and_flag(self, df):
        """
        تطبيق استراتيجية الصورة:
        1. هيكل هابط (قمم أدنى) يليه شمعة صاعدة ضخمة تكسر القمة الأدنى (CHoCH / BOS) مع انفجار حجمي.
        2. تكوين نمط العلم (تجميع ضيق 2-5 شموع بحجوم منخفضة).
        3. الشمعة الحالية تخترق سقف العلم للأعلى مع رفض من الفتائل السفلية.
        (والعكس تماماً للاتجاه الهابط SHORT)
        """
        if len(df) < 35:
            return "NEUTRAL", None

        df = df.copy()
        df["ATR"] = self.calculate_atr(df)
        df["vol_sma"] = df["volume"].rolling(window=20).mean()

        curr = df.iloc[-1]
        atr = float(curr["ATR"])
        if atr <= 0:
            return "NEUTRAL", None

        # نبحث عن الشمعة الانفجارية (سارية العلم) بين الشمعة -7 و -3
        for pole_idx in range(-6, -2):
            pole = df.iloc[pole_idx]
            pole_body = abs(float(pole["close"]) - float(pole["open"]))
            pole_vol = float(pole["volume"])
            pole_avg_vol = float(df["vol_sma"].iloc[pole_idx]) if df["vol_sma"].iloc[pole_idx] > 0 else 1.0

            # شرط الشمعة الانفجارية (ثور كبير / دب كبير): جسم أكبر من 1.5 ATR وحجم تداول >= 1.8x المتوسط
            is_impulse = (pole_body >= 1.5 * atr) and (pole_vol >= 1.8 * pole_avg_vol)
            if not is_impulse:
                continue

            # الشموع التي تلي السارية حتى قبل الشمعة الحالية تمثل "نسيج العلم" (Flag Consolidation)
            flag_candles = df.iloc[pole_idx + 1 : -1]
            if len(flag_candles) < 2:
                continue

            # البيانات السابقة للسارية للتحقق من كسر الهيكل (CHoCH / BOS)
            prior_window = df.iloc[pole_idx - 15 : pole_idx]
            if len(prior_window) < 10:
                continue

            # ================= سيناريو الصعود (LONG - نفس الصورة تماماً) =================
            if float(pole["close"]) > float(pole["open"]):
                prior_high = float(prior_window["high"].max())
                prior_low = float(prior_window["low"].min())
                # تحقق من وجود اتجاه هابط سابق (القمة في النصف الأول أعلى من النصف الثاني - قمم أدنى)
                first_half_high = float(prior_window.iloc[:7]["high"].max())
                second_half_high = float(prior_window.iloc[7:]["high"].max())
                is_downtrend_structure = first_half_high > second_half_high

                # السارية كسرت آخر قمة أدنى (CHoCH / BOS)
                broke_structure = float(pole["close"]) > second_half_high

                if is_downtrend_structure and broke_structure:
                    flag_high = float(flag_candles["high"].max())
                    flag_low = float(flag_candles["low"].min())
                    flag_range = flag_high - flag_low

                    # شرط العلم: تصحيح ضيق لا يتجاوز 55% من طول السارية، وبحجوم تداول هادئة
                    is_tight_flag = (flag_range <= 0.65 * pole_body) and (flag_low > float(pole["open"]))
                    flag_avg_vol = float(flag_candles["volume"].mean())
                    is_quiet_flag = flag_avg_vol < pole_vol

                    # شرط الاختراق الحالي: إغلاق أعلى سقف العلم مع حجم متزايد
                    is_breakout = (float(curr["close"]) > flag_high) and (float(curr["close"]) > float(curr["open"]))
                    is_vol_confirm = float(curr["volume"]) > flag_avg_vol

                    if is_tight_flag and is_quiet_flag and is_breakout and is_vol_confirm:
                        return "LONG", {
                            "flag_low": flag_low,
                            "flag_high": flag_high,
                            "pole_height": pole_body,
                            "vol_spike": round(pole_vol / pole_avg_vol, 1),
                            "broken_level": second_half_high
                        }

            # ================= سيناريو الهبوط (SHORT - النموذج المعكوس) =================
            elif float(pole["close"]) < float(pole["open"]):
                first_half_low = float(prior_window.iloc[:7]["low"].min())
                second_half_low = float(prior_window.iloc[7:]["low"].min())
                is_uptrend_structure = first_half_low < second_half_low

                # السارية كسرت آخر قاع أعلى للأسفل (CHoCH / BOS)
                broke_structure = float(pole["close"]) < second_half_low

                if is_uptrend_structure and broke_structure:
                    flag_high = float(flag_candles["high"].max())
                    flag_low = float(flag_candles["low"].min())
                    flag_range = flag_high - flag_low

                    is_tight_flag = (flag_range <= 0.65 * pole_body) and (flag_high < float(pole["open"]))
                    flag_avg_vol = float(flag_candles["volume"].mean())
                    is_quiet_flag = flag_avg_vol < pole_vol

                    is_breakout = (float(curr["close"]) < flag_low) and (float(curr["close"]) < float(curr["open"]))
                    is_vol_confirm = float(curr["volume"]) > flag_avg_vol

                    if is_tight_flag and is_quiet_flag and is_breakout and is_vol_confirm:
                        return "SHORT", {
                            "flag_low": flag_low,
                            "flag_high": flag_high,
                            "pole_height": pole_body,
                            "vol_spike": round(pole_vol / pole_avg_vol, 1),
                            "broken_level": second_half_low
                        }

        return "NEUTRAL", None

    def analyze_market_structure(self, ohlcv_5m, ohlcv_15m, ohlcv_1h=None, asset_type="crypto", drop_last_candle=True):
        neutral = build_signal(
            direction="NEUTRAL", entry=0.0, stop_loss=0.0, take_profits=[], score=0, rsi=50.0, atr=0.0,
            reason="لا يوجد كسر هيكل مع اختراق نمط العلم مكتمل الشروط حالياً",
        )
        try:
            if ohlcv_15m is None or len(ohlcv_15m) < 40 or ohlcv_5m is None or len(ohlcv_5m) < 40:
                return "NEUTRAL", 0.0, neutral

            df_5m = self.prepare_dataframe(ohlcv_5m)
            df_15m = self.prepare_dataframe(ohlcv_15m)

            # 1. فلتر الأمان على الفريم الكبير (1H) لمنع الدخول عكس الزخم العام العنيف
            htf_bias = "BOTH"
            if ohlcv_1h is not None and len(ohlcv_1h) >= 30:
                df_1h = self.prepare_dataframe(ohlcv_1h)
                ema_20_1h = df_1h["close"].ewm(span=20, adjust=False).mean().iloc[-1]
                ema_50_1h = df_1h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
                close_1h = float(df_1h["close"].iloc[-1])
                if close_1h > ema_50_1h and ema_20_1h >= ema_50_1h * 0.995:
                    htf_bias = "LONG_SAFE"
                elif close_1h < ema_50_1h and ema_20_1h <= ema_50_1h * 1.005:
                    htf_bias = "SHORT_SAFE"

            # 2. البحث عن النموذج (كسر هيكل + علم + اختراق) على فريم 5m أو 15m
            pattern_tf = "5m"
            direction, setup = self.detect_structure_and_flag(df_5m)
            if direction == "NEUTRAL":
                direction, setup = self.detect_structure_and_flag(df_15m)
                pattern_tf = "15m"

            if direction == "NEUTRAL" or not setup:
                return "NEUTRAL", 0.0, neutral

            # 3. التحقق من توافق فريم الساعة (الأمان)
            if direction == "LONG" and htf_bias == "SHORT_SAFE":
                return "NEUTRAL", 0.0, neutral
            if direction == "SHORT" and htf_bias == "LONG_SAFE":
                return "NEUTRAL", 0.0, neutral

            # حساب المؤشرات المساعدة
            df_5m["RSI"] = self.calculate_rsi(df_5m["close"])
            df_5m["ATR"] = self.calculate_atr(df_5m)
            price = float(df_5m["close"].iloc[-1])
            rsi = float(df_5m["RSI"].iloc[-1])
            atr = float(df_5m["ATR"].iloc[-1])

            if price <= 0 or atr <= 0:
                return "NEUTRAL", 0.0, neutral

            # فحص التشبع ومنع مطاردة السعر المتأخرة
            if direction == "LONG" and rsi > 76:
                return "NEUTRAL", 0.0, neutral
            if direction == "SHORT" and rsi < 24:
                return "NEUTRAL", 0.0, neutral

            bull_fvg, bear_fvg = self.detect_fvg(df_5m)
            has_fvg = (direction == "LONG" and bull_fvg) or (direction == "SHORT" and bear_fvg)

            decimals = 8 if price < 0.1 else (6 if price < 1 else (4 if price < 100 else 2))
            leverage = 10

            # حساب وقف الخسارة الهيكلي (أسفل/أعلى العلم مع هامش ATR بسيط) والأهداف بناءً على السارية
            pole_h = setup["pole_height"]
            if direction == "LONG":
                sl_raw = min(setup["flag_low"] - (0.3 * atr), price - (1.2 * atr))
                risk_dist = max(price - sl_raw, 0.8 * atr)
                stop = price - risk_dist
                tp1 = price + (1.5 * risk_dist)
                tp2 = price + max(2.8 * risk_dist, pole_h * 0.9)
                reason_text = f"كسر هيكل هابط (CHoCH) + اختراق نمط العلم الصاعد على فريم {pattern_tf}"
            else:
                sl_raw = max(setup["flag_high"] + (0.3 * atr), price + (1.2 * atr))
                risk_dist = max(sl_raw - price, 0.8 * atr)
                stop = price + risk_dist
                tp1 = price - (1.5 * risk_dist)
                tp2 = price - max(2.8 * risk_dist, pole_h * 0.9)
                reason_text = f"كسر هيكل صاعد (CHoCH) + كسر نمط العلم الهابط على فريم {pattern_tf}"

            roe1 = round(abs((tp1 - price) / price) * 100 * leverage, 1)
            roe2 = round(abs((tp2 - price) / price) * 100 * leverage, 1)
            roe_sl = round(abs((stop - price) / price) * 100 * leverage, 1)
            atr_pct = round((atr / price) * 100, 2)
            score = 94 if has_fvg else 88

            signal = build_signal(
                direction=direction,
                entry=round(price, decimals),
                stop_loss=round(stop, decimals),
                take_profits=[round(tp1, decimals), round(tp2, decimals)],
                score=score,
                rsi=rsi,
                atr=atr_pct,
                reason=reason_text,
                details={
                    "roe1": roe1,
                    "roe2": roe2,
                    "roe_sl": roe_sl,
                    "pattern_tf": pattern_tf,
                    "volume_ratio": f"{setup['vol_spike']}x",
                    "fvg_detected": "نعم (FVG داعم)" if has_fvg else "غير متوفر",
                    "htf_safety_filter": f"متوافق مع فريم الساعة ({htf_bias})",
                    "broken_level": round(setup["broken_level"], decimals),
                    "whale_justification": (
                        f"شمعة اندفاعية (حجم {setup['vol_spike']}x المتوسط) كسرت الهيكل عند "
                        f"${round(setup['broken_level'], decimals)} وتلتها استراحة علم ثم اختراق مؤكد."
                    )
                }
            )
            return direction, price, signal

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return "NEUTRAL", 0.0, neutral
