import logging
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:
    def __init__(self, exchange_id='bingx', api_key='', secret_key='', timeframe='15m'):
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

        self.min_confirmations = 3
        self.min_score = 5

    # =========================================================
    # DATA
    # =========================================================

    def fetch_ohlcv_data(self, symbol, timeframe, limit=150):
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not ohlcv or len(ohlcv) < 50:
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

            return df

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

    def add_indicators(self, df):

        df = df.copy()

        df['ema20'] = df['close'].ewm(
            span=20,
            adjust=False
        ).mean()

        df['ema50'] = df['close'].ewm(
            span=50,
            adjust=False
        ).mean()

        df['ema200'] = df['close'].ewm(
            span=200,
            adjust=False
        ).mean()

        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()

        df['tr'] = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = df['tr'].rolling(14).mean()

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

        rs = avg_gain / avg_loss.replace(
            0,
            np.nan
        )

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        df['volume_ma20'] = df['volume'].rolling(
            20
        ).mean()

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma20'].replace(0, np.nan)
        )

        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['body_ma10'] = df['body'].rolling(
            10
        ).mean()

        return df

    # =========================================================
    # TREND
    # =========================================================

    def get_trend(self, df):

        if df is None or len(df) < 30:
            return 'NEUTRAL'

        row = df.iloc[-2]

        close = row['close']
        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

        bull = 0
        bear = 0

        if close > ema20:
            bull += 1
        elif close < ema20:
            bear += 1

        if ema20 > ema50:
            bull += 1
        elif ema20 < ema50:
            bear += 1

        if close > ema200:
            bull += 1
        elif close < ema200:
            bear += 1

        if bull >= 2:
            return 'BULLISH'

        if bear >= 2:
            return 'BEARISH'

        return 'NEUTRAL'

    # =========================================================
    # STRUCTURE
    # =========================================================

    def get_structure(self, df):

        result = {
            'bull_bos': False,
            'bear_bos': False,
            'bull_sweep': False,
            'bear_sweep': False,
            'bull_structure': False,
            'bear_structure': False
        }

        if df is None or len(df) < 40:
            return result

        i = len(df) - 2
        current = df.iloc[i]

        previous_high = df['high'].iloc[
            max(0, i - 12):i
        ].max()

        previous_low = df['low'].iloc[
            max(0, i - 12):i
        ].min()

        if current['close'] > previous_high:
            result['bull_bos'] = True

        if current['close'] < previous_low:
            result['bear_bos'] = True

        liquidity_high = df['high'].iloc[
            max(0, i - 8):i
        ].max()

        liquidity_low = df['low'].iloc[
            max(0, i - 8):i
        ].min()

        if (
            current['low'] < liquidity_low
            and current['close'] > liquidity_low
        ):
            result['bull_sweep'] = True

        if (
            current['high'] > liquidity_high
            and current['close'] < liquidity_high
        ):
            result['bear_sweep'] = True

        recent = df.iloc[
            max(0, i - 20):i
        ]

        if len(recent) >= 10:

            mid = len(recent) // 2

            first = recent.iloc[:mid]
            second = recent.iloc[mid:]

            first_high = first['high'].max()
            second_high = second['high'].max()

            first_low = first['low'].min()
            second_low = second['low'].min()

            if (
                second_high > first_high
                and second_low > first_low
            ):
                result['bull_structure'] = True

            if (
                second_high < first_high
                and second_low < first_low
            ):
                result['bear_structure'] = True

        return result

    # =========================================================
    # MOMENTUM
    # =========================================================

    def get_momentum(self, df):

        result = {
            'bullish': False,
            'bearish': False,
            'rsi': 50
        }

        if df is None or len(df) < 30:
            return result

        row = df.iloc[-2]

        rsi = row['rsi']

        if pd.isna(rsi):
            return result

        result['rsi'] = float(rsi)

        if (
            row['close'] > row['ema20']
            and 50 <= rsi <= 72
        ):
            result['bullish'] = True

        elif (
            row['close'] < row['ema20']
            and 28 <= rsi <= 50
        ):
            result['bearish'] = True

        return result

    # =========================================================
    # VOLUME
    # =========================================================

    def get_volume_confirmation(self, df):

        if df is None or len(df) < 25:
            return {
                'bullish': False,
                'bearish': False,
                'ratio': 0
            }

        row = df.iloc[-2]

        ratio = row['volume_ratio']

        if pd.isna(ratio):
            ratio = 0

        recent_ratio = df['volume_ratio'].iloc[
            -4:-1
        ].mean()

        if pd.isna(recent_ratio):
            recent_ratio = 0

        effective_ratio = max(
            float(ratio),
            float(recent_ratio)
        )

        confirmed = effective_ratio >= 1.05

        return {
            'bullish': (
                confirmed
                and row['close'] > row['open']
            ),
            'bearish': (
                confirmed
                and row['close'] < row['open']
            ),
            'ratio': round(
                effective_ratio,
                2
            )
        }

    # =========================================================
    # BREAKOUT
    # =========================================================

    def get_breakout_confirmation(self, df):

        result = {
            'bullish': False,
            'bearish': False
        }

        if df is None or len(df) < 30:
            return result

        i = len(df) - 2
        row = df.iloc[i]

        previous_high = df['high'].iloc[
            max(0, i - 10):i
        ].max()

        previous_low = df['low'].iloc[
            max(0, i - 10):i
        ].min()

        avg_body = df['body'].iloc[
            max(0, i - 10):i
        ].mean()

        if pd.isna(avg_body) or avg_body <= 0:
            avg_body = row['body']

        if (
            row['close'] > previous_high
            and row['close'] > row['open']
        ):
            result['bullish'] = True

        elif (
            row['close'] > row['open']
            and row['body'] >= avg_body * 1.25
        ):
            result['bullish'] = True

        if (
            row['close'] < previous_low
            and row['close'] < row['open']
        ):
            result['bearish'] = True

        elif (
            row['close'] < row['open']
            and row['body'] >= avg_body * 1.25
        ):
            result['bearish'] = True

        return result

    # =========================================================
    # BTC
    # =========================================================

    def get_btc_context(self):

        try:

            df = self.fetch_ohlcv_data(
                'BTC/USDT:USDT',
                '1h',
                100
            )

            if df is None:
                return 'NEUTRAL'

            df = self.add_indicators(df)

            return self.get_trend(df)

        except Exception:
            return 'NEUTRAL'

    # =========================================================
    # SCORE
    # =========================================================

    def calculate_scores(
        self,
        trend_4h,
        trend_1h,
        structure,
        momentum,
        volume,
        breakout,
        btc_context
    ):

        long_score = 0
        short_score = 0

        long_conf = []
        short_conf = []

        if trend_4h == 'BULLISH':
            long_score += 2
            long_conf.append('4H TREND')

        elif trend_4h == 'BEARISH':
            short_score += 2
            short_conf.append('4H TREND')

        if trend_1h == 'BULLISH':
            long_score += 1
            long_conf.append('1H TREND')

        elif trend_1h == 'BEARISH':
            short_score += 1
            short_conf.append('1H TREND')

        if structure['bull_bos']:
            long_score += 2
            long_conf.append('BULLISH BOS')

        if structure['bear_bos']:
            short_score += 2
            short_conf.append('BEARISH BOS')

        if structure['bull_sweep']:
            long_score += 1
            long_conf.append('LIQUIDITY SWEEP')

        if structure['bear_sweep']:
            short_score += 1
            short_conf.append('LIQUIDITY SWEEP')

        if structure['bull_structure']:
            long_score += 1
            long_conf.append('HH/HL')

        if structure['bear_structure']:
            short_score += 1
            short_conf.append('LH/LL')

        if momentum['bullish']:
            long_score += 1
            long_conf.append('MOMENTUM')

        if momentum['bearish']:
            short_score += 1
            short_conf.append('MOMENTUM')

        if volume['bullish']:
            long_score += 1
            long_conf.append('VOLUME')

        if volume['bearish']:
            short_score += 1
            short_conf.append('VOLUME')

        if breakout['bullish']:
            long_score += 1
            long_conf.append('BREAKOUT')

        if breakout['bearish']:
            short_score += 1
            short_conf.append('BREAKOUT')

        if btc_context == 'BULLISH':
            long_score += 1
            long_conf.append('BTC SUPPORT')
            short_score -= 1

        elif btc_context == 'BEARISH':
            short_score += 1
            short_conf.append('BTC SUPPORT')
            long_score -= 1

        return {
            'long_score': long_score,
            'short_score': short_score,
            'long_conf': long_conf,
            'short_conf': short_conf
        }

    # =========================================================
    # RISK / LEVELS
    # =========================================================

    def build_levels(self, df, direction):

        if df is None or len(df) < 30:
            return None

        row = df.iloc[-2]

        entry = float(row['close'])
        atr = float(row['atr'])

        if pd.isna(atr) or atr <= 0:
            return None

        recent = df.iloc[-12:-1]

        recent_low = float(
            recent['low'].min()
        )

        recent_high = float(
            recent['high'].max()
        )

        if direction == 'LONG':

            structural_sl = (
                recent_low -
                atr * 0.20
            )

            atr_sl = (
                entry -
                atr * 1.35
            )

            stop_loss = min(
                structural_sl,
                atr_sl
            )

            risk = entry - stop_loss

            if risk <= 0:
                return None

            risk_pct = (
                risk / entry
            ) * 100

            if risk_pct > 6.0:

                stop_loss = (
                    entry -
                    atr * 1.50
                )

                risk = entry - stop_loss

                if risk <= 0:
                    return None

                risk_pct = (
                    risk / entry
                ) * 100

            if risk_pct > 6.5:
                return None

            tp1 = entry + risk * 2
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5

        else:

            structural_sl = (
                recent_high +
                atr * 0.20
            )

            atr_sl = (
                entry +
                atr * 1.35
            )

            stop_loss = max(
                structural_sl,
                atr_sl
            )

            risk = stop_loss - entry

            if risk <= 0:
                return None

            risk_pct = (
                risk / entry
            ) * 100

            if risk_pct > 6.0:

                stop_loss = (
                    entry +
                    atr * 1.50
                )

                risk = stop_loss - entry

                if risk <= 0:
                    return None

                risk_pct = (
                    risk / entry
                ) * 100

            if risk_pct > 6.5:
                return None

            tp1 = entry - risk * 2
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5

        return {
            'entry': entry,
            'sl': stop_loss,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': risk_pct
        }

    # =========================================================
    # ANTI CHASE
    # =========================================================

    def is_overextended(self, df):

        if df is None or len(df) < 30:
            return True

        row = df.iloc[-2]

        atr = row['atr']

        if pd.isna(atr) or atr <= 0:
            return False

        body = abs(
            row['close'] -
            row['open']
        )

        return body > atr * 3.0

    # =========================================================
    # FORMAT
    # =========================================================

    def format_price(self, value):

        value = float(value)

        if value >= 1000:
            return round(value, 2)

        if value >= 1:
            return round(value, 4)

        if value >= 0.1:
            return round(value, 5)

        if value >= 0.01:
            return round(value, 6)

        if value >= 0.001:
            return round(value, 7)

        return round(value, 9)

    # =========================================================
    # MAIN ANALYSIS
    # =========================================================

    def evaluate_strategy(self, symbol):

        try:

            df_4h = self.fetch_ohlcv_data(
                symbol,
                '4h',
                150
            )

            df_1h = self.fetch_ohlcv_data(
                symbol,
                '1h',
                150
            )

            df_15m = self.fetch_ohlcv_data(
                symbol,
                '15m',
                150
            )

            if (
                df_4h is None
                or df_1h is None
                or df_15m is None
            ):
                return None

            df_4h = self.add_indicators(df_4h)
            df_1h = self.add_indicators(df_1h)
            df_15m = self.add_indicators(df_15m)

            trend_4h = self.get_trend(df_4h)
            trend_1h = self.get_trend(df_1h)

            structure_1h = self.get_structure(df_1h)
            structure_15m = self.get_structure(df_15m)

            structure = {
                'bull_bos': (
                    structure_1h['bull_bos']
                    or structure_15m['bull_bos']
                ),
                'bear_bos': (
                    structure_1h['bear_bos']
                    or structure_15m['bear_bos']
                ),
                'bull_sweep': (
                    structure_1h['bull_sweep']
                    or structure_15m['bull_sweep']
                ),
                'bear_sweep': (
                    structure_1h['bear_sweep']
                    or structure_15m['bear_sweep']
                ),
                'bull_structure': (
                    structure_1h['bull_structure']
                    or structure_15m['bull_structure']
                ),
                'bear_structure': (
                    structure_1h['bear_structure']
                    or structure_15m['bear_structure']
                )
            }

            momentum = self.get_momentum(df_15m)
            volume = self.get_volume_confirmation(df_15m)
            breakout = self.get_breakout_confirmation(df_15m)

            btc_context = self.get_btc_context()

            if self.is_overextended(df_15m):
                logger.info(
                    "%s rejected: overextended",
                    symbol
                )
                return None

            scores = self.calculate_scores(
                trend_4h,
                trend_1h,
                structure,
                momentum,
                volume,
                breakout,
                btc_context
            )

            long_score = scores['long_score']
            short_score = scores['short_score']

            long_conf = scores['long_conf']
            short_conf = scores['short_conf']

            if (
                long_score >= self.min_score
                and long_score > short_score
                and len(long_conf) >= self.min_confirmations
            ):

                direction = 'LONG'
                score = long_score
                confirmations = long_conf

            elif (
                short_score >= self.min_score
                and short_score > long_score
                and len(short_conf) >= self.min_confirmations
            ):

                direction = 'SHORT'
                score = short_score
                confirmations = short_conf

            else:
                return None

            if direction == 'LONG':

                structural = (
                    structure['bull_bos']
                    or structure['bull_sweep']
                    or structure['bull_structure']
                    or breakout['bullish']
                )

            else:

                structural = (
                    structure['bear_bos']
                    or structure['bear_sweep']
                    or structure['bear_structure']
                    or breakout['bearish']
                )

            if not structural:
                return None

            levels = self.build_levels(
                df_15m,
                direction
            )

            if levels is None:
                return None

            if score >= 8 and len(confirmations) >= 5:
                quality = 'HIGH PROBABILITY'

            elif score >= 6 and len(confirmations) >= 4:
                quality = 'STRONG'

            else:
                quality = 'VALID SETUP'

            entry = levels['entry']
            sl = levels['sl']
            tp1 = levels['tp1']
            tp2 = levels['tp2']
            tp3 = levels['tp3']
            risk_pct = levels['risk_pct']

            symbol_name = symbol.split('/')[0]

            report = f"""
🚨 EXPERT FUTURES SIGNAL 🚨

📊 Symbol: {symbol_name}
🎯 Decision: {direction}
⭐ Score: {score}
🏷 Quality: {quality}

📌 Confirmations: {len(confirmations)}/3+
🧠 {', '.join(confirmations)}

📈 4H Trend: {trend_4h}
📊 1H Trend: {trend_1h}
₿ BTC Context: {btc_context}

💪 RSI 15M: {momentum['rsi']:.1f}
🔊 Volume: {volume['ratio']:.2f}x

💰 Entry: {self.format_price(entry)}
🛑 SL: {self.format_price(sl)} ({risk_pct:.2f}%)

🎯 TP1: {self.format_price(tp1)} | R:R 1:2
🎯 TP2: {self.format_price(tp2)} | R:R 1:3.5
🎯 TP3: {self.format_price(tp3)} | R:R 1:5

🛡 Risk Filter: PASS
📋 Structure Confirmation: PASS

⚠️ Setup signal — not a guaranteed result.
""".strip()

            return {
                'Decision': report,
                'Symbol': symbol,
                'Direction': direction,
                'Score': score,
                'Quality': quality,
                'Entry': entry,
                'StopLoss': sl,
                'TP1': tp1,
                'TP2': tp2,
                'TP3': tp3,
                'RiskPct': risk_pct,
                'Confirmations': confirmations,
                'Trend4H': trend_4h,
                'Trend1H': trend_1h,
                'BTCContext': btc_context
            }

        except Exception as e:

            logger.exception(
                "Analysis error %s: %s",
                symbol,
                e
            )

            return None
