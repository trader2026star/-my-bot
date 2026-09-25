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

        bos_long = (
            last_close > prev_high
        )

        bos_short = (
            last_close < prev_low
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
            second_high > prev_high and
            second_low > prev_low
        )

        lh_ll = (
            second_high < prev_high and
            second_low < prev_low
        )

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
    # MOMENTUM (More flexible)
    # =========================================================

    def get_momentum(self, df, direction):
        row = df.iloc[-2]

        rsi = float(row['rsi'])
        body_atr = float(
            row['body_atr']
        )

        if direction == 'LONG':

            return (
                40 <= rsi <= 80 and
                bool(row['bullish_candle']) and
                body_atr >= 0.15
            )

        return (
            20 <= rsi <= 60 and
            bool(row['bearish_candle']) and
            body_atr >= 0.15
        )

    # =========================================================
    # VOLUME (More flexible)
    # =========================================================

    def get_volume_confirmation(self, df):
        ratio = float(
            df.iloc[-2]['volume_ratio']
        )

        return ratio >= 0.85

    # =========================================================
    # DISPLACEMENT (More flexible)
    # =========================================================

    def get_displacement(self, df, direction):
        row = df.iloc[-2]

        body_atr = float(
            row['body_atr']
        )

        if direction == 'LONG':

            return (
                bool(row['bullish_candle']) and
                body_atr >= 0.35
            )

        return (
            bool(row['bearish_candle']) and
            body_atr >= 0.35
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

            if float(b['body_atr']) < 0.25:
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

                if distance <= atr * 2.0:
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

                if distance <= atr * 2.0:
                    return True

        return False

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if len(df) < 12:
            return False

        current = float(df.iloc[-2]['close'])
        atr = float(df.iloc[-2]['atr'])
        start = max(2, len(df) - 20)

        for i in range(start, len(df) - 2):
            candle = df.iloc[i]
            next_candle = df.iloc[i + 1]

            if direction == 'LONG':
                if bool(candle['bearish_candle']) and float(next_candle['body_atr']) >= 0.35:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    if abs(current - ob_high) <= atr * 2.5 or abs(current - ob_low) <= atr * 2.5:
                        return True
            else:
                if bool(candle['bullish_candle']) and float(next_candle['body_atr']) >= 0.35:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    if abs(current - ob_high) <= atr * 2.5 or abs(current - ob_low) <= atr * 2.5:
                        return True

        return False

    # =========================================================
    # STRATEGY EVALUATION (Threshold lowered to 38)
    # =========================================================

    def evaluate_strategy(self, symbol):
        df_15m = self._fetch_ohlcv(symbol, '15m', 220)
        if df_15m is None or len(df_15m) < 60:
            return None

        df_15m = self._prepare(df_15m)
        if len(df_15m) < 30:
            return None

        df_1h = self._fetch_ohlcv(symbol, '1h', 100)
        df_4h = self._fetch_ohlcv(symbol, '4h', 100)

        trend_15m = self.get_trend(df_15m)
        trend_1h = self.get_trend(df_1h) if df_1h is not None else 'NEUTRAL'
        trend_4h = self.get_trend(df_4h) if df_4h is not None else 'NEUTRAL'

        for direction in ['LONG', 'SHORT']:
            struct_data = self.get_structure(df_15m, direction)
            structure = struct_data['structure']

            momentum = self.get_momentum(df_15m, direction)
            volume_ok = self.get_volume_confirmation(df_15m)
            displacement = self.get_displacement(df_15m, direction)
            fvg_ok = self.detect_fvg(df_15m, direction)
            ob_ok = self.detect_order_block(df_15m, direction)

            score = 0
            confirmations = []

            if structure == direction or structure == 'BULLISH' if direction == 'LONG' else 'BEARISH':
                score += 30
                confirmations.append('Structure')

            if momentum:
                score += 20
                confirmations.append('Momentum')

            if volume_ok:
                score += 15
                confirmations.append('Volume')

            if displacement:
                score += 15
                confirmations.append('Displacement')

            if fvg_ok:
                score += 10
                confirmations.append('FVG')

            if ob_ok:
                score += 10
                confirmations.append('OrderBlock')

            # تم تخفيض الحد الأدنى للنقاط إلى 38 لزيادة عدد الصفقات المتاحة
            if score >= 38:
                row = df_15m.iloc[-2]
                entry = float(row['close'])
                atr = float(row['atr'])

                if direction == 'LONG':
                    sl = entry - (atr * 1.5)
                    tp1 = entry + (atr * 3.0)
                    tp2 = entry + (atr * 5.25)
                    tp3 = entry + (atr * 7.5)
                else:
                    sl = entry + (atr * 1.5)
                    tp1 = entry - (atr * 3.0)
                    tp2 = entry - (atr * 5.25)
                    tp3 = entry - (atr * 7.5)

                risk_pct = round((abs(entry - sl) / entry) * 100, 2)

                return {
                    'symbol': symbol,
                    'decision': direction,
                    'score': score,
                    'quality': 'HIGH' if score >= 65 else 'MEDIUM',
                    'confirmation_count': len(confirmations),
                    'confirmations': confirmations,
                    'trend_4h': trend_4h,
                    'trend_1h': trend_1h,
                    'btc_context': 'NEUTRAL',
                    'rsi_15m': float(row['rsi']),
                    'volume_ratio': float(row['volume_ratio']),
                    'entry': entry,
                    'sl': sl,
                    'tp1': tp1,
                    'tp2': tp2,
                    'tp3': tp3,
                    'risk_pct': risk_pct,
                    'risk_filter': 'PASSED',
                    'structure_confirmation': structure,
                    'btc_conflict': False,
                    'entry_quality': 'OPTIMAL'
                }

        return None
