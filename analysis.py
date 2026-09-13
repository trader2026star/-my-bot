# =========================================================
# analysis.py - BingX Institutional SMC Execution Tool v49.8
# =========================================================
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/49.8', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.3
MAX_SL_PCT = 15.0  # الحد الأقصى للوقف للعملات البديلة
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

def detect_liquidity_sweep(klines, swings, direction_filter=None):
    if not klines or len(klines) < 5 or not swings:
        return 'NONE', 0.0, 0
    
    curr = klines[-2]
    highs = [s for s in swings if s['type'] == 'HIGH']
    lows = [s for s in swings if s['type'] == 'LOW']
    
    if direction_filter in [None, 'SHORT']:
        for h in highs:
            if curr[2] > h['price'] and curr[4] < h['price']:
                return 'BEARISH_SWEEP', h['price'], h['index']
                
    if direction_filter in [None, 'LONG']:
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

def find_order_blocks(klines, current_price):
    bullish_obs = []
    bearish_obs = []
    if not klines or len(klines) < 10:
        return bullish_obs, bearish_obs

    for i in range(1, len(klines) - 2):
        k = klines[i]
        next_k = klines[i+1]
        
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

def is_price_at_ob(current_price, ob, atr):
    if not ob or ob['status'] == 'BROKEN':
        return False, 'INVALID'
    max_distance = atr * 0.25
    ob_low = ob['low']
    ob_high = ob['high']
    
    if ob_low - max_distance <= current_price <= ob_high + max_distance:
        return True, 'VALID'
    elif current_price < ob_low - max_distance or current_price > ob_high + max_distance:
        return False, 'CHASING_PRICE'
    return False, 'INVALID'

def select_best_order_block(obs, current_price, atr):
    valid_obs = []
    for ob in obs:
        if ob['status'] == 'BROKEN':
            continue
        at_ob, loc_status = is_price_at_ob(current_price, ob, atr)
        if at_ob:
            valid_obs.append((ob, 'VALID', abs(current_price - ((ob['high'] + ob['low']) / 2))))
        else:
            valid_obs.append((ob, loc_status, abs(current_price - ((ob['high'] + ob['low']) / 2))))
            
    if not valid_obs:
        return None, 'NO_VALID_OB', []
        
    strictly_valid = [x for x in valid_obs if x[1] == 'VALID']
    if strictly_valid:
        strictly_valid.sort(key=lambda x: (0 if x[0]['status'] == 'FRESH' else 1, x[2]))
        return strictly_valid[0][0], 'VALID', [x[1] for x in valid_obs]
        
    chasing = [x for x in valid_obs if x[1] == 'CHASING_PRICE']
    if chasing:
        chasing.sort(key=lambda x: x[2])
        return chasing[0][0], 'CHASING_PRICE', [x[1] for x in valid_obs]
        
    return None, 'NO_VALID_OB', []

def calculate_position_size(account_balance, entry_price, stop_loss_price, max_risk_pct=0.01):
    stop_distance_pct = abs(entry_price - stop_loss_price) / entry_price
    DYNAMIC_MAX_STOP = 0.15  
    
    if stop_distance_pct > DYNAMIC_MAX_STOP:
        return {"action": "REJECT", "reason": "WIDE_STOP_ABSOLUTE_LIMIT"}
        
    risk_amount_usd = account_balance * max_risk_pct
    position_size_usd = risk_amount_usd / stop_distance_pct if stop_distance_pct > 0 else 0
    
    return {
        "action": "TRADE",
        "position_size": position_size_usd,
        "stop_loss_pct": stop_distance_pct * 100
    }

def check_entry_gate_v2(market_data):
    score = 0
    structure = market_data.get('structure', 'NEUTRAL')
    decision_type = market_data.get('decision')
    
    if decision_type == 'SHORT' and structure == 'BULLISH':
        if market_data.get('liquidity_sweep') != 'BEARISH_SWEEP':
            return {"status": "NO_TRADE", "score": 0, "reason": "TREND_MISMATCH_ANTI_TREND_SHORT"}
            
    if market_data.get('entry_location') == 'VALID / PENDING':
        score += 35
        
    if market_data.get('liquidity_sweep') in ['BULLISH_SWEEP', 'BEARISH_SWEEP']:
        score += 30
        
    if market_data.get('structure') in ['BULLISH', 'BEARISH']:
        score += 20

    entry_price = market_data.get('entry_price', 0)
    stop_loss_price = market_data.get('stop_price', 0)
    
    if entry_price > 0 and stop_loss_price > 0:
        stop_distance_pct = abs(entry_price - stop_loss_price) / entry_price
        DYNAMIC_MAX_STOP = 0.15 
        
        if stop_distance_pct > DYNAMIC_MAX_STOP:
            return {"status": "NO_TRADE", "score": score, "reason": "WIDE_STOP_ABSOLUTE_LIMIT"}

    if score >= 50:
        grade = "إيجابي قوي" if score >= 75 else "إيجابي متوسط"
        return {
            "status": "TRADE",
            "score": score,
            "grade": grade,
            "action": market_data.get('decision'),
            "reason": "اجتياز فحص المنظومة الذكية وتعديل حجم العقد بناءً على الوقف بنجاح."
        }
    else:
        return {"status": "NO_TRADE", "score": score, "reason": "LOW_SCORE_CONFIRMATION"}

def dynamic_entry_and_rr_resolver(market_data):
    """
    تحديث النسخة v49.8: 
    1. منع فخ الشراء الماركت عند ابتعاد السعر (حل مشكلة ARK).
    2. إصلاح معادلة الأهداف لرفع قيمة الـ Risk to Reward والتخلص من POOR_RR.
    """
    entry_price = market_data.get('price')
    ob_high = market_data.get('ob_high', entry_price)
    ob_low = market_data.get('ob_low', entry_price)
    decision = market_data.get('decision')
    
    price_distance_pct = 0.0
    if decision == 'LONG' and ob_high > 0:
        price_distance_pct = (entry_price - ob_high) / ob_high
        if price_distance_pct > 0.02:
            return {
                "status": "TRADE",
                "strategy_status": "PENDING_LIMIT",
                "entry_zone": f"{ob_high} - {smart_round(ob_high * 0.99)}",
                "stop_loss": market_data.get('sl_absolute_low', ob_low),
                "msg": "السعر ابتعد عن الـ OB. تم إلغاء الماركت وتحويلها إلى أمر معلق (Limit) عند حافة المنطقة لتحسين الـ RR وتقليل المخاطرة."
            }
    elif decision == 'SHORT' and ob_low > 0:
        price_distance_pct = (ob_low - entry_price) / ob_low
        if price_distance_pct > 0.02:
            return {
                "status": "TRADE",
                "strategy_status": "PENDING_LIMIT",
                "entry_zone": f"{ob_low} - {smart_round(ob_low * 1.01)}",
                "stop_loss": market_data.get('sl_absolute_high', ob_high),
                "msg": "السعر ابتعد عن الـ OB. تم إلغاء الماركت وتحويلها إلى أمر معلق (Limit) عند حافة المنطقة لتحسين الـ RR وتقليل المخاطرة."
            }
            
    sl_distance = abs(entry_price - market_data.get('sl_price', entry_price))
    if sl_distance == 0:
        sl_distance = entry_price * 0.01

    if decision == 'LONG':
        tp1 = entry_price + (sl_distance * 1.5)
        tp2 = entry_price + (sl_distance * 2.5)
        tp3 = entry_price + (sl_distance * 4.0)
    else:
        tp1 = entry_price - (sl_distance * 1.5)
        tp2 = entry_price - (sl_distance * 2.5)
        tp3 = entry_price - (sl_distance * 4.0)
        
    rr_ratio = (abs(entry_price - tp1)) / sl_distance
    if rr_ratio < 1.2:
        return {"status": "NO_TRADE", "reason": "TRUE_POOR_RR_AVOIDED"}

    return {
        "status": "TRADE",
        "strategy_status": "MARKET" if price_distance_pct <= 0.02 else "LIMIT",
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3
    }

def analyze_multitimeframe_structure(symbol):
    klines_4h = get_bingx_klines(symbol, '4h', 50)
    klines_1h = get_bingx_klines(symbol, '1h', 50)
    klines_30m = get_bingx_klines(symbol, '30m', 30)
    klines_15m = get_bingx_klines(symbol, '15m', 30)

    if not klines_4h or not klines_1h or not klines_30m or not klines_15m:
        klines_1m = get_bingx_klines(symbol, '1m', 50)
        if not klines_1m:
            return None
        klines_15m = klines_1m

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    atr_15m = calculate_atr(klines_15m)
    swings_15m = calculate_swings(klines_15m)
    swings_30m = calculate_swings(klines_30m)

    struct_15m = analyze_structure_and_mss(klines_15m, swings_15m)
    struct_30m = analyze_structure_and_mss(klines_30m, swings_30m)
    struct_4h = analyze_structure_and_mss(klines_4h, calculate_swings(klines_4h))

    bullish_obs_4h, bearish_obs_4h = find_order_blocks(klines_4h, current_price)
    bullish_obs_1h, bearish_obs_1h = find_order_blocks(klines_1h, current_price)
    
    all_bullish_obs = bullish_obs_4h + bullish_obs_1h
    all_bearish_obs = bearish_obs_4h + bearish_obs_1h

    best_bullish_ob, long_ob_status, _ = select_best_order_block(all_bullish_obs, current_price, atr_15m)
    best_bearish_ob, short_ob_status, _ = select_best_order_block(all_bearish_obs, current_price, atr_15m)

    sweep_15m_long, _, _ = detect_liquidity_sweep(klines_15m, swings_15m, 'LONG')
    sweep_15m_short, _, _ = detect_liquidity_sweep(klines_15m, swings_15m, 'SHORT')
    sweep_15m = sweep_15m_long if sweep_15m_long != 'NONE' else sweep_15m_short

    candidate_direction = 'LONG' if struct_15m['trend'] == 'BULLISH' else 'SHORT'
    if struct_15m['mss'] == 'BULLISH_MSS' or sweep_15m == 'BULLISH_SWEEP':
        candidate_direction = 'LONG'
    elif struct_15m['mss'] == 'BEARISH_MSS' or sweep_15m == 'BEARISH_SWEEP':
        candidate_direction = 'SHORT'

    chosen_ob = best_bullish_ob if candidate_direction == 'LONG' else best_bearish_ob
    ob_status = long_ob_status if candidate_direction == 'LONG' else short_ob_status

    market_data = {
        'structure': struct_15m['trend'],
        'decision': candidate_direction,
        'liquidity_sweep': sweep_15m,
        'entry_location': 'VALID / PENDING' if ob_status in ['VALID', 'CHASING_PRICE'] else 'INVALID',
        'entry_price': current_price,
        'stop_price': chosen_ob.get('low', current_price * 0.95) if candidate_direction == 'LONG' else chosen_ob.get('high', current_price * 1.05)
    }

    gate_result = check_entry_gate_v2(market_data)

    if gate_result['status'] == 'NO_TRADE':
        return {
            'symbol': symbol,
            'direction': 'NONE',
            'no_trade_reason': gate_result.get('reason', 'LOW_SCORE_CONFIRMATION'),
            'price': current_price,
            'atr': atr_15m,
            'score': gate_result.get('score', 0)
        }

    return {
        'symbol': symbol,
        'direction': candidate_direction,
        'score': gate_result.get('score', 80),
        'confirmation': gate_result.get('status', 'TRADE'),
        'grade': gate_result.get('grade', 'إيجابي متوسط'),
        'price': current_price,
        'atr': atr_15m,
        'chosen_ob': chosen_ob or {'low': current_price * 0.99, 'high': current_price * 1.01},
        'struct_15m': struct_15m,
        'struct_30m': struct_30m,
        'struct_4h': struct_4h,
        'sweep_15m': sweep_15m
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    data = analyze_multitimeframe_structure(symbol)
    
    if not data or data.get('direction') == 'NONE':
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
    ob = data['chosen_ob']

    if direction == 'LONG':
        raw_sl = min(ob.get('low', p), p - (atr * 1.0))
        stop_loss = smart_round(raw_sl - buffer)
        risk_dist = p - stop_loss
        sl_pct = round((risk_dist / p) * 100, 2)
    else:
        raw_sl = max(ob.get('high', p), p + (atr * 1.0))
        stop_loss = smart_round(raw_sl + buffer)
        risk_dist = stop_loss - p
        sl_pct = round((risk_dist / p) * 100, 2)

    pos_check = calculate_position_size(account_balance=1000, entry_price=p, stop_loss_price=stop_loss)
    if pos_check['action'] == 'REJECT':
        return {'no_trade': True, 'symbol': symbol, 'reason': 'WIDE_STOP_ABSOLUTE_LIMIT', 'details': data}

    if sl_pct < MIN_SL_PCT:
        stop_loss = smart_round(p - (p * (MIN_SL_PCT / 100.0))) if direction == 'LONG' else smart_round(p + (p * (MIN_SL_PCT / 100.0)))
        risk_dist = abs(p - stop_loss)
        sl_pct = MIN_SL_PCT

    resolver_input = {
        'price': p,
        'ob_high': ob.get('high', p),
        'ob_low': ob.get('low', p),
        'decision': direction,
        'sl_price': stop_loss,
        'sl_absolute_low': stop_loss,
        'sl_absolute_high': stop_loss
    }
    
    resolver_res = dynamic_entry_and_rr_resolver(resolver_input)
    if resolver_res.get('status') == 'NO_TRADE':
        return {'no_trade': True, 'symbol': symbol, 'reason': resolver_res.get('reason', 'TRUE_POOR_RR_AVOIDED'), 'details': data}

    strategy_status = resolver_res.get('strategy_status', 'MARKET')
    
    if strategy_status == 'PENDING_LIMIT':
        return {
            'no_trade': False,
            'is_pending_limit': True,
            'symbol': symbol,
            'direction': direction,
            'score': data['score'],
            'confirmation': data['confirmation'],
            'grade': data.get('grade', 'إيجابي متوسط'),
            'state': 'PENDING_LIMIT',
            'price': smart_round(p),
            'entry_zone': resolver_res.get('entry_zone'),
            'stop_loss': stop_loss,
            'sl_pct': abs(sl_pct),
            'position_size_usd': pos_check.get('position_size', 0),
            'reason': resolver_res.get('msg'),
            'details': data
        }

    tp1 = resolver_res.get('tp1')
    tp2 = resolver_res.get('tp2')
    tp3 = resolver_res.get('tp3')

    return {
        'no_trade': False,
        'is_pending_limit': False,
        'symbol': symbol,
        'direction': direction,
        'score': data['score'],
        'confirmation': data['confirmation'],
        'grade': data.get('grade', 'إيجابي متوسط'),
        'state': 'ACTIVE',
        'price': smart_round(p),
        'entry_min': smart_round(p * 0.998 if direction == 'LONG' else p * 1.002),
        'entry_max': smart_round(p * 1.002 if direction == 'LONG' else p * 0.998),
        'stop_loss': stop_loss,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'sl_pct': abs(sl_pct),
        'position_size_usd': pos_check.get('position_size', 0),
        'order_block': f"{smart_round(ob.get('low', p))} - {smart_round(ob.get('high', p))}",
        'reason': "اجتياز فحص المنظومة الذكية وتعديل الـ RR وإلغاء فخ المطاردة بنجاح.",
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
        sweep_res = det.get('sweep_15m', 'NONE')

        lines = [
            f"🟡 **NO TRADE** | ${sym}",
            f"❌ Entry Gate & RR Resolver Failed",
            f"📊 Structure: `{struct_trend}`",
            f"💧 Liquidity Sweep: `{sweep_res}`",
            f"❌ السبب الرئيسي:\n`{rsn}`"
        ]
        return '\n'.join(lines)
    
    dr = d.get('direction', 'LONG')
    emo, text_dir = ('🟢', 'MARKET LONG') if dr == 'LONG' else ('🔴', 'MARKET SHORT')
    sym = d.get('symbol', '-').replace('-USDT','')
    score = d.get('score', 80)
    grade = d.get('grade', 'إيجابي متوسط')
    conf = d.get('confirmation', 'TRADE')
    det = d.get('details', {})

    struct_trend = det.get('struct_15m', {}).get('trend', 'NEUTRAL')
    sweep_res = det.get('sweep_15m', 'NONE')

    if d.get('is_pending_limit', False):
        lines = [
            f"⏳ **BingX Institutional SMC v49.8 (Limit Order Mode)**",
            f"💎 العملة: `{sym}-USDT`",
            f"📈 القرار: `{text_dir}` (تحويل لأمر معلق)",
            f"🏆 Grade: `{grade}` | ⭐ Score: `{score}/100`",
            f"📊 Structure: `{struct_trend}`",
            f"🎯 Entry Zone (Limit): `{d.get('entry_zone')}`",
            f"🛑 SL: `{d.get('stop_loss')}` 📊 Risk: `{d.get('sl_pct')}%`",
            f"💵 Position Size: `${smart_round(d.get('position_size_usd', 0))}`",
            f"📝 ملاحظة الحماية:\n`{d.get('reason')}`"
        ]
        return '\n'.join(lines)

    lines = [
        f"🤖 **BingX Institutional SMC v49.8 (Dynamic RR & Entry)**",
        f"💎 العملة: `{sym}-USDT`",
        f"📈 القرار:",
        f"{emo} `{text_dir}`",
        f"🏆 Grade: `{grade}`",
        f"⭐ Score: `{score}/100`",
        f"🛡️ Status: `{conf}`",
        f"📊 Structure: `{struct_trend}`",
        f"📌 OB: `{d.get('order_block')}`",
        f"💧 Sweep: `{sweep_res}`",
        f"💰 Price: `{d.get('price')}`",
        f"🎯 Entry: `{d.get('entry_min')} - {d.get('entry_max')}`",
        f"🛑 SL: `{d.get('stop_loss')}` 📊 Risk: `{d.get('sl_pct')}%`",
        f"💵 Position Size (1% Risk): `${smart_round(d.get('position_size_usd', 0))}`",
        f"🎯 TP1 (1.5R): `{d.get('tp1')}`",
        f"🎯 TP2 (2.5R): `{d.get('tp2')}`",
        f"🎯 TP3 (4.0R): `{d.get('tp3')}`",
        f"📝 Reason:\n`{d.get('reason')}`"
    ]
        
    return '\n'.join(lines)
