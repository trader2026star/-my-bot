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

    def _fetch_derivatives_metrics(self, symbol, current_price):
        """تتبع دقيق للـ OI والسعر عبر عينات زمنية مدتها 180 ثانية"""
        try:
            swap_symbol = symbol
            if not symbol.endswith(':USDT') and '/' in symbol and ':' not in symbol:
                swap_symbol = f"{symbol}:USDT"

            funding_rate = 0.0
            current_oi = 0.0
            oi_change_pct = 0.0
            price_change_pct = 0.0
            now = time.time()

            try:
                funding = self.exchange.fetch_funding_rate(swap_symbol)
                if funding and 'fundingRate' in funding and funding['fundingRate'] is not None:
                    funding_rate = float(funding['fundingRate'])
            except Exception:
                pass

            try:
                oi_data = self.exchange.fetch_open_interest(swap_symbol)
                if oi_data and 'openInterestAmount' in oi_data and oi_data['openInterestAmount'] is not None:
                    current_oi = float(oi_data['openInterestAmount'])
                    
                    if swap_symbol in self.oi_history:
                        prev_rec = self.oi_history[swap_symbol]
                        if now - prev_rec['last_sample_time'] >= 180:
                            prev_oi = prev_rec['current_oi']
                            prev_price = prev_rec['current_price']
                            if prev_oi > 0:
                                oi_change_pct = ((current_oi - prev_oi) / prev_oi) * 100.0
                            if prev_price > 0:
                                price_change_pct = ((current_price - prev_price) / prev_price) * 100.0
                            
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
                            prev_oi = prev_rec['previous_sample_oi']
                            prev_price = prev_rec['previous_sample_price']
                            if prev_oi > 0:
                                oi_change_pct = ((current_oi - prev_oi) / prev_oi) * 100.0
                            if prev_price > 0:
                                price_change_pct = ((current_price - prev_price) / prev_price) * 100.0
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
            # تصنيف العلاقة بدقة بناءً على تغير السعر والـ OI
            if oi_change_pct > 0.2:
                if price_change_pct >= 0:
                    bias = 'LONG_BUILDUP'
                else:
                    bias = 'SHORT_BUILDUP'
            elif oi_change_pct < -0.2:
                if price_change_pct >= 0:
                    bias = 'SHORT_COVERING'
                else:
                    bias = 'LONG_LIQUIDATION'

            return {
                'funding_rate': funding_rate,
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
    # ADVANCED INDICATORS & PREPARATION
    # =========================================================

    def _prepare(self, df):
        df = df.copy()

        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

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
    # BTC CONTEXT ANALYSIS
    # =========================================================

    def _get_btc_context(self, market_type='swap'):
        try:
            btc_symbol = 'BTC/USDT:USDT' if market_type == 'swap' else 'BTC/USDT'
            df_4h = self._fetch_ohlcv(btc_symbol, '4h', 50, market_type)
            df_1h = self._fetch_ohlcv(btc_symbol, '1h', 50, market_type)

            score = 0
            if df_4h is not None and len(df_4h) > 20:
                df_4h = self._prepare(df_4h)
                l = df_4h.iloc[-1]
                if l['close'] > l['ema20'] and l['ema20_slope'] > 0:
                    score += 3
                elif l['close'] < l['ema20'] and l['ema20_slope'] < 0:
                    score -= 3

            if df_1h is not None and len(df_1h) > 20:
                df_1h = self._prepare(df_1h)
                l = df_1h.iloc[-1]
                if l['close'] > l['ema20'] and l['rsi'] > 50:
                    score += 2
                elif l['close'] < l['ema20'] and l['rsi'] < 50:
                    score -= 2

            if score >= 3:
                return 'BTC_BULLISH'
            elif score <= -3:
                return 'BTC_BEARISH'
            return 'BTC_NEUTRAL'
        except Exception:
            return 'BTC_NEUTRAL'

    # =========================================================
    # MARKET REGIME DETECTION
    # =========================================================

    def _detect_market_regime(self, df):
        if df is None or len(df) < 30:
            return 'NEUTRAL'

        last = df.iloc[-1]
        atr_pct = (last['atr'] / last['close']) * 100

        if atr_pct > 2.8:
            return 'HIGH_VOLATILITY'
        elif atr_pct < 0.4:
            return 'LOW_VOLATILITY'

        if last['close'] > last['ema20'] > last['ema50'] and last['ema20_slope'] > 0:
            return 'TRENDING_BULLISH'
        elif last['close'] < last['ema20'] < last['ema50'] and last['ema20_slope'] < 0:
            return 'TRENDING_BEARISH'
        else:
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

        bullish_cond = last['close'] > last['ema20'] and last['ema20'] > last['ema50'] and last['ema20_slope'] > 0 and last['rsi'] > 48
        bearish_cond = last['close'] < last['ema20'] and last['ema20'] < last['ema50'] and last['ema20_slope'] < 0 and last['rsi'] < 52

        if bullish_cond:
            return 'BULLISH', df
        elif bearish_cond:
            return 'BEARISH', df
        return 'NEUTRAL', df

    # =========================================================
    # MARKET STRUCTURE (SWING & BREAKS)
    # =========================================================

    def _find_swing_points(self, df, window=4):
        highs = []
        lows = []
        for i in range(window, len(df) - window):
            curr_h = df['high'].iloc[i]
            if curr_h == df['high'].iloc[i - window:i + window + 1].max():
                highs.append((i, curr_h))
            curr_l = df['low'].iloc[i]
            if curr_l == df['low'].iloc[i - window:i + window + 1].min():
                lows.append((i, curr_l))
        return highs, lows

    def detect_market_structure(self, df):
        if df is None or len(df) < 30:
            return 'NEUTRAL', False, False, False, 'NORMAL_STRUCTURE'

        highs, lows = self._find_swing_points(df, window=4)
        if not highs or not lows:
            return 'NEUTRAL', False, False, False, 'NORMAL_STRUCTURE'

        last_high = highs[-1][1]
        last_low = lows[-1][1]
        last = df.iloc[-1]
        prev = df.iloc[-2]

        bullish_break = last['close'] > last_high and prev['close'] <= last_high
        bearish_break = last['close'] < last_low and prev['close'] >= last_low

        bos = False
        mss = False
        choch = False
        structure_type = 'NORMAL_STRUCTURE'
        structure = 'BULLISH' if last['close'] > last['ema20'] else 'BEARISH'

        if bullish_break:
            bos = True
            structure_type = 'BULLISH_BOS'
            structure = 'BULLISH'
            if df['ema20'].iloc[-10] < df['ema50'].iloc[-10]:
                mss = True
                choch = True
                structure_type = 'BULLISH_MSS'
        elif bearish_break:
            bos = True
            structure_type = 'BEARISH_BOS'
            structure = 'BEARISH'
            if df['ema20'].iloc[-10] > df['ema50'].iloc[-10]:
                mss = True
                choch = True
                structure_type = 'BEARISH_MSS'

        return structure, bos, mss, choch, structure_type

    # =========================================================
    # LIQUIDITY SWEEP
    # =========================================================

    def detect_advanced_liquidity_sweep(self, df, direction):
        if df is None or len(df) < 20:
            return {'passed': False, 'type': 'INSUFFICIENT_DATA'}

        highs, lows = self._find_swing_points(df, window=3)
        curr = df.iloc[-1]
        if not highs or not lows:
            return {'passed': False, 'type': 'NO_SWEEP'}

        eq_high = highs[-1][1]
        eq_low = lows[-1][1]
        displacement = curr['body_ratio'] >= 0.55 and curr['volume_ratio'] >= 1.2 and curr['range'] > df['atr'].iloc[-1] * 0.75

        if direction == 'LONG':
            swept = curr['low'] < eq_low
            reclaimed = curr['close'] > eq_low
            if swept and reclaimed and displacement:
                return {'passed': True, 'type': 'LIQUIDITY_SWEEP_LOWS_RECLAIMED'}
        else:
            swept = curr['high'] > eq_high
            rejected = curr['close'] < eq_high
            if swept and rejected and displacement:
                return {'passed': True, 'type': 'LIQUIDITY_SWEEP_HIGHS_REJECTED'}

        return {'passed': False, 'type': 'NO_SWEEP'}

    # =========================================================
    # FVG
    # =========================================================

    def detect_valid_fvg(self, df, current_price, direction):
        if df is None or len(df) < 15:
            return None

        total_bars = len(df)
        for i in range(len(df) - 3, max(2, len(df) - 25), -1):
            a = df.iloc[i - 2]
            b = df.iloc[i - 1]
            c = df.iloc[i]

            if direction == 'LONG' and c['low'] > a['high']:
                fvg_low = float(a['high'])
                fvg_high = float(c['low'])
                fvg_range = fvg_high - fvg_low
                if fvg_range <= 0:
                    continue

                # إذا تم اختراقها بالكامل (السعر أسفل الـ FVG تماماً) -> INVALID
                if current_price < fvg_low:
                    continue

                filled_pct = 0.0
                if current_price < fvg_high:
                    filled_pct = min(100.0, max(0.0, ((fvg_high - current_price) / fvg_range) * 100.0))

                if filled_pct < 80.0:
                    age = total_bars - i
                    fvg_mid = (fvg_low + fvg_high) / 2
                    inside = fvg_low <= current_price <= fvg_high
                    dist = abs(current_price - fvg_mid) / current_price
                    # يجب أن تكون قريبة نسبياً وليست بعيدة جداً
                    if dist <= 0.045:
                        return {
                            'type': 'BULLISH_FVG',
                            'low': fvg_low,
                            'high': fvg_high,
                            'mid': fvg_mid,
                            'age': age,
                            'filled_pct': round(filled_pct, 1),
                            'is_active': True,
                            'inside_zone': inside
                        }

            elif direction == 'SHORT' and c['high'] < a['low']:
                fvg_low = float(c['high'])
                fvg_high = float(a['low'])
                fvg_range = fvg_high - fvg_low
                if fvg_range <= 0:
                    continue

                if current_price > fvg_high:
                    continue

                filled_pct = 0.0
                if current_price > fvg_low:
                    filled_pct = min(100.0, max(0.0, ((current_price - fvg_low) / fvg_range) * 100.0))

                if filled_pct < 80.0:
                    age = total_bars - i
                    fvg_mid = (fvg_low + fvg_high) / 2
                    inside = fvg_low <= current_price <= fvg_high
                    dist = abs(current_price - fvg_mid) / current_price
                    if dist <= 0.045:
                        return {
                            'type': 'BEARISH_FVG',
                            'low': fvg_low,
                            'high': fvg_high,
                            'mid': fvg_mid,
                            'age': age,
                            'filled_pct': round(filled_pct, 1),
                            'is_active': True,
                            'inside_zone': inside
                        }

        return None

    # =========================================================
    # ORDER BLOCK
    # =========================================================

    def detect_valid_order_block(self, df, current_price, direction):
        if df is None or len(df) < 20:
            return None

        total_bars = len(df)
        start = max(2, len(df) - 40)

        for i in range(len(df) - 2, start - 1, -1):
            candle = df.iloc[i]
            impulse = df.iloc[i + 1]

            if direction == 'LONG':
                is_ob = candle['close'] < candle['open'] and impulse['close'] > candle['high'] and impulse['body_ratio'] >= 0.5 and impulse['volume_ratio'] >= 1.1
                if is_ob:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    age = total_bars - i

                    subsequent_df = df.iloc[i + 2:]
                    mitigation_status = 'VALID'
                    if len(subsequent_df) > 0:
                        if subsequent_df['low'].min() < ob_low:
                            closes_below = subsequent_df[subsequent_df['close'] < ob_low]
                            if len(closes_below) > 0:
                                mitigation_status = 'FULL_MITIGATION'
                            else:
                                mitigation_status = 'PARTIAL_MITIGATION'

                    if mitigation_status == 'FULL_MITIGATION':
                        continue

                    dist = abs(current_price - ((ob_low + ob_high) / 2)) / current_price
                    if dist <= 0.05:
                        return {
                            'type': 'BULLISH_OB',
                            'low': ob_low,
                            'high': ob_high,
                            'mid': (ob_low + ob_high) / 2,
                            'age': age,
                            'mitigation': mitigation_status,
                            'inside_zone': ob_low <= current_price <= ob_high
                        }
            else:
                is_ob = candle['close'] > candle['open'] and impulse['close'] < candle['low'] and impulse['body_ratio'] >= 0.5 and impulse['volume_ratio'] >= 1.1
                if is_ob:
                    ob_low = float(candle['low'])
                    ob_high = float(candle['high'])
                    age = total_bars - i

                    subsequent_df = df.iloc[i + 2:]
                    mitigation_status = 'VALID'
                    if len(subsequent_df) > 0:
                        if subsequent_df['high'].max() > ob_high:
                            closes_above = subsequent_df[subsequent_df['close'] > ob_high]
                            if len(closes_above) > 0:
                                mitigation_status = 'FULL_MITIGATION'
                            else:
                                mitigation_status = 'PARTIAL_MITIGATION'

                    if mitigation_status == 'FULL_MITIGATION':
                        continue

                    dist = abs(current_price - ((ob_low + ob_high) / 2)) / current_price
                    if dist <= 0.05:
                        return {
                            'type': 'BEARISH_OB',
                            'low': ob_low,
                            'high': ob_high,
                            'mid': (ob_low + ob_high) / 2,
                            'age': age,
                            'mitigation': mitigation_status,
                            'inside_zone': ob_low <= current_price <= ob_high
                        }

        return None

    # =========================================================
    # OVEREXTENSION FILTER
    # =========================================================

    def _check_overextension(self, df, direction):
        if df is None or len(df) < 15:
            return False
        last = df.iloc[-1]
        dist_ema20 = (last['close'] - last['ema20']) / last['ema20']
        atr_multiple = abs(last['close'] - last['ema20']) / last['atr']

        if direction == 'LONG' and (dist_ema20 > 0.045 or atr_multiple > 3.5):
            return True
        if direction == 'SHORT' and (dist_ema20 < -0.045 or atr_multiple > 3.5):
            return True
        return False

    # =========================================================
    # ENTRY ZONE, SL & TP BUILDER
    # =========================================================

    def _build_advanced_trade(self, df, direction, ob, fvg, market_type='swap'):
        row = df.iloc[-1]
        current_close = float(row['close'])
        atr = float(row['atr'])

        highs, lows = self._find_swing_points(df, window=3)
        recent_swing_low = lows[-1][1] if lows else float(df['low'].tail(15).min())
        recent_swing_high = highs[-1][1] if highs else float(df['high'].tail(15).max())

        if ob and fvg:
            zone_low = min(ob['low'], fvg['low'])
            zone_high = max(ob['high'], fvg['high'])
            entry_status = 'OB_FVG_CONFLUENCE_ZONE'
        elif ob:
            zone_low = ob['low']
            zone_high = ob['high']
            entry_status = 'OB_ZONE'
        elif fvg:
            zone_low = fvg['low']
            zone_high = fvg['high']
            entry_status = 'FVG_ZONE'
        else:
            zone_low = current_close - (atr * 0.2)
            zone_high = current_close
            entry_status = 'MARKET_ENTRY'

        entry_avg = (zone_low + zone_high) / 2

        # التحقق من قرب السعر من منطقة الدخول
        distance_to_zone_pct = abs(current_close - entry_avg) / current_close
        if distance_to_zone_pct > 0.035 and entry_status != 'MARKET_ENTRY':
            return None

        if direction == 'LONG':
            sl = recent_swing_low - (atr * 0.4)
            if ob:
                sl = min(sl, ob['low'] - (atr * 0.2))
            
            risk = entry_avg - sl
            if risk <= 0:
                sl = entry_avg - (atr * 1.5)
                risk = entry_avg - sl

            risk_pct = (risk / entry_avg) * 100
            if risk_pct > 5.0 or risk_pct < 0.3:
                return None

            # منع وضع الوقف داخل منطقة الدخول الحامية
            if ob and sl >= ob['low']:
                sl = ob['low'] - (atr * 0.3)
                risk = entry_avg - sl
                risk_pct = (risk / entry_avg) * 100
                if risk_pct > 5.0 or risk_pct < 0.3:
                    return None

            tp1 = entry_avg + (risk * 1.8)
            tp2 = recent_swing_high if recent_swing_high > tp1 else entry_avg + (risk * 3.0)
            tp3 = entry_avg + (risk * 4.5)

            if not (entry_avg < tp1 < tp2 < tp3):
                return None
        else:
            if market_type == 'spot':
                return None
            sl = recent_swing_high + (atr * 0.4)
            if ob:
                sl = max(sl, ob['high'] + (atr * 0.2))

            risk = sl - entry_avg
            if risk <= 0:
                sl = entry_avg + (atr * 1.5)
                risk = sl - entry_avg

            risk_pct = (risk / entry_avg) * 100
            if risk_pct > 5.0 or risk_pct < 0.3:
                return None

            if ob and sl <= ob['high']:
                sl = ob['high'] + (atr * 0.3)
                risk = sl - entry_avg
                risk_pct = (risk / entry_avg) * 100
                if risk_pct > 5.0 or risk_pct < 0.3:
                    return None

            tp1 = entry_avg - (risk * 1.8)
            tp2 = recent_swing_low if recent_swing_low < tp1 else entry_avg - (risk * 3.0)
            tp3 = entry_avg - (risk * 4.5)

            if not (entry_avg > tp1 > tp2 > tp3):
                return None

        rr_tp1 = round((abs(tp1 - entry_avg) / risk), 2) if risk > 0 else 0.0
        rr_tp2 = round((abs(tp2 - entry_avg) / risk), 2) if risk > 0 else 0.0
        rr_tp3 = round((abs(tp3 - entry_avg) / risk), 2) if risk > 0 else 0.0

        if rr_tp1 < 1.5:
            return None

        return {
            'entry': round(entry_avg, 6),
            'entry_zone': f"{round(zone_low, 6)} - {round(zone_high, 6)}",
            'entry_status': entry_status,
            'sl': round(float(sl), 6),
            'tp1': round(float(tp1), 6),
            'tp2': round(float(tp2), 6),
            'tp3': round(float(tp3), 6),
            'risk_pct': round(risk_pct, 2),
            'rr_tp1': rr_tp1,
            'rr_tp2': rr_tp2,
            'rr_tp3': rr_tp3
        }

    # =========================================================
    # MAIN STRATEGY EVALUATION & HARD GATES
    # =========================================================

    def evaluate_strategy(self, symbol, market_type='swap'):
        df_raw = self._fetch_ohlcv(symbol, self.timeframe, 220, market_type)
        if df_raw is None or len(df_raw) < 60:
            return self._empty_response(symbol, market_type, 'INSUFFICIENT_DATA')

        df = self._prepare(df_raw)
        current_price = float(df['close'].iloc[-1])

        trend_4h, _ = self._get_trend_external(symbol, '4h', market_type)
        trend_1h, _ = self._get_trend_external(symbol, '1h', market_type)
        btc_context = self._get_btc_context(market_type)
        market_regime = self._detect_market_regime(df)

        structure, bos, mss, choch, structure_type = self.detect_market_structure(df)
        derivatives = self._fetch_derivatives_metrics(symbol, current_price)

        # التصويت المبدئي للاتجاه
        long_score_vote = 0
        short_score_vote = 0

        if trend_4h == 'BULLISH': long_score_vote += 2
        elif trend_4h == 'BEARISH': short_score_vote += 2

        if trend_1h == 'BULLISH': long_score_vote += 2
        elif trend_1h == 'BEARISH': short_score_vote += 2

        if structure == 'BULLISH': long_score_vote += 2
        elif structure == 'BEARISH': short_score_vote += 2

        if btc_context == 'BTC_BULLISH': long_score_vote += 1
        elif btc_context == 'BTC_BEARISH': short_score_vote += 1

        if market_type == 'spot':
            if long_score_vote >= short_score_vote and trend_4h != 'BEARISH':
                decision = 'LONG'
            else:
                return self._empty_response(symbol, market_type, 'SPOT_SHORT_RESTRICTED')
        else:
            if long_score_vote > short_score_vote:
                decision = 'LONG'
            elif short_score_vote > long_score_vote:
                decision = 'SHORT'
            else:
                return self._empty_response(symbol, market_type, 'NO_CLEAR_DIRECTION')

        # =========================================================
        # HARD GATES الصارمة قبل حساب النقاط
        # =========================================================
        if not (bos or mss):
            return self._empty_response(symbol, market_type, 'NO_STRUCTURE_BREAK')

        if decision == 'LONG':
            if trend_4h == 'BEARISH' or trend_1h == 'BEARISH' or structure == 'BEARISH':
                return self._empty_response(symbol, market_type, 'HARD_GATE_FAILED')
            if btc_context == 'BTC_BEARISH':
                return self._empty_response(symbol, market_type, 'BTC_CONFLICT')
        else:
            if trend_4h == 'BULLISH' or trend_1h == 'BULLISH' or structure == 'BULLISH':
                return self._empty_response(symbol, market_type, 'HARD_GATE_FAILED')
            if btc_context == 'BTC_BULLISH':
                return self._empty_response(symbol, market_type, 'BTC_CONFLICT')

        if self._check_overextension(df, decision):
            return self._empty_response(symbol, market_type, 'OVEREXTENDED')

        fvg = self.detect_valid_fvg(df, current_price, decision)
        ob = self.detect_valid_order_block(df, current_price, decision)
        liquidity_sweep = self.detect_advanced_liquidity_sweep(df, decision)

        if not (fvg or ob or liquidity_sweep['passed']):
            return self._empty_response(symbol, market_type, 'NO_VALID_ENTRY_TOOL')

        trade = self._build_advanced_trade(df, decision, ob, fvg, market_type)
        if trade is None:
            return self._empty_response(symbol, market_type, 'POOR_RR_OR_INVALID_SL')

        # =========================================================
        # حساب الـ Score الدقيق (مجموعه 100 بالضبط - بدون قاعدة مجانية)
        # =========================================================
        score = 0

        # 1. Trend 4H (10 pts)
        if trend_4h == self._decision_to_trend(decision):
            score += 10

        # 2. Trend 1H (10 pts)
        if trend_1h == self._decision_to_trend(decision):
            score += 10

        # 3. Structure (15 pts)
        if structure == self._decision_to_trend(decision):
            score += 15

        # 4. BOS/MSS (10 pts)
        if bos or mss:
            score += 10

        # 5. Liquidity (10 pts)
        if liquidity_sweep['passed']:
            score += 10

        # 6. OB/FVG Confluence (10 pts)
        if ob and fvg:
            score += 10
        elif ob or fvg:
            score += 7

        # 7. Volume + Displacement (10 pts)
        last_row = df.iloc[-1]
        if last_row['volume_ratio'] >= 1.2 and last_row['body_ratio'] >= 0.5:
            score += 10

        # 8. Momentum (5 pts)
        rsi_val = last_row['rsi']
        rsi_slope = last_row['rsi_slope']
        ema20_slope = last_row['ema20_slope']
        if decision == 'LONG':
            if rsi_slope > 0 and ema20_slope > 0 and rsi_val >= 45:
                score += 5
        else:
            if rsi_slope < 0 and ema20_slope < 0 and rsi_val <= 55:
                score += 5

        # 9. BTC Context (10 pts)
        if (decision == 'LONG' and btc_context == 'BTC_BULLISH') or (decision == 'SHORT' and btc_context == 'BTC_BEARISH'):
            score += 10
        elif btc_context == 'BTC_NEUTRAL':
            score += 5

        # 10. Derivatives (5 pts)
        dbias = derivatives['derivatives_bias']
        if decision == 'LONG' and dbias in ['LONG_BUILDUP', 'SHORT_COVERING']:
            score += 5
        elif decision == 'SHORT' and dbias in ['SHORT_BUILDUP', 'LONG_LIQUIDATION']:
            score += 5

        # 11. Risk/RR (5 pts)
        if trade['rr_tp1'] >= 1.8:
            score += 5

        score = int(max(0, min(score, 100)))

        confirmations = []
        if trend_4h == self._decision_to_trend(decision): confirmations.append('Trend4H')
        if trend_1h == self._decision_to_trend(decision): confirmations.append('Trend1H')
        if structure == self._decision_to_trend(decision): confirmations.append('Structure')
        if bos: confirmations.append('BOS')
        if mss: confirmations.append('MSS')
        if liquidity_sweep['passed']: confirmations.append('LiquiditySweep')
        if ob: confirmations.append('OrderBlock')
        if fvg: confirmations.append('FVG')
        if last_row['volume_ratio'] >= 1.2: confirmations.append('Volume')

        # الحد الأدنى الصارم للتأكيدات (Structural + Entry + Momentum/Volume)
        if score < 75 or len(confirmations) < 4:
            return self._empty_response(symbol, market_type, 'CONFLUENCE_INSUFFICIENT')

        quality = 'HIGH QUALITY' if score >= 85 else 'GOOD'

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
            'btc_context': btc_context,
            'btc_conflict': False,
            'funding_rate': derivatives['funding_rate'],
            'oi_change_pct': derivatives['oi_change_pct'],
            'derivatives_bias': derivatives['derivatives_bias'],
            'market_regime': market_regime,
            'structure_type': structure_type,
            'liquidity_type': liquidity_sweep['type'],
            'entry_status': trade['entry_status'],
            'entry_zone': trade['entry_zone'],
            'rr_tp1': trade['rr_tp1'],
            'rr_tp2': trade['rr_tp2'],
            'rr_tp3': trade['rr_tp3'],
            'rsi_15m': round(float(rsi_val), 1),
            'volume_ratio': round(float(last_row['volume_ratio']), 2),
            'entry': trade['entry'],
            'sl': trade['sl'],
            'tp1': trade['tp1'],
            'tp2': trade['tp2'],
            'tp3': trade['tp3'],
            'risk_pct': trade['risk_pct'],
            'risk_filter': 'PASSED',
            'structure_confirmation': structure,
            'rejection_reason': 'NONE',
            'digital_data': {'near_digital_level': False},
            'candlestick': 'CONFIRMED'
        }

    def _empty_response(self, symbol, market_type, reason='NO_TRADE'):
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
            'btc_context': 'BTC_NEUTRAL',
            'btc_conflict': False,
            'funding_rate': 0.0,
            'oi_change_pct': 0.0,
            'derivatives_bias': 'NEUTRAL',
            'market_regime': 'NEUTRAL',
            'structure_type': 'NORMAL',
            'liquidity_type': 'NONE',
            'entry_status': 'INVALID',
            'entry_zone': 'N/A',
            'rr_tp1': 0.0,
            'rr_tp2': 0.0,
            'rr_tp3': 0.0,
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
            'rejection_reason': reason
        }
