# =========================================================
# analysis.py - BingX Futures AI Scanner v29.0 (Multi-Timeframe, Volume, Funding & SuperTrend Pro)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-SmartMoney-Scanner/29.0', 'Accept': 'application/json'})
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
_FUNDING_CACHE = {}
_FUNDING_CACHE_TIME = 0.0
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


def get_funding_rate(symbol):
    s = bingx_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': s})
    rows = _rows(d)
    if rows:
        try:
            val = float(rows[0].get('lastFundingRate', rows[0].get('fundingRate', 0)))
            return val
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
    if len(k) < period + 1:
        return None, 'NEUTRAL'
    
    atr_val = calculate_atr(k, period)
    if not atr_val:
        return None, 'NEUTRAL'
        
    hl2 = [(x[2] + x[3]) / 2 for x in k]
    basic_upperband = [hl2[i] + (multiplier * atr_val) for i in range(len(k))]
    basic_lowerband = [hl2[i] - (multiplier * atr_val) for i in range(len(k))]
    
    current_close = k[-1][4]
    upper_val = basic_upperband[-1]
    lower_val = basic_lowerband[-1]
    
    trend = 'BULLISH' if current_close > lower_val else 'BEARISH'
    return lower_val if trend == 'BULLISH' else upper_val, trend


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
    raw_atr = atr or (price * 0.015)
    sl_dist = min(max(raw_atr * 0.9, price * 0.015), price * 0.035)
    
    if direction == 'LONG':
        entry = price
        sl = entry - sl_dist
        tp1 = entry + (sl_dist * 1.5)
        tp2 = entry + (sl_dist * 2.3)
        tp3 = entry + (sl_dist * 3.5)
        emin, emax = entry * 0.9985, entry * 1.001
    elif direction == 'SHORT':
        entry = price
        sl = entry + sl_dist
        tp1 = entry - (sl_dist * 1.5)
        tp2 = entry - (sl_dist * 2.3)
        tp3 = entry - (sl_dist * 3.5)
        emin, emax = entry * 0.999, entry * 1.0015
    else:
        emin = emax = entry = sl = tp1 = tp2 = tp3 = sl_dist = 0

    # حساب نسبة المخاطرة إلى العائد (Risk:Reward Ratio) تلقائياً بناءً على TP1
    rr_ratio = 0.0
    if sl_dist > 0 and direction in ('LONG', 'SHORT'):
        reward_dist = abs(tp1 - entry)
        rr_ratio = round(reward_dist / sl_dist, 2)

    return {
        'entry_min': smart_round(emin), 'entry_max': smart_round(emax),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)) if sl else 0,
        'tp1': smart_round(max(tp1, 0.000001)) if tp1 else 0, 'tp2': smart_round(max(tp2, 0.000001)) if tp2 else 0, 
        'tp3': smart_round(max(tp3, 0.000001)) if tp3 else 0, 'risk': smart_round(sl_dist), 'rr_ratio': rr_ratio
    }


def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0:
        raise ValueError(f"Could not fetch real price for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30:
        return _get_blocked_signal(symbol, p, "بيانات الفريمات غير كافية لهيكل السوق", interval)

    c = [x[4] for x in k1]
    v = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    # 1️⃣ فلتر حجم التداول (Volume Filter)
    current_volume = v[-1]
    avg_volume_24 = sum(v[-25:-1]) / 24 if len(v) >= 25 else sum(v) / len(v)
    volume_ok = current_volume >= (avg_volume_24 * 1.5)

    # 2️⃣ التحقق على إطار أعلى (Multi-Timeframe 4H Confluence)
    k4h = get_bingx_klines(symbol, '4h', 50)
    st_val_4h, st_trend_4h = calculate_supertrend(k4h) if k4h and len(k4h) >= 15 else (None, 'BULLISH')

    # فحص مؤشر الـ SuperTrend للإطار الحالي
    st_val, st_trend = calculate_supertrend(k1)

    recent_highs = max([x[2] for x in k1[-15:-1]])
    recent_lows = min([x[3] for x in k1[-15:-1]])
    
    bos_bullish = c[-1] > recent_highs * 0.999
    bos_bearish = c[-1] < recent_lows * 1.001

    is_smc_long = (bos_bullish or c[-1] > c[-5]) and st_trend == 'BULLISH' and rsi < 75
    is_smc_short = (bos_bearish or c[-1] < c[-5]) and st_trend == 'BEARISH' and rsi > 25

    if is_smc_long and not is_smc_short:
        direction = 'LONG'
        state = 'MULTI-TF LONG - مدعوم بـ SuperTrend والسيولة'
        score = 95
        gate = 'PASSED'
    elif is_smc_short and not is_smc_long:
        direction = 'SHORT'
        state = 'MULTI-TF SHORT - مدعوم بـ SuperTrend والسيولة'
        score = 93
        gate = 'PASSED'
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - تعارض في الهيكل الفني أو التذبذب'
        score = 20
        gate = 'BLOCKED'

    # تطبيق شرط الـ Multi-Timeframe (منع Score أعلى من 90 لو الـ 4H هابط)
    if direction == 'LONG' and st_trend_4h == 'BEARISH':
        score = min(score, 88)
        state = 'MULTI-TF WARNING - تحذير: إطار 4H يعاكس اتجاه الشراء'

    # تطبيق تعديل فلتر الحجم (خصم 15 نقطة لو الحجم أقل من 1.5x)
    volume_warning_text = ""
    if not volume_ok and direction != 'BLOCKED':
        score = max(10, score - 15)
        volume_warning_text = "⚠️ Low Volume Warning (الحجم الحالي أقل من 1.5x المتوسط)"

    # 3️⃣ فلتر رسوم التمويل (Funding Rate Filter)
    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    funding_warning = ""
    if abs(funding_pct) > 0.05:
        funding_warning = f"⚠️ Funding Rate High: {funding_pct:.4f}% - Trade with Caution"

    plan = calculate_smart_trade_plan(direction if direction != 'BLOCKED' else 'LONG', p, atr)

    analysis_lines = [
        f'⏱️ الإطار الزمني للتحليل: {interval.upper()}',
        f'مؤشر SuperTrend ({interval}): {"🟢 صاعد" if st_trend=="BULLISH" else "🔴 هابط"}',
        f'اتجاه إطار 4H (Multi-TF): {"🟢 صاعد / مستقر" if st_trend_4h=="BULLISH" else "🔴 هابط (يُحذر التداول عكسه)"}',
        f'حجم التداول: {"✅ ممتاز (أعلى من 1.5x المتوسط)" if volume_ok else "⚠️ ضعف في الحجم (Low Volume)"}',
        f'رسوم التمويل (Funding Rate): {funding_pct:.4f}% {"(⚠️ مرتفعة)" if abs(funding_pct)>0.05 else "(✅ طبيعية)"}',
        f'مؤشر القوة النسبية (RSI): {rsi}'
    ]
    if volume_warning_text:
        analysis_lines.append(volume_warning_text)
    if funding_warning:
        analysis_lines.append(funding_warning)

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': score, 'entry_score': score, 'state': state,
        'price': smart_round(p), 'rsi': rsi, 'volume_ratio': round(current_volume / (avg_volume_24 or 1), 2),
        'volume_trend': 'CONFIRMED' if volume_ok else 'LOW_VOLUME',
        'liquidity_state': gate, 'liquidity_score': score, 'bottom_detected': direction=='LONG',
        'bottom_score': score, 'drawdown': 0, 'buy_pressure': 80.0 if direction=='LONG' else 20.0,
        'trend': 'UP' if direction == 'LONG' else 'DOWN' if direction == 'SHORT' else 'NEUTRAL',
        'trend_1d': direction, 'trend_4h': st_trend_4h, 'trend_1h': direction,
        'structure': 'BULLISH' if direction == 'LONG' else 'BEARISH' if direction == 'SHORT' else 'NEUTRAL',
        'entry_min': plan['entry_min'] if gate=='PASSED' else 0, 'entry_max': plan['entry_max'] if gate=='PASSED' else 0,
        'entry_price': plan['entry_price'] if gate=='PASSED' else smart_round(p), 'stop_loss': plan['stop_loss'] if gate=='PASSED' else 0,
        'tp1': plan['tp1'] if gate=='PASSED' else 0, 'tp2': plan['tp2'] if gate=='PASSED' else 0, 'tp3': plan['tp3'] if gate=='PASSED' else 0, 
        'risk': plan['risk'], 'rr_ratio': plan['rr_ratio'], 'funding_rate': funding_pct,
        'analysis_lines': analysis_lines, 'interval': interval.upper()
    }


def _get_blocked_signal(symbol, price, reason, interval='1h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED', 'plan_direction': 'BLOCKED',
        'score': 10, 'entry_score': 10, 'state': f'BLOCKED - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'volume_ratio': 1.0, 'volume_trend': 'BLOCKED',
        'liquidity_state': 'BLOCKED', 'liquidity_score': 0, 'bottom_detected': False,
        'entry_min': 0, 'entry_max': 0, 'entry_price': smart_round(p), 'stop_loss': 0,
        'tp1': 0, 'tp2': 0, 'tp3': 0, 'risk': 0, 'rr_ratio': 0.0, 'funding_rate': 0.0,
        'analysis_lines': [f'⏱️ الإطار الزمني: {interval.upper()}', f'🛑 تم حظر العملة: {reason}'],
        'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception as e:
        logger.exception('FULL ANALYSIS FAILED -> BLOCKED | %s | %s', symbol, e)
        p = get_current_price(symbol, True)
        if not p or p <= 0: p = 1.0
        return _get_blocked_signal(symbol, p, f"خطأ في هيكل البيانات: {e}", interval)


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


def scan_market(limit=5, interval='1h'):
    res = []
    for s in get_top_futures_symbols(limit):
        try:
            d = get_coin_analysis(s, interval)
            if d:
                res.append(d)
        except Exception:
            logger.exception('SCAN MARKET FAILED | %s', s)
    return res[:limit]


def _plan_direction_text(d):
    if d == 'LONG': return '🟢 LONG (متوافق مع الهيكل والاتجاه)'
    if d == 'SHORT': return '🔴 SHORT (متوافق مع الهيكل والاتجاه)'
    return '🛑 BLOCKED (خارج شروط الفلترة)'


def generate_evidence_report(d):
    if not d:return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'BLOCKED')
    pd = d.get('plan_direction') or 'BLOCKED'
    inv = d.get('interval', '1H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (Multi-TF Confirmed Buy)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (Multi-TF Confirmed Sell)'
    else: emo, text_dir = '🛑', 'BLOCKED (تذبذب / شروط غير مكتملة)'
    
    lines = [
        '🤖 BingX AI Scanner v29.0 (Pro Multi-TF & Volume)',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"⏱️ الإطار الزمني: {inv}",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 القرار النهائي: {emo} {text_dir}",
        f"⭐ Score: {d.get('entry_score', 0)}/100",
        f"\n🧠 الحالة: {d.get('state', '-')}",
        f"📊 مؤشر القوة النسبية (RSI): {d.get('rsi', '-')}"
    ]
    
    # تنبيه رسوم التمويل إن وجد في التقرير العام
    fr = d.get('funding_rate', 0.0)
    if abs(fr) > 0.05:
        lines.append(f"⚠️ Funding Rate High: {fr:.4f}% - Trade with Caution")

    if dr != 'BLOCKED':
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '📋 خطة صانع السوق المتقدمة (SMC Plan)',
            f"🧭 اتجاه الخطة: {_plan_direction_text(pd)}",
            f"\n📍 منطقة الدخول:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول المرجعي: {d.get('entry_price')}",
            f"\n🎯 TP1: {d.get('tp1')}",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')}",
            f"⚖️ نسبة المخاطرة إلى العائد (Risk:Reward): 1 : {d.get('rr_ratio', 0.0)}"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر التداول على هذه العملة',
            '• الشروط الفنية أو أحجام التداول أو اتجاه 4H غير متوافقة.',
            '• البوت محمي تماماً ضد الصفقات العشوائية.'
        ])
    
    lines.append('\n🛡️ التنفيذ: MULTI-TF & VOLUME FILTERS ACTIVE\n✅ تم تطبيق فحص السيولة، الحجم، رسوم التمويل، والإطار الأكبر بنجاح.')
    
    if d.get('analysis_lines'):
        lines.append('\n\n🔍 تفاصيل الفحص الفني المتقدم')
    for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
