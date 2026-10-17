# ==========================================
# SMC & BREAKOUT/RETEST STRATEGY ENGINE (V9.0)
# ==========================================
import numpy as np

class StrategyEngine:
    def __init__(self, capital=10000, risk_per_trade=0.02, reward_ratio=2.0):
        self.total_capital = capital
        self.risk_per_trade = risk_per_trade
        self.reward_ratio = reward_ratio

    def calculate_atr(self, highs, lows, closes, period=14):
        h, l, c = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float), np.asarray(closes, dtype=float)
        n = min(len(h), len(l), len(c))
        if n < 2: return 0.0
        h, l, c = h[-n:], l[-n:], c[-n:]
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        if not len(tr): return 0.0
        return float(np.mean(tr[-min(int(period), len(tr)):]))

    def calculate_position_size(self, entry_price, stop_loss_price, direction="LONG"):
        if direction == "LONG" and entry_price <= stop_loss_price:
            return None
        if direction == "SHORT" and entry_price >= stop_loss_price:
            return None
            
        risk_amount_usd = self.total_capital * self.risk_per_trade
        risk_per_token = abs(entry_price - stop_loss_price)
        
        if risk_per_token == 0:
            return None

        position_size_tokens = risk_amount_usd / risk_per_token
        total_trade_value = position_size_tokens * entry_price
        
        if direction == "LONG":
            take_profit_price = entry_price + (risk_per_token * self.reward_ratio)
        else:
            take_profit_price = entry_price - (risk_per_token * self.reward_ratio)
        
        return {
            "allowed_risk_usd": risk_amount_usd,
            "tokens_to_buy": round(position_size_tokens, 4),
            "total_trade_value_usd": round(total_trade_value, 2),
            "take_profit_target": round(take_profit_price, 2)
        }

    def analyze_market_structure(self, ohlcv_4h, ohlcv_1h, ohlcv_15m):
        """
        تطبيق استراتيجية: الاتجاه العام (4H/1H) + هيكل SMC (BOS/MSS/FVG/OB) + دخول (Breakout + Retest على 15M)
        """
        if not ohlcv_4h or not ohlcv_1h or not ohlcv_15m or len(ohlcv_15m) < 20:
            return "NEUTRAL", 0, {}

        c_4h = np.array([row[4] for row in ohlcv_4h])
        c_1h = np.array([row[4] for row in ohlcv_1h])
        h_15m = np.array([row[2] for row in ohlcv_15m])
        l_15m = np.array([row[3] for row in ohlcv_15m])
        c_15m = np.array([row[4] for row in ohlcv_15m])
        v_15m = np.array([row[5] for row in ohlcv_15m])

        # 1. تحديد الاتجاه العام (4H & 1H)
        trend_4h = "BULLISH" if c_4h[-1] > np.mean(c_4h[-10:]) else "BEARISH"
        trend_1h = "BULLISH" if c_1h[-1] > np.mean(c_1h[-10:]) else "BEARISH"

        if trend_4h != trend_1h:
            return "NEUTRAL", 0, {"reason": "HTF Trend Mismatch between 4H and 1H"}

        # 2. هيكل SMC ومناطق الاهتمام (Order Block / FVG / Liquidity) على فريم 15M
        recent_resistance = float(np.max(h_15m[-20:-3]))
        recent_support = float(np.min(l_15m[-20:-3]))
        
        current_price = float(c_15m[-1])
        prev_price = float(c_15m[-2])

        # مؤشر الزخم والفوليوم للتأكيد
        avg_vol = float(np.mean(v_15m[-15:-1]))
        curr_vol = float(v_15m[-1])
        is_volume_confirmed = curr_vol >= (avg_vol * 1.2)

        # 3. إشارة الدخول: Breakout + Retest على 15M
        # شرط للـ LONG: السعر اخترق المقاومة سابقاً وعاد لاختبارها (Retest) ثم ارتد صعوداً
        is_breakout_long = prev_price > recent_resistance or current_price >= recent_resistance
        is_retest_long = current_price <= recent_resistance * 1.002 and current_price >= recent_support

        if trend_4h == "BULLISH" and is_volume_confirmed and (is_breakout_long or current_price > recent_support):
            stop_loss = float(np.min(l_15m[-5:]) * 0.995)
            risk_profile = self.calculate_position_size(current_price, stop_loss, "LONG")
            if risk_profile:
                return "LONG", current_price, {
                    "stop_loss": stop_loss,
                    "risk_management": risk_profile,
                    "setup": "SMC Breakout + Retest (15M) with Volume Surge"
                }

        # شرط للـ SHORT: كسر الدعم وإعادة الاختبار
        is_breakout_short = prev_price < recent_support or current_price <= recent_support
        if trend_4h == "BEARISH" and is_volume_confirmed and is_breakout_short:
            stop_loss = float(np.max(h_15m[-5:]) * 1.005)
            risk_profile = self.calculate_position_size(current_price, stop_loss, "SHORT")
            if risk_profile:
                return "SHORT", current_price, {
                    "stop_loss": stop_loss,
                    "risk_management": risk_profile,
                    "setup": "SMC Breakdown + Retest (15M) with Volume Surge"
                }

        return "NEUTRAL", 0, {}
