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

            # FVG Conditions
            df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))    
            df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))    
        except Exception as e:    
            logger.error(f"خطأ في حساب المؤشرات: {e}")    
        return df    

    def get_market_structure(self, df):    
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

            current_close = df.iloc[-2]['close']    

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
        except Exception:    
            return "NEUTRAL", False, False, False, False    

    def detect_order_block(self, df):    
        if df is None or len(df) < 10:    
            return False, False, 0.0    
        try:    
            for i in range(len(df) - 3, max(3, len(df) - 10), -1):    
                row = df.iloc[i]    
                next_row = df.iloc[i+1]    
                    
                if row['close'] < row['open'] and next_row['close'] > next_row['open']:    
                    ob_zone = row['low']    
                    current_price = df.iloc[-1]['close']    
                    if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 2.5):    
                        return True, False, ob_zone    

                elif row['close'] > row['open'] and next_row['close'] < next_row['open']:    
                    ob_zone = row['high']    
                    current_price = df.iloc[-1]['close']    
                    if abs(current_price - ob_zone) <= (df.iloc[-1]['atr'] * 2.5):    
                        return False, True, ob_zone    
        except Exception:    
            pass    
        return False, False, 0.0    

    def check_liquidity_sweep(self, df):    
        if df is None or len(df) < 10:    
            return False, False    
        try:    
            recent_high = df['high'].iloc[-10:-2].max()    
            recent_low = df['low'].iloc[-10:-2].min()    
            last_high = df.iloc[-2]['high']    
            last_low = df.iloc[-2]['low']    
            last_close = df.iloc[-2]['close']    

            sweep_high = last_high > recent_high and last_close < recent_high    
            sweep_low = last_low < recent_low and last_close > recent_low    
            return sweep_high, sweep_low    
        except Exception:    
            return False, False    

    def get_premium_discount(self, df):    
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
        try:    
            df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=60)    
            if df_1h is None or len(df_1h) < 25:    
                return {"Decision": "NO TRADE ⏳", "Reason": "DATA FETCH FAILED", "Score": 0, "Quality": "WEAK"}    

            df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=30)    
            df_1d = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=20)    
            df_btc = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe='1h', limit=30)    

            df_1h = self.calculate_indicators(df_1h)    
            if df_4h is not None: df_4h = self.calculate_indicators(df_4h)    
            if df_1d is not None: df_1d = self.calculate_indicators(df_1d)    
            if df_btc is not None: df_btc = self.calculate_indicators(df_btc)    

            trend_1d, _, _, _, _ = self.get_market_structure(df_1d)    
            trend_4h, _, _, _, _ = self.get_market_structure(df_4h)    
            trend_1h, bos_bull, bos_bear, mss_bull, mss_bear = self.get_market_structure(df_1h)    
            btc_trend, _, _, _, _ = self.get_market_structure(df_btc)    

            sweep_high, sweep_low = self.check_liquidity_sweep(df_1h)    
            bull_ob, bear_ob, ob_level = self.detect_order_block(df_1h)    
            zone_status = self.get_premium_discount(df_1h)    

            last_closed = df_1h.iloc[-2]    
            current_price = df_1h.iloc[-1]['close']    
            current_atr = last_closed.get('atr', current_price * 0.01)    
            
            bull_fvg = last_closed.get('bullish_fvg', False)
            bear_fvg = last_closed.get('bearish_fvg', False)

            long_score = 50
            short_score = 50
            reasons_long = []
            reasons_short = []

            if trend_1h in ["BULLISH", "NEUTRAL"]: long_score += 10
            if trend_4h != "BEARISH": long_score += 10
            if zone_status != "PREMIUM": long_score += 10
            if btc_trend != "BEARISH": long_score += 10

            if trend_1h in ["BEARISH", "NEUTRAL"]: short_score += 10
            if trend_4h != "BULLISH": short_score += 10
            if zone_status != "DISCOUNT": short_score += 10
            if btc_trend != "BULLISH": short_score += 10

            if bos_bull: long_score += 15; reasons_long.append("BOS")
            if mss_bull: long_score += 15; reasons_long.append("MSS")
            if bull_ob: long_score += 15; reasons_long.append("OrderBlock")
            if bull_fvg: long_score += 10; reasons_long.append("FVG")
            if sweep_low: long_score += 10; reasons_long.append("Sweep")

            if bos_bear: short_score += 15; reasons_short.append("BOS")
            if mss_bear: short_score += 15; reasons_short.append("MSS")
            if bear_ob: short_score += 15; reasons_short.append("OrderBlock")
            if bear_fvg: short_score += 10; reasons_short.append("FVG")
            if sweep_high: short_score += 10; reasons_short.append("Sweep")

            is_long = long_score >= 75
            is_short = short_score >= 75

            if is_long and not is_short:
                direction = "LONG"
                decision = "MARKET LONG 🟢"
                score = long_score
                reason = " + ".join(reasons_long) if reasons_long else "Bullish Setup"
            elif is_short and not is_long:
                direction = "SHORT"
                decision = "MARKET SHORT 🔴"
                score = short_score
                reason = " + ".join(reasons_short) if reasons_short else "Bearish Setup"
            elif is_long and is_short:
                if long_score >= short_score:
                    direction = "LONG"
                    decision = "MARKET LONG 🟢"
                    score = long_score
                    reason = " + ".join(reasons_long) if reasons_long else "Bullish Setup"
                else:
                    direction = "SHORT"
                    decision = "MARKET SHORT 🔴"
                    score = short_score
                    reason = " + ".join(reasons_short) if reasons_short else "Bearish Setup"
            else:
                return {
                    "Decision": "NO TRADE ⏳",
                    "Reason": "SCORE BELOW THRESHOLD",
                    "Score": max(long_score, short_score),
                    "Quality": "WEAK"
                }

            recent_low = df_1h['low'].iloc[-12:-2].min()    
            recent_high = df_1h['high'].iloc[-12:-2].max()    
            allowed_risk = account_balance * risk_percentage    
            min_risk_distance = current_atr * 0.8

            if direction == "LONG":    
                calculated_sl = max(recent_low - (0.5 * current_atr), current_price - (4.0 * current_atr))
                risk_per_token = current_price - calculated_sl
                if risk_per_token < min_risk_distance:
                    risk_per_token = min_risk_distance
                    stop_loss = current_price - risk_per_token
                else:
                    stop_loss = calculated_sl
                tp1 = current_price + (2.0 * risk_per_token)    
                tp2 = current_price + (3.5 * risk_per_token)    
            else:    
                calculated_sl = min(recent_high + (0.5 * current_atr), current_price + (4.0 * current_atr))
                risk_per_token = calculated_sl - current_price
                if risk_per_token < min_risk_distance:
                    risk_per_token = min_risk_distance
                    stop_loss = current_price + risk_per_token
                else:
                    stop_loss = calculated_sl
                tp1 = current_price - (2.0 * risk_per_token)    
                tp2 = current_price - (3.5 * risk_per_token)    

            pos_tokens = allowed_risk / risk_per_token    
            pos_val = pos_tokens * current_price    
            max_allowed_pos_val = account_balance * 5.0
            if pos_val > max_allowed_pos_val:
                pos_val = max_allowed_pos_val

            leverage = max(1, min(10, int(pos_val / account_balance) + 1))    
            quality_str = "🔥 EXCELLENT" if score >= 90 else ("🟢 STRONG" if score >= 80 else "🟡 MEDIUM")

            return {    
                "Decision": decision,    
                "Entry": round(current_price, 4),    
                "Stop Loss": round(stop_loss, 4),    
                "TP1": round(tp1, 4),    
                "TP2": round(tp2, 4),    
                "Score": score,    
                "Quality": quality_str,    
                "Position Size (USDT)": round(pos_val, 2),    
                "Leverage": leverage,    
                "Reason": reason    
            }    

        except Exception as e:    
            logger.error(f"[CRITICAL ANALYSIS ERROR] {symbol}: {e}")    
            return {    
                "Decision": "NO TRADE ⏳",    
                "Reason": "ANALYSIS ERROR HANDLED",    
                "Score": 0,    
                "Quality": "WEAK"    
            }
