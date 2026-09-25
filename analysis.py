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
    # BASIC DATA
    # =========================================================

    def _cache_get(self, key):
        item = self.cache.get(key)

        if not item:
            return None

        timestamp, value = item

        if time.time() - timestamp <= self.cache_ttl:
            return value

        return None

    def _cache_set(self, key, value):
        self.cache[key] = (time.time(), value)

    def fetch_ohlcv(self, symbol, timeframe, limit=250):
        cache_key = f"{symbol}:{timeframe}:{limit}"

        cached = self._cache_get(cache_key)

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

            if len(df) < 80:
                return None

            self._cache_set(cache_key, df)

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

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()

        true_range = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = true_range.rolling(14).mean()

        df['volume_ma'] = df['volume'].rolling(20).mean()

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma'].replace(0, np.nan)
        )

        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['body_atr'] = (
            df['body'] /
            df['atr'].replace(0, np.nan)
        )

        df['bullish_candle'] = (
            df['close'] > df['open']
        )

        df['bearish_candle'] = (
            df['close'] < df['open']
        )

        return df

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 10:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = row['close']
        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

        bullish = (
            close > ema20 > ema50 > ema200
            or
            (
                close > ema50
                and ema20 > ema50
                and ema50 > ema200
            )
        )

        bearish = (
            close < ema20 < ema50 < ema200
            or
            (
                close < ema50
                and ema20 < ema50
                and ema50 < ema200
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

        if df is None or len(df) < 30:
            return result

        x = df.iloc[:-1].tail(24).copy()

        if len(x) < 12:
            return result

        current = x.iloc[-1]

        recent_high = x['high'].iloc[:-3].max()
        recent_low = x['low'].iloc[:-3].min()

        previous_high = x['high'].iloc[-10:-4].max()
        previous_low = x['low'].iloc[-10:-4].min()

        last_high = x['high'].iloc[-1]
        last_low = x['low'].iloc[-1]
        last_close = x['close'].iloc[-1]

        if direction == 'LONG':

            result['bos'] = (
                last_close > recent_high
                or
                last_close > previous_high
            )

            result['liquidity_sweep'] = (
                last_low < recent_low
                and
                last_close > recent_low
            )

            first_half = x.iloc[:len(x) // 2]
            second_half = x.iloc[len(x) // 2:]

            higher_high = (
                second_half['high'].max()
                > first_half['high'].max()
            )

            higher_low = (
                second_half['low'].min()
                > first_half['low'].min()
            )

            result['hh_hl'] = (
                higher_high and higher_low
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
                last_close < recent_low
                or
                last_close < previous_low
            )

            result['liquidity_sweep'] = (
                last_high > recent_high
                and
                last_close < recent_high
            )

            first_half = x.iloc[:len(x) // 2]
            second_half = x.iloc[len(x) // 2:]

            lower_high = (
                second_half['high'].max()
                < first_half['high'].max()
            )

            lower_low = (
                second_half['low'].min()
                < first_half['low'].min()
            )

            result['lh_ll'] = (
                lower_high and lower_low
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

        atr = float(current['atr'])
        price = float(current['close'])

        if atr <= 0:
            return False

        start = max(2, len(df) - 18)
        end = len(df) - 1

        for i in range(start, end):
            a = df.iloc[i - 1]
            b = df.iloc[i]
            c = df.iloc[i + 1]

            if direction == 'LONG':

                if c['low'] > a['high']:

                    zone_mid = (
                        c['low'] +
                        a['high']
                    ) / 2

                    distance = abs(
                        price - zone_mid
                    )

                    if distance <= atr * 1.50:
                        return True

            else:

                if c['high'] < a['low']:

                    zone_mid = (
                        c['high'] +
                        a['low']
                    ) / 2

                    distance = abs(
                        price - zone_mid
                    )

                    if distance <= atr * 1.50:
                        return True

        return False

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if df is None or len(df) < 30:
            return False

        current = df.iloc[-2]

        price = float(current['close'])
        atr = float(current['atr'])

        if atr <= 0:
            return False

        start = max(3, len(df) - 18)
        end = len(df) - 3

        for i in range(start, end):
            candle = df.iloc[i]
            next1 = df.iloc[i + 1]
            next2 = df.iloc[i + 2]

            if direction == 'LONG':

                if candle['bearish_candle']:

                    displacement = (
                        next1['bullish_candle']
                        and
                        next1['body_atr'] >= 0.45
                    )

                    break_up = (
                        next2['close']
                        > candle['high']
                    )

                    if displacement and break_up:

                        zone_mid = (
                            candle['open'] +
                            candle['close']
                        ) / 2

                        if abs(
                            price - zone_mid
                        ) <= atr * 1.75:
                            return True

            else:

                if candle['bullish_candle']:

                    displacement = (
                        next1['bearish_candle']
                        and
                        next1['body_atr'] >= 0.45
                    )

                    break_down = (
                        next2['close']
                        < candle['low']
                    )

                    if displacement and break_down:

                        zone_mid = (
                            candle['open'] +
                            candle['close']
                        ) / 2

                        if abs(
                            price - zone_mid
                        ) <= atr * 1.75:
                            return True

        return False

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def get_btc_context(self):
        try:
            btc = self.fetch_ohlcv(
                'BTC/USDT:USDT',
                '1h',
                150
            )

            if btc is None:
                return 'NEUTRAL'

            btc = self.add_indicators(btc)

            return self.get_trend(btc)

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
        if df is None or len(df) < 40:
            return None

        x = df.iloc[:-1].copy()

        current = x.iloc[-1]

        entry = float(current['close'])
        atr = float(current['atr'])

        if not np.isfinite(entry) or not np.isfinite(atr):
            return None

        if atr <= 0:
            return None

        recent = x.tail(20)

        swing_high = float(
            recent['high'].max()
        )

        swing_low = float(
            recent['low'].min()
        )

        if direction == 'LONG':

            swing_sl = (
                swing_low -
                atr * 0.25
            )

            atr_sl = (
                entry -
                atr * 1.25
            )

            sl = min(
                swing_sl,
                atr_sl
            )

            risk = entry - sl

            if risk <= 0:
                return None

            # لا نسمح بوقف ضيق جدًا
            min_risk = entry * 0.008

            if risk < min_risk:
                sl = entry - min_risk
                risk = entry - sl

            risk_pct = (
                risk /
                entry *
                100
            )

            if risk_pct > 7.0:
                return None

            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5.0

        else:

            swing_sl = (
                swing_high +
                atr * 0.25
            )

            atr_sl = (
                entry +
                atr * 1.25
            )

            sl = max(
                swing_sl,
                atr_sl
            )

            risk = sl - entry

            if risk <= 0:
                return None

            min_risk = entry * 0.008

            if risk < min_risk:
                sl = entry + min_risk
                risk = sl - entry

            risk_pct = (
                risk /
                entry *
                100
            )

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
    # QUALITY ENGINE
    # =========================================================

    def evaluate_quality(
        self,
        direction,
        trend_4h,
        trend_1h,
        btc_context,
        btc_conflict,
        rsi,
        volume_ratio,
        structure,
        bos,
        sweep,
        momentum,
        displacement,
        fvg,
        ob,
        levels
    ):

        if levels is None:
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': 0,
                'reason': 'INVALID LEVELS'
            }

        risk_pct = float(
            levels['risk_pct']
        )

        # -----------------------------------------------------
        # HARD PROTECTION
        # -----------------------------------------------------

        if direction == 'LONG':

            if rsi >= 75:
                return {
                    'valid': False,
                    'quality': 'NO TRADE',
                    'score': 0,
                    'reason': 'LONG RSI TOO EXTENDED'
                }

        else:

            if rsi <= 25:
                return {
                    'valid': False,
                    'quality': 'NO TRADE',
                    'score': 0,
                    'reason': 'SHORT RSI TOO EXTENDED'
                }

        if risk_pct > 7:
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': 0,
                'reason': 'RISK TOO WIDE'
            }

        # -----------------------------------------------------
        # STRUCTURAL MINIMUM
        # -----------------------------------------------------

        structural_evidence = (
            bos
            or
            sweep
            or
            displacement
            or
            fvg
        )

        if not structural_evidence:
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': 0,
                'reason': 'NO REAL STRUCTURAL EVIDENCE'
            }

        # -----------------------------------------------------
        # INDEPENDENT CONFIRMATION GROUPS
        #
        # 1 = Trend
        # 2 = Structure
        # 3 = Momentum
        # 4 = Volume
        # 5 = Location
        # -----------------------------------------------------

        groups = 0

        trend_group = (
            trend_4h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            )
            or
            trend_1h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            )
        )

        structure_group = (
            structure
            or
            bos
            or
            sweep
        )

        momentum_group = (
            momentum
            or
            displacement
        )

        volume_group = (
            volume_ratio >= 1.10
        )

        location_group = (
            fvg
            or
            ob
        )

        if trend_group:
            groups += 1

        if structure_group:
            groups += 1

        if momentum_group:
            groups += 1

        if volume_group:
            groups += 1

        if location_group:
            groups += 1

        # -----------------------------------------------------
        # RAW SCORE
        # -----------------------------------------------------

        score = 0

        if trend_4h == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):
            score += 2

        if trend_1h == (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        ):
            score += 1

        if structure:
            score += 1

        if bos:
            score += 2

        if sweep:
            score += 1

        if momentum:
            score += 1

        if volume_ratio >= 1.10:
            score += 1

        if displacement:
            score += 1

        if fvg:
            score += 1

        if ob:
            score += 1

        btc_aligned = (
            (
                direction == 'LONG'
                and btc_context == 'BULLISH'
            )
            or
            (
                direction == 'SHORT'
                and btc_context == 'BEARISH'
            )
        )

        if btc_aligned:
            score += 1

        # -----------------------------------------------------
        # PENALTIES
        # -----------------------------------------------------

        adjusted_score = score

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

        if volume_ratio < 0.80:
            adjusted_score -= 2

        elif volume_ratio < 1.05:
            adjusted_score -= 1

        if btc_conflict:
            adjusted_score -= 1

        if risk_pct >= 5:
            adjusted_score -= 1

        # -----------------------------------------------------
        # 4H / 1H CONFLICT
        # -----------------------------------------------------

        expected_trend = (
            'BULLISH'
            if direction == 'LONG'
            else 'BEARISH'
        )

        timeframe_conflict = (
            trend_4h == expected_trend
            and
            trend_1h != expected_trend
        )

        if timeframe_conflict:

            # تعارض 4H/1H لا يمر إلا بتعويض حقيقي
            compensation = 0

            if bos:
                compensation += 1

            if sweep:
                compensation += 1

            if displacement:
                compensation += 1

            if fvg:
                compensation += 1

            if momentum:
                compensation += 1

            if compensation < 3:
                return {
                    'valid': False,
                    'quality': 'NO TRADE',
                    'score': max(
                        0,
                        adjusted_score
                    ),
                    'reason':
                        '4H/1H CONFLICT WITHOUT '
                        'ENOUGH LOCAL COMPENSATION'
                }

            # لو الحجم ضعيف جدًا مع التعارض
            if volume_ratio < 0.80:

                if not (
                    bos
                    and
                    displacement
                    and
                    (
                        fvg
                        or
                        sweep
                    )
                ):
                    return {
                        'valid': False,
                        'quality': 'NO TRADE',
                        'score': max(
                            0,
                            adjusted_score
                        ),
                        'reason':
                            'TIMEFRAME CONFLICT + '
                            'VERY WEAK VOLUME'
                    }

        # -----------------------------------------------------
        # BTC CONFLICT
        # -----------------------------------------------------

        if btc_conflict:

            if volume_ratio < 0.80:

                if not (
                    bos
                    and
                    displacement
                    and
                    fvg
                    and
                    (
                        sweep
                        or
                        momentum
                    )
                ):
                    return {
                        'valid': False,
                        'quality': 'NO TRADE',
                        'score': max(
                            0,
                            adjusted_score
                        ),
                        'reason':
                            'BTC CONFLICT + '
                            'VERY WEAK VOLUME'
                    }

            compensation = 0

            if bos:
                compensation += 1

            if sweep:
                compensation += 1

            if displacement:
                compensation += 1

            if fvg:
                compensation += 1

            if momentum:
                compensation += 1

            # BTC conflict + RSI already stretched
            if direction == 'LONG' and rsi >= 72:
                return {
                    'valid': False,
                    'quality': 'NO TRADE',
                    'score': max(
                        0,
                        adjusted_score
                    ),
                    'reason':
                        'BTC CONFLICT + '
                        'LONG RSI TOO HIGH'
                }

            if direction == 'SHORT' and rsi <= 28:
                return {
                    'valid': False,
                    'quality': 'NO TRADE',
                    'score': max(
                        0,
                        adjusted_score
                    ),
                    'reason':
                        'BTC CONFLICT + '
                        'SHORT RSI TOO LOW'
                }

            # BTC conflict + weak volume
            if volume_ratio < 1.05:

                if compensation < 3:
                    return {
                        'valid': False,
                        'quality': 'NO TRADE',
                        'score': max(
                            0,
                            adjusted_score
                        ),
                        'reason':
                            'BTC CONFLICT + '
                            'WEAK VOLUME'
                    }

        # -----------------------------------------------------
        # ORDER BLOCK ALONE IS NOT ENOUGH
        # -----------------------------------------------------

        if ob and not (
            bos
            or
            sweep
            or
            displacement
            or
            fvg
            or
            momentum
        ):
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': max(
                    0,
                    adjusted_score
                ),
                'reason':
                    'ORDER BLOCK ALONE IS NOT ENOUGH'
            }

        # -----------------------------------------------------
        # MINIMUM INDEPENDENT GROUPS
        # -----------------------------------------------------

        if groups < 3:
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': max(
                    0,
                    adjusted_score
                ),
                'reason':
                    'LESS THAN 3 INDEPENDENT CONFIRMATION GROUPS'
            }

        # -----------------------------------------------------
        # SCORE FLOOR
        # -----------------------------------------------------

        if adjusted_score < 5:
            return {
                'valid': False,
                'quality': 'NO TRADE',
                'score': max(
                    0,
                    adjusted_score
                ),
                'reason':
                    'SCORE BELOW QUALITY THRESHOLD'
            }

        # -----------------------------------------------------
        # STRONG SETUP
        # -----------------------------------------------------

        strong = (
            adjusted_score >= 8
            and
            groups >= 4
            and
            trend_4h == expected_trend
            and
            trend_1h == expected_trend
            and
            btc_aligned
            and
            volume_ratio >= 1.10
            and
            risk_pct < 5.0
            and
            (
                rsi < 68
                if direction == 'LONG'
                else rsi > 32
            )
        )

        if strong:

            return {
                'valid': True,
                'quality': 'STRONG SETUP',
                'score': adjusted_score,
                'reason': 'HIGH CONFLUENCE',
                'groups': groups
            }

        # -----------------------------------------------------
        # VALID SETUP
        # -----------------------------------------------------

        if adjusted_score >= 5 and groups >= 3:

            # ظروف تقلل الجودة
            weak_environment = (
                btc_conflict
                or
                volume_ratio < 1.05
                or
                risk_pct >= 5.0
                or
                (
                    direction == 'LONG'
                    and rsi >= 70
                )
                or
                (
                    direction == 'SHORT'
                    and rsi <= 30
                )
            )

            if weak_environment:

                compensation = 0

                if bos:
                    compensation += 1

                if sweep:
                    compensation += 1

                if displacement:
                    compensation += 1

                if fvg:
                    compensation += 1

                if momentum:
                    compensation += 1

                if compensation < 3:
                    return {
                        'valid': False,
                        'quality': 'NO TRADE',
                        'score': max(
                            0,
                            adjusted_score
                        ),
                        'reason':
                            'VALID SCORE BUT '
                            'INSUFFICIENT COMPENSATION'
                    }

                return {
                    'valid': True,
                    'quality': 'MODERATE SETUP',
                    'score': adjusted_score,
                    'reason':
                        'VALID WITH RISK FACTORS',
                    'groups': groups
                }

            return {
                'valid': True,
                'quality': 'VALID SETUP',
                'score': adjusted_score,
                'reason': 'QUALITY THRESHOLD PASSED',
                'groups': groups
            }

        return {
            'valid': False,
            'quality': 'NO TRADE',
            'score': max(
                0,
                adjusted_score
            ),
            'reason': 'SETUP NOT STRONG ENOUGH'
        }

    # =========================================================
    # MAIN STRATEGY
    # =========================================================

    def evaluate_strategy(self, symbol):
        try:

            df4h = self.fetch_ohlcv(
                symbol,
                '4h',
                250
            )

            df1h = self.fetch_ohlcv(
                symbol,
                '1h',
                250
            )

            df15 = self.fetch_ohlcv(
                symbol,
                '15m',
                250
            )

            if (
                df4h is None
                or
                df1h is None
                or
                df15 is None
            ):
                return None

            df4h = self.add_indicators(df4h)
            df1h = self.add_indicators(df1h)
            df15 = self.add_indicators(df15)

            trend_4h = self.get_trend(df4h)
            trend_1h = self.get_trend(df1h)

            # الاتجاه الرئيسي من 4H
            if trend_4h == 'BULLISH':
                direction = 'LONG'

            elif trend_4h == 'BEARISH':
                direction = 'SHORT'

            else:
                return None

            structure4 = self.get_structure(
                df4h,
                direction
            )

            structure1 = self.get_structure(
                df1h,
                direction
            )

            structure15 = self.get_structure(
                df15,
                direction
            )

            bos = (
                structure1['bos']
                or
                structure15['bos']
                or
                structure4['bos']
            )

            sweep = (
                structure15['liquidity_sweep']
                or
                structure1['liquidity_sweep']
            )

            structure = (
                structure1['structure']
                or
                structure15['structure']
                or
                structure4['structure']
            )

            momentum = self.get_momentum(
                df15,
                direction
            )

            volume_confirmation = (
                self.get_volume_confirmation(
                    df15
                )
            )

            displacement = (
                self.get_displacement(
                    df15,
                    direction
                )
            )

            fvg = self.detect_fvg(
                df15,
                direction
            )

            ob = self.detect_order_block(
                df15,
                direction
            )

            row15 = df15.iloc[-2]

            rsi = float(row15['rsi'])
            volume_ratio = float(
                row15['volume_ratio']
            )

            btc_context = (
                self.get_btc_context()
            )

            btc_aligned = (
                (
                    direction == 'LONG'
                    and
                    btc_context == 'BULLISH'
                )
                or
                (
                    direction == 'SHORT'
                    and
                    btc_context == 'BEARISH'
                )
            )

            btc_conflict = (
                (
                    direction == 'LONG'
                    and
                    btc_context == 'BEARISH'
                )
                or
                (
                    direction == 'SHORT'
                    and
                    btc_context == 'BULLISH'
                )
            )

            levels = self.build_levels(
                df15,
                direction
            )

            if levels is None:
                return None

            quality = self.evaluate_quality(
                direction=direction,
                trend_4h=trend_4h,
                trend_1h=trend_1h,
                btc_context=btc_context,
                btc_conflict=btc_conflict,
                rsi=rsi,
                volume_ratio=volume_ratio,
                structure=structure,
                bos=bos,
                sweep=sweep,
                momentum=momentum,
                displacement=displacement,
                fvg=fvg,
                ob=ob,
                levels=levels
            )

            if not quality['valid']:
                return {
                    'symbol': symbol,
                    'decision': 'NO TRADE',
                    'score': quality['score'],
                    'quality': 'NO TRADE',
                    'confirmations': '',
                    'confirmation_count': 0,
                    'trend_4h': trend_4h,
                    'trend_1h': trend_1h,
                    'btc_context': btc_context,
                    'btc_conflict': btc_conflict,
                    'btc_aligned': btc_aligned,
                    'rsi_15m': rsi,
                    'volume_ratio': volume_ratio,
                    'entry': None,
                    'sl': None,
                    'tp1': None,
                    'tp2': None,
                    'tp3': None,
                    'risk_pct': levels['risk_pct'],
                    'risk_filter': 'FAIL',
                    'structure_confirmation': 'FAIL',
                    'bos': bos,
                    'liquidity_sweep': sweep,
                    'structure': structure,
                    'momentum': momentum,
                    'volume_confirmation': volume_confirmation,
                    'displacement': displacement,
                    'fvg': fvg,
                    'order_block': ob,
                    'entry_quality': 'REJECTED',
                    'message': quality['reason']
                }

            # =================================================
            # CONFIRMATIONS
            #
            # هنا نعرض الأدلة الفعلية، وليس مجرد عدّ كل شيء.
            # =================================================

            confirmations = []

            if trend_4h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            ):
                confirmations.append('4H TREND')

            if trend_1h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            ):
                confirmations.append('1H TREND')

            if bos:
                confirmations.append('BOS')

            if sweep:
                confirmations.append('LIQUIDITY SWEEP')

            if momentum:
                confirmations.append('MOMENTUM')

            if displacement:
                confirmations.append('DISPLACEMENT')

            if fvg:
                confirmations.append('FVG')

            if ob:
                confirmations.append('ORDER BLOCK')

            if volume_confirmation:
                confirmations.append('VOLUME')

            if btc_aligned:
                confirmations.append('BTC ALIGNMENT')

            confirmation_count = len(
                confirmations
            )

            # =================================================
            # ENTRY STATUS
            # =================================================

            if quality['quality'] == 'STRONG SETUP':
                entry_status = 'STRONG'

            elif btc_conflict:

                if (
                    volume_ratio >= 1.50
                    and
                    displacement
                    and
                    (
                        bos
                        or
                        sweep
                    )
                ):
                    entry_status = (
                        'BTC CONFLICT - '
                        'STRONG LOCAL CONFIRMATION'
                    )

                elif (
                    displacement
                    and
                    bos
                    and
                    fvg
                    and
                    volume_ratio >= 1.05
                ):
                    entry_status = (
                        'BTC CONFLICT - '
                        'STRUCTURE COMPENSATES'
                    )

                else:
                    entry_status = (
                        'BTC CONFLICT - '
                        'REDUCED CONFIDENCE'
                    )

            elif volume_ratio < 1.05:
                entry_status = (
                    'VALID - LOW VOLUME'
                )

            elif levels['risk_pct'] >= 5:
                entry_status = (
                    'VALID - WIDE RISK'
                )

            else:
                entry_status = 'GOOD'

            # =================================================
            # FINAL RESULT
            # =================================================

            return {
                'symbol': symbol,
                'decision': direction,
                'score': quality['score'],
                'quality': quality['quality'],
                'confirmations': ', '.join(
                    confirmations
                ),
                'confirmation_count':
                    confirmation_count,

                'trend_4h': trend_4h,
                'trend_1h': trend_1h,

                'btc_context': btc_context,
                'btc_conflict': btc_conflict,
                'btc_aligned': btc_aligned,

                'rsi_15m': rsi,
                'volume_ratio': volume_ratio,

                'entry': levels['entry'],
                'sl': levels['sl'],
                'tp1': levels['tp1'],
                'tp2': levels['tp2'],
                'tp3': levels['tp3'],

                'risk_pct': levels['risk_pct'],

                'risk_filter': (
                    'PASS'
                    if levels['risk_pct'] <= 7
                    else 'FAIL'
                ),

                'structure_confirmation':
                    'PASS',

                'bos': bos,
                'liquidity_sweep': sweep,
                'structure': structure,
                'momentum': momentum,
                'volume_confirmation':
                    volume_confirmation,
                'displacement': displacement,
                'fvg': fvg,
                'order_block': ob,

                'entry_quality':
                    entry_status,

                'message':
                    quality['reason']
            }

        except Exception as e:

            logger.exception(
                "Strategy error for %s: %s",
                symbol,
                e
            )

            return None

    # =========================================================
    # PUBLIC ANALYSIS METHOD
    # =========================================================

    def analyze(self, symbol):
        return self.evaluate_strategy(symbol)

    def get_coin_analysis(self, symbol):
        return self.evaluate_strategy(symbol)

    def scan_market(self, symbols):
        results = []

        for symbol in symbols:

            try:
                result = self.evaluate_strategy(
                    symbol
                )

                if result is not None:
                    results.append(result)

            except Exception as e:
                logger.warning(
                    "Scan error %s: %s",
                    symbol,
                    e
                )

        return results
