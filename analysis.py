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
    # BASIC DATA
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

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()

        tr = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = tr.rolling(14).mean()

        df['vol_ma'] = df['volume'].rolling(20).mean()

        df['volume_ratio'] = (
            df['volume'] /
            df['vol_ma'].replace(0, np.nan)
        )

        df['body'] = (
            df['close'] - df['open']
        ).abs()

        df['body_atr'] = (
            df['body'] /
            df['atr'].replace(0, np.nan)
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
    # MARKET STRUCTURE
    # =========================================================

    def get_structure(self, df):
        if df is None or len(df) < 40:
            return {
                'structure': 'NEUTRAL',
                'bos': False,
                'liquidity_sweep': False
            }

        x = df.iloc[:-1].copy()

        last = x.iloc[-1]

        previous_high = x['high'].iloc[-13:-1].max()
        previous_low = x['low'].iloc[-13:-1].min()

        bos_long = (
            last['close'] > previous_high
        )

        bos_short = (
            last['close'] < previous_low
        )

        sweep_long = (
            last['low'] < previous_low and
            last['close'] > previous_low
        )

        sweep_short = (
            last['high'] > previous_high and
            last['close'] < previous_high
        )

        half = max(8, len(x) // 2)

        first = x.iloc[-half:-half // 2]
        second = x.iloc[-half // 2:]

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

        bullish_candle = (
            row['close'] > row['open']
        )

        bearish_candle = (
            row['close'] < row['open']
        )

        if direction == 'LONG':
            return (
                50 <= rsi <= 72 and
                bullish_candle and
                body_atr >= 0.30
            )

        if direction == 'SHORT':
            return (
                28 <= rsi <= 50 and
                bearish_candle and
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

        return ratio >= 1.10, ratio

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
                row['close'] > row['open'] and
                body_atr >= 0.55
            )

        if direction == 'SHORT':
            return (
                row['close'] < row['open'] and
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

        # نفحص آخر 12 شمعة مغلقة
        start = max(2, len(x) - 14)

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
            b = x.iloc[i - 1]
            c = x.iloc[i]

            # Bullish FVG
            if direction == 'LONG':
                if c['low'] > a['high']:

                    low_zone = float(a['high'])
                    high_zone = float(c['low'])

                    distance = min(
                        abs(current_price - low_zone),
                        abs(current_price - high_zone)
                    )

                    # لازم تكون المنطقة قريبة من السعر
                    if distance <= atr * 1.5:

                        best = {
                            'low': low_zone,
                            'high': high_zone
                        }

            # Bearish FVG
            if direction == 'SHORT':
                if c['high'] < a['low']:

                    low_zone = float(c['high'])
                    high_zone = float(a['low'])

                    distance = min(
                        abs(current_price - low_zone),
                        abs(current_price - high_zone)
                    )

                    if distance <= atr * 1.5:

                        best = {
                            'low': low_zone,
                            'high': high_zone
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

        if not np.isfinite(current_atr):
            return False, None

        start = max(
            2,
            len(x) - 15
        )

        best = None

        for i in range(start, len(x) - 1):

            candle = x.iloc[i]
            next_candle = x.iloc[i + 1]

            candle_range = (
                candle['high'] -
                candle['low']
            )

            if candle_range <= 0:
                continue

            # LONG:
            # آخر شمعة هابطة قبل displacement صاعد
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
                        abs(current_price - zone_low),
                        abs(current_price - zone_high)
                    )

                    # OB لازم يكون قريب
                    if distance <= current_atr * 1.75:

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

            # SHORT:
            # آخر شمعة صاعدة قبل displacement هابط
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
                        abs(current_price - zone_low),
                        abs(current_price - zone_high)
                    )

                    if distance <= current_atr * 1.75:

                        best = {
                            'low': zone_low,
                            'high': zone_high
                        }

        return (
            best is not None,
            best
        )

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def get_btc_context(self):
        try:
            btc_symbol = 'BTC/USDT:USDT'

            df = self.fetch_ohlcv(
                btc_symbol,
                '1h',
                150
            )

            if df is None:
                return 'UNKNOWN'

            df = self.add_indicators(df)

            trend = self.get_trend(df)

            return trend

        except Exception as e:
            logger.warning(
                "BTC context error: %s",
                e
            )

            return 'UNKNOWN'

    # =========================================================
    # LEVELS / RISK
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

        if not np.isfinite(atr) or atr <= 0:
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
                risk /
                entry
            ) * 100

            # لا نسمح بمخاطرة طبيعية ضخمة
            if risk_pct > 7.0:
                return None

            # حد أدنى معقول
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
                risk /
                entry
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
    # QUALITY FILTER
    # =========================================================

    def evaluate_quality(
        self,
        direction,
        score,
        confirmations,
        rsi,
        volume_ratio,
        btc_conflict,
        risk_pct,
        bos,
        displacement,
        fvg,
        order_block
    ):
        # =========================================
        # HARD REJECTIONS
        # =========================================

        if direction == 'LONG':
            if rsi >= 78:
                return False, 'RSI OVERHEATED'

        if direction == 'SHORT':
            if rsi <= 22:
                return False, 'RSI OVERSOLD'

        if risk_pct > 7.0:
            return False, 'RISK TOO WIDE'

        # لازم يكون فيه دليل هيكلي حقيقي
        structural = (
            bos or
            displacement or
            fvg
        )

        if not structural:
            return False, 'NO STRUCTURAL CONFIRMATION'

        if confirmations < 3:
            return False, 'INSUFFICIENT CONFIRMATION'

        # =========================================
        # SCORE ADJUSTMENTS
        # =========================================

        adjusted_score = score

        # RSI danger zone
        if direction == 'LONG':
            if rsi >= 75:
                adjusted_score -= 2
            elif rsi >= 72:
                adjusted_score -= 1

        if direction == 'SHORT':
            if rsi <= 25:
                adjusted_score -= 2
            elif rsi <= 28:
                adjusted_score -= 1

        # weak volume
        if volume_ratio < 1.05:
            adjusted_score -= 1

        # BTC conflict
        if btc_conflict:
            adjusted_score -= 1

        # wide risk
        if risk_pct >= 6.0:
            adjusted_score -= 1

        # =========================================
        # CRITICAL COMBINATION FILTER
        # =========================================

        # لو BTC ضد الصفقة + الحجم ضعيف
        # لازم يكون عندنا هيكل أقوى
        if (
            btc_conflict and
            volume_ratio < 1.05
        ):

            strong_structure_count = sum([
                bool(bos),
                bool(displacement),
                bool(fvg),
                bool(order_block)
            ])

            if strong_structure_count < 3:
                return False, 'BTC CONFLICT + WEAK VOLUME'

        # OB وحده لا يكفي
        if (
            order_block and
            not bos and
            not displacement and
            not fvg
        ):
            return False, 'ORDER BLOCK ALONE'

        # =========================================
        # FINAL
        # =========================================

        if adjusted_score < 5:
            return False, 'SCORE BELOW THRESHOLD'

        return True, adjusted_score

    # =========================================================
    # MAIN ANALYSIS
    # =========================================================

    def evaluate_strategy(self, symbol):

        try:

            # -------------------------------------
            # DATA
            # -------------------------------------

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

            # -------------------------------------
            # TRENDS
            # -------------------------------------

            trend4h = self.get_trend(df4h)
            trend1h = self.get_trend(df1h)

            structure1h = self.get_structure(df1h)
            structure15 = self.get_structure(df15)

            # -------------------------------------
            # BTC
            # -------------------------------------

            btc_context = self.get_btc_context()

            # -------------------------------------
            # DIRECTION VOTES
            # -------------------------------------

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

            # -------------------------------------
            # HARD 4H DIRECTION
            # -------------------------------------

            if trend4h == 'BULLISH':
                direction = 'LONG'

            elif trend4h == 'BEARISH':
                direction = 'SHORT'

            else:
                return None

            # -------------------------------------
            # 15M DATA
            # -------------------------------------

            row15 = df15.iloc[-2]

            rsi = float(
                row15['rsi']
            )

            volume_ok, volume_ratio = (
                self.get_volume_confirmation(
                    df15
                )
            )

            # -------------------------------------
            # STRUCTURE
            # -------------------------------------

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

            # -------------------------------------
            # MOMENTUM
            # -------------------------------------

            momentum = self.get_momentum(
                df15,
                direction
            )

            displacement = self.get_displacement(
                df15,
                direction
            )

            # -------------------------------------
            # FVG / OB
            # -------------------------------------

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

            # -------------------------------------
            # SCORE
            # -------------------------------------

            score = 0
            confirmations = []

            # Trend
            if (
                direction == 'LONG' and
                trend4h == 'BULLISH'
            ):
                score += 2
                confirmations.append(
                    '4H TREND'
                )

            elif (
                direction == 'SHORT' and
                trend4h == 'BEARISH'
            ):
                score += 2
                confirmations.append(
                    '4H TREND'
                )

            if (
                direction == 'LONG' and
                trend1h == 'BULLISH'
            ):
                score += 1
                confirmations.append(
                    '1H TREND'
                )

            elif (
                direction == 'SHORT' and
                trend1h == 'BEARISH'
            ):
                score += 1
                confirmations.append(
                    '1H TREND'
                )

            # Structure
            if (
                direction == 'LONG' and
                structure_name in (
                    'HH/HL',
                    'BULLISH BOS'
                )
            ):
                score += 1
                confirmations.append(
                    'STRUCTURE'
                )

            elif (
                direction == 'SHORT' and
                structure_name in (
                    'LH/LL',
                    'BEARISH BOS'
                )
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

            # BTC
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

            # -------------------------------------
            # LEVELS
            # -------------------------------------

            levels = self.build_levels(
                df15,
                direction
            )

            if levels is None:
                return None

            risk_pct = levels['risk_pct']

            # -------------------------------------
            # QUALITY FILTER
            # -------------------------------------

            quality_ok, quality_result = (
                self.evaluate_quality(
                    direction=direction,
                    score=score,
                    confirmations=len(confirmations),
                    rsi=rsi,
                    volume_ratio=volume_ratio,
                    btc_conflict=btc_conflict,
                    risk_pct=risk_pct,
                    bos=bos,
                    displacement=displacement,
                    fvg=fvg_ok,
                    order_block=ob_ok
                )
            )

            if not quality_ok:
                return None

            adjusted_score = (
                quality_result
                if isinstance(
                    quality_result,
                    int
                )
                else score
            )

            # -------------------------------------
            # QUALITY LABEL
            # -------------------------------------

            if (
                adjusted_score >= 8 and
                len(confirmations) >= 5 and
                not btc_conflict and
                volume_ratio >= 1.10 and
                risk_pct < 6.0 and
                rsi < 72
            ):
                quality = 'STRONG SETUP'

            elif (
                adjusted_score >= 6 and
                len(confirmations) >= 4
            ):
                quality = 'VALID SETUP'

            else:
                quality = 'MODERATE SETUP'

            # -------------------------------------
            # ENTRY STATUS
            # -------------------------------------

            if btc_conflict:
                entry_quality = (
                    'BTC CONFLICT - REDUCED CONFIDENCE'
                )

            elif risk_pct >= 6.0:
                entry_quality = (
                    'WIDE RISK - REDUCED CONFIDENCE'
                )

            elif rsi >= 75 and direction == 'LONG':
                entry_quality = (
                    'RSI HIGH - AVOID CHASING'
                )

            elif rsi <= 25 and direction == 'SHORT':
                entry_quality = (
                    'RSI LOW - AVOID CHASING'
                )

            else:
                entry_quality = 'GOOD'

            # -------------------------------------
            # RISK STATUS
            # -------------------------------------

            if risk_pct < 6.0:
                risk_filter = 'PASS'

            elif risk_pct <= 7.0:
                risk_filter = 'PASS - WIDE'

            else:
                risk_filter = 'FAIL'

            # -------------------------------------
            # MESSAGE
            # -------------------------------------

            btc_warning = (
                ' ⚠️ CONFLICT'
                if btc_conflict
                else ''
            )

            message = (
                f"🚨 EXPERT FUTURES SIGNAL 🚨\n\n"
                f"Symbol: {symbol}\n"
                f"Decision: {direction}\n"
                f"Score: {adjusted_score}\n"
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

                f"Risk: {risk_filter}\n"
                f"Entry Status: {entry_quality}"
            )

            # -------------------------------------
            # RETURN
            # -------------------------------------

            return {
                'symbol': symbol,
                'decision': direction,

                'score': int(adjusted_score),
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
