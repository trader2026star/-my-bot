# =========================================================
# analysis.py - BingX Futures AI Scanner v30.0 (Auto-Scanner & High-Accuracy Pro)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-SmartMoney-Scanner/30.0', 'Accept': 'application/json'})
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
    s = str(s).strip().upper().replace(' ', '').replace('-', '').replace('_', '').replace('/', '')
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
        if time.time() < _RATE_LIMIT_UNTIL: return None
    with _REQUEST_LOCK:
        wait = MIN_REQUEST_INTERVAL - (time.time() - _LAST_REQUEST_TIME)
        if wait > 0: time.sleep(wait)
        _LAST_REQUEST_TIME = time.time()
    try:
        r = SESSION.get(BINGX_URL + path, params=params or {}, timeout=timeout)
        if r.status_code != 200: return None
        d = r.json()
        if not isinstance(d, dict): return None
        code = d.get('code')
        if code in (109429, 109400):
            with _RATE_LOCK: _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
            return None
        if code not in (0, None): return None
        return d
    except Exception:
        return None


def _is_crypto_usdt_symbol(s):
    s = str(s).upper().replace('-', '')
    if not s.endswith('USDT'): return False
    base = s[:-4]
    blocked = ('SP500','NASDAQ','DJI','US30','DXY','GOLD','SILVER','XAU','XAG','OIL','BRENT','WTI')
    return not base.endswith('USD') and not any(x in base for x in blocked)


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts'); out=set()
    for x in _rows(d):
        if isinstance(x, dict):
            s=str(x.get('symbol','')).replace('-','').upper(); status=x.get('status')
            if _is_crypto_usdt_symbol(s) and status in (1,'1',None): out.add(s)
    if out: _SYMBOL_CACHE, _SYMBOL_CACHE_TIME = out, time.time()
    return set(_SYMBOL_CACHE)


def symbol_exists(s):
    sy=get_futures_symbols(); return not sy or normalize_symbol(s) in sy


def _price_value(x):
    if not isinstance(x,dict): return None
    for k in ('price','lastPrice','last','close','markPrice'):
        try:
            v=float(x.get(k));
            if v>0:return v
        except Exception: pass
    return None


def _ticker_rows(force=False):
    global _TICKER_CACHE,_TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME<TICKER_CACHE_SECONDS:return _TICKER_CACHE
    x=_rows(bingx_get('/openApi/swap/v2/quote/ticker'))
    if x:_TICKER_CACHE,_TICKER_CACHE_TIME=x,time.time()
    return x


def get_funding_rate(symbol):
    s = bingx_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': s})
    rows = _rows(d)
    if rows:
        try:
            return float(rows[0].get('lastFundingRate', rows[0].get('fundingRate', 0)))
        except Exception:
            pass
    return 0.0


def _parse(rows):
    out=[]
    for x in rows:
        try:
            if isinstance(x,dict):
                t=x.get('time',x.get('timestamp',x.get('openTime',0))); o=x.get('open'); h=x.get('high'); l=x.get('low'); c=x.get('close'); v=x.get('volume',x.get('vol',0))
            elif isinstance(x,list) and len(x)>=6:t,o,h,l,c,v=x[:6]
            else:continue
            if None in (o,h,l,c):continue
            out.append([t,float(o),float(h),float(l),float(c),float(v or 0)])
        except Exception:pass
    try:out.sort(key=lambda z:z[0])
    except Exception:pass
    seen=set(); clean=[]
    for x in out:
        if x[0] in seen:continue
        seen.add(x[0]);clean.append(x)
    return clean


def get_bingx_klines(s, interval='1h', limit=200):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS: return c[1]
    
    params = {'symbol': bingx_symbol(s), 'interval': str(interval).lower(), 'limit': int(limit)}
    best = []
    for ep in ('/openApi/swap/v2/quote/klines', '/openApi/swap/v1/market/klines'):
        r = _parse(_rows(bingx_get(ep, params)))
        if len(r) > len(best): best = r
        if len(r) >= 30:
            _KLINE_CACHE[key] = (now, r)
            return r
    if best:
        _KLINE_CACHE[key] = (now, best)
        return best
    return None


def get_current_price(s, force=False):
    s = normalize_symbol(s)
    now = time.time()
    c = _PRICE_CACHE.get(s)
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS: return c[1]
    
    for x in _ticker_rows(force):
        sym = str(x.get('symbol', '')).replace('-', '').upper()
        if sym == s or sym == s.replace('USDT', '-USDT'):
            p = _price_value(x)
            if p and p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
    k = get_bingx_klines(s, '1m', 5)
    if k and k[-1][4] > 0:
        _PRICE_CACHE[s] = (now, k[-1][4])
        return k[-1][4]
    return None


def calculate_rsi(c,period=14):
    if len(c)<period+1:return 50.0
    g=[max(c[i]-c[i-1],0) for i in range(1,len(c))];l=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag=sum(g[:period])/period;al=sum(l[:period])/period
    for i in range(period,len(g)):
        ag=(ag*(period-1)+g[i])/period;al=(al*(period-1)+l[i])/period
    return 100.0 if al==0 else round(100-100/(1+ag/al),2)


def calculate_atr(k,n=14):
    if len(k)<n+1:return None
    tr=[max(x[2]-x[3],abs(x[2]-k[i-1][4]),abs(x[3]-k[i-1][4])) for i,x in enumerate(k[1:],1)]
    a=sum(tr[:n])/n
    for x in tr[n:]:a=(a*(n-1)+x)/n
    return a


def calculate_supertrend(k, period=10, multiplier=3):
    if len(k) < period + 1: return None, 'NEUTRAL'
    atr_val = calculate_atr(k, period)
    if not atr_val: return None, 'NEUTRAL'
    hl2 = [(x[2] + x[3]) / 2 for x in k]
    basic_upperband = [hl2[i] + (multiplier * atr_val) for i in range(len(k))]
    basic_lowerband = [hl2[i] - (multiplier * atr_val) for i in range(len(k))]
    current_close = k[-1][4]
    trend = 'BULLISH' if current_close > basic_lowerband[-1] else 'BEARISH'
    return basic_lowerband[-1] if trend == 'BULLISH' else basic_upperband[-1], trend


def smart_round(v):
    if v is None:return 0
    try:v=float(v)
    except Exception:return 0
    if v>=1000:return round(v,2)
    if v>=100:return round(v,3)
    if v>=1:return round(v,4)
    if v>=.1:return round(v,5)
    return round(v,8)


def calculate_smart_trade_plan(direction, price, atr):
    raw_atr = atr or (price * 0.015)
    sl_dist = min(max(raw_atr * 0.9, price * 0.015), price * 0.035)
    if direction == 'LONG':
        entry = price
        sl = entry - sl_dist
        tp1 = entry + (sl_dist * 1.5)
        tp2 = entry + (sl_dist * 2.3)
        tp3 = entry + (sl_dist * 3.5)
    elif direction == 'SHORT':
        entry = price
        sl = entry + sl_dist
        tp1 = entry - (sl_dist * 1.5)
        tp2 = entry - (sl_dist * 2.3)
        tp3 = entry - (sl_dist * 3.5)
    else:
        entry = sl = tp1 = tp2 = tp3 = sl_dist = 0

    rr_ratio = round(abs(tp1 - entry) / sl_dist, 2) if sl_dist > 0 else 0.0
    return {
        'entry_min': smart_round(entry * 0.9985), 'entry_max': smart_round(entry * 1.001),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)), 'risk': smart_round(sl_dist), 'rr_ratio': rr_ratio
    }


def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: raise ValueError(f"Price error for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: return _get_blocked_signal(symbol, p, "بيانات غير كافية", interval)

    c = [x[4] for x in k1]
    v = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    current_volume = v[-1]
    avg_volume_24 = sum(v[-25:-1]) / 24 if len(v) >= 25 else sum(v) / len(v)
    volume_ok = current_volume >= (avg_volume_24 * 1.5)

    double_candle_bullish = (c[-1] > c[-2]) and (c[-2] > c[-3])
    double_candle_bearish = (c[-1] < c[-2]) and (c[-2] < c[-3])

    k4h = get_bingx_klines(symbol, '4h', 50)
    _, st_trend_4h = calculate_supertrend(k4h) if k4h and len(k4h) >= 15 else (None, 'BULLISH')
    _, st_trend = calculate_supertrend(k1)

    is_long = double_candle_bullish and st_trend == 'BULLISH' and rsi < 72
    is_short = double_candle_bearish and st_trend == 'BEARISH' and rsi > 28

    if is_long and not is_short:
        direction = 'LONG'
        state = 'CONFIRMED LONG - تأكيد شمعتين وإتجاه صاعد'
        score = 92
    elif is_short and not is_long:
        direction = 'SHORT'
        state = 'CONFIRMED SHORT - تأكيد شمعتين وإتجاه هابط'
        score = 90
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - الشروط غير مكتملة أو تذبذب'
        score = 20

    if direction == 'LONG' and st_trend_4h == 'BEARISH':
        score = 85
        state = 'WARNING - إطار 4H يعاكس الاتجاه'

    if not volume_ok and direction != 'BLOCKED':
        score = max(10, score - 20)

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    if abs(funding_pct) > 0.05:
        score = max(10, score - 15)

    plan = calculate_smart_trade_plan(direction if direction != 'BLOCKED' else 'LONG', p, atr)

    analysis_lines = [
        f'⏱️ الإطار الزمني للتحليل: {interval.upper()}',
        f'مؤشر SuperTrend ({interval}): {"🟢 صاعد" if st_trend=="BULLISH" else "🔴 هابط"}',
        f'اتجاه إطار 4H: {"🟢 صاعد" if st_trend_4h=="BULLISH" else "🔴 هابط"}',
        f'حجم التداول: {"✅ ممتاز" if volume_ok else "⚠️ ضعف بالحجم"}',
        f'رسوم التمويل: {funding_pct:.4f}%',
        f'مؤشر RSI: {rsi}'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': score, 'entry_score': score, 'state': state,
        'price': smart_round(p), 'rsi': rsi, 'volume_ratio': round(current_volume / (avg_volume_24 or 1), 2),
        'entry_min': plan['entry_min'] if direction!='BLOCKED' else 0, 
        'entry_max': plan['entry_max'] if direction!='BLOCKED' else 0,
        'entry_price': plan['entry_price'] if direction!='BLOCKED' else smart_round(p), 
        'stop_loss': plan['stop_loss'] if direction!='BLOCKED' else 0,
        'tp1': plan['tp1'] if direction!='BLOCKED' else 0, 'tp2': plan['tp2'] if direction!='BLOCKED' else 0, 
        'tp3': plan['tp3'] if direction!='BLOCKED' else 0, 'risk': plan['risk'], 'rr_ratio': plan['rr_ratio'], 
        'funding_rate': funding_pct, 'analysis_lines': analysis_lines, 'interval': interval.upper()
    }


def _get_blocked_signal(symbol, price, reason, interval='1h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED', 'plan_direction': 'BLOCKED',
        'score': 10, 'entry_score': 10, 'state': f'BLOCKED - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'analysis_lines': [f'🛑 {reason}'], 'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='1h'):
    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception:
        return _get_blocked_signal(symbol, 1.0, "خطأ بالبيانات", interval)


def get_top_futures_symbols(limit=25):
    sy=get_futures_symbols();rows=_ticker_rows();cand=[]
    for x in rows:
        try:
            s=str(x.get('symbol','')).replace('-','').upper();v=float(x.get('quoteVolume',0))
            if s in sy and s.endswith('USDT') and v>0:cand.append((s,v))
        except Exception:pass
    cand.sort(key=lambda x:x[1],reverse=True);return [x[0] for x in cand[:limit]]


def generate_evidence_report(d):
    if not d: return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'BLOCKED')
    inv = d.get('interval', '1H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (Confirmed Buy)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (Confirmed Sell)'
    else: emo, text_dir = '🛑', 'BLOCKED (تذبذب)'
    
    lines = [
        '🤖 BingX AI Scanner v30.0 (Pro)',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"⏱️ الإطار الزمني: {inv}",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 القرار النهائي: {emo} {text_dir}",
        f"⭐ Score: {d.get('score', 0)}/100",
        f"\n🧠 الحالة: {d.get('state', '-')}",
        f"📊 RSI: {d.get('rsi', '-')}"
    ]

    if dr != 'BLOCKED':
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '📋 خطة صانع السوق (SMC Plan)',
            f"\n📍 منطقة الدخول:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول: {d.get('entry_price')}",
            f"\n🎯 TP1: {d.get('tp1')}",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')}",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر التداول على هذه العملة مؤقتاً لحماية رأس المال.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
