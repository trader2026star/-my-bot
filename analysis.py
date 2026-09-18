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

    def fetch_ohlcv_data(self, symbol, timeframe='1h', limit=60, retries=1, delay=1):    
        """جلب بيانات الشموع بحد أقصى مخفض لتوفير الذاكرة وحماية الـ RAM"""    
        for attempt in range(retries + 1):    
            try:    
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)    
                if not ohlcv or len(ohlcv) < 20:    
                    return None    
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])    
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')    
                return df    
            except Exception as e:    
                logger.warning(f"[RETRY {attempt+1}] Failed fetching {symbol} {timeframe}: {e}")    
                if attempt < retries:    
                    time.sleep(delay)    
                else:    
                    return None    
        return None    

    def calculate_indicators(self, df):    
        """حساب المؤشرات الفنية والـ FVG والـ Volume MA"""    
        if df is None or len(df) < 15:    
            return df    
        try:    
            high_low = df['high'] - df['low']    
            high_close = np.abs(df['high'] - df['close'].shift())    
            low_close = np.abs(df['low'] - df['close'].shift())    
            ranges = pd.concat([high_low, high_close, low_close], axis=1)    
            df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()    

            df['vol_ma'] = df['volume'].rolling(window=20).mean()    
            df['high_volume'] = df['volume'] > (df['vol_ma'] * 1.2)    

            df['is_swing_high'] = (df['high'] == df['high'].rolling(window=5, center=True).max())    
            df['is_swing_low'] = (df['low'] == df['low'].rolling(window=5, center=True).min())    

            df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))    
            df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))    
        except Exception as e:    
            logger.error(f"خطأ في حساب المؤشرات: {e}")    
        return df    

    def get_market_structure(self, df):    
        """تحليل الهيكل السعري مع فصل دقيق بين Bullish BOS و Bearish BOS"""    
        if df is None or len(df) < 15:    
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

            closed_close = df.iloc[-2]['close']    

            bullish_bos = closed_close > last_sh    
            bearish_bos = closed_close < last_sl    

            if last_sh > prev_sh and last_sl > prev_sl:    
                trend = "BULLISH"    
            elif last_sh < prev_sh and last_sl < prev_sl:    
                trend = "BEARISH"    
            else:    
                trend = "NEUTRAL"    

            # تحسين منطق الـ MSS ليكون انعكاساً حقيقياً مدعوماً بكسر قاع/قمة سابقة
            mss_bullish = bearish_bos and (trend == "BEARISH" or last_sh > prev_sh or closed_close > prev_sh)    
            mss_bearish = bullish_bos and (trend == "BULLISH" or last_sl < prev_sl or closed_close < prev_sl)    

            return trend, bullish_bos, bearish_bos, mss_bullish, mss_bearish    
        except Exception:    
            return "NEUTRAL", False, False, False, False    

    def detect_order_block(self, df):    
        """كشف مناطق الـ Order Block القريبة والدقيقة"""    
        if df is None or len(df) < 10:    
            return False, False, 0.0, 0.0    
        try:    
            current_price = df.iloc[-1]['close']
            atr = df.iloc[-1].get('atr', current_price * 0.01)

            bullish_ob_found = False
            bearish_ob_found = False
            bull_ob_level = 0.0
            bear_ob_level = 0.0

            for i in range(len(df) - 3, max(2, len(df) - 10), -1):    
                row = df.iloc[i]    
                next_row = df.iloc[i+1]    
                    
                if row['close'] < row['open'] and next_row['close'] > next_row['open']:    
                    ob_zone = row['low']    
                    if abs(current_price - ob_zone) <= (atr * 4.0):    
                        bullish_ob_found = True
                        bull_ob_level = ob_zone
                        break

            for i in range(len(df) - 3, max(2, len(df) - 10), -1):    
                row = df.iloc[i]    
                next_row = df.iloc[i+1]    
                    
                if row['close'] > row['open'] and next_row['close'] < next_row['open']:    
                    ob_zone = row['high']    
                    if abs(current_price - ob_zone) <= (atr * 4.0):    
                        bearish_ob_found = True
                        bear_ob_level = ob_zone
                        break

            return bullish_ob_found, bearish_ob_found, bull_ob_level, bear_ob_level
        except Exception:    
            pass    
        return False, False, 0.0, 0.0    

    def check_liquidity_sweep(self, df):    
        """فحص أخذ السيولة (Sweep High / Sweep Low) بدقة"""    
        if df is None or len(df) < 10:    
            return False, False    
        try:    
            recent_high = df['high'].iloc[-10:-2].max()    
            recent_low = df['low'].iloc[-10:-2].min()    
            last_high = df.iloc[-2]['high']    
            last_low = df.iloc[-2]['low']    
            last_close = df.iloc[-2]['close']    
            last_open = df.iloc[-2]['open']

            sweep_high = (last_high > recent_high) and (last_close < recent_high) and (last_close < last_open)
            sweep_low = (last_low < recent_low) and (last_close > recent_low) and (last_close > last_open)
            
            return sweep_high, sweep_low    
        except Exception:    
            return False, False    

    def get_premium_discount(self, df):    
        """تحديد مناطق الديسكونت والبريميوم"""    
        if df is None or len(df) < 15:    
            return "EQUILIBRIUM"    
        try:    
            high_range = df['high'].iloc[-15:-2].max()    
            low_range = df['low'].iloc[-15:-2].min()    
            mid_point = (high_range + low_range) / 2    
            current_price = df.iloc[-1]['close']    

            if current_price < mid_point:    
                return "DISCOUNT"    
            elif current_price > mid_point:    
                return "PREMIUM"    
        except Exception:    
            pass    
        return "EQUILIBRIUM"    

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):    
        """تقييم الاستراتيجية مع تطبيق الـ Hard Entry Gates وحماية كاملة ضد الصفقات المتناقضة"""    
        try:    
            df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=40)    
            if df_1h is None or len(df_1h) < 20:    
                return {    
                    "Decision": "NO TRADE ⏳",    
                    "Reason": "DATA FETCH FAILED",    
                    "Score": 0,    
                    "Quality": "WEAK"    
                }    

            df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=25)    
            df_btc = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe='1h', limit=25)    

            df_1h = self.calculate_indicators(df_1h)    
            if df_4h is not None: df_4h = self.calculate_indicators(df_4h)    
            if df_btc is not None: df_btc = self.calculate_indicators(df_btc)    

            trend_4h, _, _, _, _ = self.get_market_structure(df_4h)    
            trend_1h, bos_bull, bos_bear, mss_bull, mss_bear = self.get_market_structure(df_1h)    
            btc_trend, _, _, _, _ = self.get_market_structure(df_btc)    

            sweep_high, sweep_low = self.check_liquidity_sweep(df_1h)    
            bull_ob, bear_ob, bull_ob_lvl, bear_ob_lvl = self.detect_order_block(df_1h)    
            zone_status = self.get_premium_discount(df_1h)    

            last_closed = df_1h.iloc[-2]    
            current_price = df_1h.iloc[-1]['close']    
            current_atr = last_closed.get('atr', current_price * 0.01)    
            high_vol = last_closed.get('high_volume', False)    
            
            has_bull_fvg = last_closed.get('bullish_fvg', False)
            has_bear_fvg = last_closed.get('bearish_fvg', False)

            body_size = abs(last_closed['close'] - last_closed['open'])
            strong_displacement = body_size > (current_atr * 0.8) and high_vol

            # حساب السكور الديناميكي بناءً على الأدلة (مجموع 100)
            long_score = 0
            if trend_4h in ["BULLISH", "NEUTRAL"]: long_score += 15
            if trend_1h == "BULLISH": long_score += 20
            if bos_bull: long_score += 15
            if mss_bull: long_score += 10
            if sweep_low: long_score += 10
            if bull_ob: long_score += 10
            if has_bull_fvg: long_score += 5
            if strong_displacement: long_score += 5
            if zone_status == "DISCOUNT": long_score += 10
            if btc_trend != "BEARISH": long_score += 10

            short_score = 0
            if trend_4h in ["BEARISH", "NEUTRAL"]: short_score += 15
            if trend_1h == "BEARISH": short_score += 20
            if bos_bear: short_score += 15
            if mss_bear: short_score += 10
            if sweep_high: short_score += 10
            if bear_ob: short_score += 10
            if has_bear_fvg: short_score += 5
            if strong_displacement: short_score += 5
            if zone_status == "PREMIUM": short_score += 10
            if btc_trend != "BULLISH": short_score += 10

            # تطبيق شروط الحماية الصارمة (Hard Entry Gates) لمنع التناقضات المطلقة
            # منع الشورت الخاطئ
            short_blocked_reasons = []
            if trend_1h == "BULLISH" and not (sweep_high and mss_bear and strong_displacement):
                short_blocked_reasons.append("1H BULLISH WITHOUT VALID SWEEP/MSS")
            if bos_bull and not (sweep_high and mss_bear):
                short_blocked_reasons.append("BOS BULLISH CONFLICT")
            if trend_4h == "BULLISH" and trend_1h == "BULLISH":
                short_blocked_reasons.append("4H & 1H BOTH BULLISH")

            # منع اللونج الخاطئ
            long_blocked_reasons = []
            if trend_1h == "BEARISH" and not (sweep_low and mss_bull and strong_displacement):
                long_blocked_reasons.append("1H BEARISH WITHOUT VALID SWEEP/MSS")
            if bos_bear and not (sweep_low and mss_bull):
                long_blocked_reasons.append("BOS BEARISH CONFLICT")
            if trend_4h == "BEARISH" and trend_1h == "BEARISH":
                long_blocked_reasons.append("4H & 1H BOTH BEARISH")

            # التحقق النهائي للقرار
            THRESHOLD = 75
            direction = "NEUTRAL"
            final_score = 0
            reason = "NO CLEAR SETUP"

            # تقييم إمكانية الشورت
            can_short = (len(short_blocked_reasons) == 0) and (short_score >= THRESHOLD) and (short_score > long_score)
            # تقييم إمكانية اللونج
            can_long = (len(long_blocked_reasons) == 0) and (long_score >= THRESHOLD) and (long_score > short_score)

            if can_short:
                direction = "SHORT"
                final_score = int(short_score)
                reason = "Dynamic Bearish SMC Setup Confirmed"
            elif can_long:
                direction = "LONG"
                final_score = int(long_score)
                reason = "Dynamic Bullish SMC Setup Confirmed"
            else:
                # تحديد سبب الرفض بوضوح
                block_msg = "INSUFFICIENT CONFIRMATION"
                if len(short_blocked_reasons) > 0 and short_score >= long_score:
                    block_msg = f"SHORT BLOCKED: {short_blocked_reasons[0]}"
                elif len(long_blocked_reasons) > 0 and long_score > short_score:
                    block_msg = f"LONG BLOCKED: {long_blocked_reasons[0]}"

                return {    
                    "Decision": "NO TRADE ⏳",    
                    "Reason": block_msg,    
                    "Score": max(int(long_score), int(short_score)),    
                    "Quality": "WEAK"    
                }    

            recent_low = df_1h['low'].iloc[-10:-2].min()    
            recent_high = df_1h['high'].iloc[-10:-2].max()    
            allowed_risk = account_balance * risk_percentage    

            if direction == "LONG":    
                decision = "MARKET LONG 🟢"
                base_sl = min(recent_low, bull_ob_lvl) if bull_ob_lvl > 0 else recent_low
                stop_loss = base_sl - (1.0 * current_atr)
                
                if stop_loss >= current_price:
                    stop_loss = current_price - (1.5 * current_atr)

                risk_per_token = current_price - stop_loss    
                if risk_per_token <= 0: 
                    risk_per_token = current_atr * 1.5
                    stop_loss = current_price - risk_per_token

                tp1 = current_price + (2.0 * risk_per_token)    
                tp2 = current_price + (3.5 * risk_per_token)    
                tp3 = current_price + (4.5 * risk_per_token)
            else:    
                decision = "MARKET SHORT 🔴"
                base_sl = max(recent_high, bear_ob_lvl) if bear_ob_lvl > 0 else recent_high
                stop_loss = base_sl + (1.0 * current_atr)

                if stop_loss <= current_price:
                    stop_loss = current_price + (1.5 * current_atr)

                risk_per_token = stop_loss - current_price    
                if risk_per_token <= 0: 
                    risk_per_token = current_atr * 1.5
                    stop_loss = current_price + risk_per_token

                tp1 = current_price - (2.0 * risk_per_token)    
                tp2 = current_price - (3.5 * risk_per_token)    
                tp3 = current_price - (4.5 * risk_per_token)

            pos_tokens = allowed_risk / risk_per_token    
            pos_val = pos_tokens * current_price    
            leverage = max(1, min(10, int(pos_val / account_balance) + 1))    

            return {    
                "Decision": decision,    
                "Entry": round(current_price, 4),    
                "Stop Loss": round(stop_loss, 4),    
                "TP1": round(tp1, 4),    
                "TP2": round(tp2, 4),    
                "TP3": round(tp3, 4),
                "Score": final_score,    
                "Quality": "🟢 STRONG" if final_score >= 85 else "🟡 MEDIUM",    
                "Position Size (USDT)": round(pos_val, 2),    
                "Leverage": leverage,    
                "Reason": reason,
                "Direction": direction,
                "Trend 1D": trend_4h,
                "Trend 4H": trend_4h,
                "Trend 1H": trend_1h,
                "BTC Trend": btc_trend,
                "Liquidity Sweep": "High Sweep" if sweep_high else ("Low Sweep" if sweep_low else "None"),
                "BOS": "Bullish" if bos_bull else ("Bearish" if bos_bear else "None"),
                "MSS": "Bullish" if mss_bull else ("Bearish" if mss_bear else "None")
            }    

        except Exception as e:    
            logger.error(f"[CRITICAL ANALYSIS ERROR] {symbol}: {e}")    
            return {    
                "Decision": "NO TRADE ⏳",    
                "Reason": "ANALYSIS ERROR HANDLED",    
                "Score": 0,    
                "Quality": "WEAK"    
            }
