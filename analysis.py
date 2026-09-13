# =========================================================
# analysis.py - BingX Institutional SMC Execution Tool v49.1
# =========================================================
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/49.1', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3
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

def analyze_structure(klines):
    swings = calculate_swings(klines)
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    trend = 'NEUTRAL'
    bos_type = 'NONE'
    mss_type = 'NONE'
    
    if len(highs) >= 2 and len(lows) >= 2:
        last_h = highs[-1]['price']
        prev_h = highs[-2]['price']
        last_l = lows[-1]['price']
        prev_l = lows[-2]['price']
        
        if last_h > prev_h and last_l > prev_l:
            trend = 'BULLISH'
        elif last_h < prev_h and last_l < prev_l:
            trend = 'BEARISH'

    if klines and len(klines) >= 3:
        curr_close = klines[-1][4]
        if highs:
            last_swing_high = highs[-1]['price']
            if curr_close > last_swing_high:
                bos_type = 'BULLISH_BOS'
        if lows:
            last_swing_low = lows[-1]['price']
            if curr_close < last_swing_low:
                bos_type = 'BEARISH_BOS'

    return {
        'trend': trend,
        'bos': bos_type,
        'mss': mss_type,
        'swings': swings
    }

def check_displacement(klines):
    if not klines or len(klines) < 5:
        return False, 0.0, 'NEUTRAL'
    recent = klines[-1]
    body = abs(recent[4] - recent[1])
    rng = recent[2] - recent[3]
    if rng == 0:
        return False, 0.0, 'NEUTRAL'
    
    avg_rng = sum([k[2] - k[3] for k in klines[-10:]]) / min(10, len(klines))
    is_disp = body > (avg_rng * 1.3) and (body / rng) > 0.65
    direction = 'BULLISH' if recent[4] > recent[1] else 'BEARISH'
    return is_disp, body, direction

def check_volume(klines):
    if not klines or len(klines) < 10:
        return 'NEUTRAL'
    curr_vol = klines[-1][5]
    avg_vol = sum([k[5] for k in klines[-10:-1]]) / 9
    if avg_vol > 0 and curr_vol > avg_vol * 1.5:
        return 'CONFIRMED'
    elif curr_vol < avg_vol * 0.5:
        return 'WEAK'
    return 'NEUTRAL'

def detect_liquidity_sweep(klines, swings):
    if not klines or len(klines) < 10 or not swings:
        return 'NONE', 0.0
    curr = klines[-1]
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    for h in highs[:-1]:
        if curr[2] > h['price'] and curr[4] < h['price']:
            return 'BEARISH_SWEEP', h['price']
            
    for l in lows[:-1]:
        if curr[3] < l['price'] and curr[4] > l['price']:
            return 'BULLISH_SWEEP', l['price']
            
    return 'NONE', 0.0

def find_order_blocks(klines, current_price):
    bullish_obs = []
    bearish_obs = []
    if not klines or len(klines) < 10:
        return bullish_obs, bearish_obs

    for i in range(1, len(klines) - 1):
        k = klines[i]
        next_k = klines[i+1]
        
        # Bullish OB: last down candle before strong up move
        if k[4] < k[1] and next_k[4] > next_k[1] and (next_k[4] - next_k[1]) > (k[2] - k[3]):
            ob_low = k[3]
            ob_high = k[2]
            status = 'Fresh'
            if current_price < ob_low:
                status = 'Broken'
            elif current_price > ob_high and any(scan[3] < ob_low for scan in klines[i+2:]):
                status = 'Tested'
            
            dist = abs(current_price - ((ob_high + ob_low) / 2)) / current_price
            bullish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'Fresh' else 'MEDIUM'
            })

        # Bearish OB: last up candle before strong down move
        elif k[4] > k[1] and next_k[4] < next_k[1] and (next_k[1] - next_k[4]) > (k[2] - k[3]):
            ob_low = k[3]
            ob_high = k[2]
            status = 'Fresh'
            if current_price > ob_high:
                status = 'Broken'
            elif current_price < ob_low and any(scan[2] > ob_high for scan in klines[i+2:]):
                status = 'Tested'

            dist = abs(current_price - ((ob_high + ob_low) / 2)) / current_price
            bearish_obs.append({
                'low': ob_low,
                'high': ob_high,
                'status': status,
                'distance': dist,
                'strength': 'HIGH' if status == 'Fresh' else 'MEDIUM'
            })

    return bullish_obs, bearish_obs

def get_btc_context():
    klines = get_bingx_klines('BTC-USDT', '1h', 30)
    if not klines or len(klines) < 10:
        return 'NEUTRAL'
    c = klines[-1][4]
    ma = sum([k[4] for k in klines[-15:]]) / min(15, len(klines))
    if c > ma * 1.01:
        return 'BULLISH'
    elif c < ma * 0.99:
        return 'BEARISH'
    return 'NEUTRAL'

def analyze_multitimeframe_structure(symbol):
    klines_1d = get_bingx_klines(symbol, '1d', 30)
    klines_4h = get_bingx_klines(symbol, '4h', 50)
    klines_1h = get_bingx_klines(symbol, '1h', 50)
    klines_30m = get_bingx_klines(symbol, '30m', 30)
    klines_15m = get_bingx_klines(symbol, '15m', 30)

    if not klines_4h or not klines_1h or not klines_30m or not klines_15m:
        return None

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    struct_1d = analyze_structure(klines_1d) if klines_1d else {'trend': 'NEUTRAL', 'bos': 'NONE', 'mss': 'NONE', 'swings': []}
    struct_4h = analyze_structure(klines_4h)
    struct_1h = analyze_structure(klines_1h)
    struct_30m = analyze_structure(klines_30m)
    struct_15m = analyze_structure(klines_15m)

    swings_15m = calculate_swings(klines_15m)
    sweep_15m, sweep_lvl_15m = detect_liquidity_sweep(klines_15m, swings_15m)
    
    swings_30m = calculate_swings(klines_30m)
    sweep_30m, sweep_lvl_30m = detect_liquidity_sweep(klines_30m, swings_30m)

    bullish_obs, bearish_obs = find_order_blocks(klines_4h, current_price)
    
    disp_15m, disp_val_15m, disp_dir_15m = check_displacement(klines_15m)
    disp_30m, disp_val_30m, disp_dir_30m = check_displacement(klines_30m)
    vol_status = check_volume(klines_15m)
    btc_ctx = get_btc_context()

    direction = 'NONE'
    reasons = []

    # Determine potential setup direction based on 4H/1H structure & OB availability
    valid_bullish_ob = any(ob['status'] != 'Broken' and current_price >= ob['low'] * 0.98 for ob in bullish_obs)
    valid_bearish_ob = any(ob['status'] != 'Broken' and current_price <= ob['high'] * 1.02 for ob in bearish_obs)

    bullish_score = 0
    bearish_score = 0

    # Scoring Matrix components breakdown
    # Structure: 20, OB: 15, Liquidity: 15, MSS/BOS: 15, Displacement: 10, 15M/30M: 10, BTC: 5, Entry Loc: 5, R:R: 5
    struct_score = 20 if struct_4h['trend'] == 'BULLISH' or struct_1h['trend'] == 'BULLISH' else 10
    ob_score = 15 if valid_bullish_ob else 0
    liq_score = 15 if sweep_15m == 'BULLISH_SWEEP' or sweep_30m == 'BULLISH_SWEEP' else 5
    mss_bos_score = 15 if struct_15m['bos'] == 'BULLISH_BOS' or struct_15m['mss'] != 'NONE' or disp_15m else 5
    disp_score = 10 if disp_15m and disp_dir_15m == 'BULLISH' else 3
    tf_conf_score = 10 if struct_30m['trend'] != 'BEARISH' else 3
    btc_score = 5 if btc_ctx != 'BEARISH' else 2
    loc_score = 5 if valid_bullish_ob else 2
    rr_score = 5

    total_bullish_score = struct_score + ob_score + liq_score + mss_bos_score + disp_score + tf_conf_score + btc_score + loc_score + rr_score

    # Repeat for bearish evaluation
    b_struct_score = 20 if struct_4h['trend'] == 'BEARISH' or struct_1h['trend'] == 'BEARISH' else 10
    b_ob_score = 15 if valid_bearish_ob else 0
    b_liq_score = 15 if sweep_15m == 'BEARISH_SWEEP' or sweep_30m == 'BEARISH_SWEEP' else 5
    b_mss_bos_score = 15 if struct_15m['bos'] == 'BEARISH_BOS' or struct_15m['mss'] != 'NONE' or disp_15m else 5
    b_disp_score = 10 if disp_15m and disp_dir_15m == 'BEARISH' else 3
    b_tf_conf_score = 10 if struct_30m['trend'] != 'BULLISH' else 3
    b_btc_score = 5 if btc_ctx != 'BULLISH' else 2
    b_loc_score = 5 if valid_bearish_ob else 2
    b_rr_score = 5

    total_bearish_score = b_struct_score + b_ob_score + b_liq_score + b_mss_bos_score + b_disp_score + b_tf_conf_score + b_btc_score + b_loc_score + b_rr_score

    # Entry Gate Validation
    is_long_gate = (
        valid_bullish_ob and
        (struct_15m['bos'] != 'NONE' or disp_15m or struct_15m['mss'] != 'NONE') and
        btc_ctx != 'BEARISH'
    )

    is_short_gate = (
        valid_bearish_ob and
        (struct_15m['bos'] != 'NONE' or disp_15m or struct_15m['mss'] != 'NONE') and
        btc_ctx != 'BULLISH'
    )

    if is_long_gate and total_bullish_score >= total_bearish_score:
        direction = 'LONG'
        score = total_bullish_score
        reasons.append("توافق هيكل البنية مع Order Block صالح وتأكيد فريمات أدنى.")
    elif is_short_gate and total_bearish_score > total_bullish_score:
        direction = 'SHORT'
        score = total_bearish_score
        reasons.append("توافق هيكل الهبوط مع Order Block هابط وتأكيد فريمات أدنى.")
    else:
        direction = 'NONE'
        score = max(total_bullish_score, total_bearish_score)
        reasons.append("شروط بوابة الدخول المؤسسي (Entry Gate) غير مكتملة بالكامل.")

    atr = calculate_atr(klines_15m)

    return {
        'symbol': symbol,
        'direction': direction,
        'score': score,
        'price': current_price,
        'atr': atr,
        'klines_15m': klines_15m,
        'reasons': reasons,
        'btc_context': btc_ctx,
        'bullish_obs': bullish_obs,
        'bearish_obs': bearish_obs,
        'struct_15m': struct_15m,
        'struct_30m': struct_30m,
        'sweep_15m': sweep_15m,
        'sweep_30m': sweep_30m,
        'disp_15m': disp_15m,
        'vol_status': vol_status,
        'valid_bullish_ob': valid_bullish_ob,
        'valid_bearish_ob': valid_bearish_ob
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    data = analyze_multitimeframe_structure(symbol)
    if not data or data['direction'] == 'NONE' or data['score'] < 75:
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': data['reasons'][0] if data and data['reasons'] else "لم تكتمل شروط الدخول المؤسسي بدقة.",
            'details': data
        }

    direction = data['direction']
    p = data['price']
    atr = data['atr']

    if direction == 'LONG':
        ob_zone = data['bullish_obs'][0] if data['bullish_obs'] else {'low': p * 0.98, 'high': p * 0.99}
        stop_loss = smart_round(min(ob_zone['low'] - (atr * 1.2), p * 0.97))
        risk_dist = p - stop_loss
        tp1 = smart_round(p + (risk_dist * 1.2))
        tp2 = smart_round(p + (risk_dist * 2.0))
        tp3 = smart_round(p + (risk_dist * 3.0))
        sl_pct = round((risk_dist / p) * 100, 2)
    else:
        ob_zone = data['bearish_obs'][0] if data['bearish_obs'] else {'low': p * 1.01, 'high': p * 1.02}
        stop_loss = smart_round(max(ob_zone['high'] + (atr * 1.2), p * 1.03))
        risk_dist = stop_loss - p
        tp1 = smart_round(p - (risk_dist * 1.2))
        tp2 = smart_round(p - (risk_dist * 2.0))
        tp3 = smart_round(p - (risk_dist * 3.0))
        sl_pct = round((risk_dist / p) * 100, 2)

    if sl_pct > 7.0 or sl_pct < 0.4:
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': f"مخاطرة غير مناسبة (نسبة الوقف {sl_pct}% غير آمنة).",
            'details': data
        }

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
        'order_block': f"{smart_round(ob_zone.get('low', p))} - {smart_round(ob_zone.get('high', p))}",
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
            'reason': "حدث خطأ تقني أو نقص في البيانات أثناء التحليل."
        }

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    if not d:
        return '🟡 **NO TRADE**\nلم يتم العثور حاليًا على فرصة دخول فورية مكتملة الشروط.'
    
    if d.get('no_trade', True):
        sym = d.get('symbol', '-').replace('-USDT','')
        rsn = d.get('reason', 'لم تكتمل الشروط المؤسسية.')
        det = d.get('details', {})
        
        struct_trend = det.get('struct_15m', {}).get('trend', 'NEUTRAL')
        ob_valid = 'YES' if (det.get('valid_bullish_ob') or det.get('valid_bearish_ob')) else 'NO'
        sweep_res = 'YES' if (det.get('sweep_15m') != 'NONE' or det.get('sweep_30m') != 'NONE') else 'NO'
        mss_res = 'YES' if det.get('struct_15m', {}).get('mss') != 'NONE' else 'NO'
        bos_res = 'YES' if det.get('struct_15m', {}).get('bos') != 'NONE' else 'NO'
        disp_res = 'YES' if det.get('disp_15m') else 'NO'
        vol_res = det.get('vol_status', 'NEUTRAL')
        btc_ctx = det.get('btc_context', 'NEUTRAL')

        lines = [
            f"🟡 **NO TRADE** | ${sym}",
            f"❌ Entry Gate Failed",
            f"📊 Structure: `{struct_trend}`",
            f"📌 OB: `{'VALID' if ob_valid == 'YES' else 'INVALID'}`",
            f"💧 Liquidity Sweep: `{sweep_res}`",
            f"🧠 MSS: `{mss_res}` | BOS: `{bos_res}`",
            f"⚡ Displacement: `{disp_res}`",
            f"📈 Volume: `{vol_res}`",
            f"₿ BTC: `{btc_ctx}`",
            f"❌ السبب الرئيسي:\n`{rsn}`"
        ]
        return '\n'.join(lines)
    
    dr = d.get('direction', 'LONG')
    emo, text_dir = ('🟢', 'MARKET LONG') if dr == 'LONG' else ('🔴', 'MARKET SHORT')
    sym = d.get('symbol', '-').replace('-USDT','')
    det = d.get('details', {})

    ob_valid = 'YES' if (det.get('valid_bullish_ob') or det.get('valid_bearish_ob')) else 'NO'
    sweep_res = 'YES' if (det.get('sweep_15m') != 'NONE' or det.get('sweep_30m') != 'NONE') else 'NO'
    mss_res = 'YES' if det.get('struct_15m', {}).get('mss') != 'NONE' else 'NO'
    bos_res = 'YES' if det.get('struct_15m', {}).get('bos') != 'NONE' else 'NO'
    disp_res = 'YES' if det.get('disp_15m') else 'NO'
    vol_res = det.get('vol_status', 'NEUTRAL')
    btc_ctx = det.get('btc_context', 'NEUTRAL')

    grade = "إيجابي قوي" if d.get('score', 0) >= 85 else "جيد"

    lines = [
        f"🤖 **BingX Institutional SMC v49.1**",
        f"💎 العملة: `{sym}-USDT`",
        f"📈 القرار النهائي: `{emo} {text_dir}`",
        f"🏆 Grade: `{grade}`",
        f"⭐ Score: `{d.get('score')}/100`",
        f"💰 Current Price: `{d.get('price')}`",
        f"🎯 Entry: `{d.get('entry_min')} - {d.get('entry_max')}`",
        f"🛑 SL: `{d.get('stop_loss')}` 📊 Risk: `{d.get('sl_pct')}%`",
        f"🎯 TP1: `{d.get('tp1')}`",
        f"🎯 TP2: `{d.get('tp2')}`",
        f"🎯 TP3: `{d.get('tp3')}`",
        f"📌 OB: `{d.get('order_block')}`",
        f"💧 Liquidity Sweep: `{sweep_res}`",
        f"🧠 MSS: `{mss_res}`",
        f"📊 BOS: `{bos_res}`",
        f"⚡ Displacement: `{disp_res}`",
        f"📈 Volume: `{vol_res}`",
        f"₿ BTC Context: `{btc_ctx}`",
        f"📝 Entry Reason:\n`{d.get('reason')}`"
    ]
        
    return '\n'.join(lines)
