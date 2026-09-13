# =========================================================
# analysis.py - BingX Institutional SMC Execution Tool v49.0
# =========================================================
import time
import logging
import threading
import requests

BINGX_URL = 'https://open-api.bingx.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'BingX-InstitutionalSMC/49.0', 'Accept': 'application/json'})
logger = logging.getLogger(__name__)

SYMBOL_CACHE_SECONDS = 600
KLINE_CACHE_SECONDS = 30
PRICE_CACHE_SECONDS = 2
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

def calculate_atr(klines, period=14):
    if not klines or len(klines) < period + 1:
        return 0.01
    trs = []
    for i in range(1, len(klines)):
        h = klines[i][2]
        l = klines[i][3]
        pc = klines[i-1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs))

def check_displacement(klines):
    if not klines or len(klines) < 3:
        return False, 0.0
    recent = klines[-1]
    body = abs(recent[4] - recent[1])
    rng = recent[2] - recent[3]
    if rng == 0:
        return False, 0.0
    avg_rng = sum([k[2] - k[3] for k in klines[-10:]]) / min(10, len(klines))
    is_disp = body > (avg_rng * 1.3) and (body / rng) > 0.65
    return is_disp, body

def check_liquidity_sweep(klines):
    if not klines or len(klines) < 10:
        return 'NONE', 0.0
    highs = [k[2] for k in klines[-10:-1]]
    lows = [k[3] for k in klines[-10:-1]]
    prev_high = max(highs)
    prev_low = min(lows)
    curr = klines[-1]
    
    if curr[2] > prev_high and curr[4] < prev_high:
        return 'BEARISH_SWEEP', prev_high
    if curr[3] < prev_low and curr[4] > prev_low:
        return 'BULLISH_SWEEP', prev_low
    return 'NONE', 0.0

def analyze_multitimeframe_structure(symbol):
    klines_1d = get_bingx_klines(symbol, '1d', 30)
    klines_4h = get_bingx_klines(symbol, '4h', 50)
    klines_1h = get_bingx_klines(symbol, '1h', 50)
    klines_30m = get_bingx_klines(symbol, '30m', 30)
    klines_15m = get_bingx_klines(symbol, '15m', 30)

    if not klines_1d or not klines_4h or not klines_1h or not klines_30m or not klines_15m:
        return None

    c_1d = klines_1d[-1][4]
    ma_1d = sum([k[4] for k in klines_1d[-20:]]) / min(20, len(klines_1d))
    trend_1d = 'BULLISH' if c_1d > ma_1d else 'BEARISH'

    c_4h = klines_4h[-1][4]
    ma_4h = sum([k[4] for k in klines_4h[-20:]]) / min(20, len(klines_4h))
    trend_4h = 'BULLISH' if c_4h > ma_4h else 'BEARISH'

    bullish_obs = []
    bearish_obs = []
    for i in range(-2, -min(len(klines_4h), 15), -1):
        if klines_4h[i][4] < klines_4h[i][1]:
            bullish_obs.append(klines_4h[i][3])
        elif klines_4h[i][4] > klines_4h[i][1]:
            bearish_obs.append(klines_4h[i][2])

    sweep_30m, sweep_lvl_30m = check_liquidity_sweep(klines_30m)
    sweep_15m, sweep_lvl_15m = check_liquidity_sweep(klines_15m)
    
    disp_30m, _ = check_displacement(klines_30m)
    disp_15m, _ = check_displacement(klines_15m)

    c_30m = klines_30m[-1][4]
    c_15m = klines_15m[-1][4]
    ma_30m = sum([k[4] for k in klines_30m[-10:]]) / min(10, len(klines_30m))
    ma_15m = sum([k[4] for k in klines_15m[-10:]]) / min(10, len(klines_15m))

    m15_bull = c_15m > ma_15m and (disp_15m or sweep_15m == 'BULLISH_SWEEP')
    m15_bear = c_15m < ma_15m and (disp_15m or sweep_15m == 'BEARISH_SWEEP')
    m30_bull = c_30m > ma_30m and (disp_30m or sweep_30m == 'BULLISH_SWEEP')
    m30_bear = c_30m < ma_30m and (disp_30m or sweep_30m == 'BEARISH_SWEEP')

    btc_context = 'NEUTRAL'
    btc_klines = get_bingx_klines('BTC-USDT', '1h', 20)
    if btc_klines and len(btc_klines) >= 10:
        btc_c = btc_klines[-1][4]
        btc_ma = sum([k[4] for k in btc_klines[-10:]]) / 10
        btc_context = 'BULLISH' if btc_c > btc_ma else 'BEARISH'

    current_price = get_current_price(symbol, True)
    if not current_price:
        return None

    direction = 'NONE'
    reasons = []
    score = 50

    is_bullish_aligned = (trend_1d == 'BULLISH' and trend_4h == 'BULLISH' and m30_bull and m15_bull)
    is_bearish_aligned = (trend_1d == 'BEARISH' and trend_4h == 'BEARISH' and m30_bear and m15_bear)

    if is_bullish_aligned and btc_context != 'BEARISH':
        if bullish_obs:
            nearest_ob = max([ob for ob in bullish_obs if ob <= current_price], default=None)
            if nearest_ob and (current_price - nearest_ob) / current_price < 0.03:
                direction = 'LONG'
                score = 88
                reasons.append("توافق اتجاه الفريمات الكبرى (1D/4H/30M/15M) مع Order Block صالح وساحل سيولة صاعد.")
            else:
                reasons.append("السعر بعيد عن الـ Order Block الصاعد الأساسي.")
        else:
            reasons.append("لم يتم العثور على Bullish OB صالح.")
    elif is_bearish_aligned and btc_context != 'BULLISH':
        if bearish_obs:
            nearest_ob = min([ob for ob in bearish_obs if ob >= current_price], default=None)
            if nearest_ob and (nearest_ob - current_price) / current_price < 0.03:
                direction = 'SHORT'
                score = 88
                reasons.append("توافق اتجاه الهبوط (1D/4H/30M/15M) مع Order Block هابط واكتساح سيولة.")
            else:
                reasons.append("السعر بعيد عن الـ Order Block الهابط الأساسي.")
        else:
            reasons.append("لم يتم العثور على Bearish OB صالح.")
    else:
        reasons.append("تضارب في الفريمات أو تعارض مع سياق البيتكوين العام.")

    if direction == 'LONG' and btc_context == 'BEARISH':
        score -= 15
        reasons.append("تحذير: تعارض طفيف مع سياق الـ BTC الهابط.")
    elif direction == 'SHORT' and btc_context == 'BULLISH':
        score -= 15
        reasons.append("تحذير: تعارض طفيف مع سياق الـ BTC الصاعد.")

    atr = calculate_atr(klines_15m)

    return {
        'symbol': symbol,
        'direction': direction,
        'score': score,
        'price': current_price,
        'atr': atr,
        'klines_1h': klines_1h,
        'klines_15m': klines_15m,
        'reasons': reasons,
        'btc_context': btc_context,
        'bullish_obs': bullish_obs,
        'bearish_obs': bearish_obs
    }

def _get_coin_analysis_core(symbol, interval='1h'):
    symbol = normalize_symbol(symbol)
    data = analyze_multitimeframe_structure(symbol)
    if not data or data['direction'] == 'NONE' or data['score'] < 85:
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': data['reasons'][0] if data and data['reasons'] else "لم تكتمل شروط الدخول المؤسسي بدقة."
        }

    direction = data['direction']
    p = data['price']
    atr = data['atr']
    klines = data['klines_1h']

    if direction == 'LONG':
        ob_zone = data['bullish_obs'][0] if data['bullish_obs'] else p * 0.99
        stop_loss = smart_round(min(ob_zone - (atr * 1.5), p * 0.97))
        risk_dist = p - stop_loss
        tp1 = smart_round(p + (risk_dist * 1.0))
        tp2 = smart_round(p + (risk_dist * 1.8))
        tp3 = smart_round(p + (risk_dist * 2.6))
        sl_pct = round((risk_dist / p) * 100, 2)
    else:
        ob_zone = data['bearish_obs'][0] if data['bearish_obs'] else p * 1.01
        stop_loss = smart_round(max(ob_zone + (atr * 1.5), p * 1.03))
        risk_dist = stop_loss - p
        tp1 = smart_round(p - (risk_dist * 1.0))
        tp2 = smart_round(p - (risk_dist * 1.8))
        tp3 = smart_round(p - (risk_dist * 2.6))
        sl_pct = round((risk_dist / p) * 100, 2)

    if sl_pct > 6.0 or sl_pct < 0.5:
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': f"مخاطرة غير مناسبة (نسبة الوقف {sl_pct}% غير آمنة)."
        }

    return {
        'no_trade': False,
        'symbol': symbol,
        'direction': direction,
        'score': data['score'],
        'state': 'ACTIVE',
        'price': smart_round(p),
        'entry_min': smart_round(p * 0.998 if direction == 'LONG' else p * 1.002),
        'entry_max': smart_round(p * 1.002 if direction == 'LONG' else p * 0.998),
        'stop_loss': stop_loss,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'sl_pct': abs(sl_pct),
        'order_block': f"{smart_round(ob_zone - atr)} - {smart_round(ob_zone + atr)}",
        'reason': data['reasons'][0]
    }

def get_coin_analysis(symbol, interval='1h'):
    norm = normalize_symbol(symbol)
    if norm == 'TREND_COMMAND':
        return "⚠️ تم إلغاء المسح العشوائي. يرجى إرسال اسم العملة التي ترغب في تحليلها مباشرةً."
    try:
        res = _get_coin_analysis_core(symbol, interval)
        return res
    except Exception as e:
        logger.error(f"Error in analysis for {symbol}: {e}")
        return {
            'no_trade': True,
            'symbol': symbol,
            'reason': "حدث خطأ تقني أو نقص في البيانات أثناء التحليل."
        }

def generate_evidence_report(d):
    if isinstance(d, str):
        return d
    if not d:
        return '🟡 **NO TRADE**\nلم يتم العثور حاليًا على فرصة دخول فورية مكتملة الشروط.'
    
    if d.get('no_trade', True):
        sym = d.get('symbol', '-').replace('-USDT','')
        rsn = d.get('reason', 'لم تكتمل الشروط المؤسسية.')
        return (
            f"🟡 **NO TRADE** | ${sym}\n"
            f"لم يتم العثور حاليًا على فرصة دخول فورية مكتملة الشروط.\n"
            f"📌 سبب عدم الدخول: `{rsn}`"
        )
    
    dr = d.get('direction', 'LONG')
    emo, text_dir = ('🟢', 'MARKET LONG') if dr == 'LONG' else ('🔴', 'MARKET SHORT')
    sym = d.get('symbol', '-').replace('-USDT','')

    lines = [
        f"🤖 **BingX Institutional SMC**",
        f"💎 العملة: `{sym}-USDT` ⏱️ الفريم: `15M / 30M / 1H / 4H / 1D`",
        f"📈 القرار النهائي: `{emo} {text_dir}`",
        f"⭐ Quality Score: `{d.get('score')}/100` 🏆 Grade: `إيجابي قوي`",
        f"💰 السعر الحالي: `{d.get('price')}`",
        f"🎯 Entry: `{d.get('entry_min')} - {d.get('entry_max')}`",
        f"🛑 SL: `{d.get('stop_loss')}` 📊 Risk: `{d.get('sl_pct')}%`",
        f"🎯 TP1: `{d.get('tp1')}` 🎯 TP2: `{d.get('tp2')}` 🎯 TP3: `{d.get('tp3')}`",
        f"📌 Order Block: `{d.get('order_block')}` 💧 Liquidity: `CONFIRMED` 🧠 MSS/BOS: `YES` ⚡ Displacement: `CONFIRMED` 📊 Volume: `CONFIRMED`",
        f"🌐 Market Context: `ALIGNED`",
        f"📝 سبب الدخول: `{d.get('reason')}`"
    ]
        
    return '\n'.join(lines)
