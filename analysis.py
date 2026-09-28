import logging
import time
import math
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:

    # =========================================================
    # INIT — KEEP CONNECTION INTERFACE
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

    def _empty_response(self, reason="NO TRADE", diagnostics=None):
        """
        IMPORTANT:
        Preserve actual analysis diagnostics instead of returning
        fake score=0 / neutral data.
        """

        diagnostics = diagnostics or {}

        return {
            "decision": "NO TRADE",
            "score": int(diagnostics.get("score", 0)),
            "quality": diagnostics.get("quality", "WEAK"),
            "reason": reason,
            "rejection_reason": reason,

            "confirmations": diagnostics.get("confirmations", []),
            "confirmation_count": len(diagnostics.get("confirmations", [])),

            "trend_4h": diagnostics.get("trend_4h", "NEUTRAL"),
            "trend_1h": diagnostics.get("trend_1h", "NEUTRAL"),
            "trend_15m": diagnostics.get("trend_15m", "NEUTRAL"),

            "btc_context": diagnostics.get("btc_context", "BTC_NEUTRAL"),

            "market_regime": diagnostics.get(
                "market_regime", "UNKNOWN"
            ),

            "structure_type": diagnostics.get(
                "structure_type", "NEUTRAL"
            ),

            "structure": diagnostics.get(
                "structure", {}
            ),

            "liquidity": diagnostics.get(
                "liquidity", {}
            ),

            "order_block": diagnostics.get(
                "order_block", None
            ),

            "fvg": diagnostics.get(
                "fvg", None
            ),

            "funding_rate": self._safe_float(
                diagnostics.get("funding_rate", 0)
            ),

            "oi_change_pct": self._safe_float(
                diagnostics.get("oi_change_pct", 0)
            ),

            "price_change_pct": self._safe_float(
                diagnostics.get("price_change_pct", 0)
            ),

            "derivatives_bias": diagnostics.get(
                "derivatives_bias", "NEUTRAL"
            ),

            "rsi": self._safe_float(
                diagnostics.get("rsi", 50)
            ),

            "volume_ratio": self._safe_float(
                diagnostics.get("volume_ratio", 0)
            ),

            "atr": self._safe_float(
                diagnostics.get("atr", 0)
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
                "digital_data", {}
            ),

            "candlestick": diagnostics.get(
                "candlestick", {}
            ),

            "symbol": diagnostics.get("symbol", ""),

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
        try:
            cache_key = f"ohlcv:{market_type}:{symbol}:{timeframe}:{limit}"
            now = time.time()

            cached = self.cache.get(cache_key)

            if cached:
                ts, data = cached
                if now - ts < self.cache_seconds:
                    return data.copy()

            original_type = self.exchange.options.get(
                'defaultType',
                'swap'
            )

            self.exchange.options['defaultType'] = market_type

            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            self.exchange.options['defaultType'] = original_type

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

        # EMAs
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

        # EMA slope
        df['ema20_slope'] = (
            df['ema20']
            .pct_change(5)
            * 100
        )

        df['ema50_slope'] = (
           
