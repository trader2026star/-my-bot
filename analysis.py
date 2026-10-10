# ==========================================
# ADVANCED STRICT SMC & QUANTITATIVE ANALYSIS (analysis.py)
# Developed for Mohamed Barakat (trader2026star)
# ==========================================

import numpy as np
import pandas as pd

class StrategyEngine:
    def __init__(self):
        pass

    def calculate_atr(self, highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            c_prev = closes[i-1]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr_list.append(tr)
        return float(np.mean(tr_list[-period:]))

    def calculate_vwap(self, highs, lows, closes, volumes):
        typical_price = (np.array(highs) + np.array(lows) + np.array(closes)) / 3
        vols = np.array(volumes)
        if np.sum(vols) == 0:
            return closes[-1]
        return float(np.sum(typical_price * vols) / np.sum(vols))

    def calculate_geometric_box_levels(self, highs, lows, closes):
        if len(highs) < 10 or len(lows) < 10:
            return None, None, None
            
        box_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        box_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        box_range = box_high - box_low
        
        if box_range == 0:
            return box_high, box_low, closes[-1]
            
        lvl_025 = box_low + (box_range * 0.25)
        lvl_050 = box_low + (box_range * 0.50)
        lvl_075 = box_low + (box_range * 0.75)
        
        current_price = closes[-1]
        return box_high, box_low, {
            "lvl_025": lvl_025,
            "lvl_050": lvl_050,
            "lvl_075": lvl_075,
            "current": current_price
        }

    def detect_order_blocks_and_fvg(self, highs, lows, opens, closes):
        """
        اكتشاف صارم لمناطق الـ Order Blocks (OB) الشمعية الحقيقية
        """
        ob_zone = None
        
        if len(closes) < 5:
            return "NONE", None

        body_size = abs(closes[-1] - opens[-1])
        avg_body = np.mean([abs(closes[i] - opens[i]) for i in range(-5, -1)])
        
        if body_size > (avg_body * 1.5):
            if closes[-1] > opens[-1]: 
                for i in range(-2, -5, -1):
                    if closes[i] < opens[i]:
                        ob_zone = (lows[i], highs[i])
                        break
                if ob_zone:
                    return "BULLISH_OB", ob_zone
            else: 
                for i in range(-2, -5, -1):
                    if closes[i] > opens[i]:
                        ob_zone = (lows[i], highs[i])
                        break
                if ob_zone:
                    return "BEARISH_OB", ob_zone

        return "NONE", None

    def analyze_multi_timeframe(self, ohlcv_4h, ohlcv_1h, ohlcv_15m, ohlcv_btc_1h=None):
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m or len(ohlcv_4h) < 15 or len(ohlcv_1h) < 15 or len(ohlcv_15m) < 15:
            return "NEUTRAL", 0, 1.0, {}, []

        closes_4h = [c[4] for c in ohlcv_4h]
        closes_1h = [c[4] for c in ohlcv_1h]
        volumes_1h = [c[5] for c in ohlcv_1h]
        
        highs_1h = [c[2] for c in ohlcv_1h]
        lows_1h = [c[3] for c in ohlcv_1h]
        
        opens_15m = [c[1] for c in ohlcv_15m]
        highs_15m = [c[2] for c in ohlcv_15m]
        lows_15m = [c[3] for c in ohlcv_15m]
        closes_15m = [c[4] for c in ohlcv_15m]

        confirmations = []
        reasons_excluded = []
        score = 40

        # 1. اتجاه 4H الرئيسي
        trend_4h = "LONG" if closes_4h[-1] > closes_4h[0] else "SHORT"
        confirmations.append(f"اتّجاه 4H العام: {trend_4h}")

        # 2. اتجاه 1H
        trend_1h = "LONG" if closes_1h[-1] > closes_1h[-5] else "SHORT"
        if trend_4h == trend_1h:
            score += 15
            confirmations.append(f"توافق اتجاه 1H مع 4H ({trend_1h})")
        else:
            reasons_excluded.append("تعارض اتجاه 1H مع 4H")
            return "NEUTRAL", 0, 1.0, {}, []

        # 3. شرط أساسي صارم: فحص الـ Order Blocks على فريم 15M (ممنوع تجاوز هذا الشرط)
        smc_type, ob_zone = self.detect_order_blocks_and_fvg(highs_15m, lows_15m, opens_15m, closes_15m)
        if smc_type == "BULLISH_OB" and trend_1h == "LONG":
            score += 25
            confirmations.append("تم اكتشاف منطقة Order Block شرائية مؤكدة (SMC)")
        elif smc_type == "BEARISH_OB" and trend_1h == "SHORT":
            score += 25
            confirmations.append("تم اكتشاف منطقة Order Block بيعية مؤكدة (SMC)")
        else:
            reasons_excluded.append("لم يتم رصد منطقة Order Block مطابقة للإتجاه")
            # رفض تام للصفقة إذا لم تتواجد منطقة الـ Order Block المؤسسية
            return "NEUTRAL", score, 1.0, {"confirmations": confirmations, "reasons_excluded": reasons_excluded}, (highs_1h, lows_1h, closes_1h)

        # 4. حجم التداول (Volume Ratio) - شرط ألا يكون أقل من المتوسط
        avg_vol = np.mean(volumes_1h[-15:-1]) if len(volumes_1h) > 15 else volumes_1h[-1]
        cur_vol = volumes_1h[-1]
        vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        
        if vol_ratio >= 1.0:
            score += 10
            confirmations.append(f"فوليوم تداول مدعوم ({vol_ratio}x)")
        else:
            reasons_excluded.append(f"فوليوم ضعيف ({vol_ratio}x)")
            return "NEUTRAL", score, vol_ratio, {"confirmations": confirmations, "reasons_excluded": reasons_excluded}, (highs_1h, lows_1h, closes_1h)

        # 5. تأكيد مؤشر VWAP
        vwap_value = self.calculate_vwap(highs_1h, lows_1h, closes_1h, volumes_1h)
        current_price = closes_1h[-1]
        
        if trend_1h == "LONG" and current_price > vwap_value:
            score += 10
            confirmations.append("السعر يتداول أعلى مؤشر VWAP")
        elif trend_1h == "SHORT" and current_price < vwap_value:
            score += 10
            confirmations.append("السعر يتداول أسفل مؤشر VWAP")
        else:
            reasons_excluded.append("موقع السعر مخالف لاتجاه VWAP")

        # 6. المستويات الهندسية
        box_high, box_low, geo_levels = self.calculate_geometric_box_levels(highs_1h, lows_1h, closes_1h)
        if geo_levels:
            cur = geo_levels["current"]
            if trend_1h == "LONG" and cur >= geo_levels["lvl_025"]:
                score += 10
                confirmations.append("توافق السعر مع المستويات الهندسية الصاعدة")
            elif trend_1h == "SHORT" and cur <= geo_levels["lvl_075"]:
                score += 10
                confirmations.append("توافق السعر مع المستويات الهندسية الهابطة")

        score = max(0, min(100, score))

        if score >= 75:
            signal = trend_1h
        else:
            signal = "NEUTRAL"
            reasons_excluded.append(f"التقييم العام لم يصل للحد المطلوب ({score}/100)")

        details = {
            "trend_4h": trend_4h,
            "trend_1h": trend_1h,
            "smc_structure": smc_type,
            "volume_ratio": vol_ratio,
            "vwap_price": round(vwap_value, 4),
            "confirmations": confirmations,
            "reasons_excluded": reasons_excluded
        }

        return signal, score, vol_ratio, details, (highs_1h, lows_1h, closes_1h)

    def calculate_risk_management(self, entry_price, direction, highs, lows):
        direction = direction.upper()
        atr = self.calculate_atr(highs, lows, highs)
        if atr <= 0:
            atr = entry_price * 0.015

        if direction in ['LONG', 'BUY']:
            swing_low = min(lows[-5:]) if len(lows) >= 5 else entry_price * 0.98
            stop_loss = min(swing_low, entry_price - (atr * 1.5))
            if stop_loss >= entry_price:
                stop_loss = entry_price * 0.985
            
            risk_dist = entry_price - stop_loss
            tp1 = entry_price + (risk_dist * 1.5)
            tp2 = entry_price + (risk_dist * 2.5)
            tp3 = entry_price + (risk_dist * 4.0)
        else:
            swing_high = max(highs[-5:]) if len(highs) >= 5 else entry_price * 1.02
            stop_loss = max(swing_high, entry_price + (atr * 1.5))
            if stop_loss <= entry_price:
                stop_loss = entry_price * 1.015
            
            risk_dist = stop_loss - entry_price
            tp1 = entry_price - (risk_dist * 1.5)
            tp2 = entry_price - (risk_dist * 2.5)
            tp3 = entry_price - (risk_dist * 4.0)

        sl_pct = round(abs(entry_price - stop_loss) / entry_price * 100, 2)
        tp1_pct = round(abs(tp1 - entry_price) / entry_price * 100, 2)

        return round(stop_loss, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4), sl_pct, tp1_pct
