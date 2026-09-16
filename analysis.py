import time
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
            logger.error(f"فشل الاتصال بالمنصة عند التهيئة: {e}")

    def fetch_ohlcv_data(self, symbol, timeframe='1h', limit=150, retries=2, delay=1):
        """جلب بيانات الشموع مع آلية إعادة المحاولة (Retry) وحماية ضد الأخطاء والانقطاعات"""
        for attempt in range(retries + 1):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                if not ohlcv or len(ohlcv) < 25:
                    logger.warning(f"[DATA] {symbol} {timeframe} insufficient candles or empty response.")
                    return None
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                return df
            except Exception as e:
                logger.warning(f"[RATE LIMIT / ERROR] {symbol} {timeframe} attempt {attempt+1} failed: {e}")
                if attempt < retries:
                    time.sleep(delay)
                else:
                    logger.error(f"[DATA FETCH FAILED] {symbol} {timeframe} after {retries+1} attempts.")
                    return None
        return None

    def calculate_indicators(self, df):
        """حساب المؤشرات الفنية، الـ ATR، السيولة، والقمم/القيعان بلطف بدون انهيار"""
        if df is None or len(df) < 20:
            return df
        try:
            # ATR
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

            # Volume MA
            df['vol_ma'] = df['volume'].rolling(window=20).mean()
            df['high_volume'] = df['volume'] > (df['vol_ma'] * 1.2)

            # Swing Points (Fractals عبر نافذة 5 شموع)
            df['is_swing_high'] = (df['high'] == df['high'].rolling(window=5, center=True).max())
            df['is_swing_low'] = (df['low'] == df['low'].rolling(window=5, center=True).min())

            # FVG (Fair Value Gap)
            df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))
            df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))
        except Exception as e:
            logger.error(f"خطأ أثناء حساب المؤشرات: {e}")
        return df

    def get_market_structure(self, df):
        """تحليل الهيكل السعري (BOS و MSS) بدقة وأمان"""
        if df is None or len(df) < 20:
            return "NEUTRAL", False, False, False, False
        try:
            swing_highs = df[df['is_swing_high'] == True]
            swing_lows = df[df['is_swing_low'] == True]

            if len(swing_highs) < 2 or len(swing_lows) < 2:
                return "NEUTRAL", False, False, False, False

            last_sh = swing_highs['high'].iloc[-1]
            last_sl = swing_lows['low'].iloc[-1]
            prev_sh = swing_highs['high'].iloc[-2]
            prev_sl = swing_lows['low'].iloc[-2]

            current_close = df.iloc[-2]['close']  # آخر شمعة مغلقة

            bullish_bos = current_close > last_sh
            bearish_bos = current_close < last_sl

            if last_sh > prev_sh and last_sl > prev_sl:
                trend = "BULLISH"
            elif last_sh < prev_sh and last_sl < prev_sl:
                trend = "BEARISH"
            else:
                trend = "NEUTRAL"

            mss_bullish = bearish_bos and (trend == "BEARISH" or last_sh > prev_sh)
            mss_bearish = bullish_bos and (trend == "BULLISH" or last_sl < prev_sl)

            return trend, bullish_bos, bearish_bos, mss_bullish, mss_bearish
        except Exception as e:
            logger.error(f"خطأ في تحليل الهيكل السعري: {e}")
            return "NEUTRAL", False, False, False, False

    def detect_order_block(self, df):
        """تحديد Order Block مؤسسي حقيقي"""
        if df is None or len(df) < 15:
            return False, False, 0.0
        try:
            for i in range(len(df) - 3, max(4, len(df) - 12), -1):
                row = df.iloc[i]
                next_row = df.iloc[i+1]
                
                # Bullish OB
                if row['close'] < row['open'] and next_row['close'] > next_row['open'] and next_row['volume'] > (next_row['vol_ma'] * 1.1):
                    ob_zone = row['low']
                    current_price = df.iloc[-1]['close']
                    if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 2.0):
                        return True, False, ob_zone

                # Bearish OB
                elif row['close'] > row['open'] and next_row['close'] < next_row['open'] and next_row['volume'] > (next_row['vol_ma'] * 1.1):
                    ob_zone = row['high']
                    current_price = df.iloc[-1]['close']
                    if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 2.0):
                        return False, True, ob_zone
        except Exception as e:
            logger.error(f"خطأ في كشف الـ OB: {e}")
        return False, False, 0.0

    def check_liquidity_sweep(self, df):
        """فحص أخذ السيولة (Liquidity Sweep)"""
        if df is None or len(df) < 15:
            return False, False
        try:
            recent_high = df['high'].iloc[-12:-2].max()
            recent_low = df['low'].iloc[-12:-2].min()
            last_high = df.iloc[-2]['high']
            last_low = df.iloc[-2]['low']
            last_close = df.iloc[-2]['close']

            sweep_high = last_high > recent_high and last_close < recent_high
            sweep_low = last_low < recent_low and last_close > recent_low
            return sweep_high, sweep_low
        except Exception as e:
            return False, False

    def get_premium_discount(self, df):
        """تحديد مناطق الديسكونت والبريميوم"""
        if df is None or len(df) < 20:
            return "EQUILIBRIUM"
        try:
            high_range = df['high'].iloc[-20:-2].max()
            low_range = df['low'].iloc[-20:-2].min()
            mid_point = (high_range + low_range) / 2
            current_price = df.iloc[-1]['close']

            if current_price < mid_point:
                return "DISCOUNT"
            elif current_price > mid_point:
                return "PREMIUM"
        except Exception as e:
            pass
        return "EQUILIBRIUM"

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):
        try:
            # 1. جلب البيانات للفريمات المختلفة مع تجنب انهيار العملة عند فشل فريم فرعي
            df_1d = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=40)
            df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=40)
            df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=80)
            df_30m = self.fetch_ohlcv_data(symbol, timeframe='30m', limit=30)
            df_15m = self.fetch_ohlcv_data(symbol, timeframe='15m', limit=30)

            # Bitcoin Context
            df_btc_1h = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe='1h', limit=40)

            if df_1h is None or len(df_1h) < 30:
                return {
                    "Decision": "NO TRADE ⏳",
                    "Symbol": symbol,
                    "Reason": "DATA FETCH FAILED",
                    "Score": 0,
                    "Quality": "WEAK"
                }

            # حساب المؤشرات
            df_1h = self.calculate_indicators(df_1h)
            if df_4h is not None: df_4h = self.calculate_indicators(df_4h)
            if df_1d is not None: df_1d = self.calculate_indicators(df_1d)
            if df_30m is not None: df_30m = self.calculate_indicators(df_30m)
            if df_15m is not None: df_15m = self.calculate_indicators(df_15m)
            if df_btc_1h is not None: df_btc_1h = self.calculate_indicators(df_btc_1h)

            # استخراج الاتجاهات والهيكل
            trend_1d, _, _, _, _ = self.get_market_structure(df_1d)
            trend_4h, _, _, _, _ = self.get_market_structure(df_4h)
            trend_1h, bos_1h_bull, bos_1h_bear, mss_1h_bull, mss_1h_bear = self.get_market_structure(df_1h)

            _, _, _, mss_30m_bull, mss_30m_bear = self.get_market_structure(df_30m)
            _, _, _, mss_15m_bull, mss_15m_bear = self.get_market_structure(df_15m)
            btc_trend, _, _, _, _ = self.get_market_structure(df_btc_1h)

            sweep_high, sweep_low = self.check_liquidity_sweep(df_1h)
            bull_ob, bear_ob, ob_level = self.detect_order_block(df_1h)
            zone_status = self.get_premium_discount(df_1h)

            last_closed = df_1h.iloc[-2]
            current_price = df_1h.iloc[-1]['close']
            current_atr = last_closed.get('atr', current_price * 0.01)
            high_vol = last_closed.get('high_volume', False)
            fvg_bull = last_closed.get('bullish_fvg', False)
            fvg_bear = last_closed.get('bearish_fvg', False)

            # ----------------------------------------------------
            # شروط التقييم غير المتشددة ومنع التحويل التلقائي
            # ----------------------------------------------------
            is_long_valid = (
                trend_1h in ["BULLISH", "NEUTRAL"] and
                trend_4h != "BEARISH" and
                zone_status != "PREMIUM" and
                (bos_1h_bull or mss_1h_bull or mss_30m_bull or mss_15m_bull or bull_ob or sweep_low) and
                btc_trend != "BEARISH"
            )

            is_short_valid = (
                trend_1h in ["BEARISH", "NEUTRAL"] and
                trend_4h != "BULLISH" and
                zone_status != "DISCOUNT" and
                (bos_1h_bear or mss_1h_bear or mss_30m_bear or mss_15m_bear or bear_ob or sweep_high) and
                btc_trend != "BULLISH"
            )

            # فحص التعارضات القوية
            if trend_1d == "BEARISH" and trend_4h == "BEARISH" and is_long_valid:
                is_long_valid = False
            if trend_1d == "BULLISH" and trend_4h == "BULLISH" and is_short_valid:
                is_short_valid = False

            direction = "NEUTRAL"
            decision = "NO TRADE ⏳"
            score = 0
            reason = "NO STRUCTURE OR CONFLICT"

            if is_long_valid and not is_short_valid:
                direction = "LONG"
                decision = "MARKET LONG 🟢"
                score += 20 if trend_4h == "BULLISH" else 10
                score += 15 if trend_1h == "BULLISH" else 10
                score += 15 if zone_status == "DISCOUNT" else 10
                score += 10 if sweep_low else 0
                score += 10 if bull_ob else 0
                score += 10 if high_vol else 0
                score += 10 if (bos_1h_bull or mss_1h_bull) else 5
                score += 10 if (mss_30m_bull or mss_15m_bull) else 0
                score += 5 if btc_trend != "BEARISH" else 0
                reason = "Balanced Bullish SMC/ICT Alignment"

            elif is_short_valid and not is_long_valid:
                direction = "SHORT"
                decision = "MARKET SHORT 🔴"
                score += 20 if trend_4h == "BEARISH" else 10
                score += 15 if trend_1h == "BEARISH" else 10
                score += 15 if zone_status == "PREMIUM" else 10
                score += 10 if sweep_high else 0
                score += 10 if bear_ob else 0
                score += 10 if high_vol else 0
                score += 10 if (bos_1h_bear or mss_1h_bear) else 5
                score += 10 if (mss_30m_bear or mss_15m_bear) else 0
                score += 5 if btc_trend != "BULLISH" else 0
                reason = "Balanced Bearish SMC/ICT Alignment"

            # حد القبول لفتح الصفقة (Score >= 65)
            if score < 65 or direction == "NEUTRAL":
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
                    "Reason": reason if score > 0 else "SCORE BELOW THRESHOLD / NO SETUP"
                }

            # تحديد الجودة بناءً على الـ Score
            if score >= 85:
                quality = "🟢 STRONG"
            elif score >= 75:
                quality = "🟡 MEDIUM"
            else:
                quality = "🔴 WEAK"

            # إدارة المخاطر والوقف والأهداف
            recent_sl_low = df_1h['low'].iloc[-15:-2].min()
            recent_sh_high = df_1h['high'].iloc[-15:-2].max()
            allowed_risk_usd = account_balance * risk_percentage

            if direction == "LONG":
                base_sl = ob_level if (bull_ob and ob_level > 0) else recent_sl_low
                stop_loss = base_sl - (0.4 * current_atr)
                
                max_allowed_sl = current_price - (6.0 * current_atr)
                min_allowed_sl = current_price - (0.4 * current_atr)
                if stop_loss < max_allowed_sl: stop_loss = max_allowed_sl
                if stop_loss > min_allowed_sl: stop_loss = min_allowed_sl

                risk_per_token = current_price - stop_loss
                if risk_per_token <= 0: risk_per_token = current_atr * 1.5

                sl_distance_pct = round((risk_per_token / current_price) * 100, 2)
                tp1 = current_price + (2.0 * risk_per_token)
                tp2 = current_price + (3.5 * risk_per_token)
                tp3 = current_price + (5.0 * risk_per_token)
                rr_ratio = 3.5
            else:
                base_sl = ob_level if (bear_ob and ob_level > 0) else recent_sh_high
                stop_loss = base_sl + (0.4 * current_atr)

                max_allowed_sl = current_price + (6.0 * current_atr)
                min_allowed_sl = current_price + (0.4 * current_atr)
                if stop_loss > max_allowed_sl: stop_loss = max_allowed_sl
                if stop_loss < min_allowed_sl: stop_loss = min_allowed_sl

                risk_per_token = stop_loss - current_price
                if risk_per_token <= 0: risk_per_token = current_atr * 1.5

                sl_distance_pct = round((risk_per_token / current_price) * 100, 2)
                tp1 = current_price - (2.0 * risk_per_token)
                tp2 = current_price - (3.5 * risk_per_token)
                tp3 = current_price - (5.0 * risk_per_token)
                rr_ratio = 3.5

            if sl_distance_pct > 9.0 or sl_distance_pct < 0.3:
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
                    "Reason": "SL INVALID (TOO WIDE OR TOO CLOSE)"
                }

            position_tokens = allowed_risk_usd / risk_per_token
            position_value_usdt = position_tokens * current_price
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

        except Exception as e:
            logger.error(f"[ANALYSIS ERROR] Failed analyzing {symbol}: {e}")
            return {
                "Decision": "NO TRADE ⏳",
                "Symbol": symbol,
                "Reason": "ANALYSIS ERROR",
                "Score": 0,
                "Quality": "WEAK"
            }
