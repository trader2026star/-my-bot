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

            self._cache[key] = (now, df)

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

        rs = avg_gain / avg_loss.replace(
            0,
            np.nan
        )

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (
            df['high'] - prev_close
        ).abs()
        tr3 = (
            df['low'] - prev_close
        ).abs()

        tr = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = tr.rolling(14).mean()

        df['vol_ma'] = df['volume'].rolling(20).mean()

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

        close = row['close']
        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

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
    # STRUCTURE
    # =========================================================

    def get_structure(self, df):
        if df is None or len(df) < 40:
            return {
                'structure': 'NEUTRAL',
                'bos_long': False,
                'bos_short': False,
                'sweep_long': False,
                'sweep_short': False
            }

        x = df.iloc[:-1].copy()
        last = x.iloc[-1]

        previous_high = x['high'].iloc[-13:-1].max()
        previous_low = x['low'].iloc[-13:-1].min()

        bos_long = (
            last['close'] >
            previous_high
        )

        bos_short = (
            last['close'] <
            previous_low
        )

        sweep_long = (
            last['low'] < previous_low and
            last['close'] > previous_low
        )

        sweep_short = (
            last['high'] > previous_high and
            last['close'] < previous_high
        )

        half = max(
            8,
            len(x) // 2
        )

        first = x.iloc[
            -half:-half // 2
        ]

        second = x.iloc[
            -half // 2:
        ]

        first_high = first['high'].max()
        second_high = second['high'].max()

        first_low = first['low'].min()
        second_low = second['low'].min()

        if (
            second_high > first_high and
            second_low > first_low
        ):
            structure = 'HH/HL'

        elif (
            second_high < first_high and
            second_low < first_low
        ):
            structure = 'LH/LL'

        elif bos_long:
            structure = 'BULLISH BOS'

        elif bos_short:
            structure = 'BEARISH BOS'

        else:
            structure = 'RANGE'

        return {
            'structure': structure,
            'bos_long': bool(bos_long),
            'bos_short': bool(bos_short),
            'sweep_long': bool(sweep_long),
            'sweep_short': bool(sweep_short)
        }

    # =========================================================
    # MOMENTUM
    # =========================================================

    def get_momentum(self, df, direction):
        if df is None or len(df) < 30:
            return False

        row = df.iloc[-2]

        rsi = float(row['rsi'])
        body_atr = float(row['body_atr'])

        bullish = (
            row['close'] >
            row['open']
        )

        bearish = (
            row['close'] <
            row['open']
        )

        if direction == 'LONG':
            return (
                50 <= rsi <= 72 and
                bullish and
                body_atr >= 0.30
            )

        if direction == 'SHORT':
            return (
                28 <= rsi <= 50 and
                bearish and
                body_atr >= 0.30
            )

        return False

    # =========================================================
    # VOLUME
    # =========================================================

    def get_volume_confirmation(self, df):
        if df is None:
            return False, 0.0

        row = df.iloc[-2]

        ratio = float(
            row['volume_ratio']
        )

        return (
            ratio >= 1.10,
            ratio
        )

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def get_displacement(self, df, direction):
        if df is None:
            return False

        row = df.iloc[-2]

        body_atr = float(
            row['body_atr']
        )

        if direction == 'LONG':
            return (
                row['close'] >
                row['open'] and
                body_atr >= 0.55
            )

        if direction == 'SHORT':
            return (
                row['close'] <
                row['open'] and
                body_atr >= 0.55
            )

        return False

    # =========================================================
    # FVG
    # =========================================================

    def detect_fvg(self, df, direction):
        if df is None or len(df) < 10:
            return False, None

        x = df.iloc[:-1]

        start = max(
            2,
            len(x) - 14
        )

        current_price = float(
            x.iloc[-1]['close']
        )

        atr = float(
            x.iloc[-1]['atr']
        )

        if not np.isfinite(atr) or atr <= 0:
            return False, None

        best = None

        for i in range(start, len(x)):

            a = x.iloc[i - 2]
            c = x.iloc[i]

            # ---------------------------------
            # BULLISH FVG
            # ---------------------------------

            if direction == 'LONG':

                if c['low'] > a['high']:

                    zone_low = float(
                        a['high']
                    )

                    zone_high = float(
                        c['low']
                    )

                    distance = min(
                        abs(
                            current_price -
                            zone_low
                        ),
                        abs(
                            current_price -
                            zone_high
                        )
                    )

                    if distance <= atr * 1.5:

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

            # ---------------------------------
            # BEARISH FVG
            # ---------------------------------

            if direction == 'SHORT':

                if c['high'] < a['low']:

                    zone_low = float(
                        c['high']
                    )

                    zone_high = float(
                        a['low']
                    )

                    distance = min(
                        abs(
                            current_price -
                            zone_low
                        ),
                        abs(
                            current_price -
                            zone_high
                        )
                    )

                    if distance <= atr * 1.5:

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

        return (
            best is not None,
            best
        )

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if df is None or len(df) < 30:
            return False, None

        x = df.iloc[:-1]

        current_price = float(
            x.iloc[-1]['close']
        )

        current_atr = float(
            x.iloc[-1]['atr']
        )

        if (
            not np.isfinite(current_atr)
            or current_atr <= 0
        ):
            return False, None

        start = max(
            2,
            len(x) - 15
        )

        best = None

        for i in range(
            start,
            len(x) - 1
        ):

            candle = x.iloc[i]
            next_candle = x.iloc[i + 1]

            # ---------------------------------
            # LONG OB
            # ---------------------------------

            if direction == 'LONG':

                bearish = (
                    candle['close'] <
                    candle['open']
                )

                displacement = (
                    next_candle['close'] >
                    next_candle['open']
                    and
                    (
                        next_candle['close'] -
                        next_candle['open']
                    ) >= current_atr * 0.45
                )

                broken = (
                    next_candle['close'] >
                    candle['high']
                )

                if (
                    bearish and
                    displacement and
                    broken
                ):

                    zone_low = float(
                        candle['low']
                    )

                    zone_high = float(
                        candle['open']
                    )

                    distance = min(
                        abs(
                            current_price -
                            zone_low
                        ),
                        abs(
                            current_price -
                            zone_high
                        )
                    )

                    if (
                        distance <=
                        current_atr * 1.75
                    ):

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

            # ---------------------------------
            # SHORT OB
            # ---------------------------------

            if direction == 'SHORT':

                bullish = (
                    candle['close'] >
                    candle['open']
                )

                displacement = (
                    next_candle['close'] <
                    next_candle['open']
                    and
                    (
                        next_candle['open'] -
                        next_candle['close']
                    ) >= current_atr * 0.45
                )

                broken = (
                    next_candle['close'] <
                    candle['low']
                )

                if (
                    bullish and
                    displacement and
                    broken
                ):

                    zone_low = float(
                        candle['open']
                    )

                    zone_high = float(
                        candle['high']
                    )

                    distance = min(
                        abs(
                            current_price -
                            zone_low
                        ),
                        abs(
                            current_price -
                            zone_high
                        )
                    )

                    if (
                        distance <=
                        current_atr * 1.75
                    ):

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

        return (
            best is not None,
            best
        )

    # =========================================================
    # BTC
    # =========================================================

    def get_btc_context(self):
        try:
            df = self.fetch_ohlcv(
                'BTC/USDT:USDT',
                '1h',
                150
            )

            if df is None:
                return 'UNKNOWN'

            df = self.add_indicators(df)

            return self.get_trend(df)

        except Exception as e:
            logger.warning(
                "BTC context error: %s",
                e
            )
            return 'UNKNOWN'

    # =========================================================
    # LEVELS
    # =========================================================

    def build_levels(
        self,
        df,
        direction
    ):
        x = df.iloc[:-1]

        entry = float(
            x.iloc[-1]['close']
        )

        atr = float(
            x.iloc[-1]['atr']
        )

        if (
            not np.isfinite(atr)
            or atr <= 0
        ):
            return None

        recent = x.iloc[-12:]

        recent_low = float(
            recent['low'].min()
        )

        recent_high = float(
            recent['high'].max()
        )

        if direction == 'LONG':

            swing_sl = (
                recent_low -
                atr * 0.25
            )

            atr_sl = (
                entry -
                atr * 1.25
            )

            raw_sl = min(
                swing_sl,
                atr_sl
            )

            risk = entry - raw_sl

            risk_pct = (
                risk / entry
            ) * 100

            if risk_pct > 7.0:
                return None

            min_risk = entry * 0.008

            if risk < min_risk:
                risk = min_risk
                raw_sl = entry - risk

            sl = raw_sl

            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5.0

        else:

            swing_sl = (
                recent_high +
                atr * 0.25
            )

            atr_sl = (
                entry +
                atr * 1.25
            )

            raw_sl = max(
                swing_sl,
                atr_sl
            )

            risk = raw_sl - entry

            risk_pct = (
                risk / entry
            ) * 100

            if risk_pct > 7.0:
                return None

            min_risk = entry * 0.008

            if risk < min_risk:
                risk = min_risk
                raw_sl = entry + risk

            sl = raw_sl

            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5.0

        return {
            'entry': entry,
            'sl': float(sl),
            'tp1': float(tp1),
            'tp2': float(tp2),
            'tp3': float(tp3),
            'risk_pct': float(risk_pct)
        }

    # =========================================================
    # QUALITY ENGINE
    # =========================================================

    def evaluate_quality(
        self,
        direction,
        score,
        confirmations,
        rsi,
        volume_ratio,
        btc_conflict,
        btc_aligned,
        risk_pct,
        bos,
        sweep,
        displacement,
        fvg,
        order_block,
        momentum
    ):

        # ---------------------------------
        # HARD RSI FILTER
        # ---------------------------------

        if direction == 'LONG' and rsi >= 78:
            return {
                'accepted': False,
                'score': score,
                'quality': 'REJECTED',
                'reason': 'RSI OVERHEATED'
            }

        if direction == 'SHORT' and rsi <= 22:
            return {
                'accepted': False,
                'score': score,
                'quality': 'REJECTED',
                'reason': 'RSI OVERSOLD'
            }

        # ---------------------------------
        # RISK FILTER
        # ---------------------------------

        if risk_pct > 7.0:
            return {
                'accepted': False,
                'score': score,
                'quality': 'REJECTED',
                'reason': 'RISK TOO WIDE'
            }

        # ---------------------------------
        # REAL STRUCTURE
        # ---------------------------------

        structural_count = sum([
            bool(bos),
            bool(sweep),
            bool(displacement),
            bool(fvg)
        ])

        if structural_count < 1:
            return {
                'accepted': False,
                'score': score,
                'quality': 'REJECTED',
                'reason': 'NO STRUCTURAL CONFIRMATION'
            }

        # ---------------------------------
        # MINIMUM CONFLUENCE
        # ---------------------------------

        if confirmations < 3:
            return {
                'accepted': False,
                'score': score,
                'quality': 'REJECTED',
                'reason': 'INSUFFICIENT CONFIRMATION'
            }

        adjusted_score = int(score)

        # ---------------------------------
        # RSI PENALTY
        # ---------------------------------

        if direction == 'LONG':

            if rsi >= 75:
                adjusted_score -= 2

            elif rsi >= 72:
                adjusted_score -= 1

        else:

            if rsi <= 25:
                adjusted_score -= 2

            elif rsi <= 28:
                adjusted_score -= 1

        # ---------------------------------
        # VOLUME
        # ---------------------------------

        if volume_ratio < 1.05:
            adjusted_score -= 1

        # ---------------------------------
        # BTC CONFLICT
        # ---------------------------------

        if btc_conflict:
            adjusted_score -= 1

        # ---------------------------------
        # WIDE RISK
        # ---------------------------------

        if risk_pct >= 6.0:
            adjusted_score -= 1

        # ---------------------------------
        # BTC CONFLICT + WEAK VOLUME
        # ---------------------------------

        if (
            btc_conflict and
            volume_ratio < 1.05
        ):

            strong_evidence = sum([
                bool(bos),
                bool(sweep),
                bool(displacement),
                bool(fvg),
                bool(momentum)
            ])

            if strong_evidence < 3:
                return {
                    'accepted': False,
                    'score': adjusted_score,
                    'quality': 'REJECTED',
                    'reason':
                        'BTC CONFLICT + WEAK VOLUME'
                }

        # ---------------------------------
        # OB ALONE
        # ---------------------------------

        if (
            order_block and
            not bos and
            not displacement and
            not fvg and
            not sweep
        ):
            return {
                'accepted': False,
                'score': adjusted_score,
                'quality': 'REJECTED',
                'reason': 'ORDER BLOCK ALONE'
            }

        if adjusted_score < 5:
            return {
                'accepted': False,
                'score': adjusted_score,
                'quality': 'REJECTED',
                'reason': 'SCORE BELOW THRESHOLD'
            }

        # =====================================================
        # QUALITY CLASSIFICATION
        # =====================================================

        # STRONG:
        # ممنوع مع BTC conflict
        if (
            adjusted_score >= 8 and
            confirmations >= 5 and
            btc_aligned and
            not btc_conflict and
            volume_ratio >= 1.10 and
            risk_pct < 6.0 and
            rsi < 72
        ):
            quality = 'STRONG SETUP'

        # VALID:
        # يسمح بـ BTC conflict لكن مع أدلة حقيقية
        elif (
            adjusted_score >= 5 and
            confirmations >= 4
        ):
            quality = 'VALID SETUP'

        else:
            quality = 'MODERATE SETUP'

        return {
            'accepted': True,
            'score': adjusted_score,
            'quality': quality,
            'reason': 'PASS'
        }

    # =========================================================
    # MAIN ANALYSIS
    # =========================================================

    def evaluate_strategy(self, symbol):

        try:

            # ---------------------------------
            # DATA
            # ---------------------------------

            df4h = self.fetch_ohlcv(
                symbol,
                '4h',
                220
            )

            df1h = self.fetch_ohlcv(
                symbol,
                '1h',
                220
            )

            df15 = self.fetch_ohlcv(
                symbol,
                '15m',
                220
            )

            if (
                df4h is None or
                df1h is None or
                df15 is None
            ):
                return None

            df4h = self.add_indicators(df4h)
            df1h = self.add_indicators(df1h)
            df15 = self.add_indicators(df15)

            # ---------------------------------
            # TRENDS
            # ---------------------------------

            trend4h = self.get_trend(df4h)
            trend1h = self.get_trend(df1h)

            structure1h = self.get_structure(df1h)
            structure15 = self.get_structure(df15)

            # ---------------------------------
            # BTC
            # ---------------------------------

            btc_context = self.get_btc_context()

            # ---------------------------------
            # DIRECTION
            # ---------------------------------

            if trend4h == 'BULLISH':
                direction = 'LONG'

            elif trend4h == 'BEARISH':
                direction = 'SHORT'

            else:
                return None

            # ---------------------------------
            # VOTES
            # ---------------------------------

            long_votes = 0
            short_votes = 0

            if trend4h == 'BULLISH':
                long_votes += 2

            if trend4h == 'BEARISH':
                short_votes += 2

            if trend1h == 'BULLISH':
                long_votes += 1

            if trend1h == 'BEARISH':
                short_votes += 1

            if structure1h['structure'] in (
                'HH/HL',
                'BULLISH BOS'
            ):
                long_votes += 1

            if structure1h['structure'] in (
                'LH/LL',
                'BEARISH BOS'
            ):
                short_votes += 1

            if structure15['structure'] in (
                'HH/HL',
                'BULLISH BOS'
            ):
                long_votes += 1

            if structure15['structure'] in (
                'LH/LL',
                'BEARISH BOS'
            ):
                short_votes += 1

            if btc_context == 'BULLISH':
                long_votes += 1

            if btc_context == 'BEARISH':
                short_votes += 1

            # ---------------------------------
            # 15M
            # ---------------------------------

            row15 = df15.iloc[-2]

            rsi = float(
                row15['rsi']
            )

            volume_ok, volume_ratio = (
                self.get_volume_confirmation(
                    df15
                )
            )

            # ---------------------------------
            # STRUCTURE
            # ---------------------------------

            if direction == 'LONG':

                bos = (
                    structure1h['bos_long'] or
                    structure15['bos_long']
                )

                sweep = (
                    structure1h['sweep_long'] or
                    structure15['sweep_long']
                )

                structure_name = (
                    structure15['structure']
                )

            else:

                bos = (
                    structure1h['bos_short'] or
                    structure15['bos_short']
                )

                sweep = (
                    structure1h['sweep_short'] or
                    structure15['sweep_short']
                )

                structure_name = (
                    structure15['structure']
                )

            # ---------------------------------
            # MOMENTUM
            # ---------------------------------

            momentum = self.get_momentum(
                df15,
                direction
            )

            displacement = (
                self.get_displacement(
                    df15,
                    direction
                )
            )

            # ---------------------------------
            # FVG / OB
            # ---------------------------------

            fvg_ok, fvg_zone = (
                self.detect_fvg(
                    df15,
                    direction
                )
            )

            ob_ok, ob_zone = (
                self.detect_order_block(
                    df15,
                    direction
                )
            )

            # ---------------------------------
            # SCORE
            # ---------------------------------

            score = 0
            confirmations = []

            # 4H
            if direction == 'LONG':

                if trend4h == 'BULLISH':
                    score += 2
                    confirmations.append(
                        '4H TREND'
                    )

            else:

                if trend4h == 'BEARISH':
                    score += 2
                    confirmations.append(
                        '4H TREND'
                    )

            # 1H
            if direction == 'LONG':

                if trend1h == 'BULLISH':
                    score += 1
                    confirmations.append(
                        '1H TREND'
                    )

            else:

                if trend1h == 'BEARISH':
                    score += 1
                    confirmations.append(
                        '1H TREND'
                    )

            # Structure
            if direction == 'LONG':

                if structure_name in (
                    'HH/HL',
                    'BULLISH BOS'
                ):
                    score += 1
                    confirmations.append(
                        'STRUCTURE'
                    )

            else:

                if structure_name in (
                    'LH/LL',
                    'BEARISH BOS'
                ):
                    score += 1
                    confirmations.append(
                        'STRUCTURE'
                    )

            # BOS
            if bos:
                score += 2
                confirmations.append(
                    'BOS'
                )

            # Liquidity
            if sweep:
                score += 1
                confirmations.append(
                    'LIQUIDITY SWEEP'
                )

            # Momentum
            if momentum:
                score += 1
                confirmations.append(
                    'MOMENTUM'
                )

            # Volume
            if volume_ok:
                score += 1
                confirmations.append(
                    'VOLUME'
                )

            # Displacement
            if displacement:
                score += 1
                confirmations.append(
                    'DISPLACEMENT'
                )

            # FVG
            if fvg_ok:
                score += 1
                confirmations.append(
                    'FVG'
                )

            # OB
            if ob_ok:
                score += 1
                confirmations.append(
                    'ORDER BLOCK'
                )

            # ---------------------------------
            # BTC ALIGNMENT
            # ---------------------------------

            btc_conflict = (
                (
                    direction == 'LONG' and
                    btc_context == 'BEARISH'
                )
                or
                (
                    direction == 'SHORT' and
                    btc_context == 'BULLISH'
                )
            )

            btc_aligned = (
                (
                    direction == 'LONG' and
                    btc_context == 'BULLISH'
                )
                or
                (
                    direction == 'SHORT' and
                    btc_context == 'BEARISH'
                )
            )

            if btc_aligned:
                score += 1
                confirmations.append(
                    'BTC ALIGNMENT'
                )

            # ---------------------------------
            # LEVELS
            # ---------------------------------

            levels = self.build_levels(
                df15,
                direction
            )

            if levels is None:
                return None

            risk_pct = levels['risk_pct']

            # ---------------------------------
            # QUALITY
            # ---------------------------------

            quality_result = (
                self.evaluate_quality(
                    direction=direction,
                    score=score,
                    confirmations=len(
                        confirmations
                    ),
                    rsi=rsi,
                    volume_ratio=volume_ratio,
                    btc_conflict=btc_conflict,
                    btc_aligned=btc_aligned,
                    risk_pct=risk_pct,
                    bos=bos,
                    sweep=sweep,
                    displacement=displacement,
                    fvg=fvg_ok,
                    order_block=ob_ok,
                    momentum=momentum
                )
            )

            if not quality_result['accepted']:
                return None

            final_score = int(
                quality_result['score']
            )

            quality = (
                quality_result['quality']
            )

            # ---------------------------------
            # ENTRY STATUS
            # ---------------------------------

            if btc_conflict:

                if volume_ratio >= 1.50:
                    entry_quality = (
                        'BTC CONFLICT - '
                        'STRONG LOCAL CONFIRMATION'
                    )

                elif (
                    displacement and
                    bos and
                    fvg_ok
                ):
                    entry_quality = (
                        'BTC CONFLICT - '
                        'STRUCTURE COMPENSATES'
                    )

                else:
                    entry_quality = (
                        'BTC CONFLICT - '
                        'REDUCED CONFIDENCE'
                    )

            elif risk_pct >= 6.0:

                entry_quality = (
                    'WIDE RISK - '
                    'REDUCED CONFIDENCE'
                )

            elif (
                direction == 'LONG' and
                rsi >= 75
            ):

                entry_quality = (
                    'RSI HIGH - '
                    'AVOID CHASING'
                )

            elif (
                direction == 'SHORT' and
                rsi <= 25
            ):

                entry_quality = (
                    'RSI LOW - '
                    'AVOID CHASING'
                )

            else:
                entry_quality = 'GOOD'

            # ---------------------------------
            # RISK
            # ---------------------------------

            if risk_pct < 6.0:
                risk_filter = 'PASS'

            else:
                risk_filter = 'PASS - WIDE'

            # ---------------------------------
            # MESSAGE
            # ---------------------------------

            btc_warning = (
                ' ⚠️ CONFLICT'
                if btc_conflict
                else ''
            )

            message = (
                f"🚨 EXPERT FUTURES SIGNAL 🚨\n\n"

                f"Symbol: {symbol}\n"
                f"Decision: {direction}\n"
                f"Score: {final_score}\n"
                f"Quality: {quality}\n\n"

                f"Confirmations: "
                f"{len(confirmations)}/3+\n"
                f"• "
                f"{', '.join(confirmations)}\n\n"

                f"4H: {trend4h}\n"
                f"1H: {trend1h}\n"
                f"Structure: {structure_name}\n"
                f"BTC: {btc_context}"
                f"{btc_warning}\n\n"

                f"RSI 15M: {rsi:.1f}\n"
                f"Volume: {volume_ratio:.2f}x\n"

                f"Momentum: "
                f"{'YES' if momentum else 'NO'}\n"

                f"Displacement: "
                f"{'YES' if displacement else 'NO'}\n"

                f"FVG: "
                f"{'ACTIVE' if fvg_ok else 'NO'}\n"

                f"Order Block: "
                f"{'ACTIVE' if ob_ok else 'NO'}\n\n"

                f"Entry: "
                f"{levels['entry']:.8f}\n"

                f"SL: "
                f"{levels['sl']:.8f} "
                f"({risk_pct:.2f}%)\n"

                f"TP1: "
                f"{levels['tp1']:.8f} | 2R\n"

                f"TP2: "
                f"{levels['tp2']:.8f} | 3.5R\n"

                f"TP3: "
                f"{levels['tp3']:.8f} | 5R\n\n"

                f"Risk Filter: {risk_filter}\n"

                f"Structure Confirmation: "
                f"{'PASS' if (
                    bos or
                    sweep or
                    displacement or
                    fvg_ok
                ) else 'FAIL'}\n"

                f"Entry Status: "
                f"{entry_quality}\n\n"

                f"⚠️ Setup signal — "
                f"not a guaranteed result."
            )

            # ---------------------------------
            # RETURN
            # ---------------------------------

            return {
                'symbol': symbol,
                'decision': direction,

                'score': final_score,
                'quality': quality,

                'confirmations': confirmations,
                'confirmation_count': len(
                    confirmations
                ),

                'trend_4h': trend4h,
                'trend_1h': trend1h,

                'btc_context': btc_context,
                'btc_conflict': btc_conflict,
                'btc_aligned': btc_aligned,

                'rsi_15m': float(rsi),
                'volume_ratio': float(
                    volume_ratio
                ),

                'entry': levels['entry'],
                'sl': levels['sl'],
                'tp1': levels['tp1'],
                'tp2': levels['tp2'],
                'tp3': levels['tp3'],

                'risk_pct': float(
                    risk_pct
                ),

                'risk_filter': risk_filter,

                'structure_confirmation': (
                    'PASS'
                    if (
                        bos or
                        sweep or
                        displacement or
                        fvg_ok
                    )
                    else 'FAIL'
                ),

                'bos': bos,
                'liquidity_sweep': sweep,
                'structure': structure_name,

                'momentum': momentum,
                'volume_confirmation': volume_ok,
                'displacement': displacement,

                'fvg': fvg_ok,
                'order_block': ob_ok,

                'entry_quality': entry_quality,

                'message': message
            }

        except Exception as e:

            logger.exception(
                "Error analyzing %s: %s",
                symbol,
                e
            )

            return None
