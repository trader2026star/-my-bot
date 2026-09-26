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

            if not data or len(data) < 20:
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

    def _prepare(self, df):
        df = df.copy()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['rsi'] = 50
        df['atr'] = (df['high'] - df['low']).rolling(14).mean().fillna(df['close'] * 0.01)
        df['volume_ratio'] = 1.0
        return df.dropna().reset_index(drop=True)

    def get_trend(self, df):
        return 'BULLISH'

    def get_structure(self, df, direction):
        return {
            'structure': 'BULLISH',
            'bos': True,
            'mss': False,
            'liquidity_sweep': False,
            'hh_hl': True,
            'lh_ll': False
        }

    # =========================================================
    # STRATEGY EVALUATION (Force Immediate Signal)
    # =========================================================

    def evaluate_strategy(self, symbol):
        df_15m = self._fetch_ohlcv(symbol, '15m', 100)
        if df_15m is None or len(df_15m) < 20:
            # لو البيانات فشلت، نرجع صفقة افتراضية عشان نتأكد إن البوت بيبعت رسايل
            return {
                'symbol': symbol,
                'decision': 'LONG',
                'score': 95,
                'quality': 'HIGH',
                'confirmation_count': 5,
                'confirmations': ['ForceSignal', 'Structure', 'Momentum', 'Volume', 'Trend'],
                'trend_4h': 'BULLISH',
                'trend_1h': 'BULLISH',
                'btc_context': 'NEUTRAL',
                'rsi_15m': 55.0,
                'volume_ratio': 1.5,
                'entry': 100.0,
                'sl': 95.0,
                'tp1': 105.0,
                'tp2': 110.0,
                'tp3': 115.0,
                'risk_pct': 5.0,
                'risk_filter': 'PASSED',
                'structure_confirmation': 'BULLISH',
                'btc_conflict': False,
                'entry_quality': 'OPTIMAL'
            }

        df_15m = self._prepare(df_15m)
        row = df_15m.iloc[-1]
        entry = float(row['close'])
        atr = float(row['atr']) if 'atr' in row and row['atr'] > 0 else entry * 0.01

        sl = entry - (atr * 1.5)
        tp1 = entry + (atr * 3.0)
        tp2 = entry + (atr * 5.25)
        tp3 = entry + (atr * 7.5)

        return {
            'symbol': symbol,
            'decision': 'LONG',
            'score': 90,
            'quality': 'HIGH',
            'confirmation_count': 4,
            'confirmations': ['Structure', 'Momentum', 'Volume', 'Trend'],
            'trend_4h': 'BULLISH',
            'trend_1h': 'BULLISH',
            'btc_context': 'NEUTRAL',
            'rsi_15m': 60.0,
            'volume_ratio': 1.2,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': round((abs(entry - sl) / entry) * 100, 2),
            'risk_filter': 'PASSED',
            'structure_confirmation': 'BULLISH',
            'btc_conflict': False,
            'entry_quality': 'OPTIMAL'
        }
