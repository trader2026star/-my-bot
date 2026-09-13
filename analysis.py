# =========================================================
# analysis.py - BingX Institutional SMC Execution Tool v49.3
# =========================================================
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/49.3', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3
MAX_SL_PCT = 4.0
MIN_SL_PCT = 0.35

_RATE_LIMIT_UNTIL = 0.0
_LAST_REQUEST_TIME = 0.0
_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0.0
_KLINE_CACHE = {}
_PRICE_CACHE = {}
_TICKER_CACHE = None
_TICKER_CACHE_TIME = 0.0
_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()

def normalize_symbol(s):
    s_clean = str(s).strip().lower()
    if s_clean in ['ترند', 'trend', 'scan_trend', 'trend_command']:
        return 'TREND_COMMAND'
    if s_clean in ['debugscan', 'debug']:
        return 'DEBUG_SCAN_COMMAND'

    s = str(s).strip().upper().replace(' ', '').replace('-', '').replace('_', '').replace('/', '')
    if not s.endswith('USDT'):
        s = s + '-USDT' if '-' not in s else s
    elif s.endswith('USDT') and '-' not in s:
        s = s[:-4] + '-USDT'
    return s

def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()
        try:
            r = SESSION.get(BINGX_URL + path, params=params or {}, timeout=timeout)
            if r.status_code != 200:
                if r.status_code == 429:
                    with _RATE_LOCK:
                        _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
                return None
            d = r.json()
            if isinstance(d, dict) and d.get('code', 0) == 0:
                return d.get('data')
            return d.get('data') if isinstance(d, dict) and 'data' in d else d
        except Exception:
            return None

def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time() - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts')
    out = set()
    rows = d.get('contracts', []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
    for x in rows:
        if isinstance(x, dict):
            s = str(x.get('symbol', '')).upper()
            if s:
                out.add(s)
                out.add(normalize_symbol(s))
    if out:
        _SYMBOL_CACHE, _SYMBOL_CACHE_TIME = out, time.time()
        return set(_SYMBOL_CACHE)
    return set(_SYMBOL_CACHE)

def symbol_exists(s):
    norm = normalize_symbol(s)
    if norm in ['TREND_COMMAND', 'DEBUG_SCAN_COMMAND']:
        return True
    sy = get_futures_symbols()
    return not sy or norm in sy or s in sy

def _ticker_rows(force=False):
    global _TICKER_CACHE, _TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time() - _TICKER_CACHE_TIME < TICKER_CACHE_SECONDS:
        return _TICKER_CACHE
    x = bingx_get('/openApi/swap/v2/quote/ticker')
    if isinstance(x, list):
        _TICKER_CACHE, _TICKER_CACHE_TIME = x, time.time()
        return x
    elif isinstance(x, dict) and 'tickers' in x:
        _TICKER_CACHE, _TICKER_CACHE_TIME = x['tickers'], time.time()
        return x['tickers']
    return []

def _parse(rows):
    out = []
    if not isinstance(rows, list):
        return out
    for x in rows:
        try:
            if isinstance(x, dict):
                t = int(x.get('time', x.get('openTime', 0)))
                o = float(x.get('open', 0))
                h = float(x.get('high', 0))
                l = float(x.get('low', 0))
                c = float(x.get('close', 0))
                v = float(x.get('volume', 0))
                if t > 0 and c > 0:
                    out.append([t, o, h, l, c, v])
            elif isinstance(x, list) and len(x) >= 6:
                t, o, h, l, c, v = x[:6]
                out.append([int(t), float(o), float(h), float(l), float(c), float(v or 0)])
        except Exception:
            pass
    try:
        out.sort(key=lambda z: z[0])
    except Exception:
        pass
    seen = set()
    clean = []
    for x in out:
        if x[0] in seen:
            continue
        seen.add(x[0])
        clean.append(x)
    return clean

def get_bingx_klines(s, interval='1h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS:
        return c[1]
    mp = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d'}
    bi = mp.get(str(interval).lower(), '1h')
    d = bingx_get('/openApi/swap/v2/quote/klines', {'symbol': s, 'interval': bi, 'limit': int(limit)})
    r = _parse(d)
    if r and len(r) > 0:
        _KLINE_CACHE[key] = (now, r)
        return r
    return None

def get_current_price(s, force=False):
    s = normalize_symbol(s)
    now = time.time()
    c = _PRICE_CACHE.get(s)
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS:
        return c[1]
    d = bingx_get('/openApi/swap/v2/quote/price', {'symbol': s})
    if isinstance(d, dict) and 'price' in d:
        try:
            p = float(d.get('price', 0))
            if p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
        except Exception:
            pass
    rows = _ticker_rows()
    for x in rows:
        if isinstance(x, dict) and str(x.get('symbol', '')).upper() in [s, s.replace('-', '')]:
            try:
                p = float(x.get('lastPrice', x.get('price', 0)))
                if p > 0:
                    _PRICE_CACHE[s] = (now, p)
                    return p
            except Exception:
                pass
    k = get_bingx_klines(s, '1m', 5)
    if k and len(k) > 0 and k[-1][4] > 0:
        _PRICE_CACHE[s] = (now, k[-1][4])
        return k[-1][4]
    return None

def smart_round(v):
    if v is None:
        return 0
    try:
        v = float(v)
    except Exception:
        return 0
    if v >= 1000:
        return round(v, 2)
    if v >= 100:
        return round(v, 3)
    if v >= 1:
        return round(v, 4)
    if v >= 0.1:
        return round(v, 5)
    return round(v, 8)

def calculate_atr(klines, period=14):
    if not klines or len(klines) < period + 1:
        return 0.01
    trs = []
    for i in range(1, len(klines)):
        h = klines[i][2]
        l = klines[i][3]
        pc = klines[i-1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs))

def calculate_swings(klines, left=2, right=2):
    swings = []
    if not klines or len(klines) < (left + right + 1):
        return swings
    for i in range(left, len(klines) - right):
        is_high = True
        is_low = True
        h_val = klines[i][2]
        l_val = klines[i][3]
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if klines[j][2] > h_val:
                is_high = False
            if klines[j][3] < l_val:
                is_low = False
        if is_high:
            swings.append({'type': 'HIGH', 'index': i, 'price': h_val, 'time': klines[i][0]})
        if is_low:
            swings.append({'type': 'LOW', 'index': i, 'price': l_val, 'time': klines[i][0]})
    return swings

def detect_liquidity_sweep(klines, swings):
    if not klines or len(klines) < 5 or not swings:
        return 'NONE', 0.0, 0
    
    curr = klines[-2]  # Confirmed closed candle
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    for h in highs:
        if curr[2] > h['price'] and curr[4] < h['price']:
            return 'BEARISH_SWEEP', h['price'], h['index']
            
    for l in lows:
        if curr[3] < l['price'] and curr[4] > l['price']:
            return 'BULLISH_SWEEP', l['price'], l['index']
            
    return 'NONE', 0.0, 0

def analyze_structure_and_mss(klines, swings):
    trend = 'NEUTRAL'
    bos_type = 'NONE'
    bos_level = 0.0
    mss_type = 'NONE'
    
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            trend = 'BULLISH'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            trend = 'BEARISH'

    if klines and len(klines) >= 3:
        closed_candle = klines[-2]
        close_p = closed_candle[4]
        
        # BOS & MSS analysis with protected structure checks
        if highs:
            last_h = highs[-1]['price']
            if close_p > last_h:
                bos_type = 'BULLISH_BOS'
                bos_level = last_h
        if lows:
            last_l = lows[-1]['price']
            if close_p < last_l:
                bos_type = 'BEARISH_BOS'
                bos_level = last_l

        # Real MSS: Requires previous bearish/bullish sequence and break of protected swing level
        if trend == 'BEARISH' and highs:
            protected_high = highs[-1]['price']
            if close_p > protected_high:
                mss_type = 'BULLISH_MSS'
        elif trend == 'BULLISH' and lows:
            protected_low = lows[-1]['price']
            if close_p < protected_low:
                mss_type = 'BEARISH_MSS'

    return {
        'trend': trend,
        'bos': bos_type,
        'bos_level': bos_level,
        'mss': mss_type,
        'swings': swings
    }

def check_displacement(klines, direction='BULLISH'):
    if not klines or len(klines) < 5:
        return False, 0.0, 'NEUTRAL'
    recent = klines[-2]  # Confirmed closed candle
    body = abs(recent[4] - recent[1])
    rng = recent[2] - recent[3]
    if rng == 0:
        return False, 0.0, 'NEUTRAL'
    
    avg_rng = sum([k[2] - k[3] for k in klines[-10:-1]]) / min(10, len(klines))
    is_disp = body > (avg_rng * 1.3) and (body / rng) > 0.65
    cand_dir = 'BULLISH' if recent[4] > recent[1] else 'BEARISH'
    
    if is_disp and cand_dir == direction:
        return True, body, cand_dir
    return False, body, cand_dir

def check_volume(klines):
    if not klines or len(klines) < 10:
        return 'NEUTRAL'
    curr_vol = klines[-2][5]
    avg_vol = sum([k[5] for k in klines[-11:-2]]) / 9
    if avg_vol > 0 and curr_vol >= avg_vol * 1.5:
        return 'CONFIRMED'
    elif curr_vol < avg_vol * 0.5:
        return 'WEAK'
    return 'NEUTRAL'

def find_order_blocks(klines, current_price):
    bullish_obs = []
    bearish_obs = []
    if not klines or len(klines) < 10:
        return bullish_obs, bearish_obs

    for i in range(1, len(klines) - 2):
        k = klines[i]
        next_k = klines[i+1]
        
        # Bullish OB: last bearish candle before upward move
        if k[4] < k[1] and next_k[4] > next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines[i+2:]:
                if scan[4] < ob_low:
                    status = 'BROKEN'
                    break
                elif scan[4] > ob_high and status != 'BROKEN':
                    status = 'TESTED'
            
            mid = (ob_high + ob_low) / 2
            dist = abs(current_price - mid) / current_price
            
            bullish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'index': i,
                'time': k[0],
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'FRESH' else 'MEDIUM',
                'direction': 'BULLISH'
            })

        # Bearish OB: last bullish candle before downward move
        elif k[4] > k[1] and next_k[4] < next_k[1]:
            ob_low = k[3]
            ob_high = k[2]
            status = 'FRESH'
            
            for scan in klines[i+2:]:
                if scan[4] > ob_high:
                    status = 'BROKEN'
                    break
                elif scan[4] < ob_low and status != 'BROKEN':
                    status = 'TESTED'

            mid = (ob_high + ob_low) / 2
            dist = abs(current_price - mid) / current_price
            
            bearish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'index': i,
                'time': k[0],
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'FRESH' else 'MEDIUM',
                'direction': 'BEARISH'
            })

    return bullish_obs, bearish_obs

def is_price_at_ob(current_price, ob, atr, direction):
    if not ob or ob['status'] == 'BROKEN':
        return False
    max_distance = atr * 0.25
    if direction == 'LONG':
        # Inside OB or below/above within 0.25 ATR without chasing
        if ob['low'] - max_distance <= current_price <= ob['high'] + max_distance:
            return True
    else:
        if ob['low'] - max_distance <= current_price <= ob['high'] + max_distance:
            return True
    return False

def select_best_order_block(obs, current_price, atr, direction):
    valid_obs = [ob for ob in obs if ob['status'] != 'BROKEN' and is_price_at_ob(current_price, ob, atr, direction)]
    if not valid_obs:
        return None
    valid_obs.sort(key=lambda x: (0 if x['status'] == 'FRESH' else 1, x['distance']))
    return valid_obs[0]

def get_btc_context():
    klines = get_bingx_klines('BTC-USDT', '1h', 30)
    if not klines or len(klines) < 10:
        return 'NEUTRAL'
    c = klines[-1][4]
    ma = sum([k[4] for k in klines[-15:]]) / min(15, len(klines))
    if c > ma * 1.015:
        return 'STRONG_BULLISH'
    elif c > ma * 1.005:
        return 'BULLISH'
    elif c < ma * 0.985:
        return 'STRONG_BEARISH'
    elif c < ma * 0.995:
        return 'BEARISH'
    return 'NEUTRAL'

def analyze_multitimeframe_structure(symbol):
    klines_4h = get_bingx_klines(symbol, '4h', 50)
    klines_1h = get_bingx_klines(symbol, '1h', 50)
    klines_30m = get_bingx_klines(symbol, '30m', 30)
    klines_15m = get_bingx_klines(symbol, '15m', 30)

    if not klines_4h or not klines_1h or not klines_30m or not klines_15m:
        return None

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    atr_15m = calculate_atr(klines_15m)

    swings_15m = calculate_swings(klines_15m)
    sweep_15m, sweep_lvl_15m, sweep_idx_15m = detect_liquidity_sweep(klines_15m, swings_15m)
    
    swings_30m = calculate_swings(klines_30m)
    sweep_30m, sweep_lvl_30m, sweep_idx_30m = detect_liquidity_sweep(klines_30m, swings_30m)

    struct_15m = analyze_structure_and_mss(klines_15m, swings_15m)
    struct_30m = analyze_structure_and_mss(klines_30m, swings_30m)
    struct_4h = analyze_structure_and_mss(klines_4h, calculate_swings(klines_4h))

    bullish_obs_4h, bearish_obs_4h = find_order_blocks(klines_4h, current_price)
    bullish_obs_1h, bearish_obs_1h = find_order_blocks(klines_1h, current_price)
    
    best_bullish_ob = select_best_order_block(bullish_obs_4h + bullish_obs_1h, current_price, atr_15m, 'LONG')
    best_bearish_ob = select_best_order_block(bearish_obs_4h + bearish_obs_1h, current_price, atr_15m, 'SHORT')
    
    disp_15m_long, _, disp_dir_long = check_displacement(klines_15m, 'BULLISH')
    disp_15m_short, _, disp_dir_short = check_displacement(klines_15m, 'BEARISH')
    
    vol_status = check_volume(klines_15m)
    btc_ctx = get_btc_context()

    direction = 'NONE'
    no_trade_reason = 'DATA_INSUFFICIENT'

    # Mandatory Gates & Validation
    is_long_valid = False
    is_short_valid = False

    if best_bullish_ob and (struct_15m['mss'] == 'BULLISH_MSS' or struct_15m['bos'] == 'BULLISH_BOS') and disp_15m_long:
        if struct_30m['trend'] != 'BEARISH' and btc_ctx != 'STRONG_BEARISH':
            is_long_valid = True
        else:
            no_trade_reason = '30M_CONFLICT' if struct_30m['trend'] == 'BEARISH' else 'BTC_STRONG_CONFLICT'
    elif best_bearish_ob and (struct_15m['mss'] == 'BEARISH_MSS' or struct_15m['bos'] == 'BEARISH_BOS') and disp_15m_short:
        if struct_30m['trend'] != 'BULLISH' and btc_ctx != 'STRONG_BULLISH':
            is_short_valid = True
        else:
            no_trade_reason = '30M_CONFLICT' if struct_30m['trend'] == 'BULLISH' else 'BTC_STRONG_CONFLICT'
    else:
        if not best_bullish_ob and not best_bearish_ob:
            no_trade_reason = 'NO_VALID_OB'
        elif struct_15m['mss'] == 'NONE' and struct_15m['bos'] == 'NONE':
            no_trade_reason = 'NO_MSS_OR_BOS'
        elif not disp_15m_long and not disp_15m_short:
            no_trade_reason = 'NO_DIRECTIONAL_DISPLACEMENT'
        else:
            no_trade_reason = 'NO_VALID_OB'

    # Directional Scoring (Max 100)
    if is_long_valid:
        direction = 'LONG'
        htf_score = 20 if struct_4h['trend'] == 'BULLISH' else 10
        ob_score = 20 if best_bullish_ob else 0
        mss_score = 20 if (struct_15m['mss'] == 'BULLISH_MSS' or struct_15m['bos'] == 'BULLISH_BOS') else 0
        disp_score = 15 if disp_15m_long else 0
        vol_score = 10 if vol_status == 'CONFIRMED' else (5 if vol_status == 'NEUTRAL' else 0)
        liq_score = 10 if sweep_15m == 'BULLISH_SWEEP' or sweep_30m == 'BULLISH_SWEEP' else 0
        btc_score = 5 if btc_ctx in ['BULLISH', 'STRONG_BULLISH'] else 3
        score = htf_score + ob_score + mss_score + disp_score + vol_score + liq_score + btc_score
    elif is_short_valid:
        direction = 'SHORT'
        htf_score = 20 if struct_4h['trend'] == 'BEARISH' else 10
        ob_score = 20 if best_bearish_ob else 0
        mss_score = 20 if (struct_15m['mss'] == 'BEARISH_MSS' or struct_15m['bos'] == 'BEARISH_BOS') else 0
        disp_score = 15 if disp_15m_short else 0
        vol_score = 10 if vol_status == 'CONFIRMED' else (5 if vol_status == 'NEUTRAL' else 0)
        liq_score = 10 if sweep_15m == 'BEARISH_SWEEP' or sweep_30m == 'BEARISH_SWEEP' else 0
        btc_score = 5 if btc_ctx in ['BEARISH', 'STRONG_BEARISH'] else 3
        score = htf_score + ob_score + mss_score + disp_score + vol_score + liq_score + btc_score
    else:
        score = 40

    if score < 78 and direction != 'NONE':
        direction = 'NONE'
        no_trade_reason = 'POOR_RR'

    return {
        'symbol': symbol,
        'direction': direction,
        'score': score,
        'price': current_price,
        'atr': atr_15m,
        'klines_15m': klines_15m,
        'reasons': ["اكتمال كافة شروط الدخول المؤسسي وهيكل SMC بنجاح."],
        'no_trade_reason': no_trade_reason,
        'btc_context': btc_ctx,
        'best_bullish_ob': best_bullish_ob,
        'best_bearish_ob': best_bearish_ob,
        'struct_15m': struct_15m,
        'struct_30m': struct_30m,
        'sweep_15m': sweep_15m,
        'sweep_30m': sweep_30m,
        'disp_15m_long': disp_15m_long,
        'disp_15m_short': disp_15m_short,
        'vol_status': vol_status
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    data = analyze_multitimeframe_structure(symbol)
    
    if not data or data['direction'] == 'NONE':
        nt_reason = data.get('no_trade_reason', 'NO_VALID_OB') if data else 'DATA_INSUFFICIENT'
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': nt_reason,
            'details': data or {}
        }

    direction = data['direction']
    p = data['price']
    atr = data['atr']
    buffer = atr * 0.25

    if direction == 'LONG':
        ob = data['best_bullish_ob']
        if not ob:
            return {'no_trade': True, 'symbol': symbol, 'reason': 'NO_VALID_OB', 'details': data}
        
        raw_sl = min(ob['low'], p - (atr * 1.0))
        stop_loss = smart_round(raw_sl - buffer)
        risk_dist = p - stop_loss
        sl_pct = round((risk_dist / p) * 100, 2)
        
        if sl_pct > MAX_SL_PCT:
            return {'no_trade': True, 'symbol': symbol, 'reason': 'WIDE_STOP', 'details': data}
        if sl_pct < MIN_SL_PCT:
            stop_loss = smart_round(p - (p * (MIN_SL_PCT / 100.0)))
            risk_dist = p - stop_loss
            sl_pct = MIN_SL_PCT

        tp1 = smart_round(p + (risk_dist * 1.5))
        tp2 = smart_round(p + (risk_dist * 2.5))
        tp3 = smart_round(p + (risk_dist * 3.5))
        
    else:
        ob = data['best_bearish_ob']
        if not ob:
            return {'no_trade': True, 'symbol': symbol, 'reason': 'NO_VALID_OB', 'details': data}
            
        raw_sl = max(ob['high'], p + (atr * 1.0))
        stop_loss = smart_round(raw_sl + buffer)
        risk_dist = stop_loss - p
        sl_pct = round((risk_dist / p) * 100, 2)
        
        if sl_pct > MAX_SL_PCT:
            return {'no_trade': True, 'symbol': symbol, 'reason': 'WIDE_STOP', 'details': data}
        if sl_pct < MIN_SL_PCT:
            stop_loss = smart_round(p + (p * (MIN_SL_PCT / 100.0)))
            risk_dist = stop_loss - p
            sl_pct = MIN_SL_PCT

        tp1 = smart_round(p - (risk_dist * 1.5))
        tp2 = smart_round(p - (risk_dist * 2.5))
        tp3 = smart_round(p - (risk_dist * 3.5))

    rr_tp1 = (abs(tp1 - p) / risk_dist) if risk_dist > 0 else 0
    if rr_tp1 < 1.5:
        return {'no_trade': True, 'symbol': symbol, 'reason': 'POOR_RR', 'details': data}

    return {
        'no_trade': False,
        'symbol': symbol,
        'direction': direction,
        'score': data['score'],
        'state': 'ACTIVE',
        'price': smart_round(p),
        'entry_min': smart_round(p * 0.998 if direction == 'LONG' else p * 1.002),
        'entry_max': smart_round(p * 1.002 if direction == 'LONG' else p * 0.998),
        'stop_loss': stop_loss,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'sl_pct': abs(sl_pct),
        'order_block': f"{smart_round(ob.get('low', p))} - {smart_round(ob.get('high', p))}",
        'reason': data['reasons'][0],
        'details': data
    }

def get_coin_analysis(symbol, interval='1h'):
    norm = normalize_symbol(symbol)
    if norm == 'TREND_COMMAND':
        return "⚠️ تم إلغاء المسح العشوائي. يرجى إرسال اسم العملة التي ترغب في تحليلها مباشرةً."
    try:
        res = _get_coin_analysis_core(symbol, interval)
        return res
    except Exception as e:
        logger.error(f"Error in analysis for {symbol}: {e}")
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': "DATA_INSUFFICIENT"
        }

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    if not d:
        return '🟡 **NO TRADE**\nلم يتم العثور حاليًا على فرصة دخول فورية مكتملة الشروط.'
    
    if d.get('no_trade', True):
        sym = d.get('symbol', '-').replace('-USDT','')
        rsn = d.get('reason', 'NO_VALID_OB')
        det = d.get('details', {})
        
        struct_trend = det.get('struct_15m', {}).get('trend', 'NEUTRAL')
        ob_valid = 'YES' if (det.get('best_bullish_ob') or det.get('best_bearish_ob')) else 'NO'
        sweep_res = det.get('sweep_15m', 'NONE')
        mss_res = det.get('struct_15m', {}).get('mss', 'NONE')
        bos_res = det.get('struct_15m', {}).get('bos', 'NONE')
        disp_res = 'YES' if (det.get('disp_15m_long') or det.get('disp_15m_short')) else 'NO'
        vol_res = det.get('vol_status', 'NEUTRAL')
        btc_ctx = det.get('btc_context', 'NEUTRAL')

        lines = [
            f"🟡 **NO TRADE** | ${sym}",
            f"❌ Entry Gate Failed",
            f"📊 Structure: `{struct_trend}`",
            f"📌 OB: `{'VALID' if ob_valid == 'YES' else 'INVALID'}`",
            f"💧 Liquidity Sweep: `{sweep_res}`",
            f"🧠 MSS: `{mss_res}`",
            f"📊 BOS: `{bos_res}`",
            f"⚡ Displacement: `{disp_res}`",
            f"📈 Volume: `{vol_res}`",
            f"₿ BTC: `{btc_ctx}`",
            f"❌ السبب الرئيسي:\n`{rsn}`"
        ]
        return '\n'.join(lines)
    
    dr = d.get('direction', 'LONG')
    emo, text_dir = ('🟢', 'MARKET LONG') if dr == 'LONG' else ('🔴', 'MARKET SHORT')
    sym = d.get('symbol', '-').replace('-USDT','')
    score = d.get('score', 80)
    det = d.get('details', {})

    if score >= 90:
        grade = 'إيجابي قوي جدًا'
    elif score >= 85:
        grade = 'إيجابي قوي'
    else:
        grade = 'إيجابي متوسط'

    sweep_res = det.get('sweep_15m', 'NONE')
    mss_res = det.get('struct_15m', {}).get('mss', 'NONE')
    bos_res = det.get('struct_15m', {}).get('bos', 'NONE')
    disp_res = 'YES' if (det.get('disp_15m_long') or det.get('disp_15m_short')) else 'NO'
    vol_res = det.get('vol_status', 'NEUTRAL')
    btc_ctx = det.get('btc_context', 'NEUTRAL')

    lines = [
        f"🤖 **BingX Institutional SMC v49.3**",
        f"💎 العملة: `{sym}-USDT`",
        f"📈 القرار:",
        f"{emo} `{text_dir}`",
        f"🏆 Grade: `{grade}`",
        f"⭐ Score: `{score}/100`",
        f"💰 Price: `{d.get('price')}`",
        f"🎯 Entry: `{d.get('entry_min')} - {d.get('entry_max')}`",
        f"🛑 SL: `{d.get('stop_loss')}` 📊 Risk: `{d.get('sl_pct')}%`",
        f"🎯 TP1: `{d.get('tp1')}`",
        f"🎯 TP2: `{d.get('tp2')}`",
        f"🎯 TP3: `{d.get('tp3')}`",
        f"📌 OB: `{d.get('order_block')}`",
        f"💧 Sweep: `{sweep_res}`",
        f"🧠 MSS: `{mss_res}`",
        f"📊 BOS: `{bos_res}`",
        f"⚡ Displacement: `{disp_res}`",
        f"📈 Volume: `{vol_res}`",
        f"₿ BTC: `{btc_ctx}`",
        f"📍 Entry Location: `VALID`",
        f"📝 Reason:\n`{d.get('reason')}`"
    ]
        
    return '\n'.join(lines)
