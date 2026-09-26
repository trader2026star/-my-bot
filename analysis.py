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

        # =====================================================
        # CONNECTION - KEEPING EXISTING INTERFACE
        # =====================================================

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

        # EMA
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

        # RSI
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

        # ATR - Wilder style
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

        # Volume ratio
        volume_ma = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume']
            / volume_ma.replace(0, np.nan)
        )

        # Candle body
        df['body'] = (
            df['close'] - df['open']
        )

        df['body_pct'] = (
            df['body'].abs()
            / df['close'].replace(0, np.nan)
            * 100
        )

        # Momentum
        df['momentum'] = (
            df['close']
            .pct_change(5)
            * 100
        )

        # Rolling highs/lows
        df['swing_high'] = (
            df['high']
            .rolling(10)
            .max()
        )

        df['swing_low'] = (
            df['low']
            .rolling(10)
            .min()
        )

        # Previous structure levels
        df['prev_high'] = (
            df['high']
            .shift(1)
            .rolling(10)
            .max()
        )

        df['prev_low'] = (
            df['low']
            .shift(1)
            .rolling(10)
            .min()
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

        recent_high = float(
            recent['high'].max()
        )

        recent_low = float(
            recent['low'].min()
        )

        current_high = float(
            current['high']
        )

        current_low = float(
            current['low']
        )

        current_close = float(
            current['close']
        )

        previous_close = float(
            df.iloc[-2]['close']
        )

        # -----------------------------------------------------
        # Break of structure
        # -----------------------------------------------------

        bullish_bos = (
            current_close > recent_high
            and previous_close <= recent_high
        )

        bearish_bos = (
            current_close < recent_low
            and previous_close >= recent_low
        )

        # -----------------------------------------------------
        # Liquidity sweep
        # -----------------------------------------------------

        bullish_sweep = (
            current_low < recent_low
            and current_close > recent_low
        )

        bearish_sweep = (
            current_high > recent_high
            and current_close < recent_high
        )

        # -----------------------------------------------------
        # Recent candle sequence
        # -----------------------------------------------------

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

        bullish_score = 0
        bearish_score = 0

        if bullish_bos:
            bullish_score += 2

        if bearish_bos:
            bearish_score += 2

        if bullish_sweep:
            bullish_score += 1

        if bearish_sweep:
            bearish_score += 1

        if hh_hl:
            bullish_score += 1

        if lh_ll:
            bearish_score += 1

        if bullish_score > bearish_score:
            structure = 'BULLISH'

        elif bearish_score > bullish_score:
            structure = 'BEARISH'

        else:
            structure = 'NEUTRAL'

        return {
            'structure': structure,
            'bos': (
                bullish_bos
                if direction != 'SHORT'
                else bearish_bos
            ),
            'mss': (
                bullish_sweep
                if direction != 'SHORT'
                else bearish_sweep
            ),
            'liquidity_sweep': (
                bullish_sweep
                if direction != 'SHORT'
                else bearish_sweep
            ),
            'hh_hl': hh_hl,
            'lh_ll': lh_ll
        }

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def _get_btc_context(self):

        try:

            btc = self._fetch_ohlcv(
                'BTC/USDT:USDT',
                '1h',
                100
            )

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

        except Exception as e:

            logger.warning(
                "BTC context error: %s",
                e
            )

            return 'NEUTRAL'

    # =========================================================
    # SCORE COMPONENTS
    # =========================================================

    def _evaluate_long(
        self,
        df_4h,
        df_1h,
        df_15m,
        btc_context
    ):

        row4 = df_4h.iloc[-1]
        row1 = df_1h.iloc[-1]
        row15 = df_15m.iloc[-1]

        score = 0
        confirmations = []

        # =====================================================
        # 4H TREND
        # =====================================================

        trend4 = self.get_trend(df_4h)

        if trend4 == 'BULLISH':
            score += 20
            confirmations.append('4H Bullish Trend')

        elif trend4 == 'BEARISH':
            score -= 25

        # =====================================================
        # 1H TREND
        # =====================================================

        trend1 = self.get_trend(df_1h)

        if trend1 == 'BULLISH':
            score += 15
            confirmations.append('1H Bullish Trend')

        elif trend1 == 'BEARISH':
            score -= 20

        # =====================================================
        # 15M STRUCTURE
        # =====================================================

        structure = self.get_structure(
            df_15m,
            'LONG'
        )

        if structure['structure'] == 'BULLISH':
            score += 15
            confirmations.append('Bullish Structure')

        elif structure['structure'] == 'BEARISH':
            score -= 20

        if structure['bos']:
            score += 8
            confirmations.append('Bullish BOS')

        if structure['mss']:
            score += 5
            confirmations.append('Bullish MSS/Sweep')

        # =====================================================
        # MOMENTUM
        # =====================================================

        momentum = float(
            row15['momentum']
        )

        rsi = float(
            row15['rsi']
        )

        if momentum > 0:
            score += 8
            confirmations.append('Positive Momentum')

        if 52 <= rsi <= 68:
            score += 7
            confirmations.append('Healthy RSI')

        elif rsi > 75:
            score -= 10

        elif rsi < 40:
            score -= 5

        # =====================================================
        # VOLUME
        # =====================================================

        volume_ratio = float(
            row15['volume_ratio']
        )

        if volume_ratio >= 1.20:
            score += 7
            confirmations.append('Volume Expansion')

        elif volume_ratio >= 1.05:
            score += 4
            confirmations.append('Volume Support')

        # =====================================================
        # BTC CONTEXT
        # =====================================================

        if btc_context == 'BULLISH':
            score += 8
            confirmations.append('BTC Bullish')

        elif btc_context == 'BEARISH':
            score -= 12

        # =====================================================
        # ALIGNMENT
        # =====================================================

        if (
            trend4 == 'BULLISH'
            and trend1 == 'BULLISH'
        ):
            score += 7
            confirmations.append('MTF Alignment')

        return {
            'score': max(0, min(100, score)),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'structure': structure,
            'rsi': rsi,
            'volume_ratio': volume_ratio
        }

    # =========================================================
    # SHORT EVALUATION
    # =========================================================

    def _evaluate_short(
        self,
        df_4h,
        df_1h,
        df_15m,
        btc_context
    ):

        row4 = df_4h.iloc[-1]
        row1 = df_1h.iloc[-1]
        row15 = df_15m.iloc[-1]

        score = 0
        confirmations = []

        # =====================================================
        # 4H TREND
        # =====================================================

        trend4 = self.get_trend(df_4h)

        if trend4 == 'BEARISH':
            score += 20
            confirmations.append('4H Bearish Trend')

        elif trend4 == 'BULLISH':
            score -= 25

        # =====================================================
        # 1H TREND
        # =====================================================

        trend1 = self.get_trend(df_1h)

        if trend1 == 'BEARISH':
            score += 15
            confirmations.append('1H Bearish Trend')

        elif trend1 == 'BULLISH':
            score -= 20

        # =====================================================
        # 15M STRUCTURE
        # =====================================================

        structure = self.get_structure(
            df_15m,
            'SHORT'
        )

        if structure['structure'] == 'BEARISH':
            score += 15
            confirmations.append('Bearish Structure')

        elif structure['structure'] == 'BULLISH':
            score -= 20

        if structure['bos']:
            score += 8
            confirmations.append('Bearish BOS')

        if structure['mss']:
            score += 5
            confirmations.append('Bearish MSS/Sweep')

        # =====================================================
        # MOMENTUM
        # =====================================================

        momentum = float(
            row15['momentum']
        )

        rsi = float(
            row15['rsi']
        )

        if momentum < 0:
            score += 8
            confirmations.append('Negative Momentum')

        # RSI alone DOES NOT create a SHORT.
        if 32 <= rsi <= 48:
            score += 7
            confirmations.append('Bearish RSI')

        elif rsi < 25:
            score -= 8

        elif rsi > 70:
            score -= 3

        # =====================================================
        # VOLUME
        # =====================================================

        volume_ratio = float(
            row15['volume_ratio']
        )

        if volume_ratio >= 1.20:
            score += 7
            confirmations.append('Volume Expansion')

        elif volume_ratio >= 1.05:
            score += 4
            confirmations.append('Volume Support')

        # =====================================================
        # BTC CONTEXT
        # =====================================================

        if btc_context == 'BEARISH':
            score += 8
            confirmations.append('BTC Bearish')

        elif btc_context == 'BULLISH':
            score -= 12

        # =====================================================
        # ALIGNMENT
        # =====================================================

        if (
            trend4 == 'BEARISH'
            and trend1 == 'BEARISH'
        ):
            score += 7
            confirmations.append('MTF Alignment')

        return {
            'score': max(0, min(100, score)),
            'confirmations': confirmations,
            'trend_4h': trend4,
            'trend_1h': trend1,
            'structure': structure,
            'rsi': rsi,
            'volume_ratio': volume_ratio
        }

    # =========================================================
    # ATR / ENTRY / RISK
    # =========================================================

    def _build_long_trade(
        self,
        df,
        score,
        confirmations,
        trend4,
        trend1,
        btc_context
    ):

        row = df.iloc[-1]

        entry = float(
            row['close']
        )

        atr = float(
            row['atr']
        )

        if atr <= 0:
            atr = entry * 0.01

        recent_low = float(
            df['low']
            .iloc[-8:]
            .min()
        )

        # Structural stop with ATR protection
        structural_sl = (
            recent_low - atr * 0.35
        )

        atr_sl = (
            entry - atr * 1.5
        )

        sl = min(
            structural_sl,
            atr_sl
        )

        # Safety
        if sl >= entry:
            sl = entry - atr * 1.5

        risk = abs(
            entry - sl
        )

        risk_pct = (
            risk / entry * 100
        )

        # Reject abnormal risk
        if risk_pct > 7:
            return None

        if risk_pct < 0.25:
            sl = entry - atr
            risk = abs(entry - sl)
            risk_pct = risk / entry * 100

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 1.8
        tp3 = entry + risk * 2.6

        quality = (
            'HIGH'
            if score >= 82
            else 'MEDIUM'
            if score >= 72
            else 'LOW'
        )

        return {
            'decision': 'LONG',
            'score': int(score),
            'quality': quality,
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
