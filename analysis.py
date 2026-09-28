import logging
import time
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    # =========================================================
    # INIT
    # =========================================================

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

        # OI sampling history
        self.oi_history = {}

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    def _decision_to_trend(self, decision):
        if decision == 'LONG':
            return 'BULLISH'
        if decision == 'SHORT':
            return 'BEARISH'
        return 'NEUTRAL'

    def _safe_float(self, value, default=0.0):
        try:
            value = float(value)
            if np.isfinite(value):
                return value
        except Exception:
            pass
        return default

    # =========================================================
    # DATA FETCH
    # =========================================================

    def _fetch_ohlcv(
        self,
        symbol,
        timeframe,
        limit=250,
        market_type='swap'
    ):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD',
            'CHF', 'NZD', 'NCFX', 'USDCUSD'
        ]

        symbol_upper = str(symbol).upper()

        if any(token in symbol_upper for token in unwanted_tokens):
            return None

        key = f"{symbol}:{market_type}:{timeframe}:{limit}"

        now = time.time()
        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            self.exchange.options['defaultType'] = (
                'spot' if market_type == 'spot' else 'swap'
            )

            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 50:
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

            numeric_cols = [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]

            for col in numeric_cols:
                df[col] = pd.to_numeric(
                    df[col],
                    errors='coerce'
                )

            df = (
                df
                .dropna()
                .drop_duplicates(subset=['timestamp'])
                .reset_index(drop=True)
            )

            if len(df) < 50:
                return None

            self.cache[key] = {
                'time': now,
                'data': df
            }

            return df.copy()

        except Exception as e:
            logger.warning(
                "OHLCV error %s (%s) %s: %s",
                symbol,
                market_type,
                timeframe,
                e
            )
            return None

    # =========================================================
    # DERIVATIVES / OI / FUNDING
    # =========================================================

    def _fetch_derivatives_metrics(
        self,
        symbol,
        current_price
    ):
        """
        OI is sampled every 180 seconds.

        Classification:
        Price ↑ + OI ↑ = LONG_BUILDUP
        Price ↓ + OI ↑ = SHORT_BUILDUP
        Price ↑ + OI ↓ = SHORT_COVERING
        Price ↓ + OI ↓ = LONG_LIQUIDATION
        """

        default = {
            'funding_rate': 0.0,
            'oi_current': 0.0,
            'oi_change_pct': 0.0,
            'price_change_pct': 0.0,
            'derivatives_bias': 'NEUTRAL'
        }

        try:
            swap_symbol = symbol

            if (
                '/' in symbol
                and ':' not in symbol
            ):
                swap_symbol = f"{symbol}:USDT"

            now = time.time()

            funding_rate = 0.0
            current_oi = 0.0

            # -------------------------------------------------
            # FUNDING
            # -------------------------------------------------

            try:
                funding = self.exchange.fetch_funding_rate(
                    swap_symbol
                )

                if funding:
                    rate = funding.get('fundingRate')

                    if rate is not None:
                        funding_rate = self._safe_float(rate)

            except Exception as e:
                logger.debug(
                    "Funding unavailable %s: %s",
                    swap_symbol,
                    e
                )

            # -------------------------------------------------
            # OPEN INTEREST
            # -------------------------------------------------

            try:
                oi_data = self.exchange.fetch_open_interest(
                    swap_symbol
                )

                if oi_data:
                    raw_oi = oi_data.get(
                        'openInterestAmount'
                    )

                    if raw_oi is None:
                        raw_oi = oi_data.get(
                            'openInterestValue'
                        )

                    if raw_oi is not None:
                        current_oi = self._safe_float(
                            raw_oi
                        )

            except Exception as e:
                logger.debug(
                    "OI unavailable %s: %s",
                    swap_symbol,
                    e
                )

            if current_oi <= 0:
                return {
                    **default,
                    'funding_rate': round(
                        funding_rate,
                        6
                    )
                }

            # -------------------------------------------------
            # INITIAL SAMPLE
            # -------------------------------------------------

            if swap_symbol not in self.oi_history:

                self.oi_history[swap_symbol] = {
                    'sample_oi': current_oi,
                    'sample_price': current_price,
                    'last_sample_time': now,
                    'oi_change_pct': 0.0,
                    'price_change_pct': 0.0
                }

                return {
                    'funding_rate': round(
                        funding_rate,
                        6
                    ),
                    'oi_current': current_oi,
                    'oi_change_pct': 0.0,
                    'price_change_pct': 0.0,
                    'derivatives_bias': 'NEUTRAL'
                }

            rec = self.oi_history[swap_symbol]

            elapsed = now - rec['last_sample_time']

            # -------------------------------------------------
            # NEW 180 SECOND SAMPLE
            # -------------------------------------------------

            if elapsed >= 180:

                old_oi = self._safe_float(
                    rec['sample_oi']
                )

                old_price = self._safe_float(
                    rec['sample_price']
                )

                oi_change_pct = 0.0
                price_change_pct = 0.0

                if old_oi > 0:
                    oi_change_pct = (
                        (current_oi - old_oi)
                        / old_oi
                    ) * 100.0

                if old_price > 0:
                    price_change_pct = (
                        (current_price - old_price)
                        / old_price
                    ) * 100.0

                # Save the completed paired sample
                self.oi_history[swap_symbol] = {
                    'sample_oi': current_oi,
                    'sample_price': current_price,
                    'last_sample_time': now,
                    'oi_change_pct': oi_change_pct,
                    'price_change_pct': price_change_pct
                }

            else:
                # Keep the LAST COMPLETED measurement.
                # Do not calculate a new OI change against stale
                # intermediate values.
                oi_change_pct = self._safe_float(
                    rec.get('oi_change_pct', 0.0)
                )

                price_change_pct = self._safe_float(
                    rec.get('price_change_pct', 0.0)
                )

            # -------------------------------------------------
            # CLASSIFICATION
            # -------------------------------------------------

            bias = 'NEUTRAL'

            if oi_change_pct > 0.20:

                if price_change_pct > 0.05:
                    bias = 'LONG_BUILDUP'

                elif price_change_pct < -0.05:
                    bias = 'SHORT_BUILDUP'

            elif oi_change_pct < -0.20:

                if price_change_pct > 0.05:
                    bias = 'SHORT_COVERING'

                elif price_change_pct < -0.05:
                    bias = 'LONG_LIQUIDATION'

            return {
                'funding_rate': round(
                    funding_rate,
                    6
                ),
                'oi_current': current_oi,
                'oi_change_pct': round(
                    oi_change_pct,
                    2
                ),
                'price_change_pct': round(
                    price_change_pct,
                    2
                ),
                'derivatives_bias': bias
            }

        except Exception as e:

            logger.debug(
                "Derivatives error %s: %s",
                symbol,
                e
            )

            return default

    # =========================================================
    # INDICATORS
    # =========================================================

    def _prepare(self, df):

        df = df.copy()

        df['ema20'] = (
            df['close']
            .ewm(span=20, adjust=False)
            .mean()
        )

        df['ema50'] = (
            df['close']
            .ewm(span=50, adjust=False)
            .mean()
        )

        df['ema200'] = (
            df['close']
            .ewm(span=200, adjust=False)
            .mean()
        )

        df['ema20_slope'] = (
            df['ema20'].diff(3)
        )

        df['ema50_slope'] = (
            df['ema50'].diff(3)
        )

        # -----------------------------------------------------
        # RSI
        # -----------------------------------------------------

        delta = df['close'].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1 / 14,
            adjust=False
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / 14,
            adjust=False
        ).mean()

        rs = (
            avg_gain /
            avg_loss.replace(0, np.nan)
        )

        df['rsi'] = (
            100 -
            (100 / (1 + rs))
        )

        df['rsi'] = df['rsi'].fillna(50)

        df['rsi_slope'] = (
            df['rsi'].diff(3)
        )

        # -----------------------------------------------------
        # ATR
        # -----------------------------------------------------

        prev_close = df['close'].shift(1)

        tr = pd.concat(
            [
                df['high'] - df['low'],
                (df['high'] - prev_close).abs(),
                (df['low'] - prev_close).abs()
            ],
            axis=1
        ).max(axis=1)

        df['atr'] = (
            tr
            .ewm(span=14, adjust=False)
            .mean()
        )

        # -----------------------------------------------------
        # VOLUME
        # -----------------------------------------------------

        df['volume_ma'] = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma'].replace(0, np.nan)
        )

        df['volume_ratio'] = (
            df['volume_ratio']
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .fillna(1.0)
        )

        # -----------------------------------------------------
        # CANDLE STRUCTURE
        # -----------------------------------------------------

        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['range'] = (
            df['high'] -
            df['low']
        ).replace(0, np.nan)

        df['body_ratio'] = (
            df['body'] /
            df['range']
        ).fillna(0)

        df['bullish_candle'] = (
            df['close'] > df['open']
        )

        df['bearish_candle'] = (
            df['close'] < df['open']
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
    # BTC CONTEXT
    # =========================================================

    def _get_btc_context(
        self,
        market_type='swap'
    ):

        try:

            btc_symbol = (
                'BTC/USDT:USDT'
                if market_type == 'swap'
                else 'BTC/USDT'
            )

            df_4h = self._fetch_ohlcv(
                btc_symbol,
                '4h',
                60,
                market_type
            )

            df_1h = self._fetch_ohlcv(
                btc_symbol,
                '1h',
                60,
                market_type
            )

            score = 0

            # 4H
            if df_4h is not None:

                df_4h = self._prepare(df_4h)

                if len(df_4h) >= 30:

                    l = df_4h.iloc[-1]

                    if (
                        l['close'] > l['ema20']
                        and l['ema20'] > l['ema50']
                        and l['ema20_slope'] > 0
                    ):
                        score += 3

                    elif (
                        l['close'] < l['ema20']
                        and l['ema20'] < l['ema50']
                        and l['ema20_slope'] < 0
                    ):
                        score -= 3

            # 1H
            if df_1h is not None:

                df_1h = self._prepare(df_1h)

                if len(df_1h) >= 30:

                    l = df_1h.iloc[-1]

                    if (
                        l['close'] > l['ema20']
                        and l['rsi'] >= 50
                    ):
                        score += 2

                    elif (
                        l['close'] < l['ema20']
                        and l['rsi'] <= 50
                    ):
                        score -= 2

            if score >= 3:
                return 'BTC_BULLISH'

            if score <= -3:
                return 'BTC_BEARISH'

            return 'BTC_NEUTRAL'

        except Exception:
            return 'BTC_NEUTRAL'

    # =========================================================
    # MARKET REGIME
    # =========================================================

    def _detect_market_regime(self, df):

        if df is None or len(df) < 30:
            return 'NEUTRAL'

        last = df.iloc[-1]

        if last['close'] <= 0:
            return 'NEUTRAL'

        atr_pct = (
            last['atr'] /
            last['close']
        ) * 100

        if atr_pct > 2.8:
            return 'HIGH_VOLATILITY'

        if atr_pct < 0.4:
            return 'LOW_VOLATILITY'

        if (
            last['close'] > last['ema20']
            > last['ema50']
            and last['ema20_slope'] > 0
        ):
            return 'TRENDING_BULLISH'

        if (
            last['close'] < last['ema20']
            < last['ema50']
            and last['ema20_slope'] < 0
        ):
            return 'TRENDING_BEARISH'

        return 'RANGING'

    # =========================================================
    # MULTI-TIMEFRAME TREND
    # =========================================================

    def _get_trend_external(
        self,
        symbol,
        timeframe,
        market_type
    ):

        df = self._fetch_ohlcv(
            symbol,
            timeframe,
            160,
            market_type
        )

        if df is None or len(df) < 50:
            return 'NEUTRAL', None

        df = self._prepare(df)

        last = df.iloc[-1]

        bullish = (
            last['close'] > last['ema20']
            and last['ema20'] > last['ema50']
            and last['ema20_slope'] > 0
            and last['rsi'] >= 50
        )

        bearish = (
            last['close'] < last['ema20']
            and last['ema20'] < last['ema50']
            and last['ema20_slope'] < 0
            and last['rsi'] <= 50
        )

        if bullish:
            return 'BULLISH', df

        if bearish:
            return 'BEARISH', df

        return 'NEUTRAL', df

    # =========================================================
    # SWING POINTS
    # =========================================================

    def _find_swing_points(
        self,
        df,
        window=4
    ):

        highs = []
        lows = []

        if df is None:
            return highs, lows

        if len(df) < (
            window * 2 + 5
        ):
            return highs, lows

        for i in range(
            window,
            len(df) - window
        ):

            high_window = df[
                'high'
            ].iloc[
                i - window:
                i + window + 1
            ]

            low_window = df[
                'low'
            ].iloc[
                i - window:
                i + window + 1
            ]

            current_high = float(
                df['high'].iloc[i]
            )

            current_low = float(
                df['low'].iloc[i]
            )

            if current_high >= high_window.max():
                highs.append(
                    (i, current_high)
                )

            if current_low <= low_window.min():
                lows.append(
                    (i, current_low)
                )

        return highs, lows

    # =========================================================
    # REAL MARKET STRUCTURE
    # =========================================================

    def detect_market_structure(self, df):

        if df is None or len(df) < 40:

            return (
                'NEUTRAL',
                False,
                False,
                False,
                'NORMAL_STRUCTURE'
            )

        highs, lows = self._find_swing_points(
            df,
            window=4
        )

        if len(highs) < 2 or len(lows) < 2:

            return (
                'NEUTRAL',
                False,
                False,
                False,
                'INSUFFICIENT_SWINGS'
            )

        # Last two confirmed highs/lows
        prev_high = highs[-2][1]
        last_high = highs[-1][1]

        prev_low = lows[-2][1]
        last_low = lows[-1][1]

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # -----------------------------------------------------
        # HH / HL / LH / LL
        # -----------------------------------------------------

        higher_high = last_high > prev_high
        higher_low = last_low > prev_low

        lower_high = last_high < prev_high
        lower_low = last_low < prev_low

        # Existing structural state
        if higher_high and higher_low:
            structure = 'BULLISH'

        elif lower_high and lower_low:
            structure = 'BEARISH'

        elif higher_high or higher_low:
            structure = 'BULLISH'

        elif lower_high or lower_low:
            structure = 'BEARISH'

        else:
            structure = 'NEUTRAL'

        # -----------------------------------------------------
        # BOS
        # -----------------------------------------------------

        bullish_break = (
            last['close'] > last_high
            and prev['close'] <= last_high
        )

        bearish_break = (
            last['close'] < last_low
            and prev['close'] >= last_low
        )

        bos = (
            bullish_break
            or bearish_break
        )

        # -----------------------------------------------------
        # MSS / CHoCH
        # -----------------------------------------------------

        mss = False
        choch = False

        structure_type = 'NORMAL_STRUCTURE'

        # Look at previous structural state
        if (
            len(highs) >= 3
            and len(lows) >= 3
        ):

            old_high = highs[-3][1]
            old_last_high = highs[-2][1]

            old_low = lows[-3][1]
            old_last_low = lows[-2][1]

            previously_bearish = (
                old_last_high < old_high
                and old_last_low < old_low
            )

            previously_bullish = (
                old_last_high > old_high
                and old_last_low > old_low
            )

            if (
                bullish_break
                and previously_bearish
            ):
                mss = True
                choch = True

            if (
                bearish_break
                and previously_bullish
            ):
                mss = True
                choch = True

        if bullish_break:

            structure = 'BULLISH'

            if mss:
                structure_type = 'BULLISH_MSS'
            else:
                structure_type = 'BULLISH_BOS'

        elif bearish_break:

            structure = 'BEARISH'

            if mss:
                structure_type = 'BEARISH_MSS'
            else:
                structure_type = 'BEARISH_BOS'

        elif structure == 'BULLISH':

            structure_type = 'BULLISH_STRUCTURE'

        elif structure == 'BEARISH':

            structure_type = 'BEARISH_STRUCTURE'

        return (
            structure,
            bos,
            mss,
            choch,
            structure_type
        )

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def _has_displacement(
        self,
        df,
        direction
    ):

        if df is None or len(df) < 5:
            return False

        row = df.iloc[-1]

        directional_candle = (
            row['bullish_candle']
            if direction == 'LONG'
            else row['bearish_candle']
        )

        return (
            directional_candle
            and row['body_ratio'] >= 0.55
            and row['volume_ratio'] >= 1.20
            and row['range'] >= row['atr'] * 0.75
        )

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def detect_advanced_liquidity_sweep(
        self,
        df,
        direction
    ):

        result = {
            'passed': False,
            'type': 'NO_SWEEP'
        }

        if df is None or len(df) < 25:
            return result

        highs, lows = self._find_swing_points(
            df,
            window=3
        )

        if not highs or not lows:
            return result

        last = df.iloc[-1]
        prev = df.iloc[-2]

        recent_high = highs[-1][1]
        recent_low = lows[-1][1]

        displacement = (
            last['body_ratio'] >= 0.55
            and last['volume_ratio'] >= 1.20
            and last['range'] >= last['atr'] * 0.75
        )

        if not displacement:
            return result

        if direction == 'LONG':

            swept = (
                last['low'] < recent_low
            )

            reclaimed = (
                last['close'] > recent_low
            )

            directional = (
                last['close'] > last['open']
            )

            if (
                swept
                and reclaimed
                and directional
            ):
                return {
                    'passed': True,
                    'type':
                        'LIQUIDITY_SWEEP_LOW_RECLAIM'
                }

        else:

            swept = (
                last['high'] > recent_high
            )

            rejected = (
                last['close'] < recent_high
            )

            directional = (
                last['close'] < last['open']
            )

            if (
                swept
                and rejected
                and directional
            ):
                return {
                    'passed': True,
                    'type':
                        'LIQUIDITY_SWEEP_HIGH_REJECTION'
                }

        return result

    # =========================================================
    # FVG
    # =========================================================

    def detect_valid_fvg(
        self,
        df,
        current_price,
        direction
    ):

        if df is None or len(df) < 15:
            return None

        max_scan = min(
            30,
            len(df) - 3
        )

        for offset in range(
            0,
            max_scan
        ):

            i = len(df) - 1 - offset

            if i < 2:
                break

            a = df.iloc[i - 2]
            b = df.iloc[i - 1]
            c = df.iloc[i]

            # -------------------------------------------------
            # BULLISH FVG
            # -------------------------------------------------

            if (
                direction == 'LONG'
                and c['low'] > a['high']
            ):

                low = float(a['high'])
                high = float(c['low'])

                if high <= low:
                    continue

                # Completely broken below
                if current_price < low:
                    continue

                # Not retraced yet
                inside = (
                    low <= current_price <= high
                )

                if current_price > high:

                    distance = (
                        (current_price - high)
                        / current_price
                    )

                    if distance > 0.025:
                        continue

                    filled_pct = 0.0

                else:

                    filled_pct = (
                        (high - current_price)
                        / (high - low)
                    ) * 100

                if filled_pct >= 80:
                    continue

                mid = (low + high) / 2

                distance_mid = (
                    abs(current_price - mid)
                    / current_price
                )

                if distance_mid > 0.025:
                    continue

                return {
                    'type': 'BULLISH_FVG',
                    'low': low,
                    'high': high,
                    'mid': mid,
                    'age': offset,
                    'filled_pct': round(
                        max(0, filled_pct),
                        1
                    ),
                    'is_active': True,
                    'inside_zone': inside
                }

            # -------------------------------------------------
            # BEARISH FVG
            # -------------------------------------------------

            elif (
                direction == 'SHORT'
                and c['high'] < a['low']
            ):

                low = float(c['high'])
                high = float(a['low'])

                if high <= low:
                    continue

                # Completely broken above
                if current_price > high:
                    continue

                inside = (
                    low <= current_price <= high
                )

                # Not retraced yet
                if current_price < low:

                    distance = (
                        (low - current_price)
                        / current_price
                    )

                    if distance > 0.025:
                        continue

                    filled_pct = 0.0

                else:

                    filled_pct = (
                        (current_price - low)
                        / (high - low)
                    ) * 100

                if filled_pct >= 80:
                    continue

                mid = (low + high) / 2

                distance_mid = (
                    abs(current_price - mid)
                    / current_price
                )

                if distance_mid > 0.025:
                    continue

                return {
                    'type': 'BEARISH_FVG',
                    'low': low,
                    'high': high,
                    'mid': mid,
                    'age': offset,
                    'filled_pct': round(
                        max(0, filled_pct),
                        1
                    ),
                    'is_active': True,
                    'inside_zone': inside
                }

        return None

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_valid_order_block(
        self,
        df,
        current_price,
        direction
    ):

        if df is None or len(df) < 25:
            return None

        start = max(
            2,
            len(df) - 45
        )

        for i in range(
            len(df) - 2,
            start - 1,
            -1
        ):

            candle = df.iloc[i]
            impulse = df.iloc[i + 1]

            # -------------------------------------------------
            # BULLISH OB
            # -------------------------------------------------

            if direction == 'LONG':

                valid_ob = (
                    candle['close']
                    < candle['open']
                    and
                    impulse['close']
                    > candle['high']
                    and
                    impulse['body_ratio']
                    >= 0.50
                    and
                    impulse['volume_ratio']
                    >= 1.10
                )

                if not valid_ob:
                    continue

            # -------------------------------------------------
            # BEARISH OB
            # -------------------------------------------------

            else:

                valid_ob = (
                    candle['close']
                    > candle['open']
                    and
                    impulse['close']
                    < candle['low']
                    and
                    impulse['body_ratio']
                    >= 0.50
                    and
                    impulse['volume_ratio']
                    >= 1.10
                )

                if not valid_ob:
                    continue

            ob_low = float(candle['low'])
            ob_high = float(candle['high'])

            if ob_high <= ob_low:
                continue

            subsequent = df.iloc[i + 2:]

            mitigation = 'VALID'

            if len(subsequent) > 0:

                if direction == 'LONG':

                    if (
                        subsequent['low'].min()
                        < ob_low
                    ):

                        if (
                            subsequent['close']
                            < ob_low
                        ).any():

                            mitigation = (
                                'FULL_MITIGATION'
                            )

                        else:
                            mitigation = (
                                'PARTIAL_MITIGATION'
                            )

                else:

                    if (
                        subsequent['high'].max()
                        > ob_high
                    ):

                        if (
                            subsequent['close']
                            > ob_high
                        ).any():

                            mitigation = (
                                'FULL_MITIGATION'
                            )

                        else:
                            mitigation = (
                                'PARTIAL_MITIGATION'
                            )

            if mitigation == 'FULL_MITIGATION':
                continue

            mid = (
                ob_low + ob_high
            ) / 2

            distance = (
                abs(current_price - mid)
                / current_price
            )

            if distance > 0.025:
                continue

            return {
                'type': (
                    'BULLISH_OB'
                    if direction == 'LONG'
                    else 'BEARISH_OB'
                ),
                'low': ob_low,
                'high': ob_high,
                'mid': mid,
                'age': len(df) - i,
                'mitigation': mitigation,
                'inside_zone': (
                    ob_low
                    <= current_price
                    <= ob_high
                )
            }

        return None

    # =========================================================
    # OB + FVG CONFLUENCE
    # =========================================================

    def _build_entry_zone(
        self,
        current_price,
        ob,
        fvg
    ):

        # Both must actually overlap.
        if ob and fvg:

            overlap_low = max(
                ob['low'],
                fvg['low']
            )

            overlap_high = min(
                ob['high'],
                fvg['high']
            )

            if overlap_low < overlap_high:

                return (
                    overlap_low,
                    overlap_high,
                    'OB_FVG_CONFLUENCE_ZONE'
                )

            # No real overlap:
            # choose the zone closest to current price.
            ob_dist = abs(
                current_price - ob['mid']
            )

            fvg_dist = abs(
                current_price - fvg['mid']
            )

            if ob_dist <= fvg_dist:

                return (
                    ob['low'],
                    ob['high'],
                    'ORDER_BLOCK_ZONE'
                )

            return (
                fvg['low'],
                fvg['high'],
                'FVG_ZONE'
            )

        if ob:

            return (
                ob['low'],
                ob['high'],
                'ORDER_BLOCK_ZONE'
            )

        if fvg:

            return (
                fvg['low'],
                fvg['high'],
                'FVG_ZONE'
            )

        return (
            current_price,
            current_price,
            'MARKET_ENTRY'
        )

    # =========================================================
    # OVEREXTENSION
    # =========================================================

    def _check_overextension(
        self,
        df,
        direction
    ):

        if df is None or len(df) < 20:
            return True

        last = df.iloc[-1]

        if last['ema20'] <= 0:
            return True

        dist_ema = (
            last['close'] -
            last['ema20']
        ) / last['ema20']

        atr_multiple = (
            abs(
                last['close'] -
                last['ema20']
            )
            / max(
                last['atr'],
                1e-12
            )
        )

        if direction == 'LONG':

            if (
                dist_ema > 0.045
                or atr_multiple > 3.5
            ):
                return True

        else:

            if (
                dist_ema < -0.045
                or atr_multiple > 3.5
            ):
                return True

        return False

    # =========================================================
    # TRADE BUILDER
    # =========================================================

    def _build_advanced_trade(
        self,
        df,
        direction,
        ob,
        fvg,
        market_type='swap'
    ):

        if df is None or len(df) < 30:
            return None

        if direction == 'SHORT' and market_type == 'spot':
            return None

        row = df.iloc[-1]

        current_price = float(
            row['close']
        )

        atr = float(
            row['atr']
        )

        if atr <= 0:
            return None

        highs, lows = self._find_swing_points(
            df,
            window=3
        )

        if not highs:
            recent_swing_high = float(
                df['high'].tail(20).max()
            )
        else:
            recent_swing_high = float(
                highs[-1][1]
            )

        if not lows:
            recent_swing_low = float(
                df['low'].tail(20).min()
            )
        else:
            recent_swing_low = float(
                lows[-1][1]
            )

        # -----------------------------------------------------
        # ENTRY ZONE
        # -----------------------------------------------------

        zone_low, zone_high, entry_status = (
            self._build_entry_zone(
                current_price,
                ob,
                fvg
            )
        )

        # Market entry
        if entry_status == 'MARKET_ENTRY':

            if direction == 'LONG':

                zone_low = (
                    current_price -
                    atr * 0.15
                )

                zone_high = current_price

            else:

                zone_low = current_price

                zone_high = (
                    current_price +
                    atr * 0.15
                )

        zone_low = float(zone_low)
        zone_high = float(zone_high)

        if zone_high < zone_low:
            return None

        entry = (
            zone_low + zone_high
        ) / 2

        if entry <= 0:
            return None

        # -----------------------------------------------------
        # PRICE PROXIMITY
        # -----------------------------------------------------

        distance_to_entry = (
            abs(
                current_price - entry
            )
            / current_price
        )

        # Direct setups should be close to current price.
        if distance_to_entry > 0.025:
            return None

        # -----------------------------------------------------
        # LONG
        # -----------------------------------------------------

        if direction == 'LONG':

            sl = (
                recent_swing_low
                - atr * 0.45
            )

            if ob:
                sl = min(
                    sl,
                    ob['low'] - atr * 0.20
                )

            if sl >= entry:
                return None

            risk = entry - sl

            risk_pct = (
                risk / entry
            ) * 100

            if (
                risk_pct < 0.30
                or risk_pct > 5.00
            ):
                return None

            # TP1 minimum 1.8R
            tp1 = entry + (
                risk * 1.80
            )

            structural_tp2 = (
                recent_swing_high
            )

            if structural_tp2 > tp1:
                tp2 = structural_tp2
            else:
                tp2 = entry + (
                    risk * 3.00
                )

            tp3 = entry + (
                risk * 4.50
            )

            if not (
                entry < tp1
                < tp2
                < tp3
            ):
                return None

        # -----------------------------------------------------
        # SHORT
        # -----------------------------------------------------

        else:

            sl = (
                recent_swing_high
                + atr * 0.45
            )

            if ob:
                sl = max(
                    sl,
                    ob['high'] + atr * 0.20
                )

            if sl <= entry:
                return None

            risk = sl - entry

            risk_pct = (
                risk / entry
            ) * 100

            if (
                risk_pct < 0.30
                or risk_pct > 5.00
            ):
                return None

            tp1 = entry - (
                risk * 1.80
            )

            structural_tp2 = (
                recent_swing_low
            )

            if structural_tp2 < tp1:
                tp2 = structural_tp2
            else:
                tp2 = entry - (
                    risk * 3.00
                )

            tp3 = entry - (
                risk * 4.50
            )

            if not (
                entry > tp1
                > tp2
                > tp3
            ):
                return None

        rr1 = abs(
            tp1 - entry
        ) / risk

        rr2 = abs(
            tp2 - entry
        ) / risk

        rr3 = abs(
            tp3 - entry
        ) / risk

        if rr1 < 1.80:
            return None

        return {
            'entry': round(
                entry,
                6
            ),
            'entry_zone': (
                f"{round(zone_low, 6)}"
                f" - "
                f"{round(zone_high, 6)}"
            ),
            'entry_status': entry_status,
            'sl': round(
                sl,
                6
            ),
            'tp1': round(
                tp1,
                6
            ),
            'tp2': round(
                tp2,
                6
            ),
            'tp3': round(
                tp3,
                6
            ),
            'risk_pct': round(
                risk_pct,
                2
            ),
            'rr_tp1': round(
                rr1,
                2
            ),
            'rr_tp2': round(
                rr2,
                2
            ),
            'rr_tp3': round(
                rr3,
                2
            )
        }

    # =========================================================
    # DERIVATIVES CONFIRMATION
    # =========================================================

    def _derivatives_confirmation(
        self,
        decision,
        derivatives
    ):

        bias = derivatives.get(
            'derivatives_bias',
            'NEUTRAL'
        )

        funding = self._safe_float(
            derivatives.get(
                'funding_rate',
                0.0
            )
        )

        score = 0
        conflict = False

        if decision == 'LONG':

            if bias in (
                'LONG_BUILDUP',
                'SHORT_COVERING'
            ):
                score = 5

            elif bias in (
                'SHORT_BUILDUP',
                'LONG_LIQUIDATION'
            ):
                conflict = True
                score = 0

            # Extreme positive funding can indicate
            # crowded longs.
            if funding > 0.0015:
                score = max(
                    0,
                    score - 1
                )

        else:

            if bias in (
                'SHORT_BUILDUP',
                'LONG_LIQUIDATION'
            ):
                score = 5

            elif bias in (
                'LONG_BUILDUP',
                'SHORT_COVERING'
            ):
                conflict = True
                score = 0

            if funding < -0.0015:
                score = max(
                    0,
                    score - 1
                )

        return score, conflict

    # =========================================================
    # MAIN STRATEGY
    # =========================================================

    def evaluate_strategy(
        self,
        symbol,
        market_type='swap'
    ):

        # -----------------------------------------------------
        # MAIN 15M DATA
        # -----------------------------------------------------

        df_raw = self._fetch_ohlcv(
            symbol,
            self.timeframe,
            240,
            market_type
        )

        if df_raw is None or len(df_raw) < 70:

            return self._empty_response(
                symbol,
                market_type,
                'INSUFFICIENT_DATA'
            )

        df = self._prepare(df_raw)

        if len(df) < 70:

            return self._empty_response(
                symbol,
                market_type,
                'INSUFFICIENT_PREPARED_DATA'
            )

        current_price = float(
            df['close'].iloc[-1]
        )

        # -----------------------------------------------------
        # MTF
        # -----------------------------------------------------

        trend_4h, df_4h = (
            self._get_trend_external(
                symbol,
                '4h',
                market_type
            )
        )

        trend_1h, df_1h = (
            self._get_trend_external(
                symbol,
                '1h',
                market_type
            )
        )

        btc_context = self._get_btc_context(
            market_type
        )

        market_regime = (
            self._detect_market_regime(df)
        )

        # -----------------------------------------------------
        # STRUCTURE
        # -----------------------------------------------------

        (
            structure,
            bos,
            mss,
            choch,
            structure_type
        ) = self.detect_market_structure(df)

        # -----------------------------------------------------
        # DERIVATIVES
        # -----------------------------------------------------

        derivatives = (
            self._fetch_derivatives_metrics(
                symbol,
                current_price
            )
        )

        # -----------------------------------------------------
        # INITIAL DIRECTION
        # -----------------------------------------------------

        long_votes = 0
        short_votes = 0

        if trend_4h == 'BULLISH':
            long_votes += 3

        elif trend_4h == 'BEARISH':
            short_votes += 3

        if trend_1h == 'BULLISH':
            long_votes += 2

        elif trend_1h == 'BEARISH':
            short_votes += 2

        if structure == 'BULLISH':
            long_votes += 3

        elif structure == 'BEARISH':
            short_votes += 3

        if bos:

            if structure == 'BULLISH':
                long_votes += 3

            elif structure == 'BEARISH':
                short_votes += 3

        if mss:

            if structure == 'BULLISH':
                long_votes += 2

            elif structure == 'BEARISH':
                short_votes += 2

        if btc_context == 'BTC_BULLISH':
            long_votes += 1

        elif btc_context == 'BTC_BEARISH':
            short_votes += 1

        # -----------------------------------------------------
        # SPOT
        # -----------------------------------------------------

        if market_type == 'spot':

            if (
                long_votes >= short_votes
                and trend_4h != 'BEARISH'
            ):
                decision = 'LONG'

            else:

                return self._empty_response(
                    symbol,
                    market_type,
                    'SPOT_SHORT_RESTRICTED'
                )

        # -----------------------------------------------------
        # SWAP
        # -----------------------------------------------------

        else:

            if long_votes > short_votes:
                decision = 'LONG'

            elif short_votes > long_votes:
                decision = 'SHORT'

            else:

                return self._empty_response(
                    symbol,
                    market_type,
                    'NO_CLEAR_DIRECTION'
                )

        # -----------------------------------------------------
        # HARD GATE 1:
        # REAL STRUCTURAL BREAK
        # -----------------------------------------------------

        if not (
            bos or mss
        ):

            return self._empty_response(
                symbol,
                market_type,
                'NO_STRUCTURE_BREAK'
            )

        # -----------------------------------------------------
        # HARD GATE 2:
        # MTF ALIGNMENT
        # -----------------------------------------------------

        if decision == 'LONG':

            if trend_4h == 'BEARISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    '4H_BEARISH_CONFLICT'
                )

            if trend_1h == 'BEARISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    '1H_BEARISH_CONFLICT'
                )

            if structure != 'BULLISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    'STRUCTURE_NOT_BULLISH'
                )

            if btc_context == 'BTC_BEARISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    'BTC_CONFLICT'
                )

        else:

            if trend_4h == 'BULLISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    '4H_BULLISH_CONFLICT'
                )

            if trend_1h == 'BULLISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    '1H_BULLISH_CONFLICT'
                )

            if structure != 'BEARISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    'STRUCTURE_NOT_BEARISH'
                )

            if btc_context == 'BTC_BULLISH':
                return self._empty_response(
                    symbol,
                    market_type,
                    'BTC_CONFLICT'
                )

        # -----------------------------------------------------
        # HARD GATE 3:
        # OVEREXTENSION
        # -----------------------------------------------------

        if self._check_overextension(
            df,
            decision
        ):

            return self._empty_response(
                symbol,
                market_type,
                'OVEREXTENDED'
            )

        # -----------------------------------------------------
        # ENTRY TOOLS
        # -----------------------------------------------------

        fvg = self.detect_valid_fvg(
            df,
            current_price,
            decision
        )

        ob = self.detect_valid_order_block(
            df,
            current_price,
            decision
        )

        liquidity = (
            self.detect_advanced_liquidity_sweep(
                df,
                decision
            )
        )

        # -----------------------------------------------------
        # ENTRY TOOL GATE
        # -----------------------------------------------------

        if not (
            fvg
            or ob
            or liquidity['passed']
        ):

            return self._empty_response(
                symbol,
                market_type,
                'NO_VALID_ENTRY_TOOL'
            )

        # -----------------------------------------------------
        # VOLUME / DISPLACEMENT
        # -----------------------------------------------------

        displacement = (
            self._has_displacement(
                df,
                decision
            )
        )

        last = df.iloc[-1]

        volume_ok = (
            last['volume_ratio'] >= 1.15
        )

        # A very weak candle should not create
        # an immediate trade.
        if not (
            volume_ok
            or liquidity['passed']
            or displacement
        ):

            return self._empty_response(
                symbol,
                market_type,
                'WEAK_VOLUME'
            )

        # -----------------------------------------------------
        # MOMENTUM
        # -----------------------------------------------------

        rsi = float(
            last['rsi']
        )

        rsi_slope = float(
            last['rsi_slope']
        )

        ema_slope = float(
            last['ema20_slope']
        )

        if decision == 'LONG':

            momentum_ok = (
                rsi >= 50
                and rsi_slope > 0
                and ema_slope > 0
            )

        else:

            momentum_ok = (
                rsi <= 50
                and rsi_slope < 0
                and ema_slope < 0
            )

        # -----------------------------------------------------
        # MARKET REGIME FILTER
        # -----------------------------------------------------

        if (
            market_regime == 'LOW_VOLATILITY'
            and not (
                displacement
                or liquidity['passed']
            )
        ):

            return self._empty_response(
                symbol,
                market_type,
                'LOW_VOLATILITY_NO_DISPLACEMENT'
            )

        # -----------------------------------------------------
        # TRADE CONSTRUCTION
        # -----------------------------------------------------

        trade = self._build_advanced_trade(
            df,
            decision,
            ob,
            fvg,
            market_type
        )

        if trade is None:

            return self._empty_response(
                symbol,
                market_type,
                'POOR_RR_OR_INVALID_ENTRY'
            )

        # -----------------------------------------------------
        # DERIVATIVE CONFIRMATION
        # -----------------------------------------------------

        derivative_score, derivative_conflict = (
            self._derivatives_confirmation(
                decision,
                derivatives
            )
        )

        # Do not hard reject neutral derivatives.
        # Hard conflict only matters when it is accompanied
        # by weak structure/entry confirmation.
        if (
            derivative_conflict
            and not (
                liquidity['passed']
                and displacement
                and ob
            )
        ):

            return self._empty_response(
                symbol,
                market_type,
                'DERIVATIVES_CONFLICT'
            )

        # -----------------------------------------------------
        # SCORE = EXACTLY 100 MAX
        #
        # 4H                 10
        # 1H                 10
        # Structure           15
        # BOS/MSS             10
        # Liquidity           10
        # OB/FVG              10
        # Volume/Displacement 10
        # Momentum             5
        # BTC                 10
        # Derivatives          5
        # Risk/RR              5
        # ----------------------
        # TOTAL              100
        # -----------------------------------------------------

        score = 0

        confirmations = []

        # 1. 4H = 10
        if (
            trend_4h
            == self._decision_to_trend(
                decision
            )
        ):

            score += 10
            confirmations.append(
                'Trend4H'
            )

        # 2. 1H = 10
        if (
            trend_1h
            == self._decision_to_trend(
                decision
            )
        ):

            score += 10
            confirmations.append(
                'Trend1H'
            )

        # 3. Structure = 15
        if (
            structure
            == self._decision_to_trend(
                decision
            )
        ):

            score += 15
            confirmations.append(
                'Structure'
            )

        # 4. BOS/MSS = 10
        if bos or mss:

            score += 10

            if bos:
                confirmations.append('BOS')

            if mss:
                confirmations.append('MSS')

        # 5. Liquidity = 10
        if liquidity['passed']:

            score += 10
            confirmations.append(
                'LiquiditySweep'
            )

        # 6. OB/FVG = 10
        if ob and fvg:

            score += 10

            confirmations.append(
                'OB+FVG'
            )

        elif ob:

            score += 7

            confirmations.append(
                'OrderBlock'
            )

        elif fvg:

            score += 7

            confirmations.append(
                'FVG'
            )

        # 7. Volume + displacement = 10
        if (
            volume_ok
            and (
                displacement
                or liquidity['passed']
            )
        ):

            score += 10

            confirmations.append(
                'VolumeDisplacement'
            )

        # 8. Momentum = 5
        if momentum_ok:

            score += 5

            confirmations.append(
                'Momentum'
            )

        # 9. BTC = 10
        if (
            (
                decision == 'LONG'
                and btc_context == 'BTC_BULLISH'
            )
            or
            (
                decision == 'SHORT'
                and btc_context == 'BTC_BEARISH'
            )
        ):

            score += 10

            confirmations.append(
                'BTC_Aligned'
            )

        # Neutral BTC gets no positive points.
        # It is not a free confirmation.

        # 10. Derivatives = 5
        score += derivative_score

        if derivative_score > 0:
            confirmations.append(
                'Derivatives'
            )

        # 11. Risk/RR = 5
        if trade['rr_tp1'] >= 1.8:

            score += 5

            confirmations.append(
                'RiskRR'
            )

        score = int(
            max(
                0,
                min(
                    score,
                    100
                )
            )
        )

        # -----------------------------------------------------
        # CONFIRMATION QUALITY
        # -----------------------------------------------------

        structural_confirmation = (
            bos
            or mss
        )

        entry_confirmation = (
            ob
            or fvg
            or liquidity['passed']
        )

        if not structural_confirmation:

            return self._empty_response(
                symbol,
                market_type,
                'STRUCTURE_CONFIRMATION_FAILED'
            )

        if not entry_confirmation:

            return self._empty_response(
                symbol,
                market_type,
                'ENTRY_CONFIRMATION_FAILED'
            )

        # Momentum or strong volume/displacement
        momentum_or_volume = (
            momentum_ok
            or displacement
            or liquidity['passed']
        )

        if not momentum_or_volume:

            return self._empty_response(
                symbol,
                market_type,
                'MOMENTUM_VOLUME_CONFIRMATION_FAILED'
            )

        # -----------------------------------------------------
        # FINAL QUALITY GATE
        # -----------------------------------------------------

        if score < 75:

            return self._empty_response(
                symbol,
                market_type,
                'SCORE_BELOW_THRESHOLD'
            )

        if len(confirmations) < 5:

            return self._empty_response(
                symbol,
                market_type,
                'CONFLUENCE_INSUFFICIENT'
            )

        # 85+ = strongest accepted quality
        if score >= 85:
            quality = 'HIGH QUALITY'

        elif score >= 80:
            quality = 'GOOD'

        else:
            quality = 'MODERATE'

        # -----------------------------------------------------
        # BTC CONFLICT FLAG
        # -----------------------------------------------------

        btc_conflict = (
            (
                decision == 'LONG'
                and btc_context == 'BTC_BEARISH'
            )
            or
            (
                decision == 'SHORT'
                and btc_context == 'BTC_BULLISH'
            )
        )

        # -----------------------------------------------------
        # FINAL RESPONSE
        # -----------------------------------------------------

        return {
            'symbol': symbol,
            'market_type': market_type.upper(),

            'decision': decision,

            'score': score,
            'quality': quality,

            'confirmation_count': len(
                confirmations
            ),

            'confirmations': confirmations,

            'trend_4h': trend_4h,
            'trend_1h': trend_1h,

            'btc_context': btc_context,
            'btc_conflict': btc_conflict,

            'funding_rate': derivatives[
                'funding_rate'
            ],

            'oi_change_pct': derivatives[
                'oi_change_pct'
            ],

            'derivatives_bias': derivatives[
                'derivatives_bias'
            ],

            'market_regime': market_regime,

            'structure_type': structure_type,

            'liquidity_type': liquidity[
                'type'
            ],

            'entry_status': trade[
                'entry_status'
            ],

            'entry_zone': trade[
                'entry_zone'
            ],

            'rr_tp1': trade[
                'rr_tp1'
            ],

            'rr_tp2': trade[
                'rr_tp2'
            ],

            'rr_tp3': trade[
                'rr_tp3'
            ],

            'rsi_15m': round(
                rsi,
                1
            ),

            'volume_ratio': round(
                float(
                    last['volume_ratio']
                ),
                2
            ),

            'entry': trade[
                'entry'
            ],

            'sl': trade[
                'sl'
            ],

            'tp1': trade[
                'tp1'
            ],

            'tp2': trade[
                'tp2'
            ],

            'tp3': trade[
                'tp3'
            ],

            'risk_pct': trade[
                'risk_pct'
            ],

            'risk_filter': 'PASSED',

            'structure_confirmation':
                structure,

            'rejection_reason': 'NONE',

            'digital_data': {
                'near_digital_level': False
            },

            'candlestick': 'CONFIRMED'
        }

    # =========================================================
    # EMPTY RESPONSE
    # =========================================================

    def _empty_response(
        self,
        symbol,
        market_type,
        reason='NO_TRADE'
    ):

        return {
            'symbol': symbol,
            'market_type': market_type.upper(),

            'decision': 'NO TRADE',

            'score': 0,

            'quality': 'WEAK',

            'confirmation_count': 0,

            'confirmations': [],

            'trend_4h': 'NEUTRAL',
            'trend_1h': 'NEUTRAL',

            'btc_context': 'BTC_NEUTRAL',
            'btc_conflict': False,

            'funding_rate': 0.0,

            'oi_change_pct': 0.0,

            'derivatives_bias': 'NEUTRAL',

            'market_regime': 'NEUTRAL',

            'structure_type': 'NORMAL',

            'liquidity_type': 'NONE',

            'entry_status': 'INVALID',

            'entry_zone': 'N/A',

            'rr_tp1': 0.0,
            'rr_tp2': 0.0,
            'rr_tp3': 0.0,

            'rsi_15m': 50.0,

            'volume_ratio': 1.0,

            'entry': 0.0,
            'sl': 0.0,

            'tp1': 0.0,
            'tp2': 0.0,
            'tp3': 0.0,

            'risk_pct': 0.0,

            'risk_filter': 'FAILED',

            'structure_confirmation':
                'NEUTRAL',

            'rejection_reason': reason
        }
