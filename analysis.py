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

    def _decision_to_trend(self, decision):
        if decision == 'LONG':
            return 'BULLISH'
        if decision == 'SHORT':
            return 'BEARISH'
        return 'NEUTRAL'

    # =========================================================
    # DATA
    # =========================================================

    def _fetch_ohlcv(self, symbol, timeframe, limit=220):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF',
            'NZD', 'NCFX', 'USDCUSD'
        ]

        if any(token in symbol.upper() for token in unwanted_tokens):
            return None

        key = f"{symbol}:{timeframe}:{limit}"
        now = time.time()
        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 30:
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

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna().reset_index(drop=True)

            if len(df) < 30:
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

        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        prev_close = df['close'].shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs()
        ], axis=1).max(axis=1)

        df['atr'] = tr.ewm(span=14, adjust=False).mean()

        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma'].replace(0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(1.0)

        df['body'] = (df['close'] - df['open']).abs()
        df['range'] = (df['high'] - df['low']).replace(0, np.nan)
        df['body_ratio'] = (df['body'] / df['range']).fillna(0)

        return df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)

    # =========================================================
    # DIGITAL ANALYSIS (التحليل الرقمي وفيبوناتشي)
    # =========================================================

    def detect_digital_levels(self, df):
        if df is None or len(df) < 30:
            return None

        recent = df.tail(50)
        high_val = float(recent['high'].max())
        low_val = float(recent['low'].min())
        diff = high_val - low_val
        current_price = float(df['close'].iloc[-1])

        if diff <= 0:
            return None

        # حساب مستويات فيبوناتشي التصحيحية
        fib_levels = {
            'fib_382': high_val - (diff * 0.382),
            'fib_500': high_val - (diff * 0.5),
            'fib_618': high_val - (diff * 0.618),
            'fib_786': high_val - (diff * 0.786)
        }

        # فحص هل السعر الحالي قريب من أي مستوى رقمي/فيبوناتشي بنسبة أقل من 0.8%
        near_level = False
        active_fib = None
        for name, level in fib_levels.items():
            if abs(current_price - level) / current_price <= 0.008:
                near_level = True
                active_fib = name
                break

        return {
            'high': high_val,
            'low': low_val,
            'levels': fib_levels,
            'near_digital_level': near_level,
            'active_fib': active_fib
        }

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def _structure(self, df, lookback=30):
        if df is None or len(df) < 12:
            return 'NEUTRAL', False, False

        x = df.tail(lookback)

        swing_high = x['high'].iloc[:-3].max()
        swing_low = x['low'].iloc[:-3].min()

        last = x.iloc[-1]
        prev = x.iloc[-2]

        bullish_break = (
            last['close'] > swing_high and
            last['close'] > prev['high']
        )

        bearish_break = (
            last['close'] < swing_low and
            last['close'] < prev['low']
        )

        if bullish_break:
            return 'BULLISH', True, False

        if bearish_break:
            return 'BEARISH', False, True

        ema20_slope = x['ema20'].iloc[-1] - x['ema20'].iloc[-5]
        ema50_slope = x['ema50'].iloc[-1] - x['ema50'].iloc[-5]

        if (
            last['close'] > last['ema20'] > last['ema50'] and
            ema20_slope > 0 and
            ema50_slope >= 0
        ):
            return 'BULLISH', False, False

        if (
            last['close'] < last['ema20'] < last['ema50'] and
            ema20_slope < 0 and
            ema50_slope <= 0
        ):
            return 'BEARISH', False, False

        return 'NEUTRAL', False, False

    # =========================================================
    # FVG
    # =========================================================

    def detect_fvg(self, df):
        if df is None or len(df) < 3:
            return None

        a = df.iloc[-3]
        b = df.iloc[-2]
        c = df.iloc[-1]

        if c['low'] > a['high']:
            return {
                'type': 'BULLISH_FVG',
                'low': float(a['high']),
                'high': float(c['low']),
                'mid': float((a['high'] + c['low']) / 2)
            }

        if c['high'] < a['low']:
            return {
                'type': 'BEARISH_FVG',
                'low': float(c['high']),
                'high': float(a['low']),
                'mid': float((c['high'] + a['low']) / 2)
            }

        return None

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_order_block(self, df, direction):
        if df is None or len(df) < 10:
            return None

        start = max(2, len(df) - 50)

        for i in range(len(df) - 2, start - 1, -1):
            candle = df.iloc[i]
            impulse = df.iloc[i + 1]

            if direction == 'LONG':
                bearish_ob = candle['close'] < candle['open']
                bullish_impulse = impulse['close'] > impulse['open']
                displacement = (
                    impulse['close'] > candle['high'] and
                    impulse['body_ratio'] >= 0.55
                )

                if bearish_ob and bullish_impulse and displacement:
                    return {
                        'type': 'BULLISH_OB',
                        'low': float(candle['low']),
                        'high': float(candle['high']),
                        'mid': float((candle['low'] + candle['high']) / 2)
                    }

            else:
                bullish_ob = candle['close'] > candle['open']
                bearish_impulse = impulse['close'] < impulse['open']
                displacement = (
                    impulse['close'] < candle['low'] and
                    impulse['body_ratio'] >= 0.55
                )

                if bullish_ob and bearish_impulse and displacement:
                    return {
                        'type': 'BEARISH_OB',
                        'low': float(candle['low']),
                        'high': float(candle['high']),
                        'mid': float((candle['low'] + candle['high']) / 2)
                    }

        return None

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def detect_inducement_filter(self, df, direction):
        if df is None or len(df) < 8:
            return {
                'passed': False,
                'type': 'INSUFFICIENT_DATA'
            }

        curr = df.iloc[-1]
        previous = df.iloc[-6:-1]

        recent_low = previous['low'].min()
        recent_high = previous['high'].max()

        if direction == 'LONG':
            swept = curr['low'] < recent_low
            reclaimed = curr['close'] > recent_low

            if swept and reclaimed:
                return {
                    'passed': True,
                    'type': 'BULLISH_LIQUIDITY_SWEEP'
                }

        else:
            swept = curr['high'] > recent_high
            rejected = curr['close'] < recent_high

            if swept and rejected:
                return {
                    'passed': True,
                    'type': 'BEARISH_LIQUIDITY_SWEEP'
                }

        return {
            'passed': False,
            'type': 'NO_CONFIRMED_SWEEP'
        }

    # =========================================================
    # CANDLE
    # =========================================================

    def detect_candlestick_patterns(self, df):
        if df is None or len(df) < 3:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        body = abs(curr['close'] - curr['open'])
        range_val = curr['high'] - curr['low']

        if range_val <= 0:
            return None

        upper = curr['high'] - max(curr['open'], curr['close'])
        lower = min(curr['open'], curr['close']) - curr['low']

        if (
            curr['close'] > curr['open'] and
            lower >= body * 2 and
            upper <= max(body * 0.7, range_val * 0.08)
        ):
            return 'BULLISH_PINBAR'

        if (
            curr['close'] < curr['open'] and
            upper >= body * 2 and
            lower <= max(body * 0.7, range_val * 0.08)
        ):
            return 'BEARISH_PINBAR'

        prev_body = abs(prev['close'] - prev['open'])

        if (
            prev['close'] < prev['open'] and
            curr['close'] > curr['open'] and
            curr['close'] >= prev['open'] and
            curr['open'] <= prev['close'] and
            body > prev_body
        ):
            return 'BULLISH_ENGULFING'

        if (
            prev['close'] > prev['open'] and
            curr['close'] < curr['open'] and
            curr['open'] >= prev['close'] and
            curr['close'] <= prev['open'] and
            body > prev_body
        ):
            return 'BEARISH_ENGULFING'

        return None

    # =========================================================
    # LIQUIDITY TARGETS
    # =========================================================

    def analyze_liquidation_heatmap(self, df, direction):
        if df is None or len(df) < 20:
            return {
                'cluster_detected': False,
                'level': 0.0,
                'bias': 'NEUTRAL'
            }

        x = df.tail(30)

        recent_high = float(x['high'].iloc[:-2].max())
        recent_low = float(x['low'].iloc[:-2].min())
        price = float(df['close'].iloc[-1])

        if direction == 'LONG':
            distance = (recent_high - price) / price if price else 999

            return {
                'cluster_detected': distance > 0 and distance <= 0.04,
                'level': recent_high,
                'bias': 'BULLISH_LIQUIDITY_MAGNET'
            }

        distance = (price - recent_low) / price if price else 999

        return {
            'cluster_detected': distance > 0 and distance <= 0.04,
            'level': recent_low,
            'bias': 'BEARISH_LIQUIDITY_MAGNET'
        }

    # =========================================================
    # MULTI TIMEFRAME TREND
    # =========================================================

    def _get_trend(self, symbol, timeframe):
        df = self._fetch_ohlcv(symbol, timeframe, 180)

        if df is None or len(df) < 60:
            return 'NEUTRAL', None

        df = self._prepare(df)

        last = df.iloc[-1]
        slope20 = df['ema20'].iloc[-1] - df['ema20'].iloc[-5]
        slope50 = df['ema50'].iloc[-1] - df['ema50'].iloc[-5]

        if (
            last['close'] > last['ema20'] > last['ema50'] and
            slope20 > 0 and
            slope50 >= 0
        ):
            return 'BULLISH', df

        if (
            last['close'] < last['ema20'] < last['ema50'] and
            slope20 < 0 and
            slope50 <= 0
        ):
            return 'BEARISH', df

        return 'NEUTRAL', df

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def _btc_context(self):
        try:
            symbol = 'BTC/USDT:USDT'

            trend_1h, df = self._get_trend(symbol, '1h')

            if df is None:
                return 'NEUTRAL'

            rsi = float(df['rsi'].iloc[-1])

            if trend_1h == 'BULLISH' and rsi >= 52:
                return 'BULLISH'

            if trend_1h == 'BEARISH' and rsi <= 48:
                return 'BEARISH'

            return 'NEUTRAL'

        except Exception as e:
            logger.warning("BTC context error: %s", e)
            return 'NEUTRAL'

    # =========================================================
    # ENTRY QUALITY
    # =========================================================

    def _entry_quality(
        self,
        direction,
        price,
        ema20,
        rsi,
        volume_ratio,
        atr,
        ob,
        fvg
    ):
        score = 0
        reasons = []

        if direction == 'LONG':
            if price > ema20:
                score += 1
                reasons.append('PRICE_ABOVE_EMA20')

            if 50 <= rsi <= 68:
                score += 1
                reasons.append('RSI_HEALTHY_LONG')

            if rsi > 76:
                score -= 2
                reasons.append('OVERBOUGHT')

        else:
            if price < ema20:
                score += 1
                reasons.append('PRICE_BELOW_EMA20')

            if 32 <= rsi <= 50:
                score += 1
                reasons.append('RSI_HEALTHY_SHORT')

            if rsi < 24:
                score -= 2
                reasons.append('OVERSOLD')

        if volume_ratio >= 1.15:
            score += 1
            reasons.append('VOLUME_CONFIRMATION')

        if ob:
            ob_low = ob['low']
            ob_high = ob['high']

            if ob_low <= price <= ob_high:
                score += 2
                reasons.append('PRICE_IN_ORDER_BLOCK')
            else:
                distance = min(
                    abs(price - ob_low),
                    abs(price - ob_high)
                ) / price

                if distance <= 0.012:
                    score += 1
                    reasons.append('NEAR_ORDER_BLOCK')

        if fvg:
            if fvg['low'] <= price <= fvg['high']:
                score += 2
                reasons.append('PRICE_IN_FVG')
            else:
                distance = min(
                    abs(price - fvg['low']),
                    abs(price - fvg['high'])
                ) / price

                if distance <= 0.012:
                    score += 1
                    reasons.append('NEAR_FVG')

        return score, reasons

    # =========================================================
    # RISK ENGINE
    # =========================================================

    def _build_trade(self, df, direction, ob):
        row = df.iloc[-1]
        entry = float(row['close'])
        atr = float(row['atr'])

        recent = df.tail(20)
        swing_low = float(recent['low'].min())
        swing_high = float(recent['high'].max())

        if direction == 'LONG':
            structural_sl = swing_low - atr * 0.25

            if ob:
                structural_sl = min(
                    structural_sl,
                    ob['low'] - atr * 0.15
                )

            sl = structural_sl
            risk = entry - sl

            if risk <= 0:
                return None

            risk_pct = risk / entry * 100

            if risk_pct > 5.0:
                sl = entry - atr * 2.0
                risk = entry - sl
                risk_pct = risk / entry * 100

            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5.0

        else:
            structural_sl = swing_high + atr * 0.25

            if ob:
                structural_sl = max(
                    structural_sl,
                    ob['high'] + atr * 0.15
                )

            sl = structural_sl
            risk = sl - entry

            if risk <= 0:
                return None

            risk_pct = risk / entry * 100

            if risk_pct > 5.0:
                sl = entry + atr * 2.0
                risk = sl - entry
                risk_pct = risk / entry * 100

            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5.0

        return {
            'entry': entry,
            'sl': float(sl),
            'tp1': float(tp1),
            'tp2': float(tp2),
            'tp3': float(tp3),
            'risk_pct': round(risk_pct, 2)
        }

    # =========================================================
    # MAIN ANALYSIS
    # =========================================================

    def evaluate_strategy(self, symbol):
        df_15m_raw = self._fetch_ohlcv(symbol, '15m', 220)

        if df_15m_raw is None or len(df_15m_raw) < 80:
            return {
                'symbol': symbol,
                'decision': 'NO TRADE',
                'score': 0,
                'quality': 'INSUFFICIENT DATA',
                'confirmation_count': 0,
                'confirmations': [],
                'trend_4h': 'NEUTRAL',
                'trend_1h': 'NEUTRAL',
                'btc_context': 'NEUTRAL',
                'rsi_15m': 50.0,
                'volume_ratio': 1.0,
                'entry': 0.0,
                'sl': 0.0,
                'tp1': 0.0,
                'tp2': 0.0,
                'tp3': 0.0,
                'risk_pct': 0.0,
                'risk_filter': 'FAILED',
                'structure_confirmation': 'NEUTRAL',
                'btc_conflict': False,
                'entry_quality': 'INVALID'
            }

        df = self._prepare(df_15m_raw)

        trend_4h, _ = self._get_trend(symbol, '4h')
        trend_1h, _ = self._get_trend(symbol, '1h')
        btc_context = self._btc_context()

        structure, bullish_bos, bearish_bos = self._structure(df)
        digital_data = self.detect_digital_levels(df)

        long_votes = 0
        short_votes = 0

        if trend_4h == 'BULLISH':
            long_votes += 2
        elif trend_4h == 'BEARISH':
            short_votes += 2

        if trend_1h == 'BULLISH':
            long_votes += 2
        elif trend_1h == 'BEARISH':
            short_votes += 2

        if structure == 'BULLISH':
            long_votes += 2
        elif structure == 'BEARISH':
            short_votes += 2

        if btc_context == 'BULLISH':
            long_votes += 1
        elif btc_context == 'BEARISH':
            short_votes += 1

        if long_votes > short_votes:
            decision = 'LONG'
        elif short_votes > long_votes:
            decision = 'SHORT'
        else:
            return {
                'symbol': symbol,
                'decision': 'NO TRADE',
                'score': 35,
                'quality': 'WEAK',
                'confirmation_count': 0,
                'confirmations': [],
                'trend_4h': trend_4h,
                'trend_1h': trend_1h,
                'btc_context': btc_context,
                'rsi_15m': round(float(df['rsi'].iloc[-1]), 1),
                'volume_ratio': round(float(df['volume_ratio'].iloc[-1]), 2),
                'entry': float(df['close'].iloc[-1]),
                'sl': 0.0,
                'tp1': 0.0,
                'tp2': 0.0,
                'tp3': 0.0,
                'risk_pct': 0.0,
                'risk_filter': 'FAILED',
                'structure_confirmation': structure,
                'btc_conflict': False,
                'entry_quality': 'CONFLICT'
            }

        row = df.iloc[-1]
        entry = float(row['close'])
        rsi = float(row['rsi'])
        volume_ratio = float(row['volume_ratio'])
        atr = float(row['atr'])

        fvg = self.detect_fvg(df)
        ob = self.detect_order_block(df, decision)
        candle = self.detect_candlestick_patterns(df)
        inducement = self.detect_inducement_filter(df, decision)
        liquidity = self.analyze_liquidation_heatmap(df, decision)

        confirmations = []

        if (
            (decision == 'LONG' and trend_4h == 'BULLISH' and trend_1h == 'BULLISH') or
            (decision == 'SHORT' and trend_4h == 'BEARISH' and trend_1h == 'BEARISH')
        ):
            confirmations.append('Trend')

        if (
            (decision == 'LONG' and structure == 'BULLISH') or
            (decision == 'SHORT' and structure == 'BEARISH')
        ):
            confirmations.append('Structure')

        if decision == 'LONG':
            if 52 <= rsi <= 70:
                confirmations.append('Momentum')
        else:
            if 30 <= rsi <= 48:
                confirmations.append('Momentum')

        if volume_ratio >= 1.10:
            confirmations.append('Volume')

        if (decision == 'LONG' and bullish_bos) or (
            decision == 'SHORT' and bearish_bos
        ):
            confirmations.append('BOS')

        if inducement['passed']:
            confirmations.append('LiquiditySweep')

        if ob:
            confirmations.append('OrderBlock')

        if fvg:
            if (
                decision == 'LONG' and fvg['type'] == 'BULLISH_FVG'
            ) or (
                decision == 'SHORT' and fvg['type'] == 'BEARISH_FVG'
            ):
                confirmations.append('FVG')

        if candle:
            if (
                decision == 'LONG' and candle.startswith('BULLISH')
            ) or (
                decision == 'SHORT' and candle.startswith('BEARISH')
            ):
                confirmations.append('CandlePattern')

        # إضافة تأكيد التحليل الرقمي إذا كان السعر عند مستوى فيبوناتشي
        if digital_data and digital_data['near_digital_level']:
            confirmations.append('DigitalLevel')

        entry_score, entry_reasons = self._entry_quality(
            decision,
            entry,
            float(row['ema20']),
            rsi,
            volume_ratio,
            atr,
            ob,
            fvg
        )

        trade = self._build_trade(df, decision, ob)

        if trade is None:
            return {
                'symbol': symbol,
                'decision': 'NO TRADE',
                'score': 30,
                'quality': 'WEAK',
                'confirmation_count': len(confirmations),
                'confirmations': confirmations,
                'trend_4h': trend_4h,
                'trend_1h': trend_1h,
                'btc_context': btc_context,
                'rsi_15m': round(rsi, 1),
                'volume_ratio': round(volume_ratio, 2),
                'entry': entry,
                'sl': 0.0,
                'tp1': 0.0,
                'tp2': 0.0,
                'tp3': 0.0,
                'risk_pct': 0.0,
                'risk_filter': 'FAILED',
                'structure_confirmation': structure,
                'btc_conflict': False,
                'entry_quality': 'INVALID'
            }

        risk_pct = trade['risk_pct']

        btc_conflict = (
            (decision == 'LONG' and btc_context == 'BEARISH') or
            (decision == 'SHORT' and btc_context == 'BULLISH')
        )

        score = 30

        if trend_4h == self._decision_to_trend(decision):
            score += 12

        if trend_1h == self._decision_to_trend(decision):
            score += 12

        if structure == self._decision_to_trend(decision):
            score += 12

        if (
            decision == 'LONG' and 52 <= rsi <= 70
        ) or (
            decision == 'SHORT' and 30 <= rsi <= 48
        ):
            score += 7

        if volume_ratio >= 1.10:
            score += 6

        if volume_ratio >= 1.50:
            score += 3

        if inducement['passed']:
            score += 7

        if ob:
            score += 5

        if fvg and (
            (decision == 'LONG' and fvg['type'] == 'BULLISH_FVG') or
            (decision == 'SHORT' and fvg['type'] == 'BEARISH_FVG')
        ):
            score += 5

        if candle and (
            (decision == 'LONG' and candle.startswith('BULLISH')) or
            (decision == 'SHORT' and candle.startswith('BEARISH'))
        ):
            score += 3

        # منح نقاط إضافية إذا احترم السعر مستويات التحليل الرقمي (فيبوناتشي)
        if digital_data and digital_data['near_digital_level']:
            score += 5

        if entry_score >= 5:
            score += 4
        elif entry_score >= 3:
            score += 2

        if btc_context == self._decision_to_trend(decision):
            score += 5

        if btc_conflict:
            score -= 8

        if 0.5 <= risk_pct <= 3.5:
            score += 7
        elif 3.5 < risk_pct <= 5.0:
            score += 2
        else:
            score -= 8

        if decision == 'LONG' and rsi >= 75:
            score -= 8
        if decision == 'SHORT' and rsi <= 25:
            score -= 8

        score = int(max(0, min(score, 100)))

        risk_pass = (
            0.5 <= risk_pct <= 5.0
        )

        trend_pass = (
            trend_4h == self._decision_to_trend(decision) and
            trend_1h == self._decision_to_trend(decision)
        )

        confirmation_pass = len(confirmations) >= 4

        momentum_pass = (
            (decision == 'LONG' and 45 <= rsi <= 72) or
            (decision == 'SHORT' and 28 <= rsi <= 55)
        )

        elite_pass = (
            score >= 86 and
            risk_pass and
            trend_pass and
            confirmation_pass and
            momentum_pass and
            (
                inducement['passed'] or
                ob is not None or
                fvg is not None
            )
        )

        if not risk_pass or not trend_pass or not confirmation_pass:
            final_decision = 'NO TRADE'
        elif score >= 86 and elite_pass:
            final_decision = decision
        elif score >= 72 and momentum_pass:
            final_decision = decision
        else:
            final_decision = 'NO TRADE'

        if final_decision == 'NO TRADE':
            quality = 'WEAK' if score < 60 else 'MODERATE'
            entry_status = 'REJECTED'
            risk_filter = 'FAILED' if not risk_pass else 'PASSED'
        else:
            if score >= 90:
                quality = 'HIGH'
            elif score >= 80:
                quality = 'GOOD'
            else:
                quality = 'MODERATE'

            entry_status = (
                'OPTIMAL' if entry_score >= 5 and
                risk_pct <= 3.5 else 'VALID'
            )
            risk_filter = 'PASSED'

        return {
            'symbol': symbol,
            'decision': final_decision,
            'score': score,
            'quality': quality,
            'confirmation_count': len(confirmations),
            'confirmations': confirmations,
            'trend_4h': trend_4h,
            'trend_1h': trend_1h,
            'btc_context': btc_context,
            'rsi_15m': round(rsi, 1),
            'volume_ratio': round(volume_ratio, 2),
            'entry': trade['entry'],
            'sl': trade['sl'],
            'tp1': trade['tp1'],
            'tp2': trade['tp2'],
            'tp3': trade['tp3'],
            'risk_pct': trade['risk_pct'],
            'risk_filter': risk_filter,
            'structure_confirmation': structure,
            'btc_conflict': btc_conflict,
            'entry_quality': entry_status,
            'liquidation_data': liquidity,
            'inducement_status': inducement,
            'entry_reasons': entry_reasons,
            'fvg_data': fvg,
            'order_block_data': ob,
            'digital_data': digital_data
        }
