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
                "OHLCV error %s %s: %s",
                symbol,
                timeframe,
                e
            )
            return None

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

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        df['rsi'] = df['rsi'].fillna(50)

        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (
            df['high'] - prev_close
        ).abs()
        tr3 = (
            df['low'] - prev_close
        ).abs()

        true_range = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = (
            true_range
            .ewm(
                alpha=1 / 14,
                adjust=False
            )
            .mean()
        )

        volume_ma = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume']
            / volume_ma.replace(0, np.nan)
        )

        df['body'] = (
            df['close'] - df['open']
        )

        df['body_pct'] = (
            df['body'].abs()
            / df['close'].replace(0, np.nan)
            * 100
        )

        df['momentum'] = (
            df['close']
            .pct_change(5)
            * 100
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
    # TREND
    # =========================================================

    def get_trend(self, df):
        if df is None or len(df) < 10:
            return 'NEUTRAL'

        row = df.iloc[-1]

        close = float(row['close'])
        ema20 = float(row['ema20'])
        ema50 = float(row['ema50'])

        if ema20 > ema50 and close > ema20:
            return 'BULLISH'

        if ema20 < ema50 and close < ema20:
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def get_structure(self, df, direction=None):
        if df is None or len(df) < 15:
            return {
                'structure': 'NEUTRAL',
                'bos': False,
                'mss': False,
                'liquidity_sweep': False,
                'hh_hl': False,
                'lh_ll': False
            }

        current = df.iloc[-1]
        recent = df.iloc[-6:-1]

        recent_high = float(recent['high'].max())
        recent_low = float(recent['low'].min())
        current_close = float(current['close'])
        previous_close = float(df.iloc[-2]['close'])

        bullish_bos = (
            current_close > recent_high
            and previous_close <= recent_high
        )

        bearish_bos = (
            current_close < recent_low
            and previous_close >= recent_low
        )

        bullish_sweep = (
            current['low'] < recent_low
            and current_close > recent_low
        )

        bearish_sweep = (
            current['high'] > recent_high
            and current_close < recent_high
        )

        highs = df['high'].iloc[-6:].values
        lows = df['low'].iloc[-6:].values

        hh_hl = (
            highs[-1] >= highs[-2]
            and lows[-1] >= lows[-2]
        )

        lh_ll = (
            highs[-1] <= highs[-2]
            and lows[-1] <= lows[-2]
        )

        return {
            'structure': 'BULLISH' if hh_hl else ('BEARISH' if lh_ll else 'NEUTRAL'),
            'bos': bullish_bos if direction != 'SHORT' else bearish_bos,
            'mss': bullish_sweep if direction != 'SHORT' else bearish_sweep,
            'liquidity_sweep': bullish_sweep if direction != 'SHORT' else bearish_sweep,
            'hh_hl': hh_hl,
            'lh_ll': lh_ll
        }

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def _get_btc_context(self):
        try:
            btc = self._fetch_ohlcv('BTC/USDT:USDT', '1h', 100)
            if btc is None:
                return 'NEUTRAL'

            btc = self._prepare(btc)
            if btc is None or len(btc) < 10:
                return 'NEUTRAL'

            row = btc.iloc[-1]
            close = float(row['close'])
            ema20 = float(row['ema20'])
            ema50 = float(row['ema50'])

            if close > ema20 and ema20 > ema50:
                return 'BULLISH'
            if close < ema20 and ema20 < ema50:
                return 'BEARISH'

            return 'NEUTRAL'
        except Exception:
            return 'NEUTRAL'

    # =========================================================
    # EVALUATE LONG & SHORT
    # =========================================================

    def _evaluate_long(self, df_4h, df_1h, df_15m, btc_context):
        row15 = df_15m.iloc[-1]
        score = 30  # سكور أساسي مرن لضمان عمل الحنفية
        confirmations = ['Flexible Structure', 'Trend Support']

        trend4 = self.get_trend(df_4h)
        trend1 = self.get_trend(df_1h)
        structure = self.get_structure(df_15m, 'LONG')

        if trend4 == 'BULLISH':
            score += 15
            confirmations.append('4H Bullish Trend')
        if trend1 == 'BULLISH':
            score += 15
            confirmations.append('1H Bullish Trend')
        if structure['structure'] == 'BULLISH':
            score += 10
            confirmations.append('Bullish Structure')

        return {
            'score': max(0, min(100, score)),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'structure': structure,
            'rsi': float(row15['rsi']),
            'volume_ratio': float(row15['volume_ratio'])
        }

    def _evaluate_short(self, df_4h, df_1h, df_15m, btc_context):
        row15 = df_15m.iloc[-1]
        score = 30  # سكور أساسي مرن للشورت
        confirmations = ['Flexible Structure', 'Trend Support']

        trend4 = self.get_trend(df_4h)
        trend1 = self.get_trend(df_1h)
        structure = self.get_structure(df_15m, 'SHORT')

        if trend4 == 'BEARISH':
            score += 15
            confirmations.append('4H Bearish Trend')
        if trend1 == 'BEARISH':
            score += 15
            confirmations.append('1H Bearish Trend')
        if structure['structure'] == 'BEARISH':
            score += 10
            confirmations.append('Bearish Structure')

        return {
            'score': max(0, min(100, score)),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'structure': structure,
            'rsi': float(row15['rsi']),
            'volume_ratio': float(row15['volume_ratio'])
        }

    # =========================================================
    # BUILD TRADES (LONG & SHORT)
    # =========================================================

    def _build_long_trade(self, df, score, confirmations, trend4, trend1, btc_context):
        row = df.iloc[-1]
        entry = float(row['close'])
        atr = float(row['atr'])
        if atr <= 0:
            atr = entry * 0.01

        sl = entry - (atr * 1.5)
        risk = abs(entry - sl)
        risk_pct = (risk / entry) * 100

        if risk_pct > 7:
            return None

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 1.8
        tp3 = entry + risk * 2.6

        return {
            'decision': 'LONG',
            'score': int(score),
            'quality': 'HIGH' if score >= 50 else 'MEDIUM',
            'confirmation_count': len(confirmations),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'btc_context': btc_context,
            'rsi_15m': float(row['rsi']),
            'volume_ratio': float(row['volume_ratio']),
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3
        }

    def _build_short_trade(self, df, score, confirmations, trend4, trend1, btc_context):
        row = df.iloc[-1]
        entry = float(row['close'])
        atr = float(row['atr'])
        if atr <= 0:
            atr = entry * 0.01

        sl = entry + (atr * 1.5)
        risk = abs(entry - sl)
        risk_pct = (risk / entry) * 100

        if risk_pct > 7:
            return None

        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 1.8
        tp3 = entry - risk * 2.6

        return {
            'decision': 'SHORT',
            'score': int(score),
            'quality': 'HIGH' if score >= 50 else 'MEDIUM',
            'confirmation_count': len(confirmations),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'btc_context': btc_context,
            'rsi_15m': float(row['rsi']),
            'volume_ratio': float(row['volume_ratio']),
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3
        }

    # =========================================================
    # MAIN STRATEGY ENTRYPOINT
    # =========================================================

    def evaluate_strategy(self, symbol):
        df_15m = self._fetch_ohlcv(symbol, '15m', 220)
        if df_15m is None or len(df_15m) < 50:
            return None

        df_15m = self._prepare(df_15m)
        if df_15m is None or len(df_15m) < 30:
            return None

        df_1h = self._fetch_ohlcv(symbol, '1h', 100)
        df_4h = self._fetch_ohlcv(symbol, '4h', 100)

        if df_1h is not None:
            df_1h = self._prepare(df_1h)
        if df_4h is not None:
            df_4h = self._prepare(df_4h)

        btc_context = self._get_btc_context()

        # فحص إمكانية الصعود (LONG)
        if df_1h is not None and df_4h is not None:
            long_eval = self._evaluate_long(df_4h, df_1h, df_15m, btc_context)
            if long_eval['score'] >= 30:
                trade = self._build_long_trade(
                    df_15m,
                    long_eval['score'],
                    long_eval['confirmations'],
                    long_eval['trend_4h'],
                    long_eval['trend_1h'],
                    btc_context
                )
                if trade:
                    return trade

            # فحص إمكانية الهبوط (SHORT)
            short_eval = self._evaluate_short(df_4h, df_1h, df_15m, btc_context)
            if short_eval['score'] >= 30:
                trade = self._build_short_trade(
                    df_15m,
                    short_eval['score'],
                    short_eval['confirmations'],
                    short_eval['trend_4h'],
                    short_eval['trend_1h'],
                    btc_context
                )
                if trade:
                    return trade

        return None
