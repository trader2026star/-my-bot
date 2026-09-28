import logging
import time
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    # =========================================================
    # INIT — CONNECTION UNCHANGED
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

    def _direction_conflict(self, decision, trend):
        if decision == 'LONG':
            return trend == 'BEARISH'
        if decision == 'SHORT':
            return trend == 'BULLISH'
        return False

    # =========================================================
    # DATA FETCH — CONNECTION UNCHANGED
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

            df = (
                df
                .dropna()
                .drop_duplicates(
                    subset=['timestamp']
                )
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
        default = {
            'funding_rate': 0.0,
            'oi_current': 0.0,
            'oi_change_pct': 0.0,
            'price_change_pct': 0.0,
            'derivatives_bias': 'NEUTRAL'
        }

        try:
            swap_symbol = symbol

            if '/' in symbol and ':' not in symbol:
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
            # FIRST SAMPLE
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

            elapsed = (
                now -
                rec['last_sample_time']
            )

            oi_change_pct = self._safe_float(
                rec.get('oi_change_pct', 0.0)
            )

            price_change_pct = self._safe_float(
                rec.get('price_change_pct', 0.0)
            )

            # -------------------------------------------------
            # NEW PAIRED SAMPLE EVERY 180 SEC
            # -------------------------------------------------

            if elapsed >= 180:

                old_oi = self._safe_float(
                    rec.get('sample_oi', 0.0)
                )

                old_price = self._safe_float(
                    rec.get('sample_price', 0.0)
                )

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

                self.oi_history[swap_symbol] = {
                    'sample_oi': current_oi,
                    'sample_price': current_price,
                    'last_sample_time': now,
                    'oi_change_pct': oi_change_pct,
                    'price_change_pct': price_change_pct
                }

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

        # -----------------------------------------------------
        # EMA
        # -----------------------------------------------------

        df['ema20'] = (
            df['close']
            .ewm(
                span=20,
                adjust=False
            )
            .mean()
        )

        df['ema50'] = (
            df['close']
            .ewm(
                span=50,
                adjust=False
            )
            .mean()
        )

        df['ema200'] = (
            df['close']
            .ewm(
                span=200,
                adjust=False
            )
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
            avg_loss.replace(
                0,
                np.nan
            )
        )

        df['rsi'] = (
            100 -
            (100 / (1 + rs))
        )

        df['rsi'] = (
            df['rsi']
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .fillna(50)
        )

        df['rsi_slope'] = (
            df['rsi'].diff(3)
        )

        # -----------------------------------------------------
        # ATR
        # -----------------------------------------------------

        prev_close = df['close'].shift(1)

       
