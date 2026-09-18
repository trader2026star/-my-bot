import time
import ccxt
import pandas as pd
import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SmartMoneyTradingAnalyst:

    def __init__(self, exchange_id='bingx', api_key='', secret_key=''):
        exchange_class = getattr(ccxt, exchange_id)

        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'
            }
        })

        try:
            self.exchange.load_markets()
            logger.info(
                f"تم الاتصال بنجاح بمنصة {exchange_id.upper()} "
                f"وتحميل أسواق الـ Swap."
            )
        except Exception as e:
            logger.error(f"فشل الاتصال بالمنصة عند التهيئة: {e}")

    # =========================================================
    # FETCH DATA
    # =========================================================

    def fetch_ohlcv_data(
        self,
        symbol,
        timeframe='1h',
        limit=150,
        retries=2,
        delay=1
    ):
        for attempt in range(retries + 1):
            try:
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    limit=limit
                )

                if not ohlcv or len(ohlcv) < 30:
                    return None

                df = pd.DataFrame(
                    ohlcv,
                    columns=[
                        'timestamp',
                        'open',
                        'high',
                        'low',
                        'close',
                        'volume'
                    ]
                )

                df['timestamp'] = pd.to_datetime(
                    df['timestamp'],
                    unit='ms'
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

                df = df.dropna().reset_index(drop=True)

                if len(df) < 30:
                    return None

                return df

            except Exception as e:
                logger.warning(
                    f"[RETRY {attempt + 1}] "
                    f"Failed fetching {symbol} {timeframe}: {e}"
                )

                if attempt < retries:
                    time.sleep(delay)

        return None

    # =========================================================
    # INDICATORS
    # =========================================================

    def calculate_indicators(self, df):

        if df is None or len(df) < 20:
            return df

        try:

            prev_close = df['close'].shift(1)

            tr1 = df['high'] - df['low']
            tr2 = (df['high'] - prev_close).abs()
            tr3 = (df['low'] - prev_close).abs()

            true_range = pd.concat(
                [tr1, tr2, tr3],
                axis=1
            ).max(axis=1)

            df['atr'] = true_range.rolling(
                window=14,
                min_periods=14
            ).mean()

            df['vol_ma'] = df['volume'].rolling(
                window=20,
                min_periods=20
            ).mean()

            df['volume_ratio'] = np.where(
                df['vol_ma'] > 0,
                df['volume'] / df['vol_ma'],
                1.0
            )

            df['high_volume'] = (
                df['volume_ratio'] >= 1.20
            )

            # -------------------------------------------------
            # SWINGS
            # -------------------------------------------------

            swing_window = 5

            df['is_swing_high'] = (
                df['high'] ==
                df['high'].rolling(
                    window=swing_window,
                    center=True
                ).max()
            )

            df['is_swing_low'] = (
                df['low'] ==
                df['low'].rolling(
                    window=swing_window,
                    center=True
                ).min()
            )

            # -------------------------------------------------
            # FVG
            # -------------------------------------------------

            df['bullish_fvg'] = (
                df['low'] >
                df['high'].shift(2)
            )

            df['bearish_fvg'] = (
                df['high'] <
                df['low'].shift(2)
            )

            # -------------------------------------------------
            # CANDLE BODY / DISPLACEMENT
            # -------------------------------------------------

            df['body'] = (
                df['close'] - df['open']
            ).abs()

            df['bull_body'] = (
                (df['close'] > df['open']) &
                (df['body'] > df['atr'] * 0.8)
            )

            df['bear_body'] = (
                (df['close'] < df['open']) &
                (df['body'] > df['atr'] * 0.8)
            )

        except Exception as e:
            logger.error(
                f"خطأ في حساب المؤشرات: {e}"
            )

        return df

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def get_market_structure(self, df):

        if df is None or len(df) < 25:
            return (
                "NEUTRAL",
                False,
                False,
                False,
                False
            )

        try:

            # نستبعد آخر شمعة لأنها قد تكون غير مكتملة
            closed_df = df.iloc[:-1].copy()

            swing_highs = closed_df[
                closed_df['is_swing_high'] == True
            ]

            swing_lows = closed_df[
                closed_df['is_swing_low'] == True
            ]

            if (
                len(swing_highs) < 3 or
                len(swing_lows) < 3
            ):
                return (
                    "NEUTRAL",
                    False,
                    False,
                    False,
                    False
                )

            last_high = swing_highs.iloc[-1]
            prev_high = swing_highs.iloc[-2]

            last_low = swing_lows.iloc[-1]
            prev_low = swing_lows.iloc[-2]

            last_close = closed_df.iloc[-1]['close']

            # -------------------------------------------------
            # STRUCTURE
            # -------------------------------------------------

            higher_high = (
                last_high['high'] >
                prev_high['high']
            )

            higher_low = (
                last_low['low'] >
                prev_low['low']
            )

            lower_high = (
                last_high['high'] <
                prev_high['high']
            )

            lower_low = (
                last_low['low'] <
                prev_low['low']
            )

            if higher_high and higher_low:
                trend = "BULLISH"

            elif lower_high and lower_low:
                trend = "BEARISH"

            else:
                trend = "NEUTRAL"

            # -------------------------------------------------
            # BOS
            # -------------------------------------------------

            bullish_bos = (
                last_close >
                prev_high['high']
            )

            bearish_bos = (
                last_close <
                prev_low['low']
            )

            # -------------------------------------------------
            # MSS
            #
            # MSS = break against previous structure.
            # IMPORTANT:
            # Bullish MSS must be bullish.
            # Bearish MSS must be bearish.
            # -------------------------------------------------

            bullish_mss = (
                bearish_low_break := (
                    last_close >
                    last_high['high']
                )
            ) and (
                trend == "BEARISH"
            )

            bearish_mss = (
                bearish_high_break := (
                    last_close <
                    last_low['low']
                )
            ) and (
                trend == "BULLISH"
            )

            # -------------------------------------------------
            # Better MSS confirmation:
            # use recent structural break rather than simply
            # assigning opposite labels.
            # -------------------------------------------------

            recent_high = closed_df[
                'high'
            ].iloc[-8:-1].max()

            recent_low = closed_df[
                'low'
            ].iloc[-8:-1].min()

            bullish_mss = (
                trend == "BEARISH" and
                last_close > recent_high
            )

            bearish_mss = (
                trend == "BULLISH" and
                last_close < recent_low
            )

            return (
                trend,
                bool(bullish_bos),
                bool(bearish_bos),
                bool(bullish_mss),
                bool(bearish_mss)
            )

        except Exception as e:
            logger.warning(
                f"Structure error: {e}"
            )

            return (
                "NEUTRAL",
                False,
                False,
                False,
                False
            )

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df):

        if df is None or len(df) < 25:
            return False, False, 0.0, 0.0

        try:

            current_price = df.iloc[-1]['close']

            atr = df.iloc[-2].get(
                'atr',
                current_price * 0.01
            )

            if pd.isna(atr) or atr <= 0:
                atr = current_price * 0.01

            bull_found = False
            bear_found = False

            bull_level = 0.0
            bear_level = 0.0

            # Search recent closed candles
            start = max(3, len(df) - 20)
            end = len(df) - 2

            for i in range(end - 1, start - 1, -1):

                row = df.iloc[i]
                next_row = df.iloc[i + 1]

                # Bullish OB:
                # bearish candle followed by meaningful bullish
                # displacement.
                if (
                    row['close'] < row['open'] and
                    next_row['close'] > next_row['open']
                ):

                    next_body = abs(
                        next_row['close'] -
                        next_row['open']
                    )

                    if next_body >= atr * 0.6:

                        ob_low = row['low']
                        ob_high = row['open']

                        if (
                            ob_low <= current_price <= ob_high
                            or
                            abs(current_price - ob_high) <= atr * 2.5
                        ):
                            bull_found = True
                            bull_level = (
                                ob_low + ob_high
                            ) / 2

                            break

            for i in range(end - 1, start - 1, -1):

                row = df.iloc[i]
                next_row = df.iloc[i + 1]

                # Bearish OB
                if (
                    row['close'] > row['open'] and
                    next_row['close'] < next_row['open']
                ):

                    next_body = abs(
                        next_row['close'] -
                        next_row['open']
                    )

                    if next_body >= atr * 0.6:

                        ob_low = row['open']
                        ob_high = row['high']

                        if (
                            ob_low <= current_price <= ob_high
                            or
                            abs(current_price - ob_low) <= atr * 2.5
                        ):
                            bear_found = True
                            bear_level = (
                                ob_low + ob_high
                            ) / 2

                            break

            return (
                bull_found,
                bear_found,
                bull_level,
                bear_level
            )

        except Exception as e:
            logger.warning(
                f"OB detection error: {e}"
            )

            return False, False, 0.0, 0.0

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def check_liquidity_sweep(self, df):

        if df is None or len(df) < 15:
            return False, False

        try:

            closed = df.iloc[:-1]

            recent_high = closed[
                'high'
            ].iloc[-12:-1].max()

            recent_low = closed[
                'low'
            ].iloc[-12:-1].min()

            candle = closed.iloc[-1]

            sweep_high = (
                candle['high'] > recent_high and
                candle['close'] < recent_high and
                candle['close'] < candle['open']
            )

            sweep_low
