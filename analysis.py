# =========================================================
# analysis.py - BingX Institutional SMC & Risk Suite v41.8
# (مُخصص لاكتشاف قيعان التجميع الحقيقي وفلترة التصريف والفخاخ الخبيثة)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/41.8', 'Accept': 'application/json'})
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


def get_open_interest_history(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v1/market/openInterestHist', {'symbol': symbol, 'period': '1h', 'limit': 5})
    if isinstance(d, list) and len(d) > 0:
        vals = []
        for item in d:
            try:
                vals.append(float(item.get('openInterest', 0)))
            except Exception:
                pass
        return vals
    return []


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


def get_whale_order_book_analysis(symbol, current_price):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/depth', {'symbol': symbol, 'limit': 100})
    if not isinstance(d, dict):
        return {"buy_walls": [], "sell_walls": [], "walls_lines": [], "max_buy_wall_price": 0, "max_buy_wall_val": 0}

    bids = d.get('bids', [])
    asks = d.get('asks', [])

    parsed_bids = []
    for b in bids:
        try:
            p = float(b[0])
            qty = float(b[1])
            usd_val = p * qty
            if p < current_price:
                parsed_bids.append((p, qty, usd_val))
        except Exception:
            pass

    parsed_asks = []
    for a in asks:
        try:
            p = float(a[0])
            qty = float(a[1])
            usd_val = p * qty
            if p > current_price:
                parsed_asks.append((p, qty, usd_val))
        except Exception:
            pass

    parsed_bids.sort(key=lambda x: x[2], reverse=True)
    parsed_asks.sort(key=lambda x: x[2], reverse=True)

    top_bids = parsed_bids[:3]
    top_asks = parsed_asks[:3]

    max_buy_p = top_bids[0][0] if top_bids else 0
    max_buy_val = top_bids[0][2] if top_bids else 0

    walls_summary = []
    for p, q, val in top_asks:
        walls_summary.append(f"🔴 جدار بيع (مقاومة حيتان): السعر `{smart_round(p)}` | القيمة: `${val:,.0f}`")
    for p, q, val in top_bids:
        walls_summary.append(f"🟢 جدار شراء (دعم حيتان قوي في القاع): السعر `{smart_round(p)}` | القيمة: `${val:,.0f}`")

    return {
        'buy_walls': top_bids,
        'sell_walls': top_asks,
        'walls_lines': walls_summary,
        'max_buy_wall_price': max_buy_p,
        'max_buy_wall_val': max_buy_val
    }


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
    if len(k) < n + 1: None
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


def calculate_institutional_trade_plan(direction, price, klines, atr, support_wall_price, portfolio_size=1000.0, risk_pct=1.0):
    raw_atr = atr or (price * 0.015)
    candle_ranges = [abs(x[4] - x[1]) for x in klines[-15:]] if klines and len(klines) >= 15 else [raw_atr]
    avg_candle_range = sum(candle_ranges) / len(candle_ranges) if candle_ranges else raw_atr

    if direction == 'LONG':
        entry = price
        sl = support_wall_price if (support_wall_price > 0 and support_wall_price < entry) else min(entry - (raw_atr * 1.5), entry * 0.97)
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 2.0)
        tp2 = entry + (risk_dist * 3.5)
        tp3 = entry + (risk_dist * 5.0)
        full_range_target = entry + (avg_candle_range * 2.2)
    else:
        entry = price
        sl = entry + (raw_atr * 1.5)
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 2.0)
        tp2 = entry - (risk_dist * 3.5)
        tp3 = entry - (risk_dist * 5.0)
        full_range_target = entry - (avg_candle_range * 2.2)

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

    c = [x[4] for x in k1]
    vols = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    # فحوصات الأوبن بوك وتجميع الحيتان
    whale_data = get_whale_order_book_analysis(symbol, p)
    max_buy_wall_val = whale_data.get('max_buy_wall_val', 0)
    max_buy_wall_price = whale_data.get('max_buy_wall_price', 0)

    # فلتر كشف التصريف (هل العقود المفتوحة تهبط بشراسة مع السعر؟)
    oi_history = get_open_interest_history(symbol)
    is_distribution = False
    if len(oi_history) >= 3:
        # إذا كانت العقود المفتوحة تنخفض بوضوح خلال آخر الشموع والسعر ينزل -> تصريف حقيقي (خبيث)
        if oi_history[-1] < oi_history[-2] < oi_history[-3] and c[-1] < c[-2]:
            is_distribution = True

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    open_interest = get_open_interest(symbol)

    # إذا تم كشف تصريف حقيقي، البوت يحظر الصفقة فوراً لحمايتك من الفخ
    if is_distribution:
        return _get_blocked_signal(symbol, p, "تحذير: تم رصد تصريف حقيقي وهروب رؤوس الأموال (فخ هبوطي خبيث)", interval)

    has_giant_buy_wall = max_buy_wall_val >= 500000

    if has_giant_buy_wall:
        direction = 'LONG'
        state = '🐳 REAL ACCUMULATION LONG - تجميع حقيقي مؤكد ودعم حيتان قوي في القاع'
        score = 92
    elif rsi < 35:
        direction = 'LONG'
        state = '🟢 OVERSOLD LONG - تشبع بيعي نظيف وإمكانية ارتداد'
        score = 80
    else:
        direction = 'SHORT'
        state = 'INSTITUTIONAL SHORT - ضغط هابط مستمر'
        score = 75

    plan = calculate_institutional_trade_plan(direction, p, k1, atr, max_buy_wall_price, portfolio_size=1000.0, risk_pct=1.0)

    low_range_100 = min([x[3] for x in k1[-24:]])
    high_range_100 = max([x[2] for x in k1[-24:]])
    
    narrative_summary = (
        f"رصد السوق تحرك السعر بين قاع `{smart_round(low_range_100)}` وقمة `{smart_round(high_range_100)}`. "
        f"{'التدفق النقدي والعقود المفتوحة تؤكد وجود تجميع حقيقي ودفاع من الحيتان.' if has_giant_buy_wall else 'الحركة تخضع للمراقبة.'}"
    )

    analysis_lines = [
        f'📖 القصة السعرية وفلتر كشف التصريف: {narrative_summary}',
        f'الإطار الزمني: {interval.upper()}',
        f'فلتر كشف التصريف (Distribution): {"🟢 آمن (لا يوجد تصريف خبيث)" if not is_distribution else "🛑 خطر (تصريف حقيقي)"}',
        f'فلتر جدران الحيتان: {"✅ جدار شراء قوي محمي" if has_giant_buy_wall else "⚠️ عادي"}',
        f'العقود المفتوحة (OI): {open_interest:,.2f}',
        f'معدل التمويل (Funding): {funding_pct:.4f}%',
        f'مؤشر القوة النسبية (RSI): {rsi}'
    ]

    if whale_data.get('walls_lines'):
        analysis_lines.append('--- خريطة جدران الحيتان (Whale Walls) ---')
        analysis_lines.extend(whale_data['walls_lines'])

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
            k1 = get_bingx_klines(sym, '1h', 20)
            if not k1 or len(k1) < 15: continue
            p = get_current_price(sym)
            whale_data = get_whale_order_book_analysis(sym, p)
            if whale_data.get('max_buy_wall_val', 0) >= 800000:
                rsi = calculate_rsi([x[4] for x in k1])
                spark_signals.append({'symbol': sym, 'price': smart_round(p), 'rsi': rsi, 'score': 95, 'action': '🟢 قاع تجميع حقيقي مؤكد'})
        except Exception:
            continue
    return spark_signals


def generate_trend_scan_report():
    results = scan_for_emerging_trends(limit_symbols=40)
    if not results:
        return "🔍 ماسح قيعان التجميع الحقيقي (v41.8):\nلا توجد فرص تجميع خالية من التصريف حالياً."

    lines = [
        "🛡️ تقرير ماسح قيعان الحيتان وكشف التصريف (v41.8)",
        "العملات التي أثبتت خلوها من التصريف ووجود تجميع حقيقي:",
        "━━━━━━━━━━━━━━━━━━"
    ]
    for idx, item in enumerate(results[:10], 1):
        lines.append(f"{idx}. 💎 **{item['symbol']}**\n   💰 السعر: `{item['price']}` | 📊 RSI: `{item['rsi']}`\n   {item['action']}\n")
    lines.append("━━━━━━━━━━━━━━━━━━\nاكتب اسم أي عملة لفحصها بالكامل!")
    return '\n'.join(lines)


def _get_blocked_signal(symbol, price, reason, interval='1h'):
    p = price if price and price > 0 else 1.0
    return {
        'symbol': symbol, 'direction': 'BLOCKED', 'plan_direction': 'BLOCKED',
        'score': 10, 'entry_score': 10, 'state': f'BLOCKED - {reason}',
        'price': smart_round(p), 'rsi': 50.0, 'analysis_lines': [f'🛑 {reason}'], 'interval': interval.upper()
    }


def get_coin_analysis(symbol, interval='1h'):
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
    inv = d.get('interval', '1H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (تجميع حقيقي خالٍ من التصريف)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT'
    else: emo, text_dir = '🛑', 'BLOCKED (محمي من التصريف والفخاخ)'
    
    lines = [
        '🤖 BingX Institutional Suite v41.8 [مضاد التصريف]',
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
            '📋 الخطة المؤسسية المصفاة وإدارة المخاطر',
            f"\n📍 منطقة الدخول المبكر:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول الفعلي: {d.get('entry_price')}",
            f"\n🎯 TP1 (هدف التأمين): {d.get('tp1')} -> (عند الوصول له ارفع الوقف لـ Break-Even)",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"🚀 الهدف الكلي (Full Range): {d.get('full_range_target')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')} (محمي تحت جدار الحوت | بنسبة {d.get('sl_pct', 0)}%)",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}",
            f"🛡️ حجم الصفقة الآمن (محفظة 1000$ بمخاطرة 1%): ~{d.get('position_size_usd', 0)}$"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر التداول لتجنب فخاخ التصريف.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية وفلتر كشف التصريف:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
