import logging
import time
import math
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    # =========================================================
    # INIT — CONNECTION INTERFACE PRESERVED
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
    # UTILITIES
    # =========================================================

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            if value is None:
                return default

            value = float(value)

            if not np.isfinite(value):
                return default

            return value

        except Exception:
            return default

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    @staticmethod
    def _fmt(value, digits=8):
        try:
            value = float(value)

            if value == 0:
                return "0"

            return f"{value:.{digits}g}"

        except Exception:
            return "0"

    @staticmethod
    def _pct(a, b):
        try:
            if b == 0:
                return 0.0

            return ((a - b) / b) * 100.0

        except Exception:
            return 0.0

    # =========================================================
    # EMPTY RESPONSE
    # =========================================================

    def _empty_response(self, reason="NO TRADE", diagnostics=None):

        diagnostics = diagnostics or {}

        return {
            "decision": "NO TRADE",

            "score": int(
                diagnostics.get("score", 0)
            ),

            "quality": diagnostics.get(
                "quality",
                "WEAK"
            ),

            "reason": reason,

            "rejection_reason": reason,

            "confirmations": diagnostics.get(
                "confirmations",
                []
            ),

            "confirmation_count": len(
                diagnostics.get(
                    "confirmations",
                    []
                )
            ),

            "trend_4h": diagnostics.get(
                "trend_4h",
                "NEUTRAL"
            ),

            "trend_1h": diagnostics.get(
                "trend_1h",
                "NEUTRAL"
            ),

            "trend_15m": diagnostics.get(
                "trend_15m",
                "NEUTRAL"
            ),

            "btc_context": diagnostics.get(
                "btc_context",
                "BTC_NEUTRAL"
            ),

            "market_regime": diagnostics.get(
                "market_regime",
                "UNKNOWN"
            ),

            "structure_type": diagnostics.get(
                "structure_type",
                "NEUTRAL"
            ),

            "structure": diagnostics.get(
                "structure",
                {}
            ),

            "liquidity": diagnostics.get(
                "liquidity",
                {}
            ),

            "order_block": diagnostics.get(
                "order_block",
                None
            ),

            "fvg": diagnostics.get(
                "fvg",
                None
            ),

            "funding_rate": self._safe_float(
                diagnostics.get(
                    "funding_rate",
                    0
                )
            ),

            "oi_change_pct": self._safe_float(
                diagnostics.get(
                    "oi_change_pct",
                    0
                )
            ),

            "price_change_pct": self._safe_float(
                diagnostics.get(
                    "price_change_pct",
                    0
                )
            ),

            "derivatives_bias": diagnostics.get(
                "derivatives_bias",
                "NEUTRAL"
            ),

            "rsi": self._safe_float(
                diagnostics.get(
                    "rsi",
                    50
                )
            ),

            "volume_ratio": self._safe_float(
                diagnostics.get(
                    "volume_ratio",
                    0
                )
            ),

            "atr": self._safe_float(
                diagnostics.get(
                    "atr",
                    0
                )
            ),

            "entry": 0,

            "entry_zone": None,

            "sl": 0,

            "tp1": 0,

            "tp2": 0,

            "tp3": 0,

            "risk_pct": 0,

            "rr_tp1": 0,

            "rr_tp2": 0,

            "rr_tp3": 0,

            "risk_status": "FAIL",

            "digital_data": diagnostics.get(
                "digital_data",
                {}
            ),

            "candlestick": diagnostics.get(
                "candlestick",
                {}
            ),

            "symbol": diagnostics.get(
                "symbol",
                ""
            ),

            "timestamp": int(time.time())
        }

    # =========================================================
    # OHLCV
    # =========================================================

    def _fetch_ohlcv(
        self,
        symbol,
        timeframe,
        limit=250,
        market_type='swap'
    ):

        cache_key = (
            f"ohlcv:{market_type}:"
            f"{symbol}:{timeframe}:{limit}"
        )

        now = time.time()

        try:

            cached = self.cache.get(
                cache_key
            )

            if cached:

                ts, data = cached

                if now - ts < self.cache_seconds:
                    return data.copy()

            original_type = self.exchange.options.get(
                'defaultType',
                'swap'
            )

            try:

                self.exchange.options[
                    'defaultType'
                ] = market_type

                data = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    limit=limit
                )

            finally:

                self.exchange.options[
                    'defaultType'
                ] = original_type

            if not data or len(data) < 50:
                return pd.DataFrame()

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

            numeric_columns = [
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]

            for col in numeric_columns:

                df[col] = pd.to_numeric(
                    df[col],
                    errors='coerce'
                )

            df = (
                df
                .replace(
                    [np.inf, -np.inf],
                    np.nan
                )
                .dropna()
                .reset_index(drop=True)
            )

            if len(df) < 50:
                return pd.DataFrame()

            self.cache[cache_key] = (
                now,
                df.copy()
            )

            return df

        except Exception as e:

            logger.warning(
                "OHLCV error %s %s: %s",
                symbol,
                timeframe,
                e
            )

            return pd.DataFrame()

    # =========================================================
    # TICKER
    # =========================================================

    def _fetch_price(self, symbol):

        cache_key = f"price:{symbol}"
        now = time.time()

        try:

            cached = self.cache.get(
                cache_key
            )

            if cached:

                ts, price = cached

                if now - ts < 3:
                    return price

            ticker = self.exchange.fetch_ticker(
                symbol
            )

            price = self._safe_float(
                ticker.get('last')
                or ticker.get('close')
            )

            if price <= 0:

                price = self._safe_float(
                    ticker.get('bid')
                )

            if price <= 0:

                price = self._safe_float(
                    ticker.get('ask')
                )

            if price > 0:

                self.cache[cache_key] = (
                    now,
                    price
                )

            return price

        except Exception as e:

            logger.warning(
                "Price error %s: %s",
                symbol,
                e
            )

            return 0.0

    # =========================================================
    # INDICATORS
    # =========================================================

    def _prepare(self, df):

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()

        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        # -----------------------------------------------------
        # EMA
        # -----------------------------------------------------

        df['ema20'] = close.ewm(
            span=20,
            adjust=False
        ).mean()

        df['ema50'] = close.ewm(
            span=50,
            adjust=False
        ).mean()

        df['ema200'] = close.ewm(
            span=200,
            adjust=False
        ).mean()

        df['ema20_slope'] = (
            df['ema20']
            .pct_change(5)
            * 100
        )

        df['ema50_slope'] = (
            df['ema50']
            .pct_change(5)
            * 100
        )

        # -----------------------------------------------------
        # ATR
        # -----------------------------------------------------

        prev_close = close.shift(1)

        tr1 = high - low

        tr2 = (
            high - prev_close
        ).abs()

        tr3 = (
            low - prev_close
        ).abs()

        df['tr'] = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = (
            df['tr']
            .rolling(14)
            .mean()
        )

        df['atr_pct'] = (
            df['atr']
            / close
        ) * 100

        # -----------------------------------------------------
        # RSI
        # -----------------------------------------------------

        delta = close.diff()

        gain = delta.clip(
            lower=0
        )

        loss = (
            -delta.clip(
                upper=0
            )
        )

        avg_gain = (
            gain
            .rolling(14)
            .mean()
        )

        avg_loss = (
            loss
            .rolling(14)
            .mean()
        )

        rs = avg_gain / avg_loss.replace(
            0,
            np.nan
        )

        df['rsi'] = (
            100
            - (
                100
                / (1 + rs)
            )
        )

        df['rsi'] = (
            df['rsi']
            .fillna(50)
        )

        # -----------------------------------------------------
        # Volume
        # -----------------------------------------------------

        df['volume_ma20'] = (
            volume
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            volume
            / df['volume_ma20'].replace(
                0,
                np.nan
            )
        )

        df['volume_ratio'] = (
            df['volume_ratio']
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .fillna(1)
        )

        # -----------------------------------------------------
        # ROC / Momentum
        # -----------------------------------------------------

        df['roc5'] = (
            close
            .pct_change(5)
            * 100
        )

        df['roc10'] = (
            close
            .pct_change(10)
            * 100
        )

        # -----------------------------------------------------
        # Bollinger Bands
        # -----------------------------------------------------

        bb_mid = (
            close
            .rolling(20)
            .mean()
        )

        bb_std = (
            close
            .rolling(20)
            .std()
        )

        df['bb_mid'] = bb_mid

        df['bb_upper'] = (
            bb_mid
            + 2 * bb_std
        )

        df['bb_lower'] = (
            bb_mid
            - 2 * bb_std
        )

        df['bb_width'] = (
            (
                df['bb_upper']
                - df['bb_lower']
            )
            / bb_mid.replace(
                0,
                np.nan
            )
        ) * 100

        # -----------------------------------------------------
        # Candle anatomy
        # -----------------------------------------------------

        df['body'] = (
            df['close']
            - df['open']
        )

        df['body_abs'] = (
            df['body']
            .abs()
        )

        df['range'] = (
            df['high']
            - df['low']
        )

        df['upper_wick'] = (
            df['high']
            - df[['open', 'close']].max(
                axis=1
            )
        )

        df['lower_wick'] = (
            df[['open', 'close']].min(
                axis=1
            )
            - df['low']
        )

        df['body_ratio'] = (
            df['body_abs']
            / df['range'].replace(
                0,
                np.nan
            )
        )

        df['body_ratio'] = (
            df['body_ratio']
            .fillna(0)
        )

        return (
            df
            .replace(
                [np.inf, -np.inf],
                np.nan
            )
            .ffill()
            .bfill()
        )

    # =========================================================
    # TREND
    # =========================================================

    def _trend(self, df):

        if df is None or len(df) < 20:
            return "NEUTRAL"

        x = df.iloc[-1]

        price = self._safe_float(
            x['close']
        )

        ema20 = self._safe_float(
            x['ema20']
        )

        ema50 = self._safe_float(
            x['ema50']
        )

        ema200 = self._safe_float(
            x['ema200']
        )

        slope20 = self._safe_float(
            x['ema20_slope']
        )

        slope50 = self._safe_float(
            x['ema50_slope']
        )

        bullish = 0
        bearish = 0

        if price > ema20:
            bullish += 1
        else:
            bearish += 1

        if ema20 > ema50:
            bullish += 1
        else:
            bearish += 1

        if ema50 > ema200:
            bullish += 1
        else:
            bearish += 1

        if slope20 > 0:
            bullish += 1
        else:
            bearish += 1

        if slope50 > 0:
            bullish += 1
        else:
            bearish += 1

        if bullish >= 4:
            return "BULLISH"

        if bearish >= 4:
            return "BEARISH"

        return "NEUTRAL"

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def _structure(self, df):

        if df is None or len(df) < 30:

            return {
                "bias": "NEUTRAL",
                "bos": False,
                "choch": False,
                "mss": False,
                "swing_high": 0,
                "swing_low": 0
            }

        recent = df.tail(40)

        swing_high = self._safe_float(
            recent['high'].iloc[:-3].max()
        )

        swing_low = self._safe_float(
            recent['low'].iloc[:-3].min()
        )

        last = df.iloc[-1]

        close = self._safe_float(
            last['close']
        )

        prev_close = self._safe_float(
            df['close'].iloc[-2]
        )

        bos_long = (
            close > swing_high
        )

        bos_short = (
            close < swing_low
        )

        previous_range_high = self._safe_float(
            df['high'].iloc[-10:-3].max()
        )

        previous_range_low = self._safe_float(
            df['low'].iloc[-10:-3].min()
        )

        mss_long = (
            close > previous_range_high
            and prev_close <= previous_range_high
        )

        mss_short = (
            close < previous_range_low
            and prev_close >= previous_range_low
        )

        if bos_long:

            bias = "BULLISH"

        elif bos_short:

            bias = "BEARISH"

        elif mss_long:

            bias = "BULLISH"

        elif mss_short:

            bias = "BEARISH"

        else:

            bias = "NEUTRAL"

        return {
            "bias": bias,

            "bos": bool(
                bos_long or bos_short
            ),

            "choch": bool(
                mss_long or mss_short
            ),

            "mss": bool(
                mss_long or mss_short
            ),

            "bos_long": bool(bos_long),

            "bos_short": bool(bos_short),

            "mss_long": bool(mss_long),

            "mss_short": bool(mss_short),

            "swing_high": swing_high,

            "swing_low": swing_low
        }

    # =========================================================
    # LIQUIDITY
    # =========================================================

    def _liquidity(self, df):

        if df is None or len(df) < 25:

            return {
                "sweep_high": False,
                "sweep_low": False,
                "bias": "NEUTRAL",
                "high": 0,
                "low": 0
            }

        last = df.iloc[-1]

        previous = df.iloc[-21:-1]

        prior_high = self._safe_float(
            previous['high'].max()
        )

        prior_low = self._safe_float(
            previous['low'].min()
        )

        current_high = self._safe_float(
            last['high']
        )

        current_low = self._safe_float(
            last['
