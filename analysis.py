import logging
import time
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class ExpertAnalystBot:
    """
    Expert Futures Analyst
    ----------------------
    Multi-Timeframe:
        4H  -> Macro Trend
        1H  -> Market Structure
        15M -> Entry Trigger

    Confirmation groups:
        Trend
        Structure
        Liquidity
        Momentum
        Volume
        Breakout / Displacement
        FVG
        Order Block
        BTC Context

    الهدف:
        استخراج صفقات LONG / SHORT بجودة متوازنة
        بدون الإفراط في NO TRADE وبدون تخفيف الفلاتر لدرجة
        إصدار إشارات عشوائية.
    """

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

        self.exchange.timeout = 15000

        self._cache = {}

    # ============================================================
    # BASIC DATA
    # ============================================================

    def fetch_ohlcv_data(self, symbol, timeframe, limit=250):
        try:
            cache_key = f"{symbol}_{timeframe}_{limit}"
            now = time.time()

            cached = self._cache.get(cache_key)

            # Cache 20 seconds
            if cached and now - cached['time'] < 20:
                return cached['data'].copy()

            data = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not data or len(data) < 80:
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

            self._cache[cache_key] = {
                'time': now,
                'data': df
            }

            return df.copy()

        except Exception as e:
            logger.warning(
                f"OHLCV error {symbol} {timeframe}: {e}"
            )
            return None

    # ============================================================
    # INDICATORS
    # ============================================================

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

        # ATR
        prev_close = df['close'].shift(1)

        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()

        df['tr'] = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df['atr'] = df['tr'].rolling(14).mean()

        # RSI
        delta = df['close'].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df['rsi'] = 100 - (
            100 / (1 + rs)
        )

        # Volume
        df['volume_ma'] = (
            df['volume']
            .rolling(20)
            .mean()
        )

        df['volume_ratio'] = (
            df['volume'] /
            df['volume_ma'].replace(0, np.nan)
        )

        # Candle body
        df['body'] = (
            df['close'] -
            df['open']
        ).abs()

        df['body_ratio'] = (
            df['body'] /
            (df['high'] - df['low'])
            .replace(0, np.nan)
        )

        # Bollinger
        df['bb_mid'] = (
            df['close']
            .rolling(20)
            .mean()
        )

        df['bb_std'] = (
            df['close']
            .rolling(20)
            .std()
        )

        df['bb_upper'] = (
            df['bb_mid'] +
            2 * df['bb_std']
        )

        df['bb_lower'] = (
            df['bb_mid'] -
            2 * df['bb_std']
        )

        return df

    # ============================================================
    # TREND
    # ============================================================

    def get_trend(self, df):
        if df is None or len(df) < 50:
            return 'NEUTRAL'

        # آخر شمعة مغلقة
        row = df.iloc[-2]

        close = row['close']
        ema20 = row['ema20']
        ema50 = row['ema50']
        ema200 = row['ema200']

        bullish = (
            close > ema20 >
            ema50 > ema200
        )

        bearish = (
            close < ema20 <
            ema50 < ema200
        )

        if bullish:
            return 'BULLISH'

        if bearish:
            return 'BEARISH'

        # اتجاه متوسط حتى لو لم تكن كل المتوسطات مصطفة
        if close > ema50 and ema20 > ema50:
            return 'BULLISH'

        if close < ema50 and ema20 < ema50:
            return 'BEARISH'

        return 'NEUTRAL'

    # ============================================================
    # MARKET STRUCTURE
    # ============================================================

    def get_structure(self, df):
        result = {
            'direction': 'NEUTRAL',
            'bos_long': False,
            'bos_short': False,
            'sweep_long': False,
            'sweep_short': False,
            'hh_hl': False,
            'lh_ll': False
        }

        if df is None or len(df) < 40:
            return result

        # آخر شمعة مغلقة
        row = df.iloc[-2]

        prev_high = df['high'].iloc[-14:-2].max()
        prev_low = df['low'].iloc[-14:-2].min()

        # ========================================================
        # BOS
        # ========================================================

        result['bos_long'] = (
            row['close'] > prev_high
        )

        result['bos_short'] = (
            row['close'] < prev_low
        )

        # ========================================================
        # LIQUIDITY SWEEP
        # ========================================================

        liquidity_high = df['high'].iloc[-10:-2].max()
        liquidity_low = df['low'].iloc[-10:-2].min()

        result['sweep_long'] = (
            row['low'] < liquidity_low
            and row['close'] > liquidity_low
        )

        result['sweep_short'] = (
            row['high'] > liquidity_high
            and row['close'] < liquidity_high
        )

        # ========================================================
        # HH / HL
        # ========================================================

        recent_highs = df['high'].iloc[-20:-2]
        recent_lows = df['low'].iloc[-20:-2]

        mid = len(recent_highs) // 2

        first_high = recent_highs.iloc[:mid].max()
        second_high = recent_highs.iloc[mid:].max()

        first_low = recent_lows.iloc[:mid].min()
        second_low = recent_lows.iloc[mid:].min()

        result['hh_hl'] = (
            second_high > first_high
            and second_low > first_low
        )

        result['lh_ll'] = (
            second_high < first_high
            and second_low < first_low
        )

        if (
            result['bos_long']
            or result['sweep_long']
            or result['hh_hl']
        ):
            result['direction'] = 'BULLISH'

        elif (
            result['bos_short']
            or result['sweep_short']
            or result['lh_ll']
        ):
            result['direction'] = 'BEARISH'

        return result

    # ============================================================
    # FVG
    # ============================================================

    def detect_fvg(self, df):
        result = {
            'bullish': False,
            'bearish': False
        }

        if df is None or len(df) < 10:
            return result

        # نستخدم آخر 3 شموع مغلقة
        c1 = df.iloc[-4]
        c2 = df.iloc[-3]
        c3 = df.iloc[-2]

        # Bullish FVG
        if c3['low'] > c1['high']:
            result['bullish'] = True

        # Bearish FVG
        if c3['high'] < c1['low']:
            result['bearish'] = True

        return result

    # ============================================================
    # ORDER BLOCK
    # ============================================================

    def detect_order_block(self, df):
        result = {
            'bullish': False,
            'bearish': False,
            'bullish_low': None,
            'bullish_high': None,
            'bearish_low': None,
            'bearish_high': None
        }

        if df is None or len(df) < 30:
            return result

        # آخر 12 شمعة مغلقة
        start = max(2, len(df) - 14)

        for i in range(start, len(df) - 2):
            candle = df.iloc[i]
            next_candle = df.iloc[i + 1]

            candle_range = candle['high'] - candle['low']

            if candle_range <= 0:
                continue

            # Bullish displacement بعد شمعة هابطة
            if (
                candle['close'] < candle['open']
                and next_candle['close'] > candle['high']
            ):
                result['bullish'] = True
                result['bullish_low'] = candle['low']
                result['bullish_high'] = candle['high']

            # Bearish displacement بعد شمعة صاعدة
            if (
                candle['close'] > candle['open']
                and next_candle['close'] < candle['low']
            ):
                result['bearish'] = True
                result['bearish_low'] = candle['low']
                result['bearish_high'] = candle['high']

        return result

    # ============================================================
    # MOMENTUM
    # ============================================================

    def get_momentum(self, df, direction):
        if df is None or len(df) < 30:
            return False, 50

        row = df.iloc[-2]

        rsi = float(row['rsi'])

        atr = float(row['atr']) if pd.notna(row['atr']) else 0

        body = float(row['body'])

        bullish_candle = (
            row['close'] > row['open']
        )

        bearish_candle = (
            row['close'] < row['open']
        )

        body_strength = (
            body >= atr * 0.35
            if atr > 0
            else False
        )

        if direction == 'LONG':
            valid_rsi = (
                50 <= rsi <= 72
            )

            return (
                valid_rsi
                and bullish_candle
                and body_strength,
                rsi
            )

        valid_rsi = (
            28 <= rsi <= 50
        )

        return (
            valid_rsi
            and bearish_candle
            and body_strength,
            rsi
        )

    # ============================================================
    # VOLUME
    # ============================================================

    def get_volume_confirmation(self, df):
        if df is None or len(df) < 30:
            return False, 0

        row = df.iloc[-2]

        ratio = float(
            row['volume_ratio']
        )

        # أقل من 1.05 لا نعتبره Confirmation
        confirmed = ratio >= 1.10

        return confirmed, ratio

    # ============================================================
    # DISPLACEMENT / BREAKOUT
    # ============================================================

    def get_breakout_confirmation(self, df, direction):
        if df is None or len(df) < 30:
            return False

        row = df.iloc[-2]

        atr = float(row['atr'])

        if atr <= 0:
            return False

        body = abs(
            row['close'] -
            row['open']
        )

        strong_body = (
            body >= atr * 0.55
        )

        if direction == 'LONG':
            candle_direction = (
                row['close'] > row['open']
            )
        else:
            candle_direction = (
                row['close'] < row['open']
            )

        return (
            strong_body
            and candle_direction
        )

    # ============================================================
    # BTC CONTEXT
    # ============================================================

    def get_btc_context(self):
        try:
            btc_symbol = None

            markets = self.exchange.load_markets()

            possible = [
                'BTC/USDT:USDT',
                'BTC/USDT'
            ]

            for symbol in possible:
                if symbol in markets:
                    btc_symbol = symbol
                    break

            if not btc_symbol:
                return 'UNKNOWN'

            df = self.fetch_ohlcv_data(
                btc_symbol,
                '1h',
                120
            )

            if df is None:
                return 'UNKNOWN'

            df = self.add_indicators(df)

            trend = self.get_trend(df)

            if trend == 'BULLISH':
                return 'BULLISH'

            if trend == 'BEARISH':
                return 'BEARISH'

            return 'NEUTRAL'

        except Exception as e:
            logger.warning(
                f"BTC context error: {e}"
            )
            return 'UNKNOWN'

    # ============================================================
    # LEVELS
    # ============================================================

    def build_levels(self, df15, direction):
        if df15 is None or len(df15) < 40:
            return None

        row = df15.iloc[-2]

        entry = float(row['close'])

        atr = float(row['atr'])

        if atr <= 0:
            return None

        recent_low = float(
            df15['low'].iloc[-12:-2].min()
        )

        recent_high = float(
            df15['high'].iloc[-12:-2].max()
        )

        # ========================================================
        # LONG
        # ========================================================

        if direction == 'LONG':

            swing_sl = recent_low - (
                atr * 0.25
            )

            atr_sl = entry - (
                atr * 1.25
            )

            # نختار الوقف الأكثر منطقية
            sl = min(
                swing_sl,
                atr_sl
            )

            risk = entry - sl

            # حماية من SL ضيق جدًا
            min_risk = entry * 0.008

            if risk < min_risk:
                sl = entry - min_risk
                risk = min_risk

            # سقف مخاطرة
            max_risk = entry * 0.065

            if risk > max_risk:
                sl = entry - max_risk
                risk = max_risk

            tp1 = entry + risk * 2.0
            tp2 = entry + risk * 3.5
            tp3 = entry + risk * 5.0

        # ========================================================
        # SHORT
        # ========================================================

        else:

            swing_sl = recent_high + (
                atr * 0.25
            )

            atr_sl = entry + (
                atr * 1.25
            )

            sl = max(
                swing_sl,
                atr_sl
            )

            risk = sl - entry

            # حماية من SL ضيق جدًا
            min_risk = entry * 0.008

            if risk < min_risk:
                sl = entry + min_risk
                risk = min_risk

            max_risk = entry * 0.065

            if risk > max_risk:
                sl = entry + max_risk
                risk = max_risk

            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5
            tp3 = entry - risk * 5.0

        if risk <= 0:
            return None

        risk_pct = (
            risk / entry
        ) * 100

        return {
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk_pct': risk_pct
        }

    # ============================================================
    # OVEREXTENSION
    # ============================================================

    def is_overextended(self, df):
        if df is None or len(df) < 30:
            return False

        row = df.iloc[-2]

        atr = float(row['atr'])

        body = float(row['body'])

        if atr <= 0:
            return False

        # شمعة ضخمة جدًا
        if body > atr * 2.8:
            return True

        # RSI extreme
        rsi = float(row['rsi'])

        if rsi > 78 or rsi < 22:
            return True

        return False

    # ============================================================
    # PRICE FORMAT
    # ============================================================

    def format_price(self, price):
        if price is None:
            return 'N/A'

        if price >= 100:
            return f"{price:.4f}"

        if price >= 1:
            return f"{price:.5f}"

        if price >= 0.01:
            return f"{price:.7f}"

        if price >= 0.0001:
            return f"{price:.9f}"

        return f"{price:.12f}"

    # ============================================================
    # MAIN ANALYSIS
    # ============================================================

    def evaluate_strategy(self, symbol):
        try:

            # ====================================================
            # FETCH DATA
            # ====================================================

            df4h = self.fetch_ohlcv_data(
                symbol,
                '4h',
                250
            )

            df1h = self.fetch_ohlcv_data(
                symbol,
                '1h',
                250
            )

            df15 = self.fetch_ohlcv_data(
                symbol,
                '15m',
                250
            )

            if (
                df4h is None
                or df1h is None
                or df15 is None
            ):
                return None

            df4h = self.add_indicators(df4h)
            df1h = self.add_indicators(df1h)
            df15 = self.add_indicators(df15)

            # ====================================================
            # TRENDS
            # ====================================================

            trend4h = self.get_trend(df4h)
            trend1h = self.get_trend(df1h)

            # ====================================================
            # STRUCTURE
            # ====================================================

            structure1h = self.get_structure(df1h)
            structure15 = self.get_structure(df15)

            # ====================================================
            # BTC
            # ====================================================

            btc_context = self.get_btc_context()

            # ====================================================
            # DETERMINE DIRECTION
            # ====================================================

            long_votes = 0
            short_votes = 0

            if trend4h == 'BULLISH':
                long_votes += 2

            elif trend4h == 'BEARISH':
                short_votes += 2

            if trend1h == 'BULLISH':
                long_votes += 1

            elif trend1h == 'BEARISH':
                short_votes += 1

            if structure1h['direction'] == 'BULLISH':
                long_votes += 1

            elif structure1h['direction'] == 'BEARISH':
                short_votes += 1

            if structure15['direction'] == 'BULLISH':
                long_votes += 1

            elif structure15['direction'] == 'BEARISH':
                short_votes += 1

            # BTC is a vote, not an automatic blocker
            if btc_context == 'BULLISH':
                long_votes += 1

            elif btc_context == 'BEARISH':
                short_votes += 1

            if long_votes > short_votes:
                direction = 'LONG'

            elif short_votes > long_votes:
                direction = 'SHORT'

            else:
                return None

            # ====================================================
            # HARD TREND FILTER
            # ====================================================

            if direction == 'LONG':
                if trend4h != 'BULLISH':
                    return None

            else:
                if trend4h != 'BEARISH':
                    return None

            # ====================================================
            # ENTRY DATA
            # ====================================================

            momentum_ok, rsi = self.get_momentum(
                df15,
                direction
            )

            volume_ok, volume_ratio = (
                self.get_volume_confirmation(df15)
            )

            breakout_ok = (
                self.get_breakout_confirmation(
                    df15,
                    direction
                )
            )

            # ====================================================
            # STRUCTURE EVENTS
            # ====================================================

            if direction == 'LONG':

                bos = (
                    structure1h['bos_long']
                    or structure15['bos_long']
                )

                sweep = (
                    structure1h['sweep_long']
                    or structure15['sweep_long']
                )

                hh_hl = (
                    structure1h['hh_hl']
                    or structure15['hh_hl']
                )

            else:

                bos = (
                    structure1h['bos_short']
                    or structure15['bos_short']
                )

                sweep = (
                    structure1h['sweep_short']
                    or structure15['sweep_short']
                )

                hh_hl = (
                    structure1h['lh_ll']
                    or structure15['lh_ll']
                )

            # ====================================================
            # FVG
            # ====================================================

            fvg = self.detect_fvg(df15)

            fvg_ok = (
                fvg['bullish']
                if direction == 'LONG'
                else fvg['bearish']
            )

            # ====================================================
            # ORDER BLOCK
            # ====================================================

            ob = self.detect_order_block(df15)

            ob_ok = (
                ob['bullish']
                if direction == 'LONG'
                else ob['bearish']
            )

            # ====================================================
            # BTC ALIGNMENT
            # ====================================================

            btc_aligned = (
                (
                    direction == 'LONG'
                    and btc_context == 'BULLISH'
                )
                or
                (
                    direction == 'SHORT'
                    and btc_context == 'BEARISH'
                )
            )

            btc_conflict = (
                (
                    direction == 'LONG'
                    and btc_context == 'BEARISH'
                )
                or
                (
                    direction == 'SHORT'
                    and btc_context == 'BULLISH'
                )
            )

            # ====================================================
            # REAL CONFIRMATION GROUPS
            # ====================================================

            confirmations = []

            # 1. Macro trend
            confirmations.append(
                '4H TREND'
            )

            # 2. 1H trend
            if trend1h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            ):
                confirmations.append(
                    '1H TREND'
                )

            # 3. Structure
            if bos:
                confirmations.append(
                    'BOS'
                )

            elif sweep:
                confirmations.append(
                    'LIQUIDITY SWEEP'
                )

            elif hh_hl:
                confirmations.append(
                    'HH/HL'
                    if direction == 'LONG'
                    else 'LH/LL'
                )

            # 4. Momentum
            if momentum_ok:
                confirmations.append(
                    'MOMENTUM'
                )

            # 5. Volume
            if volume_ok:
                confirmations.append(
                    'VOLUME'
                )

            # 6. Displacement
            if breakout_ok:
                confirmations.append(
                    'DISPLACEMENT'
                )

            # 7. FVG
            if fvg_ok:
                confirmations.append(
                    'FVG'
                )

            # 8. OB
            if ob_ok:
                confirmations.append(
                    'ORDER BLOCK'
                )

            # 9. BTC
            if btc_aligned:
                confirmations.append(
                    'BTC SUPPORT'
                )

            # ====================================================
            # SCORE
            # ====================================================

            score = 0

            # Macro trend
            if trend4h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            ):
                score += 2

            # 1H trend
            if trend1h == (
                'BULLISH'
                if direction == 'LONG'
                else 'BEARISH'
            ):
                score += 1

            # Structure
            if bos:
                score += 2

            elif sweep:
                score += 1

            elif hh_hl:
                score += 1

            # Momentum
            if momentum_ok:
                score += 1

            # Volume
            if volume_ok:
                score += 1

            # Displacement
            if breakout_ok:
                score += 1

            # FVG
            if fvg_ok:
                score += 1

            # Order Block
            if ob_ok:
                score += 1

            # BTC
            if btc_aligned:
                score += 1

            elif btc_conflict:
                score -= 1

            # ====================================================
            # UNIQUE CONFIRMATION COUNT
            # ====================================================

            confirmation_count = len(
                set(confirmations)
            )

            # ====================================================
            # MUST HAVE REAL STRUCTURE
            # ====================================================

            structure_confirmation = (
                bos
                or sweep
                or hh_hl
                or fvg_ok
                or ob_ok
            )

            if not structure_confirmation:
                return None

            # ====================================================
            # MINIMUM CONFIRMATIONS
            # ====================================================

            if confirmation_count < 3:
                return None

            # Score floor
            if score < 5:
                return None

            # ====================================================
            # ANTI CHASE
            # ====================================================

            if self.is_overextended(df15):
                return None

            # ====================================================
            # LEVELS
            # ====================================================

            levels = self.build_levels(
                df15,
                direction
            )

            if levels is None:
                return None

            entry = levels['entry']
            sl = levels['sl']
            tp1 = levels['tp1']
            tp2 = levels['tp2']
            tp3 = levels['tp3']
            risk_pct = levels['risk_pct']

            # ====================================================
            # RISK FILTER
            # ====================================================

            if risk_pct < 0.8:
                return None

            if risk_pct > 6.5:
                return None

            risk_filter = 'PASS'

            # ====================================================
            # QUALITY ENGINE
            # ====================================================

            # STRONG only if:
            # - score >= 7
            # - at least 5 confirmations
            # - structure exists
            # - no BTC conflict
            # - volume reasonable

            if (
                score >= 7
                and confirmation_count >= 5
                and not btc_conflict
                and volume_ratio >= 1.10
            ):
                quality = 'STRONG'

            elif (
                score >= 5
                and confirmation_count >= 4
            ):
                quality = 'VALID SETUP'

            else:
                quality = 'EARLY SETUP'

            # BTC conflict prevents fake STRONG
            if btc_conflict and quality == 'STRONG':
                quality = 'VALID SETUP'

            # Very weak volume prevents STRONG
            if volume_ratio < 1.10:
                if quality == 'STRONG':
                    quality = 'VALID SETUP'

            # ====================================================
            # ENTRY QUALITY
            # ====================================================

            entry_quality = 'DIRECT'

            if btc_conflict:
                entry_quality = 'BTC CONFLICT'

            # ====================================================
            # FINAL RESULT
            # ====================================================

            return {
                'symbol': symbol,
                'decision': direction,
                'score': int(score),
                'quality': quality,

                'confirmations': confirmations,
                'confirmation_count': confirmation_count,

                'trend_4h': trend4h,
                'trend_1h': trend1h,

                'btc_context': btc_context,
                'btc_conflict': btc_conflict,
                'btc_aligned': btc_aligned,

                'rsi_15m': float(rsi),
                'volume_ratio': float(volume_ratio),

                'entry': float(entry),
                'sl': float(sl),
                'tp1': float(tp1),
                'tp2': float(tp2),
                'tp3': float(tp3),

                'risk_pct': float(risk_pct),

                'risk_filter': risk_filter,
                'structure_confirmation': 'PASS',

                'bos': bos,
                'liquidity_sweep': sweep,
                'structure': hh_hl,
                'momentum': momentum_ok,
                'volume_confirmation': volume_ok,
                'displacement': breakout_ok,
                'fvg': fvg_ok,
                'order_block': ob_ok,

                'entry_quality': entry_quality,

                'message': (
                    'Setup signal — not a guaranteed result.'
                )
            }

        except Exception as e:
            logger.exception(
                f"Analysis error for {symbol}: {e}"
            )
            return None

    # ============================================================
    # COMPATIBILITY METHODS
    # ============================================================

    def analyze(self, symbol):
        return self.evaluate_strategy(symbol)

    def get_coin_analysis(self, symbol):
        return self.evaluate_strategy(symbol)
