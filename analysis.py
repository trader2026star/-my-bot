import logging
import ccxt
import pandas as pd
import numpy as np
import time

logger = logging.getLogger(__name__)


class ExpertAnalystBot:
    """
    Expert SMC / ICT Multi-Timeframe Analysis Engine

    الاتصال مع BingX محفوظ.
    التغيير الأساسي هنا في منطق التحليل فقط.

    Timeframes:
        1D  = Macro direction
        4H  = Main market structure
        1H  = Structure / liquidity
        30M = Setup zone
        15M = Execution

    Final signal requires:
        - Valid market structure
        - Liquidity / OB / FVG evidence
        - Execution confirmation
        - Volume / momentum confirmation
        - BTC context
        - Risk validation
    """

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

        # Cache to reduce unnecessary API requests
        self.cache = {}
        self.cache_ttl = 25

    # =========================================================
    # DATA
    # =========================================================

    def fetch_ohlcv_data(self, symbol, timeframe, limit=200):
        cache_key = f"{symbol}_{timeframe}_{limit}"
        now = time.time()

        cached = self.cache.get(cache_key)

        if cached:
            timestamp, data = cached

            if now - timestamp < self.cache_ttl:
                return data.copy()

        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not ohlcv or len(ohlcv) < 50:
                return None

            df = pd.DataFrame(
                ohlcv,
                columns=[
                    'timestamp',
                    'open',
                    'high',
                    'low',
                    'close',
                    'volume'
                ]
            )

            df['timestamp'] = pd.to_datetime(
                df['timestamp'],
                unit='ms'
            )

            numeric_cols = [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]

            for col in numeric_cols:
                df[col] = pd.to_numeric(
                    df[col],
                    errors='coerce'
                )

            df = df.dropna().reset_index(drop=True)

            self.cache[cache_key] = (now, df.copy())

            return df

        except Exception as e:
            logger.warning(
                f"OHLCV error {symbol} {timeframe}: {e}"
            )
            return None

    # =========================================================
    # INDICATORS
    # =========================================================

    def add_indicators(self, df):

        df = df.copy()

        # EMAs
        df['ema20'] = df['close'].ewm(
            span=20,
            adjust=False
        ).mean()

        df['ema50'] = df['close'].ewm(
            span=50,
            adjust=False
        ).mean()

        df['ema200'] = df['close'].ewm(
            span=200,
            adjust=False
        ).mean()

        # ATR
        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - prev_close)
        tr3 = abs(df['low'] - prev_close)

        df['tr'] = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = df['tr'].rolling(14).mean()

        # Candle statistics
        df['body'] = abs(
            df['close'] - df['open']
        )

        df['range'] = (
            df['high'] - df['low']
        ).replace(0, np.nan)

        df['body_ratio'] = (
            df['body'] / df['range']
        ).fillna(0)

        df['upper_wick'] = (
            df['high'] -
            df[['open', 'close']].max(axis=1)
        )

        df['lower_wick'] = (
            df[['open', 'close']].min(axis=1) -
            df['low']
        )

        # Volume
        df['vol_ma20'] = df['volume'].rolling(20).mean()

        df['volume_ratio'] = (
            df['volume'] /
            df['vol_ma20'].replace(0, np.nan)
        ).fillna(1)

        # Momentum
        delta = df['close'].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = (
            avg_gain /
            avg_loss.replace(0, np.nan)
        )

        df['rsi'] = (
            100 -
            (100 / (1 + rs))
        )

        # MACD
        ema12 = df['close'].ewm(
            span=12,
            adjust=False
        ).mean()

        ema26 = df['close'].ewm(
            span=26,
            adjust=False
        ).mean()

        df['macd'] = ema12 - ema26

        df['macd_signal'] = df['macd'].ewm(
            span=9,
            adjust=False
        ).mean()

        df['macd_hist'] = (
            df['macd'] -
            df['macd_signal']
        )

        return df

    # =========================================================
    # SWING STRUCTURE
    # =========================================================

    def find_swings(self, df, lookback=3):

        highs = []
        lows = []

        for i in range(
            lookback,
            len(df) - lookback
        ):

            high = df['high'].iloc[i]
            low = df['low'].iloc[i]

            left_highs = df['high'].iloc[
                i - lookback:i
            ]

            right_highs = df['high'].iloc[
                i + 1:i + 1 + lookback
            ]

            left_lows = df['low'].iloc[
                i - lookback:i
            ]

            right_lows = df['low'].iloc[
                i + 1:i + 1 + lookback
            ]

            if (
                high > left_highs.max()
                and high > right_highs.max()
            ):
                highs.append(
                    (i, float(high))
                )

            if (
                low < left_lows.min()
                and low < right_lows.min()
            ):
                lows.append(
                    (i, float(low))
                )

        return highs, lows

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def analyze_structure(self, df):

        highs, lows = self.find_swings(df)

        result = {
            'bias': 'NEUTRAL',
            'bos_long': False,
            'bos_short': False,
            'mss_long': False,
            'mss_short': False,
            'swing_high': None,
            'swing_low': None
        }

        if len(highs) < 2 or len(lows) < 2:
            return result

        last_high = highs[-1][1]
        previous_high = highs[-2][1]

        last_low = lows[-1][1]
        previous_low = lows[-2][1]

        close = df['close'].iloc[-1]

        result['swing_high'] = last_high
        result['swing_low'] = last_low

        # Bullish structure
        higher_high = last_high > previous_high
        higher_low = last_low > previous_low

        # Bearish structure
        lower_high = last_high < previous_high
        lower_low = last_low < previous_low

        if higher_high and higher_low:
            result['bias'] = 'BULLISH'

        elif lower_high and lower_low:
            result['bias'] = 'BEARISH'

        # BOS
        if close > last_high:
            result['bos_long'] = True

        if close < last_low:
            result['bos_short'] = True

        # MSS approximation:
        # recent close breaks the latest opposing structure
        recent_close = df['close'].iloc[-2]

        if (
            recent_close <= last_high
            and close > last_high
        ):
            result['mss_long'] = True

        if (
            recent_close >= last_low
            and close < last_low
        ):
            result['mss_short'] = True

        return result

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def detect_liquidity_sweep(self, df):

        result = {
            'long': False,
            'short': False,
            'level': None
        }

        if len(df) < 15:
            return result

        recent = df.iloc[-12:-2]

        previous_high = recent['high'].max()
        previous_low = recent['low'].min()

        candle = df.iloc[-1]

        # Sell-side liquidity sweep:
        # price takes low then closes back above it
        if (
            candle['low'] < previous_low
            and candle['close'] > previous_low
        ):
            result['long'] = True
            result['level'] = previous_low

        # Buy-side liquidity sweep:
        # price takes high then closes back below it
        if (
            candle['high'] > previous_high
            and candle['close'] < previous_high
        ):
            result['short'] = True
            result['level'] = previous_high

        return result

    # =========================================================
    # FAIR VALUE GAP
    # =========================================================

    def detect_fvg(self, df):

        result = {
            'bullish': False,
            'bearish': False,
            'bull_zone': None,
            'bear_zone': None
        }

        if len(df) < 5:
            return result

        # Search recent candles
        start = max(2, len(df) - 12)

        for i in range(
            start,
            len(df)
        ):

            c1_high = df['high'].iloc[i - 2]
            c1_low = df['low'].iloc[i - 2]

            c3_high = df['high'].iloc[i]
            c3_low = df['low'].iloc[i]

            # Bullish FVG
            if c3_low > c1_high:

                result['bullish'] = True
                result['bull_zone'] = (
                    float(c1_high),
                    float(c3_low)
                )

            # Bearish FVG
            if c3_high < c1_low:

                result['bearish'] = True
                result['bear_zone'] = (
                    float(c3_high),
                    float(c1_low)
                )

        return result

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df):

        result = {
            'bullish': False,
            'bearish': False,
            'bull_zone': None,
            'bear_zone': None
        }

        if len(df) < 10:
            return result

        atr = df['atr'].iloc[-1]

        if pd.isna(atr) or atr <= 0:
            return result

        # Search recent displacement
        for i in range(
            len(df) - 6,
            len(df)
        ):

            candle = df.iloc[i]

            body = abs(
                candle['close'] -
                candle['open']
            )

            # Strong bullish displacement
            if (
                candle['close'] > candle['open']
                and body > atr * 1.2
            ):

                # Previous bearish candle = potential bullish OB
                prev = df.iloc[i - 1]

                if prev['close'] < prev['open']:

                    result['bullish'] = True
                    result['bull_zone'] = (
                        float(prev['low']),
                        float(prev['high'])
                    )

            # Strong bearish displacement
            if (
                candle['close'] < candle['open']
                and body > atr * 1.2
            ):

                prev = df.iloc[i - 1]

                if prev['close'] > prev['open']:

                    result['bearish'] = True
                    result['bear_zone'] = (
                        float(prev['low']),
                        float(prev['high'])
                    )

        return result

    # =========================================================
    # ZONE PROXIMITY
    # =========================================================

    def price_in_or_near_zone(
        self,
        price,
        zone,
        atr,
        tolerance=0.75
    ):

        if not zone:
            return False

        low, high = zone

        tolerance_value = atr * tolerance

        return (
            low - tolerance_value
            <= price
            <=
            high + tolerance_value
        )

    # =========================================================
    # MOMENTUM
    # =========================================================

    def momentum_confirmation(
        self,
        df,
        direction
    ):

        if len(df) < 30:
            return False

        row = df.iloc[-1]

        rsi = row['rsi']
        macd_hist = row['macd_hist']

        if pd.isna(rsi):
            return False

        if direction == 'LONG':

            return (
                50 <= rsi <= 72
                and macd_hist > 0
            )

        if direction == 'SHORT':

            return (
                28 <= rsi <= 50
                and macd_hist < 0
            )

        return False

    # =========================================================
    # VOLUME
    # =========================================================

    def volume_confirmation(
        self,
        df,
        direction
    ):

        row = df.iloc[-1]

        volume_ratio = row['volume_ratio']
        body_ratio = row['body_ratio']

        if direction == 'LONG':

            return (
                volume_ratio >= 1.15
                and row['close'] > row['open']
                and body_ratio >= 0.50
            )

        if direction == 'SHORT':

            return (
                volume_ratio >= 1.15
                and row['close'] < row['open']
                and body_ratio >= 0.50
            )

        return False

    # =========================================================
    # HIGHER TIMEFRAME BIAS
    # =========================================================

    def timeframe_bias(self, df):

        df = self.add_indicators(df)

        if len(df) < 50:
            return 'NEUTRAL'

        row = df.iloc[-1]

        close = row['close']

        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

        if (
            close > ema20
            and ema20 > ema50
            and ema50 > ema200
        ):
            return 'BULLISH'

        if (
            close < ema20
            and ema20 < ema50
            and ema50 < ema200
        ):
            return 'BEARISH'

        # Secondary trend condition
        if close > ema50 and ema20 > ema50:
            return 'BULLISH'

        if close < ema50 and ema20 < ema50:
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def get_btc_context(self):

        try:

            df = self.fetch_ohlcv_data(
                'BTC/USDT:USDT',
                '1h',
                100
            )

            if df is None:
                return 'NEUTRAL'

            bias = self.timeframe_bias(df)

            return bias

        except Exception as e:

            logger.warning(
                f"BTC context error: {e}"
            )

            return 'NEUTRAL'

    # =========================================================
    # EXTENSION / CHASE FILTER
    # =========================================================

    def chase_filter(
        self,
        df,
        direction
    ):

        row = df.iloc[-1]

        atr = row['atr']

        if pd.isna(atr) or atr <= 0:
            return False

        distance_from_ema = abs(
            row['close'] -
            row['ema20']
        )

        # Avoid buying/selling an excessively extended move
        if distance_from_ema > atr * 3.0:
            return False

        # RSI extreme protection
        if direction == 'LONG' and row['rsi'] > 78:
            return False

        if direction == 'SHORT' and row['rsi'] < 22:
            return False

        return True

    # =========================================================
    # SCORE
    # =========================================================

    def calculate_score(
        self,
        direction,
        structure,
        sweep,
        fvg,
        ob,
        volume_ok,
        momentum_ok,
        btc_bias,
        biases,
        execution_df
    ):

        score = 0
        confirmations = []

        # -----------------------------------------
        # Structure
        # -----------------------------------------

        structure_bias = structure['bias']

        if structure_bias == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):

            score += 20
            confirmations.append(
                'MARKET STRUCTURE'
            )

        if (
            structure['bos_long']
            if direction == 'LONG'
            else structure['bos_short']
        ):

            score += 10
            confirmations.append('BOS')

        if (
            structure['mss_long']
            if direction == 'LONG'
            else structure['mss_short']
        ):

            score += 12
            confirmations.append('MSS')

        # -----------------------------------------
        # Liquidity
        # -----------------------------------------

        if (
            sweep['long']
            if direction == 'LONG'
            else sweep['short']
        ):

            score += 12
            confirmations.append(
                'LIQUIDITY SWEEP'
            )

        # -----------------------------------------
        # Order Block
        # -----------------------------------------

        if (
            ob['bullish']
            if direction == 'LONG'
            else ob['bearish']
        ):

            score += 10
            confirmations.append(
                'ORDER BLOCK'
            )

        # -----------------------------------------
        # FVG
        # -----------------------------------------

        if (
            fvg['bullish']
            if direction == 'LONG'
            else fvg['bearish']
        ):

            score += 8
            confirmations.append('FVG')

        # -----------------------------------------
        # Volume
        # -----------------------------------------

        if volume_ok:

            score += 10
            confirmations.append(
                'VOLUME'
            )

        # -----------------------------------------
        # Momentum
        # -----------------------------------------

        if momentum_ok:

            score += 8
            confirmations.append(
                'MOMENTUM'
            )

        # -----------------------------------------
        # Higher TF alignment
        # -----------------------------------------

        target_bias = (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        )

        aligned = sum(
            1
            for bias in biases
            if bias == target_bias
        )

        if aligned >= 3:

            score += 10
            confirmations.append(
                'MTF ALIGNMENT'
            )

        elif aligned >= 2:

            score += 5

        # -----------------------------------------
        # BTC
        # -----------------------------------------

        if btc_bias == target_bias:

            score += 10
            confirmations.append(
                'BTC CONFIRMATION'
            )

        elif btc_bias != 'NEUTRAL':

            score -= 12

        return score, confirmations

    # =========================================================
    # RISK ENGINE
    # =========================================================

    def calculate_trade_levels(
        self,
        df,
        direction,
        entry
    ):

        atr = df['atr'].iloc[-1]

        if pd.isna(atr) or atr <= 0:
            return None

        structure = self.analyze_structure(df)

        swing_low = structure.get(
            'swing_low'
        )

        swing_high = structure.get(
            'swing_high'
        )

        # -----------------------------------------
        # LONG
        # -----------------------------------------

        if direction == 'LONG':

            candidates = [
                x for x in [
                    swing_low,
                    df['low'].iloc[-2],
                    df['low'].iloc[-3],
                    entry - atr * 1.3
                ]
                if x is not None
            ]

            if not candidates:
                return None

            structural_low = min(
                candidates
            )

            stop = structural_low - (
                atr * 0.15
            )

            risk = entry - stop

            if risk <= 0:
                return None

            risk_pct = (
                risk / entry
            ) * 100

            # Avoid extremely tight stops
            if risk_pct < 0.35:

                stop = entry - (
                    atr * 0.8
                )

                risk = entry - stop
                risk_pct = (
                    risk / entry
                ) * 100

            # Maximum stop distance
            if risk_pct > 7.0:
                return None

            tp1 = entry + (
                risk * 1.5
            )

            tp2 = entry + (
                risk * 2.5
            )

            tp3 = entry + (
                risk * 4.0
            )

        # -----------------------------------------
        # SHORT
        # -----------------------------------------

        else:

            candidates = [
                x for x in [
                    swing_high,
                    df['high'].iloc[-2],
                    df['high'].iloc[-3],
                    entry + atr * 1.3
                ]
                if x is not None
            ]

            if not candidates:
                return None

            structural_high = max(
                candidates
            )

            stop = structural_high + (
                atr * 0.15
            )

            risk = stop - entry

            if risk <= 0:
                return None

            risk_pct = (
                risk / entry
            ) * 100

            if risk_pct < 0.35:

                stop = entry + (
                    atr * 0.8
                )

                risk = stop - entry

                risk_pct = (
                    risk / entry
                ) * 100

            if risk_pct > 7.0:
                return None

            tp1 = entry - (
                risk * 1.5
            )

            tp2 = entry - (
                risk * 2.5
            )

            tp3 = entry - (
                risk * 4.0
            )

        return {
            'entry': entry,
            'stop': stop,
            'risk': risk,
            'risk_pct': risk_pct,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3
        }

    # =========================================================
    # PRECISION
    # =========================================================

    def precision_price(
        self,
        symbol,
        price
    ):

        try:

            return float(
                self.exchange.price_to_precision(
                    symbol,
                    price
                )
            )

        except Exception:

            if price < 1:
                return round(price, 8)

            return round(price, 4)

    # =========================================================
    # FINAL ANALYSIS
    # =========================================================

    def evaluate_smc_strategy(
        self,
        symbol
    ):

        try:

            # =====================================
            # FETCH MULTI-TIMEFRAME DATA
            # =====================================

            df_1d = self.fetch_ohlcv_data(
                symbol,
                '1d',
                120
            )

            df_4h = self.fetch_ohlcv_data(
                symbol,
                '4h',
                160
            )

            df_1h = self.fetch_ohlcv_data(
                symbol,
                '1h',
                160
            )

            df_30m = self.fetch_ohlcv_data(
                symbol,
                '30m',
                160
            )

            df_15m = self.fetch_ohlcv_data(
                symbol,
                '15m',
                160
            )

            datasets = [
                df_1d,
                df_4h,
                df_1h,
                df_30m,
                df_15m
            ]

            if any(
                x is None or len(x) < 60
                for x in datasets
            ):
                return None

            # =====================================
            # INDICATORS
            # =====================================

            df_1d = self.add_indicators(df_1d)
            df_4h = self.add_indicators(df_4h)
            df_1h = self.add_indicators(df_1h)
            df_30m = self.add_indicators(df_30m)
            df_15m = self.add_indicators(df_15m)

            # =====================================
            # TIMEFRAME BIASES
            # =====================================

            bias_1d = self.timeframe_bias(
                df_1d
            )

            bias_4h = self.timeframe_bias(
                df_4h
            )

            bias_1h = self.timeframe_bias(
                df_1h
            )

            bias_30m = self.timeframe_bias(
                df_30m
            )

            # =====================================
            # BTC
            # =====================================

            btc_bias = self.get_btc_context()

            # =====================================
            # 1H STRUCTURE
            # =====================================

            structure_1h = self.analyze_structure(
                df_1h
            )

            # =====================================
            # 30M STRUCTURE
            # =====================================

            structure_30m = self.analyze_structure(
                df_30m
            )

            # =====================================
            # 15M EXECUTION STRUCTURE
            # =====================================

            structure_15m = self.analyze_structure(
                df_15m
            )

            sweep = self.detect_liquidity_sweep(
                df_15m
            )

            fvg = self.detect_fvg(
                df_30m
            )

            ob = self.detect_order_block(
                df_30m
            )

            current_price = float(
                df_15m['close'].iloc[-1]
            )

            # =====================================
            # DETERMINE LONG / SHORT
            # =====================================

            long_score = 0
            short_score = 0

            long_confirmations = []
            short_confirmations = []

            # -------------------------------------
            # LONG
            # -------------------------------------

            long_volume = self.volume_confirmation(
                df_15m,
                'LONG'
            )

            long_momentum = self.momentum_confirmation(
                df_15m,
                'LONG'
            )

            if (
                self.chase_filter(
                    df_15m,
                    'LONG'
                )
            ):

                long_score, long_confirmations = (
                    self.calculate_score(
                        'LONG',
                        structure_15m,
                        sweep,
                        fvg,
                        ob,
                        long_volume,
                        long_momentum,
                        btc_bias,
                        [
                            bias_1d,
                            bias_4h,
                            bias_1h,
                            bias_30m
                        ],
                        df_15m
                    )
                )

            # -------------------------------------
            # SHORT
            # -------------------------------------

            short_volume = self.volume_confirmation(
                df_15m,
                'SHORT'
            )

            short_momentum = self.momentum_confirmation(
                df_15m,
                'SHORT'
            )

            if (
                self.chase_filter(
                    df_15m,
                    'SHORT'
                )
            ):

                short_score, short_confirmations = (
                    self.calculate_score(
                        'SHORT',
                        structure_15m,
                        sweep,
                        fvg,
                        ob,
                        short_volume,
                        short_momentum,
                        btc_bias,
                        [
                            bias_1d,
                            bias_4h,
                            bias_1h,
                            bias_30m
                        ],
                        df_15m
                    )
                )

            # =====================================
            # CHOOSE DIRECTION
            # =====================================

            if (
                long_score < 70
                and short_score < 70
            ):
                return None

            if long_score > short_score:

                direction = 'LONG'
                score = long_score
                confirmations = (
                    long_confirmations
                )

            else:

                direction = 'SHORT'
                score = short_score
                confirmations = (
                    short_confirmations
                )

            # =====================================
            # HARD CONFLICT FILTER
            # =====================================

            target_bias = (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            )

            higher_tf = [
                bias_1d,
                bias_4h,
                bias_1h
            ]

            aligned_count = sum(
                1
                for x in higher_tf
                if x == target_bias
            )

            opposite_count = sum(
                1
                for x in higher_tf
                if x not in (
                    target_bias,
                    'NEUTRAL'
                )
            )

            # Strong direct conflict
            if opposite_count >= 2:
                return None

            # Need real MTF support
            if aligned_count < 2:
                return None

            # =====================================
            # REAL CONFIRMATIONS
            # =====================================

            real_confirmation_set = set(
                confirmations
            )

            real_groups = 0

            if (
                'MARKET STRUCTURE'
                in real_confirmation_set
                or 'BOS'
                in real_confirmation_set
                or 'MSS'
                in real_confirmation_set
            ):
                real_groups += 1

            if (
                'LIQUIDITY SWEEP'
                in real_confirmation_set
                or 'ORDER BLOCK'
                in real_confirmation_set
                or 'FVG'
                in real_confirmation_set
            ):
                real_groups += 1

            if (
                'VOLUME'
                in real_confirmation_set
            ):
                real_groups += 1

            if (
                'MOMENTUM'
                in real_confirmation_set
            ):
                real_groups += 1

            if (
                'BTC CONFIRMATION'
                in real_confirmation_set
            ):
                real_groups += 1

            if (
                'MTF ALIGNMENT'
                in real_confirmation_set
            ):
                real_groups += 1

            # Minimum three independent confirmation groups
            if real_groups < 3:
                return None

            # =====================================
            # OB / FVG LOCATION VALIDATION
            # =====================================

            atr = df_15m['atr'].iloc[-1]

            zone_ok = False

            if direction == 'LONG':

                if self.price_in_or_near_zone(
                    current_price,
                    ob.get('bull_zone'),
                    atr
                ):
                    zone_ok = True

                if self.price_in_or_near_zone(
                    current_price,
                    fvg.get('bull_zone'),
                    atr
                ):
                    zone_ok = True

            else:

                if self.price_in_or_near_zone(
                    current_price,
                    ob.get('bear_zone'),
                    atr
                ):
                    zone_ok = True

                if self.price_in_or_near_zone(
                    current_price,
                    fvg.get('bear_zone'),
                    atr
                ):
                    zone_ok = True

            # =====================================
            # FINAL QUALITY GATE
            # =====================================

            # High quality requires structure + location
            if score >= 86:

                if not zone_ok:
                    return None

                if (
                    'MARKET STRUCTURE'
                    not in real_confirmation_set
                    and 'BOS'
                    not in real_confirmation_set
                    and 'MSS'
                    not in real_confirmation_set
                ):
                    return None

            # =====================================
            # RISK
            # =====================================

            trade = self.calculate_trade_levels(
                df_15m,
                direction,
                current_price
            )

            if trade is None:
                return None

            entry = self.precision_price(
                symbol,
                trade['entry']
            )

            stop = self.precision_price(
                symbol,
                trade['stop']
            )

            tp1 = self.precision_price(
                symbol,
                trade['tp1']
            )

            tp2 = self.precision_price(
                symbol,
                trade['tp2']
            )

            tp3 = self.precision_price(
                symbol,
                trade['tp3']
            )

            risk_pct = trade['risk_pct']

            # =====================================
            # R:R INTEGRITY
            # =====================================

            if direction == 'LONG':

                rr1 = (
                    (tp1 - entry) /
                    (entry - stop)
                )

                rr2 = (
                    (tp2 - entry) /
                    (entry - stop)
                )

                rr3 = (
                    (tp3 - entry) /
                    (entry - stop)
                )

            else:

                rr1 = (
                    (entry - tp1) /
                    (stop - entry)
                )

                rr2 = (
                    (entry - tp2) /
                    (stop - entry)
                )

                rr3 = (
                    (entry - tp3) /
                    (stop - entry)
                )

            if rr1 < 1.3:
                return None

            # =====================================
            # QUALITY
            # =====================================

            if score >= 90:
                quality = 'INSTITUTIONAL'
            elif score >= 86:
                quality = 'HIGH PROBABILITY'
            elif score >= 78:
                quality = 'STRONG'
            elif score >= 70:
                quality = 'VALID SETUP'
            else:
                quality = 'WEAK'

            # =====================================
            # DISPLAY PERCENTAGES
            # =====================================

            if direction == 'LONG':

                tp1_pct = (
                    (tp1 - entry) /
                    entry
                ) * 100

                tp2_pct = (
                    (tp2 - entry) /
                    entry
                ) * 100

                tp3_pct = (
                    (tp3 - entry) /
                    entry
                ) * 100

            else:

                tp1_pct = (
                    (entry - tp1) /
                    entry
                ) * 100

                tp2_pct = (
                    (entry - tp2) /
                    entry
                ) * 100

                tp3_pct = (
                    (entry - tp3) /
                    entry
                ) * 100

            clean_symbol = symbol.split('/')[0]

            # =====================================
            # REPORT
            # =====================================

            report = f"""
🏛️ **EXPERT SMC & ICT INSTITUTIONAL REPORT**

━━━━━━━━━━━━━━━━━━

💠 **Symbol:** `{clean_symbol}`
📌 **Decision:** `{direction}`
🔥 **Score:** `{score}/100`
🏆 **Quality:** `{quality}`

━━━━━━━━━━━━━━━━━━

📍 **ENTRY:** `{entry}`

🛑 **SL:** `{stop}`
📉 **Risk Distance:** `{risk_pct:.2f}%`

━━━━━━━━━━━━━━━━━━

🎯 **TP1:** `{tp1}`  | R:R `{rr1:.2f}`
📈 `{tp1_pct:.2f}%`

🎯 **TP2:** `{tp2}`  | R:R `{rr2:.2f}`
📈 `{tp2_pct:.2f}%`

🎯 **TP3:** `{tp3}`  | R:R `{rr3:.2f}`
📈 `{tp3_pct:.2f}%`

━━━━━━━━━━━━━━━━━━

🧠 **SMART MONEY EVIDENCE**

• Structure: `{structure_15m['bias']}`
• 1D Bias: `{bias_1d}`
• 4H Bias: `{bias_4h}`
• 1H Bias: `{bias_1h}`
• 30M Bias: `{bias_30m}`
• BTC Context: `{btc_bias}`

━━━━━━━━━━━━━━━━━━

🔎 **CONFIRMATIONS**

{chr(10).join("✔ " + x for x in confirmations)}

📊 **Independent Confirmations:** `{real_groups}`

━━━━━━━━━━━━━━━━━━

🛡️ **RISK ENGINE**

✔ Structure-based SL
✔ ATR protection
✔ R:R integrity
✔ Anti-chase filter
✔ Multi-timeframe validation
✔ Conflicting-market filter
✔ Minimum confirmation gate

━━━━━━━━━━━━━━━━━━

⚡ **EXECUTION MODEL**

15M execution
30M setup
1H structure
4H trend
1D macro
BTC context

━━━━━━━━━━━━━━━━━━

⚠️ This is a rule-based market analysis signal.
"""

            return report.strip()

        except Exception as e:

            logger.exception(
                f"Analysis error for {symbol}: {e}"
            )

            return None

    # =========================================================
    # COMPATIBILITY ALIAS
    # =========================================================

    def evaluate_strategy(self, symbol):

        return self.evaluate_smc_strategy(
            symbol
        )
