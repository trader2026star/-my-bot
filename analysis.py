# ==============================================================================
# analysis.py - BingX Futures AI Scanner v28.9 [ULTRA EDITION]
# ==============================================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX Futures AI Scanner v28.9'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 45
PRICE_CACHE_SECONDS = 3
TICKER_CACHE_SECONDS = 5
MIN_REQUEST_INTERVAL = 0.45

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
    s = str(s).strip().upper().replace(' ', '')
    return s if s.endswith(('USDT', 'USDC')) else s + 'USDT'


def bingx_symbol(s):
    s = normalize_symbol(s)
    return s[:-4] + '-' + s[-4:]


def _rows(d):
    if not isinstance(d, dict): return []
    x = d.get('data')
    if isinstance(x, list): return x
    if isinstance(x, dict): return [x]
    return []


def bingx_get(path, params=None, timeout=12):
    global _RATE_LIMIT_UNTIL, _LAST_REQUEST_TIME
    with _RATE_LOCK:
        if time.time() < _RATE_LIMIT_UNTIL:
            return None
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0: time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()
    try:
        r = SESSION.get(BINGX_URL + path, params=params, timeout=timeout)
        if r.status_code != 200:
            logger.warning(f"BingX HTTP {r.status_code} | {path}")
            return None
        d = r.json()
        if not isinstance(d, dict): return None
        code = d.get('code')
        if code in (109429, 109400):
            with _RATE_LOCK: _RATE_LIMIT_UNTIL = time.time() + 60
            logger.warning('BingX rate limit reached. Backing off.')
        if code not in (0, None):
            logger.warning(f"BingX API error code: {code}")
        return d
    except Exception as e:
        logger.warning(f"BingX request failed: {e}")
        return None


def _crypto_usdt_symbol(s):
    s = str(s).upper().replace('-', '')
    if not s.endswith('USDT'): return False
    base = s[:-4]
    blocked = ('SP500', 'NASDAQ', 'DJI', 'US30', 'GOLD', 'OIL')
    return not base.endswith('USD') and not base in blocked


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and (time.time() - _SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS):
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/ticker')
    out = []
    for x in _rows(d):
        if isinstance(x, dict):
            s = str(x.get('symbol', '')).replace('-', '').upper()
            if _crypto_usdt_symbol(s):
                out.append(s)
    if out:
        _SYMBOL_CACHE = set(out)
        _SYMBOL_CACHE_TIME = time.time()
    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    sy = get_futures_symbols()
    return normalize_symbol(s) in sy


def _price_value(x):
    if not isinstance(x, dict): return None
    for k in ('price', 'lastPrice', 'last', 'close'):
        try:
            v = float(x.get(k))
            if v > 0: return v
        except: pass
    return None


def _ticker_rows(force=False):
    global _TICKER_CACHE, _TICKER_CACHE_TIME
    now = time.time()
    if not force and _TICKER_CACHE and (now - _TICKER_CACHE_TIME < TICKER_CACHE_SECONDS):
        return _TICKER_CACHE
    d = bingx_get('/openApi/swap/v2/quote/ticker')
    res = _rows(d)
    if res:
        _TICKER_CACHE = res
        _TICKER_CACHE_TIME = now
    return res if res else []


def _parse(rows):
    out = []
    for x in rows:
        try:
            if isinstance(x, dict):
                t = x.get('time', x.get('timestamp', 0))
                o, h, l, c_val, v = x.get('open'), x.get('high'), x.get('low'), x.get('close'), x.get('volume')
            elif isinstance(x, list) and len(x) >= 6:
                t, o, h, l, c_val, v = x[0], x[1], x[2], x[3], x[4], x[5]
            else: continue
            if None in (o, h, l, c_val): continue
            out.append([int(t), float(o), float(h), float(l), float(c_val), float(v if v is not None else 0)])
        except Exception: pass
    try: out.sort(key=lambda z: z[0])
    except Exception: pass
    seen = set()
    clean = []
    for x in out:
        if tuple(x) in seen: continue
        seen.add(tuple(x))
        clean.append(x)
    return clean


def get_bingx_klines(s, interval='1h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and (now - c[0] < KLINE_CACHE_SECONDS):
        return c[1]
    params = {'symbol': bingx_symbol(s), 'interval': interval, 'limit': limit}
    best = []
    for ep in ('/openApi/swap/v2/quote/klines', '/openApi/swap/v1/quote/klines'):
        r = _parse(_rows(bingx_get(ep, params=params)))
        if len(r) > len(best):
            best = r
        if len(best) >= 30:
            _KLINE_CACHE[key] = (now, best)
            return best
    if best:
        _KLINE_CACHE[key] = (now, best)
        return best
    return None


def get_current_price(s, force=False):
    s = normalize_symbol(s)
    now = time.time()
    c = _PRICE_CACHE.get(s)
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS:
        return c[1]
    for x in _ticker_rows(force):
        sym = str(x.get('symbol', '')).replace('-', '').upper()
        if sym == s or sym == s.replace('USDT', ''):
            p = _price_value(x)
            if p and p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
    for ep in ('/openApi/swap/v2/quote/ticker', '/openApi/swap/v1/quote/ticker'):
        for x in _rows(bingx_get(ep, {'symbol': bingx_symbol(s)})):
            p = _price_value(x)
            if p and p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
    k = get_bingx_klines(s, '1m', 5) or get_bingx_klines(s, '1h', 5)
    if k and k[-1][4] > 0:
        _PRICE_CACHE[s] = (now, k[-1][4])
        return k[-1][4]
    return None


def calculate_rsi(k, period=14):
    if len(k) < period + 1: return 50.0
    c = [x[4] for x in k]
    g = [max(c[i] - c[i-1], 0) for i in range(1, len(c))]
    l = [max(c[i-1] - c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else round(100.0 - (100.0 / (1 + ag / al)), 2)


def calculate_atr(k, n=14):
    if len(k) < n + 1: return None
    tr = []
    for i in range(1, len(k)):
        h, l, prev_c = k[i][2], k[i][3], k[i-1][4]
        tr.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    a = sum(tr[:n]) / n
    for x in tr[n:]: a = (a * (n - 1) + x) / n
    return a


def calculate_supertrend(k, period=10, multiplier=3):
    if len(k) < period + 1:
        return None, 'NEUTRAL'
    atr_val = calculate_atr(k, period)
    if not atr_val:
        return None, 'NEUTRAL'
    hl2 = [(x[2] + x[3]) / 2 for x in k]
    basic_upperband = [hl2[i] + (multiplier * atr_val) for i in range(len(k))]
    basic_lowerband = [hl2[i] - (multiplier * atr_val) for i in range(len(k))]
    current_close = k[-1][4]
    lower_val = basic_lowerband[-1]
    trend = 'BULLISH' if current_close > lower_val else 'BEARISH'
    return lower_val if trend == 'BULLISH' else upper_val, trend


def smart_round(v):
    if v is None: return None
    try: v = float(v)
    except Exception: return 0
    if v >= 1000: return round(v, 2)
    if v >= 100: return round(v, 3)
    if v >= 1: return round(v, 4)
    if v >= 0.1: return round(v, 5)
    if v >= 0.01: return round(v, 6)
    return round(v, 8)


def check_btc_trend():
    try:
        btc_k = get_bingx_klines('BTCUSDT', '5m', 10)
        if btc_k and len(btc_k) >= 5:
            if btc_k[-1][4] < btc_k[-5][4] * 0.993:
                return 'BEARISH_PANIC'
            if btc_k[-1][4] > btc_k[-5][4] * 1.007:
                return 'BULLISH_PUMP'
    except Exception: pass
    return 'STABLE'


def calculate_smart_trade_plan(direction, price, atr):
    raw_atr = atr or (price * 0.015)
    sl_dist = min(max(raw_atr * 0.9, price * 0.01), price * 0.05)
    if direction == 'LONG':
        entry = price
        sl = entry - sl_dist
        tp1 = entry + (sl_dist * 1.5)
        tp2 = entry + (sl_dist * 2.3)
        tp3 = entry + (sl_dist * 3.5)
        emin, emax = entry * 0.9985, entry * 1.0015
    elif direction == 'SHORT':
        entry = price
        sl = entry + sl_dist
        tp1 = entry - (sl_dist * 1.5)
        tp2 = entry - (sl_dist * 2.3)
        tp3 = entry - (sl_dist * 3.5)
        emin, emax = entry * 0.999, entry * 1.001
    else:
        emin = emax = entry = sl = tp1 = tp2 = tp3 = price

    risk = abs(entry - sl)
    reward = abs(tp1 - entry)
    rr_ratio = round(reward / risk, 2) if risk != 0 else 0
    rr_text = f"1:{rr_ratio}"

    return {
        'entry_min': smart_round(emin),
        'entry_max': smart_round(emax),
        'entry_price': smart_round(entry),
        'sl': smart_round(sl),
        'tp1': smart_round(tp1),
        'tp2': smart_round(tp2),
        'tp3': smart_round(tp3),
        'rr_ratio': rr_text
    }


def _get_blocked_signal(symbol, price, reason):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED',
        'score': 10, 'entry_score': 10,
        'state': f'BLOCKED - {reason}', 'price': smart_round(p),
        'volume_ratio': 1.0, 'volume_trend': 'NEUTRAL',
        'liquidity_score': 0, 'bottom_detected': False,
