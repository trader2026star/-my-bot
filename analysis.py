import time
import logging
import gc

import ccxt
import pandas as pd
import numpy as np


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# SMART MONEY TRADING ANALYST
# =========================================================

class SmartMoneyTradingAnalyst:

    def __init__(
        self,
        exchange_id="bingx",
        api_key="",
        secret_key=""
    ):

        exchange_class = getattr(ccxt, exchange_id)

        self.exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret_key,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap"
            }
        })

        # -----------------------------------------------------
        # BTC CACHE
        # لا نطلب BTC لكل عملة من جديد
        # -----------------------------------------------------

        self.btc_cache = None
        self.btc_cache_time = 0
        self.btc_cache_ttl = 60

        try:

            self.exchange.load_markets()

            logger.info(
                f"تم الاتصال بنجاح بمنصة "
                f"{exchange_id.upper()} وتحميل أسواق الـ Swap."
            )

        except Exception as e:

            logger.error(
                f"فشل الاتصال بالمنصة عند التهيئة: {e}"
            )

    # =========================================================
    # FETCH OHLCV
    # =========================================================

    def fetch_ohlcv_data(
        self,
        symbol,
        timeframe="1h",
        limit=100,
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
                        "timestamp",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume"
                    ]
                )

                df["timestamp"] = pd.to_datetime(
                    df["timestamp"],
                    unit="ms"
                )

                numeric_columns = [
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume"
                ]

                for col in numeric_columns:

                    df[col] = pd.to_numeric(
                        df[col],
                        errors="coerce"
                    )

                df = df.dropna().reset_index(drop=True)

                if len(df) < 30:
                    return None

                return df

            except Exception as e:

                logger.warning(
                    f"[RETRY {attempt + 1}] "
                    f"{symbol} {timeframe}: {e}"
                )

                if attempt < retries:
                    time.sleep(delay)

        return None

    # =========================================================
    # BTC CACHE
    # =========================================================

    def fetch_btc_cached(self):

        now = time.time()

        # استخدام البيانات الموجودة إذا لم تنتهِ مدة الـ Cache
        if (
            self.btc_cache is not None
            and
            (now - self.btc_cache_time) < self.btc_cache_ttl
        ):

            return self.btc_cache.copy()

        btc_df = self.fetch_ohlcv_data(
            "BTC/USDT:USDT",
            timeframe="1h",
            limit=40,
            retries=1,
            delay=0.5
        )

        if btc_df is not None:

            btc_df = self.calculate_indicators(
                btc_df
            )

            self.btc_cache = btc_df.copy()
            self.btc_cache_time = now

        return btc_df

    # =========================================================
    # INDICATORS
    # =========================================================

    def calculate_indicators(self, df):

        if df is None or len(df) < 20:
            return df

        try:

            prev_close = df["close"].shift(1)

            tr1 = (
                df["high"] -
                df["low"]
            )

            tr2 = (
                df["high"] -
                prev_close
            ).abs()

            tr3 = (
                df["low"] -
                prev_close
            ).abs()

            true_range = pd.concat(
                [tr1, tr2, tr3],
                axis=1
            ).max(axis=1)

            df["atr"] = true_range.rolling(
                window=14,
                min_periods=14
            ).mean()

            df["vol_ma"] = df["volume"].rolling(
                window=20,
                min_periods=20
            ).mean()

            df["volume_ratio"] = np.where(
                df["vol_ma"] > 0,
                df["volume"] / df["vol_ma"],
                1.0
            )

            df["high_volume"] = (
                df["volume_ratio"] >= 1.20
            )

            # -------------------------------------------------
            # SWINGS
            # -------------------------------------------------

            swing_window = 5

            df["is_swing_high"] = (
                df["high"]
                ==
                df["high"].rolling(
                    window=swing_window,
                    center=True
                ).max()
            )

            df["is_swing_low"] = (
                df["low"]
                ==
                df["low"].rolling(
                    window=swing_window,
                    center=True
                ).min()
            )

            # -------------------------------------------------
            # FVG
            # -------------------------------------------------

            df["bullish_fvg"] = (
                df["low"] >
                df["high"].shift(2)
            )

            df["bearish_fvg"] = (
                df["high"] <
                df["low"].shift(2)
            )

            # -------------------------------------------------
            # CANDLE BODY
            # -------------------------------------------------

            df["body"] = (
                df["close"] -
                df["open"]
            ).abs()

            df["bull_body"] = (
                (df["close"] > df["open"]) &
                (
                    df["body"] >
                    df["atr"] * 0.8
                )
            )

            df["bear_body"] = (
                (df["close"] < df["open"]) &
                (
                    df["body"] >
                    df["atr"] * 0.8
                )
            )

            # -------------------------------------------------
            # BODY / RANGE
            # -------------------------------------------------

            candle_range = (
                df["high"] -
                df["low"]
            ).replace(0, np.nan)

            df["body_ratio"] = (
                df["body"] /
                candle_range
            ).fillna(0)

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

            # -------------------------------------------------
            # CLOSED C
