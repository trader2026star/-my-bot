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

        config = {
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        }

        if api_key:
            config['apiKey'] = api_key

        if secret_key:
            config['secret'] = secret_key

        self.exchange = exchange_class(config)

        self.cache = {}
        self.cache_ttl = 20

    # =========================================================
    # CACHE
    # =========================================================

    def _cache_get(self, key):
        item = self.cache.get(key)

        if item is None:
            return None

        timestamp, value = item

        if time.time() - timestamp <= self.cache_ttl:
            return value

        return None

    def _cache_set(self, key, value):
        self.cache[key] = (
            time.time(),
            value
        )

    # =========================================================
    # OHLCV
    # =========================================================

    def fetch_ohlcv(self, symbol, timeframe, limit=250):
        key = f"{symbol}:{timeframe}:{limit}"

        cached = self._cache_get(key)

        if cached is not None:
            return cached.copy()

        try:
            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data:
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

            numeric_columns = [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]

            for column in numeric_columns:
                df[column] = pd.to_numeric(
                    df[column],
                    errors='coerce'
                )

            df = df.dropna().reset_index(drop=True)

            if len(df) < 80:
                return None

            self._cache_set(key, df)

            return df.copy()

        except Exception as e:
            logger.warning(
                "OHLCV error %s %s: %s",
                symbol,
                timeframe,
                e
            )
            return None

    # =========================================================
    # INDICATORS
    # =========================================================

    def add_indicators(self, df):
        df = df.copy()

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

        delta = df['close'].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(
            0,
            np.nan
        )

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        previous_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (
            df['high'] -
            previous_close
        ).abs()

        tr3 = (
            df['low'] -
            previous_close
        ).abs()

        true_range = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = true_range.rolling(14).mean()

        df['volume_ma'] = df['volume'].rolling(20).mean()

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma'].replace(
                0,
                np.nan
            )
        )

        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['body_atr'] = (
            df['body'] /
            df['atr'].replace(
                0,
                np.nan
            )
        )

        df['bullish_candle'] = (
            df['close'] >
            df['open']
        )

        df['bearish_candle'] = (
            df['close'] <
            df['open']
        )

        return df

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 20:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = float(row['close'])
        ema20 = float(row['ema20'])
        ema50 = float(row['ema50'])
        ema200 = float(row['ema200'])

        bullish = (
            close > ema20 > ema50 > ema200
            or
            (
                close > ema50
                and
                ema20 > ema50
                and
                ema50 > ema200
            )
        )

        bearish = (
            close < ema20 < ema50 < ema200
            or
            (
                close < ema50
                and
                ema20 < ema50
                and
                ema50 < ema200
            )
        )

        if bullish:
            return 'BULLISH'

        if bearish:
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # STRUCTURE
    # =========================================================

    def get_structure(self, df, direction):
        result = {
            'structure': False,
            'bos': False,
            'liquidity_sweep': False,
            'hh_hl': False,
            'lh_ll': False
        }

        if df is None or len(df) < 35:
            return result

        x = df.iloc[:-1].tail(24).copy()

        if len(x) < 12:
            return result

        last_close = float(x.iloc[-1]['close'])
        last_high = float(x.iloc[-1]['high'])
        last_low = float(x.iloc[-1]['low'])

        previous_high = float(
            x['high'].iloc[:-3].max()
        )

        previous_low = float(
            x['low'].iloc[:-3].min()
        )

        earlier_high = float(
            x['high'].iloc[-10:-4].max()
        )

        earlier_low = float(
            x['low'].iloc[-10:-4].min()
        )

        half = len(x) // 2

        first_half = x.iloc[:half]
        second_half = x.iloc[half:]

        if direction == 'LONG':

            result['bos'] = (
                last_close > previous_high
                or
                last_close > earlier_high
            )

            result['liquidity_sweep'] = (
                last_low < previous_low
                and
                last_close > previous_low
            )

            higher_high = (
                second_half['high'].max()
                >
                first_half['high'].max()
            )

            higher_low = (
                second_half['low'].min()
                >
                first_half['low'].min()
            )

            result['hh_hl'] = (
                higher_high and
                higher_low
            )

            result['structure'] = (
                result['bos']
                or
                result['liquidity_sweep']
                or
                result['hh_hl']
            )

        else:

            result['bos'] = (
                last_close < previous_low
                or
                last_close < earlier_low
            )

            result['liquidity_sweep'] = (
                last_high > previous_high
                and
                last_close < previous_high
            )

            lower_high = (
                second_half['high'].max()
                <
                first_half['high'].max()
            )

            lower_low = (
                second_half['low'].min()
                <
                first_half['low'].min()
            )

            result['lh_ll'] = (
                lower_high and
                lower_low
            )

            result['structure'] = (
                result['bos']
                or
                result['liquidity_sweep']
                or
                result['lh_ll']
            )

        return result

    # =========================================================
    # MOMENTUM
    # =========================================================

    def get_momentum(self, df, direction):
        if df is None or len(df) < 5:
            return False

        row = df.iloc[-2]

        rsi = float(row['rsi'])
        body_atr = float(row['body_atr'])

        if direction == 'LONG':
            return (
                50 <= rsi <= 71
                and
                row['bullish_candle']
                and
                body_atr >= 0.30
            )

        return (
            29 <= rsi <= 50
            and
            row['bearish_candle']
            and
            body_atr >= 0.30
        )

    # =========================================================
    # VOLUME
    # =========================================================

    def get_volume_confirmation(self, df):
        if df is None or len(df) < 5:
            return False

        ratio = float(
            df.iloc[-2]['volume_ratio']
        )

        return ratio >= 1.10

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def get_displacement(self, df, direction):
        if df is None or len(df) < 5:
            return False

        row = df.iloc[-2]

        body_atr = float(row['body_atr'])

        if direction == 'LONG':
            return (
                row['bullish_candle']
                and
                body_atr >= 0.55
            )

        return (
            row['bearish_candle']
            and
            body_atr >= 0.55
        )

    # =========================================================
    # FVG
    # =========================================================

    def detect_fvg(self, df, direction):
        if df is None or len(df) < 25:
            return False

        current = df.iloc[-2]

        price = float(current['close'])
        atr = float(current['atr'])

        if atr <= 0:
            return False

        start = max(
            2,
            len(df) - 18
        )

        end = len(df) - 1

        for i in range(start, end):

            a = df.iloc[i - 1]
            c = df.iloc[i + 1]

            if direction == 'LONG':

               
