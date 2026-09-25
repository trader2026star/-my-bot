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

        rs = avg_gain / avg_loss.replace(0, np.nan)

        rsi = 100 - (100 / (1 + rs))

        return rsi.fillna(50)

    def _atr(self, df, period=14):
        high_low = df['high'] - df['low']

        high_close = (
            df['high'] - df['close'].shift()
        ).abs()

        low_close = (
            df['low'] - df['close'].shift()
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
            df['avg_volume'].replace(0, np.nan)
        )

        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['body_atr'] = (
            df['body'] /
            df['atr'].replace(0, np.nan)
        )

        df['range'] = (
            df['high'] -
            df['low']
        )

        df['bullish_candle'] = (
            df['close'] > df['open']
        )

        df['bearish_candle'] = (
            df['close'] < df['open']
        )

        return df.replace(
            [np.inf, -np.inf],
            np.nan
        ).dropna().reset_index(drop=True)

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 50:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = row['close']
        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

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
    # STRUCTURE
    # =========================================================

    def get_structure(self, df, direction):
        if df is None or len(df) < 35:
            return {
                'structure': 'NEUTRAL',
                'bos': False,
                'liquidity_sweep': False,
                'hh_hl': False,
                'lh_ll': False
            }

        x = df.iloc[:-2].copy()

        recent = x.tail(24)

        midpoint = len(recent) // 2

        first_half = recent.iloc[:midpoint]
        second_half = recent.iloc[midpoint:]

        prev_high = float(
            first_half['high'].max()
        )

        prev_low = float(
            first_half['low'].min()
        )

        recent_high = float(
            second_half['high'].max()
        )

        recent_low = float(
            second_half['low'].min()
        )

        last_close = float(
            x['close'].iloc[-1]
        )

        last_high = float(
            x['high'].iloc[-1]
        )

        last_low = float(
            x['low'].iloc[-1]
        )

        bos_long = (
            last_close > prev_high or
            last_close > recent_high
        )

        bos_short = (
            last_close < prev_low or
            last_close < recent_low
        )

        sweep_long = (
            last_low < prev_low and
            last_close > prev_low
        )

        sweep_short = (
            last_high > prev_high and
            last_close < prev_high
        )

        hh_hl = (
            recent_high > prev_high and
            recent_low > prev_low
        )

        lh_ll = (
            recent_high < prev_high and
            recent_low < prev_low
        )

        if direction == 'LONG':

            if bos_long or hh_hl:
                structure = 'BULLISH'
            else:
                structure = 'NEUTRAL'

            bos = bool(bos_long)
            sweep = bool(sweep_long)

        else:

            if bos_short or lh_ll:
                structure = 'BEARISH'
            else:
                structure = 'NEUTRAL'

            bos = bool(bos_short)
            sweep = bool(sweep_short)

        return {
            'structure': structure,
            'bos': bos,
            'liquidity_sweep': sweep,
            'hh_hl': bool(hh_hl),
            'lh_ll': bool(lh_ll)
        }

    # =========================================================
    # MOMENTUM
    # =========================================================

    def get_momentum(self, df, direction):
        row = df.iloc[-2]

        rsi = float(row['rsi'])
        body_atr = float(row['body_atr'])

        if direction == 'LONG':
            return (
                50 <= rsi <= 70 and
                row['bullish_candle'] and
                body_atr >= 0.25
            )

        return (
            30 <= rsi <= 50 and
            row['bearish_candle'] and
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

        body_atr = float(row['body_atr'])

        if direction == 'LONG':
            return (
                row['bullish_candle'] and
                body_atr >= 0.55
            )

        return (
            row['bearish_candle'] and
            body_atr >= 0.55
        )

    # =========================================================
    # FVG
    # =========================================================

    def detect_fvg(self, df, direction):
        if len(df) < 10:
            return False

        atr = float(
            df.iloc[-2]['atr']
        )

        current = float(
            df.iloc[-2]['close']
        )

        start = max(
            2,
            len(df) - 18
        )

        for i in range(
            start,
            len(df) - 2
        ):

            a = df.iloc[i - 1]
            c = df.iloc[i + 1]

            if direction == 'LONG':

                gap_low = float(
                    a['high']
                )

                gap_high = float(
                    c['low']
                )

                if gap_high > gap_low:

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

                    if distance <= atr * 1.75:
                        return True

            else:

                gap_high = float(
                    a['low']
                )

                gap_low = float(
                    c['high']
                )

                if gap_high > gap_low:

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

                    if distance <= atr * 1.75:
                        return True

        return False

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if len(df) < 20:
            return False

        atr = float(
            df.iloc[-2]['atr']
        )

        current = float(
            df.iloc[-2]['close']
        )

        start = max(
            3,
            len(df) - 18
        )

        for i in range(
            start,
            len(df) - 2
        ):

            candle = df.iloc[i]
            next_candle = df.iloc[i + 1]

            distance = abs(
                current -
                float(candle['close'])
            )

            if distance > atr * 2.0:
                continue

            if direction == 'LONG':

                if (
                    candle['bearish_candle'] and
                    next_candle['bullish_candle'] and
                    float(
                        next_candle['body_atr']
                    ) >= 0.45 and
                    float(
                        next_candle['close']
                    ) >
                    float(candle['high'])
                ):
                    return True

            else:

                if (
                    candle['bullish_candle'] and
                    next_candle['bearish_candle'] and
                    float(
                        next_candle['body_atr']
                    ) >= 0.45 and
                    float(
                        next_candle['close']
                    ) <
                    float(candle['low'])
                ):
                    return True

        return False

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def get_btc_context(self):
        try:

            btc_symbol = 'BTC/USDT:USDT'

            df = self._fetch_ohlcv(
                btc_symbol,
                '1h',
                150
            )

            if df is None:
                return 'NEUTRAL'

            df = self._prepare(df)

            return self.get_trend(df)

        except Exception as e:

            logger.warning(
                "BTC context error: %s",
                e
            )

            return 'NEUTRAL'

    # =========================================================
    # LEVELS
    # =========================================================

    def build_levels(self, df, direction):

        if df is None or len(df) < 30:
            return None

        x = df.iloc[:-2]

        row = df.iloc[-2]

        entry = float(
            row['close']
        )

        atr = float(
            row['atr']
        )

        recent = x.tail(20)

        swing_low = float(
            recent['low'].min()
        )

        swing_high = float(
            recent['high'].max()
        )

        if direction == 'LONG':

            structural_sl = (
                swing_low -
                atr * 0.30
            )

            atr_sl = (
                entry -
                atr * 1.35
            )

            sl = min(
                structural_sl,
                atr_sl
            )

            risk = entry - sl

            if risk <= 0:
                return None

            minimum_risk = (
                entry * 0.008
            )

            if risk < minimum_risk:

                sl = (
                    entry -
                    minimum_risk
                )

                risk = minimum_risk

            risk_pct = (
                risk /
                entry
            ) * 100

            if risk_pct > 7.0:
                return None

            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5.0

        else:

            structural_sl = (
                swing_high +
                atr * 0.30
            )

            atr_sl = (
                entry +
                atr * 1.35
            )

            sl = max(
                structural_sl,
                atr_sl
            )

            risk = sl - entry

            if risk <= 0:
                return None

            minimum_risk = (
                entry * 0.008
            )

            if risk < minimum_risk:

                sl = (
                    entry +
                    minimum_risk
                )

                risk = minimum_risk

            risk_pct = (
                risk /
                entry
            ) * 100

            if risk_pct > 7.0:
                return None

            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5.0

        return {
            'entry': entry,
            'sl': sl,
            'tp1': tp1
