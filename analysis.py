# =========================================================
# analysis.py - BingX Institutional SMC & Risk Suite v44.0
# (النسخة المتطورة: محرك فريم 4 ساعات + درع الوقف + العداد الزمني)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalShield/44.0', 'Accept': 'application/json'})
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
    s_clean = str(s).strip().lower()
    if s_clean in ['ترند', 'trend', 'scan_trend', 'trend_command']:
        return 'TREND_COMMAND'
        
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
    if normalize_symbol(s) == 'TREND_COMMAND': return True
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


def get_top_futures_symbols(limit=30):
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


def get_bingx_klines(s, interval='4h', limit=100):
    s = normalize_symbol(s)
    key = (s, str(interval).lower(), int(limit))
    now = time.time()
    c = _KLINE_CACHE.get(key)
    if c and now - c[0] < KLINE_CACHE_SECONDS: return c[1]
    mp = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d'}
    bi = mp.get(str(interval).lower(), '4h')
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
    k = get_bingx_klines(s, '4h', 5)
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


def analyze_macro_liquidity_sweep(klines):
    if len(klines) < 20:
        return 'NONE', 0.0, 0.0

    recent_lows = [x[3] for x in klines[-15:-2]]
    prev_lowest = min(recent_lows) if recent_lows else klines[-5][3]
    
    last_candle = klines[-1]
    prev_candle = klines[-2]
    
    is_swept_low = prev_candle[3] < prev_lowest and prev_candle[4] > prev_lowest
    is_bullish_choch = last_candle[4] > last_candle[1] and last_candle[4] > prev_candle[2]

    recent_highs = [x[2] for x in klines[-15:-2]]
    prev_highest = max(recent_highs) if recent_highs else klines[-5][2]
    is_swept_high = prev_candle[2] > prev_highest and prev_candle[4] < prev_highest
    is_bearish_choch = last_candle[4] < last_candle[1] and last_candle[4] < prev_candle[3]

    if is_swept_low or is_bullish_choch:
        return 'LONG', prev_lowest, prev_lowest
    elif is_swept_high or is_bearish_choch:
        return 'SHORT', prev_highest, prev_highest

    return 'NEUTRAL', prev_lowest, prev_highest


def calculate_macro_trade_plan(direction, price, klines, atr, structural_stop, portfolio_size=1000.0, risk_pct=1.0):
    raw_atr = atr or (price * 0.02)
    buffer_margin = raw_atr * 0.9  # مسافة أمان أوسع لفريم 4 ساعات لحماية الصفقة من التلاعب الطويل
    
    if direction == 'LONG':
        entry = price
        base_sl = structural_stop if (structural_stop > 0 and structural_stop < entry) else entry - (raw_atr * 1.5)
        sl = base_sl - buffer_margin
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 2.5)
        tp2 = entry + (risk_dist * 4.0)
        tp3 = entry + (risk_dist * 6.0)
        full_range_target = entry + (risk_dist * 5.0)
    else:
        entry = price
        base_sl = structural_stop if (structural_stop > 0 and structural_stop > entry) else entry + (raw_atr * 1.5)
        sl = base_sl + buffer_margin
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 2.5)
        tp2 = entry - (risk_dist * 4.0)
        tp3 = entry - (risk_dist * 6.0)
        full_range_target = entry - (risk_dist * 5.0)

    rr_ratio = round(abs(tp1 - entry) / risk_dist, 2) if risk_dist > 0 else 0.0
    sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry > 0 and sl > 0 else 0.0
    allowed_risk_usd = portfolio_size * (risk_pct / 100.0)
    position_size_usd = round(allowed_risk_usd / (sl_pct / 100.0), 2) if sl_pct > 0 else 0.0

    return {
        'entry_min': smart_round(entry * 0.997), 'entry_max': smart_round(entry * 1.003),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)), 'full_range_target': smart_round(max(full_range_target, 0.000001)),
        'risk': smart_round(risk_dist), 'rr_ratio': rr_ratio, 'sl_pct': sl_pct, 
        'position_size_usd': position_size_usd, 'breakeven_trigger': tp1
    }


def _get_coin_analysis_core(symbol, interval='4h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: raise ValueError(f"Price error for {symbol}")

    has_news, news_title = get_economic_news_status()
    if has_news:
        return _get_blocked_signal(symbol, p, f"تم الحظر مؤقتاً بسبب قرب صدور خبر اقتصادي قوي: ({news_title})", interval)

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: return _get_blocked_signal(symbol, p, "بيانات السوق غير كافية على فريم 4H", interval)

    c = [x[4] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.02

    sweep_dir, sweep_level, structural_sl = analyze_macro_liquidity_sweep(k1)

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    open_interest = get_open_interest(symbol)

    if sweep_dir == 'LONG':
        direction = 'LONG'
        state = '⚡ MACRO 4H SWEEP LONG - صيد سيولة فريم 4 ساعات مع درع الأمان وزدوج العداد الزمني'
        score = 96
    elif sweep_dir == 'SHORT':
        direction = 'SHORT'
        state = '⚡ MACRO 4H SWEEP SHORT - صيد سيولة علوية فريم 4 ساعات مع درع الأمان الزمني'
        score = 96
    else:
        ma_fast = sum(c[-10:]) / 10
        if c[-1] > ma_fast and rsi < 65:
            direction = 'LONG'
            state = '🟢 MACRO 4H TREND CONTINUATION LONG'
            score = 80
        else:
            direction = 'SHORT'
            state = '🔴 MACRO 4H TREND CONTINUATION SHORT'
            score = 80

    plan = calculate_macro_trade_plan(direction, p, k1, atr, structural_sl, portfolio_size=1000.0, risk_pct=1.0)

    analysis_lines = [
        f'📖 النظام المتقدم v44.0: تفعيل محرك فريم (4H) مع نظام الخروج الزمني بنهاية عمر الشمعة.',
        f'الإطار الزمني: {interval.upper()}',
        f'حالة سحب السيولة: {"🟢 مؤكد على فريم 4H مع مسافة أمان كبرى" if sweep_dir in ["LONG", "SHORT"] else "⚪ حركة ترند رئيسية على 4H"}',
        f'العقود المفتوحة (OI): {open_interest:,.2f}',
        f'معدل التمويل (Funding): {funding_pct:.4f}%',
        f'مؤشر القوة النسبية (RSI): {rsi}'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': max(20, min(100, score)), 'entry_score': max(20, min(100, score)), 'state': state,
        'price': smart_round(p), 'rsi': rsi,
        'entry_min': plan['entry_min'], 'entry_max': plan['entry_max'],
        'entry_price': plan['entry_price'], 'stop_loss': plan['stop_loss'],
        'tp1': plan['tp1'], 'tp2': plan['tp2'], 'tp3': plan['tp3'], 'full_range_target': plan['full_range_target'],
        'risk': plan['risk'], 'rr_ratio': plan['rr_ratio'], 'sl_pct': plan['sl_pct'], 
        'position_size_usd': plan['position_size_usd'], 'breakeven_trigger': plan['breakeven_trigger'],
        'funding_rate': funding_pct, 'open_interest': open_interest, 'analysis_lines': analysis_lines, 'interval': interval.upper()
    }


def scan_for_emerging_trends(limit_symbols=35):
    top_syms = get_top_futures_symbols(limit=limit_symbols)
    spark_signals = []

    for sym in top_syms:
        try:
            k1 = get_bingx_klines(sym, '4h', 25)
            if not k1 or len(k1) < 20: continue
            p = get_current_price(sym)
            sweep_dir, _, _ = analyze_macro_liquidity_sweep(k1)
            if sweep_dir in ['LONG', 'SHORT']:
                rsi = calculate_rsi([x[4] for x in k1])
                spark_signals.append({'symbol': sym, 'price': smart_round(p), 'rsi': rsi, 'score': 96, 'action': f'⚡ فرصة 4H كبرى ({sweep_dir})'})
        except Exception:
            continue
    return spark_signals


def generate_trend_scan_report():
    results = scan_for_emerging_trends(limit_symbols=40)
    if not results:
        return "🔍 ماسح فريم 4 ساعات (v44.0):\nلا توجد حالات سحب سيولة كبرى على فريم 4H حالياً."

    lines = [
        "🛡️ تقرير ماسح الفريمات الكبرى (v44.0)",
        "العملات التي شكلت إشارات هيكلية على فريم 4 ساعات:",
        "━━━━━━━━━━━━━━━━━━"
    ]
    for idx, item in enumerate(results[:10], 1):
        lines.append(f"{idx}. 💎 **{item['symbol']}**\n   💰 السعر: `{item['price']}` | 📊 RSI: `{item['rsi']}`\n   {item['action']}\n")
    lines.append("━━━━━━━━━━━━━━━━━━\nاكتب اسم أي عملة لتحليلها بنظام الـ 4 ساعات والعد الزمني!")
    return '\n'.join(lines)


def _get_blocked_signal(symbol, price, reason, interval='4h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED', 'plan_direction': 'BLOCKED',
        'score': 10, 'entry_score': 10, 'state': f'BLOCKED - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'analysis_lines': [f'🛑 {reason}'], 'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='4h'):
    if normalize_symbol(symbol) == 'TREND_COMMAND':
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
    inv = d.get('interval', '4H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (محرك 4H + درع الأمان الزمني)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (محرك 4H + درع الأمان الزمني)'
    else: emo, text_dir = '🛑', 'BLOCKED'
    
    lines = [
        '🤖 BingX Institutional Suite v44.0 [محرك فريم 4 ساعات والعد الزمني]',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"⏱️ الإطار الزمني الأساسي: {inv} (شمعة ماكرو)",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 القرار النهائي: {emo} {text_dir}",
        f"⭐ Score: {d.get('score', 0)}/100",
        f"\n🧠 الحالة: {d.get('state', '-')}",
        f"📊 RSI: {d.get('rsi', '-')}"
    ]

    if dr != 'BLOCKED':
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '📋 الخطة المؤسسية الكبرى (منتهي الصلاحية بنهاية شمعة 4H)',
            f"\n📍 منطقة الدخول المبكر:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول الفعلي: {d.get('entry_price')}",
            f"\n🎯 TP1 (هدف التأمين): {d.get('tp1')} -> (عند الوصول له ارفع الوقف لـ Break-Even)",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"🚀 الهدف الكلي (Full Range): {d.get('full_range_target')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')} (محمي خلف درع الأمان الماكروني | بنسبة {d.get('sl_pct', 0)}%)",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}",
            f"🛡️ حجم الصفقة الآمن (محفظة 1000$ بمخاطرة 1%): ~{d.get('position_size_usd', 0)}$",
            f"⏳ تنبيه العد الزمني: تُغلق الصفقة أوتوماتيكياً عند اكتمال مدة شمعة الـ 4 ساعات الحالية إذا لم تضرب الأهداف."
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر التداول مؤقتاً.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية وهيكل الماكرو:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
