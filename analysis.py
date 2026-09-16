import ccxt
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmartMoneyTradingAnalyst:
    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        try:
            self.exchange.load_markets()
            logger.info(f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} وتحميل أسواق الـ Swap.")
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة: {e}")

    def fetch_ohlcv_data(self, symbol, timeframe='1h', limit=150):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"خطأ أثناء جلب بيانات الشموع لـ {symbol} على فريم {timeframe}: {e}")
            return None

    def calculate_indicators(self, df):
        """حساب المؤشرات الأساسية: ATR، القمم والقيعان الحقيقية، والفجوات FVG، والـ OB، والـ Volume"""
        if df is None or len(df) < 50:
            return df

        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

        # Volume MA لتحديد الفوليوم المرتفع
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        df['high_volume'] = df['volume'] > (df['vol_ma'] * 1.3)

        # قمم وقيعان هيكلية مؤكدة (Fractal / Swing High & Low عبر نافذة 5 شموع)
        df['is_swing_high'] = (df['high'] == df['high'].rolling(window=5, center=True).max())
        df['is_swing_low'] = (df['low'] == df['low'].rolling(window=5, center=True).min())

        # FVG (Fair Value Gap)
        df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))
        df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))

        return df

    def get_market_structure(self, df):
        """تحليل الهيكل (BOS, MSS/CHoCH) وتحديد اتجاه الفريم"""
        if df is None or len(df) < 30:
            return "NEUTRAL", False, False, False, False

        # العثور على آخر قمة وقاع مؤكدين
        swing_highs = df[df['is_swing_high'] == True]
        swing_lows = df[df['is_swing_low'] == True]

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "NEUTRAL", False, False, False, False

        last_swing_high = swing_highs['high'].iloc[-1]
        last_swing_low = swing_lows['low'].iloc[-1]
        prev_swing_high = swing_highs['high'].iloc[-2]
        prev_swing_low = swing_lows['low'].iloc[-2]

        current_close = df.iloc[-2]['close']  # آخر شمعة مغلقة

        # BOS & MSS Detection
        bullish_bos = current_close > last_swing_high
        bearish_bos = current_close < last_swing_low

        # تحديد اتجاه الهيكل العام
        if last_swing_high > prev_swing_high and last_swing_low > prev_swing_low:
            trend = "BULLISH"
        elif last_swing_high < prev_swing_high and last_swing_low < prev_swing_low:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        # MSS / CHoCH (تغير الشخصية: كسر قاع سابق في اتجاه صاعد أو قمة في اتجاه هابط)
        mss_bullish = bearish_bos and (trend == "BEARISH" or last_swing_high > prev_swing_high)
        mss_bearish = bullish_bos and (trend == "BULLISH" or last_swing_low < prev_swing_low)

        return trend, bullish_bos, bearish_bos, mss_bullish, mss_bearish

    def detect_order_block(self, df):
        """تحديد Order Block حقيقي (آخر شمعة معاكسة قبل الـ Displacement / BOS)"""
        if df is None or len(df) < 20:
            return False, False, 0.0

        # البحث في آخر 10 شموع مغلقة عن شمعة معاكسة سبقت حركة قوية (Displacement)
        for i in range(len(df) - 3, max(5, len(df) - 15), -1):
            row = df.iloc[i]
            next_row = df.iloc[i+1]
            
            # Displacement صاعد: شمعة هابطة تليها شمعة صاعدة قوية بحجم يتجاوز المتوسط
            if row['close'] < row['open'] and next_row['close'] > next_row['open'] and next_row['volume'] > (next_row['vol_ma'] * 1.2):
                ob_zone = row['low']
                current_price = df.iloc[-1]['close']
                # التأكد أن السعر قريب من منطقة الـ OB أو عاد إليها (بحدود 1.5 ATR)
                if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 1.5):
                    return True, False, ob_zone

            # Displacement هابط: شمعة صاعدة تليها شمعة هابطة قوية
            elif row['close'] > row['open'] and next_row['close'] < next_row['open'] and next_row['volume'] > (next_row['vol_ma'] * 1.2):
                ob_zone = row['high']
                current_price = df.iloc[-1]['close']
                if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 1.5):
                    return False, True, ob_zone

        return False, False, 0.0

    def check_liquidity_sweep(self, df):
        """فحص أخذ السيولة (Sweep للقمم أو القيعان السابقة ثم الارتداد)"""
        if df is None or len(df) < 20:
            return False, False

        recent_high = df['high'].iloc[-15:-2].max()
        recent_low = df['low'].iloc[-15:-2].min()

        last_high = df.iloc[-2]['high']
        last_low = df.iloc[-2]['low']
        last_close = df.iloc[-2]['close']
        prev_close = df.iloc[-3]['close']

        # Sweep قمة (اختراق وهمي بذيْل الشمعة ثم الاغلاق تحتها)
        sweep_high = last_high > recent_high and last_close < recent_high
        # Sweep قاع (كسر وهمي بذيْل الشمعة ثم الاغلاق فوقه)
        sweep_low = last_low < recent_low and last_close > recent_low

        return sweep_high, sweep_low

    def get_premium_discount(self, df):
        """تحديد موقع السعر الحالي (Discount للـ Long، Premium للـ Short)"""
        if df is None or len(df) < 30:
            return "EQUILIBRIUM"

        high_range = df['high'].iloc[-30:-2].max()
        low_range = df['low'].iloc[-30:-2].min()
        mid_point = (high_range + low_range) / 2
        current_price = df.iloc[-1]['close']

        if current_price < mid_point:
            return "DISCOUNT"
        elif current_price > mid_point:
            return "PREMIUM"
        return "EQUILIBRIUM"

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        # 1. جلب البيانات للفريمات المختلفة (تجنب تعطل البوت عند فشل فريم معين)
        df_1d = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=50)
        df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=50)
        df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=100)
        df_30m = self.fetch_ohlcv_data(symbol, timeframe='30m', limit=50)
        df_15m = self.fetch_ohlcv_data(symbol, timeframe='15m', limit=50)

        # جلب بيانات البيتكوين (BTC Context) كفلتر للسوق
        btc_symbol = 'BTC/USDT:USDT'
        df_btc_1h = self.fetch_ohlcv_data(btc_symbol, timeframe='1h', limit=50)

        if df_1h is None or len(df_1h) < 50:
            return {
                "Decision": "NO TRADE",
                "Symbol": symbol,
                "Reason": "DATA FETCH FAILED",
                "Score": 0,
                "Quality": "WEAK"
            }

        # حساب المؤشرات للفريمات الرئيسية
        df_1h = self.calculate_indicators(df_1h)
        if df_4h is not None: df_4h = self.calculate_indicators(df_4h)
        if df_1d is not None: df_1d = self.calculate_indicators(df_1d)
        if df_btc_1h is not None: df_btc_1h = self.calculate_indicators(df_btc_1h)

        # استخراج اتجاهات الفريمات
        trend_1d, _, _, _, _ = self.get_market_structure(df_1d)
        trend_4h, _, _, _, _ = self.get_market_structure(df_4h)
        trend_1h, bos_1h_bull, bos_1h_bear, mss_1h_bull, mss_1h_bear = self.get_market_structure(df_1h)

        # تأكيدات الفريمات الصغرى
        _, _, _, mss_30m_bull, mss_30m_bear = self.get_market_structure(df_30m)
        _, _, _, mss_15m_bull, mss_15m_bear = self.get_market_structure(df_15m)

        # فحص البيتكوين (BTC Context)
        btc_trend, _, _, _, _ = self.get_market_structure(df_btc_1h)

        # فحص السيولة والـ OB والـ FVG والـ Zone
        sweep_high, sweep_low = self.check_liquidity_sweep(df_1h)
        bull_ob, bear_ob, ob_level = self.detect_order_block(df_1h)
        zone_status = self.get_premium_discount(df_1h)

        last_closed = df_1h.iloc[-2]
        current_price = df_1h.iloc[-1]['close']
        current_atr = last_closed['atr']
        high_vol = last_closed['high_volume']
        fvg_bull = last_closed['bullish_fvg']
        fvg_bear = last_closed['bearish_fvg']

        # ----------------------------------------------------
        # المنطق الصارم للتقييم واتخاذ القرار (بدون تحويل تلقائي)
        # ----------------------------------------------------
        decision = "NO TRADE"
        reason = "NO STRUCTURE"
        direction = "NEUTRAL"
        score = 0

        # شروط تأكيد الـ LONG الحقيقية
        is_long_valid = (
            trend_1d != "BEARISH" and
            trend_4h != "BEARISH" and
            zone_status == "DISCOUNT" and
            (sweep_low or bull_ob or fvg_bull) and
            (bos_1h_bull or mss_1h_bull or mss_30m_bull or mss_15m_bull) and
            btc_trend != "BEARISH"
        )

        # شروط تأكيد الـ SHORT الحقيقية
        is_short_valid = (
            trend_1d != "BULLISH" and
            trend_4h != "BULLISH" and
            zone_status == "PREMIUM" and
            (sweep_high or bear_ob or fvg_bear) and
            (bos_1h_bear or mss_1h_bear or mss_30m_bear or mss_15m_bear) and
            btc_trend != "BULLISH"
        )

        # التحقق من التعارضات القوية (Conflict Check)
        if trend_1d == "BEARISH" and trend_4h == "BEARISH" and is_long_valid:
            is_long_valid = False
            reason = "TIMEFRAME CONFLICT (Higher TF Bearish)"

        if trend_1d == "BULLISH" and trend_4h == "BULLISH" and is_short_valid:
            is_short_valid = False
            reason = "TIMEFRAME CONFLICT (Higher TF Bullish)"

        # فلترة بيتكويت المعاكس بقوة
        if btc_trend == "BEARISH" and is_long_valid:
            is_long_valid = False
            reason = "BTC CONFLICT (BTC Bearish)"

        if btc_trend == "BULLISH" and is_short_valid:
            is_short_valid = False
            reason = "BTC CONFLICT (BTC Bullish)"

        # حساب السكور (Score / 100) ونظام النقاط الداعم للجودة
        if is_long_valid and not is_short_valid:
            direction = "LONG"
            decision = "MARKET LONG 🟢"
            score += 25 if trend_4h == "BULLISH" else 15
            score += 20 if zone_status == "DISCOUNT" else 10
            score += 15 if sweep_low else 5
            score += 15 if bull_ob else 5
            score += 15 if high_vol else 0
            score += 10 if (bos_1h_bull or mss_1h_bull) else 5
            reason = "Bullish SMC/ICT Alignment with OB/Sweep & Discount Zone"

        elif is_short_valid and not is_long_valid:
            direction = "SHORT"
            decision = "MARKET SHORT 🔴"
            score += 25 if trend_4h == "BEARISH" else 15
            score += 20 if zone_status == "PREMIUM" else 10
            score += 15 if sweep_high else 5
            score += 15 if bear_ob else 5
            score += 15 if high_vol else 0
            score += 10 if (bos_1h_bear or mss_1h_bear) else 5
            reason = "Bearish SMC/ICT Alignment with OB/Sweep & Premium Zone"
        else:
            if trend_1d == "NEUTRAL" and trend_4h == "NEUTRAL":
                reason = "NO STRUCTURE"
            elif sweep_high == False and sweep_low == False and not (bull_ob or bear_ob):
                reason = "NO LIQUIDITY SWEEP OR OB"
            elif not (bos_1h_bull or bos_1h_bear or mss_1h_bull or mss_1h_bear):
                reason = "NO MSS/BOS"
            elif not high_vol:
                reason = "WEAK VOLUME"
            else:
                reason = "CONFLICTING EVIDENCE / NO TRADE"

            return {
                "Decision": "NO TRADE ⏳",
                "Symbol": symbol,
                "Current Price": round(current_price, 4),
                "Direction": "NEUTRAL",
                "Score": score,
                "Quality": "WEAK",
                "Entry": 0,
                "Stop Loss": 0,
                "SL Distance %": 0,
                "TP1": 0,
                "TP2": 0,
                "TP3": 0,
                "Risk/Reward": 0,
                "Position Size (USDT)": 0,
                "Leverage": 1,
                "Trend 1D": trend_1d,
                "Trend 4H": trend_4h,
                "Trend 1H": trend_1h,
                "Confirmation 30m": mss_30m_bull or mss_30m_bear,
                "Confirmation 15m": mss_15m_bull or mss_15m_bear,
                "Liquidity Sweep": sweep_high or sweep_low,
                "MSS": mss_1h_bull or mss_1h_bear,
                "BOS": bos_1h_bull or bos_1h_bear,
                "Order Block": bull_ob or bear_ob,
                "FVG": fvg_bull or fvg_bear,
                "Displacement": high_vol,
                "BTC Context": btc_trend,
                "Reason": reason
            }

        # تحديد تصنيف الجودة بناءً على الـ Score
        if score >= 75:
            quality = "🟢 STRONG"
        elif score >= 50:
            quality = "🟡 MEDIUM"
        else:
            quality = "🔴 WEAK"

        # ----------------------------------------------------
        # حساب إدارة المخاطر (Stop Loss & Take Profits) بدقة
        # ----------------------------------------------------
        recent_swing_low = df_1h['low'].iloc[-20:-2].min()
        recent_swing_high = df_1h['high'].iloc[-20:-2].max()
        allowed_risk_usd = account_balance * risk_percentage

        if direction == "LONG":
            # وقف الخسارة خلف الـ OB أو القاع مع ATR buffer صغير
            base_sl = ob_level if (bull_ob and ob_level > 0) else recent_swing_low
            stop_loss = base_sl - (0.3 * current_atr)
            
            # حماية ضد SL قريب جداً أو بعيد مبالغ فيه
            max_allowed_sl = current_price - (5.0 * current_atr)
            min_allowed_sl = current_price - (0.5 * current_atr)
            if stop_loss < max_allowed_sl: stop_loss = max_allowed_sl
            if stop_loss > min_allowed_sl: stop_loss = min_allowed_sl

            risk_per_token = current_price - stop_loss
            if risk_per_token <= 0: risk_per_token = current_atr * 1.5

            sl_distance_pct = round((risk_per_token / current_price) * 100, 2)
            
            # حساب الأهداف المتعددة (TP1: 2R, TP2: 3.5R, TP3: 5R)
            tp1 = current_price + (2.0 * risk_per_token)
            tp2 = current_price + (3.5 * risk_per_token)
            tp3 = current_price + (5.0 * risk_per_token)
            rr_ratio = 3.5

        else: # SHORT
            base_sl = ob_level if (bear_ob and ob_level > 0) else recent_swing_high
            stop_loss = base_sl + (0.3 * current_atr)

            max_allowed_sl = current_price + (5.0 * current_atr)
            min_allowed_sl = current_price + (0.5 * current_atr)
            if stop_loss > max_allowed_sl: stop_loss = max_allowed_sl
            if stop_loss < min_allowed_sl: stop_loss = min_allowed_sl

            risk_per_token = stop_loss - current_price
            if risk_per_token <= 0: risk_per_token = current_atr * 1.5

            sl_distance_pct = round((risk_per_token / current_price) * 100, 2)

            tp1 = current_price - (2.0 * risk_per_token)
            tp2 = current_price - (3.5 * risk_per_token)
            tp3 = current_price - (5.0 * risk_per_token)
            rr_ratio = 3.5

        # رفض الصفقة إذا كان الـ SL غير منطقي أو واسع جداً
        if sl_distance_pct > 8.0 or sl_distance_pct < 0.4:
            return {
                "Decision": "NO TRADE ⏳",
                "Symbol": symbol,
                "Current Price": round(current_price, 4),
                "Direction": "NEUTRAL",
                "Score": score,
                "Quality": "WEAK",
                "Entry": round(current_price, 4),
                "Stop Loss": round(stop_loss, 4),
                "SL Distance %": sl_distance_pct,
                "TP1": round(tp1, 4),
                "TP2": round(tp2, 4),
                "TP3": round(tp3, 4),
                "Risk/Reward": rr_ratio,
                "Position Size (USDT)": 0,
                "Leverage": 1,
                "Trend 1D": trend_1d,
                "Trend 4H": trend_4h,
                "Trend 1H": trend_1h,
                "Confirmation 30m": mss_30m_bull or mss_30m_bear,
                "Confirmation 15m": mss_15m_bull or mss_15m_bear,
                "Liquidity Sweep": sweep_high or sweep_low,
                "MSS": mss_1h_bull or mss_1h_bear,
                "BOS": bos_1h_bull or bos_1h_bear,
                "Order Block": bull_ob or bear_ob,
                "FVG": fvg_bull or fvg_bear,
                "Displacement": high_vol,
                "BTC Context": btc_trend,
                "Reason": "SL TOO WIDE OR TOO CLOSE"
            }

        # حساب حجم الصفقة (Position Sizing) بناءً على المخاطر الثابتة
        position_tokens = allowed_risk_usd / risk_per_token
        position_value_usdt = position_tokens * current_price
        
        # الرافعة المالية كنتيجة لإدارة المخاطر وليست سبباً لها
        leverage = max(1, min(10, int(position_value_usdt / account_balance) + 1))

        return {
            "Decision": decision,
            "Symbol": symbol,
            "Current Price": round(current_price, 4),
            "Direction": direction,
            "Score": score,
            "Quality": quality,
            "Entry": round(current_price, 4),
            "Stop Loss": round(stop_loss, 4),
            "SL Distance %": sl_distance_pct,
            "TP1": round(tp1, 4),
            "TP2": round(tp2, 4),
            "TP3": round(tp3, 4),
            "Risk/Reward": rr_ratio,
            "Position Size (USDT)": round(position_value_usdt, 2),
            "Leverage": leverage,
            "Trend 1D": trend_1d,
            "Trend 4H": trend_4h,
            "Trend 1H": trend_1h,
            "Confirmation 30m": mss_30m_bull or mss_30m_bear,
            "Confirmation 15m": mss_15m_bull or mss_15m_bear,
            "Liquidity Sweep": sweep_high or sweep_low,
            "MSS": mss_1h_bull or mss_1h_bear,
            "BOS": bos_1h_bull or bos_1h_bear,
            "Order Block": bull_ob or bear_ob,
            "FVG": fvg_bull or fvg_bear,
            "Displacement": high_vol,
            "BTC Context": btc_trend,
            "Reason": reason
        }
