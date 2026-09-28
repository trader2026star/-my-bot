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

    def _opposite(self, direction):
        return 'SHORT' if direction == 'LONG' else 'LONG'

    # =========================================================
    # DATA & FETCHING
    # =========================================================

    def _fetch_ohlcv(
        self,
        symbol,
        timeframe,
        limit=250,
        market_type='swap'
    ):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF',
            'NZD', 'NCFX', 'USDCUSD'
        ]

        if any(token in symbol.upper() for token in unwanted_tokens):
            return None

        key = f"{symbol}:{market_type}:{timeframe}:{limit}"
        now = time.time()

        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            if market_type == 'spot':
                self.exchange.options['defaultType'] = 'spot'
            else:
                self.exchange.options['defaultType'] = 'swap'

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
    # DERIVATIVES
    # =========================================================

    def _fetch_derivatives_metrics(
        self,
        symbol,
        current_price
    ):
        try:
            swap_symbol = symbol

            if (
                not symbol.endswith(':USDT')
                and '/' in symbol
                and ':' not in symbol
            ):
                swap_symbol = f"{symbol}:USDT"

            funding_rate = 0.0
            current_oi = 0.0
            oi_change_pct = 0.0
            price_change_pct = 0.0
            now = time.time()

            try:
                funding = self.exchange.fetch_funding_rate(
                    swap_symbol
                )

                if (
                    funding
                    and funding.get('fundingRate') is not None
                ):
                    funding_rate = float(
                        funding['fundingRate']
                    )

            except Exception:
                pass

            try:
                oi_data = self.exchange.fetch_open_interest(
                    swap_symbol
                )

                if (
                    oi_data
                    and oi_data.get('openInterestAmount')
                    is not None
                ):
                    current_oi = float(
                        oi_data['openInterestAmount']
                    )

                    if swap_symbol in self.oi_history:
                        prev_rec = self.oi_history[swap_symbol]

                        if (
                            now -
                            prev_rec['last_sample_time']
                            >= 180
                        ):
                            prev_oi = prev_rec['current_oi']
                            prev_price = prev_rec['current_price']

                            if prev_oi > 0:
                                oi_change_pct = (
                                    (current_oi - prev_oi)
                                    / prev_oi
                                ) * 100.0

                            if prev_price > 0:
                                price_change_pct = (
                                    (current_price - prev_price)
                                    / prev_price
                                ) * 100.0

                            self.oi_history[swap_symbol] = {
                                'current_oi': current_oi,
                                'previous_sample_oi': prev_oi,
                                'current_price': current_price,
                                'previous_sample_price': prev_price,
                                'last_sample_time': now,
                                'oi_change_pct': oi_change_pct,
                                'price_change_pct': price_change_pct
                            }

                        else:
                            prev_oi = prev_rec[
                                'previous_sample_oi'
                            ]
                            prev_price = prev_rec[
                                'previous_sample_price'
                            ]

                            if prev_oi > 0:
                                oi_change_pct = (
                                    (current_oi - prev_oi)
                                    / prev_oi
                                ) * 100.0

                            if prev_price > 0:
                                price_change_pct = (
                                    (current_price - prev_price)
                                    / prev_price
                                ) * 100.0

                    else:
                        self.oi_history[swap_symbol] = {
                            'current_oi': current_oi,
                            'previous_sample_oi': current_oi,
                            'current_price': current_price,
                            'previous_sample_price': current_price,
                            'last_sample_time': now,
                            'oi_change_pct': 0.0,
                            'price_change_pct': 0.0
                        }

            except Exception:
                pass

            bias = 'NEUTRAL'

            if oi_change_pct > 0.2:
                if price_change_pct >= 0:
                    bias = 'LONG_BUILDUP'
                else:
                    bias = 'SHORT_BUILDUP'

            elif oi_change_pct < -0.2:
                if price_change_pct >= 0:
                    bias = 'SHORT_COVERING'
                else:
                    bias = 'LONG_LIQUIDATION'

            return {
                'funding_rate': funding_rate,
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

        except Exception:
            return {
                'funding_rate': 0.0,
                'oi_current': 0.0,
                'oi_change_pct': 0.0,
                'price_change_pct': 0.0,
                'derivatives_bias': 'NEUTRAL'
            }

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

        df['ema20_slope'] = df['ema20'].diff(3)
        df['ema50_slope'] = df['ema50'].diff(3)

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

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        df['rsi'] = df['rsi'].fillna(50)

        df['rsi_slope'] = df['rsi'].diff(3)

        prev_close = df['close'].shift(1)

        tr = pd.concat(
            [
                df['high'] - df['low'],
                (
                    df['high'] - prev_close
                ).abs(),
                (
                    df['low'] - prev_close
                ).abs()
            ],
            axis=1
        ).max(axis=1)

        df['atr'] = (
            tr
            .ewm(
                span=14,
                adjust=False
            )
            .mean()
        )

        df['volume_ma'] = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma']
            .replace(0, np.nan)
        )

        df['volume_ratio'] = (
            df['volume_ratio']
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .fillna(1.0)
        )

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
                80,
                market_type
            )

            df_1h = self._fetch_ohlcv(
                btc_symbol,
                '1h',
                80,
                market_type
            )

            score = 0

            if (
                df_4h is not None
                and len(df_4h) > 20
            ):
                df_4h = self._prepare(df_4h)
                last = df_4h.iloc[-1]

                if (
                    last['close'] > last['ema20']
                    and
                    last['ema20_slope'] > 0
                ):
                    score += 3

                elif (
                    last['close'] < last['ema20']
                    and
                    last['ema20_slope'] < 0
                ):
                    score -= 3

            if (
                df_1h is not None
                and len(df_1h) > 20
            ):
                df_1h = self._prepare(df_1h)
                last = df_1h.iloc[-1]

                if (
                    last['close'] > last['ema20']
                    and
                    last['rsi'] > 50
                ):
                    score += 2

                elif (
                    last['close'] < last['ema20']
                    and
                    last['rsi'] < 50
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
            last['close'] >
            last['ema20'] >
            last['ema50']
            and
            last['ema20_slope'] > 0
        ):
            return 'TRENDING_BULLISH'

        if (
            last['close'] <
            last['ema20'] <
            last['ema50']
            and
            last['ema20_slope'] < 0
        ):
            return 'TRENDING_BEARISH'

        return 'RANGING'

    # =========================================================
    # EXTERNAL TREND
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
            150,
            market_type
        )

        if df is None or len(df) < 50:
            return 'NEUTRAL', None

        df = self._prepare(df)

        last = df.iloc[-1]

        bullish = (
            last['close'] > last['ema20']
            and
            last['ema20'] > last['ema50']
            and
            last['ema20_slope'] >= 0
        )

        bearish = (
            last['close'] < last['ema20']
            and
            last['ema20'] < last['ema50']
            and
            last['ema20_slope'] <= 0
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

        for i in range(
            window,
            len(df) - window
        ):
            curr_h = df['high'].iloc[i]

            if (
                curr_h ==
                df['high']
                .iloc[
                    i - window:
                    i + window + 1
                ]
                .max()
            ):
                highs.append(
                    (i, curr_h)
                )

            curr_l = df['low'].iloc[i]

            if (
                curr_l ==
                df['low']
                .iloc[
                    i - window:
                    i + window + 1
                ]
                .min()
            ):
                lows.append(
                    (i, curr_l)
                )

        return highs, lows

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def detect_market_structure(
        self,
        df
    ):
        if (
            df is None
            or len(df) < 40
        ):
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

        if not highs or not lows:
            return (
                'NEUTRAL',
                False,
                False,
                False,
                'NORMAL_STRUCTURE'
            )

        last_high = highs[-1][1]
        last_low = lows[-1][1]

        recent_df = df.tail(5)

        bullish_break = any(
            recent_df['close'] > last_high
        )

        bearish_break = any(
            recent_df['close'] < last_low
        )

        bos = False
        mss = False
        choch = False

        structure_type = 'NORMAL_STRUCTURE'

        last = df.iloc[-1]

        if (
            last['close'] > last['ema20']
            and
            last['ema20'] >= last['ema50']
        ):
            structure = 'BULLISH'
        elif (
            last['close'] < last['ema20']
            and
            last['ema20'] <= last['ema50']
        ):
            structure = 'BEARISH'
        else:
            structure = 'NEUTRAL'

        if bullish_break:
            bos = True
            structure_type = 'BULLISH_BOS'
            structure = 'BULLISH'

            if (
                df['ema20'].iloc[-10]
                <
                df['ema50'].iloc[-10]
            ):
                mss = True
                choch = True
                structure_type = 'BULLISH_MSS'

        elif bearish_break:
            bos = True
            structure_type = 'BEARISH_BOS'
            structure = 'BEARISH'

            if (
                df['ema20'].iloc[-10]
                >
                df['ema50'].iloc[-10]
            ):
                mss = True
                choch = True
                structure_type = 'BEARISH_MSS'

        return (
            structure,
            bos,
            mss,
            choch,
            structure_type
        )

    # =========================================================
    # LIQUIDITY
    # =========================================================

    def detect_advanced_liquidity_sweep(
        self,
        df,
        direction
    ):
        if (
            df is None
            or len(df) < 20
        ):
            return {
                'passed': False,
                'type': 'NO_SWEEP'
            }

        highs, lows = self._find_swing_points(
            df,
            window=3
        )

        curr = df.iloc[-1]

        if not highs or not lows:
            return {
                'passed': False,
                'type': 'NO_SWEEP'
            }

        eq_high = highs[-1][1]
        eq_low = lows[-1][1]

        if direction == 'LONG':

            swept = any(
                df['low'].tail(5)
                < eq_low
            )

            reclaimed = (
                curr['close'] > eq_low
            )

            if swept and reclaimed:
                return {
                    'passed': True,
                    'type':
                        'LIQUIDITY_SWEEP_LOWS_RECLAIMED'
                }

        else:

            swept = any(
                df['high'].tail(5)
                > eq_high
            )

            rejected = (
                curr['close'] < eq_high
            )

            if swept and rejected:
                return {
                    'passed': True,
                    'type':
                        'LIQUIDITY_SWEEP_HIGHS_REJECTED'
                }

        return {
            'passed': False,
            'type': 'NO_SWEEP'
        }

    # =========================================================
    # FVG
    # =========================================================

    def detect_valid_fvg(
        self,
        df,
        current_price,
        direction
    ):
        if (
            df is None
            or len(df) < 15
        ):
            return None

        total_bars = len(df)

        for i in range(
            len(df) - 3,
            max(2, len(df) - 35),
            -1
        ):
            a = df.iloc[i - 2]
            b = df.iloc[i - 1]
            c = df.iloc[i]

            if direction == 'LONG':

                if c['low'] > a['high']:

                    fvg_low = float(a['high'])
                    fvg_high = float(c['low'])

                    fvg_range = (
                        fvg_high -
                        fvg_low
                    )

                    if fvg_range <= 0:
                        continue

                    if (
                        current_price <
                        fvg_low -
                        (df.iloc[-1]['atr'] * 2)
                    ):
                        continue

                    filled_pct = 0.0

                    if current_price < fvg_high:
                        filled_pct = min(
                            100.0,
                            max(
                                0.0,
                                (
                                    (
                                        fvg_high -
                                        current_price
                                    ) /
                                    fvg_range
                                ) * 100.0
                            )
                        )

                    if filled_pct < 90.0:

                        age = (
                            total_bars - i
                        )

                        fvg_mid = (
                            fvg_low +
                            fvg_high
                        ) / 2

                        inside = (
                            fvg_low
                            <= current_price
                            <= fvg_high
                        )

                        dist = (
                            abs(
                                current_price -
                                fvg_mid
                            ) /
                            current_price
                        )

                        if dist <= 0.08:
                            return {
                                'type':
                                    'BULLISH_FVG',
                                'low': fvg_low,
                                'high': fvg_high,
                                'mid': fvg_mid,
                                'age': age,
                                'filled_pct':
                                    round(
                                        filled_pct,
                                        1
                                    ),
                                'is_active': True,
                                'inside_zone': inside
                            }

            else:

                if c['high'] < a['low']:

                    fvg_low = float(c['high'])
                    fvg_high = float(a['low'])

                    fvg_range = (
                        fvg_high -
                        fvg_low
                    )

                    if fvg_range <= 0:
                        continue

                    if (
                        current_price >
                        fvg_high +
                        (df.iloc[-1]['atr'] * 2)
                    ):
                        continue

                    filled_pct = 0.0

                    if current_price > fvg_low:
                        filled_pct = min(
                            100.0,
                            max(
                                0.0,
                                (
                                    (
                                        current_price -
                                        fvg_low
                                    ) /
                                    fvg_range
                                ) * 100.0
                            )
                        )

                    if filled_pct < 90.0:

                        age = (
                            total_bars - i
                        )

                        fvg_mid = (
                            fvg_low +
                            fvg_high
                        ) / 2

                        inside = (
                            fvg_low
                            <= current_price
                            <= fvg_high
                        )

                        dist = (
                            abs(
                                current_price -
                                fvg_mid
                            ) /
                            current_price
                        )

                        if dist <= 0.08:
                            return {
                                'type':
                                    'BEARISH_FVG',
                                'low': fvg_low,
                                'high': fvg_high,
                                'mid': fvg_mid,
                                'age': age,
                                'filled_pct':
                                    round(
                                        filled_pct,
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
        if (
            df is None
            or len(df) < 20
        ):
            return None

        total_bars = len(df)
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
            atr = df.iloc[-1]['atr']

            if direction == 'LONG':

                is_ob = (
                    candle['close'] <
                    candle['open']
                    and
                    impulse['close'] >
                    candle['high']
                )

                if is_ob:

                    ob_low = float(
                        candle['low']
                    )

                    ob_high = float(
                        candle['high']
                    )

                    age = (
                        total_bars - i
                    )

                    dist = (
                        abs(
                            current_price -
                            (
                                (
                                    ob_low +
                                    ob_high
                                ) / 2
                            )
                        ) /
                        current_price
                    )

                    if (
                        dist <= 0.08
                        or
                        (
                            ob_low -
                            (atr * 3)
                            <= current_price
                            <=
                            ob_high +
                            (atr * 3)
                        )
                    ):
                        return {
                            'type':
                                'BULLISH_OB',
                            'low': ob_low,
                            'high': ob_high,
                            'mid': (
                                ob_low +
                                ob_high
                            ) / 2,
                            'age': age,
                            'inside_zone':
                                ob_low
                                <= current_price
                                <= ob_high
                        }

            else:

                is_ob = (
                    candle['close'] >
                    candle['open']
                    and
                    impulse['close'] <
                    candle['low']
                )

                if is_ob:

                    ob_low = float(
                        candle['low']
                    )

                    ob_high = float(
                        candle['high']
                    )

                    age = (
                        total_bars - i
                    )

                    dist = (
                        abs(
                            current_price -
                            (
                                (
                                    ob_low +
                                    ob_high
                                ) / 2
                            )
                        ) /
                        current_price
                    )

                    if (
                        dist <= 0.08
                        or
                        (
                            ob_low -
                            (atr * 3)
                            <= current_price
                            <=
                            ob_high +
                            (atr * 3)
                        )
                    ):
                        return {
                            'type':
                                'BEARISH_OB',
                            'low': ob_low,
                            'high': ob_high,
                            'mid': (
                                ob_low +
                                ob_high
                            ) / 2,
                            'age': age,
                            'inside_zone':
                                ob_low
                                <= current_price
                                <= ob_high
                        }

        return None

    # =========================================================
    # OVEREXTENSION
    # =========================================================

    def _check_overextension(
        self,
        df,
        direction
    ):
        if (
            df is None
            or len(df) < 15
        ):
            return False

        last = df.iloc[-1]

        if last['ema20'] <= 0:
            return False

        dist_ema20 = (
            last['close'] -
            last['ema20']
        ) / last['ema20']

        if last['atr'] <= 0:
            return False

        atr_multiple = (
            abs(
                last['close'] -
                last['ema20']
            ) /
            last['atr']
        )

        if direction == 'LONG':

            if (
                dist_ema20 > 0.12
                or
                atr_multiple > 7.0
            ):
                return True

        else:

            if (
                dist_ema20 < -0.12
                or
                atr_multiple > 7.0
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
        row = df.iloc[-1]

        current_close = float(
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

        recent_swing_low = (
            lows[-1][1]
            if lows
            else float(
                df['low']
                .tail(15)
                .min()
            )
        )

        recent_swing_high = (
            highs[-1][1]
            if highs
            else float(
                df['high']
                .tail(15)
                .max()
            )
        )

        # -----------------------------------------------------
        # ENTRY ZONE
        # -----------------------------------------------------

        if ob and fvg:

            zone_low = min(
                ob['low'],
                fvg['low']
            )

            zone_high = max(
                ob['high'],
                fvg['high']
            )

            entry_status = (
                'OB_FVG_CONFLUENCE_ZONE'
            )

        elif ob:

            zone_low = ob['low']
            zone_high = ob['high']

            entry_status = 'OB_ZONE'

        elif fvg:

            zone_low = fvg['low']
            zone_high = fvg['high']

            entry_status = 'FVG_ZONE'

        else:

            zone_low = (
                current_close -
                (atr * 0.35)
            )

            zone_high = current_close

            entry_status = 'MARKET_ENTRY'

        entry_avg = (
            zone_low +
            zone_high
        ) / 2

        # =====================================================
        # LONG
        # =====================================================

        if direction == 'LONG':

            sl = (
                recent_swing_low -
                (atr * 0.45)
            )

            if ob:
                sl = min(
                    sl,
                    ob['low'] -
                    (atr * 0.25)
                )

            risk = (
                entry_avg -
                sl
            )

            if risk <= 0:

                sl = (
                    entry_avg -
                    (atr * 1.5)
                )

                risk = (
                    entry_avg -
                    sl
                )

            risk_pct = (
                risk /
                entry_avg
            ) * 100

            # More controlled than old 8%
            if (
                risk_pct > 6.0
                or
                risk_pct < 0.20
            ):
                return None

            tp1 = (
                entry_avg +
                (risk * 1.8)
            )

            tp2 = (
                recent_swing_high
                if recent_swing_high > tp1
                else
                entry_avg +
                (risk * 3.0)
            )

            tp3 = (
                entry_avg +
                (risk * 4.5)
            )

            if not (
                entry_avg <
                tp1 <
                tp2 <
                tp3
            ):
                return None

        # =====================================================
        # SHORT
        # =====================================================

        else:

            if market_type == 'spot':
                return None

            sl = (
                recent_swing_high +
                (atr * 0.45)
            )

            if ob:

                sl = max(
                    sl,
                    ob['high'] +
                    (atr * 0.25)
                )

            risk = (
                sl -
                entry_avg
            )

            if risk <= 0:

                sl = (
                    entry_avg +
                    (atr * 1.5)
                )

                risk = (
                    sl -
                    entry_avg
                )

            risk_pct = (
                risk /
                entry_avg
            ) * 100

            if (
                risk_pct > 6.0
                or
                risk_pct < 0.20
            ):
                return None

            tp1 = (
                entry_avg -
                (risk * 1.8)
            )

            tp2 = (
                recent_swing_low
                if recent_swing_low < tp1
                else
                entry_avg -
                (risk * 3.0)
            )

            tp3 = (
                entry_avg -
                (risk * 4.5)
            )

            if not (
                entry_avg >
                tp1 >
                tp2 >
                tp3
            ):
                return None

        rr_tp1 = round(
            abs(
                tp1 -
                entry_avg
            ) / risk,
            2
        ) if risk > 0 else 0.0

        rr_tp2 = round(
            abs(
                tp2 -
                entry_avg
            ) / risk,
            2
        ) if risk > 0 else 0.0

        rr_tp3 = round(
            abs(
                tp3 -
                entry_avg
            ) / risk,
            2
        ) if risk > 0 else 0.0

        if rr_tp1 < 1.5:
            return None

        return {
            'entry': round(
                entry_avg,
                6
            ),
            'entry_zone': (
                f"{round(zone_low, 6)}"
                f" - "
                f"{round(zone_high, 6)}"
            ),
            'entry_status':
                entry_status,
            'sl': round(
                float(sl),
                6
            ),
            'tp1': round(
                float(tp1),
                6
            ),
            'tp2': round(
                float(tp2),
                6
            ),
            'tp3': round(
                float(tp3),
                6
            ),
            'risk_pct': round(
                risk_pct,
                2
            ),
            'rr_tp1': rr_tp1,
            'rr_tp2': rr_tp2,
            'rr_tp3': rr_tp3
        }

    # =========================================================
    # DIRECTION ENGINE
    # =========================================================

    def _select_direction(
        self,
        trend_4h,
        trend_1h,
        structure,
        btc_context,
        rsi,
        derivatives
    ):
        long_points = 0
        short_points = 0

        # 4H carries the highest directional weight
        if trend_4h == 'BULLISH':
            long_points += 4

        elif trend_4h == 'BEARISH':
            short_points += 4

        # 1H
        if trend_1h == 'BULLISH':
            long_points += 3

        elif trend_1h == 'BEARISH':
            short_points += 3

        # Structure
        if structure == 'BULLISH':
            long_points += 3

        elif structure == 'BEARISH':
            short_points += 3

        # BTC context
        if btc_context == 'BTC_BULLISH':
            long_points += 1

        elif btc_context == 'BTC_BEARISH':
            short_points += 1

        # RSI momentum
        if rsi >= 52:
            long_points += 1

        elif rsi <= 48:
            short_points += 1

        # Derivatives
        dbias = derivatives.get(
            'derivatives_bias',
            'NEUTRAL'
        )

        if dbias in [
            'LONG_BUILDUP',
            'SHORT_COVERING'
        ]:
            long_points += 1

        elif dbias in [
            'SHORT_BUILDUP',
            'LONG_LIQUIDATION'
        ]:
            short_points += 1

        if long_points > short_points:
            return (
                'LONG',
                long_points,
                short_points
            )

        if short_points > long_points:
            return (
                'SHORT',
                long_points,
                short_points
            )

        # Tie breaker:
        if trend_4h == 'BULLISH':
            return (
                'LONG',
                long_points,
                short_points
            )

        if trend_4h == 'BEARISH':
            return (
                'SHORT',
                long_points,
                short_points
            )

        return (
            'LONG',
            long_points,
            short_points
        )

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
            220,
            market_type
        )

        if (
            df_raw is None
            or len(df_raw) < 60
        ):
            return self._empty_response(
                symbol,
                market_type,
                'INSUFFICIENT_DATA'
            )

        df = self._prepare(
            df_raw
        )

        if len(df) < 60:
            return self._empty_response(
                symbol,
                market_type,
                'INSUFFICIENT_PREPARED_DATA'
            )

        current_price = float(
            df['close'].iloc[-1]
        )

        # -----------------------------------------------------
        # HIGHER TIMEFRAMES
        # -----------------------------------------------------

        trend_4h, _ = self._get_trend_external(
            symbol,
            '4h',
            market_type
        )

        trend_1h, _ = self._get_trend_external(
            symbol,
            '1h',
            market_type
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

        last_row = df.iloc[-1]

        rsi_val = float(
            last_row['rsi']
        )

        v_ratio = float(
            last_row['volume_ratio']
        )

        # -----------------------------------------------------
        # DIRECTION
        # -----------------------------------------------------

        if market_type == 'spot':

            decision = 'LONG'

            direction_long_points = 0
            direction_short_points = 0

        else:

            (
                decision,
                direction_long_points,
                direction_short_points
            ) = self._select_direction(
                trend_4h,
                trend_1h,
                structure,
                btc_context,
                rsi_val,
                derivatives
            )

        # -----------------------------------------------------
        # STRUCTURAL CONFLICT
        # -----------------------------------------------------

        expected_trend = (
            self._decision_to_trend(
                decision
            )
        )

        trend4h_aligned = (
            trend_4h ==
            expected_trend
        )

        trend1h_aligned = (
            trend_1h ==
            expected_trend
        )

        structure_aligned = (
            structure ==
            expected_trend
        )

        btc_aligned = (
            (
                decision == 'LONG'
                and
                btc_context ==
                'BTC_BULLISH'
            )
            or
            (
                decision == 'SHORT'
                and
                btc_context ==
                'BTC_BEARISH'
            )
        )

        btc_conflict = (
            (
                decision == 'LONG'
                and
                btc_context ==
                'BTC_BEARISH'
            )
            or
            (
                decision == 'SHORT'
                and
                btc_context ==
                'BTC_BULLISH'
            )
        )

        # -----------------------------------------------------
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
        # LIQUIDITY
        # -----------------------------------------------------

        liquidity_sweep = (
            self.detect_advanced_liquidity_sweep(
                df,
                decision
            )
        )

        if liquidity_sweep['passed']:
            trade_style = 'REVERSAL'
        else:
            trade_style = 'TREND_CONTINUATION'

        # -----------------------------------------------------
        # OB / FVG
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

        # -----------------------------------------------------
        # TRADE
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
                'POOR_RR_OR_INVALID_SL'
            )

        # =====================================================
        # VOLUME QUALITY
        # =====================================================

        warnings = []

        if v_ratio < 0.20:

            volume_quality = 'VERY_LOW'
            warnings.append(
                'VERY_LOW_VOLUME'
            )

        elif v_ratio < 0.50:

            volume_quality = 'WEAK'
            warnings.append(
                'WEAK_VOLUME'
            )

        elif v_ratio < 0.80:

            volume_quality = 'BELOW_AVERAGE'

            warnings.append(
                'BELOW_AVERAGE_VOLUME'
            )

        elif v_ratio < 1.00:

            volume_quality = 'NORMAL'

        elif v_ratio < 1.20:

            volume_quality = 'CONFIRMING'

        else:

            volume_quality = 'STRONG'

        # =====================================================
        # RSI
        # =====================================================

        if decision == 'LONG':

            if rsi_val > 70:
                warnings.append(
                    'RSI_OVERBOUGHT_WARNING'
                )

            elif rsi_val > 67:
                warnings.append(
                    'RSI_HIGH_WARNING'
                )

            elif rsi_val < 40:
                warnings.append(
                    'RSI_WEAK_MOMENTUM'
                )

        else:

            if rsi_val < 30:
                warnings.append(
                    'RSI_OVERSOLD_WARNING'
                )

            elif rsi_val < 33:
                warnings.append(
                    'RSI_LOW_WARNING'
                )

            elif rsi_val > 60:
                warnings.append(
                    'RSI_WEAK_SHORT_MOMENTUM'
                )

        # =====================================================
        # SCORE
        #
        # Maximum = 100
        # =====================================================

        score = 0

        # -----------------------------------------------------
        # 1. 4H Trend = 15
        # -----------------------------------------------------

        if trend4h_aligned:
            score += 15

        elif trend_4h == 'NEUTRAL':
            score += 6

        # Opposite trend = 0

        # -----------------------------------------------------
        # 2. 1H Trend = 15
        # -----------------------------------------------------

        if trend1h_aligned:
            score += 15

        elif trend_1h == 'NEUTRAL':
            score += 7

        # Opposite = 0

        # -----------------------------------------------------
        # 3. 15M RSI/Momentum = 10
        # -----------------------------------------------------

        if decision == 'LONG':

            if 45 <= rsi_val <= 62:
                score += 10

            elif 62 < rsi_val <= 67:
                score += 8

            elif 67 < rsi_val <= 70:
                score += 5

            elif rsi_val > 70:
                score += 2

            else:
                score += 4

        else:

            if 38 <= rsi_val <= 55:
                score += 10

            elif 33 <= rsi_val < 38:
                score += 8

            elif 30 <= rsi_val < 33:
                score += 5

            elif rsi_val < 30:
                score += 2

            else:
                score += 4

        # -----------------------------------------------------
        # 4. Structure = 15
        # -----------------------------------------------------

        if structure_aligned:
            score += 15

        elif structure == 'NEUTRAL':
            score += 5

        else:
            score += 0

        # -----------------------------------------------------
        # 5. Structural Breaks = 8
        #
        # BOS/MSS/CHoCH are related events.
        # They are NOT counted as 3 independent confirmations.
        # -----------------------------------------------------

        structural_event = (
            bos or
            mss or
            choch
        )

        if mss or choch:
            score += 8

        elif bos:
            score += 6

        # -----------------------------------------------------
        # 6. Liquidity = 12
        # -----------------------------------------------------

        if liquidity_sweep['passed']:
            score += 12

        # -----------------------------------------------------
        # 7. OB/FVG = 10
        # -----------------------------------------------------

        if ob and fvg:

            score += 10

        elif ob or fvg:

            score += 7

        # -----------------------------------------------------
        # 8. Volume = 5
        # -----------------------------------------------------

        if v_ratio >= 1.20:

            score += 5

        elif v_ratio >= 1.00:

            score += 4

        elif v_ratio >= 0.80:

            score += 3

        elif v_ratio >= 0.50:

            score += 2

        elif v_ratio >= 0.20:

            score += 1

        else:

            score -= 5

        # -----------------------------------------------------
        # 9. BTC Context = 5
        # -----------------------------------------------------

        if btc_aligned:

            score += 5

        elif btc_context == 'BTC_NEUTRAL':

            score += 2

        # BTC conflict gets 0

        # -----------------------------------------------------
        # 10. Derivatives = 5
        # -----------------------------------------------------

        dbias = derivatives.get(
            'derivatives_bias',
            'NEUTRAL'
        )

        derivatives_aligned = False

        if decision == 'LONG':

            derivatives_aligned = (
                dbias in [
                    'LONG_BUILDUP',
                    'SHORT_COVERING'
                ]
            )

        else:

            derivatives_aligned = (
                dbias in [
                    'SHORT_BUILDUP',
                    'LONG_LIQUIDATION'
                ]
            )

        if derivatives_aligned:
            score += 5

        # -----------------------------------------------------
        # 11. Risk / RR = 5
        # -----------------------------------------------------

        if (
            trade['rr_tp1'] >= 1.8
            and
            trade['risk_pct'] <= 4.0
        ):
            score += 5

        elif (
            trade['rr_tp1'] >= 1.5
            and
            trade['risk_pct'] <= 6.0
        ):
            score += 3

        # -----------------------------------------------------
        # Clamp
        # -----------------------------------------------------

        score = int(
            max(
                0,
                min(
                    score,
                    100
                )
            )
        )

        # =====================================================
        # INDEPENDENT CONFIRMATIONS
        #
        # Avoid double-counting BOS/MSS/CHoCH.
        # =====================================================

        confirmations = []

        if trend4h_aligned:
            confirmations.append(
                'Trend4H'
            )

        if trend1h_aligned:
            confirmations.append(
                'Trend1H'
            )

        if structure_aligned:
            confirmations.append(
                'Structure'
            )

        if structural_event:
            if mss or choch:
                confirmations.append(
                    'MSS/CHoCH'
                )
            else:
                confirmations.append(
                    'BOS'
                )

        if liquidity_sweep['passed']:
            confirmations.append(
                'LiquiditySweep'
            )

        if ob:
            confirmations.append(
                'OrderBlock'
            )

        if fvg:
            confirmations.append(
                'FVG'
            )

        if v_ratio >= 1.0:
            confirmations.append(
                'Volume'
            )

        if btc_aligned:
            confirmations.append(
                'BTC'
            )

        if derivatives_aligned:
            confirmations.append(
                'Derivatives'
            )

        # =====================================================
        # QUALITY GATES
        # =====================================================

        strong_alignment_count = sum(
            [
                trend4h_aligned,
                trend1h_aligned,
                structure_aligned
            ]
        )

        has_price_action = (
            structural_event
            or
            liquidity_sweep['passed']
            or
            ob
            or
            fvg
        )

        # Hard directional conflict
        if btc_conflict:

            # Don't automatically reject every trade,
            # but prevent STRONG classification.
            btc_penalty = True

        else:
            btc_penalty = False

        # Opposite higher timeframe is dangerous
        severe_4h_conflict = (
            trend_4h ==
            self._opposite(
                expected_trend
            )
        )

        severe_1h_conflict = (
            trend_1h ==
            self._opposite(
                expected_trend
            )
        )

        # -----------------------------------------------------
        # Minimum acceptance
        # -----------------------------------------------------

        if score < 68:
            return self._empty_response(
                symbol,
                market_type,
                'CONFLUENCE_INSUFFICIENT'
            )

        if len(confirmations) < 3:
            return self._empty_response(
                symbol,
                market_type,
                'CONFIRMATIONS_INSUFFICIENT'
            )

        if not has_price_action:
            return self._empty_response(
                symbol,
                market_type,
                'NO_PRICE_ACTION_CONFIRMATION'
            )

        # Opposite 4H trend requires much stronger evidence
        if severe_4h_conflict:

            if (
                score < 78
                or
                not liquidity_sweep['passed']
                or
                not (ob or fvg)
            ):
                return self._empty_response(
                    symbol,
                    market_type,
                    '4H_TREND_CONFLICT'
                )

        # Opposite 1H trend is allowed only with stronger setup
        if severe_1h_conflict:

            if (
                score < 73
                or
                not (ob or fvg)
            ):
                return self._empty_response(
                    symbol,
                    market_type,
                    '1H_TREND_CONFLICT'
                )

        # =====================================================
        # DIRECT ENTRY FILTER
        # =====================================================

        inside_ob = bool(
            ob and
            ob.get('inside_zone', False)
        )

        inside_fvg = bool(
            fvg and
            fvg.get('inside_zone', False)
        )

        strong_entry_location = (
            inside_ob
            or
            inside_fvg
            or
            (
                ob is not None
                and
                fvg is not None
            )
        )

        direct_allowed = (
            strong_entry_location
            and
            has_price_action
            and
            not severe_4h_conflict
            and
            score >= 70
        )

        if direct_allowed:
            final_entry_status = 'DIRECT'
        else:
            final_entry_status = (
                trade['entry_status']
            )

        # =====================================================
        # QUALITY CLASSIFICATION
        # =====================================================

        quality = 'VALID SETUP'

        # HIGH QUALITY
        if (
            score >= 85
            and
            strong_alignment_count >= 2
            and
            len(confirmations) >= 5
            and
            not btc_penalty
            and
            v_ratio >= 0.80
            and
            trade['risk_pct'] <= 4.5
        ):
            quality = 'HIGH QUALITY'

        # STRONG
        elif (
            score >= 75
            and
            strong_alignment_count >= 2
            and
            len(confirmations) >= 4
            and
            not severe_4h_conflict
            and
            not btc_penalty
            and
            v_ratio >= 0.70
            and
            trade['risk_pct'] <= 5.0
        ):
            quality = 'STRONG'

        # -----------------------------------------------------
        # Prevent weak-volume setups from being STRONG
        # -----------------------------------------------------

        if v_ratio < 0.70:
            quality = 'VALID SETUP'

        # Prevent 1H neutral from becoming STRONG
        if trend_1h == 'NEUTRAL':
            if quality in [
                'HIGH QUALITY',
                'STRONG'
            ]:
                quality = 'VALID SETUP'

        # Prevent high RSI LONG from being HIGH QUALITY
        if (
            decision == 'LONG'
            and
            rsi_val > 67
        ):
            if quality == 'HIGH QUALITY':
                quality = 'STRONG'

        # Prevent very wide risk
        if trade['risk_pct'] > 5.0:
            if quality in [
                'HIGH QUALITY',
                'STRONG'
            ]:
                quality = 'VALID SETUP'

        # BTC conflict never allows HIGH QUALITY
        if btc_penalty:
            if quality == 'HIGH QUALITY':
                quality = 'STRONG'

        # =====================================================
        # FINAL WARNING
        # =====================================================

        if v_ratio < 0.80:
            if 'LOW_VOLUME_CONFIRMATION' not in warnings:
                warnings.append(
                    'LOW_VOLUME_CONFIRMATION'
                )

        if btc_conflict:
            warnings.append(
                'BTC_DIRECTION_CONFLICT'
            )

        if trend_1h == 'NEUTRAL':
            warnings.append(
                '1H_NEUTRAL'
            )

        if trade['risk_pct'] > 4.5:
            warnings.append(
                'WIDE_RISK'
            )

        # =====================================================
        # FINAL RESPONSE
        # =====================================================

        return {
            'symbol': symbol,
            'market_type':
                market_type.upper(),

            'decision':
                decision,

            'score':
                score,

            'quality':
                quality,

            'confirmation_count':
                len(confirmations),

            'confirmations':
                confirmations,

            'strong_confirmations':
                confirmations,

            'trend_4h':
                trend_4h,

            'trend_1h':
                trend_1h,

            'btc_context':
                btc_context,

            'btc_conflict':
                btc_conflict,

            'funding_rate':
                derivatives[
                    'funding_rate'
                ],

            'oi_change_pct':
                derivatives[
                    'oi_change_pct'
                ],

            'derivatives_bias':
                derivatives[
                    'derivatives_bias'
                ],

            'market_regime':
                market_regime,

            'structure_type':
                structure_type,

            'liquidity_type':
                liquidity_sweep[
                    'type'
                ],

            'entry_status':
                final_entry_status,

            'entry_zone':
                trade[
                    'entry_zone'
                ],

            'rr_tp1':
                trade[
                    'rr_tp1'
                ],

            'rr_tp2':
                trade[
                    'rr_tp2'
                ],

            'rr_tp3':
                trade[
                    'rr_tp3'
                ],

            'rsi_15m':
                round(
                    rsi_val,
                    1
                ),

            'volume_ratio':
                round(
                    v_ratio,
                    2
                ),

            'volume_quality':
                volume_quality,

            'warnings':
                warnings,

            'entry':
                trade[
                    'entry'
                ],

            'sl':
                trade[
                    'sl'
                ],

            'tp1':
                trade[
                    'tp1'
                ],

            'tp2':
                trade[
                    'tp2'
                ],

            'tp3':
                trade[
                    'tp3'
                ],

            'risk_pct':
                trade[
                    'risk_pct'
                ],

            'risk_filter':
                'PASSED',

            'structure_confirmation':
                structure,

            'rejection_reason':
                'NONE',

            'digital_data': {
                'near_digital_level':
                    False
            },

            'candlestick':
                'CONFIRMED',

            'trade_style':
                trade_style,

            'setup_type':
                trade_style
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
            'symbol':
                symbol,

            'market_type':
                market_type.upper(),

            'decision':
                'NO TRADE',

            'score':
                0,

            'quality':
                'WEAK',

            'confirmation_count':
                0,

            'confirmations':
                [],

            'strong_confirmations':
                [],

            'trend_4h':
                'NEUTRAL',

            'trend_1h':
                'NEUTRAL',

            'btc_context':
                'BTC_NEUTRAL',

            'btc_conflict':
                False,

            'funding_rate':
                0.0,

            'oi_change_pct':
                0.0,

            'derivatives_bias':
                'NEUTRAL',

            'market_regime':
                'NEUTRAL',

            'structure_type':
                'NORMAL',

            'liquidity_type':
                'NONE',

            'entry_status':
                'INVALID',

            'entry_zone':
                'N/A',

            'rr_tp1':
                0.0,

            'rr_tp2':
                0.0,

            'rr_tp3':
                0.0,

            'rsi_15m':
                50.0,

            'volume_ratio':
                1.0,

            'volume_quality':
                'NORMAL',

            'warnings':
                [],

            'entry':
                0.0,

            'sl':
                0.0,

            'tp1':
                0.0,

            'tp2':
                0.0,

            'tp3':
                0.0,

            'risk_pct':
                0.0,

            'risk_filter':
                'FAILED',

            'structure_confirmation':
                'NEUTRAL',

            'rejection_reason':
                reason,

            'trade_style':
                'NONE',

            'setup_type':
                'NONE'
        }
