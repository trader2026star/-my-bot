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

    # =========================================================
    # DATA & FETCHING
    # =========================================================

    def _fetch_ohlcv(self, symbol, timeframe, limit=250, market_type='swap'):
        unwanted_tokens = [
            'EUR', 'JPY', 'GBP', 'CAD', 'AUD', 'CHF',
            'NZD', 'NCFX', 'USDCUSD'
        ]

        if any(token in symbol.upper() for token in unwanted_tokens):
            return None

        key = f"{symbol}:{market_type}:{timeframe}:{limit}"
        now = time.time()

        cached = self.cache.get(key)

        if cached and now - cached['time'] < self.cache_seconds:
            return cached['data'].copy()

        try:
            if market_type == 'spot':
                self.exchange.options['defaultType'] = 'spot'
            else:
                self.exchange.options['defaultType'] = 'swap'

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
    # DERIVATIVES
    # =========================================================

    def _fetch_derivatives_metrics(self, symbol, current_price):
        try:
            swap_symbol = symbol

            if (
                not symbol.endswith(':USDT')
                and '/' in symbol
                and ':' not in symbol
            ):
                swap_symbol = f"{symbol}:USDT"

            funding_rate = 0.0
            current_oi = 0.0
            oi_change_pct = 0.0
            price_change_pct = 0.0

            now = time.time()

            try:
                funding = self.exchange.fetch_funding_rate(
                    swap_symbol
                )

                if (
                    funding
                    and funding.get('fundingRate') is not None
                ):
                    funding_rate = float(
                        funding['fundingRate']
                    )

            except Exception:
                pass

            try:
                oi_data = self.exchange.fetch_open_interest(
                    swap_symbol
                )

                if oi_data:
                    current_oi = float(
                        oi_data.get('openInterestAmount') or
                        oi_data.get('openInterest') or
                        0.0
                    )

                    if swap_symbol in self.oi_history:

                        prev_rec = self.oi_history[
                            swap_symbol
                        ]

                        if (
                            now -
                            prev_rec['last_sample_time']
                            >= 180
                        ):

                            prev_oi = prev_rec['current_oi']
                            prev_price = prev_rec['current_price']

                            if prev_oi > 0:
                                oi_change_pct = (
                                    (current_oi - prev_oi)
                                    / prev_oi
                                ) * 100.0

                            if prev_price > 0:
                                price_change_pct = (
                                    (current_price - prev_price)
                                    / prev_price
                                ) * 100.0

                            self.oi_history[swap_symbol] = {
                                'current_oi': current_oi,
                                'previous_sample_oi': prev_oi,
                                'current_price': current_price,
                                'previous_sample_price': prev_price,
                                'last_sample_time': now,
                                'oi_change_pct': oi_change_pct,
                                'price_change_pct': price_change_pct
                            }

                        else:
                            prev_oi = prev_rec[
                                'previous_sample_oi'
                            ]

                            prev_price = prev_rec[
                                'previous_sample_price'
                            ]

                            if prev_oi > 0:
                                oi_change_pct = (
                                    (current_oi - prev_oi)
                                    / prev_oi
                                ) * 100.0

                            if prev_price > 0:
                                price_change_pct = (
                                    (current_price - prev_price)
                                    / prev_price
                                ) * 100.0

                    else:
                        self.oi_history[swap_symbol] = {
                            'current_oi': current_oi,
                            'previous_sample_oi': current_oi,
                            'current_price': current_price,
                            'previous_sample_price': current_price,
                            'last_sample_time': now,
                            'oi_change_pct': 0.0,
                            'price_change_pct': 0.0
                        }

            except Exception:
                pass

            bias = 'NEUTRAL'

            if oi_change_pct > 0.15:
                if price_change_pct >= 0:
                    bias = 'LONG_BUILDUP'
                else:
                    bias = 'SHORT_BUILDUP'

            elif oi_change_pct < -0.15:
                if price_change_pct >= 0:
                    bias = 'SHORT_COVERING'
                else:
                    bias = 'LONG_LIQUIDATION'

            return {
                'funding_rate': round(funding_rate, 6),
                'oi_current': current_oi,
                'oi_change_pct': round(oi_change_pct, 2),
                'price_change_pct': round(price_change_pct, 2),
                'derivatives_bias': bias
            }

        except Exception:
            return {
                'funding_rate': 0.0,
                'oi_current': 0.0,
                'oi_change_pct': 0.0,
                'price_change_pct': 0.0,
                'derivatives_bias': 'NEUTRAL'
            }

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

        df['ema20_slope'] = df['ema20'].diff(3)
        df['ema50_slope'] = df['ema50'].diff(3)

        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)
        df['rsi_slope'] = df['rsi'].diff(3)

        prev_close = df['close'].shift(1)
        tr = pd.concat(
            [
                df['high'] - df['low'],
                (df['high'] - prev_close).abs(),
                (df['low'] - prev_close).abs()
            ],
            axis=1
        ).max(axis=1)

        df['atr'] = tr.ewm(span=14, adjust=False).mean()

        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = (
            df['volume'] / df['volume_ma'].replace(0, np.nan)
        )
        df['volume_ratio'] = (
            df['volume_ratio']
            .replace([np.inf, -np.inf], np.nan)
            .fillna(1.0)
        )

        df['body'] = (df['close'] - df['open']).abs()
        df['range'] = (df['high'] - df['low']).replace(0, np.nan)
        df['body_ratio'] = (df['body'] / df['range']).fillna(0)
        df['close_location'] = (
            (df['close'] - df['low']) / df['range']
        ).replace([np.inf, -np.inf], np.nan).fillna(0.5)

        return (
            df
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .reset_index(drop=True)
        )

    # =========================================================
    # BTC CONTEXT
    # =========================================================

    def _get_btc_context(self, market_type='swap'):
        try:
            btc_symbol = (
                'BTC/USDT:USDT'
                if market_type == 'swap'
                else 'BTC/USDT'
            )

            df_4h = self._fetch_ohlcv(btc_symbol, '4h', 80, market_type)
            df_1h = self._fetch_ohlcv(btc_symbol, '1h', 80, market_type)

            score = 0

            if df_4h is not None and len(df_4h) > 30:
                df_4h = self._prepare(df_4h)
                last = df_4h.iloc[-1]
                if last['close'] > last['ema20']:
                    score += 2
                elif last['close'] < last['ema20']:
                    score -= 2

            if df_1h is not None and len(df_1h) > 30:
                df_1h = self._prepare(df_1h)
                last = df_1h.iloc[-1]
                if last['close'] > last['ema20']:
                    score += 1
                elif last['close'] < last['ema20']:
                    score -= 1

            if score >= 2:
                return 'BTC_BULLISH'
            if score <= -2:
                return 'BTC_BEARISH'
            return 'BTC_NEUTRAL'

        except Exception:
            return 'BTC_NEUTRAL'

    # =========================================================
    # MARKET REGIME
    # =========================================================

    def _detect_market_regime(self, df):
        if df is None or len(df) < 30:
            return 'NEUTRAL'

        last = df.iloc[-1]
        if last['close'] <= 0:
            return 'NEUTRAL'

        atr_pct = (last['atr'] / last['close']) * 100
        if atr_pct > 3.0:
            return 'HIGH_VOLATILITY'
        if atr_pct < 0.3:
            return 'LOW_VOLATILITY'

        if last['close'] > last['ema20'] > last['ema50']:
            return 'TRENDING_BULLISH'
        if last['close'] < last['ema20'] < last['ema50']:
            return 'TRENDING_BEARISH'

        return 'RANGING'

    # =========================================================
    # EXTERNAL TREND
    # =========================================================

    def _get_trend_external(self, symbol, timeframe, market_type):
        df = self._fetch_ohlcv(symbol, timeframe, 150, market_type)
        if df is None or len(df) < 50:
            return 'NEUTRAL', None

        df = self._prepare(df)
        last = df.iloc[-1]

        if last['close'] > last['ema20']:
            return 'BULLISH', df
        if last['close'] < last['ema20']:
            return 'BEARISH', df

        return 'NEUTRAL', df

    # =========================================================
    # SWING POINTS
    # =========================================================

    def _find_swing_points(self, df, window=3):
        highs = []
        lows = []

        if df is None or len(df) < (window * 2 + 3):
            return highs, lows

        for i in range(window, len(df) - window):
            curr_h = df['high'].iloc[i]
            if curr_h == df['high'].iloc[i - window:i + window + 1].max():
                highs.append((i, curr_h))

            curr_l = df['low'].iloc[i]
            if curr_l == df['low'].iloc[i - window:i + window + 1].min():
                lows.append((i, curr_l))

        return highs, lows

    # =========================================================
    # TRENDLINES DETECTION (مؤشر خطوط الاتجاه الجديد)
    # =========================================================

    def detect_trendlines(self, df, current_price, direction):
        """
        يقوم بالكشف عن خطوط الاتجاه (Trendlines) الصاعدة والهابطة
        ويتحقق مما إذا كان السعر يختبر خط الاتجاه حالياً.
        """
        if df is None or len(df) < 30:
            return {'passed': False, 'type': 'NO_TRENDLINE'}

        highs, lows = self._find_swing_points(df, window=3)

        if direction == 'LONG' and len(lows) >= 2:
            # خط اتجاه صاعد يعتمد على القعور الصاعدة
            p1 = lows[-2]
            p2 = lows[-1]
            
            # معادلة الخط المستقيم y = mx + c
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            
            if x2 == x1:
                return {'passed': False, 'type': 'NO_TRENDLINE'}
            
            slope = (y2 - y1) / (x2 - x1)
            current_x = len(df) - 1
            expected_trendline_price = y2 + slope * (current_x - x2)
            
            # السماح بنطاق تذبذب بسيط حول خط الاتجاه (مثلاً 1.5% أو بحدود الـ ATR)
            atr = float(df.iloc[-1]['atr'])
            if abs(current_price - expected_trendline_price) <= (atr * 1.8):
                return {
                    'passed': True,
                    'type': 'BULLISH_TRENDLINE_BOUNCE',
                    'line_price': round(expected_trendline_price, 4)
                }

        elif direction == 'SHORT' and len(highs) >= 2:
            # خط اتجاه هابط يعتمد على القمم الهابطة
            p1 = highs[-2]
            p2 = highs[-1]
            
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            
            if x2 == x1:
                return {'passed': False, 'type': 'NO_TRENDLINE'}
            
            slope = (y2 - y1) / (x2 - x1)
            current_x = len(df) - 1
            expected_trendline_price = y2 + slope * (current_x - x2)
            
            atr = float(df.iloc[-1]['atr'])
            if abs(current_price - expected_trendline_price) <= (atr * 1.8):
                return {
                    'passed': True,
                    'type': 'BEARISH_TRENDLINE_BOUNCE',
                    'line_price': round(expected_trendline_price, 4)
                }

        return {'passed': False, 'type': 'NO_TRENDLINE'}

    # =========================================================
    # MARKET STRUCTURE
    # =========================================================

    def detect_market_structure(self, df):
        if df is None or len(df) < 30:
            return ('NEUTRAL', False, False, False, 'NORMAL_STRUCTURE')

        highs, lows = self._find_swing_points(df, window=3)
        if not highs or not lows:
            return ('NEUTRAL', False, False, False, 'NORMAL_STRUCTURE')

        last_high = highs[-1][1]
        last_low = lows[-1][1]
        recent_df = df.tail(5)

        bullish_break = (recent_df['close'] > last_high).any()
        bearish_break = (recent_df['close'] < last_low).any()

        bos = False
        mss = False
        choch = False
        last = df.iloc[-1]

        structure = 'NEUTRAL'
        if last['close'] > last['ema20']:
            structure = 'BULLISH'
        elif last['close'] < last['ema20']:
            structure = 'BEARISH'

        structure_type = 'NORMAL_STRUCTURE'

        if bullish_break and not bearish_break:
            bos = True
            structure = 'BULLISH'
            structure_type = 'BULLISH_BOS'
        elif bearish_break and not bullish_break:
            bos = True
            structure = 'BEARISH'
            structure_type = 'BEARISH_BOS'

        return (structure, bos, mss, choch, structure_type)

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def detect_advanced_liquidity_sweep(self, df, direction):
        if df is None or len(df) < 20:
            return {'passed': False, 'type': 'NO_SWEEP'}

        highs, lows = self._find_swing_points(df, window=3)
        if not highs or not lows:
            return {'passed': False, 'type': 'NO_SWEEP'}

        curr = df.iloc[-1]
        eq_high = highs[-1][1]
        eq_low = lows[-1][1]
        recent = df.tail(5)

        if direction == 'LONG':
            swept = (recent['low'] < eq_low).any()
            reclaimed = curr['close'] > eq_low
            if swept or reclaimed:
                return {'passed': True, 'type': 'LIQUIDITY_SWEEP_LOW_RECLAIM'}
        else:
            swept = (recent['high'] > eq_high).any()
            rejected = curr['close'] < eq_high
            if swept or rejected:
                return {'passed': True, 'type': 'LIQUIDITY_SWEEP_HIGH_REJECT'}

        return {'passed': False, 'type': 'NO_SWEEP'}

    # =========================================================
    # FVG
    # =========================================================

    def detect_valid_fvg(self, df, current_price, direction):
        if df is None or len(df) < 15:
            return None

        total_bars = len(df)
        start_i = max(2, len(df) - 40)

        for i in range(len(df) - 3, start_i - 1, -1):
            a = df.iloc[i - 2]
            b = df.iloc[i - 1]
            c = df.iloc[i]
            atr = max(float(df.iloc[-1]['atr']), current_price * 0.0005)

            if direction == 'LONG' and c['low'] > a['high']:
                fvg_low = float(a['high'])
                fvg_high = float(c['low'])
                fvg_range = fvg_high - fvg_low
                if fvg_range <= 0:
                    continue

                return {
                    'type': 'BULLISH_FVG',
                    'low': fvg_low,
                    'high': fvg_high,
                    'mid': (fvg_low + fvg_high) / 2,
                    'is_active': True
                }

            elif direction == 'SHORT' and c['high'] < a['low']:
                fvg_low = float(c['high'])
                fvg_high = float(a['low'])
                fvg_range = fvg_high - fvg_low
                if fvg_range <= 0:
                    continue

                return {
                    'type': 'BEARISH_FVG',
                    'low': fvg_low,
                    'high': fvg_high,
                    'mid': (fvg_low + fvg_high) / 2,
                    'is_active': True
                }

        return None

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_valid_order_block(self, df, current_price, direction):
        if df is None or len(df) < 20:
            return None

        total_bars = len(df)
        start = max(2, len(df) - 50)
        atr = float(df.iloc[-1]['atr'])

        for i in range(len(df) - 3, start - 1, -1):
            candle = df.iloc[i]
            impulse = df.iloc[i + 1]

            if direction == 'LONG':
                is_ob = candle['close'] < candle['open'] and impulse['close'] > candle['high']
                if is_ob:
                    return {
                        'type': 'BULLISH_OB',
                        'low': float(candle['low']),
                        'high': float(candle['high']),
                        'mid': (float(candle['low']) + float(candle['high'])) / 2,
                        'inside_zone': True
                    }
            else:
                is_ob = candle['close'] > candle['open'] and impulse['close'] < candle['low']
                if is_ob:
                    return {
                        'type': 'BEARISH_OB',
                        'low': float(candle['low']),
                        'high': float(candle['high']),
                        'mid': (float(candle['low']) + float(candle['high'])) / 2,
                        'inside_zone': True
                    }

        return None
