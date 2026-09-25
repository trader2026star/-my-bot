import time
import logging
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

        self._cache = {}
        self.cache_seconds = 20

    # =========================================================
    # DATA
    # =========================================================

    def fetch_ohlcv(self, symbol, timeframe, limit=250):
        try:
            key = f"ohlcv:{symbol}:{timeframe}"
            now = time.time()

            cached = self._cache.get(key)

            if cached:
                ts, data = cached

                if now - ts < self.cache_seconds:
                    return data

            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 80:
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

            df = df.astype({
                'open': float,
                'high': float,
                'low': float,
                'close': float,
                'volume': float
            })

            self._cache[key] = (
                now,
                df
            )

            return df

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

        rs = (
            avg_gain /
            avg_loss.replace(0, np.nan)
        )

        df['rsi'] = (
            100 -
            (100 / (1 + rs))
        )

        prev_close = df['close'].shift(1)

        tr1 = (
            df['high'] -
            df['low']
        )

        tr2 = (
            df['high'] -
            prev_close
        ).abs()

        tr3 = (
            df['low'] -
            prev_close
        ).abs()

        tr = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = tr.rolling(14).mean()

        df['vol_ma'] = (
            df['volume'].rolling(20).mean()
        )

        df['volume_ratio'] = (
            df['volume'] /
            df['vol_ma'].replace(
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

        return df

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 30:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = float(row['close'])
        ema20 = float(row['ema20'])
        ema50 = float(row['ema50'])
        ema200 = float(row['ema200'])

        if (
            close > ema20 >
            ema50 > ema200
        ):
            return 'BULLISH'

        if (
            close < ema20 <
            ema50 < ema200
        ):
            return 'BEARISH'

        if (
            close > ema50 and
            ema20 > ema50
        ):
            return 'BULLISH'

        if (
            close < ema50 and
            ema20 < ema50
        ):
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def get_structure(self, df):
        if df is None or len(df) < 40:
           
