# =========================================================
# analysis.py - BingX Futures SMC Pro Scanner v31.0
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-SMC-Pro/31.0', 'Accept': 'application/json'})
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


def smart_round(v):
    if v is None:return 0
    try:v=float(v)
    except Exception:return 0
    if v>=1000:return round(v,2)
    if v>=100:return round(v,3)
    if v>=1:return round(v,4)
    if v>=.1:return round(v,5)
    return round(v,8)


def analyze_smc_structure(klines):
    """
    منطق تحليل هيكل السوق (Smart Money Concepts - SMC)
    البحث عن مناطق الأوردر بلوك (Order Blocks) وحالة كسر الهيكل (BOS / CHoCH)
    """
    if not klines or len(klines) < 20:
        return 'NEUTRAL', 0, 0, 0

    highs = [x[2] for x in klines]
    lows = [x[3] for x in klines]
    closes = [x[4] for x in klines]
    opens = [x[1] for x in klines]

    recent_high = max(highs[-15:-1])
    recent_low = min(lows[-15:-1])
    current_close = closes[-1]

    # اكتشاف الـ Order Block الصاعد (آخر شمعة هابطة قبل الانفجار الصاعد)
    bullish_ob = lows[-2] if closes[-1] > closes[-2] and closes[-2] < opens[-2] else recent_low
    # اكتشاف الـ Order Block الهابط (آخر شمعة صاعدة قبل الانفجار الهابط)
    bearish_ob = highs[-2] if closes[-1] < closes[-2] and closes[-2] > opens[-2] else recent_high

    # فحص كسر الهيكل (Break of Structure)
    if current_close > recent_high:
        return 'BULLISH', bullish_ob, recent_high, 95  # هيكل صاعد قوي جداً
    elif current_close < recent_low:
        return 'BEARISH', bearish_ob, recent_low, 95   # هيكل هابط قوي جداً
    else:
        # تحديد الاتجاه العام بالاستعانة بالمتوسطات أو الشموع الأخيرة
        if current_close > closes[-5]:
            return 'BULLISH', bullish_ob, recent_high, 75
        else:
            return 'BEARISH', bearish_ob, recent_low, 75


def calculate_smc_trade_plan(direction, price, atr, ob_level):
    raw_atr = atr or (price * 0.015)
    # تظبيط وقف الخسارة خلف منطقة الأوردر بلوك أو بناءً على مسافة أمان عالية ضد الـ Fakeout
    if direction == 'LONG':
        entry = price
        sl = min(ob_level - (raw_atr * 0.5), entry - (raw_atr * 1.5))
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 1.8)
        tp2 = entry + (risk_dist * 2.8)
        tp3 = entry + (risk_dist * 4.2)
    elif direction == 'SHORT':
        entry = price
        sl = max(ob_level + (raw_atr * 0.5), entry + (raw_atr * 1.5))
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 1.8)
        tp2 = entry - (risk_dist * 2.8)
        tp3 = entry - (risk_dist * 4.2)
    else:
        entry = sl = tp1 = tp2 = tp3 = risk_dist = 0

    rr_ratio = round(abs(tp1 - entry) / risk_dist, 2) if risk_dist > 0 else 0.0
    return {
        'entry_min': smart_round(entry * 0.998), 'entry_max': smart_round(entry * 1.002),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)), 'risk': smart_round(risk_dist), 'rr_ratio': rr_ratio
    }


def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: raise ValueError(f"Price error for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: return _get_blocked_signal(symbol, p, "بيانات غير كافية للسوق", interval)

    c = [x[4] for x in k1]
    v = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    # فحص السيولة وحجم التداول (يجب أن يكون قوي لتجنب الخدع)
    current_volume = v[-1]
    avg_volume = sum(v[-20:]) / 20 if len(v) >= 20 else sum(v) / len(v)
    volume_ok = current_volume >= (avg_volume * 1.2)

    # تحليل الهيكل باستخدام SMC
    smc_trend, ob_level, key_level, smc_score = analyze_smc_structure(k1)

    # فحص الفريم الأكبر 4H للتوافق التام
    k4h = get_bingx_klines(symbol, '4h', 50)
    trend_4h, _, _, _ = analyze_smc_structure(k4h) if k4h and len(k4h) >= 20 else ('NEUTRAL', 0, 0, 50)

    # شروط القرار النهائي بفلتر قوي
    if smc_trend == 'BULLISH' and rsi < 75:
        direction = 'LONG'
        state = 'SMC CONFIRMED LONG - ارتداد من منطقة سيولة (Order Block)'
        score = smc_score
    elif smc_trend == 'BEARISH' and rsi > 25:
        direction = 'SHORT'
        state = 'SMC CONFIRMED SHORT - هبوط من منطقة عرض (Order Block)'
        score = smc_score
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - تذبذب السعر داخل منطقة ريلود (No Clear SMC Structure)'
        score = 25

    # خصم نقاط لو الفريم الكبير معاكس
    if direction == 'LONG' and trend_4h == 'BEARISH':
        score -= 20
        state = 'WARNING - صراع مع اتجاه فريم 4 ساعات'
    elif direction == 'SHORT' and trend_4h == 'BULLISH':
        score -= 20
        state = 'WARNING - صراع مع اتجاه فريم 4 ساعات'

    if not volume_ok and direction != 'BLOCKED':
        score -= 15

    # حظر الصفقات لو النتيجة ضعيفة لضمان عدم ضرب الستوب
    if score < 75:
        direction = 'BLOCKED'
        state = 'BLOCKED - السكور ضعيف، حماية المحفظة مفعلة'

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100

    plan = calculate_smc_trade_plan(direction if direction != 'BLOCKED' else 'LONG', p, atr, ob_level)

    analysis_lines = [
        f'⏱️ الإطار الزمني: {interval.upper()}',
        f'هيكل السوق (SMC): {"🟢 صاعد (BOS)" if smc_trend=="BULLISH" else "🔴 هابط (BOS)"}',
        f'اتجاه فريم 4H: {"🟢 صاعد" if trend_4h=="BULLISH" else "🔴 هابط"}',
        f'منطقة الأوردر بلوك: {smart_round(ob_level)}',
        f'حجم السيولة: {"✅ قوي ومناسب" if volume_ok else "⚠️ ضعيف"}',
        f'رسوم التمويل: {funding_pct:.4f}%',
        f'مؤشر RSI: {rsi}'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': max(10, score), 'entry_score': max(10, score), 'state': state,
        'price': smart_round(p), 'rsi': rsi, 'volume_ratio': round(current_volume / (avg_volume or 1), 2),
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
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (SMC Buy Setup)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (SMC Sell Setup)'
    else: emo, text_dir = '🛑', 'BLOCKED (تجنب التذبذب)'
    
    lines = [
        '🤖 BingX SMC Pro Scanner v31.0',
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
            '📋 خطة صانع السوق الاحترافية (SMC)',
            f"\n📍 منطقة الدخول:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول الفعلي: {d.get('entry_price')}",
            f"\n🎯 TP1: {d.get('tp1')}",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"\n🛑 Stop Loss (أمان الهيكل): {d.get('stop_loss')}",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر الدخول تماماً لحماية الرأس المال من التلاعب.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
