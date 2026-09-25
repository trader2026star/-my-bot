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

    # =========================================================
    # DATA
    # =========================================================

    def _fetch_ohlcv(self, symbol, timeframe, limit=220):
        key = f"{symbol}:{timeframe}:{limit}"
        now = time.time()

        cached = self.cache.get(key)

        if cached:
            if now - cached['time'] < self.cache_seconds:
                return cached['data'].copy()

        try:
            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 60:
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

            df = df.dropna().reset_index(drop=True)

            self.cache[key] = {
                'time': now,
                'data': df
            }

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

    def _ema(self, series, period):
        return series.ewm(
            span=period,
            adjust=False
        ).mean()

    def _rsi(self, series, period=14):
        delta = series.diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

        rs = avg_gain / avg_loss.replace(
            0,
            np.nan
        )

        rsi = 100 - (
            100 / (1 + rs)
        )

        return rsi.fillna(50)

    def _atr(self, df, period=14):
        high_low = (
            df['high'] -
            df['low']
        )

        high_close = (
            df['high'] -
            df['close'].shift()
        ).abs()

        low_close = (
            df['low'] -
            df['close'].shift()
        ).abs()

        tr = pd.concat(
            [
                high_low,
                high_close,
                low_close
            ],
            axis=1
        ).max(axis=1)

        return tr.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

    def _prepare(self, df):
        df = df.copy()

        df['ema20'] = self._ema(
            df['close'],
            20
        )

        df['ema50'] = self._ema(
            df['close'],
            50
        )

        df['ema200'] = self._ema(
            df['close'],
            200
        )

        df['rsi'] = self._rsi(
            df['close'],
            14
        )

        df['atr'] = self._atr(
            df,
            14
        )

        df['avg_volume'] = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume'] /
            df['avg_volume'].replace(
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

        df['range'] = (
            df['high'] -
            df['low']
        )

        df['bullish_candle'] = (
            df['close'] >
            df['open']
        )

        df['bearish_candle'] = (
            df['close'] <
            df['open']
        )

        return (
            df
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .dropna()
            .reset_index(drop=True)
        )

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 50:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = float(row['close'])
        ema20 = float(row['ema20'])
        ema50 = float(row['ema50'])
        ema200 = float(row['ema200'])

        bullish_strong = (
            close > ema20 >
            ema50 > ema200
        )

        bearish_strong = (
            close < ema20 <
            ema50 < ema200
        )

        bullish_soft = (
            close > ema50 and
            ema20 > ema50
        )

        bearish_soft = (
            close < ema50 and
            ema20 < ema50
        )

        if bullish_strong or bullish_soft:
            return 'BULLISH'

        if bearish_strong or bearish_soft:
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def get_structure(self, df, direction):
        if df is None or len(df) < 40:
            return {
                'structure': 'NEUTRAL',
                'bos': False,
                'mss': False,
                'liquidity_sweep': False,
                'hh_hl': False,
                'lh_ll': False
            }

        # Ignore current unfinished candle and last closed candle
        x = df.iloc[:-2].copy()

        recent = x.tail(30)

        if len(recent) < 20:
            return {
                'structure': 'NEUTRAL',
                'bos': False,
                'mss': False,
                'liquidity_sweep': False,
                'hh_hl': False,
                'lh_ll': False
            }

        midpoint = len(recent) // 2

        first = recent.iloc[:midpoint]
        second = recent.iloc[midpoint:]

        prev_high = float(
            first['high'].max()
        )

        prev_low = float(
            first['low'].min()
        )

        second_high = float(
            second['high'].max()
        )

        second_low = float(
            second['low'].min()
        )

        last = x.iloc[-1]

        last_close = float(
            last['close']
        )

        last_high = float(
            last['high']
        )

        last_low = float(
            last['low']
        )

        # -----------------------------------------------------
        # BOS
        # -----------------------------------------------------

        bos_long = (
            last_close > prev_high
        )

        bos_short = (
            last_close < prev_low
        )

        # -----------------------------------------------------
        # LIQUIDITY SWEEP
        # -----------------------------------------------------

        sweep_long = (
            last_low < prev_low and
            last_close > prev_low
        )

        sweep_short = (
            last_high > prev_high and
            last_close < prev_high
        )

        # -----------------------------------------------------
        # STRUCTURAL HIGHER/LOWER
        # -----------------------------------------------------

        hh_hl = (
            second_high > prev_high and
            second_low > prev_low
        )

        lh_ll = (
            second_high < prev_high and
            second_low < prev_low
        )

        # -----------------------------------------------------
        # MSS
        # -----------------------------------------------------

        mss_long = (
            sweep_long and
            last_close > (
                float(first['high'].iloc[-1])
            )
        )

        mss_short = (
            sweep_short and
            last_close < (
                float(first['low'].iloc[-1])
            )
        )

        if direction == 'LONG':

            structure = (
                'BULLISH'
                if (
                    bos_long or
                    mss_long or
                    hh_hl
                )
                else 'NEUTRAL'
            )

            return {
                'structure': structure,
                'bos': bool(bos_long),
                'mss': bool(mss_long),
                'liquidity_sweep': bool(
                    sweep_long
                ),
                'hh_hl': bool(hh_hl),
                'lh_ll': bool(lh_ll)
            }

        structure = (
            'BEARISH'
            if (
                bos_short or
                mss_short or
                lh_ll
            )
            else 'NEUTRAL'
        )

        return {
            'structure': structure,
            'bos': bool(bos_short),
            'mss': bool(mss_short),
            'liquidity_sweep': bool(
                sweep_short
            ),
            'hh_hl': bool(hh_hl),
            'lh_ll': bool(lh_ll)
        }

    # =========================================================
    # MOMENTUM
    # =========================================================

    def get_momentum(self, df, direction):
        row = df.iloc[-2]

        rsi = float(row['rsi'])
        body_atr = float(
            row['body_atr']
        )

        if direction == 'LONG':

            return (
                50 <= rsi <= 70 and
                bool(row['bullish_candle']) and
                body_atr >= 0.25
            )

        return (
            30 <= rsi <= 50 and
            bool(row['bearish_candle']) and
            body_atr >= 0.25
        )

    # =========================================================
    # VOLUME
    # =========================================================

    def get_volume_confirmation(self, df):
        ratio = float(
            df.iloc[-2]['volume_ratio']
        )

        return ratio >= 1.05

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def get_displacement(self, df, direction):
        row = df.iloc[-2]

        body_atr = float(
            row['body_atr']
        )

        if direction == 'LONG':

            return (
                bool(row['bullish_candle']) and
                body_atr >= 0.55
            )

        return (
            bool(row['bearish_candle']) and
            body_atr >= 0.55
        )

    # =========================================================
    # FVG
    # =========================================================

    def detect_fvg(self, df, direction):
        if len(df) < 12:
            return False

        current = float(
            df.iloc[-2]['close']
        )

        atr = float(
            df.iloc[-2]['atr']
        )

        start = max(
            2,
            len(df) - 20
        )

        for i in range(
            start,
            len(df) - 2
        ):

            a = df.iloc[i - 1]
            b = df.iloc[i]
            c = df.iloc[i + 1]

            # Ignore tiny/non-displacement gaps
            if float(b['body_atr']) < 0.35:
                continue

            if direction == 'LONG':

                gap_low = float(
                    a['high']
                )

                gap_high = float(
                    c['low']
                )

                if gap_high <= gap_low:
                    continue

                distance = min(
                    abs(
                        current -
                        gap_low
                    ),
                    abs(
                        current -
                        gap_high
                    )
                )

                if distance <= atr * 1.50:
                    return True

            else:

                gap_high = float(
                    a['low']
                )

                gap_low = float(
                    c['high']
                )

                if gap_high <= gap_low:
                    continue

                distance = min(
                    abs(
                        current -
                        gap_low
                    ),
                    abs(
                        current -
                        gap_high
                    )
                )

                if distance <= atr * 1.50:
                    return True

        return False

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if len(df
