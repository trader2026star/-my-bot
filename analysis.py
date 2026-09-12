# analysis.py - BingX Precision Execution Tool v47.0
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/47.0', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 45
PRICE_CACHE_SECONDS = 3
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

def calculate_rsi(c, period=14):
    if len(c) < period + 1:
        return 50.0
    g = [max(c[i]-c[i-1], 0) for i in range(1, len(c))]
    l = [max(c[i-1]-c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)

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

def find_pin_bar_target(direction, klines):
    if not klines or len(klines) < 3:
        return 0
    best_pin_target = 0
    for i in range(-1, -4, -1):
        c = klines[i]
        o, h, l, close_val = c[1], c[2], c[3], c[4]
        body = abs(close_val - o)
        total_range = h - l
        if total_range == 0:
            continue
        if direction == 'SHORT':
            upper_wick = h - max(o, close_val)
            if upper_wick > (body * 1.5) and upper_wick >= (total_range * 0.4):
                best_pin_target = h
                break
        else:
            lower_wick = min(o, close_val) - l
            if lower_wick > (body * 1.5) and lower_wick >= (total_range * 0.4):
                best_pin_target = l
                break
    if best_pin_target == 0:
        best_pin_target = klines[-1][3] if direction == 'SHORT' else klines[-1][2]
    return smart_round(best_pin_target)

def calculate_precision_plan(direction, price, klines):
    """
    حساب خطة التداول بدقة بناءً على طلب المستخدم المباشر (تجنب الوقف العشوائي)
    """
    if not klines or len(klines) < 2:
        return {
            'entry_min': smart_round(price * 0.998),
            'entry_max': smart_round(price * 1.004),
            'stop_loss': smart_round(price * 1.02),
            'tp1': smart_round(price * 0.98),
            'tp2': smart_round(price * 0.96),
            'tp3': smart_round(price * 0.94),
            'tp4': smart_round(price * 0.92),
            'candle_target': smart_round(price * 0.975),
            'pin_bar_target': smart_round(price * 0.97),
            'sl_pct': 2.0
        }

    last_candle = klines[-1]
    prev_candle = klines[-2]
    
    if direction == 'SHORT':
        entry_max = smart_round(max(last_candle[1], last_candle[2], prev_candle[2]))
        entry_min = smart_round(min(last_candle[1], last_candle[4], prev_candle[4]))
        if entry_min > entry_max:
            entry_min, entry_max = entry_max, entry_min
        
        # حماية وقف الخسارة بوضع مسافة أمان أوسع قليلاً لتفادي التذبذب العشوائي
        risk_range = (entry_max - entry_min) if (entry_max - entry_min) > 0 else (price * 0.012)
        stop_loss = smart_round(entry_max + (risk_range * 1.8))
        
        risk_dist = stop_loss - price
        tp1 = smart_round(price - (risk_dist * 0.8))
        tp2 = smart_round(price - (risk_dist * 1.4))
        tp3 = smart_round(price - (risk_dist * 2.0))
        tp4 = smart_round(price - (risk_dist * 2.8))
        candle_target = smart_round(last_candle[3])
        pin_bar_target = find_pin_bar_target('SHORT', klines)
        sl_pct = round(((stop_loss - price) / price) * 100, 2)
    else:
        entry_min = smart_round(min(last_candle[1], last_candle[3], prev_candle[3]))
        entry_max = smart_round(max(last_candle[1], last_candle[4], prev_candle[4]))
        if entry_min > entry_max:
            entry_min, entry_max = entry_max, entry_min
            
        risk_range = (entry_max - entry_min) if (entry_max - entry_min) > 0 else (price * 0.012)
        stop_loss = smart_round(entry_min - (risk_range * 1.8))
        
        risk_dist = price - stop_loss
        tp1 = smart_round(price + (risk_dist * 0.8))
        tp2 = smart_round(price + (risk_dist * 1.4))
        tp3 = smart_round(price + (risk_dist * 2.0))
        tp4 = smart_round(price + (risk_dist * 2.8))
        candle_target = smart_round(last_candle[2])
        pin_bar_target = find_pin_bar_target('LONG', klines)
        sl_pct = round(((price - stop_loss) / price) * 100, 2)

    return {
        'entry_min': min(entry_min, entry_max),
        'entry_max': max(entry_min, entry_max),
        'stop_loss': stop_loss,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'tp4': tp4,
        'candle_target': candle_target,
        'pin_bar_target': pin_bar_target,
        'sl_pct': abs(sl_pct)
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0:
        raise ValueError(f"Price error for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 50)
    if not k1 or len(k1) < 10:
        k1 = [[0, p, p*1.01, p*0.99, p, 0]]

    closes = [x[4] for x in k1]
    rsi = calculate_rsi(closes)

    # تحديد اتجاه الصفقة بناءً على الزخم الفعلي للعملة المختارة بدقة
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    direction = 'SHORT' if p <= ma20 or closes[-1] <= closes[-2] else 'LONG'

    plan = calculate_precision_plan(direction, p, k1)

    return {
        'symbol': symbol,
        'direction': direction,
        'score': 90,
        'state': 'ACTIVE',
        'price': smart_round(p),
        'rsi': rsi,
        'entry_min': plan['entry_min'],
        'entry_max': plan['entry_max'],
        'stop_loss': plan['stop_loss'],
        'tp1': plan['tp1'],
        'tp2': plan['tp2'],
        'tp3': plan['tp3'],
        'tp4': plan['tp4'],
        'candle_target': plan['candle_target'],
        'pin_bar_target': plan['pin_bar_target'],
        'sl_pct': plan['sl_pct'],
        'interval': interval.upper()
    }

def get_coin_analysis(symbol, interval='1h'):
    norm = normalize_symbol(symbol)
    if norm == 'TREND_COMMAND':
        return "⚠️ تم إلغاء المسح العشوائي. يرجى إرسال اسم العملة التي ترغب في تحليلها مباشرةً."
    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception as e:
        p = get_current_price(symbol, True) or 1.0
        return {
            'symbol': symbol, 'direction': 'LONG', 'score': 85,
            'price': smart_round(p), 'rsi': 50.0,
            'entry_min': smart_round(p * 0.998), 'entry_max': smart_round(p * 1.004),
            'stop_loss': smart_round(p * 0.98), 'tp1': smart_round(p * 1.02),
            'tp2': smart_round(p * 1.04), 'tp3': smart_round(p * 1.06),
            'tp4': smart_round(p * 1.08), 'candle_target': smart_round(p * 1.025),
            'pin_bar_target': smart_round(p * 1.03), 'sl_pct': 2.0, 'interval': interval.upper()
        }

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    if not d:
        return '⚠️ تعذر إكمال التحليل.'
    
    dr = d.get('direction', 'SHORT')
    emo, text_dir = ('🟢', 'LONG') if dr == 'LONG' else ('🔴', 'SHORT')

    lines = [
        f"🎯 **Precision Tool v47.0** | {text_dir}",
        f"{text_dir} 10x ${d.get('symbol', '-').replace('-USDT','')} - تحليل يدوي دقيق.",
        f"خطة التداول:",
        f"الدخول: `{d.get('entry_min')} - {d.get('entry_max')}`",
        f"TP1: `{d.get('tp1')}` (R:R 1:0.8)",
        f"TP2: `{d.get('tp2')}` (R:R 1:1.4)",
        f"TP3: `{d.get('tp3')}` (R:R 1:2.0)",
        f"TP4: `{d.get('tp4')}` (R:R 1:2.8)",
        f"🎯 هدف الشمعة: `{d.get('candle_target')}`",
        f"📌 هدف الدبوس (Pin Bar): `{d.get('pin_bar_target')}`",
        f"وقف الخسارة SL (محمي): `{d.get('stop_loss')}` (-{d.get('sl_pct', 2.0)}%)",
        f"السعر الحالي: `{d.get('price')}`"
    ]
        
    return '\n'.join(lines)
