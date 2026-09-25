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

        highs = recent['high']
        lows = recent['low']

        last_close = x['close'].iloc[-1]
        last_high = x['high'].iloc[-1]
        last_low = x['low'].iloc[-1]

        midpoint = len(recent) // 2

        first_half = recent.iloc[:midpoint]
        second_half = recent.iloc[midpoint:]

        prev_high = first_half['high'].max()
        prev_low = first_half['low'].min()

        recent_high = second_half['high'].max()
        recent_low = second_half['low'].min()

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
            if bos_long:
                structure = 'BULLISH'
            elif hh_hl:
                structure = 'BULLISH'
            else:
                structure = 'NEUTRAL'

            bos = bool(bos_long)
            sweep = bool(sweep_long)

        else:
            if bos_short:
                structure = 'BEARISH'
            elif lh_ll:
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

        atr = float(df.iloc[-2]['atr'])
        current = float(df.iloc[-2]['close'])

        start = max(2, len(df) - 18)

        for i in range(start, len(df) - 2):
            a = df.iloc[i - 1]
            b = df.iloc[i]
            c = df.iloc[i + 1]

            if direction == 'LONG':
                gap_low = float(a['high'])
                gap_high = float(c['low'])

                if gap_high > gap_low:
                    distance = min(
                        abs(current - gap_low),
                        abs(current - gap_high)
                    )

                    if distance <= atr * 1.75:
                        return True

            else:
                gap_high = float(a['low'])
                gap_low = float(c['high'])

                if gap_high > gap_low:
                    distance = min(
                        abs(current - gap_low),
                        abs(current - gap_high)
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

        atr = float(df.iloc[-2]['atr'])
        current = float(df.iloc[-2]['close'])

        start = max(3, len(df) - 18)

        for i in range(start, len(df) - 2):
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
                    float(next_candle['body_atr']) >= 0.45 and
                    float(next_candle['close']) >
                    float(candle['high'])
                ):
                    return True

            else:
                if (
                    candle['bullish_candle'] and
                    next_candle['bearish_candle'] and
                    float(next_candle['body_atr']) >= 0.45 and
                    float(next_candle['close']) <
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

        entry = float(row['close'])
        atr = float(row['atr'])

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

            risk_pct = (
                risk / entry
            ) * 100

            # Don't allow extremely tight stops.
            minimum_risk = entry * 0.008

            if risk < minimum_risk:
                sl = entry - minimum_risk
                risk = minimum_risk
                risk_pct = (
                    risk / entry
                ) * 100

            # Do not accept absurdly wide risk.
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

            risk_pct = (
                risk / entry
            ) * 100

            minimum_risk = entry * 0.008

            if risk < minimum_risk:
                sl = entry + minimum_risk
                risk = minimum_risk
                risk_pct = (
                    risk / entry
                ) * 100

            if risk_pct > 7.0:
                return None

            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5.0

        return {
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': risk_pct
        }

    # =========================================================
    # CONFIRMATIONS
    # =========================================================

    def build_confirmations(
        self,
        direction,
        trend4h,
        trend1h,
        structure_data,
        momentum,
        volume_confirmation,
        displacement,
        fvg,
        order_block,
        btc_context
    ):
        confirmations = []

        if (
            (direction == 'LONG' and
             trend4h == 'BULLISH') or
            (direction == 'SHORT' and
             trend4h == 'BEARISH')
        ):
            confirmations.append('4H TREND')

        if (
            (direction == 'LONG' and
             trend1h == 'BULLISH') or
            (direction == 'SHORT' and
             trend1h == 'BEARISH')
        ):
            confirmations.append('1H TREND')

        if structure_data['bos']:
            confirmations.append('BOS')

        if structure_data['liquidity_sweep']:
            confirmations.append('LIQUIDITY SWEEP')

        if momentum:
            confirmations.append('MOMENTUM')

        if displacement:
            confirmations.append('DISPLACEMENT')

        if fvg:
            confirmations.append('FVG')

        if order_block:
            confirmations.append('ORDER BLOCK')

        if volume_confirmation:
            confirmations.append('VOLUME')

        if (
            (direction == 'LONG' and
             btc_context == 'BULLISH') or
            (direction == 'SHORT' and
             btc_context == 'BEARISH')
        ):
            confirmations.append('BTC ALIGNMENT')

        return confirmations

    # =========================================================
    # QUALITY ENGINE
    # =========================================================

    def evaluate_quality(
        self,
        direction,
        trend4h,
        trend1h,
        btc_context,
        rsi,
        volume_ratio,
        structure_data,
        momentum,
        displacement,
        fvg,
        order_block,
        levels,
        confirmations
    ):
        if levels is None:
            return {
                'valid': False,
                'score': 0,
                'quality': 'NO TRADE',
                'reason': 'INVALID RISK'
            }

        risk_pct = levels['risk_pct']

        # -----------------------------------------------------
        # HARD REJECTIONS
        # -----------------------------------------------------

        if direction == 'LONG' and rsi >= 75:
            return {
                'valid': False,
                'score': 0,
                'quality': 'NO TRADE',
                'reason': 'RSI TOO HIGH'
            }

        if direction == 'SHORT' and rsi <= 25:
            return {
                'valid': False,
                'score': 0,
                'quality': 'NO TRADE',
                'reason': 'RSI TOO LOW'
            }

        if risk_pct > 7:
            return {
                'valid': False,
                'score': 0,
                'quality': 'NO TRADE',
                'reason': 'RISK TOO HIGH'
            }

        # -----------------------------------------------------
        # STRUCTURAL EVIDENCE
        # -----------------------------------------------------

        bos = structure_data['bos']
        sweep = structure_data['liquidity_sweep']

        structural_evidence = sum([
            bool(bos),
            bool(sweep),
            bool(displacement),
            bool(fvg)
        ])

        # OB alone is never enough.
        if structural_evidence < 1:
            return {
                'valid': False,
                'score': 0,
                'quality': 'NO TRADE',
                'reason': 'NO STRUCTURAL EVIDENCE'
            }

        # -----------------------------------------------------
        # INDEPENDENT CONFIRMATION GROUPS
        # -----------------------------------------------------

        groups = 0

        trend_group = (
            (
                direction == 'LONG' and
                trend4h == 'BULLISH'
            ) or
            (
                direction == 'SHORT' and
                trend4h == 'BEARISH'
            )
        )

        if trend_group:
            groups += 1

        structure_group = (
            bos or
            sweep or
            displacement
        )

        if structure_group:
            groups += 1

        momentum_group = bool(momentum)

        if momentum_group:
            groups += 1

        volume_group = (
            volume_ratio >= 1.05
        )

        if volume_group:
            groups += 1

        location_group = (
            fvg or
            order_block
        )

        if location_group:
            groups += 1

        # -----------------------------------------------------
        # RAW SCORE
        # -----------------------------------------------------

        score = 0

        if trend4h == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):
            score += 2

        if trend1h == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):
            score += 1

        if structure_group:
            score += 1

        if bos:
            score += 2

        if sweep:
            score += 1

        if momentum:
            score += 1

        if volume_ratio >= 1.05:
            score += 1

        if displacement:
            score += 1

        if fvg:
            score += 1

        if order_block:
            score += 1

        if btc_context == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):
            score += 1

        # -----------------------------------------------------
        # PENALTIES
        # -----------------------------------------------------

        adjusted_score = score

        # Low volume penalties
        if volume_ratio < 0.80:
            adjusted_score -= 2
        elif volume_ratio < 1.00:
            adjusted_score -= 1
        elif volume_ratio < 1.05:
            adjusted_score -= 1

        # Risk penalties
        if risk_pct >= 5.0:
            adjusted_score -= 1

        # RSI late-entry penalty
        if direction == 'LONG':
            if rsi >= 72:
                adjusted_score -= 2
            elif rsi >= 68:
                adjusted_score -= 1
        else:
            if rsi <= 28:
                adjusted_score -= 2
            elif rsi <= 32:
                adjusted_score -= 1

        # BTC conflict
        btc_conflict = (
            (
                direction == 'LONG' and
                btc_context == 'BEARISH'
            ) or
            (
                direction == 'SHORT' and
                btc_context == 'BULLISH'
            )
        )

        if btc_conflict:
            adjusted_score -= 1

        # -----------------------------------------------------
        # SPECIAL LOW VOLUME RULE
        # -----------------------------------------------------

        if volume_ratio < 0.80:

            strong_compensation = (
                bos and
                displacement and
                (
                    sweep or
                    fvg
                )
            )

            if not strong_compensation:
                return {
                    'valid': False,
                    'score': max(0, adjusted_score),
                    'quality': 'NO TRADE',
                    'reason': 'VERY LOW VOLUME'
                }

        # -----------------------------------------------------
        # BTC CONFLICT RULE
        # -----------------------------------------------------

        if btc_conflict:

            compensation = sum([
                bool(bos),
                bool(sweep),
                bool(displacement),
                bool(fvg),
                bool(momentum)
            ])

            if compensation < 3:
                return {
                    'valid': False,
                    'score': max(0, adjusted_score),
                    'quality': 'NO TRADE',
                    'reason': 'BTC CONFLICT'
                }

            if direction == 'LONG' and rsi >= 70:
                return {
                    'valid': False,
                    'score': max(0, adjusted_score),
                    'quality': 'NO TRADE',
                    'reason': 'BTC CONFLICT + LATE LONG'
                }

            if direction == 'SHORT' and rsi <= 30:
                return {
                    'valid': False,
                    'score': max(0, adjusted_score),
                    'quality': 'NO TRADE',
                    'reason': 'BTC CONFLICT + LATE SHORT'
                }

        # -----------------------------------------------------
        # TREND CONFLICT
        # -----------------------------------------------------

        trend_conflict = (
            trend4h != 'NEUTRAL' and
            trend1h != 'NEUTRAL' and
            trend4h != trend1h
        )

        if trend_conflict:

            compensation = sum([
                bool(bos),
                bool(sweep),
                bool(displacement),
                bool(fvg),
                bool(momentum)
            ])

            if compensation < 3:
                return {
                    'valid': False,
                    'score': max(0, adjusted_score),
                    'quality': 'NO TRADE',
                    'reason': 'TIMEFRAME CONFLICT'
                }

        # -----------------------------------------------------
        # MINIMUM REAL CONFIRMATIONS
        # -----------------------------------------------------

        if len(confirmations) < 3:
            return {
                'valid': False,
                'score': max(0, adjusted_score),
                'quality': 'NO TRADE',
                'reason': 'LESS THAN 3 CONFIRMATIONS'
            }

        # Prevent trend-only confirmation inflation.
        real_evidence = sum([
            bool(bos),
            bool(sweep),
            bool(momentum),
            bool(displacement),
            bool(fvg),
            bool(order_block),
            volume_ratio >= 1.05
        ])

        if real_evidence < 2:
            return {
                'valid': False,
                'score': max(0, adjusted_score),
                'quality': 'NO TRADE',
                'reason': 'WEAK REAL EVIDENCE'
            }

        # -----------------------------------------------------
        # FINAL SCORE GATE
        # -----------------------------------------------------

        if adjusted_score < 5:
            return {
                'valid': False,
                'score': max(0, adjusted_score),
                'quality': 'NO TRADE',
                'reason': 'FINAL SCORE BELOW THRESHOLD'
            }

        # -----------------------------------------------------
        # QUALITY
        # -----------------------------------------------------

        strong = (
            adjusted_score >= 8 and
            groups >= 4 and
            trend4h == trend1h and
            volume_ratio >= 1.10 and
            risk_pct < 5.0 and
            not btc_conflict and
            (
                (direction == 'LONG' and rsi < 68) or
                (direction == 'SHORT' and rsi > 32)
            )
        )

        if strong:
            quality = 'STRONG SETUP'

        elif adjusted_score >= 6:
            quality = 'MODERATE SETUP'

        else:
            quality = 'VALID SETUP'

        # Low volume is explicitly reflected.
        if volume_ratio < 1.05:
            quality = 'MODERATE SETUP'

        return {
            'valid': True,
            'score': int(adjusted_score),
            'quality': quality,
            'reason': 'VALID'
        }

    # =========================================================
    # MAIN ANALYSIS
    # =========================================================

    def evaluate_strategy(self, symbol):

        try:
            df4h = self._fetch_ohlcv(
                symbol,
                '4h',
                220
            )

            df1h = self._fetch_ohlcv(
                symbol,
                '1h',
                220
            )

            df15 = self._fetch_ohlcv(
                symbol,
                '15m',
                220
            )

            if (
                df4h is None or
                df1h is None or
                df15 is None
            ):
                return self._no_trade(
                    symbol,
                    reason='INSUFFICIENT DATA'
                )

            df4h = self._prepare(df4h)
            df1h = self._prepare(df1h)
            df15 = self._prepare(df15)

            trend4h = self.get_trend(df4h)
            trend1h = self.get_trend(df1h)

            if trend4h == 'BULLISH':
                direction = 'LONG'

            elif trend4h == 'BEARISH':
                direction = 'SHORT'

            else:
                # If 4H is neutral, allow 1H to decide
                # only when 1H has a clear direction.
                if trend1h == 'BULLISH':
                    direction = 'LONG'
                elif trend1h == 'BEARISH':
                    direction = 'SHORT'
                else:
                    return self._no_trade(
                        symbol,
                        reason='NO CLEAR HIGHER TIMEFRAME TREND'
                    )

            structure_data = self.get_structure(
                df15,
                direction
            )

            momentum = self.get_momentum(
                df15,
                direction
            )

            volume_ratio = float(
                df15.iloc[-2]['volume_ratio']
            )

            volume_confirmation = (
                volume_ratio >= 1.05
            )

            displacement = self.get_displacement(
                df15,
                direction
            )

            fvg = self.detect_fvg(
                df15,
                direction
            )

            order_block = self.detect_order_block(
                df15,
                direction
            )

            btc_context = self.get_btc_context()

            rsi = float(
                df15.iloc[-2]['rsi']
            )

            levels = self.build_levels(
                df15,
                direction
            )

            confirmations = self.build_confirmations(
                direction=direction,
                trend4h=trend4h,
                trend1h=trend1h,
                structure_data=structure_data,
                momentum=momentum,
                volume_confirmation=volume_confirmation,
                displacement=displacement,
                fvg=fvg,
                order_block=order_block,
                btc_context=btc_context
            )

            quality = self.evaluate_quality(
                direction=direction,
                trend4h=trend4h,
                trend1h=trend1h,
                btc_context=btc_context,
                rsi=rsi,
                volume_ratio=volume_ratio,
                structure_data=structure_data,
                momentum=momentum,
                displacement=displacement,
                fvg=fvg,
                order_block=order_block,
                levels=levels,
                confirmations=confirmations
            )

            # =================================================
            # REJECTED
            # =================================================

            if not quality['valid']:

                return {
                    'symbol': symbol,
                    'decision': 'NO TRADE',
                    'score': int(
                        quality.get('score', 0)
                    ),
                    'quality': 'NO TRADE',

                    'confirmations': 'NONE',
                    'confirmation_list': [],
                    'confirmation_count': 0,

                    'trend_4h': trend4h,
                    'trend_1h': trend1h,

                    'btc_context': btc_context,

                    'btc_conflict': (
                        (
                            direction == 'LONG' and
                            btc_context == 'BEARISH'
                        ) or
                        (
                            direction == 'SHORT' and
                            btc_context == 'BULLISH'
                        )
                    ),

                    'btc_aligned': (
                        (
                            direction == 'LONG' and
                            btc_context == 'BULLISH'
                        ) or
                        (
                            direction == 'SHORT' and
                            btc_context == 'BEARISH'
                        )
                    ),

                    'rsi_15m': round(
                        rsi,
                        1
                    ),

                    'volume_ratio': round(
                        volume_ratio,
                        2
                    ),

                    'entry': None,
                    'sl': None,
                    'tp1': None,
                    'tp2': None,
                    'tp3': None,

                    'risk_pct': None,
                    'risk_filter': 'FAIL',

                    'structure_confirmation': 'FAIL',

                    'bos': structure_data['bos'],
                    'liquidity_sweep':
                        structure_data['liquidity_sweep'],

                    'structure':
                        structure_data['structure'],

                    'momentum': momentum,
                    'volume_confirmation':
                        volume_confirmation,

                    'displacement': displacement,
                    'fvg': fvg,
                    'order_block': order_block,

                    'entry_quality': 'REJECTED',

                    'message': quality['reason']
                }

            # =================================================
            # VALID TRADE
            # =================================================

            risk_pct = levels['risk_pct']

            entry_status = 'VALID'

            if volume_ratio < 1.05:
                entry_status = 'VALID - LOW VOLUME'

            confirmations_text = ', '.join(
                confirmations
            )

            return {
                'symbol': symbol,

                'decision': direction,

                'score': int(
                    quality['score']
                ),

                'quality': quality['quality'],

                # Main field
                'confirmations':
                    confirmations_text,

                # Compatibility aliases
                'confirmation_list':
                    confirmations,

                'confirmation_count':
                    len(confirmations),

                'trend_4h': trend4h,
                'trend_1h': trend1h,

                'btc_context': btc_context,

                'btc_conflict': (
                    (
                        direction == 'LONG' and
                        btc_context == 'BEARISH'
                    ) or
                    (
                        direction == 'SHORT' and
                        btc_context == 'BULLISH'
                    )
                ),

                'btc_aligned': (
                    (
                        direction == 'LONG' and
                        btc_context == 'BULLISH'
                    ) or
                    (
                        direction == 'SHORT' and
                        btc_context == 'BEARISH'
                    )
                ),

                'rsi_15m': round(
                    rsi,
                    1
                ),

                'volume_ratio': round(
                    volume_ratio,
                    2
                ),

                'entry': levels['entry'],
                'sl': levels['sl'],
                'tp1': levels['tp1'],
                'tp2': levels['tp2'],
                'tp3': levels['tp3'],

                'risk_pct': round(
                    risk_pct,
                    2
                ),

                'risk_filter': 'PASS',

                'structure_confirmation':
                    'PASS',

                'bos':
                    structure_data['bos'],

                'liquidity_sweep':
                    structure_data['liquidity_sweep'],

                'structure':
                    structure_data['structure'],

                'momentum':
                    momentum,

                'volume_confirmation':
                    volume_confirmation,

                'displacement':
                    displacement,

                'fvg':
                    fvg,

                'order_block':
                    order_block,

                'entry_quality':
                    entry_status,

                'message':
                    'VALID SETUP'
            }

        except Exception as e:

            logger.exception(
                "Analysis error for %s",
                symbol
            )

            return self._no_trade(
                symbol,
                reason=f'ANALYSIS ERROR: {e}'
            )

    # =========================================================
    # NO TRADE HELPER
    # =========================================================

    def _no_trade(
        self,
        symbol,
        reason='NO SETUP'
    ):
        return {
            'symbol': symbol,
            'decision': 'NO TRADE',
            'score': 0,
            'quality': 'NO TRADE',

            'confirmations': 'NONE',
            'confirmation_list': [],
            'confirmation_count': 0,

            'trend_4h': 'NEUTRAL',
            'trend_1h': 'NEUTRAL',

            'btc_context': 'NEUTRAL',
            'btc_conflict': False,
            'btc_aligned': False,

            'rsi_15m': None,
            'volume_ratio': None,

            'entry': None,
            'sl': None,
            'tp1': None,
            'tp2': None,
            'tp3': None,

            'risk_pct': None,
            'risk_filter': 'N/A',

            'structure_confirmation': 'FAIL',

            'bos': False,
            'liquidity_sweep': False,
            'structure': 'NEUTRAL',

            'momentum': False,
            'volume_confirmation': False,
            'displacement': False,
            'fvg': False,
            'order_block': False,

            'entry_quality': 'REJECTED',

            'message': reason
        }

    # =========================================================
    # PUBLIC METHOD
    # =========================================================

    def analyze(self, symbol):
        return self.evaluate_strategy(symbol)

    def get_coin_analysis(self, symbol):
        return self.evaluate_strategy(symbol)

    def get_analysis(self, symbol):
        return self.evaluate_strategy(symbol)
