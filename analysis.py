import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        self.exchange_id = exchange_id

        exchange_class = getattr(ccxt, exchange_id)

        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        })

    # =========================================================
    # DATA
    # =========================================================

    def fetch_ohlcv_data(self, symbol, timeframe, limit=150):
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not ohlcv or len(ohlcv) < 30:
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

            numeric_columns = [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]

            for col in numeric_columns:
                df[col] = pd.to_numeric(
                    df[col],
                    errors='coerce'
                )

            df = df.dropna().reset_index(drop=True)

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

        # EMA
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

        # Volume
        df['vol_ma20'] = df['volume'].rolling(
            20
        ).mean()

        df['vol_ratio'] = (
            df['volume'] /
            df['vol_ma20'].replace(0, np.nan)
        )

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

        # RSI
        delta = df['close'].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        # Candle body
        df['body'] = abs(
            df['close'] - df['open']
        )

        df['avg_body'] = df['body'].rolling(
            10
        ).mean()

        # Recent highs/lows
        df['recent_high'] = df['high'].rolling(
            10
        ).max().shift(1)

        df['recent_low'] = df['low'].rolling(
            10
        ).min().shift(1)

        return df

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):

        if df is None or len(df) < 50:
            return "NEUTRAL"

        row = df.iloc[-1]

        bullish = (
            row['close'] > row['ema20'] and
            row['ema20'] > row['ema50']
        )

        bearish = (
            row['close'] < row['ema20'] and
            row['ema20'] < row['ema50']
        )

        if bullish:
            return "BULLISH"

        if bearish:
            return "BEARISH"

        return "NEUTRAL"

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def get_structure(self, df):

        if df is None or len(df) < 25:
            return {
                'bullish': False,
                'bearish': False,
                'bos_bull': False,
                'bos_bear': False,
                'liquidity_bull': False,
                'liquidity_bear': False
            }

        current = df.iloc[-1]

        previous_high = df['high'].iloc[-11:-
