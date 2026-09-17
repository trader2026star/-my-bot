import os
import time
import random
import logging
import requests
import threading
import ccxt
import pandas as pd
import numpy as np
from flask import Flask

# =====================================================================
# 1. إعداد السجلات (Logging)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =====================================================================
# 2. محرك استراتيجية المال الذكي (SMC Trading Analyst)
# =====================================================================
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

    def fetch_ohlcv_data(self, symbol, timeframe='1h', limit=100, retries=2, delay=1):
        """جلب بيانات الشموع مع آلية إعادة المحاولة وحماية كاملة ضد الأخطاء"""
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
        """حساب المؤشرات بأمان تام وبدون النظر إلى المستقبل (تجنب Look-ahead bias)"""
        if df is None or len(df) < 25:
            return df
        try:
            # حساب الـ ATR
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            df['atr'] = np.max(ranges, axis=1).rolling(window=14).mean()

            # حساب مؤشرات الفوليوم
            df['vol_ma'] = df['volume'].rolling(window=20).mean()
            df['high_volume'] = df['volume'] > (df['vol_ma'] * 1.2)

            # تحديد القمم والقيعان (Swing High/Low) تاريخياً وبأمان (الاعتماد على الشموع المغلقة فقط)
            df['is_swing_high'] = (df['high'].shift(2) > df['high'].shift(4)) & \
                                  (df['high'].shift(2) > df['high'].shift(3)) & \
                                  (df['high'].shift(2) > df['high'].shift(1)) & \
                                  (df['high'].shift(2) > df['high'])

            df['is_swing_low'] = (df['low'].shift(2) < df['low'].shift(4)) & \
                                 (df['low'].shift(2) < df['low'].shift(3)) & \
                                 (df['low'].shift(2) < df['low'].shift(1)) & \
                                 (df['low'].shift(2) < df['low'])

            # حساب الفجوات السعرية (FVG)
            df['bullish_fvg'] = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1))
            df['bearish_fvg'] = (df['high'] < df['low'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1))
        except Exception as e:
            logger.error(f"خطأ في حساب المؤشرات: {e}")
        return df

    def get_market_structure(self, df):
        """تحليل الهيكل السعري وتصحيح منطق الـ BOS والـ MSS"""
        if df is None or len(df) < 25:
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

            current_close = df.iloc[-1]['close']

            # كسر الهيكل (BOS)
            bullish_bos = current_close > last_sh
            bearish_bos = current_close < last_sl

            # تحديد الاتجاه العام
            if last_sh > prev_sh and last_sl > prev_sl:
                trend = "BULLISH"
            elif last_sh < prev_sh and last_sl < prev_sl:
                trend = "BEARISH"
            else:
                trend = "NEUTRAL"

            # تغير بنية السوق (MSS)
            mss_bullish = (current_close > last_sh) and (trend == "BEARISH")
            mss_bearish = (current_close < last_sl) and (trend == "BULLISH")

            return trend, bullish_bos, bearish_bos, mss_bullish, mss_bearish
        except Exception:
            return "NEUTRAL", False, False, False, False

    def detect_order_block(self, df):
        """كشف مناطق الـ Order Block القريبة من السعر الحالي"""
        if df is None or len(df) < 15:
            return False, False, 0.0
        try:
            for i in range(len(df) - 3, max(3, len(df) - 15), -1):
                row = df.iloc[i]
                next_row = df.iloc[i+1]
                current_price = df.iloc[-1]['close']
                atr = df.iloc[-1]['atr'] if not pd.isna(df.iloc[-1]['atr']) else (current_price * 0.01)
                
                # Bullish OB
                if row['close'] < row['open'] and next_row['close'] > next_row['open']:
                    ob_zone = row['low']
                    if abs(current_price - ob_zone) <= (atr * 2.5):
                        return True, False, ob_zone

                # Bearish OB
                elif row['close'] > row['open'] and next_row['close'] < next_row['open']:
                    ob_zone = row['high']
                    if abs(current_price - ob_zone) <= (atr * 2.5):
                        return False, True, ob_zone
        except Exception:
            pass
        return False, False, 0.0

    def check_liquidity_sweep(self, df):
        """فحص ضرب السيولة السعرية للقمم والقيعان القريبة"""
        if df is None or len(df) < 15:
            return False, False
        try:
            recent_high = df['high'].iloc[-12:-2].max()
            recent_low = df['low'].iloc[-12:-2].min()
            last_high = df.iloc[-1]['high']
            last_low = df.iloc[-1]['low']
            last_close = df.iloc[-1]['close']

            sweep_high = last_high > recent_high and last_close < recent_high
            sweep_low = last_low < recent_low and last_close > recent_low
            return sweep_high, sweep_low
        except Exception:
            return False, False

    def get_premium_discount(self, df):
        """تحديد موقع السعر الحالي بالنسبة لمصفوفة الـ PD Matrix"""
        if df is None or len(df) < 20:
            return "EQUILIBRIUM"
        try:
            high_range = df['high'].iloc[-20:-1].max()
            low_range = df['low'].iloc[-20:-1].min()
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
        """الدالة الرئيسية: تجميع نقاط قوة شروط SMC وحساب إدارة المخاطر"""
        try:
            df_1h = self.fetch_ohlcv_data(symbol, timeframe='1h', limit=100)
            if df_1h is None or len(df_1h) < 30:
                return {"Decision": "NO TRADE ⏳", "Reason": "DATA FETCH FAILED OR INSUFFICIENT", "Score": 0}

            df_4h = self.fetch_ohlcv_data(symbol, timeframe='4h', limit=100)
            df_1d = self.fetch_ohlcv_data(symbol, timeframe='1d', limit=100)
            df_btc = self.fetch_ohlcv_data('BTC/USDT:USDT', timeframe='1h', limit=100)

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

            current_price = df_1h.iloc[-1]['close']
            atr = df_1h.iloc[-1]['atr'] if not pd.isna(df_1h.iloc[-1]['atr']) else (current_price * 0.01)

            bullish_score = 0
            bearish_score = 0

            if trend_1d == "BULLISH": bullish_score += 1
            if trend_1d == "BEARISH": bearish_score += 1
            if trend_4h == "BULLISH": bullish_score += 1
            if trend_4h == "BEARISH": bearish_score += 1
            if btc_trend == "BULLISH": bullish_score += 1
            if btc_trend == "BEARISH": bearish_score += 1

            if mss_bull or bos_bull: bullish_score += 2
