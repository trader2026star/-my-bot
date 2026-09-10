# =========================================================
# analysis.py - BingX Institutional SMC & Risk Suite v41.1
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/41.1', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 45
PRICE_CACHE_SECONDS = 3
TICKER_CACHE_SECONDS = 5
NEWS_CACHE_SECONDS = 300  
MIN_REQUEST_INTERVAL = 0.3
_RATE_LIMIT_UNTIL = 0.0
_LAST_REQUEST_TIME = 0.0
_SYMBOL_CACHE = set()
_SYMBOL_CACHE_TIME = 0.0
_KLINE_CACHE = {}
_PRICE_CACHE = {}
_TICKER_CACHE = None
_TICKER_CACHE_TIME = 0.0
_NEWS_CACHE = None
_NEWS_CACHE_TIME = 0.0
_RATE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()


def normalize_symbol(s):
    s = str(s).strip().upper().replace(' ', '').replace('-', '').replace('_', '').replace('/', '')
    if not s.endswith('USDT'):
        s = s + '-USDT' if '-' not in s else s
    if s.endswith('USDT') and '-' not in s:
        s = s[:-4] + '-USDT'
    return s


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
            if r.status_code == 429:
                with _RATE_LOCK: _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + 60)
            return None
        d = r.json()
        if isinstance(d, dict) and d.get('code', 0) == 0:
            return d.get('data')
        return d.get('data') if isinstance(d, dict) and 'data' in d else d
    except Exception:
        return None


def get_economic_news_status():
    global _NEWS_CACHE, _NEWS_CACHE_TIME
    now = time.time()
    if _NEWS_CACHE is not None and now - _NEWS_CACHE_TIME < NEWS_CACHE_SECONDS:
        return _NEWS_CACHE
    try:
        res = requests.get('https://nfs.faireconomy.media/ff_calendar_thisweek.json', timeout=5)
        if res.status_code == 200:
            events = res.json()
            current_time = time.time()
            high_impact_near = False
            event_title = ""
            for ev in events:
                if ev.get('impact') == 'High':
                    date_str = ev.get('date')
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        ev_timestamp = dt.timestamp()
                        if -7200 <= (ev_timestamp - current_time) <= 7200:
                            high_impact_near = True
                            event_title = ev.get('title', 'High Impact Economic Event')
                            break
                    except Exception:
                        pass
            _NEWS_CACHE = (high_impact_near, event_title)
            _NEWS_CACHE_TIME = now
            return _NEWS_CACHE
    except Exception:
        pass
    return (False, "")


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
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
    sy = get_futures_symbols()
    return not sy or normalize_symbol(s) in sy or s in sy


def _ticker_rows(force=False):
    global _TICKER_CACHE, _TICKER_CACHE_TIME
    if not force and _TICKER_CACHE is not None and time.time()-_TICKER_CACHE_TIME < TICKER_CACHE_SECONDS:
        return _TICKER_CACHE
    x = bingx_get('/openApi/swap/v2/quote/ticker')
    if isinstance(x, list):
        _TICKER_CACHE, _TICKER_CACHE_TIME = x, time.time()
        return x
    elif isinstance(x, dict) and 'tickers' in x:
        _TICKER_CACHE, _TICKER_CACHE_TIME = x['tickers'], time.time()
        return x['tickers']
    return []


def get_top_futures_symbols(limit=25):
    rows = _ticker_rows()
    cand = []
    for x in rows:
        try:
            if isinstance(x, dict):
                s = str(x.get('symbol', '')).upper()
                v = float(x.get('volume', x.get('quoteVolume', 0)))
                if s and v > 0: cand.append((s, v))
        except Exception: pass
    cand.sort(key=lambda x: x[1], reverse=True)
    out = []
    for x in cand[:limit]:
        sy = normalize_symbol(x[0])
        if sy not in out: out.append(sy)
    return out


def get_funding_rate(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': symbol})
    if isinstance(d, dict):
        try: return float(d.get('fundingRate', 0))
        except Exception: pass
    return 0.0


def get_open_interest(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/openInterest', {'symbol': symbol})
    if isinstance(d, dict):
        try: return float(d.get('openInterest', 0))
        except Exception: pass
    elif isinstance(d, list) and len(d) > 0:
        try: return float(d[0].get('openInterest', 0))
        except Exception: pass
    return 0.0


def _parse(rows):
    out = []
    if not isinstance(rows, list): return out
    for x in rows:
        try:
            if isinstance(x, dict):
                t = int(x.get('time', x.get('openTime', 0)))
                o = float(x.get('open', 0))
                h = float(x.get('high', 0))
                l = float(x.get('low', 0))
                c = float(x.get('close', 0))
                v = float(x.get('volume', 0))
                if t > 0 and c > 0: out.append([t, o, h, l, c, v])
            elif isinstance(x, list) and len(x) >= 6:
                t, o, h, l, c, v = x[:6]
                out.append([int(t), float(o), float(h), float(l), float(c), float(v or 0)])
        except Exception: pass
    try: out.sort(key=lambda z: z[0])
    except Exception: pass
    seen = set(); clean = []
    for x in out:
        if x[0] in seen: continue
        seen.add(x[0]); clean.append(x)
    return clean


def get_bingx_klines(s, interval='1h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS: return c[1]
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
    if not force and c and now - c[0] < PRICE_CACHE_SECONDS: return c[1]
    d = bingx_get('/openApi/swap/v2/quote/price', {'symbol': s})
    if isinstance(d, dict) and 'price' in d:
        try:
            p = float(d.get('price', 0))
            if p > 0:
                _PRICE_CACHE[s] = (now, p)
                return p
        except Exception: pass
    rows = _ticker_rows()
    for x in rows:
        if isinstance(x, dict) and str(x.get('symbol', '')).upper() in [s, s.replace('-', '')]:
            try:
                p = float(x.get('lastPrice', x.get('price', 0)))
                if p > 0:
                    _PRICE_CACHE[s] = (now, p)
                    return p
            except Exception: pass
    k = get_bingx_klines(s, '1m', 5)
    if k and len(k) > 0 and k[-1][4] > 0:
        _PRICE_CACHE[s] = (now, k[-1][4])
        return k[-1][4]
    return None


def calculate_rsi(c, period=14):
    if len(c) < period + 1: return 50.0
    g = [max(c[i]-c[i-1], 0) for i in range(1, len(c))]
    l = [max(c[i-1]-c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)


def calculate_atr(k, n=14):
    if len(k) < n + 1: return None
    tr = [max(x[2]-x[3], abs(x[2]-k[i-1][4]), abs(x[3]-k[i-1][4])) for i, x in enumerate(k[1:], 1)]
    a = sum(tr[:n]) / n
    for x in tr[n:]: a = (a * (n - 1) + x) / n
    return a


def smart_round(v):
    if v is None: return 0
    try: v = float(v)
    except Exception: return 0
    if v >= 1000: return round(v, 2)
    if v >= 100: return round(v, 3)
    if v >= 1: return round(v, 4)
    if v >= 0.1: return round(v, 5)
    return round(v, 8)


def determine_strict_trend(klines_4h, klines_1h):
    if not klines_4h or len(klines_4h) < 15:
        trend_4h = 'NEUTRAL'
    else:
        closes_4h = [x[4] for x in klines_4h]
        ma_4h = sum(closes_4h[-10:]) / 10
        trend_4h = 'BULLISH' if closes_4h[-1] > ma_4h else 'BEARISH'

    if not klines_1h or len(klines_1h) < 15:
        return trend_4h, 'NEUTRAL'
    
    closes_1h = [x[4] for x in klines_1h]
    ma_1h = sum(closes_1h[-10:]) / 10
    trend_1h = 'BULLISH' if closes_1h[-1] > ma_1h else 'BEARISH'

    return trend_4h, trend_1h


def calculate_institutional_trade_plan(direction, price, klines, atr, ob_level, portfolio_size=1000.0, risk_pct=1.0):
    raw_atr = atr or (price * 0.015)
    candle_ranges = [abs(x[4] - x[1]) for x in klines[-15:]] if klines and len(klines) >= 15 else [raw_atr]
    avg_candle_range = sum(candle_ranges) / len(candle_ranges) if candle_ranges else raw_atr

    if direction == 'LONG':
        entry = price
        sl = min(ob_level - (raw_atr * 0.5), entry - (raw_atr * 1.5))
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 2.0)
        tp2 = entry + (risk_dist * 3.5)
        tp3 = entry + (risk_dist * 5.0)
        full_range_target = entry + (avg_candle_range * 2.2)
    elif direction == 'SHORT':
        entry = price
        sl = max(ob_level + (raw_atr * 0.5), entry + (raw_atr * 1.5))
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 2.0)
        tp2 = entry - (risk_dist * 3.5)
        tp3 = entry - (risk_dist * 5.0)
        full_range_target = entry - (avg_candle_range * 2.2)
    else:
        entry = sl = tp1 = tp2 = tp3 = full_range_target = risk_dist = 0

    rr_ratio = round(abs(tp1 - entry) / risk_dist, 2) if risk_dist > 0 else 0.0
    sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry > 0 and sl > 0 else 0.0
    allowed_risk_usd = portfolio_size * (risk_pct / 100.0)
    position_size_usd = round(allowed_risk_usd / (sl_pct / 100.0), 2) if sl_pct > 0 else 0.0
    breakeven_trigger = tp1

    return {
        'entry_min': smart_round(entry * 0.998), 'entry_max': smart_round(entry * 1.002),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)), 'full_range_target': smart_round(max(full_range_target, 0.000001)),
        'risk': smart_round(risk_dist), 'rr_ratio': rr_ratio, 'sl_pct': sl_pct, 
        'position_size_usd': position_size_usd, 'breakeven_trigger': smart_round(breakeven_trigger)
    }


def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: raise ValueError(f"Price error for {symbol}")

    has_news, news_title = get_economic_news_status()
    if has_news:
        return _get_blocked_signal(symbol, p, f"تم الحظر مؤقتاً بسبب قرب صدور خبر اقتصادي قوي: ({news_title})", interval)

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: return _get_blocked_signal(symbol, p, "بيانات السوق غير كافية", interval)

    k4h = get_bingx_klines(symbol, '4h', 50)
    trend_4h, trend_1h = determine_strict_trend(k4h, k1)

    c = [x[4] for x in k1]
    vols = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    avg_vol = sum(vols[-15:]) / 15 if len(vols) >= 15 else 1.0
    last_vol = vols[-1]
    is_volume_confirmed = last_vol >= (avg_vol * 0.7)

    highs = [x[2] for x in k1]
    lows = [x[3] for x in k1]
    closes = [x[4] for x in k1]
    opens = [x[1] for x in k1]

    bullish_ob = lows[-3]
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] < opens[i]:
            bullish_ob = lows[i]
            break

    bearish_ob = highs[-3]
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] > opens[i]:
            bearish_ob = highs[i]
            break

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    open_interest = get_open_interest(symbol)

    if trend_4h == 'BULLISH' and trend_1h == 'BULLISH':
        direction = 'LONG'
        state = 'INSTITUTIONAL LONG - توافق تجمعي صاعد قاطع'
        score = 88
    elif trend_4h == 'BEARISH' and trend_1h == 'BEARISH':
        direction = 'SHORT'
        state = 'INSTITUTIONAL SHORT - توافق تجمعي هابط قاطع'
        score = 88
    elif trend_4h == 'BULLISH' and trend_1h == 'BEARISH':
        if rsi < 40:
            direction = 'LONG'
            state = 'LONG (تصحيح صحي داخل ترند صاعد 4H)'
            score = 75
        else:
            direction = 'BLOCKED'
            state = 'BLOCKED - تداخل بين 4H الصاعد و 1H الهابط'
            score = 45
    elif trend_4h == 'BEARISH' and trend_1h == 'BULLISH':
        direction = 'SHORT'
        state = 'INSTITUTIONAL SHORT - قمع ارتداد 1H الوهمي ومطابقة ترند 4H'
        score = 82
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - اتجاه مذبذب وغير مستقر'
        score = 40

    if not is_volume_confirmed and direction != 'BLOCKED':
        score -= 10
        state = f'{state} | تنبيه: فوليوم التداول ضعيف نسبياً'

    if score < 50:
        direction = 'BLOCKED'
        state = 'BLOCKED - السوق لا يلبي المعايير المؤسسية الآمنة'

    plan = calculate_institutional_trade_plan(direction if direction != 'BLOCKED' else 'SHORT', p, k1, atr, bearish_ob if direction=='SHORT' else bullish_ob, portfolio_size=1000.0, risk_pct=1.0)

    analysis_lines = [
        f'الإطار الزمني: {interval.upper()}',
        f'اتجاه الفريم الكبير (4H): {"🟢 صاعد" if trend_4h=="BULLISH" else "🔴 هابط"}',
        f'اتجاه فريم الساعة (1H): {"🟢 صاعد" if trend_1h=="BULLISH" else "🔴 هابط"}',
        f'فلتر الفوليوم المؤسسية: {"✅ مؤكد" if is_volume_confirmed else "⚠️ ضعيف"}',
        f'العقود المفتوحة (OI): {open_interest:,.2f}',
        f'معدل التمويل (Funding): {funding_pct:.4f}%',
        f'مؤشر القوة النسبية (RSI): {rsi}',
        f'المنطقة الفنية (OB): {smart_round(bearish_ob if direction=="SHORT" else bullish_ob)}'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': max(20, min(100, score)), 'entry_score': max(20, min(100, score)), 'state': state,
        'price': smart_round(p), 'rsi': rsi,
        'entry_min': plan['entry_min'] if direction!='BLOCKED' else 0, 
        'entry_max': plan['entry_max'] if direction!='BLOCKED' else 0,
        'entry_price': plan['entry_price'] if direction!='BLOCKED' else smart_round(p), 
        'stop_loss': plan['stop_loss'] if direction!='BLOCKED' else 0,
        'tp1': plan['tp1'] if direction!='BLOCKED' else 0, 'tp2': plan['tp2'] if direction!='BLOCKED' else 0, 
        'tp3': plan['tp3'] if direction!='BLOCKED' else 0, 'full_range_target': plan['full_range_target'] if direction!='BLOCKED' else 0,
        'risk': plan['risk'], 'rr_ratio': plan['rr_ratio'], 'sl_pct': plan['sl_pct'], 
        'position_size_usd': plan['position_size_usd'], 'breakeven_trigger': plan['breakeven_trigger'],
        'funding_rate': funding_pct, 'open_interest': open_interest, 'analysis_lines': analysis_lines, 'interval': interval.upper()
    }


def scan_for_emerging_trends(limit_symbols=30):
    top_syms = get_top_futures_symbols(limit=limit_symbols)
    emerging_trends = []

    for sym in top_syms:
        try:
            k1 = get_bingx_klines(sym, '1h', 40)
            k4h = get_bingx_klines(sym, '4h', 20)
            if not k1 or not k4h or len(k1) < 25 or len(k4h) < 10:
                continue

            trend_4h, trend_1h = determine_strict_trend(k4h, k1)
            
            if trend_4h == 'BULLISH' and trend_1h == 'BULLISH':
                c = [x[4] for x in k1]
                vols = [x[5] for x in k1]
                avg_vol = sum(vols[-15:]) / 15 if len(vols) >= 15 else 1.0
                
                if vols[-1] >= (avg_vol * 0.8) or vols[-2] >= (avg_vol * 0.8):
                    p = get_current_price(sym)
                    rsi = calculate_rsi(c)
                    emerging_trends.append({
                        'symbol': sym,
                        'price': smart_round(p),
                        'rsi': rsi,
                        'score': 88,
                        'type': 'BULLISH_TREND_START'
                    })
        except Exception:
            continue

    return emerging_trends


def generate_trend_scan_report():
    results = scan_for_emerging_trends(limit_symbols=35)
    if not results:
        return "🔍 ماسح الترندات (v41.1):\nلم يتم رصد عملات بدأت ترنداً صاعداً قوياً في هذه اللحظة بالذات. السوق هادئ، جرب البحث لاحقاً أو افحص عملة معينة."

    lines = [
        "🚀 تقرير ماسح الترندات المؤسسية (v41.1)",
        "العملات التي تبدأ تشكيل ترند صاعد حقيقي بفوليوم وتوافق فريمات:",
        "━━━━━━━━━━━━━━━━━━"
    ]

    for idx, item in enumerate(results[:10], 1):
        lines.append(
            f"{idx}. 💎 **{item['symbol']}**\n"
            f"   💰 السعر: `{item['price']}` | 📊 RSI: `{item['rsi']}` | ⭐ Score: `{item['score']}`\n"
            f"   🟢 الحالة: بداية ترند صاعد مؤسسي مؤكد\n"
        )

    lines.append("━━━━━━━━━━━━━━━━━━\nاكتب اسم أي عملة من القائمة لتفصيل خطتها الكاملة!")
    return '\n'.join(lines)


def _get_blocked_signal(symbol, price, reason, interval='1h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED', 'plan_direction': 'BLOCKED',
        'score': 10, 'entry_score': 10, 'state': f'BLOCKED - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'analysis_lines': [f'🛑 {reason}'], 'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='1h'):
    # التحقق مما إذا كان المدخل أمر مسح ترند وليس اسم عملة
    clean_sym = str(symbol).strip().lower()
    if clean_sym in ['ترند', 'trend', 'scan_trend']:
        return generate_trend_scan_report()

    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception as e:
        return _get_blocked_signal(symbol, 1.0, f"خطأ بالبيانات ({str(e)})", interval)


def generate_evidence_report(d):
    if isinstance(d, str):
        return d

    if not d: return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'BLOCKED')
    inv = d.get('interval', '1H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (مؤسسي مدعوم بالترند)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (مؤسسي مدعوم بالترند)'
    else: emo, text_dir = '🛑', 'BLOCKED (محمي من تقلبات السوق)'
    
    lines = [
        '🤖 BingX Institutional Suite v41.1',
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
            '📋 الخطة المؤسسية وإدارة المخاطر المتقدمة',
            f"\n📍 منطقة الدخول:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول الفعلي: {d.get('entry_price')}",
            f"\n🎯 TP1 (هدف التأمين): {d.get('tp1')} -> (عند الوصول له ارفع الوقف لـ Break-Even)",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"🚀 الهدف الكلي لمدى الشمعة (Full Range): {d.get('full_range_target')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')} (بعد بنسبة {d.get('sl_pct', 0)}%)",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}",
            f"🛡️ حجم الصفقة الآمن (محفظة 1000$ بمخاطرة 1%): ~{d.get('position_size_usd', 0)}$"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر التداول مؤقتاً لحماية رصيدك من أي فخاخ أو أخبار قوية.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
