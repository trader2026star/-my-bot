import logging
import time
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    def __init__(
        self,
        exchange_id='bingx',
        api_key='',
        secret_key='',
        timeframe='15m'
    ):
        self.exchange_id = exchange_id
        self.timeframe = timeframe

        exchange_class = getattr(ccxt, exchange_id)

        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        })

        self.cache = {}
        self.cache_seconds = 20
        self.oi_history = {}

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    def _safe_float(self, value, default=0.0):
        try:
            value = float(value)
            if np.isfinite(value):
                return value
        except Exception:
            pass
        return default

    # =========================================================
    # DATA & FETCHING
    # =========================================================

    def _fetch_ohlcv(self, symbol, timeframe, limit=250, market_type='swap'):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF',
            'NZD', 'NCFX', 'USDCUSD'
        ]

        if any(token in symbol.upper() for token in unwanted_tokens):
            return None

        key = f"{symbol}:{market_type}:{timeframe}:{limit}"
        now = time.time()

        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            if market_type == 'spot':
                self.exchange.options['defaultType'] = 'spot'
            else:
                self.exchange.options['defaultType'] = 'swap'

            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 50:
                return None

            df = pd.DataFrame(
                data,
                columns=[
                    'timestamp',
                    'open',
                    'high',
                    'low',
                    'close',
                    'volume'
                ]
            )

            for col in [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]:
                df[col] = pd.to_numeric(
                    df[col],
                    errors='coerce'
                )

            df = (
                df
                .dropna()
                .reset_index(drop=True)
            )

            if len(df) < 50:
                return None

            self.cache[key] = {
                'time': now,
                'data': df
            }

            return df.copy()

        except Exception as e:
            logger.warning(
                "OHLCV error %s (%s) %s: %s",
                symbol,
                market_type,
                timeframe,
                e
            )
            return None

    # =========================================================
    # INDICATORS & SUPERTREND (أفضل مؤشر لتأكيد الاتجاه)
    # =========================================================

    def _prepare(self, df):
        df = df.copy()

        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema20_slope'] = df['ema20'].diff(3)

        # حساب الـ ATR
        prev_close = df['close'].shift(1)
        tr = pd.concat(
            [
                df['high'] - df['low'],
                (df['high'] - prev_close).abs(),
                (df['low'] - prev_close).abs()
            ],
            axis=1
        ).max(axis=1)

        df['atr'] = tr.ewm(span=14, adjust=False).mean()

        # حساب مؤشر الـ Supertrend (المماثل للموجود في المنصة)
        period = 10
        multiplier = 3.0
        
        hl2 = (df['high'] + df['low']) / 2
        df['basic_upper'] = hl2 + (multiplier * df['atr'])
        df['basic_lower'] = hl2 - (multiplier * df['atr'])
        
        df['final_upper'] = df['basic_upper']
        df['final_lower'] = df['basic_lower']
        
        supertrend = [True] * len(df)
        
        for i in range(1, len(df)):
            curr_close = df['close'].iloc[i]
            prev_close_val = df['close'].iloc[i - 1]
            
            if df['basic_upper'].iloc[i] < df['final_upper'].iloc[i - 1] or prev_close_val > df['final_upper'].iloc[i - 1]:
                df.loc[df.index[i], 'final_upper'] = df['basic_upper'].iloc[i]
            else:
                df.loc[df.index[i], 'final_upper'] = df['final_upper'].iloc[i - 1]
                
            if df['basic_lower'].iloc[i] > df['final_lower'].iloc[i - 1] or prev_close_val < df['final_lower'].iloc[i - 1]:
                df.loc[df.index[i], 'final_lower'] = df['basic_lower'].iloc[i]
            else:
                df.loc[df.index[i], 'final_lower'] = df['final_lower'].iloc[i - 1]

        # تحديد اتجاه الـ Supertrend
        df['supertrend_bullish'] = df['close'] > df['final_lower']

        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = (df['volume'] / df['volume_ma'].replace(0, np.nan)).fillna(1.0)

        df['body'] = (df['close'] - df['open']).abs()
        df['range'] = (df['high'] - df['low']).replace(0, np.nan)
        df['body_ratio'] = (df['body'] / df['range']).fillna(0)

        return df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)

    # =========================================================
    # SWING POINTS
    # =========================================================

    def _find_swing_points(self, df, window=3):
        highs = []
        lows = []

        if df is None or len(df) < (window * 2 + 3):
            return highs, lows

        for i in range(window, len(df) - window):
            curr_h = df['high'].iloc[i]
            if curr_h == df['high'].iloc[i - window:i + window + 1].max():
                highs.append((i, curr_h))

            curr_l = df['low'].iloc[i]
            if curr_l == df['low'].iloc[i - window:i + window + 1].min():
                lows.append((i, curr_l))

        return highs, lows

    # =========================================================
    # TRENDLINES DETECTION (مشابه لـ Trendlines with Breaks)
    # =========================================================

    def detect_trendlines(self, df, current_price, direction):
        if df is None or len(df) < 30:
            return {'passed': False, 'type': 'NO_TRENDLINE'}

        highs, lows = self._find_swing_points(df, window=3)

        if direction == 'LONG' and len(lows) >= 2:
            p1, p2 = lows[-2], lows[-1]
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            
            if x2 == x1:
                return {'passed': False, 'type': 'NO_TRENDLINE'}
            
            slope = (y2 - y1) / (x2 - x1)
            current_x = len(df) - 1
            expected_price = y2 + slope * (current_x - x2)
            atr = float(df.iloc[-1]['atr'])
            
            # السماح بالارتداد من خط الاتجاه أو قربه
            if abs(current_price - expected_price) <= (atr * 2.5) or current_price >= expected_price:
                return {'passed': True, 'type': 'TRENDLINE_BULLISH_BOUNCE'}

        elif direction == 'SHORT' and len(highs) >= 2:
            p1, p2 = highs[-2], highs[-1]
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            
            if x2 == x1:
                return {'passed': False, 'type': 'NO_TRENDLINE'}
            
            slope = (y2 - y1) / (x2 - x1)
            current_x = len(df) - 1
            expected_price = y2 + slope * (current_x - x2)
            atr = float(df.iloc[-1]['atr'])
            
            if abs(current_price - expected_price) <= (atr * 2.5) or current_price <= expected_price:
                return {'passed': True, 'type': 'TRENDLINE_BEARISH_REJECTION'}

        return {'passed': False, 'type': 'NO_TRENDLINE'}

    # =========================================================
    # MARKET STRUCTURE & ORDER BLOCKS
    # =========================================================

    def detect_market_structure(self, df):
        if df is None or len(df) < 30:
            return 'NEUTRAL'
        last = df.iloc[-1]
        if last['close'] > last['ema20'] and last['supertrend_bullish']:
            return 'LONG'
        elif last['close'] < last['ema20'] and not last['supertrend_bullish']:
            return 'SHORT'
        return 'NEUTRAL'

    def detect_valid_order_block(self, df, current_price, direction):
        if df is None or len(df) < 20:
            return None
        
        # اختيار Order Block بسيط وفعال
        candle = df.iloc[-3]
        impulse = df.iloc[-2]
        
        if direction == 'LONG' and candle['close'] < candle['open'] and impulse['close'] > candle['high']:
            return {'type': 'BULLISH_OB', 'active': True}
        elif direction == 'SHORT' and candle['close'] > candle['open'] and impulse['close'] < candle['low']:
            return {'type': 'BEARISH_OB', 'active': True}
            
        return None

    # =========================================================
    # الدالة الرئيسية لتوليد الصفقات (تأكد من استدعائها في البوت لديك)
    # =========================================================

    def analyze_symbol(self, symbol):
        try:
            df = self._fetch_ohlcv(symbol, self.timeframe, 150, 'swap')
            if df is None or len(df) < 40:
                return None

            df = self._prepare(df)
            current_price = float(df.iloc[-1]['close'])
            
            # تحديد الاتجاه بناءً على الهيكل ومؤشر الـ Supertrend
            direction = self.detect_market_structure(df)
            if direction not in ['LONG', 'SHORT']:
                return None

            # فحص خطوط الاتجاه (Trendlines) والـ Order Block
            trendline_check = self.detect_trendlines(df, current_price, direction)
            ob_check = self.detect_valid_order_block(df, current_price, direction)

            # إذا توفرت أدوات الدعم (خط اتجاه أو أوردر بلوك مع اتجاه السوبرتريند)
            if trendline_check['passed'] or ob_check:
                atr = float(df.iloc[-1]['atr'])

                if direction == 'LONG':
                    stop_loss = current_price - (atr * 2.0)
                    tp1 = current_price + (atr * 2.0)
                    tp2 = current_price + (atr * 4.0)
                else:
                    stop_loss = current_price + (atr * 2.0)
                    tp1 = current_price - (atr * 2.0)
                    tp2 = current_price - (atr * 4.0)

                return {
                    'symbol': symbol,
                    'direction': direction,
                    'entry': current_price,
                    'stop_loss': round(stop_loss, 4),
                    'tp1': round(tp1, 4),
                    'tp2': round(tp2, 4),
                    'strategy': 'Supertrend + Trendlines & OB'
                }

        except Exception as e:
            logger.error(f"Error in analyze_symbol for {symbol}: {e}")

        return None
