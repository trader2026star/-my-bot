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

    def fetch_ohlcv_data(self, symbol, timeframe='1h', limit=100, retries=1, delay=1):    
        for attempt in range(retries + 1):    
            try:    
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)    
                if not ohlcv or len(ohlcv) < 30:    
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
        if df is None or len(df) < 20:    
            return df    
        try:    
            high_low = df['high'] - df['low']    
            high_close = np.abs(df['high'] - df['close'].shift())    
            low_close = np.abs(df['low'] - df['close'].shift())    
            ranges = pd.concat([high_low, high_close, low_close], axis=1)    
            df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()    

            df['vol_ma'] = df['volume'].rolling(window=20).mean()    
            df['vol_std'] = df['volume'].rolling(window=20).std()
            df['institutional_volume'] = df['volume'] > (df['vol_ma'] + (1.5 * df['vol_std']))

            df['is_swing_high'] = (df['high'] == df['high'].rolling(window=5, center=True).max())    
            df['is_swing_low'] = (df['low'] == df['low'].rolling(window=5, center=True).min())    

            df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))    
            df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))    
        except Exception as e:    
            logger.error(f"خطأ في حساب المؤشرات: {e}")    
        return df    

    def get_market_structure(self, df):    
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

            closed_close = df.iloc[-2]['close']    

            bullish_bos = closed_close > last_sh    
            bearish_bos = closed_close < last_sl    

            if last_sh > prev_sh and last_sl > prev_sl:    
                trend = "BULLISH"    
            elif last_sh < prev_sh and last_sl < prev_sl:    
                trend = "BEARISH"    
            else:    
                trend = "NEUTRAL"    

            mss_bullish = bearish_bos and (closed_close > prev_sh or trend == "BULLISH")    
            mss_bearish = bullish_bos and (closed_close < prev_sl or trend == "BEARISH")    

            return trend, bullish_bos, bearish_bos, mss_bullish, mss_bearish    
        except Exception:    
            return "NEUTRAL", False, False, False, False    

    def detect_order_block(self, df):    
        if df is None or len(df) < 15:    
            return False, False, 0.0, 0.0, "None"    
        try:    
            current_price = df.iloc[-1]['close']
            atr = df.iloc[-1].get('atr', current_price * 0.01)

            bullish_ob_found = False
            bearish_ob_found = False
            bull_ob_level = 0.0
            bear_ob_level = 0.0
            ob_status = "None"

            for i in range(len(df) - 3, max(2, len(df) - 12), -1):    
                row = df.iloc[i]    
                next_row = df.iloc[i+1]    
                if row['close'] < row['open'] and next_row['close'] > next_row['open']:    
                    ob_zone = row['low']    
                    if abs(current_price - ob_zone) <= (atr * 5.0):    
                        bullish_ob_found = True
                        bull_ob_level = ob_zone
                        ob_status = "Institutional Bullish OB"
                        break

            for i in range(len(df) - 3, max(2, len(df) - 12), -1):    
                row = df.iloc[i]    
                next_row = df.iloc[i+1]    
                if row['close'] > row['open'] and next_row['close'] < next_row['open']:    
                    ob_zone = row['high']    
                    if abs(current_price - ob_zone) <= (atr * 5.0):    
                        bearish_ob_found = True
                        bear_ob_level = ob_zone
                        ob_status = "Institutional Bearish OB"
                        break

            return bullish_ob_found, bearish_ob_found, bull_ob_level, bear_ob_level, ob_status
        except Exception:    
            pass    
        return False, False, 0.0, 0.0, "None"    

    def check_liquidity_sweep(self, df):    
        if df is None or len(df) < 15:    
            return False, False    
        try:    
            recent_high = df['high'].iloc[-15:-2].max()    
            recent_low = df['low'].iloc[-15:-2].min()    
            last_high = df.iloc[-2]['high']    
            last_low = df.iloc[-2]['low']    
            last_close = df.iloc[-2]['close']    
            last_open = df.iloc[-2]['open']

            sweep_high = (last_high > recent_high) and (last_close < recent_high) and (last_close < last_open)
            sweep_low = (last_low < recent_low) and (last_close > recent_low) and (last_close > last_open)
            
            return sweep_high, sweep_low    
        except Exception:    
            return False, False    

    def get_volume_profile_poc(self, df):    
        try:
            prices = df['close'].values
            volumes = df['volume'].values
            
            bins = np.linspace(prices.min(), prices.max(), 10)
            bin_indices = np.digitize(prices, bins)
            bin_volumes = [volumes[bin_indices == i].sum() for i in range(1, len(bins))]
            
            max_vol_bin_idx = np.argmax(bin_volumes)
            poc_price = (bins[max_vol_bin_idx] + bins[max_vol_bin_idx+1]) / 2
            
            current_price = prices[-1]
            if current_price > poc_price:
                return "ABOVE_POC", poc_price
            else:
                return "BELOW_POC", poc_price
        except Exception:
            return "NEUTRAL_POC", 0.0

    def evaluate_strategy(self, symbol='BTC/USDT:USDT', account_balance=1000.0, risk_percentage=0.01):    
        try:    
            df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=70)    
            if df_1h is None or len(df_1h) < 30:    
                return {"Decision": "NO TRADE ⏳", "Reason": "SCORE BELOW THRESHOLD / NO SETUP", "Score": 50, "Quality": "WEAK"}    

            df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=40)    
            df_btc = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe='1h', limit=40)    

            df_1h = self.calculate_indicators(df_1h)    
            if df_4h is not None: df_4h = self.calculate_indicators(df_4h)    
            if df_btc is not None: df_btc = self.calculate_indicators(df_btc)    

            trend_4h, _, _, _, _ = self.get_market_structure(df_4h)    
            trend_1h, bos_bull, bos_bear, mss_bull, mss_bear = self.get_market_structure(df_1h)    
            btc_trend, _, _, _, _ = self.get_market_structure(df_btc)    

            sweep_high, sweep_low = self.check_liquidity_sweep(df_1h)    
            bull_ob, bear_ob, bull_ob_lvl, bear_ob_lvl, ob_status = self.detect_order_block(df_1h)    
            poc_status, poc_price = self.get_volume_profile_poc(df_1h)

            last_closed = df_1h.iloc[-2]    
            current_price = df_1h.iloc[-1]['close']    
            current_atr = last_closed.get('atr', current_price * 0.01)    
            inst_vol = last_closed.get('institutional_volume', False)    
            
            has_bull_fvg = last_closed.get('bullish_fvg', False)
            has_bear_fvg = last_closed.get('bearish_fvg', False)

            body_size = abs(last_closed['close'] - last_closed['open'])
            strong_displacement = body_size > (current_atr * 0.9)

            # نظام النقاط والفلترة المتوافقة مع التقرير
            long_score = 50
            if trend_4h == "BULLISH": long_score += 10
            if trend_1h == "BULLISH": long_score += 10
            if bos_bull or mss_bull: long_score += 5
            if sweep_low: long_score += 5
            if bull_ob: long_score += 5

            short_score = 50
            if trend_4h == "BEARISH": short_score += 10
            if trend_1h == "BEARISH": short_score += 10
            if bos_bear or mss_bear: short_score += 5
            if sweep_high: short_score += 5
            if bear_ob: short_score += 5

            THRESHOLD = 75 
            STOP_LOSS_MAX_PCT = 0.08  
            direction = "NEUTRAL"
            final_score = 50

            is_long_valid = (long_score >= THRESHOLD) and (long_score > short_score)
            is_short_valid = (short_score >= THRESHOLD) and (short_score > long_score)

            if is_short_valid:
                direction = "SHORT"
                final_score = int(min(short_score, 75))
                reason = "Balanced Bearish Setup"
            elif is_long_valid:
                direction = "LONG"
                final_score = int(min(long_score, 75))
                reason = "Balanced Bullish Setup"
            else:
                return {    
                    "Decision": "NO TRADE ⏳",    
                    "Reason": "SCORE BELOW THRESHOLD / NO SETUP",    
                    "Score": 50,    
                    "Quality": "WEAK"    
                }    

            recent_low = df_1h['low'].iloc[-12:-2].min()    
            recent_high = df_1h['high'].iloc[-12:-2].max()    
            allowed_risk = account_balance * risk_percentage    

            if direction == "LONG":    
                decision = "MARKET LONG 🟢"
                base_sl = min(recent_low, bull_ob_lvl) if bull_ob_lvl > 0 else recent_low
                stop_loss = base_sl - (1.0 * current_atr)
                if stop_loss >= current_price: stop_loss = current_price * 0.995
                
                if (current_price - stop_loss) / current_price > STOP_LOSS_MAX_PCT:
                    stop_loss = current_price * (1.0 - STOP_LOSS_MAX_PCT)

                risk_per_token = current_price - stop_loss    
                if risk_per_token <= 0: risk_per_token = current_atr * 1.5

                tp1 = current_price + (1.5 * risk_per_token)    
                tp2 = current_price + (2.5 * risk_per_token)    
            else:    
                decision = "MARKET SHORT 🔴"
                base_sl = max(recent_high, bear_ob_lvl) if bear_ob_lvl > 0 else recent_high
                stop_loss = base_sl + (1.0 * current_atr)
                if stop_loss <= current_price: stop_loss = current_price * 1.005
                
                if (stop_loss - current_price) / current_price > STOP_LOSS_MAX_PCT:
                    stop_loss = current_price * (1.0 + STOP_LOSS_MAX_PCT)

                risk_per_token = stop_loss - current_price    
                if risk_per_token <= 0: risk_per_token = current_atr * 1.5

                tp1 = current_price - (1.5 * risk_per_token)    
                tp2 = current_price - (2.5 * risk_per_token)    

            pos_tokens = allowed_risk / risk_per_token if risk_per_token > 0 else 100
            pos_val = pos_tokens * current_price    
            leverage = 1 if pos_val <= account_balance else 2

            quality_str = "🟢 STRONG" if final_score >= 75 else "WEAK"

            return {    
                "Decision": decision,    
                "Entry": round(current_price, 4),    
                "Stop Loss": round(stop_loss, 4),    
                "TP1": round(tp1, 4),    
                "TP2": round(tp2, 4),    
                "Score": final_score,    
                "Quality": quality_str,    
                "Position Size (USDT)": round(pos_val, 2),    
                "Leverage": leverage,    
                "Reason": reason
            }    

        except Exception as e:    
            logger.error(f"[CRITICAL ANALYSIS ERROR] {symbol}: {e}")    
            return {"Decision": "NO TRADE ⏳", "Reason": "SCORE BELOW THRESHOLD / NO SETUP", "Score": 50, "Quality": "WEAK"}
