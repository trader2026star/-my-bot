# =========================================================
# analysis.py - BingX Ultra Safe Pure SMC Scanner v33.2 (DCA & Breakeven Enhanced)
# =========================================================

import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-UltraSMC/33.2', 'Accept': 'application/json'})
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
                            event_title = ev.get('title', 'Economic Event')
                            break
                    except Exception:
                        pass
            
            _NEWS_CACHE = (high_impact_near, event_title)
            _NEWS_CACHE_TIME = now
            return _NEWS_CACHE
    except Exception:
        pass
    
    return (False, "لا توجد أخبار قريبة مرصودة")


def get_futures_symbols(force_refresh=False):
    global _SYMBOL_CACHE, _SYMBOL_CACHE_TIME
    if not force_refresh and _SYMBOL_CACHE and time.time()-_SYMBOL_CACHE_TIME < SYMBOL_CACHE_SECONDS:
        return set(_SYMBOL_CACHE)
    d = bingx_get('/openApi/swap/v2/quote/contracts')
    out = set()
    rows = []
    if isinstance(d, dict):
        rows = d.get('contracts', [])
    elif isinstance(d, list):
        rows = d
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


def get_funding_rate(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': symbol})
    if isinstance(d, dict):
        try:
            return float(d.get('fundingRate', 0))
        except Exception:
            pass
    return 0.015


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


def analyze_pure_smc_safe(klines):
    if not klines or len(klines) < 25:
        return 'NEUTRAL', 0, 0, 50

    highs = [x[2] for x in klines]
    lows = [x[3] for x in klines]
    closes = [x[4] for x in klines]
    opens = [x[1] for x in klines]

    swing_high = max(highs[-20:-2])
    swing_low = min(lows[-20:-2])
    current_close = closes[-1]
    prev_close = closes[-2]

    is_violent_dump = (current_close < prev_close) and ((prev_close - current_close) > (closes[-5] - closes[-6] if len(closes)>5 else 0) * 1.5)
    is_violent_pump = (current_close > prev_close) and ((current_close - prev_close) > (closes[-5] - closes[-6] if len(closes)>5 else 0) * 1.5)

    bullish_ob = lows[-3]
    for i in range(len(klines)-2, max(len(klines)-15, 2), -1):
        if closes[i] < opens[i]:
            bullish_ob = lows[i]
            break

    bearish_ob = highs[-3]
    for i in range(len(klines)-2, max(len(klines)-15, 2), -1):
        if closes[i] > opens[i]:
            bearish_ob = highs[i]
            break

    if current_close > swing_high and not is_violent_dump:
        return 'BULLISH', bullish_ob, swing_high, 92
    elif current_close < swing_low and not is_violent_pump:
        return 'BEARISH', bearish_ob, swing_low, 92
    else:
        if is_violent_dump:
            return 'BEARISH', bearish_ob, swing_low, 85
        if current_close > closes[-10]:
            return 'BULLISH', bullish_ob, swing_high, 65
        else:
            return 'BEARISH', bearish_ob, swing_low, 65


def calculate_smc_trade_plan(direction, price, atr, ob_level, rsi=50):
    raw_atr = atr or (price * 0.015)
    if direction == 'LONG':
        entry = price
        sl = min(ob_level - (raw_atr * 0.6), entry - (raw_atr * 1.8))
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 2.0)
        tp2 = entry + (risk_dist * 3.2)
        tp3 = entry + (risk_dist * 4.8)
    elif direction == 'SHORT':
        entry = price
        sl = max(ob_level + (raw_atr * 0.6), entry + (raw_atr * 1.8))
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 2.0)
        tp2 = entry - (risk_dist * 3.2)
        tp3 = entry - (risk_dist * 4.8)
    else:
        entry = sl = tp1 = tp2 = tp3 = risk_dist = 0

    rr_ratio = round(abs(tp1 - entry) / risk_dist, 2) if risk_dist > 0 else 0.0
    
    # دمج نظام الدخول المجزأ (DCA) بناءً على حالة تشبع الـ RSI
    orders = []
    is_dca_active = False
    
    if direction == 'LONG' and rsi > 70:
        is_dca_active = True
        orders = [
            {"label": "DCA 1 (حذر - 30%)", "price": smart_round(entry), "allocation": 30},
            {"label": "DCA 2 (الأوردر بلوك - 70%)", "price": smart_round(max(ob_level, entry * 0.95)), "allocation": 70}
        ]
    elif direction == 'SHORT' and rsi < 30:
        is_dca_active = True
        orders = [
            {"label": "DCA 1 (حذر - 30%)", "price": smart_round(entry), "allocation": 30},
            {"label": "DCA 2 (منطقة العرض - 70%)", "price": smart_round(min(ob_level, entry * 1.05)), "allocation": 70}
        ]
    else:
        orders = [
            {"label": "Standard Entry (100%)", "price": smart_round(entry), "allocation": 100}
        ]

    breakeven_trigger = smart_round(entry + (risk_dist if direction == 'LONG' else -risk_dist))

    return {
        'entry_min': smart_round(entry * 0.998), 'entry_max': smart_round(entry * 1.002),
        'entry_price': smart_round(entry), 'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)), 'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)), 'risk': smart_round(risk_dist), 'rr_ratio': rr_ratio,
        'orders': orders, 'is_dca_active': is_dca_active, 'breakeven_trigger': breakeven_trigger
    }


def monitor_active_position(current_market_price, entry_price, breakeven_trigger, current_sl, direction):
    """مراقبة وتحديث وقف الخسارة لنقطة الدخول فور تحقيق عائد 1:1"""
    try:
        if direction == 'LONG' and current_market_price >= breakeven_trigger and current_sl < entry_price:
            return entry_price
        elif direction == 'SHORT' and current_market_price <= breakeven_trigger and current_sl > entry_price:
            return entry_price
    except Exception:
        pass
    return current_sl


def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0: raise ValueError(f"Price error for {symbol}")

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30: return _get_blocked_signal(symbol, p, "بيانات السوق غير كافية", interval)

    c = [x[4] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015

    smc_trend, ob_level, key_level, smc_score = analyze_pure_smc_safe(k1)

    k4h = get_bingx_klines(symbol, '4h', 50)
    trend_4h, _, _, _ = analyze_pure_smc_safe(k4h) if k4h and len(k4h) >= 20 else ('NEUTRAL', 0, 0, 50)

    btc_k = get_bingx_klines('BTC-USDT', '1h', 20)
    btc_stable = True
    if btc_k and len(btc_k) >= 5:
        btc_change = (btc_k[-1][4] - btc_k[-5][4]) / btc_k[-5][4]
        if btc_change < -0.025:
            btc_stable = False

    has_news, news_title = get_economic_news_status()
    last_candle_red = k1[-1][4] < k1[-1][1]

    if smc_trend == 'BULLISH' and rsi < 78 and not (last_candle_red and (k1[-1][2] - k1[-1][3]) > atr * 1.2):
        direction = 'LONG'
        state = 'SAFE SMC LONG - ارتداد مؤكد من أوردر بلوك سيولة'
        score = smc_score
    elif smc_trend == 'BEARISH' and rsi > 22:
        direction = 'SHORT'
        state = 'SAFE SMC SHORT - هبوط مؤكد من منطقة عرض'
        score = smc_score
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - تذبذب لحظي أو شمعة انعكاسية عنيفة'
        score = 30

    if direction == 'LONG' and trend_4h == 'BEARISH':
        score -= 20
        state = 'WARNING - تعارض مع هيكل فريم 4H'
    elif direction == 'SHORT' and trend_4h == 'BULLISH':
        score -= 20
        state = 'WARNING - تعارض مع هيكل فريم 4H'

    if has_news:
        score -= 25
        state = f'WARNING - خبر اقتصادي هام ({news_title})'

    if score < 72:
        direction = 'BLOCKED'
        state = 'BLOCKED - السوق غير مستقر أو وجود خبر قوي وحماية المحفظة مفعلة'

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100

    plan = calculate_smc_trade_plan(direction if direction != 'BLOCKED' else 'LONG', p, atr, ob_level, rsi)

    analysis_lines = [
        f'الإطار الزمني: {interval.upper()}',
        f'هيكل السوق الآمن: {"🟢 صاعد" if smc_trend=="BULLISH" else "🔴 هابط"}',
        f'نظام الدخول (DCA): {"⚠️ مفعّل (تشبع RSI)" if plan["is_dca_active"] else "✅ قياسي (100% دفعة واحدة)"}',
        f'اتصال البيتكوين (BTC): {"✅ مستقر" if btc_stable else "⚠️ متذبذب أو هابط"}',
        f'فلتر الأخبار الاقتصادية: {"⚠️ تحذير (خبر قوي قريب)" if has_news else "✅ آمن (لا توجد أخبار قوية)"}',
        f'اتجاه فريم 4H: {"🟢 صاعد" if trend_4h=="BULLISH" else "🔴 هابط"}',
        f'منطقة الأوردر بلوك: {smart_round(ob_level)}',
        f'رسوم التمويل: {funding_pct:.4f}%',
        f'مؤشر RSI: {rsi}'
    ]

    return {
        'symbol': symbol, 'direction': direction, 'plan_direction': direction,
        'score': max(10, score), 'entry_score': max(10, score), 'state': state,
        'price': smart_round(p), 'rsi': rsi,
        'entry_min': plan['entry_min'] if direction!='BLOCKED' else 0, 
        'entry_max': plan['entry_max'] if direction!='BLOCKED' else 0,
        'entry_price': plan['entry_price'] if direction!='BLOCKED' else smart_round(p), 
        'stop_loss': plan['stop_loss'] if direction!='BLOCKED' else 0,
        'tp1': plan['tp1'] if direction!='BLOCKED' else 0, 'tp2': plan['tp2'] if direction!='BLOCKED' else 0, 
        'tp3': plan['tp3'] if direction!='BLOCKED' else 0, 'risk': plan['risk'], 'rr_ratio': plan['rr_ratio'], 
        'orders': plan['orders'], 'is_dca_active': plan['is_dca_active'], 'breakeven_trigger': plan['breakeven_trigger'],
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
    except Exception as e:
        return _get_blocked_signal(symbol, 1.0, f"خطأ بالبيانات ({str(e)})", interval)


def get_top_futures_symbols(limit=25):
    rows = _ticker_rows()
    cand = []
    for x in rows:
        try:
            if isinstance(x, dict):
                s = str(x.get('symbol', '')).upper()
                v = float(x.get('volume', x.get('quoteVolume', 0)))
                if s and v > 0:
                    cand.append((s, v))
        except Exception:
            pass
    cand.sort(key=lambda x: x[1], reverse=True)
    out = []
    for x in cand[:limit]:
        sy = normalize_symbol(x[0])
        if sy not in out:
            out.append(sy)
    return out


def generate_evidence_report(d):
    if not d: return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'BLOCKED')
    inv = d.get('interval', '1H')
    
    if dr == 'LONG': emo, text_dir = '🟢', 'LONG (Institutional Safe SMC Buy)'
    elif dr == 'SHORT': emo, text_dir = '🔴', 'SHORT (Institutional Safe SMC Sell)'
    else: emo, text_dir = '🛑', 'BLOCKED (تجنب التذبذب العنيف أو الأخبار)'
    
    lines = [
        '🤖 BingX Ultra Safe SMC Scanner v33.2',
        f"💎 العملة: {d.get('symbol', '-')}",
        f"⏱️ الإطار الزمني: {inv}",
        f"💰 السعر الحالي: {d.get('price', '-')}",
        f"📈 القرار النهائي: {emo} {text_dir}",
        f"⭐ Score: {d.get('score', 0)}/100",
        f"\n🧠 الحالة: {d.get('state', '-')}",
        f"📊 RSI: {d.get('rsi', '-')}"
    ]

    if dr != 'BLOCKED':
        lines.append('\n━━━━━━━━━━━━━━━━━━')
        lines.append('📋 خطة صانع السوق والدخول المجزأ (DCA)')
        
        orders = d.get('orders', [])
        for ord_item in orders:
            lines.append(f"• {ord_item.get('label')}: سعر {ord_item.get('price')} (نسبة: {ord_item.get('allocation')}%)")
            
        lines.extend([
            f"\n🎯 TP1: {d.get('tp1')}",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')}",
            f"🔒 نقطة تفعيل تأمين الصفقة (1:1 Breakeven): {d.get('breakeven_trigger', '-')}",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🛑 تم حظر الدخول لوجود حركة عنيفة، تذبذب، أو خبر اقتصادي قوي.'
        ])
    
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
            
    return '\n'.join(lines)
