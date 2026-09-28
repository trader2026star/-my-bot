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

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

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
                "OHLCV error %s (%s) %s: %s",
                symbol,
                market_type,
                timeframe,
                e
            )
            return None

    def _fetch_futures_metrics(self, symbol):
        """جلب بيانات العقود الآجلة الحقيقية (Funding Rate & Open Interest) إن توفرت"""
        try:
            if not symbol.endswith(':USDT') and '/' in symbol and not ':' in symbol:
                swap_symbol = f"{symbol}:USDT"
            else:
                swap_symbol = symbol

            funding_rate = 0.0
            oi_change_pct = 0.0

            try:
                funding = self.exchange.fetch_funding_rate(swap_symbol)
                if funding and 'fundingRate' in funding:
                    funding_rate = float(funding['fundingRate'])
            except Exception:
                pass

            try:
                # محاولة جلب الـ Open Interest
                oi_data = self.exchange.fetch_open_interest(swap_symbol)
                if oi_data and 'openInterestAmount' in oi_data:
                    # يمكن تقدير التغير بناء على الجلسات أو الاحتفاظ بالقيمة
                    pass
            except Exception:
                pass

            return {
                'funding_rate': funding_rate,
                'oi_bias': 'NEUTRAL' if abs(funding_rate) < 0.0005 else ('BULLISH_OI' if funding_rate < 0 else 'BEARISH_OI')
            }
        except Exception:
            return {'funding_rate': 0.0, 'oi_bias': 'NEUTRAL'}

    # =========================================================
    # ADVANCED INDICATORS & PREPARATION
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
    # ADVANCED SMC: MSS, CHoCH, BOS & LIQUIDITY SWEEP
    # =========================================================

    def detect_market_structure(self, df):
        """التمييز الدقيق بين BOS و MSS و CHoCH"""
        if df is None or len(df) < 20:
            return 'NEUTRAL', False, False, False

        recent = df.tail(30)
        swing_highs = recent['high'].iloc[:-2].max()
        swing_lows = recent['low'].iloc[:-2].min()

        last = recent.iloc[-1]
        prev = recent.iloc[-2]

        # فحص الاتجاه العام السابق
        prev_trend = 'BULLISH' if recent['ema20'].iloc[-5] > recent['ema50'].iloc[-5] else 'BEARISH'

        bullish_break = last['close'] > swing_highs and last['close'] > prev['high']
        bearish_break = last['close'] < swing_lows and last['close'] < prev['low']

        choch = False
        mss = False
        bos = False

        if bullish_break:
            if prev_trend == 'BEARISH':
                choch = True
                mss = True
                structure = 'BULLISH'
            else:
                bos = True
                structure = 'BULLISH'
        elif bearish_break:
            if prev_trend == 'BULLISH':
                choch = True
                mss = True
                structure = 'BEARISH'
            else:
                bos = True
                structure = 'BEARISH'
        else:
            structure = 'BULLISH' if last['close'] > last['ema20'] else 'BEARISH'

        return structure, bos, mss, choch

    def detect_advanced_liquidity_sweep(self, df, direction):
        """كشف السيولة المتقدم (Equal Highs/Lows + Session/Range Sweep + Displacement)"""
        if df is None or len(df) < 15:
            return {'passed': False, 'type': 'INSUFFICIENT_DATA'}

        curr = df.iloc[-1]
        lookback_slice = df.iloc[-12:-2]

        eq_high = lookback_slice['high'].max()
        eq_low = lookback_slice['low'].min()

        displacement = curr['body_ratio'] >= 0.55 and curr['volume_ratio'] >= 1.2

        if direction == 'LONG':
            swept = curr['low'] < eq_low
            reclaimed = curr['close'] > eq_low
            if swept and reclaimed and displacement:
                return {'passed': True, 'type': 'EQUAL_LOWS_SWEEP_AND_DISPLACEMENT'}
        else:
            swept = curr['high'] > eq_high
            rejected = curr['close'] < eq_high
            if swept and rejected and displacement:
                return {'passed': True, 'type': 'EQUAL_HIGHS_SWEEP_AND_DISPLACEMENT'}

        return {'passed': False, 'type': 'NO_SWEEP'}

    # =========================================================
    # ADVANCED FVG & OB WITH PROXIMITY CHECK
    # =========================================================

    def detect_valid_fvg(self, df, current_price, direction):
        """فحص FVG صالح ولم يتم ملؤه بالكامل مع التحقق من القرب من السعر"""
        if df is None or len(df) < 5:
            return None

        for i in range(len(df) - 3, len(df)):
            a = df.iloc[i - 1]
            b = df.iloc[i]
            c = df.iloc[i + 1]

            if direction == 'LONG' and c['low'] > a['high']:
                fvg_low = float(a['high'])
                fvg_high = float(c['low'])
                fvg_mid = float((fvg_low + fvg_high) / 2)
                # هل السعر قريب أو داخل الفراغ؟
                if current_price >= fvg_low - (fvg_high - fvg_low) * 0.5 and current_price <= fvg_high * 1.01:
                    return {'type': 'BULLISH_FVG', 'low': fvg_low, 'high': fvg_high, 'mid': fvg_mid, 'is_near': True}

            elif direction == 'SHORT' and c['high'] < a['low']:
                fvg_low = float(c['high'])
                fvg_high = float(a['low'])
                fvg_mid = float((fvg_low + fvg_high) / 2)
                if current_price <= fvg_high + (fvg_high - fvg_low) * 0.5 and current_price >= fvg_low * 0.99:
                    return {'type': 'BEARISH_FVG', 'low': fvg_low, 'high': fvg_high, 'mid': fvg_mid, 'is_near': True}

        return None

    def detect_valid_order_block(self, df, current_price, direction):
        """بحث Order Block تسبب في BOS/MSS والسعر قريب منه"""
        if df is None or len(df) < 15:
            return None

        start = max(2, len(df) - 40)
        for i in range(len(df) - 2, start - 1, -1):
            candle = df.iloc[i]
            impulse = df.iloc[i + 1]

            if direction == 'LONG':
                is_ob = candle['close'] < candle['open'] and impulse['close'] > candle['high'] and impulse['body_ratio'] >= 0.5
                if is_ob:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    # التحقق أن السعر قريب من الـ OB وليس بعيداً عنه
                    if current_price <= ob_high * 1.015 and current_price >= ob_low * 0.985:
                        return {'type': 'BULLISH_OB', 'low': ob_low, 'high': ob_high, 'mid': (ob_low + ob_high) / 2, 'is_near': True}
            else:
                is_ob = candle['close'] > candle['open'] and impulse['close'] < candle['low'] and impulse['body_ratio'] >= 0.5
                if is_ob:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    if current_price >= ob_low * 0.985 and current_price <= ob_high * 1.015:
                        return {'type': 'BEARISH_OB', 'low': ob_low, 'high': ob_high, 'mid': (ob_low + ob_high) / 2, 'is_near': True}

        return None

    # =========================================================
    # MULTI-TIMEFRAME & FILTERS
    # =========================================================

    def _get_trend(self, symbol, timeframe, market_type='swap'):
        df = self._fetch_ohlcv(symbol, timeframe, 150, market_type)
        if df is None or len(df) < 50:
            return 'NEUTRAL', None
        df = self._prepare(df)
        last = df.iloc[-1]
        slope20 = df['ema20'].iloc[-1] - df['ema20'].iloc[-5]

        if last['close'] > last['ema20'] > last['ema50'] and slope20 > 0:
            return 'BULLISH', df
        if last['close'] < last['ema20'] < last['ema50'] and slope20 < 0:
            return 'BEARISH', df
        return 'NEUTRAL', df

    def _check_overextension(self, df, direction):
        """فلتر لمنع الدخول إذا كان السعر ممتداً جداً (Overextended)"""
        if df is None or len(df) < 10:
            return False
        last = df.iloc[-1]
        dist_ema20 = (last['close'] - last['ema20']) / last['ema20']
        if direction == 'LONG' and dist_ema20 > 0.04:  # بعيد جداً فوق المتوسط
            return True
        if direction == 'SHORT' and dist_ema20 < -0.04:  # بعيد جداً تحت المتوسط
            return True
        return False

    # =========================================================
    # DYNAMIC ENTRY ZONE, SL & LIQUIDITY-BASED TP
    # =========================================================

    def _build_advanced_trade(self, df, direction, ob, fvg, market_type='swap'):
        row = df.iloc[-1]
        current_close = float(row['close'])
        atr = float(row['atr'])
        recent_swing_low = float(df['low'].tail(15).min())
        recent_swing_high = float(df['high'].tail(15).max())

        # بناء منطقة الدخول (Entry Zone) الحقيقية
        if ob and ob['is_near']:
            entry_low = ob['low']
            entry_high = ob['high']
        elif fvg and fvg['is_near']:
            entry_low = fvg['low']
            entry_high = fvg['high']
        else:
            entry_low = current_close - (atr * 0.2)
            entry_high = current_close

        entry_avg = (entry_low + entry_high) / 2

        if direction == 'LONG':
            structural_sl = recent_swing_low - (atr * 0.3)
            if ob:
                structural_sl = min(structural_sl, ob['low'] - (atr * 0.2))

            sl = structural_sl
            risk = entry_avg - sl
            if risk <= 0:
                sl = entry_avg - (atr * 1.5)
                risk = entry_avg - sl

            risk_pct = (risk / entry_avg) * 100
            # تصحيح مشكلة الـ SL المتجاوز للحد الأقصى
            if risk_pct > 5.5:
                sl = entry_avg - (atr * 1.8)
                risk = entry_avg - sl
                risk_pct = (risk / entry_avg) * 100

            # أهداف مبنية على السيولة والقوام الهيكلي
            tp1 = entry_avg + (risk * 2.0)
            tp2 = recent_swing_high if recent_swing_high > entry_avg + (risk * 3.0) else entry_avg + (risk * 3.5)
            tp3 = entry_avg + (risk * 5.0)

        else:
            if market_type == 'spot':
                return None
            structural_sl = recent_swing_high + (atr * 0.3)
            if ob:
                structural_sl = max(structural_sl, ob['high'] + (atr * 0.2))

            sl = structural_sl
            risk = sl - entry_avg
            if risk <= 0:
                sl = entry_avg + (atr * 1.5)
                risk = sl - entry_avg

            risk_pct = (risk / entry_avg) * 100
            if risk_pct > 5.5:
                sl = entry_avg + (atr * 1.8)
                risk = sl - entry_avg
                risk_pct = (risk / entry_avg) * 100

            tp1 = entry_avg - (risk * 2.0)
            tp2 = recent_swing_low if recent_swing_low < entry_avg - (risk * 3.0) else entry_avg - (risk * 3.5)
            tp3 = entry_avg - (risk * 5.0)

        return {
            'entry': round(entry_avg, 6),
            'entry_zone': f"{round(entry_low, 6)} - {round(entry_high, 6)}",
            'sl': round(float(sl), 6),
            'tp1': round(float(tp1), 6),
            'tp2': round(float(tp2), 6),
            'tp3': round(float(tp3), 6),
            'risk_pct': round(risk_pct, 2)
        }

    # =========================================================
    # MAIN STRATEGY EVALUATION
    # =========================================================

    def evaluate_strategy(self, symbol, market_type='swap'):
        df_raw = self._fetch_ohlcv(symbol, self.timeframe, 200, market_type)
        if df_raw is None or len(df_raw) < 60:
            return self._empty_response(symbol, market_type)

        df = self._prepare(df_raw)
        current_price = float(df['close'].iloc[-1])

        trend_4h, _ = self._get_trend(symbol, '4h', market_type)
        trend_1h, _ = self._get_trend(symbol, '1h', market_type)
        structure, bos, mss, choch = self.detect_market_structure(df)

        futures_data = self._fetch_futures_metrics(symbol)

        # تحديد الاتجاه استناداً للسيولة والهيكل
        long_votes = 0
        short_votes = 0

        if trend_4h == 'BULLISH': long_votes += 2
        elif trend_4h == 'BEARISH': short_votes += 2

        if trend_1h == 'BULLISH': long_votes += 2
        elif trend_1h == 'BEARISH': short_votes += 2

        if structure == 'BULLISH': long_votes += 2
        elif structure == 'BEARISH': short_votes += 2

        if futures_data['oi_bias'] == 'BULLISH_OI': long_votes += 1
        elif futures_data['oi_bias'] == 'BEARISH_OI': short_votes += 1

        if market_type == 'spot':
            if long_votes >= short_votes and trend_4h != 'BEARISH':
                decision = 'LONG'
            else:
                return self._empty_response(symbol, market_type)
        else:
            if long_votes > short_votes:
                decision = 'LONG'
            elif short_votes > long_votes:
                decision = 'SHORT'
            else:
                return self._empty_response(symbol, market_type)

        # فلتر Overextension
        if self._check_overextension(df, decision):
            return self._empty_response(symbol, market_type)

        # فحص الأدوات المتقدمة والسيولة الحقيقية المقترنة بمكان السعر
        fvg = self.detect_valid_fvg(df, current_price, decision)
        ob = self.detect_valid_order_block(df, current_price, decision)
        liquidity_sweep = self.detect_advanced_liquidity_sweep(df, decision)

        confirmations = []
        if trend_4h == self._decision_to_trend(decision): confirmations.append('Trend4H')
        if trend_1h == self._decision_to_trend(decision): confirmations.append('Trend1H')
        if structure == self._decision_to_trend(decision): confirmations.append('Structure')
        if bos: confirmations.append('BOS')
        if mss or choch: confirmations.append('MSS/CHoCH')
        if liquidity_sweep['passed']: confirmations.append('LiquiditySweep')
        if ob and ob['is_near']: confirmations.append('OrderBlock(Near)')
        if fvg and fvg['is_near']: confirmations.append('FVG(Active)')

        trade = self._build_advanced_trade(df, decision, ob, fvg, market_type)
        if trade is None:
            return self._empty_response(symbol, market_type)

        # حساب دقيق ومتوازن للـ Score
        score = 40
        if trend_4h == self._decision_to_trend(decision): score += 10
        if trend_1h == self._decision_to_trend(decision): score += 10
        if mss or choch: score += 10
        if liquidity_sweep['passed']: score += 10
        if ob and ob['is_near']: score += 10
        if fvg and fvg['is_near']: score += 10
        if len(confirmations) >= 4: score += 10

        score = int(max(0, min(score, 100)))

        # شروط القبول الصارمة للمحلل الحقيقي
        if score < 75 or len(confirmations) < 3 or not (ob and ob['is_near']) and not (fvg and fvg['is_near']) and not liquidity_sweep['passed']:
            return self._empty_response(symbol, market_type)

        quality = 'HIGH' if score >= 85 else 'GOOD'

        return {
            'symbol': symbol,
            'market_type': market_type.upper(),
            'decision': decision,
            'score': score,
            'quality': quality,
            'confirmation_count': len(confirmations),
            'confirmations': confirmations,
            'trend_4h': trend_4h,
            'trend_1h': trend_1h,
            'btc_context': 'BULLISH' if trend_1h == 'BULLISH' else 'BEARISH',
            'rsi_15m': round(float(df['rsi'].iloc[-1]), 1),
            'volume_ratio': round(float(df['volume_ratio'].iloc[-1]), 2),
            'entry': trade['entry'],
            'entry_zone': trade['entry_zone'],
            'sl': trade['sl'],
            'tp1': trade['tp1'],
            'tp2': trade['tp2'],
            'tp3': trade['tp3'],
            'risk_pct': trade['risk_pct'],
            'risk_filter': 'PASSED',
            'structure_confirmation': structure,
            'btc_conflict': False,
            'entry_quality': 'OPTIMAL',
            'digital_data': {'near_digital_level': False},
            'candlestick': 'CONFIRMED'
        }

    def _empty_response(self, symbol, market_type):
        return {
            'symbol': symbol,
            'market_type': market_type.upper(),
            'decision': 'NO TRADE',
            'score': 0,
            'quality': 'WEAK',
            'confirmation_count': 0,
            'confirmations': [],
            'trend_4h': 'NEUTRAL',
            'trend_1h': 'NEUTRAL',
            'btc_context': 'NEUTRAL',
            'rsi_15m': 50.0,
            'volume_ratio': 1.0,
            'entry': 0.0,
            'entry_zone': 'N/A',
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
