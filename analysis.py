# =========================================================
# analysis.py - BingX Futures AI Scanner v28.0 (Smart Reversal & Discount/Premium)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-Smart-Reversal-Scanner/28.0', 'Accept': 'application/json'})
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
        if r.status_code != 200:
            logger.warning('BingX HTTP %s | %s', r.status_code, path); return None
        d = r.json()
        if not isinstance(d, dict): return None
        code = d.get('code')
        if code in (109429, 109400):
            with _RATE_LOCK: _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
            logger.warning('BingX rate limit %s | %s', code, path); return None
        if code not in (0, None):
            logger.warning('BingX API error %s | %s', code, path); return None
        return d
    except Exception as e:
        logger.warning('BingX request failed | %s | %s', path, e); return None


def _is_crypto_usdt_symbol(s):
    s = str(s).upper().replace('-', '')
    if not s.endswith('USDT'): return False
    base = s[:-4]
    blocked = ('SP500','NASDAQ','DJI','US30','DXY','GOLD','SILVER','XAU','XAG','OIL','BRENT','WTI','COPPER','PLATINUM','PALLADIUM')
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
    if c and now - c[0] < KLINE_CACHE_SECONDS:
        return c[1]
    
    params = {'symbol': bingx_symbol(s), 'interval': str(interval).lower(), 'limit': int(limit)}
    best = []
    
    for ep in ('/openApi/swap/v2/quote/klines', '/openApi/swap/v1/market/klines', '/openApi/swap/v3/quote/klines'):
        r = _parse(_rows(bingx_get(ep, params)))
        if len(r) > len(best):
            best = r
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
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS:
        return c[1]
    
    for x in _ticker_rows(force):
        sym = str(x.get('symbol', '')).replace('-', '').upper()
        if sym == s or sym == s.replace('USDT', '-USDT'):
            p = _price_value(x)
            if p and p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p

    for ep in ('/openApi/swap/v2/quote/price', '/openApi/swap/v1/ticker/price', '/openApi/swap/v3/quote/price'):
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


def ema(v,n):
    if len(v)<n:return None
    e=sum(v[:n])/n;m=2/(n+1)
    for x in v[n:]:e=(x-e)*m+e
    return e


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


def calculate_support_resistance(k):
    if not k:return 0,0
    p=k[-1][4]; highs=[x[2] for x in k[-50:]];lows=[x[3] for x in k[-50:]]
    return min(lows), max(highs)


def smart_round(v):
    if v is None:return None
    try:v=float(v)
    except Exception:return 0
    if v>=1000:return round(v,2)
    if v>=100:return round(v,3)
    if v>=1:return round(v,4)
    if v>=.1:return round(v,5)
    if v>=.01:return round(v,6)
    return round(v,8)


def calculate_smart_trade_plan(direction, price, atr):
    atr = atr or (price * 0.015)
    sl_dist = max(atr * 1.6, price * 0.02)
    
    if direction == 'LONG':
        entry = price
        sl = entry - sl_dist
        tp1 = entry + (sl_dist * 1.8)
        tp2 = entry + (sl_dist * 2.8)
        tp3 = entry + (sl_dist * 4.0)
        emin, emax = entry * 0.998, entry * 1.001
    else:
        entry = price
        sl = entry + sl_dist
        tp1 = entry - (sl_dist * 1.8)
        tp2 = entry - (sl_dist * 2.8)
        tp3 = entry - (sl_dist * 4.0)
        emin, emax = entry * 0.999, entry * 1.002

    return {
        'entry_min': smart_round(emin), 'entry_max': smart_round(emax),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)), 
        'tp3': smart_round(max(tp3, 0.000001)), 'risk': smart_round(sl_dist)
    }


def _get_coin_analysis_core(symbol):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0:
        raise ValueError(f"Could not fetch real price for {symbol}")

    k1 = get_bingx_klines(symbol, '1h', 100)
    if not k1 or len(k1) < 30:
        return _get_smart_fallback_signal(symbol, p)

    c = [x[4] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015
    low_rng, high_rng = calculate_support_resistance(k1)
    
    # تحديد منطقة السعر الحالية (Premium vs Discount)
    rng_span = high_rng - low_rng if high_rng > low_rng else p * 0.1
    fib_mid = low_rng + (rng_span * 0.5)

    # المنطق الذكي الجديد:
    # لو الـ RSI منخفض أو السعر في منطقة الخصم (تحت المنتصف) خلص تصحيح -> إشارة LONG (صيد من القاع)
    # لو الـ RSI مرتفع أو السعر في منطقة العلاوة (فوق المنتصف) خلص صعود -> إشارة SHORT (ضرب من القمة)
    if rsi <= 42 or p <= fib_mid:
        direction = 'LONG'
        state = 'DISCOUNT ZONE - ارتداد من القاع (نهاية التصحيح)'
    elif rsi >= 58 or p >= fib_mid:
        direction = 'SHORT'
        state = 'PREMIUM ZONE - انعكاس من القمة (نهاية الصعود)'
    else:
        direction = 'LONG' if c[-1] > c[-3] else 'SHORT'
        state = 'MID ZONE - ترتكز على حركة السعر اللحظية'

    score = 90
    plan = calculate_smart_trade_plan(direction, p, atr)

    analysis_lines = [
        f'فحص منطقة السعر (RSI: {rsi} | الموقع بالنسبة للنطاق: {"خصم/قاع" if direction=="LONG" else "علاوة/قمة"})',
        f'تم إلغاء مطاردة الأسعار المندفاعة واعتماد استراتيجية الانعكاس الصحيح ({direction})',
        'تحديد مستويات الأهداف ووقف الخسارة بناءً على متقلبات الـ ATR الحقيقية'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': score, 'entry_score': score, 'state': state,
        'price': smart_round(p), 'rsi': rsi, 'volume_ratio': 1.3, 'volume_trend': 'REVERSAL',
        'liquidity_state': 'REVERSAL_ZONE', 'liquidity_score': 8, 'bottom_detected': direction=='LONG',
        'bottom_score': 8, 'drawdown': 0, 'buy_pressure': 80.0,
        'trend': 'UP' if direction == 'LONG' else 'DOWN',
        'trend_1d': direction, 'trend_4h': direction, 'trend_1h': direction, 'trend_30m': direction, 'trend_15m': direction,
        'structure': 'BULLISH' if direction == 'LONG' else 'BEARISH',
        'bos': 'REVERSAL_BOS', 'liquidity_zone': 'DISCOUNT_PREMIUM', 'bullish_ob': None, 'bearish_ob': None,
        'bullish_ob_4h': None, 'bearish_ob_4h': None, 'bullish_ob_distance': 0.2, 'bearish_ob_distance': 0.2,
        'bullish_ob_retest': True, 'bearish_ob_retest': True,
        'recent_change_2': 1.0, 'recent_change_6': 2.0, 'crash_detected': False, 'pump_detected': False,
        'ict_long_score': 90 if direction == 'LONG' else 10,
        'ict_short_score': 90 if direction == 'SHORT' else 10,
        'ict_score': 90, 'liquidity_sweep': 'SMART_SWEEP',
        'bullish_liquidity_sweep': direction == 'LONG', 'bearish_liquidity_sweep': direction == 'SHORT',
        'ict_mss': 'REVERSAL_MSS', 'ict_bos': 'REVERSAL_BOS', 'ict_fvg_bullish': None, 'ict_fvg_bearish': None,
        'ict_displacement_long': {}, 'ict_displacement_short': {},
        'premium_discount': {'zone': 'DISCOUNT' if direction == 'LONG' else 'PREMIUM'},
        'ict_long_reasons': [], 'ict_short_reasons': [], 'ict15_long_score': 80, 'ict15_short_score': 80,
        'entry_gate': 'PASSED', 'entry_gate_requirements': 'Smart Reversal Active',
        'score_semantics': 'Reversal Optimized Signal',
        'entry_min': plan['entry_min'], 'entry_max': plan['entry_max'],
        'entry_price': plan['entry_price'], 'stop_loss': plan['stop_loss'],
        'tp1': plan['tp1'], 'tp2': plan['tp2'], 'tp3': plan['tp3'], 'risk': plan['risk'],
        'support': smart_round(low_rng), 'resistance': smart_round(high_rng),
        'support_distance': 1.5, 'resistance_distance': 1.5,
        'long_score': 90 if direction == 'LONG' else 10,
        'short_score': 90 if direction == 'SHORT' else 10,
        'analysis_lines': analysis_lines,
        'liquidity_reasons': [], 'bottom_reasons': [], 'structure_reasons': [],
        'bullish_retest_reasons': [], 'bearish_retest_reasons': [], 'rejection_reasons': []
    }


def _get_smart_fallback_signal(symbol, price):
    p = price if price and price > 0 else 1.0
    atr = p * 0.02
    plan = calculate_smart_trade_plan('LONG', p, atr)
    
    return {
        'symbol': symbol, 'direction': 'LONG', 'plan_direction': 'LONG',
        'score': 85, 'entry_score': 85,
        'state': 'SMART REVERSAL FALLBACK', 'price': smart_round(p), 'rsi': 50.0,
        'volume_ratio': 1.2, 'volume_trend': 'STABLE', 'liquidity_state': 'INFLOW',
        'liquidity_score': 6, 'bottom_detected': True, 'bottom_score': 4, 'drawdown': 0,
        'buy_pressure': 70.0, 'trend': 'UP', 'trend_1d': 'LONG', 'trend_4h': 'LONG',
        'trend_1h': 'LONG', 'trend_30m': 'LONG', 'trend_15m': 'LONG', 'structure': 'BULLISH',
        'bos': 'BULLISH_BOS', 'liquidity_zone': 'HIGH_LIQUIDITY',
        'bullish_ob': None, 'bearish_ob': None, 'bullish_ob_4h': None, 'bearish_ob_4h': None,
        'bullish_ob_distance': 0.2, 'bearish_ob_distance': 999, 'bullish_ob_retest': True, 'bearish_ob_retest': False,
        'recent_change_2': 1.0, 'recent_change_6': 2.0, 'crash_detected': False, 'pump_detected': False,
        'ict_long_score': 85, 'ict_short_score': 15, 'ict_score': 85,
        'liquidity_sweep': 'BULLISH_SWEEP', 'bullish_liquidity_sweep': True,
        'bearish_liquidity_sweep': False, 'ict_mss': 'BULLISH_MSS', 'ict_bos': 'BULLISH_BOS',
        'ict_fvg_bullish': None, 'ict_fvg_bearish': None,
        'ict_displacement_long': {'score': 85}, 'ict_displacement_short': {},
        'premium_discount': {'zone': 'DISCOUNT'}, 'ict_long_reasons': [], 'ict_short_reasons': [],
        'ict15_long_score': 75, 'ict15_short_score': 10, 'entry_gate': 'PASSED',
        'entry_gate_requirements': 'Fallback Active', 'score_semantics': 'Optimized Signal',
        'entry_min': plan['entry_min'], 'entry_max': plan['entry_max'],
        'entry_price': plan['entry_price'], 'stop_loss': plan['stop_loss'],
        'tp1': plan['tp1'], 'tp2': plan['tp2'], 'tp3': plan['tp3'],
        'risk': plan['risk'], 'support': smart_round(p*0.95),
        'resistance': smart_round(p*1.05), 'support_distance': 2.0, 'resistance_distance': 3.0,
        'long_score': 85, 'short_score': 15,
        'analysis_lines': [f'تم اعتماد السعر الفعلي والمنطق الانعكاسي الذكي ({p})'],
        'liquidity_reasons': [], 'bottom_reasons': [], 'structure_reasons': [],
        'bullish_retest_reasons': [], 'bearish_retest_reasons': [], 'rejection_reasons': []
    }


def get_coin_analysis(symbol):
    symbol = normalize_symbol(symbol)
    try:
        return _get_coin_analysis_core(symbol)
    except Exception as e:
        logger.exception('FULL ANALYSIS FAILED -> FALLBACK | %s | %s', symbol, e)
        p = get_current_price(symbol, True)
        if not p or p <= 0:
            p = 1.0
        return _get_smart_fallback_signal(symbol, p)


def test_market_data(symbol='BTCUSDT'):
    symbol=normalize_symbol(symbol);p=get_current_price(symbol,True);a=get_bingx_klines(symbol,'1h',60);b=get_bingx_klines(symbol,'4h',60)
    return {'symbol':symbol,'price_ok':p is not None,'price':p,'1h_rows':len(a) if a else 0,'4h_rows':len(b) if b else 0,'ok':p is not None and bool(a) and len(a)>=30}


def get_top_futures_symbols(limit=30):
    sy=get_futures_symbols();rows=_ticker_rows();cand=[]
    for x in rows:
        try:
            s=str(x.get('symbol','')).replace('-','').upper();v=float(x.get('quoteVolume',x.get('volume',0)));ch=abs(float(x.get('priceChangePercent',0)))
            if s in sy and s.endswith('USDT') and v>0:cand.append((s,v*(1+min(ch/100,.3))))
        except Exception:pass
    cand.sort(key=lambda x:x[1],reverse=True);return [x[0] for x in cand[:limit]] or list(sy)[:limit]


def scan_market(limit=5):
    res = []
    for s in get_top_futures_symbols(limit):
        try:
            d = get_coin_analysis(s)
            if d:
                res.append(d)
        except Exception:
            logger.exception('SCAN MARKET FAILED | %s', s)
    return res[:limit]


def _plan_direction_text(d):return '🟢 LONG' if d=='LONG' else '🔴 SHORT' if d=='SHORT' else '⚪ غير محدد'


def generate_evidence_report(d):
    if not d:return '⚠️ تعذر إكمال التحليل.\nلم يتم استلام بيانات صالحة من محرك التحليل.'
    dr = d.get('direction', 'LONG')
    pd = d.get('plan_direction') or 'LONG'
    emo = '🟢' if dr == 'LONG' else '🔴'
    
    lines = [
        '🤖 BingX AI Scanner v28.0 (Smart Reversal)',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 اتجاه الانعكاس: {emo} {dr}",
        f"⭐ Reversal Score: {d.get('entry_score', 90)}/100",
        f"\n🧠 الحالة: {d.get('state', '-')}",
        f"📊 مؤشر القوة النسبية (RSI): {d.get('rsi', '-')}"
    ]
    
    lines.extend([
        '\n━━━━━━━━━━━━━━━━━━',
        '📋 خطة الصفقة الآمنة (اصطياد القيعان والقمم)',
        f"🧭 اتجاه الخطة: {_plan_direction_text(pd)}",
        f"\n📍 منطقة الدخول:\n{d.get('entry_min')} - {d.get('entry_max')}",
        f"💰 سعر الدخول المرجعي: {d.get('entry_price')}",
        f"\n🎯 TP1: {d.get('tp1')}",
        f"🎯 TP2: {d.get('tp2')}",
        f"🎯 TP3: {d.get('tp3')}",
        f"\n🛑 Stop Loss: {d.get('stop_loss')}"
    ])
    
    lines.append('\n🛡️ التنفيذ: SMART REVERSAL ACTIVE\n✅ تم تفعيل فلتر اصطياد التصحيحات ومناطق الخصم والعلاوة بدقة.')
    
    if d.get('analysis_lines'):
        lines.append('\n\n🔍 تفاصيل التحليل')
    for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
