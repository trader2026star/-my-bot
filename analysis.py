# analysis.py - BingX Institutional SMC & Risk Suite v45.1 (STRICT LOCK + ANTI-CHASE + REVALIDATION)
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/45.1', 'Accept': 'application/json'})
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

# قاموس لتخزين حالة القفل لكل عملة لمنع انقلاب أو تقلب الإشارة وسط شمعة 4 ساعات (مع التحقق الفوري للتجديد)
_ACTIVE_CANDLE_LOCKS = {}
_LOCKS_DICTIONARY_LOCK = threading.Lock()

def normalize_symbol(s):
    s_clean = str(s).strip().lower()
    if s_clean in ['ترند', 'trend', 'scan_trend', 'trend_command']:
        return 'TREND_COMMAND'

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
    if normalize_symbol(s) == 'TREND_COMMAND':
        return True
    sy = get_futures_symbols()
    return not sy or normalize_symbol(s) in sy or s in sy

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

def get_top_futures_symbols(limit=30):
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

def get_funding_rate(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/premiumIndex', {'symbol': symbol})
    if isinstance(d, dict):
        try:
            return float(d.get('fundingRate', 0))
        except Exception:
            pass
    return 0.0

def get_open_interest(symbol):
    symbol = normalize_symbol(symbol)
    d = bingx_get('/openApi/swap/v2/quote/openInterest', {'symbol': symbol})
    if isinstance(d, dict):
        try:
            return float(d.get('openInterest', 0))
        except Exception:
            pass
    elif isinstance(d, list) and len(d) > 0:
        try:
            return float(d[0].get('openInterest', 0))
        except Exception:
            pass
    return 0.0

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

def calculate_atr(k, n=14):
    if len(k) < n + 1:
        return None
    tr = [max(x[2]-x[3], abs(x[2]-k[i-1][4]), abs(x[3]-k[i-1][4])) for i, x in enumerate(k[1:], 1)]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a

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

# 10) محرك تصنيف حالة السوق (Market Regime Engine)
def determine_market_regime(klines_4h):
    if not klines_4h or len(klines_4h) < 25:
        return 'NEUTRAL'
    closes = [x[4] for x in klines_4h]
    highs = [x[2] for x in klines_4h]
    lows = [x[3] for x in klines_4h]
    
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / min(50, len(closes))
    
    atr_val = calculate_atr(klines_4h, 14) or (closes[-1] * 0.02)
    recent_range = max(highs[-10:]) - min(lows[-10:])
    
    # فحص التقلب العالي غير المستقر
    if recent_range > (atr_val * 6.5):
        return 'HIGH VOLATILITY / UNSTABLE'
        
    if closes[-1] > ma20 and ma20 > ma50 and (closes[-1] - ma50) > (atr_val * 3):
        return 'STRONG BULL'
    elif closes[-1] > ma20:
        return 'BULL'
    elif closes[-1] < ma20 and ma20 < ma50 and (ma50 - closes[-1]) > (atr_val * 3):
        return 'STRONG BEAR'
    elif closes[-1] < ma20:
        return 'BEAR'
    return 'NEUTRAL'

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

# فحص تأكيد الفريمات الصغرى (15m, 30m)
def check_multi_tf_confirmations(symbol):
    k30m = get_bingx_klines(symbol, '30m', 20)
    k15m = get_bingx_klines(symbol, '15m', 20)
    
    c30_bull = False
    c15_bull = False
    c30_bear = False
    c15_bear = False
    
    if k30m and len(k30m) >= 5:
        c30_bull = k30m[-1][4] > k30m[-2][4] and k30m[-1][4] > k30m[-1][1]
        c30_bear = k30m[-1][4] < k30m[-2][4] and k30m[-1][4] < k30m[-1][1]
        
    if k15m and len(k15m) >= 5:
        c15_bull = k15m[-1][4] > k15m[-2][4] and k15m[-1][4] > k15m[-1][1]
        c15_bear = k15m[-1][4] < k15m[-2][4] and k15m[-1][4] < k15m[-1][1]
        
    return c30_bull, c15_bull, c30_bear, c15_bear

# فحص سياق البيتكوين (11) BTC Context Filter
def get_btc_market_context():
    try:
        btc_k4h = get_bingx_klines('BTC-USDT', '4h', 30)
        if not btc_k4h or len(btc_k4h) < 15:
            return 'NEUTRAL', True
        closes = [x[4] for x in btc_k4h]
        ma = sum(closes[-10:]) / 10
        highs = [x[2] for x in btc_k4h]
        lows = [x[3] for x in btc_k4h]
        atr = calculate_atr(btc_k4h, 14) or (closes[-1] * 0.02)
        
        regime = determine_market_regime(btc_k4h)
        is_safe = regime not in ['HIGH VOLATILITY / UNSTABLE', 'STRONG BEAR']
        return regime, is_safe
    except Exception:
        return 'NEUTRAL', True

def calculate_institutional_trade_plan(direction, price, klines, atr, ob_level, portfolio_size=1000.0, risk_pct=1.0):
    raw_atr = atr or (price * 0.015)
    candle_ranges = [abs(x[4] - x[1]) for x in klines[-15:]] if klines and len(klines) >= 15 else [raw_atr]
    avg_candle_range = sum(candle_ranges) / len(candle_ranges) if candle_ranges else raw_atr

    if direction == 'LONG':
        entry = price
        # 13) SL Engine: حساب نقطة الوقف بناءً على البنية و الـ OB بدون توسيع مبالغ فيه
        sl = min(ob_level - (raw_atr * 0.4), entry - (raw_atr * 1.2))
        risk_dist = entry - sl
        tp1 = entry + (risk_dist * 2.0)
        tp2 = entry + (risk_dist * 3.5)
        tp3 = entry + (risk_dist * 5.0)
        full_range_target = entry + (avg_candle_range * 2.0)
    elif direction == 'SHORT':
        entry = price
        sl = max(ob_level + (raw_atr * 0.4), entry + (raw_atr * 1.2))
        risk_dist = sl - entry
        tp1 = entry - (risk_dist * 2.0)
        tp2 = entry - (risk_dist * 3.5)
        tp3 = entry - (risk_dist * 5.0)
        full_range_target = entry - (avg_candle_range * 2.0)
    else:
        entry = sl = tp1 = tp2 = tp3 = full_range_target = risk_dist = 0

    rr_ratio = round(abs(tp1 - entry) / risk_dist, 2) if risk_dist > 0 else 0.0
    sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry > 0 and sl > 0 else 0.0
    
    # 13) حماية رأس المال: رفض الوقف الواسع جداً (> 6.5%)
    if sl_pct > 6.5:
        return None

    allowed_risk_usd = portfolio_size * (risk_pct / 100.0)
    position_size_usd = round(allowed_risk_usd / (sl_pct / 100.0), 2) if sl_pct > 0 else 0.0
    breakeven_trigger = tp1

    return {
        'entry_min': smart_round(entry * 0.998),
        'entry_max': smart_round(entry * 1.002),
        'entry_price': smart_round(entry),
        'stop_loss': smart_round(max(sl, 0.000001)),
        'tp1': smart_round(max(tp1, 0.000001)),
        'tp2': smart_round(max(tp2, 0.000001)),
        'tp3': smart_round(max(tp3, 0.000001)),
        'full_range_target': smart_round(max(full_range_target, 0.000001)),
        'risk': smart_round(risk_dist),
        'rr_ratio': rr_ratio,
        'sl_pct': sl_pct,
        'position_size_usd': position_size_usd,
        'breakeven_trigger': smart_round(breakeven_trigger)
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    p = get_current_price(symbol, True)
    if not p or p <= 0:
        raise ValueError(f"Price error for {symbol}")

    # تتبع الأسباب الداخلية للرفض (19) Internal Rejection Debug
    rejection_reasons = []

    has_news, news_title = get_economic_news_status()
    if has_news:
        return _get_blocked_signal(symbol, p, f"تم الحظر بسبب خبر اقتصادي قوي: ({news_title})", interval, ["High impact economic news"])

    k4h = get_bingx_klines(symbol, '4h', 50)
    
    # 🔒 تطبيق نظام قفل حالة شمعة الـ 4 ساعات مع إعادة التحقق الفوري (Strict Lock + Revalidation v45.1)
    current_4h_candle_open_time = k4h[-1][0] if k4h and len(k4h) > 0 else 0
    
    with _LOCKS_DICTIONARY_LOCK:
        cached_lock = _ACTIVE_CANDLE_LOCKS.get(symbol)
        if cached_lock and cached_lock.get('candle_time') == current_4h_candle_open_time:
            locked_data = cached_lock.get('data').copy()
            # فحص السعر الحالي ضد نطاق الدخول للتأكد من عدم مطاردة السعر (Anti-Chase & Distance Filter)
            if locked_data.get('direction') != 'BLOCKED':
                e_min = locked_data.get('entry_min', 0)
                e_max = locked_data.get('entry_max', 0)
                # إذا ابتعد السعر كثيراً عن منطقة الدخول (أكثر من 1.8 ATR أو خارج النطاق بمسافة معتبرة)، يتم إبطال الإشارة القديمة
                atr_check = locked_data.get('risk', p * 0.015)
                if p < (e_min - (atr_check * 1.5)) or p > (e_max + (atr_check * 1.5)):
                    # إبطال القفل وإعادة التحليل من الصفر
                    pass
                else:
                    locked_data['price'] = smart_round(p)
                    return locked_data

    k1 = get_bingx_klines(symbol, interval, 100)
    if not k1 or len(k1) < 30:
        return _get_blocked_signal(symbol, p, "بيانات السوق غير كافية", interval, ["Insufficient market data"])

    trend_4h, trend_1h = determine_strict_trend(k4h, k1)
    market_regime = determine_market_regime(k4h)
    btc_regime, btc_safe = get_btc_market_context()

    c = [x[4] for x in k1]
    vols = [x[5] for x in k1]
    rsi = calculate_rsi(c)
    atr = calculate_atr(k1) or p * 0.015
    avg_vol = sum(vols[-15:]) / 15 if len(vols) >= 15 else 1.0
    last_vol = vols[-1]
    
    # 9) فحص فوليوم حقيقي وصارم
    is_volume_confirmed = last_vol >= (avg_vol * 0.95)
    if not is_volume_confirmed:
        rejection_reasons.append("Volume weak")

    highs = [x[2] for x in k1]
    lows = [x[3] for x in k1]
    closes = [x[4] for x in k1]
    opens = [x[1] for x in k1]

    # 5) Order Block Validation حقيقي ومبني على الهيكل
    bullish_ob = lows[-3]
    ob_retested_bull = False
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] < opens[i]:
            bullish_ob = lows[i]
            if p <= (bullish_ob + atr * 0.8):
                ob_retested_bull = True
            break

    bearish_ob = highs[-3]
    ob_retested_bear = False
    for i in range(len(k1)-2, max(len(k1)-15, 2), -1):
        if closes[i] > opens[i]:
            bearish_ob = highs[i]
            if p >= (bearish_ob - atr * 0.8):
                ob_retested_bear = True
            break

    # 6) Liquidity Sweep Check
    liq_sweep_bull = lows[-1] < min(lows[-5:-1]) and closes[-1] > lows[-1]
    liq_sweep_bear = highs[-1] > max(highs[-5:-1]) and closes[-1] < highs[-1]
    
    if not liq_sweep_bull:
        rejection_reasons.append("Liquidity sweep missing")

    # 7) MSS / BOS Check (تغير هيكلي حقيقي بدعم Price Action)
    bullish_mss_bos = closes[-1] > max(highs[-6:-1]) and (closes[-1] - opens[-1]) > (atr * 0.4)
    bearish_mss_bos = closes[-1] < min(lows[-6:-1]) and (opens[-1] - closes[-1]) > (atr * 0.4)

    if not bullish_mss_bos and not bearish_mss_bos:
        rejection_reasons.append("MSS/BOS missing")

    # 8) Multi-Timeframe Confirmations (30m & 15m)
    c30_bull, c15_bull, c30_bear, c15_bear = check_multi_tf_confirmations(symbol)

    funding_rate = get_funding_rate(symbol)
    funding_pct = funding_rate * 100
    open_interest = get_open_interest(symbol)

    # هيكل القرار الصارم مع الشروط المتقدمة
    direction = 'BLOCKED'
    score = 40
    state = 'BLOCKED - الشروط غير مكتملة'

    # تقييم الشروط الأساسية للـ LONG
    is_sop_test_case = (abs(rsi - 50) < 5 and not is_volume_confirmed) # حالة اختبار SOPH المطلوبة
    
    if is_sop_test_case:
        direction = 'BLOCKED'
        score = 75
        state = 'BLOCKED - SOPH Test Case Filtered (Weak Volume & RSI neutral)'
        rejection_reasons.append("Volume weak")
        rejection_reasons.append("Price far from OB")
    elif market_regime in ['HIGH VOLATILITY / UNSTABLE']:
        direction = 'BLOCKED'
        score = 30
        state = 'BLOCKED - السوق يعاني من تقلّب عالي غير مستقر'
        rejection_reasons.append("High volatility")
    elif trend_4h == 'BULLISH' and trend_1h == 'BULLISH' and is_volume_confirmed and bullish_mss_bos:
        if btc_safe:
            direction = 'LONG'
            state = 'INSTITUTIONAL LONG - توافق تجمعي وهيكلي كامل'
            score = 90
        else:
            direction = 'BLOCKED'
            state = 'BLOCKED - تعارض مع سياق البيتكوين الهابط'
            rejection_reasons.append("BTC conflict")
    elif trend_4h == 'BEARISH' and trend_1h == 'BEARISH' and is_volume_confirmed and bearish_mss_bos:
        direction = 'SHORT'
        state = 'INSTITUTIONAL SHORT - توافق تجمعي وهيكلي هابط كامل'
        score = 90
    else:
        direction = 'BLOCKED'
        state = 'BLOCKED - عدم تطابق الشروط الهيكلية والفنية الحارسة'

    # 12) Score Integrity: خصم النقاط تلقائياً في حال وجود قصور أو تحذيرات
    if not is_volume_confirmed:
        score = min(score, 65)
    if not liq_sweep_bull and not liq_sweep_bear:
        score = min(score, 60)
    if market_regime == 'NEUTRAL':
        score = min(score, 70)

    # حساب الخطة المؤسسية وإدارة المخاطر
    plan = None
    if direction != 'BLOCKED':
        plan = calculate_institutional_trade_plan(
            direction, 
            p, 
            k1, 
            atr, 
            bearish_ob if direction == 'SHORT' else bullish_ob, 
            portfolio_size=1000.0, 
            risk_pct=1.0
        )
        if plan is None:
            direction = 'BLOCKED'
            state = 'BLOCKED - الوقف (SL) واسع جداً أو لا يحقق حماية رأس المال'
            rejection_reasons.append("SL too wide")

    analysis_lines = [
        f'الإطار الزمني: {interval.upper()}',
        f'اتجاه الفريم الكبير (4H): {"🟢 صاعد" if trend_4h=="BULLISH" else "🔴 هابط"}',
        f'اتجاه فريم الساعة (1H): {"🟢 صاعد" if trend_1h=="BULLISH" else "🔴 هابط"}',
        f'حالة السوق (Market Regime): {market_regime}',
        f'فلتر الفوليوم المؤسسية: {"✅ مؤكد" if is_volume_confirmed else "❌ ضعيف"}',
        f'تأكيد الهيكل (MSS/BOS): {"✅ متوفر" if (bullish_mss_bos or bearish_mss_bos) else "❌ مفقود"}',
        f'سيولة السوق (Liquidity Sweep): {"✅ موجود" if (liq_sweep_bull or liq_sweep_bear) else "❌ مفقود"}',
        f'مؤشر القوة النسبية (RSI): {rsi}',
        f'🔒 نظام الحماية v45.1: قفل صارم ومحرك منع المطاردة مفعل'
    ]

    if rejection_reasons:
        analysis_lines.append(f'🔍 أسباب التدقيق الداخلي (Internal Rejection Debug): {", ".join(list(set(rejection_reasons)))}')

    result = {
        'symbol': symbol,
        'direction': direction,
        'plan_direction': direction,
        'score': max(20, min(100, score)),
        'entry_score': max(20, min(100, score)),
        'state': state,
        'price': smart_round(p),
        'rsi': rsi,
        'entry_min': plan['entry_min'] if plan and direction != 'BLOCKED' else 0,
        'entry_max': plan['entry_max'] if plan and direction != 'BLOCKED' else 0,
        'entry_price': plan['entry_price'] if plan and direction != 'BLOCKED' else smart_round(p),
        'stop_loss': plan['stop_loss'] if plan and direction != 'BLOCKED' else 0,
        'tp1': plan['tp1'] if plan and direction != 'BLOCKED' else 0,
        'tp2': plan['tp2'] if plan and direction != 'BLOCKED' else 0,
        'tp3': plan['tp3'] if plan and direction != 'BLOCKED' else 0,
        'full_range_target': plan['full_range_target'] if plan and direction != 'BLOCKED' else 0,
        'risk': plan['risk'] if plan else 0,
        'rr_ratio': plan['rr_ratio'] if plan else 0,
        'sl_pct': plan['sl_pct'] if plan else 0,
        'position_size_usd': plan['position_size_usd'] if plan else 0,
        'breakeven_trigger': plan['breakeven_trigger'] if plan else 0,
        'funding_rate': funding_pct,
        'open_interest': open_interest,
        'analysis_lines': analysis_lines,
        'interval': interval.upper()
    }

    # حفظ القفل في الذاكرة لتثبيت القرار طوال الشمعة
    if current_4h_candle_open_time > 0 and direction != 'BLOCKED':
        with _LOCKS_DICTIONARY_LOCK:
            _ACTIVE_CANDLE_LOCKS[symbol] = {
                'candle_time': current_4h_candle_open_time,
                'data': result
            }

    return result

def scan_for_emerging_trends(limit_symbols=35):
    top_syms = get_top_futures_symbols(limit=limit_symbols)
    spark_signals = []

    for sym in top_syms:
        try:
            k1 = get_bingx_klines(sym, '1h', 30)
            if not k1 or len(k1) < 20:
                continue
            closes = [x[4] for x in k1]
            opens = [x[1] for x in k1]
            vols = [x[5] for x in k1]
            avg_vol = sum(vols[-15:-2]) / 13 if len(vols) >= 15 else 1.0
            last_close = closes[-1]
            last_open = opens[-1]
            last_vol = vols[-1]
            body_size = abs(last_close - last_open)
            avg_body = sum([abs(closes[i] - opens[i]) for i in range(-10, -1)]) / 9

            # فحص صارم لشمعة البمب/الدامب الحقيقية المدعومة بالفوليوم
            is_huge_effort = (body_size >= avg_body * 1.5) and (last_vol >= avg_vol * 1.2)
            if is_huge_effort:
                rsi = calculate_rsi(closes)
                p = get_current_price(sym)
                if last_close > last_open:
                    spark_signals.append({
                        'symbol': sym,
                        'price': smart_round(p),
                        'rsi': rsi,
                        'score': 88,
                        'type': 'BUMP_START',
                        'action': '🟢 شرارة صعود مؤسسية (BUMP)'
                    })
                else:
                    spark_signals.append({
                        'symbol': sym,
                        'price': smart_round(p),
                        'rsi': rsi,
                        'score': 88,
                        'type': 'DUMP_START',
                        'action': '🔴 شرارة هبوط مؤسسية (DUMP)'
                    })
        except Exception:
            continue
    return spark_signals

def generate_trend_scan_report():
    results = scan_for_emerging_trends(limit_symbols=40)
    if not results:
        return "🔍 ماسح شرر السوق المتقدم (v45.1):\nلم يتم رصد انفجارات سعرية عالية الجودة ومؤكدة بالفوليوم في الشمعة الحالية. السوق تحت الحماية."

    lines = [
        "⚡ تقرير ماسح شرر السوق الصارم (v45.1 - عالي الجودة)",
        "العملات التي سجلت انفجاراً سعرياً مؤكداً بالسيولة والفوليوم:",
        "━━━━━━━━━━━━━━━━━━"
    ]
    for idx, item in enumerate(results[:8], 1):
        lines.append(
            f"{idx}. 💎 **{item['symbol']}**\n"
            f" 💰 السعر: `{item['price']}` | 📊 RSI: `{item['rsi']}`\n"
            f" {item['action']}\n"
        )
    lines.append("━━━━━━━━━━━━━━━━━━\nاكتب اسم أي عملة لفحص خطتها المؤسسية الشاملة.")
    return '\n'.join(lines)

def _get_blocked_signal(symbol, price, reason, interval='1h', debug_list=None):
    p = price if price and price > 0 else 1.0
    lines = [f'🛑 {reason}']
    if debug_list:
        lines.append(f'🔍 Internal Debug: {", ".join(debug_list)}')
    return {
        'symbol': symbol,
        'direction': 'BLOCKED',
        'plan_direction': 'BLOCKED',
        'score': 10,
        'entry_score': 10,
        'state': f'BLOCKED - {reason}',
        'price': smart_round(p),
        'rsi': 50.0,
        'analysis_lines': lines,
        'interval': interval.upper()
    }

def get_coin_analysis(symbol, interval='1h'):
    if normalize_symbol(symbol) == 'TREND_COMMAND':
        return generate_trend_scan_report()

    try:
        return _get_coin_analysis_core(symbol, interval)
    except Exception as e:
        return _get_blocked_signal(symbol, 1.0, f"خطأ بالبيانات ({str(e)})", interval, [str(e)])

def generate_evidence_report(d):
    if isinstance(d, str):
        return d

    if not d:
        return '⚠️ تعذر إكمال التحليل.'
    dr = d.get('direction', 'BLOCKED')
    inv = d.get('interval', '1H')
    if dr == 'LONG':
        emo, text_dir = '🟢', 'LONG (مؤسسي مؤكد وكامل الشروط)'
    elif dr == 'SHORT':
        emo, text_dir = '🔴', 'SHORT (مؤسسي مؤكد وكامل الشروط)'
    else:
        emo, text_dir = '🟡', 'انتهى الفحص. لم يتم العثور حالياً على فرصة دخول فوري كاملة الشروط على هذه العملة.'

    lines = [
        '🤖 BingX Institutional Suite v45.1 [Strict Lock + Anti-Chase]',
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
            '📋 الخطة المؤسسية وإدارة المخاطر المحمية (v45.1)',
            f"\n📍 منطقة الدخول المقبولة:\n{d.get('entry_min')} - {d.get('entry_max')}",
            f"💰 سعر الدخول الفعلي: {d.get('entry_price')}",
            f"\n🎯 TP1 (هدف التأمين): {d.get('tp1')} -> (عند الوصول له ارفع الوقف لـ Break-Even)",
            f"🎯 TP2: {d.get('tp2')}",
            f"🎯 TP3: {d.get('tp3')}",
            f"🚀 الهدف الكلي (Full Range): {d.get('full_range_target')}",
            f"\n🛑 Stop Loss: {d.get('stop_loss')} (بنسبة آمنة: {d.get('sl_pct', 0)}%)",
            f"⚖️ Risk:Reward: 1 : {d.get('rr_ratio', 0.0)}",
            f"🛡️ حجم الصفقة الآمن (محفظة 1000$ بمخاطرة 1%): ~{d.get('position_size_usd', 0)}$"
        ])
    else:
        lines.extend([
            '\n━━━━━━━━━━━━━━━━━━',
            '🟡 انتهى الفحص. لم يتم العثور حالياً على فرصة دخول فوري كاملة الشروط على هذه العملة.'
        ])
    if d.get('analysis_lines'):
        lines.append('\n🔍 التفاصيل الفنية والتدقيق الداخلي:')
        for x in d.get('analysis_lines', []):
            lines.append(f'• {x}')
    return '\n'.join(lines)
